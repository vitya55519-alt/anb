"""V3.167.27: «фантазия» — the standalone wish frame (owner ТЗ, 20 ноя).

A collapsible panel above «✨ Возможности»: he writes in his own words what he
wants to see, and the generator draws THAT woman from the chat — her face and
body, his words for the wardrobe, the place and the pose. This is its own
feature, not a variant of «🎭 Фетиши»: the fetish mode is never switched on,
no chat text is consumed, and the economics are its own.

Owner's rails, verbatim from the ТЗ:
* one wish frame per Moscow day is free for every account; Premium changes
  nothing («с премиумом тоже 1 бесплатно в сутки, потом плата»);
* every later frame costs the existing explicit-frame price
  (EXPLICIT_PHOTO_PEACH_COST 🍑) — no new price knob lives here;
* nothing is charged or burned before the frame exists: a refused or failed
  render costs nothing and keeps the free slot for the day;
* the only text filter is the engine's hard limits (fetish_mode._BLOCKED —
  minors, animals, violence); everything else is drawn in the mode the
  account is in: 18+ uncensored, romance on the censored pipeline.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from config import EXPLICIT_PHOTO_PEACH_COST
from services import dialog_store, fetish_mode

logger = logging.getLogger(__name__)

WISH_MAX = fetish_mode.WISH_MAX  # 300 characters, the same hard-limit filter
_MSK = timezone(timedelta(hours=3))
_day = dialog_store.DialogStore('wish_day')


def clean_wish(text: str) -> str | None:
    """His fantasy, one line up to WISH_MAX, or None when it is empty or
    touches a hard limit the generator will not draw at all."""
    return fetish_mode.clean_custom(text, max_len=WISH_MAX)


def photo_line(text: str) -> str:
    """The English wrapper around his own words for the render prompt — the
    same convention as a custom fetish photo theme, but this frame is only
    ever about the one woman he is chatting with."""
    return (f"his own fantasy, in his words: «{text}» — an adult scene, "
            "she is the only person in the frame")


def _today() -> str:
    return datetime.now(_MSK).date().isoformat()


def free_available(telegram_id: int) -> bool:
    """The day's free frame is still untouched (per account, not per girl)."""
    try:
        return str(_day.get(int(telegram_id)) or '') != _today()
    except Exception:
        logger.exception('wish free-slot read failed user=%s', telegram_id)
        return False


def cost() -> int:
    return EXPLICIT_PHOTO_PEACH_COST


def settle(telegram_id: int) -> str:
    """Bill a DELIVERED wish frame: the day's free slot first, then peaches.

    Returns 'free' / 'paid'; 'none' means the charge did not fit (a balance
    race) — the frame was already delivered, so it is logged, never re-billed.
    """
    from services.payments import spend_peaches
    try:
        if free_available(telegram_id):
            _day[int(telegram_id)] = _today()
            return 'free'
        if spend_peaches(telegram_id, EXPLICIT_PHOTO_PEACH_COST, paid_only=True):
            return 'paid'
    except Exception:
        logger.exception('wish settle failed user=%s', telegram_id)
    return 'none'
