"""V3.139.0: owner ТЗ (Фогель) — a man without Premium who asks for a photo of
both girls must not start a render. He gets a heavily blurred joint teaser out
of a pre-made pool of three (`webapp/art/duo_blur_1..3.jpg`, his own files), and
only Premium buys the real fal.ai/SpicyAPI shot.

Until those three pictures exist, the same teaser is composed locally: the two
girls' locked cards side by side, blurred beyond recognition with one padlock.
That is a Pillow job on files we already have — no provider call, no spend.
"""
from __future__ import annotations

import io
import logging
import random
import re
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

ART_DIR = Path(__file__).resolve().parents[1] / 'webapp' / 'art'
# The owner's pool — «random.choice([blur_1, blur_2, blur_3])» from the ТЗ.
POOL = ('duo_blur_1.jpg', 'duo_blur_2.jpg', 'duo_blur_3.jpg')
_SAFE_ID = re.compile(r'^[A-Za-z0-9_\-]{1,64}$')
_CACHE: dict[tuple[str, str], bytes] = {}
_MAX_CACHE = 32


def _pair_key(host_id: str, guest_id: str) -> tuple[str, str]:
    return (host_id, guest_id) if host_id <= guest_id else (guest_id, host_id)


def usable(character_id: str) -> bool:
    return bool(character_id) and bool(_SAFE_ID.match(character_id))


def pool_url() -> str | None:
    """One of the owner's pre-made blurred joint photos, already uploaded."""
    ready = [name for name in POOL if (ART_DIR / name).is_file()]
    return f'/webapp/art/{random.choice(ready)}' if ready else None


def pool_bytes() -> bytes | None:
    """The bytes of one randomly picked blurred joint photo of the owner's pool."""
    ready = [name for name in POOL if (ART_DIR / name).is_file()]
    if not ready:
        return None
    try:
        return (ART_DIR / random.choice(ready)).read_bytes()
    except OSError:
        return None


def photo_for(host_id: str, guest_id: str) -> bytes | None:
    """The teaser as bytes — what the bot sends; the app gets the same picture
    through url_for(), which prefers the very same pool file."""
    return pool_bytes() or render(host_id, guest_id)


def url_for(host_id: str, guest_id: str) -> str | None:
    """What the chat bubble shows: the owner's file when it exists, otherwise
    the locally composed blur of these two girls. None — and no broken <img> —
    when neither is available, e.g. a constructed girl has no picture of her own
    for the imaginary partner."""
    if not usable(host_id) or not usable(guest_id):
        return None
    pool = pool_url()
    if pool:
        return pool
    return f'/webapp/duo-teaser/{host_id}/{guest_id}.jpg' if render(host_id, guest_id) else None


def _side_by_side(host_id: str, guest_id: str) -> io.BytesIO | None:
    from services.webapp_service import character_photo
    frames = []
    for cid in (host_id, guest_id):
        shot = character_photo(cid, 0)
        if not shot:
            return None
        try:
            img = Image.open(io.BytesIO(shot[0])).convert('RGB')
        except Exception:
            logger.warning('duo teaser frame unread character=%s', cid)
            return None
        img.thumbnail((450, 600))
        frames.append(img)
    height = max(f.height for f in frames)
    canvas = Image.new('RGB', (sum(f.width for f in frames), height), (20, 10, 30))
    x = 0
    for f in frames:
        canvas.paste(f, (x, (height - f.height) // 2))
        x += f.width
    out = io.BytesIO()
    canvas.save(out, 'JPEG', quality=90)
    out.seek(0)
    return out


def render(host_id: str, guest_id: str) -> bytes | None:
    """Blurred joint card for this pair, cached in memory for the whole pod."""
    if not usable(host_id) or not usable(guest_id):
        return None
    key = _pair_key(host_id, guest_id)
    cached = _CACHE.get(key)
    if cached:
        return cached
    try:
        from services import first_offer_service as fos
        pair = _side_by_side(*key)
        if pair is None:
            return None
        # the same lock the single-girl tease uses: blur, shade, padlock, no text
        body = fos.locked_card(pair, '')
    except Exception:
        logger.exception('duo teaser render failed host=%s guest=%s', host_id, guest_id)
        return None
    if len(_CACHE) >= _MAX_CACHE:
        _CACHE.clear()
    _CACHE[key] = body
    return body
