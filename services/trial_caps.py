"""V3.124.0: owner — «надо, чтобы человек покупал премиум, и я в любом
случае не уходил в минус». Every Premium plan carries a fixed allowance for
its whole term (not per day), sized so that even a man who uses everything
to the end leaves at least half of the money (after payment fees) as profit.
Unit costs behind the numbers (backup 5 Nov 2026, 100 ₽/$): his message with
her reply ≈0.23 ₽, a photo / «Раздеть» ≈3.6 ₽, a Premium call minute ≈1.6 ₽,
a voice note ≈0.2 ₽, a photo animation ≈19 ₽.

The daily rules (2 photos a day, 15 call minutes a day, …) still apply on
top; the allowance only caps the total.

Which allowance: each active subscription contributes the allowance of the
product that bought it (a renewal on top adds its own); usage is counted
from the start of the earliest active subscription. Counted from rows that
already exist (messages, product events), so no table is needed. The module
keeps its old name (it began as the trial-only cap).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

logger = logging.getLogger(__name__)

KEYS = ('messages', 'photos', 'undress', 'call_seconds', 'voice', 'animations')

# tier → allowance for the whole term. Env override: CAP_<TIER>_<KEY>, e.g.
# CAP_WEEK_PHOTOS=6. messages -1 = unlimited (owner: «безлимит на сообщения»
# on the paid plans; only the trial and the free demo count them). Max cost
# of everything except messages ≈ trial 44 ₽ / week 45 ₽ / month 164 ₽ /
# quarter 394 ₽ against 89 / 179 / 629 / 1619 ₽ received.
_DEFAULTS = {
    'demo':    {'messages': 30,   'photos': 1,  'undress': 0,  'call_seconds': 0,    'voice': 3,   'animations': 0},
    'trial':   {'messages': 100,  'photos': 2,  'undress': 1,  'call_seconds': 300,  'voice': 10,  'animations': 0},
    'week':    {'messages': -1,  'photos': 5,  'undress': 2,  'call_seconds': 600,  'voice': 20,  'animations': 0},
    'month':   {'messages': -1,  'photos': 15, 'undress': 6,  'call_seconds': 1500, 'voice': 50,  'animations': 0},
    'quarter': {'messages': -1, 'photos': 40, 'undress': 15, 'call_seconds': 3600, 'voice': 120, 'animations': 0},
}


def _env_int(name: str, default: int) -> int:
    try:
        return max(-1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


CAPS = {tier: {k: _env_int(f'CAP_{tier.upper()}_{k.upper()}', v) for k, v in caps.items()}
        for tier, caps in _DEFAULTS.items()}

# Kept for the texts that name the trial's numbers.
TRIAL_MESSAGES = CAPS['trial']['messages']
TRIAL_PHOTOS = CAPS['trial']['photos']
TRIAL_UNDRESS = CAPS['trial']['undress']
TRIAL_CALL_SECONDS = CAPS['trial']['call_seconds']
TRIAL_VOICE = CAPS['trial']['voice']

_PRODUCT_TIER = {
    'premium_trial': 'trial', 'premium_week': 'week', 'premium_week_auto': 'week',
    'premium_month': 'month', 'premium_month_discount': 'month', 'premium_month_vip': 'month',
    'premium_month_auto': 'month', 'premium_quarter': 'quarter',
}

def plan_line(tier: str, en: bool = False) -> str:
    """'. Входит: 15 фото, 6 «Раздеть», …' — what the plan holds, for the shop."""
    c = CAPS[tier]
    parts = []
    if c['photos'] >= 0:
        parts.append(f"{c['photos']} {'photos' if en else 'фото'}")
    if c['undress'] > 0:
        parts.append(f"{c['undress']} {'«Undress»' if en else '«Раздеть»'}")
    if c['call_seconds'] > 0:
        parts.append(f"{c['call_seconds'] // 60} {'call min' if en else 'мин звонка'}")
    if c['voice'] > 0:
        parts.append(f"{c['voice']} {'voice notes' if en else 'голосовых'}")
    if c['animations'] > 0:
        parts.append(f"{c['animations']} {'animations' if en else 'оживления'}")
    if not parts:
        return ''
    return ('. Included: ' if en else '. Входит: ') + ', '.join(parts)


VOICE_EVENT = 'plan_voice'
ANIMATION_EVENT = 'plan_animation'


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _tier_for(sub, product: str | None) -> str:
    if product in _PRODUCT_TIER:
        return _PRODUCT_TIER[product]
    if (sub.telegram_charge_id or '').startswith('demo'):
        return 'demo'
    days = (sub.expires_at - sub.started_at).total_seconds() / 86400 if sub.started_at and sub.expires_at else 30
    if days <= 1:
        return 'demo'
    if days <= 4:
        return 'trial'
    if days <= 10:
        return 'week'
    if days <= 45:
        return 'month'
    return 'quarter'


def plan_uid(uid: int) -> tuple[datetime, dict, list[str]] | None:
    """(window start, summed allowance, tiers) for his active Premium, or None."""
    from models.app_models import StarTransaction, Subscription
    from services.db import SessionLocal
    now = _now()
    with SessionLocal() as s:
        subs = s.scalars(select(Subscription).where(
            Subscription.user_id == uid, Subscription.status == 'active',
            Subscription.expires_at > now)).all()
        if not subs:
            return None
        charges = [x.telegram_charge_id for x in subs if x.telegram_charge_id]
        products = dict(s.execute(select(StarTransaction.telegram_charge_id, StarTransaction.product).where(
            StarTransaction.telegram_charge_id.in_(charges))).all()) if charges else {}
    total = {k: 0 for k in KEYS}
    tiers = []
    for sub in subs:
        tier = _tier_for(sub, products.get(sub.telegram_charge_id))
        tiers.append(tier)
        for k in KEYS:
            if total[k] < 0 or CAPS[tier][k] < 0:
                total[k] = -1  # unlimited wins
            else:
                total[k] += CAPS[tier][k]
    since = min((x.started_at for x in subs if x.started_at), default=now)
    return since, total, tiers


def _uid(telegram_id: int) -> int | None:
    from models.app_models import User
    from services.db import SessionLocal
    with SessionLocal() as s:
        return s.scalar(select(User.id).where(User.telegram_id == str(telegram_id)))


def plan(telegram_id: int):
    try:
        uid = _uid(telegram_id)
        return plan_uid(uid) if uid else None
    except Exception:
        logger.exception('plan caps check failed user=%s', telegram_id)
        return None


def window_start_uid(uid: int) -> datetime | None:
    """Start of his trial window when he is on the trial/demo only, else None."""
    p = plan_uid(uid)
    if not p or any(t not in ('trial', 'demo') for t in p[2]):
        return None
    return p[0]


def window_start(telegram_id: int) -> datetime | None:
    try:
        uid = _uid(telegram_id)
        return window_start_uid(uid) if uid else None
    except Exception:
        logger.exception('trial window check failed user=%s', telegram_id)
        return None


def _events_since(uid: int, event: str, since: datetime, *, sum_value: bool = False) -> int:
    from models.app_models import ProductEvent
    from services.db import SessionLocal
    agg = func.coalesce(func.sum(ProductEvent.value), 0) if sum_value else func.count(ProductEvent.id)
    with SessionLocal() as s:
        return int(s.scalar(select(agg).where(
            ProductEvent.user_id == uid, ProductEvent.event_name == event,
            ProductEvent.created_at >= since)) or 0)


def messages_left(uid: int) -> int | None:
    """None = no Premium; else his messages left in the plan's allowance."""
    p = plan_uid(uid)
    if p is None or p[1]['messages'] < 0:
        return None
    from models.app_models import Message
    from services.db import SessionLocal
    with SessionLocal() as s:
        used = int(s.scalar(select(func.count(Message.id)).where(
            Message.user_id == uid, Message.role == 'user', Message.created_at >= p[0])) or 0)
    return max(0, p[1]['messages'] - used)


