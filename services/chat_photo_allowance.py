"""V3.61.5: the daily free chat photos («2 фото в сутки бесплатно»).

Every photo she sends inside a chat — asked for or promised by her («лови»,
«шлю ещё фотку») — first uses today's free allowance (all girls together),
and only then costs CHAT_PHOTO_PEACH_COST peaches. Counted from product events,
so no new table is needed.
"""
from __future__ import annotations

from datetime import datetime, time, timezone

from sqlalchemy import func, select

from config import CHAT_FREE_PHOTOS_PER_DAY
from models.app_models import ProductEvent
from services.db import SessionLocal

EVENT = 'chat_free_photo'


def _day_start() -> datetime:
    today = datetime.now(timezone.utc).date()
    return datetime.combine(today, time.min)


def free_chat_photos_used(uid: int) -> int:
    with SessionLocal() as session:
        return int(session.scalar(
            select(func.count(ProductEvent.id)).where(
                ProductEvent.user_id == uid, ProductEvent.event_name == EVENT,
                ProductEvent.created_at >= _day_start())
        ) or 0)


def free_chat_photos_left(uid: int) -> int:
    try:
        return max(0, CHAT_FREE_PHOTOS_PER_DAY - free_chat_photos_used(uid))
    except Exception:
        return 0


def use_free_chat_photo(uid: int, character_id: str) -> None:
    with SessionLocal() as session:
        session.add(ProductEvent(user_id=uid, character_id=character_id, event_name=EVENT,
                                 created_at=datetime.now(timezone.utc).replace(tzinfo=None)))
        session.commit()
