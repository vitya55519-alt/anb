"""V3.107.0 — the evening ritual arrives as her voice note.

Owner: «может вечернее сообщение будет голосовое? для русских на русском,
для англ пользователей на английском, всем одно и то же» — every user, free
or Premium, gets the evening line spoken in her own voice (the same TTS chain
as chat voice: Gemini via SpicyAPI → Grok → fallbacks), with the text kept as
the caption. Russian users hear Russian, English users hear English: the
Russian-only evening template is replaced by an English line for them.

Flag: EVENING_VOICE_ENABLED (default on). Any TTS failure → plain text, as before.
"""
from __future__ import annotations

import logging
import os
import random
import re

logger = logging.getLogger(__name__)

ENABLED = os.getenv('EVENING_VOICE_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')
CAPTION_LIMIT = 1000

# The Russian template pool lives in retention_features_service; the English
# side had none, so EN users got Russian evenings. Short, warm, one question.
EN_EVENING = (
    "hey you… how was your day? I kept thinking about you tonight",
    "evening 🌙 tell me how your day went, I want to hear everything",
    "I'm finally home and cozy… how are you doing tonight?",
    "it's getting late and I miss you a little. how was your day?",
    "so… did today treat you well? come tell me before bed",
)

_EMOJI = re.compile('[\U0001F000-\U0001FAFF☀-➿️‍]+')


def en_evening_line() -> str:
    return random.choice(EN_EVENING)


def spoken_text(text: str) -> str:
    """What she says aloud: no emojis, no markup, collapsed spaces."""
    t = _EMOJI.sub(' ', text or '')
    t = re.sub(r'[*_`#>]+', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def language_matches(text: str, lang: str) -> bool:
    """Never read a Russian line to an English user (or the other way)."""
    try:
        from services.voice_service import detect_voice_language
        got = detect_voice_language(text) or ''
    except Exception:
        return False
    return got.startswith('en') if lang == 'en' else got.startswith('ru')


async def voice_bytes(text: str, character_id: str, lang: str) -> bytes | None:
    """Her voice for the evening line, or None (then the text goes as before)."""
    if not ENABLED:
        return None
    line = spoken_text(text)
    if not line or not language_matches(line, lang):
        return None
    try:
        from services.voice_service import synthesize_bytes
        audio = await synthesize_bytes(line, None, character_id=character_id)
        return audio or None
    except Exception:
        logger.exception('evening voice synth failed character=%s', character_id)
        return None


def caption(text: str) -> str:
    return text if len(text) <= CAPTION_LIMIT else text[:CAPTION_LIMIT - 1].rstrip() + '…'