def photos_left(uid: int, event: str) -> int | None:
    p = plan_uid(uid)
    if p is None or p[1]['photos'] < 0:
        return None
    return max(0, p[1]['photos'] - _events_since(uid, event, p[0]))


def undress_allowance_today(uid: int, used_today: int) -> int | None:
    """The daily allowance the undress gate compares today's count with, so
    that the plan total holds across days: used_today + what is left."""
    p = plan_uid(uid)
    if p is None or p[1]['undress'] < 0:
        return None
    left = max(0, p[1]['undress'] - _events_since(uid, 'undress_free', p[0]))
    return used_today + left


def call_seconds_left(uid: int, event: str) -> int | None:
    p = plan_uid(uid)
    if p is None or p[1]['call_seconds'] < 0:
        return None
    return max(0, p[1]['call_seconds'] - _events_since(uid, event, p[0], sum_value=True))


def _take(telegram_id: int, key: str, event: str) -> bool:
    try:
        uid = _uid(telegram_id)
        if not uid:
            return True
        p = plan_uid(uid)
        if p is None:
            return True
        if p[1][key] >= 0 and _events_since(uid, event, p[0]) >= p[1][key]:
            return False
        from services.analytics_service import track_event
        track_event(uid, event)
        return True
    except Exception:
        logger.exception('plan cap %s check failed user=%s', key, telegram_id)
        return True


def take_voice(telegram_id: int) -> bool:
    """True when she may send him a voice note now (counts one)."""
    return _take(telegram_id, 'voice', VOICE_EVENT)


def take_animation(telegram_id: int) -> bool:
    """True when one more photo animation fits his plan (counts one)."""
    return _take(telegram_id, 'animations', ANIMATION_EVENT)


def summary(telegram_id: int) -> dict | None:
    """What is left of his plan, for the app (None without Premium)."""
    try:
        uid = _uid(telegram_id)
        p = plan_uid(uid) if uid else None
        if p is None:
            return None
        from services import voice_call
        from services.chat_photo_allowance import EVENT as PHOTO_EVENT
        return {
            'messages': messages_left(uid),
            'photos': photos_left(uid, PHOTO_EVENT),
            'call_minutes': (call_seconds_left(uid, voice_call.EVENT_PREMIUM) or 0) // 60,
            'voice': None if p[1]['voice'] < 0 else max(0, p[1]['voice'] - _events_since(uid, VOICE_EVENT, p[0])),
            'trial': all(t in ('trial', 'demo') for t in p[2]),
        }
    except Exception:
        logger.exception('plan summary failed user=%s', telegram_id)
        return None
