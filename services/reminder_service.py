import datetime as dt, re, logging
from zoneinfo import ZoneInfo
from sqlalchemy import func, select
from services.db import SessionLocal
from models.app_models import Reminder, User
from services.user_service import ensure_user, get_user, update_user_settings
from config import LANG_TZ_DEFAULTS

logger = logging.getLogger(__name__)


def _resolve_timezone(telegram_id: int, user, hint_text: str | None = None) -> str:
    """Return user's timezone, auto-detecting from language if still default UTC."""
    tz = getattr(user, 'timezone', None) or 'UTC'
    if tz != 'UTC':
        return tz
    # Timezone is still default — try to infer from detected language.
    try:
        from services.adaptation_service import get_profile, detect_language
        profile = get_profile(telegram_id)
        lang = None
        if profile and profile.preferred_language and profile.preferred_language != 'auto':
            lang = profile.preferred_language
        elif hint_text:
            lang, _ = detect_language(hint_text)
        if lang and lang != 'auto':
            detected_tz = LANG_TZ_DEFAULTS.get(lang)
            if detected_tz:
                update_user_settings(telegram_id, timezone=detected_tz)
                logger.info('auto-set timezone=%s for user=%s (lang=%s)', detected_tz, telegram_id, lang)
                return detected_tz
    except Exception:
        pass
    return tz

def set_timezone(telegram_id:int, timezone_name:str):
    ZoneInfo(timezone_name); ensure_user(telegram_id); update_user_settings(telegram_id, timezone=timezone_name)

def parse_time_request(text:str):
    t=(text or '').lower().strip()
    if not any(k in t for k in ('разбуди','буди','напомни','wake','remind')): return None
    m=re.search(r'\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b',t)
    if not m: return None
    h=int(m.group(1)); minute=int(m.group(2) or 0); ap=m.group(3)
    if ap=='pm' and h<12: h+=12
    if ap=='am' and h==12: h=0
    if h>23 or minute>59: return None
    return h, minute, 1 if any(x in t for x in ('завтра','tomorrow')) else 0

def create_from_text(telegram_id:int,text:str):
    parsed=parse_time_request(text)
    if not parsed: return None
    h,m,days=parsed
    return create_at(telegram_id, 'wake' if is_wake_request(text) else 'reminder', text, h, m, days)


_CLOCK_RE = re.compile(r'\b(\d{1,2})[:.]\s*(\d{1,2})\b')

_BARE_HOUR_RE = re.compile(r'\b(\d{1,2})\b')
_PM_WORDS = ('вечера', 'вечером', 'вечер', 'pm', 'после полудня')
_NIGHT_WORDS = ('ночи', 'ночь', 'полночь', 'midnight')
_NOON_WORDS = ('полдень', 'полдня', 'noon', 'дня')
_DAYS_WORDS = ('завтра', 'tomorrow', 'послезавтра')


def parse_clock_text(text: str):
    """V3.149.0: the FSM answer to «на какое время?» — nobody should type a
    command for a button press, so «08:00», «8:30», «8 утра», «12 ночи»,
    «20:15 pm» and «завтра в 9» all count. Returns (hour, minute, days) or None."""
    t = (text or '').lower().strip()
    if not t:
        return None
    m = _CLOCK_RE.search(t)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        ap = ''
    else:
        m2 = _BARE_HOUR_RE.search(t)
        if not m2:
            # «полдень» and «полночь» without a single digit still mean a time.
            if any(w in t for w in ('полдень', 'noon')):
                return 12, 0, 1 if any(w in t for w in _DAYS_WORDS) else 0
            if any(w in t for w in ('полночь', 'midnight')):
                return 0, 0, 1 if any(w in t for w in _DAYS_WORDS) else 0
            return None
        h, mi = int(m2.group(1)), 0
        ap = 'pm' if 'pm' in t else ('am' if 'am' in t else '')
    if ap == 'pm' and h < 12:
        h += 12
    if ap == 'am' and h == 12:
        h = 0
    if h > 23 or mi > 59:
        return None
    if any(w in t for w in _PM_WORDS) and h < 12:
        h += 12
    if any(w in t for w in _NIGHT_WORDS) and h in (12, 0):
        h = 0
    if any(w in t for w in _NOON_WORDS) and h == 12:
        h = 12
    days = 2 if 'послезавтра' in t else (1 if any(w in t for w in _DAYS_WORDS) else 0)
    return h, mi, days


