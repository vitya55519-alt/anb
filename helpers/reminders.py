import datetime as dt
import re
from zoneinfo import ZoneInfo
from .db_interaction import create_reminder, get_character_state


def _tz(user_id):
    state = get_character_state(user_id)
    try:
        return ZoneInfo(state.timezone or 'UTC'), state.timezone or 'UTC'
    except Exception:
        return ZoneInfo('UTC'), 'UTC'


def set_timezone(user_id, timezone_name: str):
    ZoneInfo(timezone_name)
    from .db_interaction import update_character_state
    update_character_state(user_id, timezone=timezone_name)


def parse_time_request(text: str):
    """Return (hour, minute, days_ahead) for simple wake/reminder phrases, else None."""
    t = text.lower().strip()
    if not any(k in t for k in ('wake', 'wake me', 'alarm', 'remind me', 'despierta', 'despertarme', 'recuérdame', 'recuerdame', 'буди', 'разбуди', 'напомни')):
        return None
    m = re.search(r'\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b', t)
    if not m:
        return None
    hour = int(m.group(1)); minute = int(m.group(2) or 0); ampm = m.group(3)
    if ampm == 'pm' and hour < 12: hour += 12
    if ampm == 'am' and hour == 12: hour = 0
    if hour > 23 or minute > 59: return None
    days_ahead = 1 if any(x in t for x in ('tomorrow', 'mañana', 'manana', 'завтра')) else 0
    return hour, minute, days_ahead


def create_wake_from_text(user_id: int, text: str):
    parsed = parse_time_request(text)
    if not parsed:
        return None
    hour, minute, days_ahead = parsed
    tz, tz_name = _tz(user_id)
    now = dt.datetime.now(tz)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0) + dt.timedelta(days=days_ahead)
    if target <= now:
        target += dt.timedelta(days=1)
    wake = any(x in text.lower() for x in ('wake', 'despierta', 'despertarme', 'буди', 'разбуди'))
    kind = 'wake' if wake else 'reminder'
    label = 'wake up' if wake else text.strip()
    return create_reminder(user_id, kind, label, target.astimezone(dt.timezone.utc), tz_name, max_attempts=6 if wake else 1)
