"""V3.168 (ТЗ блок 5): the first 24 hours are the whole funnel.

Only 20% of new accounts got a life event in their first day (goal 70%).
The life loop already runs hotter for a young account; this module adds the
guarantee: a man who has consented, has no event yet and keeps silent gets one
by NEW_USER_FIRST_EVENT_HOURS after consent — from FIRST_EVENT_HOURS-2 the
scan stops sprinkling at random and just sends. It also feeds the
`new_user_first_event` analytics event and the ritual rule («no ritual in the
first day when her day already wrote»).
"""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select

from config import NEW_USER_FIRST_EVENT_HOURS, NEW_USER_PRIORITY_HOURS
from models.app_models import ProductEvent, UserConsent
from services.db import SessionLocal

logger = logging.getLogger(__name__)

FIRST_EVENT = 'new_user_first_event'
FORCE_LEAD_HOURS = 2.0       # start guaranteeing this long before the deadline


def _naive_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def hours_since_consent(uid: int, account_hours: float | None = None) -> float:
    """Hours since 18+/terms consent; the account age when no row exists."""
    try:
        with SessionLocal() as s:
            at = s.scalar(select(UserConsent.accepted_at).where(
                UserConsent.user_id == int(uid), UserConsent.accepted == True))  # noqa: E712
        if at:
            return max(0.0, (_naive_utc() - at).total_seconds() / 3600.0)
    except Exception:
        logger.debug('consent age read failed user=%s', uid, exc_info=True)
    return float(account_hours or 0.0)


def has_first_event(uid: int) -> bool:
    try:
        with SessionLocal() as s:
            return bool(s.scalar(select(ProductEvent.id).where(
                ProductEvent.user_id == int(uid),
                ProductEvent.event_name.in_(('life_event_sent', FIRST_EVENT))).limit(1)))
    except Exception:
        return True      # unreadable store: never force anything


def state(uid: int, account_hours: float) -> str:
    """'' = not applicable, 'first' = this account still waits for its first
    event, 'force' = it is time to send regardless of the random sprinkle."""
    if account_hours is None or float(account_hours) >= NEW_USER_PRIORITY_HOURS * 3:
        return ''
    if has_first_event(uid):
        return ''
    since = hours_since_consent(uid, account_hours)
    return 'force' if since >= max(0.5, NEW_USER_FIRST_EVENT_HOURS - FORCE_LEAD_HOURS) else 'first'


def note_first_event(uid: int, account_hours: float) -> None:
    """Once per account, at the first delivered life event."""
    try:
        from services.analytics_service import track_event
        try:
            from sqlalchemy import update as _upd
            from models.app_models import User as _U
            from models.app_models import utcnow as _now
            with SessionLocal() as s:
                s.execute(_upd(_U).where(_U.id == int(uid), _U.first_life_event_at.is_(None))
                          .values(first_life_event_at=_now()))
                s.commit()
        except Exception:
            logger.debug('first_life_event_at stamp failed user=%s', uid, exc_info=True)
        track_event(int(uid), FIRST_EVENT, metadata={
            'hours_since_consent': round(hours_since_consent(uid, account_hours), 2),
            'account_hours': round(float(account_hours or 0.0), 2)})
    except Exception:
        logger.debug('first event note failed user=%s', uid, exc_info=True)


def life_event_today(uid: int, tz_name=None) -> bool:
    """Did her day already write to him on HIS calendar day (for the ritual rule)."""
    try:
        from services.push_governor import _local_day_start
        with SessionLocal() as s:
            return bool(s.scalar(select(ProductEvent.id).where(
                ProductEvent.user_id == int(uid), ProductEvent.event_name == 'life_event_sent',
                ProductEvent.created_at >= _local_day_start(tz_name)).limit(1)))
    except Exception:
        return False
