"""V3.97.0: a one-time «месяц −50%» for the people who love her the most.

The 1 Nov 2026 stats: nine users wrote 177–525 messages each and hit the free
daily limit up to 387 times, and not one of them paid. They are the warmest
audience the bot has. After his MIN_SLEEP_BLOCKS-th limit hit the next wall
opens a personal window: a month of Premium at half price for VIP_HOURS.
One window per user, ever; buying any Premium closes it.

Stored as product events (``vip_offer_opened``), so no new table is needed.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from config import PLATEGA_ENABLED, PLATEGA_PREMIUM_PRICE_RUB, PREMIUM_MONTHLY_STARS
from models.app_models import ProductEvent, User
from services.db import SessionLocal

PRODUCT = 'premium_month_vip'
OPENED_EVENT = 'vip_offer_opened'
VIP_PERCENT = max(10, min(80, int(os.getenv('VIP_OFFER_PERCENT', '50'))))
VIP_HOURS = max(1, int(os.getenv('VIP_OFFER_HOURS', '48')))
MIN_SLEEP_BLOCKS = max(1, int(os.getenv('VIP_OFFER_MIN_LIMIT_HITS', '3')))
ENABLED = os.getenv('VIP_OFFER_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')

VIP_STARS = max(1, PREMIUM_MONTHLY_STARS * (100 - VIP_PERCENT) // 100)
VIP_RUB = max(1, PLATEGA_PREMIUM_PRICE_RUB * (100 - VIP_PERCENT) // 100)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _uid(session, telegram_id: int) -> int | None:
    return session.scalar(select(User.id).where(User.telegram_id == str(telegram_id)))


def _count(session, uid: int, event: str) -> int:
    return int(session.scalar(select(func.count(ProductEvent.id)).where(
        ProductEvent.user_id == uid, ProductEvent.event_name == event)) or 0)


def maybe_open(telegram_id: int) -> bool:
    """Called on a daily-limit wall (after its own event was recorded). Opens
    the window once he has hit the limit MIN_SLEEP_BLOCKS times. True when it
    was opened right now."""
    if not ENABLED:
        return False
    try:
        from services.access_service import is_premium
        if is_premium(telegram_id):
            return False
        with SessionLocal() as s:
            uid = _uid(s, telegram_id)
            if not uid or _count(s, uid, OPENED_EVENT):
                return False
            if _count(s, uid, 'chat_sleep_block') < MIN_SLEEP_BLOCKS:
                return False
            s.add(ProductEvent(user_id=uid, event_name=OPENED_EVENT, created_at=_now()))
            s.commit()
            return True
    except Exception:
        return False


def info(telegram_id: int) -> dict:
    """{'active', 'hours_left', 'stars', 'rub', 'percent'} — active only inside
    the window and while he is not Premium."""
    try:
        from services.access_service import is_premium
        with SessionLocal() as s:
            uid = _uid(s, telegram_id)
            if not uid:
                return {'active': False}
            opened = s.scalar(select(func.max(ProductEvent.created_at)).where(
                ProductEvent.user_id == uid, ProductEvent.event_name == OPENED_EVENT))
        if not opened:
            return {'active': False}
        left = (opened + timedelta(hours=VIP_HOURS) - _now()).total_seconds() / 3600
        if left <= 0 or is_premium(telegram_id):
            return {'active': False}
        return {'active': True, 'hours_left': left, 'stars': VIP_STARS,
                'rub': VIP_RUB if PLATEGA_ENABLED else None, 'percent': VIP_PERCENT}
    except Exception:
        return {'active': False}


def is_active(telegram_id: int) -> bool:
    return bool(info(telegram_id).get('active'))
