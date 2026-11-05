"""V3.97.0: a one-time «месяц −50%» for the people who love her the most.

The 1 Nov 2026 stats: nine users wrote 177–525 messages each and hit the free
daily limit up to 387 times, and not one of them paid. They are the warmest
audience the bot has. After his MIN_SLEEP_BLOCKS-th limit hit the next wall
opens a personal window: a month of Premium at half price for VIP_HOURS.
One window per user, ever; buying any Premium closes it.

Stored as product events (``vip_offer_opened``), so no new table is needed.

V3.104.0: the same −VIP_PERCENT month is also his «остаться» price right after
his FIRST payment (a 99 ₽ trial or a 199 ₽ week): a loyalty window that lasts
while his paid days run plus LOYAL_GRACE_HOURS (``loyal_offer_opened``). All
three people who paid in Oct–Nov left the same or the next day and nobody
offered them a reason to stay longer. Unlike the limit-wall window this one is
open while he IS Premium (the month stacks on top of his current days); buying
the month (or a quarter) closes it. Flag: LOYAL_OFFER_ENABLED.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from config import PLATEGA_ENABLED, PLATEGA_PREMIUM_PRICE_RUB, PREMIUM_MONTHLY_STARS
from models.app_models import ProductEvent, StarTransaction, Subscription, User
from services.db import SessionLocal

PRODUCT = 'premium_month_vip'
OPENED_EVENT = 'vip_offer_opened'
VIP_PERCENT = max(10, min(80, int(os.getenv('VIP_OFFER_PERCENT', '50'))))
VIP_HOURS = max(1, int(os.getenv('VIP_OFFER_HOURS', '48')))
MIN_SLEEP_BLOCKS = max(1, int(os.getenv('VIP_OFFER_MIN_LIMIT_HITS', '3')))
ENABLED = os.getenv('VIP_OFFER_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')

LOYAL_EVENT = 'loyal_offer_opened'
LOYAL_ENABLED = os.getenv('LOYAL_OFFER_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')
LOYAL_GRACE_HOURS = max(1, int(os.getenv('LOYAL_OFFER_GRACE_HOURS', '48')))
# A first payment with these products opens the loyalty window.
LOYAL_TRIGGERS = ('premium_trial', 'premium_week')
# Buying one of these after the window opened closes it (he already stayed).
LONG_PLANS = ('premium_month', 'premium_month_discount', 'premium_month_vip', 'premium_quarter')

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


def open_loyalty(telegram_id: int, product: str) -> bool:
    """V3.104.0: called right after a Premium payment. Opens his loyalty window
    once ever, and only when this is his first payment (a trial or a week) —
    someone who already bought a month never needs it. True when opened now."""
    if not (ENABLED and LOYAL_ENABLED) or product not in LOYAL_TRIGGERS:
        return False
    try:
        with SessionLocal() as s:
            uid = _uid(s, telegram_id)
            if not uid or _count(s, uid, LOYAL_EVENT):
                return False
            if s.scalar(select(func.count(StarTransaction.id)).where(
                    StarTransaction.user_id == uid, StarTransaction.transaction_type == 'purchase',
                    StarTransaction.product.in_(LONG_PLANS))):
                return False
            s.add(ProductEvent(user_id=uid, event_name=LOYAL_EVENT, created_at=_now()))
            s.commit()
            return True
    except Exception:
        return False


def _loyal_left_hours(session, uid: int) -> float:
    """Hours left in his loyalty window; 0 when there is none (or it is closed)."""
    opened = session.scalar(select(func.max(ProductEvent.created_at)).where(
        ProductEvent.user_id == uid, ProductEvent.event_name == LOYAL_EVENT))
    if not opened:
        return 0.0
    if session.scalar(select(func.count(StarTransaction.id)).where(
            StarTransaction.user_id == uid, StarTransaction.transaction_type == 'purchase',
            StarTransaction.product.in_(LONG_PLANS), StarTransaction.created_at >= opened)):
        return 0.0
    paid_until = session.scalar(select(func.max(Subscription.expires_at)).where(
        Subscription.user_id == uid, Subscription.status == 'active'))
    base = max(opened, paid_until) if paid_until else opened
    return max(0.0, (base + timedelta(hours=LOYAL_GRACE_HOURS) - _now()).total_seconds() / 3600)


def info(telegram_id: int) -> dict:
    """{'active', 'hours_left', 'stars', 'rub', 'percent', 'loyal'} — active
    inside the limit-wall window while he is not Premium, or (V3.104.0) inside
    his loyalty window after the first payment (Premium or not)."""
    try:
        from services.access_service import is_premium
        with SessionLocal() as s:
            uid = _uid(s, telegram_id)
            if not uid:
                return {'active': False}
            opened = s.scalar(select(func.max(ProductEvent.created_at)).where(
                ProductEvent.user_id == uid, ProductEvent.event_name == OPENED_EVENT))
            loyal_left = _loyal_left_hours(s, uid) if (ENABLED and LOYAL_ENABLED) else 0.0
        offer = {'active': True, 'stars': VIP_STARS, 'rub': VIP_RUB if PLATEGA_ENABLED else None,
                 'percent': VIP_PERCENT}
        if loyal_left > 0:
            return {**offer, 'hours_left': loyal_left, 'loyal': True}
        if not opened:
            return {'active': False}
        left = (opened + timedelta(hours=VIP_HOURS) - _now()).total_seconds() / 3600
        if left <= 0 or is_premium(telegram_id):
            return {'active': False}
        return {**offer, 'hours_left': left, 'loyal': False}
    except Exception:
        return {'active': False}


def is_active(telegram_id: int) -> bool:
    return bool(info(telegram_id).get('active'))
