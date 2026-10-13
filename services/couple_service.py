"""V3.21.0: couple-layer mechanics — pet names, daily quests, couple album
and anniversaries. Pure service code; main.py wires the Telegram UI."""
from __future__ import annotations

import hashlib
import json
import logging
import random
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from models.app_models import CoupleAlbum, Message, ProductEvent, User
from models.relationship_models import UserCharacterRelationship
from services.db import SessionLocal

logger = logging.getLogger(__name__)

# Assigned once at level 3 — she starts calling the user by this name.
PET_NAMES = (
    'солнышко', 'милый', 'мой хороший', 'котик', 'родной',
    'моя радость', 'дорогой', 'любимый',
)

# Daily quests, deterministic pick. V3.59.1: no longer honor-system — a claim
# only counts if today's dialog shows the task was actually done.
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


def daily_quests(telegram_id: int) -> list[tuple[str, str]]:
    """V3.49.0 / V3.51.0: deterministic daily quests (key, text). Free users get
    2-3 a day; Premium gets exactly 4. Both the count and the rotation derive
    from the day+user seed, so a given day always shows the same short list
    while consecutive days feel different."""
    seed = int(hashlib.md5(f'{_today_key()}:{telegram_id}'.encode('utf-8')).hexdigest(), 16)
    from services.access_service import is_premium
    if is_premium(telegram_id):
        count = 4
    else:
        count = 3 if seed % 2 == 0 else 2
    start = seed % len(DAILY_QUESTS)
    return [DAILY_QUESTS[(start + i) % len(DAILY_QUESTS)] for i in range(count)]


def daily_quest(telegram_id: int) -> tuple[str, str]:
    """Backward-compatible: the primary (first) quest of today's list."""
    return daily_quests(telegram_id)[0]


def _claims_map(user) -> dict:
    try:
        data = json.loads(user.quest_claims or '{}')
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def claimed_keys_today(telegram_id: int) -> list[str]:
    today = _today_key()
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            return []
        return list(_claims_map(user).get(today, []))


def daily_quests_state(telegram_id: int) -> list[dict]:
    """Today's quests with per-item claimed flags (drives the app checklist)."""
    done = set(claimed_keys_today(telegram_id))
    return [{'key': k, 'text': t, 'claimed': k in done} for k, t in daily_quests(telegram_id)]


# V3.59.1: what «done» means for each task, read from today's own messages.
_COMPLIMENT = re.compile(r'красив|прекрасн|мил(ая|ашк|о)|нежн|умниц|обожа|чудесн|восхит|потрясающ|сексуальн|лучш(ая|е)|нравишься|beautiful|pretty|cute|gorgeous|amazing|sexy', re.I)
_SWEET = re.compile(r'солнышк|солнце|зайк|зай\b|котик|кис(а|к)|малыш|любим|родн(ая|ой)|дорог(ая|уша)|милая|пупс|ласточк|sweetheart|honey|babe|baby|darling', re.I)
_DREAM = re.compile(r'сни(лось|тся|л)|сон\b|сны|dream', re.I)
_RED = re.compile(r'красн|\bred\b', re.I)
_DAY_MIN_CHARS = 60


def quest_done_today(telegram_id: int, quest_key: str) -> bool:
    start = datetime.now(timezone.utc).replace(tzinfo=None).replace(hour=0, minute=0, second=0, microsecond=0)
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            return False
        if quest_key == 'voice':
            return bool(session.scalar(select(ProductEvent.id).where(
                ProductEvent.user_id == user.id, ProductEvent.created_at >= start,
                ProductEvent.event_name.in_(('chat_user_message', 'webapp_chat_media')),
                ProductEvent.metadata_json.like('%voice%')).limit(1)))
        texts = session.scalars(select(Message.content).where(
            Message.user_id == user.id, Message.role == 'user', Message.created_at >= start)).all()
    if quest_key == 'compliment':
        return any(_COMPLIMENT.search(t or '') for t in texts)
    if quest_key == 'sweet':
        return any(_SWEET.search(t or '') for t in texts)
    if quest_key == 'dream':
        return any(_DREAM.search(t or '') for t in texts)
    if quest_key == 'red':
        return any(_RED.search(t or '') for t in texts)
    if quest_key == 'day':
        return any(len((t or '').strip()) >= _DAY_MIN_CHARS for t in texts)
    return True  # an unknown/legacy key keeps the old behaviour


def _bonus_media_roll(user) -> bool:
    """~20% chance a spontaneous free photo drops, at most once per day. Marks
    ``bonus_media_date`` on success so the caller can deliver the media."""
    today = _today_key()
    if (user.bonus_media_date or '') == today:
        return False
    if random.random() < 0.20:
        user.bonus_media_date = today
        return True
    return False


def claim_quest(telegram_id: int, quest_key: str) -> dict | None:
    """V3.49.0: claim one of today's quests by key. Returns a result dict on a
    fresh claim (attention +5, quests_completed +1, bonus-media roll) or None
    when the key is not today's quest or was already claimed today."""
    today = _today_key()
    todays = {k for k, _ in daily_quests(telegram_id)}
    if quest_key not in todays:
        return None
    if quest_key in claimed_keys_today(telegram_id):
        return None
    if not quest_done_today(telegram_id, quest_key):
        return {'not_done': True}
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            return None
        claims = _claims_map(user)
        done = list(claims.get(today, []))
        if quest_key in done:
            return None
        done.append(quest_key)
        claims[today] = done
        # keep only the last few days so the JSON column never grows unbounded
        recent = sorted(claims.keys())[-5:]
        claims = {d: claims[d] for d in recent}
        user.quest_claims = json.dumps(claims, ensure_ascii=False)
        user.quest_claimed_date = today  # legacy field kept in sync for old clients
        user.attention_points = (user.attention_points or 0) + 5
        user.quests_completed = (user.quests_completed or 0) + 1
        bonus = _bonus_media_roll(user)
        session.commit()
        return {
            'attention': 5,
            'quests_completed': user.quests_completed or 0,
            'bonus_media': bonus,
        }


def claim_daily_quest(telegram_id: int) -> bool:
    """Legacy single-quest entry point: claims today's primary quest. Returns
    True on a fresh claim (kept for the bot's old callback and V3.21 pins)."""
    result = claim_quest(telegram_id, daily_quest(telegram_id)[0])
    return bool(result) and not result.get('not_done')


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
