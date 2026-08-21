"""Gamification: streaks, achievements, attention points."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from config import FREE_MESSAGES_PER_DAY, CHARACTER_ID
from models.app_models import Achievement, User
from services.db import SessionLocal
from services.user_service import ensure_user, get_user

logger = logging.getLogger(__name__)

ACHIEVEMENTS = {
    'first_message': ('Первое сообщение', 'Вы начали общение'),
    'three_day_streak': ('3 дня подряд', 'Три дня общения без перерыва'),
    'seven_day_streak': ('7 дней подряд', 'Неделя ежедневного общения'),
    'voice_user': ('Голосовой собеседник', 'Отправили голосовое сообщение'),
    'photo_collector': ('Коллекционер', 'Открыли все фото одного уровня'),
    'premium_member': ('Premium', 'Оформили подписку Premium'),
    'hundred_messages': ('100 сообщений', 'Общались более 100 раз'),
}


def _today() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _date_key(dt: datetime | None) -> str:
    if not dt:
        return ''
    return dt.strftime('%Y-%m-%d')


def touch_activity(telegram_id: int) -> dict:
    """Update streak and attention points on user activity. Returns summary."""
    user = get_user(telegram_id)
    if not user:
        return {}
    today = _today()
    today_key = _date_key(today)
    last_key = _date_key(user.streak_last_date)

    with SessionLocal() as session:
        u = session.get(User, user.id)
        if not u:
            return {}

        # Attention points: small reward for every activity
        u.attention_points = (u.attention_points or 0) + 1

        if last_key == today_key:
            pass  # already counted today
        elif last_key == _date_key(today - timedelta(days=1)):
            u.streak_count = (u.streak_count or 0) + 1
        else:
            u.streak_count = 1
        u.streak_last_date = today
        u.last_active_at = today
        session.commit()

        summary = {
            'streak_count': u.streak_count or 0,
            'attention_points': u.attention_points or 0,
            'new_streak_day': last_key != today_key,
        }

    # Unlock streak achievements
    streak = summary['streak_count']
    if streak >= 3:
        unlock_achievement(telegram_id, 'three_day_streak')
    if streak >= 7:
        unlock_achievement(telegram_id, 'seven_day_streak')

    return summary


def unlock_achievement(telegram_id: int, key: str) -> bool:
    if key not in ACHIEVEMENTS:
        return False
    user = get_user(telegram_id)
    if not user:
        return False
    display_name, _ = ACHIEVEMENTS[key]
    with SessionLocal() as session:
        existing = session.scalar(
            select(Achievement).where(
                Achievement.user_id == user.id,
                Achievement.achievement_key == key,
            )
        )
        if existing:
            return False
        session.add(
            Achievement(
                user_id=user.id,
                achievement_key=key,
                display_name=display_name,
            )
        )
        session.commit()
    logger.info('achievement unlocked user=%s key=%s', telegram_id, key)
    return True


def list_achievements(telegram_id: int) -> list[Achievement]:
    user = get_user(telegram_id)
    if not user:
        return []
    with SessionLocal() as session:
        return list(
            session.scalars(
                select(Achievement).where(Achievement.user_id == user.id).order_by(Achievement.unlocked_at.asc())
            ).all()
        )


def get_profile_summary(telegram_id: int, character_id: str = CHARACTER_ID) -> dict:
    from services.access_service import is_premium
    from services.payments import get_photo_credits
    from services.photo_service import get_relationship_level
    from services.collection_service import collection_progress

    user = get_user(telegram_id)
    if not user:
        return {}

    achievements = list_achievements(telegram_id)
    collection = collection_progress(telegram_id)
    total_photos = sum(len(v) for v in collection.values()) if collection else 0

    return {
        'name': user.name or 'ты',
        'premium': is_premium(telegram_id),
        'relationship_level': get_relationship_level(telegram_id, character_id),
        'photo_credits': get_photo_credits(telegram_id),
        'streak_count': user.streak_count or 0,
        'attention_points': user.attention_points or 0,
        'achievements_count': len(achievements),
        'achievements': [a.display_name for a in achievements],
        'collection_total': total_photos,
    }


def format_profile_summary(summary: dict) -> str:
    if not summary:
        return 'Профиль не найден.'
    lines = [
        f"👤 {summary['name']}",
        f"{'👑 Premium активен' if summary['premium'] else '⭐ Premium не активен'}",
        f"❤️ Уровень близости: {summary['relationship_level']}/6",
        f"📷 Фото-кредиты: {summary['photo_credits']}",
        f"🔥 Стрик: {summary['streak_count']} дн.",
        f"✨ Очки внимания: {summary['attention_points']}",
        f"🏆 Достижений: {summary['achievements_count']}",
    ]
    if summary.get('achievements'):
        lines.append('  ' + ' · '.join(summary['achievements'][:5]))
    lines.append(f"📚 Фото в коллекции: {summary['collection_total']}")
    return '\n'.join(lines)


def check_first_message(telegram_id: int) -> None:
    user = get_user(telegram_id)
    if user and (user.attention_points or 0) <= 1:
        unlock_achievement(telegram_id, 'first_message')
