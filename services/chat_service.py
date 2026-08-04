from __future__ import annotations
import re
from openai import AsyncOpenAI
from config import AI_KEY, AI_MODEL, AI_BASE_URL, CHARACTER_ID
from services.character_service import get_anna, build_system_prompt
from services.memory_service import get_recent_messages, get_memories, save_message, extract_memory
from services.relationship_service import record_user_message
from services.relationship_signals import infer_delta
from services.test_mode import get_stage as get_test_stage
from services.behavior_service import behavior_context
from services.state_service import state_context, softly_evolve_state
from services.user_service import ensure_user
from services.access_service import is_premium

client = AsyncOpenAI(api_key=AI_KEY, base_url=AI_BASE_URL)

def _clean(answer: str) -> str:
    answer = (answer or "хм… я зависла на секунду 🙈").strip()
    answer = re.sub(r"^(Конечно|Разумеется|Понимаю тебя)[,!:.\s]+", "", answer, flags=re.I)
    return answer.strip() or "хм… я зависла на секунду 🙈"

async def reply(user_id: int, user_name: str, user_text: str) -> str:
    db_user_id = ensure_user(user_id, user_name)
    delta = infer_delta(user_text)
    test_stage = get_test_stage(user_id)
    if test_stage:
        rel_context = f"Тестовая стадия поведения: {test_stage}. Реальные баллы не меняй и режим тестирования не упоминай."
    else:
        rel_context = await record_user_message(user_id, user_name, relationship=delta.relationship, trust=delta.trust, intimacy=delta.intimacy, event_type=delta.event_type, reason=delta.reason)
    character = get_anna()
    premium = is_premium(user_id)
    memories = get_memories(db_user_id, CHARACTER_ID, 40 if premium else 14)
    history = get_recent_messages(db_user_id, CHARACTER_ID, 30 if premium else 16)
    system = build_system_prompt(character, rel_context, [m.content for m in memories], behavior_context(user_text), state_context(user_id))
    messages = [{"role":"system","content":system}]
    messages += [{"role":m.role,"content":m.content} for m in history]
    messages.append({"role":"user","content":user_text})
    r = await client.chat.completions.create(model=AI_MODEL, messages=messages, temperature=0.95, max_tokens=380)
    answer = _clean(r.choices[0].message.content)
    save_message(db_user_id, CHARACTER_ID, "user", user_text)
    save_message(db_user_id, CHARACTER_ID, "assistant", answer)
    await extract_memory(db_user_id, CHARACTER_ID, user_text)
    softly_evolve_state(user_id, user_text)
    return answer

async def proactive_reply(user_id: int, user_name: str, hours_inactive: int) -> str:
    db_user_id = ensure_user(user_id, user_name)
    character = get_anna(); memories = get_memories(db_user_id, CHARACTER_ID, 10); history = get_recent_messages(db_user_id, CHARACTER_ID, 8)
    from services.relationship_service import get_context
    rel_context = await get_context(user_id) or "Отношения только начинаются."
    system = build_system_prompt(character, rel_context, [m.content for m in memories], "Напиши одну короткую спонтанную реплику первой; не обязательно задавать вопрос.", state_context(user_id))
    messages=[{"role":"system","content":system}]+[{"role":m.role,"content":m.content} for m in history]
    messages.append({"role":"user","content":f"Пользователь не писал около {hours_inactive} часов. Напиши естественно первой, не упоминая отслеживание активности."})
    r=await client.chat.completions.create(model=AI_MODEL,messages=messages,temperature=1.05,max_tokens=120)
    answer=_clean(r.choices[0].message.content); save_message(db_user_id, CHARACTER_ID, "assistant", answer); return answer
