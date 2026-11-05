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
        audio = await synthesize_bytes(line, None, character_id=character_id, mood='evening')
        return audio or None
    except Exception:
        logger.exception('evening voice synth failed character=%s', character_id)
        return None


def caption(text: str) -> str:
    return text if len(text) <= CAPTION_LIMIT else text[:CAPTION_LIMIT - 1].rstrip() + '…'


# ── V3.110.0: a photo of her comes with the evening voice ───────────────
# Owner: «хотелось чтобы с голосовым каждый вечер приходила фотка». Budget
# rule (29.10): no new renders for this — the photo is one that already
# exists (her pool first, then a clean chat photo already rendered of her),
# rotated per user so he does not get the same one twice. Spicy prompts are
# filtered out in reused_photo, so free users never get anything intimate.
PHOTO_ENABLED = os.getenv('EVENING_PHOTO_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')


def evening_photo(character_id: str, uid: int | None) -> tuple[bytes, str, str] | None:
    """(bytes, content_type, 'photo') of a ready photo of her, or None. $0."""
    if not PHOTO_ENABLED or not character_id:
        return None
    try:
        from services.chat_photo_allowance import reused_photo
        picked = reused_photo(character_id, uid)
    except Exception:
        logger.exception('evening photo pick failed character=%s', character_id)
        return None
    if not picked or not picked[0]:
        return None
    data, mime, _ext = picked
    return data, mime or 'image/jpeg', 'photo'


# ── V3.108.0: owner's one-off voice cast to everyone ─────────────────────
# «всем одно и то же»: one line per language, voiced once per girl and
# reused for every user of that girl (a handful of TTS calls, not hundreds).
CAST_LINES = {
    'ru': 'привет… я уже лежу и думаю о тебе. как прошёл твой день? расскажешь мне? я жду',
    'en': "hey you… I'm already in bed and thinking about you. how was your day? tell me, I'm waiting",
}
CAST_ACTIVE_DAYS = max(1, int(os.getenv('VOICE_CAST_ACTIVE_DAYS', '30')))


def cast_recipients(days: int = CAST_ACTIVE_DAYS) -> list[tuple[int, int, str, str]]:
    """(user_id, telegram_id, character_id, lang) for everyone who kept her
    messages on and was here in the last ``days`` days."""
    import datetime as dt
    from sqlalchemy import select
    from models.app_models import User
    from services.db import SessionLocal
    cutoff = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(days=days)
    with SessionLocal() as s:
        rows = s.execute(select(User.id, User.telegram_id, User.selected_character, User.ui_lang)
                         .where(User.proactive_enabled == True, User.last_active_at >= cutoff)).all()  # noqa: E712
    out = []
    for uid, tid, char, lang in rows:
        try:
            tg = int(tid)
        except (TypeError, ValueError):
            continue
        out.append((int(uid), tg, char or '', 'en' if (lang or '').lower().startswith('en') else 'ru'))
    return out
