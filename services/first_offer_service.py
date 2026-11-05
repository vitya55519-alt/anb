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
# V3.111.0: 3 → 2 messages and 20 → 8 minutes. All three people who ever paid
# did it 4–95 minutes after /start, after 1–4 messages; a 20-minute pause
# after the 3rd message found most of them already gone.
FIRST_OFFER_MIN_MESSAGES = max(1, int(os.getenv('FIRST_OFFER_MIN_MESSAGES', '2')))
FIRST_OFFER_MAX_ACCOUNT_HOURS = max(6, int(os.getenv('FIRST_OFFER_MAX_ACCOUNT_HOURS', '72')))
# She waits for a pause: the offer never lands in the middle of a live dialog.
FIRST_OFFER_PAUSE_MINUTES = max(3, int(os.getenv('FIRST_OFFER_PAUSE_MINUTES', '8')))
# V3.111.0: «витрина первого часа» — inside the first SHOWCASE_HOURS the offer
# comes with her short voice note and the trial price right on the card
# (one tap to pay), and after a Premium payment she sends the very photo that
# was blurred on the card, unblurred: the card promised «открыть», so it opens.
SHOWCASE_ENABLED = os.getenv('FIRST_HOUR_SHOWCASE_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')
SHOWCASE_HOURS = max(1, int(os.getenv('FIRST_HOUR_SHOWCASE_HOURS', '3')))

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


def remember_photo(telegram_id: int, character_id: str, file_id: str | None, path: str | None) -> None:
    """What was blurred on his card: a Telegram file_id (owner upload) or a
    repo path (her reference). Delivered clean after a Premium payment."""
    try:
        data = dict(_store.get(int(telegram_id)) or {})
        data.update({'char': character_id or '', 'fid': file_id or '', 'path': path or '', 'delivered': 0})
        _store[int(telegram_id)] = data
    except Exception:
        logger.warning('first offer photo remember failed user=%s', telegram_id, exc_info=True)


def take_pending_photo(telegram_id: int) -> dict | None:
    """The blurred photo still owed to him, once: {'char','fid','path'} or None."""
    try:
        data = dict(_store.get(int(telegram_id)) or {})
    except Exception:
        return None
    if not data or data.get('delivered') or not (data.get('fid') or data.get('path')):
        return None
    data['delivered'] = 1
    try:
        _store[int(telegram_id)] = data
    except Exception:
        return None
    return {'char': data.get('char') or '', 'fid': data.get('fid') or '', 'path': data.get('path') or ''}


def is_showcase(created_at, now: dt.datetime | None = None) -> bool:
    """True while the account is inside its first SHOWCASE_HOURS."""
    if not SHOWCASE_ENABLED or created_at is None:
        return False
    now = now or dt.datetime.utcnow()
    return now - created_at <= dt.timedelta(hours=SHOWCASE_HOURS)


# Her short voice note before the card: shy, warm, no pressure, no countdown.
VOICE_RU = (
    'слушай… я тут подумала и решила записать тебе голосом. мне приятно, что ты мне написал. я кое-что приготовила, только для тебя',
    'привет ещё раз… мне захотелось, чтобы ты услышал мой голос. у меня для тебя есть одна фотография, сейчас пришлю',
)
VOICE_EN = (
    "hey… I wanted you to hear my voice for once. I'm really glad you wrote to me. I have something just for you",
    "hi again… I thought I'd send you a voice note instead of typing. I have one photo for you, sending it now",
)

SHOWCASE_CAPTION_RU = ('это только для тебя 🙈\nоткрою за {price} — и ещё {days} дня без лимитов, с голосом и фото.\n'
                       'разовый платёж, без автопродления')
SHOWCASE_CAPTION_EN = ('this one is just for you 🙈\nunlocks for {price}, plus {days} days with no limits, voice and photos.\n'
                       'one-time payment, no auto-renewal')
DELIVER_RU = 'как обещала 🙈 это тебе. теперь можешь просить у меня фото прямо в чате'
DELIVER_EN = "as promised 🙈 this is for you. now you can ask me for photos right in the chat"


def voice_line(lang: str) -> str:
    return random.choice(VOICE_EN if lang == 'en' else VOICE_RU)


def showcase_caption(lang: str, price: str, days: int) -> str:
    return (SHOWCASE_CAPTION_EN if lang == 'en' else SHOWCASE_CAPTION_RU).format(price=price, days=days)


def deliver_caption(lang: str) -> str:
    return DELIVER_EN if lang == 'en' else DELIVER_RU


def caption(lang: str) -> str:
    return random.choice(CAPTIONS_EN if lang == 'en' else CAPTIONS_RU)


def candidates(now: dt.datetime | None = None) -> list[tuple[int, int, str, dt.datetime | None]]:
    """(user_id, telegram_id, character_id, created_at) of fresh, interested, paused users."""
    now = now or dt.datetime.utcnow()
    young = now - dt.timedelta(hours=FIRST_OFFER_MAX_ACCOUNT_HOURS)
    paused = now - dt.timedelta(minutes=FIRST_OFFER_PAUSE_MINUTES)
    out: list[tuple[int, int, str, dt.datetime | None]] = []
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
            out.append((u.id, int(u.telegram_id), char_id, u.created_at))
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
