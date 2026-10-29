"""V3.61.5: the daily free chat photos («2 фото в сутки бесплатно»).

Every photo she sends inside a chat — asked for or promised by her («лови»,
«шлю ещё фотку») — first uses today's free allowance (all girls together),
and only then costs CHAT_PHOTO_PEACH_COST peaches. Counted from product events,
so no new table is needed.
"""
from __future__ import annotations

import re
from datetime import datetime, time, timezone

from sqlalchemy import func, select

from config import (CHAT_FREE_PHOTOS_PER_DAY, CHAT_PREMIUM_PHOTOS_PER_DAY, FREE_PHOTO_COST_USD,
                    FREE_PHOTO_DAILY_BUDGET_USD)
from models.app_models import ProductEvent
from services.db import SessionLocal

EVENT = 'chat_free_photo'
# V3.81.0: a free photo served from the pool after the daily budget ran out.
POOL_EVENT = 'chat_free_photo_pool'


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


def daily_free_photos(premium: bool) -> int:
    """V3.93.0: 1 a day without Premium, 2 with it."""
    return CHAT_PREMIUM_PHOTOS_PER_DAY if premium else CHAT_FREE_PHOTOS_PER_DAY


def free_chat_photos_left(uid: int, premium: bool = False) -> int:
    try:
        return max(0, daily_free_photos(premium) - free_chat_photos_used(uid))
    except Exception:
        return 0


# A chat photo rendered for someone else may be lingerie / nude (Premium) —
# never reuse one whose request reads that way.
_SPICY_PROMPT = re.compile(
    r'(гол(ая|ую|ой|еньк)|обнаж|без одежды|разде|бель[её]|трусик|лифчик|сиськ|грудь|соск|киск|попк|'
    r'наедине|секс|пошл|nude|naked|lingerie|topless|boobs|panties)', re.I)


def reused_photo(character_id: str, uid: int | None = None) -> tuple[bytes, str, str] | None:
    """V3.93.0: (bytes, mime, ext) of a photo of her that already exists — her
    pool first, then a chat photo already rendered of her for anyone (owner:
    «используй сгенерированные фотки, они же есть в одной базе»). $0."""
    try:
        from services.retention_features_service import random_proactive_photo
        picked = random_proactive_photo(character_id, user_id=uid)
        if picked and picked[2] == 'photo':
            data, mime, _kind = picked
            return data, *(('image/png', 'png') if 'png' in (mime or '') else ('image/jpeg', 'jpg'))
    except Exception:
        pass
    try:
        import random
        from models.app_models import ChatMedia, UserGeneration
        with SessionLocal() as session:
            rows = session.execute(
                select(UserGeneration.filename, UserGeneration.prompt)
                .where(UserGeneration.kind == 'photo', UserGeneration.character_id == character_id,
                       UserGeneration.filename.is_not(None),
                       (UserGeneration.engine.is_(None)) | (UserGeneration.engine != 'error'))
                .order_by(UserGeneration.id.desc()).limit(300)
            ).all()
            names = [r.filename for r in rows if not _SPICY_PROMPT.search(r.prompt or '')]
            random.shuffle(names)
            for name in names[:10]:
                media = session.execute(
                    select(ChatMedia.data, ChatMedia.content_type).where(ChatMedia.filename == name).limit(1)
                ).first()
                ctype = (media.content_type or '') if media else ''
                if media and media.data and ctype.startswith('image/'):
                    ext = {'image/png': 'png', 'image/webp': 'webp'}.get(ctype, 'jpg')
                    return media.data, (ctype if ext != 'jpg' else 'image/jpeg'), ext
    except Exception:
        pass
    return None


def use_free_chat_photo(uid: int, character_id: str) -> None:
    with SessionLocal() as session:
        session.add(ProductEvent(user_id=uid, character_id=character_id, event_name=EVENT,
                                 created_at=datetime.now(timezone.utc).replace(tzinfo=None)))
        session.commit()


def count_today(uid: int, event: str) -> int:
    """V3.61.7: how many times today `event` happened (e.g. 'undress_free')."""
    with SessionLocal() as session:
        return int(session.scalar(
            select(func.count(ProductEvent.id)).where(
                ProductEvent.user_id == uid, ProductEvent.event_name == event,
                ProductEvent.created_at >= _day_start())
        ) or 0)


def count_ever(uid: int, event: str) -> int:
    """V3.61.12: how many times `event` ever happened (the one-time trial)."""
    with SessionLocal() as session:
        return int(session.scalar(
            select(func.count(ProductEvent.id)).where(
                ProductEvent.user_id == uid, ProductEvent.event_name == event)
        ) or 0)


def note_today(uid: int, event: str, character_id: str) -> None:
    with SessionLocal() as session:
        session.add(ProductEvent(user_id=uid, character_id=character_id, event_name=event,
                                 created_at=datetime.now(timezone.utc).replace(tzinfo=None)))
        session.commit()


def free_photo_spend_today() -> float:
    """V3.81.0: what today's RENDERED free chat photos cost, all users together
    (pool-served ones are logged as POOL_EVENT and cost nothing)."""
    try:
        with SessionLocal() as session:
            rendered = int(session.scalar(
                select(func.count(ProductEvent.id)).where(
                    ProductEvent.event_name == EVENT,
                    ProductEvent.created_at >= _day_start())
            ) or 0)
            pooled = int(session.scalar(
                select(func.count(ProductEvent.id)).where(
                    ProductEvent.event_name == POOL_EVENT,
                    ProductEvent.created_at >= _day_start())
            ) or 0)
    except Exception:
        return 0.0
    return max(0, rendered - pooled) * FREE_PHOTO_COST_USD


def free_photo_budget_spent() -> bool:
    """True once today's free-photo ceiling is reached (never when it is off)."""
    if FREE_PHOTO_DAILY_BUDGET_USD <= 0:
        return False
    return free_photo_spend_today() >= FREE_PHOTO_DAILY_BUDGET_USD
