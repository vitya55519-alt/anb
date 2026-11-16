"""V3.159.0: push diet (owner review of the 13.11 dump).

One rule, checked at every unsolicited send: she never writes a man while he
is asleep, and she never drops a burst of first messages into one window.

V3.162.0 turned that into «two first writes a day, total». V3.167.0 (owner
16.11 «разрешаю по пушам») splits the day by RAIL instead: counting every rail
in one bucket is exactly what let 2149 life moments strangle her morning and
evening line — the two messages the owner actually asked for. So each family
spends its own budget, the ritual lines no longer consume the burst window
(they are anchored to the clock, not to each other), and every refusal is
logged with its reason, because an invisible «held back» is indistinguishable
from a job that never ran.

The dump: 15.7% of all first-writes landed between 23:00 and 07:00 local time
(compatibility forecast 42%, donation ping 40%, random gift 34%), and 23% of
them arrived in a window that already had a push in it. The rails that check
the clock (life events, rituals) were fine — the scheduler jobs that fire on a
UTC cron simply never looked at the man's timezone.
"""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import func, select

from config import (
    LIFE_EVENTS_MAX_PER_DAY,
    LIFE_EVENTS_QUIET_END_HOUR,
    LIFE_EVENTS_QUIET_START_HOUR,
    PUSH_MAX_IN_WINDOW,
    PUSH_MAX_PER_DAY,
    PUSH_SPACING_WINDOW_MINUTES,
    RITUAL_BUDGET_PER_DAY,
    SCENARIO_BUDGET_PER_DAY,
)
from models.app_models import ProductEvent
from services.db import SessionLocal

logger = logging.getLogger(__name__)

# Что считается «она написала первой». Компаньоны вида *_photo_sent висят на том
# же пуше и не считаются. Сгруппировано V3.167.0: у каждой семьи свой бюджет дня.
RITUAL_PUSHES = ('ritual_morning_sent', 'ritual_evening_sent', 'morning_voice_sent', 'evening_voice_sent',
                 'morning_callback_sent', 'evening_callback_sent')
LIFE_PUSHES = ('life_event_sent',)
SCENARIO_PUSHES = ('scenario_card_sent',)
MARKETING_PUSHES = ('proactive_sent', 'retention_push_sent', 'donation_reminder_sent',
                    'story_hook_sent', 'random_gift_sent', 'whats_new_sent', 'whats_new_sent_ok',
                    'compatibility_forecast_sent', 'welcome_selfie_sent', 'voice_cast_sent',
                    'partner_nudge_sent', 'day1_hook_sent', 'care_followup_sent', 'first_offer_sent',
                    'trial_followup_sent', 'heavy_offer_sent_ok', 'renewal_care_sent',
                    'first_minutes_nudge_sent')

PUSH_EVENTS = RITUAL_PUSHES + LIFE_PUSHES + SCENARIO_PUSHES + MARKETING_PUSHES
FAMILY_EVENTS = {'ritual': RITUAL_PUSHES, 'life': LIFE_PUSHES,
                 'scenario': SCENARIO_PUSHES, 'marketing': MARKETING_PUSHES}
# Her two lines are hour-anchored, so they never spend anyone's burst window.
SPACED_PUSHES = tuple(e for e in PUSH_EVENTS if e not in RITUAL_PUSHES)


def rail_budget(family: str) -> int:
    """Today's money for one rail family (module globals, so tests and the
    kitchen can move a single knob without touching the others)."""
    if family == 'ritual':
        return RITUAL_BUDGET_PER_DAY
    if family == 'life':
        return LIFE_EVENTS_MAX_PER_DAY
    if family == 'scenario':
        return SCENARIO_BUDGET_PER_DAY
    return PUSH_MAX_PER_DAY


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
    """V3.167.0: the burst window belongs to the rails that fire on a scan —
    her two clock-anchored ritual lines are not in it and spend nothing."""
    minutes = max(0, int(PUSH_SPACING_WINDOW_MINUTES or 0))
    if not db_user_id or minutes <= 0:
        return 0
    since = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(minutes=minutes)
    try:
        with SessionLocal() as s:
            return int(s.scalar(
                select(func.count(ProductEvent.id)).where(
                    ProductEvent.user_id == int(db_user_id),
                    ProductEvent.event_name.in_(SPACED_PUSHES),
                    ProductEvent.created_at >= since,
                )
            ) or 0)
    except Exception:
        return 0


