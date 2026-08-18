import datetime as dt, re, logging
from zoneinfo import ZoneInfo
from sqlalchemy import select
from services.db import SessionLocal
from models.app_models import Reminder, User
from services.user_service import ensure_user, get_user, update_user_settings

logger = logging.getLogger(__name__)

# Auto-detect timezone from communication language when user hasn't set one explicitly.
# Prevents the common bug where Russian speakers get reminders 3 hours late (UTC vs MSK).
_LANG_TZ_DEFAULTS = {
    'ru': 'Europe/Moscow',
    'uk': 'Europe/Kyiv',
    'en': 'America/New_York',
    'es': 'Europe/Madrid',
    'de': 'Europe/Berlin',
    'fr': 'Europe/Paris',
    'it': 'Europe/Rome',
    'pt': 'Europe/Lisbon',
    'zh': 'Asia/Shanghai',
    'ja': 'Asia/Tokyo',
    'ko': 'Asia/Seoul',
}


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
            detected_tz = _LANG_TZ_DEFAULTS.get(lang)
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
    uid=ensure_user(telegram_id); user=get_user(telegram_id)
    resolved_tz = _resolve_timezone(telegram_id, user, hint_text=text)
    try: tz=ZoneInfo(resolved_tz)
    except Exception: tz=ZoneInfo('UTC')
    h,m,days=parsed; now=dt.datetime.now(tz); target=now.replace(hour=h,minute=m,second=0,microsecond=0)+dt.timedelta(days=days)
    if target<=now: target+=dt.timedelta(days=1)
    kind='wake' if any(x in text.lower() for x in ('разбуди','буди','wake')) else 'reminder'
    with SessionLocal() as s:
        row=Reminder(user_id=uid,reminder_type=kind,text='Пора вставать' if kind=='wake' else text.strip(),due_at_utc=target.astimezone(dt.timezone.utc).replace(tzinfo=None),timezone=resolved_tz,max_attempts=6 if kind=='wake' else 1)
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
