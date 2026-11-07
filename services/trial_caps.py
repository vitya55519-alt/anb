"""V3.124.0: owner — «пробный прогорает, там сразу всё есть». The cheap
first-purchase trial (and the free demo) is a short Premium; without caps one
active man burned 3–4× its price in MiniMax replies, renders and call minutes.

A man is «on a trial» while every active Premium subscription he holds is
short (≤ TRIAL_TIER_MAX_HOURS). For the whole trial window (from the start of
that subscription) he gets fixed totals, not daily ones:

  TRIAL_MESSAGES     his messages (then the usual sleep wall → full Premium)
  TRIAL_PHOTOS       new chat photos
  TRIAL_UNDRESS      «Раздеть»
  TRIAL_CALL_SECONDS Premium call seconds
  TRIAL_VOICE        her voice notes (auto voice replies + «🔊 Озвучить»)

Everything is counted from rows that already exist (messages, product
events), so no table is needed. Every helper fails open to «not a trial»
only on a DB error, never silently granting a longer plan's limits to a
trial — callers treat None as «normal Premium rules».
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

logger = logging.getLogger(__name__)


def _int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return default


TRIAL_TIER_MAX_HOURS = _int('TRIAL_TIER_MAX_HOURS', 96)
TRIAL_MESSAGES = _int('TRIAL_MESSAGES', 100)
TRIAL_PHOTOS = _int('TRIAL_PHOTOS', 2)
TRIAL_UNDRESS = _int('TRIAL_UNDRESS', 1)
TRIAL_CALL_SECONDS = _int('TRIAL_CALL_SECONDS', 300)
TRIAL_VOICE = _int('TRIAL_VOICE', 10)

VOICE_EVENT = 'trial_voice'


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def window_start_uid(uid: int) -> datetime | None:
    """Start of his trial window, or None when he is not on a short plan
    (no Premium at all, or any active plan longer than the trial tier)."""
    from models.app_models import Subscription
    from services.db import SessionLocal
    now = _now()
    with SessionLocal() as s:
        subs = s.scalars(select(Subscription).where(
            Subscription.user_id == uid, Subscription.status == 'active',
            Subscription.expires_at > now)).all()
    if not subs:
        return None
    limit = timedelta(hours=TRIAL_TIER_MAX_HOURS)
    starts = []
    for sub in subs:
        if not sub.started_at or not sub.expires_at:
            return None
        if sub.expires_at - sub.started_at > limit:
            return None
        starts.append(sub.started_at)
    return min(starts)


def _uid(telegram_id: int) -> int | None:
    from models.app_models import User
    from services.db import SessionLocal
    with SessionLocal() as s:
        return s.scalar(select(User.id).where(User.telegram_id == str(telegram_id)))


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
    """None = not on a trial; else his messages left in the trial window."""
    since = window_start_uid(uid)
    if since is None:
        return None
    from models.app_models import Message
    from services.db import SessionLocal
    with SessionLocal() as s:
        used = int(s.scalar(select(func.count(Message.id)).where(
            Message.user_id == uid, Message.role == 'user', Message.created_at >= since)) or 0)
    return max(0, TRIAL_MESSAGES - used)


def photos_left(uid: int, event: str) -> int | None:
    since = window_start_uid(uid)
    if since is None:
        return None
    return max(0, TRIAL_PHOTOS - _events_since(uid, event, since))


def undress_allowance_today(uid: int, used_today: int) -> int | None:
    """The daily allowance the undress gate compares today's count with, so
    that the trial total holds across days: used_today + what is left."""
    since = window_start_uid(uid)
    if since is None:
        return None
    left = max(0, TRIAL_UNDRESS - _events_since(uid, 'undress_free', since))
    return used_today + left


def call_seconds_left(uid: int, event: str) -> int | None:
    since = window_start_uid(uid)
    if since is None:
        return None
    return max(0, TRIAL_CALL_SECONDS - _events_since(uid, event, since, sum_value=True))


def take_voice(telegram_id: int) -> bool:
    """True when she may send him a voice note now. Not on a trial → True
    (normal rules apply). On a trial → counts one against TRIAL_VOICE."""
    try:
        uid = _uid(telegram_id)
        if not uid:
            return True
        since = window_start_uid(uid)
        if since is None:
            return True
        if _events_since(uid, VOICE_EVENT, since) >= TRIAL_VOICE:
            return False
        from services.analytics_service import track_event
        track_event(uid, VOICE_EVENT)
        return True
    except Exception:
        logger.exception('trial voice check failed user=%s', telegram_id)
        return True