def _local_day_start(tz_name) -> dt.datetime:
    """Midnight of HIS calendar day, as the naive UTC the events are stored in."""
    utc = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    try:
        from zoneinfo import ZoneInfo
        local = utc.replace(tzinfo=dt.timezone.utc).astimezone(ZoneInfo(tz_name or 'UTC'))
        return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(
            dt.timezone.utc).replace(tzinfo=None)
    except Exception:
        return utc.replace(hour=0, minute=0, second=0, microsecond=0)


def pushes_today(db_user_id: int, tz_name=None, family: str = 'marketing') -> int:
    """V3.167.0: counted on HIS clock, and per rail family — the day is no
    longer one shared bucket, which is precisely how «жизнь без тебя» used to
    drink her morning and evening line dry."""
    if not db_user_id or rail_budget(family) <= 0:
        return 0
    since = _local_day_start(tz_name)
    try:
        with SessionLocal() as s:
            return int(s.scalar(
                select(func.count(ProductEvent.id)).where(
                    ProductEvent.user_id == int(db_user_id),
                    ProductEvent.event_name.in_(FAMILY_EVENTS.get(family) or PUSH_EVENTS),
                    ProductEvent.created_at >= since,
                )
            ) or 0)
    except Exception:
        return 0


def allow_push(db_user_id: int, tz_name=None, family: str = 'marketing') -> tuple[bool, str]:
    """(ok, reason). reason is 'night' | 'burst' | 'daily' | '' — every refusal
    is logged with the rail and the man, so «the governor held it» is no longer
    indistinguishable from «the job never ran»."""
    hour = local_hour(tz_name)
    if in_quiet_hours(hour):
        return _deny(db_user_id, family, 'night')
    if family != 'ritual' and PUSH_MAX_IN_WINDOW > 0 \
            and pushes_in_window(int(db_user_id or 0)) >= PUSH_MAX_IN_WINDOW:
        return _deny(db_user_id, family, 'burst')
    if rail_budget(family) > 0 and pushes_today(int(db_user_id or 0), tz_name, family) >= rail_budget(family):
        return _deny(db_user_id, family, 'daily')
    return True, ''


def _deny(db_user_id, family: str, reason: str) -> tuple[bool, str]:
    logger.info('push held user=%s rail=%s reason=%s', db_user_id, family, reason)
    _note_denial(db_user_id, family, reason)
    return False, reason


#: V3.167.5 §9 (владелец ТЗ): «push_denied(rail, reason)». Отказов в сотни раз
#: больше, чем отправок: сканер спрашивает каждый час, и молчащий аккаунт
#: получает «night» или «daily» на каждом витке. В product_events это лилась бы
#: тысячами строк в сутки, поэтому один (аккаунт, рельс, причина) пишется ровно
#: раз за его сутки — ровно столько, чтобы отличить «губернатор держит» от
#: «джоба не завелась», и не больше.
DENIAL_EVENT = 'push_denied'
_denial_memo: dict[tuple[int, str, str], str] = {}


def _already_denied(db_user_id: int, family: str, reason: str, today: str) -> bool:
    if _denial_memo.get((db_user_id, family, reason)) == today:
        return True                     # тот же отказ в этом процессе — без запроса
    try:
        needle = f'"rail": "{family}", "reason": "{reason}"'
        with SessionLocal() as s:
            hit = bool(s.scalar(select(ProductEvent.id).where(
                ProductEvent.user_id == db_user_id,
                ProductEvent.event_name == DENIAL_EVENT,
                ProductEvent.created_at >= _local_day_start(None),
                ProductEvent.metadata_json.like(f'%{needle}%'),
            ).limit(1)))
    except Exception:
        return False
    if hit:
        _remember_denial(db_user_id, family, reason, today)
    return hit


def _remember_denial(db_user_id: int, family: str, reason: str, today: str) -> None:
    if len(_denial_memo) > 20000:       # ключей на одного молчащего в сутки три
        _denial_memo.clear()
    _denial_memo[(db_user_id, family, reason)] = today


def _note_denial(db_user_id, family: str, reason: str) -> None:
    uid = int(db_user_id or 0)
    if uid <= 0:
        return
    try:
        today = dt.date.today().isoformat()
        if _already_denied(uid, family, reason, today):
            return
        from services.analytics_service import track_event
        track_event(uid, DENIAL_EVENT, metadata={'rail': family, 'reason': reason})
        _remember_denial(uid, family, reason, today)
    except Exception:
        logger.debug('push denial journal failed user=%s', uid, exc_info=True)
