"""V3.21.0: couple-layer mechanics — pet names, daily quests, couple album
and anniversaries. Pure service code; main.py wires the Telegram UI."""
from __future__ import annotations

import hashlib
import logging
import random
from datetime import datetime, timezone

from sqlalchemy import select

from models.app_models import CoupleAlbum, User
from models.relationship_models import UserCharacterRelationship
from services.db import SessionLocal

logger = logging.getLogger(__name__)

# Assigned once at level 3 — she starts calling the user by this name.
PET_NAMES = (
    'солнышко', 'милый', 'мой хороший', 'котик', 'родной',
    'моя радость', 'дорогой', 'любимый',
)

# Honor-system daily quests: one per user per day, deterministic pick.
DAILY_QUESTS: tuple[tuple[str, str], ...] = (
    ('compliment', 'сделай ей комплимент — искренний и тёплый'),
    ('dream', 'спроси, что ей снилось сегодня'),
    ('red', 'попроси у неё фото в красном'),
    ('day', 'расскажи, как прошёл твой день'),
    ('sweet', 'обратись к ней ласково в своём сообщении'),
    ('voice', 'отправь ей голосовое сообщение'),
)

ANNIVERSARY_DAYS = (7, 30, 90)


def _today_key(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc).replace(tzinfo=None)).date().isoformat()


def daily_quest(telegram_id: int) -> tuple[str, str]:
    """Deterministic per-user per-day quest (key, text)."""
    seed = hashlib.md5(f'{_today_key()}:{telegram_id}'.encode('utf-8')).hexdigest()
    return DAILY_QUESTS[int(seed, 16) % len(DAILY_QUESTS)]


def claim_daily_quest(telegram_id: int) -> bool:
    """Once per day. Returns True when the claim is fresh (also +5 attention)."""
    today = _today_key()
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            return False
        if (user.quest_claimed_date or '') == today:
            return False
        user.quest_claimed_date = today
        user.attention_points = (user.attention_points or 0) + 5
        session.commit()
    return True


def get_pet_name(telegram_id: int) -> str | None:
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        return user.pet_name if user else None


def assign_pet_name(telegram_id: int) -> str | None:
    """Pick once (level 3 ceremony); an existing name is never replaced."""
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            return None
        if user.pet_name:
            return user.pet_name
        user.pet_name = random.choice(PET_NAMES)
        session.commit()
        return user.pet_name


def add_album_milestone(user_id: int, level: int, delivery_id: int) -> None:
    """One milestone photo per level — the couple album."""
    with SessionLocal() as session:
        exists = session.scalar(select(CoupleAlbum).where(
            CoupleAlbum.user_id == user_id, CoupleAlbum.level == level,
        ))
        if exists:
            return
        session.add(CoupleAlbum(user_id=user_id, level=level, delivery_id=delivery_id))
        session.commit()


def album_entries(user_id: int) -> list[tuple[int, int]]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(CoupleAlbum).where(CoupleAlbum.user_id == user_id)
            .order_by(CoupleAlbum.level.asc())
        ).all()
        return [(r.level, r.delivery_id) for r in rows]


def check_anniversary(user_id: int) -> int | None:
    """Newest reached-but-uncelebrated anniversary (7/30/90 days), if any."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with SessionLocal() as session:
        user = session.get(User, user_id)
        rel = session.scalar(
            select(UserCharacterRelationship)
            .where(UserCharacterRelationship.user_id == user_id)
            .order_by(UserCharacterRelationship.id.asc())
        )
        if not user or not rel or not rel.first_interaction_at:
            return None
        days = (now - rel.first_interaction_at).days
        done = set((user.anniversaries or '').split(',')) - {''}
        new = [d for d in ANNIVERSARY_DAYS if days >= d and str(d) not in done]
        if not new:
            return None
        user.anniversaries = ','.join(sorted(done | {str(d) for d in new}, key=int))
        session.commit()
    return max(new)
