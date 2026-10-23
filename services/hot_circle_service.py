"""V3.72.0: «🔥 горячий кружок» — a paid, uncensored video note.
V3.73.0: «🤫 тайное видео» — Seedance 2.5 Spicy, silent, more explicit.

Owner (2026-10-23): «горячий кружок на спайсе сделай… чтобы цепляло», but
never a circle for everyone («в минус просто работать»). So:

* it is only rendered after the user taps and has HOT_CIRCLE_PEACH_COST;
  peaches are charged only for a delivered clip;
* Seedance 2.5 Spicy renders a silent 5 s square clip (Wan 2.6 lost her
  face; the owner found the lip-synced voice crooked, so no voice);
* the hook costs nothing: in a flirty moment she *offers* it in the chat
  (``offer_for``), at most once a day, and the render only starts on a tap.

Safety line: the frame is always our own built-in character's portrait (an
adult fictional woman we generated), never a user upload and never a custom
character, whose face may come from a real person's photo.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from config import (
    HOT_CIRCLE_ENABLED,
    SPICYAPI_HOT_CIRCLE_MODEL,
    SPICYAPI_HOT_CIRCLE_RESOLUTION,
    SPICYAPI_HOT_CIRCLE_SECONDS,
    SPICYAPI_HOT_CIRCLE_COST_USD,
)
from services import dialog_store

logger = logging.getLogger(__name__)

# V3.73.0: owner — «пооткровеннее, не только лицо: трогает себя за грудь»,
# «между ног руку опускает… прям эротика».
# Seedance has no negative_prompt, so the guard rails live in the prompt; its
# own filter refuses some words (e.g. kissing), so the wording stays plain.
HOT_CIRCLE_PROMPT = (
    'Handheld front-camera selfie video she records privately for her boyfriend on her bed, soft warm bedroom light. '
    'She looks straight into the lens with a seductive, teasing smile and bites her lower lip, '
    'slowly slides her lingerie down, caresses and squeezes her bare breasts, then slowly runs her hand '
    'down her belly and slips it between her thighs, breathing deeper, eyes half closed with pleasure, '
    'erotic, intimate and confident, slow sensual movement. '
    'Adult woman, exactly the same face, hair and body as in the photo, one person only, '
    'photorealistic, natural skin, sharp focus, no text.'
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


async def bedroom_frame(character_id: str) -> bytes | None:
    """V3.73.0: the start frame. Seedance only animates what the first frame
    shows, and the storefront portraits are a café in a sweater, framed to the
    chest — no room for «рука между ног». So the clip starts from one of her
    own «Наедине» lingerie-in-bedroom shots: a stockpiled one when the shared
    pool has it (free), else one fresh render (~$0.035) that also feeds the
    pool. None → the caller falls back to the portrait."""
    import asyncio
    from services.private_photo_service import (
        PrivatePhotoRequest, build_private_photo_prompt, generate_private_photo_real,
        pool_get, cache_save,
    )
    from services.character_dna_service import character_dna_context
    try:
        shot = await asyncio.to_thread(pool_get, character_id, 'lingerie', '', 1)
        if shot:
            return shot
        req = PrivatePhotoRequest(category='lingerie', type_id='lace', location_id='bedroom',
                                  mood_id='sensual', character_id=character_id)
        dna = character_dna_context(character_id)
        prompt = build_private_photo_prompt(req, dna, use_reference=True)
        shot = await generate_private_photo_real(req, dna, prompt)
        if shot:
            await asyncio.to_thread(cache_save, prompt, character_id, 'lingerie', 'lace', shot)
        return shot
    except Exception:
        logger.warning('hot circle bedroom frame failed character=%s', character_id, exc_info=True)
        return None


async def render(frame_jpeg: bytes, lang: str = 'ru') -> bytes:
    """Seedance 2.5 Spicy → silent square mp4 (640×640 at 480p). Raises on
    failure (the caller never charges). Failed jobs are not billed."""
    from services import spend_service, spicy_jobs
    frame_uri = await spicy_jobs.upload(frame_jpeg, 'image/jpeg')
    block = {
        'image_url': frame_uri,
        'prompt': HOT_CIRCLE_PROMPT,
        'resolution': SPICYAPI_HOT_CIRCLE_RESOLUTION,
        'duration_seconds': SPICYAPI_HOT_CIRCLE_SECONDS,
        'generate_audio': False,
    }
    ok = False
    billed = True
    try:
        video, _, _ = await spicy_jobs.run(SPICYAPI_HOT_CIRCLE_MODEL, block, timeout=600)
        ok = True
        return video
    except spicy_jobs.SpicyJobError as exc:
        # refused or failed jobs are not billed; a timeout still is
        billed = str(exc).startswith('timeout')
        raise
    finally:
        spend_service.record_image_spend('spicyapi_hot_circle', 'hot_circle',
                                         SPICYAPI_HOT_CIRCLE_COST_USD, billed=billed, success=ok)
