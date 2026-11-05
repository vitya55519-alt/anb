from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func
from services.db import SessionLocal
from models.app_models import User, Message, Subscription
from config import FREE_LATE_FROM_DAY, FREE_MESSAGES_PER_DAY, FREE_MESSAGES_PER_DAY_LATE, NEW_USER_UNLIMITED_HOURS

def is_premium(telegram_id:int)->bool:
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    with SessionLocal() as s:
        user=s.scalar(select(User).where(User.telegram_id==str(telegram_id)))
        if not user: return False
        return bool(s.scalar(select(func.count()).select_from(Subscription).where(Subscription.user_id==user.id,Subscription.status=="active",Subscription.expires_at>now)))

def free_limit_for(created_at, now=None)->int:
    """V3.106.0: 20 a day for his first days, FREE_MESSAGES_PER_DAY_LATE from
    day FREE_LATE_FROM_DAY after sign-up (day 1 = the sign-up day, UTC)."""
    if not created_at:
        return FREE_MESSAGES_PER_DAY
    now=now or datetime.now(timezone.utc).replace(tzinfo=None)
    day=(now.date()-created_at.date()).days+1
    if day >= FREE_LATE_FROM_DAY:
        return min(FREE_MESSAGES_PER_DAY, FREE_MESSAGES_PER_DAY_LATE)
    return FREE_MESSAGES_PER_DAY


def can_send_message(telegram_id:int)->bool:
    if is_premium(telegram_id): return True
    now=datetime.now(timezone.utc); start=now.replace(hour=0,minute=0,second=0,microsecond=0).replace(tzinfo=None)
    with SessionLocal() as s:
        user=s.scalar(select(User).where(User.telegram_id==str(telegram_id)))
        if not user: return True
        # V3.47.2: unlimited text for the first NEW_USER_UNLIMITED_HOURS after
        # registration (activation window). Text only — photos stay gated.
        if NEW_USER_UNLIMITED_HOURS and user.created_at:
            if datetime.now(timezone.utc).replace(tzinfo=None) < user.created_at + timedelta(hours=NEW_USER_UNLIMITED_HOURS):
                return True
        count=s.scalar(select(func.count()).select_from(Message).where(Message.user_id==user.id,Message.role=="user",Message.created_at>=start)) or 0
        return count < free_limit_for(user.created_at)


def unlimited_text_remaining(telegram_id:int)->int:
    """V3.47.2: seconds left in a new user's unlimited-text window (0 when the
    offer is off, the user is premium, or the window already elapsed)."""
    if not NEW_USER_UNLIMITED_HOURS or is_premium(telegram_id):
        return 0
    with SessionLocal() as s:
        user=s.scalar(select(User).where(User.telegram_id==str(telegram_id)))
        if not user or not user.created_at:
            return 0
        ends=user.created_at + timedelta(hours=NEW_USER_UNLIMITED_HOURS)
        remaining=(ends-datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds()
        return int(remaining) if remaining > 0 else 0
