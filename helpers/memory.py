import asyncio
import json
import logging
import openai
from openai import AsyncOpenAI
from config import AI_KEY, AI_MODEL, AI_BASE_URL

logger = logging.getLogger(__name__)
client = AsyncOpenAI(api_key=AI_KEY, base_url=AI_BASE_URL)
SUMMARIZE_THRESHOLD = 100
KEEP_RECENT = 50

async def maybe_summarize(user_id: int, waifu_name: str, user_name: str):
    from .db_interaction import count_chat_log_user, get_oldest_chat_logs, save_memory_summary, delete_chat_logs_before_id
    count = await asyncio.to_thread(count_chat_log_user, user_id)
    if count <= SUMMARIZE_THRESHOLD:
        return
    to_summarize = count - KEEP_RECENT
    oldest = await asyncio.to_thread(get_oldest_chat_logs, user_id, to_summarize)
    if not oldest:
        return
    convo_lines = []
    for text, _, _ in oldest:
        try:
            entry = json.loads(text)
            role = waifu_name if entry.get("role") == "assistant" else user_name
            convo_lines.append(f"{role}: {entry.get('content', '')}")
        except Exception:
            continue
    try:
        response = await client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": "Resume una conversación para memoria a largo plazo. Conserva hechos, preferencias, promesas, bromas internas, temas pendientes y contexto emocional. No inventes datos."},
                {"role": "user", "content": f"Resume en 6-10 puntos concretos la conversación entre {waifu_name} y {user_name}:\n\n" + "\n".join(convo_lines)},
            ], temperature=0.2, max_tokens=450,
        )
        summary = response.choices[0].message.content
    except openai.APIError as e:
        logger.error("Failed to generate memory summary for user %s: %s", user_id, e)
        return
    await asyncio.to_thread(save_memory_summary, user_id, summary, oldest[0][2], oldest[-1][2])
    await asyncio.to_thread(delete_chat_logs_before_id, user_id, oldest[-1][1])

async def build_context(user_id: int, system_role: str) -> list:
    from .db_interaction import get_memory_summaries, get_memory_facts, get_chat_log_user, get_character_state
    state = await asyncio.to_thread(get_character_state, user_id)
    facts = await asyncio.to_thread(get_memory_facts, user_id, 30)
    summaries = await asyncio.to_thread(get_memory_summaries, user_id)
    messages = [{"role": "system", "content": system_role}]
    state_text = (
        f"ESTADO ACTUAL DE ANNA: ánimo={state.mood}; energía={state.energy:.2f}; "
        f"cariño={state.affection:.2f}; juego={state.playfulness:.2f}; irritación={state.irritation:.2f}; "
        f"actividad={state.current_activity or 'no definida'}; tema pendiente={state.pending_hook or 'ninguno'}; "
        f"idioma={state.language}; zona horaria={state.timezone}."
    )
    messages.append({"role": "system", "content": state_text})
    if facts:
        messages.append({"role": "system", "content": "RECUERDOS IMPORTANTES (úsalos solo cuando sean pertinentes):\n" + "\n".join(f"- [{c}] {f}" for c, f, _ in facts)})
    if summaries:
        messages.append({"role": "system", "content": "RESÚMENES DE HISTORIA COMPARTIDA:\n" + "\n".join(f"- {s}" for s in summaries[-8:])})
    chat_log = await asyncio.to_thread(get_chat_log_user, user_id, KEEP_RECENT)
    for log in chat_log:
        try:
            messages.append(json.loads(log[0]))
        except Exception:
            pass
    return messages
