import datetime as dt, re
from zoneinfo import ZoneInfo
from sqlalchemy import select
from services.db import SessionLocal
from models.app_models import Reminder, User
from services.user_service import ensure_user, get_user, update_user_settings

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
    try: tz=ZoneInfo(user.timezone or 'UTC')
    except Exception: tz=ZoneInfo('UTC')
    h,m,days=parsed; now=dt.datetime.now(tz); target=now.replace(hour=h,minute=m,second=0,microsecond=0)+dt.timedelta(days=days)
    if target<=now: target+=dt.timedelta(days=1)
    kind='wake' if any(x in text.lower() for x in ('разбуди','буди','wake')) else 'reminder'
    with SessionLocal() as s:
        row=Reminder(user_id=uid,reminder_type=kind,text='Пора вставать' if kind=='wake' else text.strip(),due_at_utc=target.astimezone(dt.timezone.utc).replace(tzinfo=None),timezone=user.timezone or 'UTC',max_attempts=6 if kind=='wake' else 1)
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
