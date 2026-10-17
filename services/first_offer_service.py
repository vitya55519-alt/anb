"""V3.63.2: the first-evening offer — Premium shown at a moment of interest.

The funnel numbers that motivated it (owner's admin panel, Oct 2026): of 185
users who pressed /start in 30 days only 9 ever SAW a paid offer. The only
paywall was the daily message limit, but new users get 24h of unlimited text
and then write ~5 messages a day, so the limit (20/day) never bites and the
sale never starts.

This sends ONE offer per user, in the bot chat (a Telegram notification also
pulls back someone who is chatting in the Mini App), once they have shown
interest: a fresh account (< FIRST_OFFER_MAX_ACCOUNT_HOURS) that has written at
least FIRST_OFFER_MIN_MESSAGES messages and paused for a while. The card is
her blurred, locked photo with a short line in her voice; «🔓 открыть» opens
the regular Premium screen with the one-time 24h discount switched on.

Dedup is a persisted DialogStore marker (no schema change), written BEFORE the
send so a failing send can never re-fire the offer every scan.
"""
from __future__ import annotations

import datetime as dt
import io
import logging
import os
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from sqlalchemy import func, select

from services import dialog_store
from services.db import SessionLocal
from models.app_models import Message, User

logger = logging.getLogger(__name__)

FIRST_OFFER_ENABLED = os.getenv('FIRST_OFFER_ENABLED', '1').strip() not in ('0', 'false', 'no', 'off')
FIRST_OFFER_MIN_MESSAGES = max(1, int(os.getenv('FIRST_OFFER_MIN_MESSAGES', '3')))
FIRST_OFFER_MAX_ACCOUNT_HOURS = max(6, int(os.getenv('FIRST_OFFER_MAX_ACCOUNT_HOURS', '72')))
# She waits for a pause: the offer never lands in the middle of a live dialog.
FIRST_OFFER_PAUSE_MINUTES = max(5, int(os.getenv('FIRST_OFFER_PAUSE_MINUTES', '20')))

_store = dialog_store.DialogStore('first_offer')

ROOT = Path(__file__).resolve().parents[1]
_FONT_CANDIDATES = (
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf',
)

CAPTIONS_RU = (
    'я тут сделала пару фото… только для тебя 🙈\nно такие я показываю самым близким',
    'знаешь, я сегодня долго выбирала, что надеть… и сфоткалась 🙈\nхочешь посмотреть?',
    'мне кажется, тебе можно доверять 🙈\nу меня есть фото, которые я больше никому не показываю',
)
CAPTIONS_EN = (
    'I took a couple of photos… just for you 🙈\nbut I only show these to the closest ones',
    'I spent ages choosing what to wear today… and took a photo 🙈\nwant to see?',
    'I feel like I can trust you 🙈\nI have photos I never show anyone else',
)


def already_offered(telegram_id: int) -> bool:
    try:
        return bool(_store.get(int(telegram_id)))
    except Exception:
        return True  # store hiccup: never risk a double offer


def mark_offered(telegram_id: int) -> None:
    _store[int(telegram_id)] = {'at': dt.datetime.utcnow().isoformat(timespec='seconds')}


def caption(lang: str) -> str:
    return random.choice(CAPTIONS_EN if lang == 'en' else CAPTIONS_RU)


def candidates(now: dt.datetime | None = None) -> list[tuple[int, int, str]]:
    """(user_id, telegram_id, character_id) of fresh, interested, paused users."""
    now = now or dt.datetime.utcnow()
    young = now - dt.timedelta(hours=FIRST_OFFER_MAX_ACCOUNT_HOURS)
    paused = now - dt.timedelta(minutes=FIRST_OFFER_PAUSE_MINUTES)
    out: list[tuple[int, int, str]] = []
    with SessionLocal() as s:
        users = s.scalars(select(User).where(
            User.created_at >= young,
            User.last_active_at <= paused,
            User.proactive_enabled == True,  # noqa: E712 — SQL expression
        )).all()
        for u in users:
            sent = s.scalar(select(func.count(Message.id)).where(
                Message.user_id == u.id, Message.role == 'user')) or 0
            if sent < FIRST_OFFER_MIN_MESSAGES:
                continue
            char_id = (getattr(u, 'selected_character', '') or '').strip()
            out.append((u.id, int(u.telegram_id), char_id))
    return out


def _font(size: int):
    """A Cyrillic-capable truetype font, or None (Pillow's bundled default has
    no Cyrillic — the label is skipped rather than drawn as boxes)."""
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return None


def locked_card(reference, label: str = 'только для тебя') -> bytes:
    # reference: a Path or a file-like object (a downloaded Telegram photo)
    """Her reference photo, heavily blurred, with a lock badge — a cover for
    the offer, not a preview of any specific paid photo."""
    img = Image.open(reference).convert('RGB')
    img.thumbnail((900, 1200))
    img = img.filter(ImageFilter.GaussianBlur(radius=max(14, img.width // 40)))
    shade = Image.new('RGB', img.size, (20, 10, 30))
    img = Image.blend(img, shade, 0.15)
    d = ImageDraw.Draw(img)
    w, h = img.size
    r = w // 9
    cx, cy = w // 2, int(h * 0.44)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255))
    # padlock: shackle + body
    sw = max(4, r // 7)
    d.arc([cx - r // 2, cy - int(r * 0.85), cx + r // 2, cy + r // 6], 180, 360, fill=(40, 20, 50), width=sw)
    d.rounded_rectangle([cx - int(r * 0.62), cy - r // 8, cx + int(r * 0.62), cy + int(r * 0.6)], radius=r // 6, fill=(40, 20, 50))
    font = _font(max(28, w // 16))
    if font is not None and label:
        tw = d.textlength(label, font=font)
        d.text(((w - tw) / 2, cy + r + w // 30), label, font=font, fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=86)
    return buf.getvalue()
