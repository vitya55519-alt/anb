"""V3.159.0: push diet (owner review of the 13.11 dump).

One rule, checked at every unsolicited send: she never writes a man while he
is asleep, and she never drops three messages into the same two hours.

The dump: 15.7% of all first-writes landed between 23:00 and 07:00 local time
(compatibility forecast 42%, donation ping 40%, random gift 34%), and 23% of
them arrived in a window that already had a push in it. The rails that check
the clock (life events, rituals) were fine — the scheduler jobs that fire on a
UTC cron simply never looked at the man's timezone.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select

from config import (
    LIFE_EVENTS_QUIET_END_HOUR,
    LIFE_EVENTS_QUIET_START_HOUR,
    PUSH_MAX_IN_WINDOW,
    PUSH_SPACING_WINDOW_MINUTES,
)
from models.app_models import ProductEvent
from services.db import SessionLocal

# What counts as «она написала первой». Только самостоятельные сообщения:
# компаньоны вида *_photo_sent висят на том же пуше и не считаются.
PUSH_EVENTS = (
    'ritual_morning_sent', 'ritual_evening_sent', 'morning_voice_sent', 'evening_voice_sent',
    'life_event_sent', 'proactive_sent', 'retention_push_sent', 'donation_reminder_sent',
    'story_hook_sent', 'random_gift_sent', 'whats_new_sent', 'compatibility_forecast_sent',
    'welcome_selfie_sent', 'voice_cast_sent', 'partner_nudge_sent', 'day1_hook_sent',
    'care_followup_sent',
)


def local_hour(tz_name) -> int:
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo(tz_name or 'UTC')).hour
    except Exception:
        return dt.datetime.now(dt.timezone.utc).hour


def in_quiet_hours(hour: int) -> bool:
    """Wrap-aware sleeping window [start, end): 23→7 blocks 23,0..6."""
    start, end = LIFE_EVENTS_QUIET_START_HOUR, LIFE_EVENTS_QUIET_END_HOUR
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def pushes_in_window(db_user_id: int) -> int:
    minutes = max(0, int(PUSH_SPACING_WINDOW_MINUTES or 0))
    if not db_user_id or minutes <= 0:
        return 0
    since = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(minutes=minutes)
    try:
        with SessionLocal() as s:
            return int(s.scalar(
                select(func.count(ProductEvent.id)).where(
                    ProductEvent.user_id == int(db_user_id),
                    ProductEvent.event_name.in_(PUSH_EVENTS),
                    ProductEvent.created_at >= since,
                )
            ) or 0)
    except Exception:
        return 0


def allow_push(db_user_id: int, tz_name=None) -> tuple[bool, str]:
    """(ok, reason). reason is 'night' | 'burst' | '' — callers only log it."""
    hour = local_hour(tz_name)
    if in_quiet_hours(hour):
        return False, 'night'
    if PUSH_MAX_IN_WINDOW > 0 and pushes_in_window(int(db_user_id or 0)) >= PUSH_MAX_IN_WINDOW:
        return False, 'burst'
    return True, ''
