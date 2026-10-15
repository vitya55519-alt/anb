"""V3.61.8: «Я скучала… вот, держи 💋» — the owner fills the free media pool
with fresh photos of every heroine in one tap.

The gift, the morning ritual and the life moments all send a photo from the
ProactivePhoto pool. The owner's pool held hand-picked gallery shots, some of
them cropped at the chin (only the blazer and the chest in frame), which reads
as a stranger's body, not «her». These shots are made for the gift itself: a
personal phone photo for him, her whole face in frame, a tender «missed you»
mood. Every shot is tagged with its heroine, so it only lands in her chats.
"""
from __future__ import annotations

import logging
import math
import random
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

GIFT_POOL_DEFAULT_TOTAL = 20

# One head-to-waist framing rule for every shot: the cropped gift showed
# no face at all, and a gift without her face is not a gift from her.
GIFT_FRAMING = (
    'framed from slightly above the top of her head down to her waist or hips, her ENTIRE face, '
    'hair and eyes fully inside the frame and in sharp focus, looking straight into the lens; '
    'never crop her head or face, never a body-only shot'
)

# (scene, location, clothing, angle, mood) — a «missed you» photo she takes
# for him at different moments of her day.
GIFT_SHOTS: tuple[tuple[str, str, str, str, str], ...] = (
    ('selfie', 'her cozy living room in the evening, warm floor lamp, soft blanket on the sofa',
     'an oversized soft knit sweater slipping off one shoulder',
     'phone held at arm\'s length, she hugs a cushion', 'tender, missing him, a shy warm smile'),
    ('selfie', 'her bed in the morning, white sheets, soft daylight from the window',
     'a loose cotton t-shirt, messy hair after sleep',
     'she lies on the pillow and holds the phone above her face', 'sleepy, sweet, missed you smile'),
    ('selfie', 'a hallway mirror at home, warm light, a coat on the hook',
     'a fitted little black dress, ready for the evening',
     'mirror selfie, she blows a kiss to the camera', 'playful, flirty, a little sad he is not here'),
    ('selfie', 'a window seat on a rainy evening, raindrops on the glass, a mug of tea',
     'a cozy cardigan over a camisole',
     'she leans against the window, phone at eye level', 'wistful, dreamy, thinking about him'),
    ('selfie', 'her kitchen in the morning, coffee cup in hand, sunlight on the counter',
     'a silk robe tied at the waist',
     'quick selfie with the coffee cup near her lips', 'playful smile, «good morning, I missed you»'),
    ('selfie', 'a candlelit table at home with a glass of wine, soft bokeh lights',
     'an elegant black blazer dress with a deep neckline',
     'she sits at the table and holds the phone at arm\'s length', 'romantic, inviting, warm eyes'),
    ('selfie', 'a bathroom mirror after a shower, soft steam, warm light',
     'a white towel wrapped around her body, damp hair',
     'mirror selfie, the phone partly covers one side, her face fully visible', 'shy, intimate, sweet'),
    ('selfie', 'a sunny city street, cafe terrace behind her',
     'a light summer dress and sunglasses pushed up into her hair',
     'selfie at arm\'s length on her walk', 'bright, happy, «wish you were here»'),
)


def _heroines() -> list[str]:
    """Visible built-in heroines (constructor personas belong to one user)."""
    from services.character_card_service import list_cards
    from services.custom_character_service import is_custom_character
    try:
        cards = list_cards(visible_only=True)
    except Exception:
        logger.exception('gift pool: card list failed')
        return []
    return [c.character_id for c in cards if c.character_id and not is_custom_character(c.character_id)]


def plan_gift_pool(total: int = GIFT_POOL_DEFAULT_TOTAL, heroines: list[str] | None = None) -> list[tuple[str, tuple]]:
    """(character_id, shot) pairs — every heroine gets the same share of the
    total, each with different moments of her day."""
    heroines = list(heroines if heroines is not None else _heroines())
    if not heroines or total <= 0:
        return []
    per = max(1, math.ceil(total / len(heroines)))
    plan: list[tuple[str, tuple]] = []
    for cid in heroines:
        shots = random.sample(GIFT_SHOTS, min(per, len(GIFT_SHOTS)))
        plan.extend((cid, shot) for shot in shots)
    return plan


def gift_request(shot: tuple):
    from services.photo_service import PhotoRequest
    scene, location, clothing, angle, mood = shot
    return PhotoRequest(
        scene=scene, location=location, clothing=clothing,
        angle=f'{angle}; {GIFT_FRAMING}', mood=mood, customized=True,
    )


async def fill_gift_pool(
    admin_telegram_id: int,
    total: int = GIFT_POOL_DEFAULT_TOTAL,
    progress: Callable[[int, int, str], Awaitable[None]] | None = None,
) -> tuple[int, int]:
    """Render the plan one shot at a time and append each to the pool.
    Returns (added, failed). Never raises."""
    from services.photo_service import generate_photo_set, photo_frame_bytes
    from services import retention_features_service as rfs
    plan = plan_gift_pool(total)
    added = failed = 0
    for n, (cid, shot) in enumerate(plan, 1):
        ok = False
        try:
            photos, _ = await generate_photo_set(admin_telegram_id, gift_request(shot), character_id=cid, frames=1)
            data = await photo_frame_bytes(photos[0]) if photos else None
            ok = bool(data) and rfs.add_proactive_photo(data, 'image/jpeg', 'photo', character_id=cid)
        except Exception:
            logger.exception('gift pool render failed character=%s', cid)
        if ok:
            added += 1
        else:
            failed += 1
        if progress:
            try:
                await progress(n, len(plan), cid)
            except Exception:
                pass
    return added, failed
