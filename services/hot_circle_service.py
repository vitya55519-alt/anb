"""V3.72.0: «🔥 горячий кружок» — a paid, uncensored video note.

Owner (2026-10-23): «горячий кружок на спайсе сделай… чтобы цепляло», but
never a circle for everyone («в минус просто работать»). So:

* it is only rendered after the user pays HOT_CIRCLE_PEACH_COST (1500 🍑);
* her voice comes from SpicyAPI TTS (Grok, the voices the owner liked) and
  Wan 2.6 Spicy lip-syncs the portrait to it;
* the hook costs nothing: in a flirty moment she *offers* it in the chat
  (``offer_for``), at most once a day, and the render only starts on a tap.

Safety line: the frame is always our own built-in character's portrait (an
adult fictional woman we generated), never a user upload and never a custom
character, whose face may come from a real person's photo.
"""
from __future__ import annotations

import logging
import random
import re
from datetime import datetime, timezone

from config import (
    HOT_CIRCLE_ENABLED,
    SPICYAPI_HOT_CIRCLE_MODEL,
    SPICYAPI_HOT_CIRCLE_COST_USD,
    SPICYAPI_TTS_MODEL,
    SPICYAPI_TTS_VOICE,
    SPICYAPI_TTS_COST_PER_1K_USD,
)
from services import dialog_store

logger = logging.getLogger(__name__)

HOT_CIRCLE_PROMPT = (
    'Handheld front-camera selfie video she records privately for her boyfriend. '
    'She looks straight into the lens with a seductive, teasing smile and says the line, '
    'lips synced to the audio. She slowly slips the strap off her shoulder and lets her top fall, '
    'sensual slow body movement, playful and confident, soft bedroom light. '
    'Adult woman, the exact same face, hair and body as in the photo. Photorealistic, sharp, natural skin.'
)
HOT_CIRCLE_NEGATIVE = (
    'second person, man, text, watermark, subtitles, distorted face, different face, '
    'extra limbs, deformed hands, child, teen, underage, minor'
)

# What she whispers (Grok TTS tags). 3+ seconds of speech so Wan accepts the
# audio (3–30 s), short enough to land inside the 5-second clip.
HOT_LINES_RU = (
    '<whisper>Это только для тебя…</whisper> [laugh] Не показывай никому, ладно?',
    'Я весь вечер думала о тебе… <whisper>Смотри внимательно.</whisper>',
    'Ну что, ты этого ждал? [laugh] <whisper>Иди ко мне поближе.</whisper>',
    '<whisper>Закрыла дверь, теперь я вся твоя…</whisper> Нравится?',
)
HOT_LINES_EN = (
    '<whisper>This one is just for you…</whisper> [laugh] Don\'t show anyone, okay?',
    'I was thinking about you all evening… <whisper>Watch closely.</whisper>',
    'So, were you waiting for this? [laugh] <whisper>Come closer.</whisper>',
)

# A flirty moment: either side of the turn talks about closeness or desire.
_FLIRTY = re.compile(
    r'(хоч[уе]\s+тебя|поцел|обним|раздев|разде[нл]|голая|голенькая|сексу|секс|возбужд|ласк|постел|'
    r'горяч|страст|сладк|целую|соблазн|бель[её]|kiss|naked|sexy|horny|undress|bed\b|hot\b)',
    re.IGNORECASE,
)
# The user asks for a video note outright — the offer shows every time.
_ASKS_CIRCLE = re.compile(r'(кружо[кч]|кружоч|видео\s*сообщ|video\s*note|circle)', re.IGNORECASE)

_offered = dialog_store.DialogStore('hot_circle_offer')  # telegram_id -> 'YYYY-MM-DD'


def _today() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def hot_line(lang: str = 'ru') -> str:
    return random.choice(HOT_LINES_EN if lang == 'en' else HOT_LINES_RU)


def offer_for(telegram_id: int, character_id: str, user_text: str, answer: str, *,
              is_custom: bool, adult_confirmed: bool, level: int) -> dict | None:
    """The in-chat hook: which circle buttons to show under her reply.

    Returns ``{'hot': bool}`` or None. Costs nothing — rendering starts only
    when the user taps (and pays)."""
    asked = bool(_ASKS_CIRCLE.search(user_text or ''))
    hot_ok = HOT_CIRCLE_ENABLED and adult_confirmed and not is_custom
    if asked:
        return {'hot': hot_ok}
    if not hot_ok or level < 3:
        return None
    if not (_FLIRTY.search(user_text or '') or _FLIRTY.search(answer or '')):
        return None
    if _offered.get(telegram_id) == _today():
        return None
    _offered[telegram_id] = _today()
    return {'hot': True}


async def synth_voice(text: str, lang: str = 'ru') -> tuple[bytes, str]:
    """Her line through SpicyAPI TTS → (mp3 bytes, mime)."""
    from services import spend_service, spicy_jobs
    block = {'text': text, 'voice_id': SPICYAPI_TTS_VOICE, 'language': 'en' if lang == 'en' else 'ru'}
    ok = False
    try:
        data, mime, _ = await spicy_jobs.run(SPICYAPI_TTS_MODEL, block, timeout=90, first_wait=2.0)
        ok = True
        return data, mime or 'audio/mpeg'
    finally:
        spend_service.record_image_spend('spicyapi_tts', 'hot_circle',
                                         SPICYAPI_TTS_COST_PER_1K_USD * len(text) / 1000, billed=ok, success=ok)


async def render(frame_jpeg: bytes, lang: str = 'ru') -> bytes:
    """Voice + Wan 2.6 Spicy lip-sync → mp4 bytes. Raises on failure (the
    caller refunds)."""
    from services import spend_service, spicy_jobs
    from services.spicy_video_service import park_frame
    line = hot_line(lang)
    audio_uri = None
    try:
        audio, mime = await synth_voice(line, lang)
        audio_uri = await spicy_jobs.upload(audio, mime)
    except Exception:
        # a silent clip still delivers the moment; the prompt carries the mood
        logger.warning('hot circle voice failed, rendering without audio', exc_info=True)
    image_url = park_frame(frame_jpeg, 'image/jpeg')
    block = {
        'image_url': image_url,
        'prompt': HOT_CIRCLE_PROMPT,
        'negative_prompt': HOT_CIRCLE_NEGATIVE,
        'resolution': '720p',
        'duration_seconds': 5,
        'shot_type': 'single',
    }
    if audio_uri:
        block['audio_url'] = audio_uri
    ok = False
    billed = True
    try:
        video, _, _ = await spicy_jobs.run(SPICYAPI_HOT_CIRCLE_MODEL, block, timeout=420)
        ok = True
        return video
    except spicy_jobs.SpicyJobError as exc:
        # refused or failed jobs are not billed; a timeout still is
        billed = str(exc).startswith('timeout')
        raise
    finally:
        spend_service.record_image_spend('spicyapi_hot_circle', 'hot_circle',
                                         SPICYAPI_HOT_CIRCLE_COST_USD, billed=billed, success=ok)