def reminder_body(text: str) -> str:
    """The words the user wants remembered — everything except the time itself."""
    t = _CLOCK_RE.sub(' ', (text or '').strip())
    t = re.sub(r'\s+', ' ', t).strip(' .,!?-')
    for word in ('напомни мне', 'напомни', 'напомнить', 'напоминание', 'напоминание о', 'мне', 'про',
                 'about', 'please', 'remind', 'me', 'завтра', 'послезавтра', 'tomorrow',
                 'в', 'у', 'к', 'на', 'at', 'around'):
        t = re.sub(r'^(' + re.escape(word) + r')\s+', '', t, count=1, flags=re.I)
    return (t or (text or '').strip())[:200]


def create_at(telegram_id:int, kind:str, text:str, hour:int, minute:int, days:int=0):
    """V3.149.0: one row-building path for both entries — the free-text parser
    and the button FSM schedule through here, so the timezone resolution and
    the «already passed → tomorrow» roll-over can never drift apart."""
    uid = ensure_user(telegram_id); user = get_user(telegram_id)
    resolved_tz = _resolve_timezone(telegram_id, user, hint_text=text)
    try: tz = ZoneInfo(resolved_tz)
    except Exception: tz = ZoneInfo('UTC')
    now = dt.datetime.now(tz)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0) + dt.timedelta(days=days)
    if target <= now: target += dt.timedelta(days=1)
    body = 'Пора вставать' if kind == 'wake' else ((text or '').strip()[:200] or 'Напоминание')
    with SessionLocal() as s:
        row = Reminder(user_id=uid, reminder_type=kind, text=body[:200],
                       due_at_utc=target.astimezone(dt.timezone.utc).replace(tzinfo=None),
                       timezone=resolved_tz, max_attempts=6 if kind == 'wake' else 1)
        s.add(row); s.commit(); return row.id

def cancel_active_wake(telegram_id:int):
    user=get_user(telegram_id)
    if not user: return
    with SessionLocal() as s:
        rows=s.scalars(select(Reminder).where(Reminder.user_id==user.id,Reminder.reminder_type=='wake',Reminder.active==True)).all()
        for r in rows:
            if r.attempts>0: r.active=False
        s.commit()

def due_reminders():
    now=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    with SessionLocal() as s:
        return s.scalars(select(Reminder).where(Reminder.active==True,Reminder.due_at_utc<=now)).all()

def mark_after_send(reminder_id:int, final:bool=False, delay_minutes:int=3):
    with SessionLocal() as s:
        r=s.get(Reminder,reminder_id)
        if not r: return
        r.attempts+=1
        if final or r.attempts>=r.max_attempts: r.active=False
        else: r.due_at_utc=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)+dt.timedelta(minutes=delay_minutes)
        s.commit()

def is_wake_request(text:str)->bool:
    """V3.63.2: a parseable «разбуди в 8:00» (not a plain reminder)."""
    return bool(parse_time_request(text)) and any(x in (text or '').lower() for x in ('разбуди','буди','wake'))

def wake_trial_available(telegram_id:int)->bool:
    """V3.63.2: one free alarm ever for non-Premium users, so they hear her
    wake them before deciding on Premium. Counted from existing rows — no schema."""
    user=get_user(telegram_id)
    if not user: return True
    with SessionLocal() as s:
        used=s.scalar(select(func.count()).select_from(Reminder).where(Reminder.user_id==user.id,Reminder.reminder_type=='wake'))
    return not used
