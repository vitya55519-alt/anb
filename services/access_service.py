from datetime import datetime, timezone
from sqlalchemy import select, func
from services.db import SessionLocal
from models.app_models import User, Message, Subscription
from config import FREE_MESSAGES_PER_DAY

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
        count=s.scalar(select(func.count()).select_from(Message).where(Message.user_id==user.id,Message.role=="user",Message.created_at>=start)) or 0
        return count < FREE_MESSAGES_PER_DAY
