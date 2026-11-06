"""V3.115.0: «📞 Позвонить» — a voice call with her inside the Mini App.

Telegram bots cannot take real calls, so the call lives in the Mini App.
Two kinds of call (Витя, 2026-11-06):

* Premium — «звонок с ней обо всём». He speaks, the app catches the pause,
  the recording goes through the normal chat pipeline (memory, level, 18+
  rules, MiniMax) with a phone-call direction, and her answer comes back in
  her own voice (SpicyAPI Gemini TTS). 3–5 s per answer, 18+ allowed by the
  same rules as the chat. CALL_PREMIUM_SECONDS_PER_DAY a day.
* Without Premium — a live call through the Gemini Live API: she answers in
  about half a second and he can interrupt her, but Google's model keeps it
  clean (no 18+). CALL_FREE_SECONDS_PER_DAY a day. The server bridges the
  app's WebSocket to Gemini so the key never reaches the phone.

Seconds spoken are stored as ProductEvent rows (value = seconds), so no new
table is needed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, time as dtime, timezone

logger = logging.getLogger(__name__)


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ('1', 'true', 'yes', 'on')


ENABLED = _flag('CALL_ENABLED', 'true')
LIVE_ENABLED = _flag('CALL_LIVE_ENABLED', 'true')
PREMIUM_SECONDS_PER_DAY = int(os.getenv('CALL_PREMIUM_SECONDS_PER_DAY', str(15 * 60)))
FREE_SECONDS_PER_DAY = int(os.getenv('CALL_FREE_SECONDS_PER_DAY', '180'))
# Newest first; the first model that accepts the connection is remembered.
LIVE_MODELS = tuple(m.strip() for m in os.getenv(
    'GEMINI_LIVE_MODELS',
    'gemini-3.8-live,gemini-3.1-flash-live-preview,gemini-2.5-flash-native-audio-preview-12-2025',
).split(',') if m.strip())
# Gemini Live: $0.005/min audio in + $0.018/min audio out (pricing 2026-11).
LIVE_COST_PER_MIN_USD = float(os.getenv('CALL_LIVE_COST_PER_MIN_USD', '0.023'))

EVENT_PREMIUM = 'call_premium_sec'
EVENT_LIVE = 'call_live_sec'
# Between two Premium turns at most this much wall time is counted (he may
# have put the phone down with the call screen open).
MAX_TURN_GAP = 90

_good_model: str | None = None
_premium_last_turn: dict[str, float] = {}


def mode_for(premium: bool, admin: bool = False, asked: str = '') -> str:
    """'premium' (MiniMax + her TTS voice, 18+) or 'live' (Gemini Live, clean).
    Admins may ask for either to test both."""
    if admin and asked in ('premium', 'live'):
        return asked
    return 'premium' if (premium or admin) else 'live'


def _day_start() -> datetime:
    return datetime.combine(datetime.now(timezone.utc).date(), dtime.min)


def seconds_today(uid: int, event: str) -> int:
    from sqlalchemy import func, select
    from models.app_models import ProductEvent
    from services.db import SessionLocal
    with SessionLocal() as s:
        return int(s.scalar(select(func.coalesce(func.sum(ProductEvent.value), 0)).where(
            ProductEvent.user_id == uid, ProductEvent.event_name == event,
            ProductEvent.created_at >= _day_start())) or 0)


def seconds_left(uid: int, mode: str, admin: bool = False) -> int:
    if admin:
        return 3600
    if mode == 'premium':
        return max(0, PREMIUM_SECONDS_PER_DAY - seconds_today(uid, EVENT_PREMIUM))
    return max(0, FREE_SECONDS_PER_DAY - seconds_today(uid, EVENT_LIVE))


def add_seconds(uid: int, mode: str, seconds: float, character_id: str) -> None:
    if seconds <= 0:
        return
    from services.analytics_service import track_event
    track_event(uid, EVENT_PREMIUM if mode == 'premium' else EVENT_LIVE,
                value=round(float(seconds), 1), character_id=character_id)


def premium_turn_seconds(call_id: str, now: float | None = None) -> float:
    """Wall time since the previous turn of this Premium call, capped."""
    now = now if now is not None else time.monotonic()
    key = (call_id or '')[:64]
    last = _premium_last_turn.get(key)
    _premium_last_turn[key] = now
    if len(_premium_last_turn) > 5000:
        for k in list(_premium_last_turn)[:2500]:
            _premium_last_turn.pop(k, None)
    if last is None:
        return 0.0
    return max(0.0, min(MAX_TURN_GAP, now - last))


# ── Premium call: the chat pipeline with a phone direction ─────────────────

CALL_SCENE = (
    'СЕЙЧАС ВЫ РАЗГОВАРИВАЕТЕ ПО ТЕЛЕФОНУ, ГОЛОСОМ. Его реплика — это то, что он сказал вслух '
    '(распознанная речь, могут быть ошибки — угадывай смысл). Отвечай так, как говорят живым голосом '
    'в трубку: 1–3 коротких предложения, разговорно, с паузами «…», смешками и вздохами по настроению. '
    'Никаких звёздочек с действиями, никаких эмодзи, списков и описаний сцены — только то, что ты '
    'произносишь. Не обещай прислать фото во время звонка. Задай встречный вопрос, если разговор '
    'затихает. Говори на его языке.'
)

# V3.115.1: the pick-up is instant — a short «алло» in her voice, synthesized
# once per girl and kept in memory, instead of 12–17 s of LLM + TTS while he
# stares at «Думает…» (Витя hung up before she answered).
HELLO_LINES = {
    'ru': ('алло… привет, котик', 'алло? ну наконец-то, я ждала', 'привет… как же я рада тебя слышать'),
    'en': ('hello… hi, sweetheart', 'hey… finally, I was waiting', 'hi… I am so glad to hear you'),
}
_hello_audio: dict[tuple[str, str, int], bytes] = {}


def hello_line(lang: str, n: int) -> tuple[int, str]:
    lines = HELLO_LINES.get(lang) or HELLO_LINES['ru']
    i = n % len(lines)
    return i, lines[i]


def hello_cached(character_id: str, lang: str, i: int) -> bytes | None:
    return _hello_audio.get((character_id, lang, i))


def hello_store(character_id: str, lang: str, i: int, audio: bytes) -> None:
    if len(_hello_audio) > 600:
        _hello_audio.clear()
    _hello_audio[(character_id, lang, i)] = audio


_SENT_END = re.compile(r'(?<=[.!?…])\s+')


def split_for_speech(text: str, first_max: int = 110) -> list[str]:
    """Her answer in two parts: a short first phrase that is voiced and played
    at once, and the rest, voiced while the first one plays."""
    t = re.sub(r'\s+', ' ', text or '').strip()
    if len(t) <= first_max:
        return [t] if t else []
    parts = _SENT_END.split(t)
    first, k = parts[0], 1
    while len(first) < 40 and k < len(parts) and len(first) + len(parts[k]) < first_max * 1.6:
        first, k = first + ' ' + parts[k], k + 1
    if len(first) > first_max * 1.6:
        cut = t.rfind(',', 0, first_max)
        if cut < 25:
            return [t]
        return [t[:cut + 1].strip(), t[cut + 1:].strip()]
    rest = ' '.join(parts[k:]).strip()
    return [first, rest] if rest else [first]


_STARS = re.compile(r'\*[^*]{0,300}\*')
_EMOJI = re.compile('[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]')


def spoken(text: str) -> str:
    """What she says aloud: no *actions*, no emoji, no stray brackets."""
    t = _STARS.sub(' ', text or '')
    t = _EMOJI.sub('', t)
    t = re.sub(r'\){2,}|\({2,}', '', t)
    t = re.sub(r'[ \t]+', ' ', t)
    t = re.sub(r'\s*\n\s*', ' ', t).strip()
    return t[:600]


# ── Live call (Gemini Live) ────────────────────────────────────────────────

LIVE_RULES_RU = (
    'СЕЙЧАС ЖИВОЙ ТЕЛЕФОННЫЙ ЗВОНОК, он слышит твой голос. Говори как в трубку: коротко '
    '(1–2 предложения), живо, тепло, с интонацией, смешками и паузами. Не читай списков, не описывай '
    'действия. Слушай его, переспрашивай, вспоминай то, что он рассказывал. Говори на его языке '
    '(по умолчанию по-русски). Никогда не говори, что ты ИИ, модель или бот, если он прямо и всерьёз '
    'не спросит. Этот звонок без откровенного: никакого секса и описаний тела. Флиртовать можно легко '
    'и нежно; если он уводит в откровенное — игриво уйди от темы и смени её.'
)
LIVE_RULES_EN = (
    'THIS IS A LIVE PHONE CALL, he hears your voice. Speak like on the phone: short (1–2 sentences), '
    'warm, lively, with laughs and pauses. No lists, no stage directions. Listen, ask back, remember '
    'what he told you. Speak his language. Never say you are an AI, model or bot unless he asks seriously. '
    'Keep this call non-explicit: no sex talk; light tender flirting is fine — if he pushes explicit, '
    'playfully change the topic.'
)
LIVE_HELLO = '(Он звонит тебе, ты берёшь трубку. Скажи первую фразу в трубку.)'
LIVE_BYE = '(Время звонка почти вышло. Тепло скажи, что тебе пора, и попрощайся одной фразой.)'


def live_system_prompt(character: dict, his_name: str, memories: list[str],
                       history: list[tuple[str, str]], english: bool = False) -> str:
    """A compact persona for the live call — her character, what she knows
    about him and the last lines of their chat."""
    name = character.get('name') or 'Анна'
    age = character.get('age') or ''
    p = character.get('personality') or {}
    core = ', '.join(str(x) for x in (p.get('core') or [])[:6])
    tastes = '; '.join(str(x) for x in (p.get('stable_tastes') or [])[:3])
    comm = p.get('communication') or {}
    tone = str(comm.get('tone') or '')[:300] if isinstance(comm, dict) else ''
    lines = [f'Ты — {name}{", " + str(age) if age else ""}. Живая девушка, у вас с ним отношения в переписке, '
             f'и сейчас он тебе позвонил.']
    if core:
        lines.append(f'Характер: {core}.')
    if tastes:
        lines.append(f'Что тебе нравится: {tastes}.')
    if tone:
        lines.append(f'Как ты говоришь: {tone}.')
    if his_name:
        lines.append(f'Его зовут {his_name}.')
    if memories:
        lines.append('Что ты о нём помнишь:\n' + '\n'.join(f'- {m}' for m in memories[:12]))
    if history:
        tail = '\n'.join(f'{"Он" if r == "user" else "Ты"}: {spoken(c)[:240]}' for r, c in history[-10:]
                         if spoken(c))
        if tail:
            lines.append('Последние сообщения вашей переписки:\n' + tail)
    lines.append(LIVE_RULES_EN if english else LIVE_RULES_RU)
    return '\n\n'.join(lines)


def live_cost_usd(seconds: float) -> float:
    return round(LIVE_COST_PER_MIN_USD * seconds / 60.0, 4)


async def live_bridge(ws, *, api_key: str, voice_name: str, system_prompt: str,
                      seconds_allowed: int, english: bool = False) -> tuple[float, list[tuple[str, str]], str]:
    """Bridge the app's WebSocket (binary PCM16 16 kHz up, PCM16 24 kHz down,
    JSON events both ways) to a Gemini Live session.

    Returns (seconds talked, transcript [(role, text)], end reason)."""
    global _good_model
    from aiohttp import WSMsgType
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    config = types.LiveConnectConfig(
        response_modalities=['AUDIO'],
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name))),
        system_instruction=system_prompt,
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )
    transcript: list[tuple[str, str]] = []
    buf = {'user': '', 'assistant': ''}
    state = {'started': 0.0, 'reason': 'hangup'}

    def _flush(role: str) -> None:
        t = re.sub(r'\s+', ' ', buf[role]).strip()
        if t:
            if transcript and transcript[-1][0] == role:
                transcript[-1] = (role, (transcript[-1][1] + ' ' + t)[:1500])
            else:
                transcript.append((role, t[:1500]))
        buf[role] = ''

    async def _say(session, text: str) -> None:
        await session.send_client_content(
            turns=types.Content(role='user', parts=[types.Part(text=text)]), turn_complete=True)

    async def upstream(session):
        async for msg in ws:
            if msg.type == WSMsgType.BINARY:
                if msg.data:
                    await session.send_realtime_input(
                        audio=types.Blob(data=msg.data, mime_type='audio/pcm;rate=16000'))
            elif msg.type == WSMsgType.TEXT:
                try:
                    j = json.loads(msg.data)
                except Exception:
                    continue
                if j.get('type') == 'hangup':
                    state['reason'] = 'hangup'
                    return
            else:
                state['reason'] = 'closed'
                return

    async def downstream(session):
        while True:
            async for m in session.receive():
                if m.go_away is not None:
                    state['reason'] = 'go_away'
                sc = m.server_content
                if not sc:
                    continue
                if sc.input_transcription and sc.input_transcription.text:
                    if buf['assistant']:
                        _flush('assistant')
                    buf['user'] += sc.input_transcription.text
                    await ws.send_json({'type': 'you', 'text': sc.input_transcription.text})
                if sc.model_turn and sc.model_turn.parts:
                    if buf['user']:
                        _flush('user')
                    for part in sc.model_turn.parts:
                        data = part.inline_data.data if part.inline_data else None
                        if data:
                            await ws.send_bytes(data)
                if sc.output_transcription and sc.output_transcription.text:
                    buf['assistant'] += sc.output_transcription.text
                    await ws.send_json({'type': 'her', 'text': sc.output_transcription.text})
                if sc.interrupted:
                    _flush('assistant')
                    await ws.send_json({'type': 'interrupted'})
                if sc.turn_complete:
                    _flush('user')
                    _flush('assistant')
                    await ws.send_json({'type': 'turn'})

    async def timer(session):
        warn_at = max(5, seconds_allowed - 15)
        await asyncio.sleep(warn_at)
        try:
            await _say(session, LIVE_BYE)
        except Exception:
            pass
        await asyncio.sleep(max(0, seconds_allowed - warn_at))
        state['reason'] = 'limit'

    models = ([_good_model] if _good_model else []) + [m for m in LIVE_MODELS if m != _good_model]
    last_error: Exception | None = None
    for model in models:
        try:
            async with client.aio.live.connect(model=model, config=config) as session:
                _good_model = model
                state['started'] = time.monotonic()
                await ws.send_json({'type': 'ready', 'seconds_left': seconds_allowed})
                await _say(session, LIVE_HELLO if not english else '(He is calling you, you pick up. Say your first line.)')
                tasks = [asyncio.create_task(upstream(session)), asyncio.create_task(downstream(session)),
                         asyncio.create_task(timer(session))]
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for t in pending:
                    t.cancel()
                for t in done:
                    exc = t.exception()
                    if exc is not None:
                        logger.warning('live call task failed model=%s: %s', model, exc)
                        state['reason'] = 'error'
                break
        except Exception as exc:
            if state['started']:
                logger.warning('live call dropped model=%s: %s', model, exc)
                state['reason'] = 'error'
                break
            last_error = exc
            logger.warning('live call connect failed model=%s: %s', model, exc)
            if _good_model == model:
                _good_model = None
    if not state['started']:
        raise last_error or RuntimeError('gemini_live_no_model')
    _flush('user')
    _flush('assistant')
    return time.monotonic() - state['started'], transcript, state['reason']
