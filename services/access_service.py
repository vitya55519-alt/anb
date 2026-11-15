from datetime import datetime, timezone
from sqlalchemy import select, func
from services.db import SessionLocal
from models.app_models import User, Subscription


def is_premium(telegram_id:int)->bool:
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    with SessionLocal() as s:
        user=s.scalar(select(User).where(User.telegram_id==str(telegram_id)))
        if not user: return False
        return bool(s.scalar(select(func.count()).select_from(Subscription).where(Subscription.user_id==user.id,Subscription.status=="active",Subscription.expires_at>now)))


def can_send_message(telegram_id:int)->bool:
    """V3.166.2: the daily ceiling is hard again — 30 messages a day for the
    whole account, in both modes and on both platforms (owner: «безлимит
    дается только платным подписчикам»). Premium is the only lift, so this is
    the single gate the bot chat, its button taps and the Mini App all ask."""
    if is_premium(telegram_id):
        return True
    from services import daily_limit
    return daily_limit.has_left(telegram_id)
