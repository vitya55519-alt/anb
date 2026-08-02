from __future__ import annotations

from openai import AsyncOpenAI
from sqlalchemy import select

from config import AI_KEY, AI_MODEL, AI_BASE_URL, CHARACTER_ID
from models.app_models import User
from services.character_service import get_anna, build_system_prompt
from services.db import SessionLocal
from services.memory_service import get_recent_messages, get_memories, save_message, extract_memory
from services.relationship_service import record_user_message
from services.relationship_signals import infer_delta
from services.test_mode import get_stage as get_test_stage
from services.relationship_engine import build_relationship_context

client = AsyncOpenAI(api_key=AI_KEY, base_url=AI_BASE_URL)


def ensure_user(telegram_id: int, user_name: str | None = None) -> int:
    """Create the canonical service user and return its DB id."""
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            user = User(telegram_id=str(telegram_id), name=user_name or "")
            s.add(user)
            s.flush()
        elif user_name:
            user.name = user_name
        s.commit()
        return user.id


async def reply(user_id: int, user_name: str, user_text: str) -> str:
    db_user_id = ensure_user(user_id, user_name)
    delta = infer_delta(user_text)
    test_stage = get_test_stage(user_id)

    if test_stage:
        relationship_context = (
            f"Сейчас моделируй Анну на стадии {test_stage}. "
            "Это внутренний режим проверки: реальные баллы отношений не меняй и "
            "не раскрывай пользователю существование тестового режима."
        )
    else:
        relationship_context = await record_user_message(
            user_id, user_name,
            relationship=delta.relationship,
            trust=delta.trust,
            intimacy=delta.intimacy,
            event_type=delta.event_type,
            reason=delta.reason,
        )

    character = get_anna()
    memories = get_memories(db_user_id, CHARACTER_ID, 20)
    history = get_recent_messages(db_user_id, CHARACTER_ID, 20)
    messages = [{
        "role": "system",
        "content": build_system_prompt(
            character,
            relationship_context,
            [m.content for m in memories],
        ),
    }]
    messages += [{"role": m.role, "content": m.content} for m in history]
    messages.append({"role": "user", "content": user_text})

    r = await client.chat.completions.create(
        model=AI_MODEL,
        messages=messages,
        temperature=0.92,
        max_tokens=450,
    )
    answer = (r.choices[0].message.content or "хм… я немного задумалась 🙈").strip()

    save_message(db_user_id, CHARACTER_ID, "user", user_text)
    save_message(db_user_id, CHARACTER_ID, "assistant", answer)
    await extract_memory(db_user_id, CHARACTER_ID, user_text)
    return answer


async def proactive_reply(user_id: int, user_name: str, hours_inactive: int) -> str:
    """Generate a proactive Anna message using the same personality/memory stack."""
    db_user_id = ensure_user(user_id, user_name)
    character = get_anna()
    memories = get_memories(db_user_id, CHARACTER_ID, 12)
    history = get_recent_messages(db_user_id, CHARACTER_ID, 8)
    relationship_context = await _relationship_context_for_user(db_user_id)

    system = build_system_prompt(
        character,
        relationship_context,
        [m.content for m in memories],
    ) + f"\n\nАнна не получала сообщений около {hours_inactive} часов. Можешь сама написать первой. Не обязательно задавать вопрос. Сообщение должно ощущаться спонтанным, личным и коротким. Не говори, что ты проверяешь активность пользователя."

    messages = [{"role": "system", "content": system}]
    messages += [{"role": m.role, "content": m.content} for m in history]
    messages.append({"role": "user", "content": "Напиши одно естественное сообщение первой. Только текст сообщения."})

    r = await client.chat.completions.create(
        model=AI_MODEL,
        messages=messages,
        temperature=1.05,
        max_tokens=160,
    )
    answer = (r.choices[0].message.content or "эй… ты там не потерялся? 😌").strip()
    save_message(db_user_id, CHARACTER_ID, "assistant", answer)
    return answer


async def _relationship_context_for_user(db_user_id: int) -> str:
    from services.relationship_engine import get_state
    with SessionLocal() as s:
        row = get_state(s, db_user_id, CHARACTER_ID)
        return build_relationship_context(row)
