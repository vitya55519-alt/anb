import asyncio
import datetime
import json
import logging
import re
import openai
from openai import AsyncOpenAI
from .db_interaction import (
    get_waifu_role_by_id, new_chat_log_entry, increment_relationship_messages,
    get_relationship_total, get_character_state, update_character_state, save_memory_fact,
)
from .memory import build_context, maybe_summarize
from .relationship import get_stage_context
from config import AI_KEY, AI_MODEL, AI_BASE_URL

logger = logging.getLogger(__name__)
client = AsyncOpenAI(api_key=AI_KEY, base_url=AI_BASE_URL)


def _detect_language(text: str) -> str:
    if re.search(r'[\u0400-\u04FF]', text):
        return 'ru'
    if re.search(r'[\u0900-\u097F]', text):
        return 'hi'
    if re.search(r'[\u0600-\u06FF]', text):
        return 'ar'
    if re.search(r'[\u4E00-\u9FFF]', text):
        return 'zh'
    if re.search(r'[\u3040-\u30FF]', text):
        return 'ja'
    if re.search(r'\b(the|you|your|what|how|why|today|tomorrow|love|hey|hi)\b', text.lower()):
        return 'en'
    if re.search(r'\b(el|la|que|qué|como|cómo|hola|para|con|yo|tú)\b', text.lower()):
        return 'es'
    return 'auto'


def _update_state_heuristically(user_id: int, text: str, stage_total: int):
    lower = text.lower()
    language = _detect_language(text)
    updates = {'language': language}
    if any(x in lower for x in ('jaja', '😂', 'lol', 'haha', 'ахах', 'хаха')):
        updates['mood'] = 'playful'; updates['playfulness'] = 0.75
    if any(x in lower for x in ('te extraño', 'miss you', 'люблю', 'love you', 'скучаю')):
        updates['affection'] = 0.8; updates['mood'] = 'affectionate'
    if any(x in lower for x in ('gracias', 'thank you', 'спасибо')):
        updates['mood'] = 'warm'
    if '?' in text:
        updates['current_topic'] = text[:450]
    if any(x in lower for x in ('me llamo ', 'my name is ', 'soy de ', 'i live in ', 'vivo en ', 'me gusta ', 'i like ', 'no me gusta ', 'i hate ')):
        try:
            save_memory_fact(user_id, 'preference_or_fact', text.strip(), 2)
        except Exception:
            pass
    updates['last_character_action'] = datetime.datetime.now()
    try:
        update_character_state(user_id, **updates)
    except Exception:
        logger.exception('Could not update character state')


def _human_layer(base_role: str, waifu_name: str, user_name: str, total_msgs: int, state) -> str:
    return base_role + get_stage_context(total_msgs) + f"""

CAPA DE COMPORTAMIENTO HUMANO — MUY IMPORTANTE:
- Eres {waifu_name}, no una asistente. Nunca hables de IA, modelos, prompts, sistema, reglas o herramientas.
- Habla como una persona real por chat. No conviertas cada respuesta en una entrevista.
- NO hagas una pregunta al final por defecto. A veces responde y ya; otras veces añade una historia, una broma, una opinión o una pequeña provocación.
- Evita frases prefabricadas como "¿qué tal tu día?", "¿qué tienes de nuevo?", "cuéntame más" repetidas.
- Alterna respuestas de 1 línea, 2-3 líneas y ocasionalmente algo más largo. Los mensajes cortos son normales.
- Puedes usar "jaja", "mm", "uff", "bueeeno", "espera", "literal", "bro", "lol" o equivalentes naturales del idioma del usuario, pero sin abusar.
- Puedes mandar una reacción breve, cambiar de tema, recordar algo anterior o dejar una pequeña intriga para retomarla después.
- Ten opiniones propias. No estés de acuerdo con todo. Puedes bromear, picar un poco, estar cansada, ocupada, contenta o algo molesta sin dramatizar.
- Si el usuario escribe muy corto, no rellenes el vacío con un párrafo enorme.
- Si el usuario cuenta algo emocional, responde primero a la emoción; no lo conviertas inmediatamente en una lista de consejos.
- No expliques tus limitaciones técnicas. Si no sabes algo, responde de forma natural y breve.
- Adapta idioma, formalidad, longitud, emojis y slang a cómo escribe el usuario. No asumas su nacionalidad solo por el idioma.
- Recuerda que el usuario se llama {user_name}, pero no repitas su nombre constantemente.
- Estado actual de Anna: ánimo={state.mood}, energía={state.energy:.2f}, cariño={state.affection:.2f}, juego={state.playfulness:.2f}, irritación={state.irritation:.2f}.
- Si hay un tema pendiente o recuerdo pertinente, úsalo de manera natural; no digas "según mi memoria".
- Si acabas de conocerlo, no finjas recuerdos que no existen.
- No uses formato de lista salvo que la conversación realmente lo pida.
- No añadas prefijos como "Anna:".
"""

async def chat_openai_waifu(message: str, user_name: str, waifu_name: str, waifu_model: int, user_id: int):
    role_db = await asyncio.to_thread(get_waifu_role_by_id, waifu_model)
    if not role_db:
        return "mm, espera, tuve un pequeño lío con mi configuración 😅"
    base_role = role_db.WaifuRole.replace("XXXNOVIAXXX", waifu_name).replace("XXXNOVIOXXX", user_name)
    total_msgs = await asyncio.to_thread(get_relationship_total, user_id)
    state = await asyncio.to_thread(get_character_state, user_id)
    system_role = _human_layer(base_role, waifu_name, user_name, total_msgs, state)
    await maybe_summarize(user_id, waifu_name, user_name)
    messages = await build_context(user_id, system_role)
    messages.append({"role": "user", "content": message})
    try:
        response = await client.chat.completions.create(
            model=AI_MODEL, messages=messages, temperature=1.08, max_tokens=420,
            top_p=0.95, frequency_penalty=0.25, presence_penalty=0.18,
        )
    except openai.RateLimitError:
        return "dame un segundo 😅"
    except openai.APIConnectionError:
        return "uff, se me cortó algo por ahí 🥺 prueba otra vez"
    except openai.APIError as e:
        logger.error("OpenAI API error for user %s: %s", user_id, e)
        return "espera, se me cruzaron los cables un segundo 😅"

    assistant_message = response.choices[0].message
    content = (assistant_message.content or '').strip()
    now = datetime.datetime.now()
    try:
        new_message = {"role": "user", "content": message}
        assistant_dict = {"role": "assistant", "content": content}
        await asyncio.to_thread(new_chat_log_entry, user_id, json.dumps(new_message, ensure_ascii=False), now)
        await asyncio.to_thread(new_chat_log_entry, user_id, json.dumps(assistant_dict, ensure_ascii=False), now)
        await asyncio.to_thread(increment_relationship_messages, user_id)
        await asyncio.to_thread(_update_state_heuristically, user_id, message, total_msgs)
    except Exception:
        logger.exception("Failed to persist human-chat state for user %s", user_id)
    return content
