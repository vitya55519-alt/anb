from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func
from services.db import SessionLocal
from models.app_models import User, Message, Subscription
from config import FREE_MESSAGES_PER_DAY, NEW_USER_UNLIMITED_HOURS

def is_premium(telegram_id:int)->bool:
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    with SessionLocal() as s:
        user=s.scalar(select(User).where(User.telegram_id==str(telegram_id)))
        if not user: return False
        return bool(s.scalar(select(func.count()).select_from(Subscription).where(Subscription.user_id==user.id,Subscription.status=="active",Subscription.expires_at>now)))

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
        return count < FREE_MESSAGES_PER_DAY


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
