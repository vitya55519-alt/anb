"""Gamification: streaks, achievements, attention points."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from config import FREE_MESSAGES_PER_DAY, CHARACTER_ID, STREAK_REWARDS
from models.app_models import Achievement, StarTransaction, User, AchievementBadge
from services.db import SessionLocal
from services.user_service import ensure_user, get_user

logger = logging.getLogger(__name__)

# A 7-day streak grants one free date voucher (stored as 0-star payment
# markers so no schema change is needed). The voucher is granted once and
# consumed on the next date the user starts.
FREE_DATE_STREAK = 7

# V3.46.0: achievement rewards are NON-monetized perks only — a free date
# voucher (the same rail the streak uses), a permanently-unlocked sealed
# private-photo category (private_photo_service.ACHIEVEMENT_SCENE_UNLOCKS),
# or a purely cosmetic badge. NO peaches, NO Stars (owner decision) so the
# 20🍑 creation and the paid-photo loop are never diluted.
REWARD_VOUCHER = 'voucher'
REWARD_SCENE = 'scene'

# The lifecycle achievement board. Each entry is (name, description, reward)
# where reward is a list of (kind, payload) perks granted once on unlock.
ACHIEVEMENTS = {
    # (name, description, reward list of (kind, payload)). Empty reward list =
    # a cosmetic badge only.
    'first_message': ('Первое сообщение', 'Вы начали общение', []),
    'three_day_streak': ('3 дня подряд', 'Три дня общения без перерыва', []),
    'seven_day_streak': ('7 дней подряд', 'Неделя ежедневного общения', [('scene', 'ach_seven')]),
    'voice_user': ('Голосовой собеседник', 'Отправили голосовое сообщение', []),
    'photo_collector': ('Коллекционер', 'Открыли все фото одного уровня', [('scene', 'ach_photo_collector')]),
    'premium_member': ('Premium', 'Оформили подписку Premium', []),
    'hundred_messages': ('100 сообщений', 'Общались более 100 раз', [('scene', 'ach_hundred')]),
    'first_gift': ('Первый подарок', 'Подарили ей первый подарок', []),
    'first_date': ('Первое свидание', 'Сходили на первое свидание', []),
    'ten_dates': ('10 свиданий', 'Десять свиданий — настоящий роман', [('voucher', None)]),
    'date_collector': ('Сердцеед', 'Прошли все свидания из каталога', [('scene', 'ach_date_collector')]),
    # V3.21.0: couple anniversaries.
    'anniv_7': ('Неделя вместе', '7 дней общей истории', [('scene', 'ach_anniv7')]),
    'anniv_30': ('Месяц вместе', '30 дней — уже серьёзно', [('scene', 'ach_anniv30'), ('voucher', None)]),
    'anniv_90': ('90 дней вместе', 'Целый сезон вашей истории', [('scene', 'ach_anniv90')]),
    # V3.46.0: missions funnel — behaviour that nudges toward paid/creator
    # actions. Unlock hooks fire where the event happens (bot/app, Incr 2/3).
    'first_creation': ('Персонаж с нуля', 'Создал(а) своего персонажа в конструкторе', []),
    'community_publish': ('Голос сообщества', 'Опубликовал(а) персонажа в «Сообществе»', []),
    'views_100': ('100 просмотров', 'Твой персонаж посмотрели 100 раз', [('scene', 'ach_views100')]),
    'first_video': ('Живое видео', 'Заказал(а) первое видео или видеокружок', [('voucher', None)]),
    'first_spicy_photo': ('Искра', 'Заказал(а) первое пикантное фото', []),
    # V3.55.0: gallery-set collecting (V3.53.0 backlog). Cosmetic-only perks —
    # no peaches, no Stars, per the standing owner decision above.
    'gallery_set_first': ('Первый сет', 'Собрал(а) галерею персонажа — 50 фото', []),
    'gallery_set_five': ('Марафонец галерей', 'Собрано пять сетов', []),
}


def reward_preview(reward: list | None) -> str:
    """V3.46.0: a short chip label for the reward shown on the board / missions
    screen before it is claimed. Badge (empty list) reads as a plain trophy."""
    kinds = [k for k, _ in (reward or [])]
    if REWARD_VOUCHER in kinds and REWARD_SCENE in kinds:
        return '🔓🎟'
    if REWARD_VOUCHER in kinds:
        return '🎟 свидание'
    if REWARD_SCENE in kinds:
        return '🔓 sealed-фото'
    return '🎖'


# V3.46.0: the missions funnel. Every lifecycle achievement is placed in one of
# three roadmap groups, and the actionable ones carry a CTA to an existing bot
# callback (all verified to exist). Private-photo CSV badges are not missions.
MISSION_GROUP: dict[str, str] = {
    'first_message': 'start', 'three_day_streak': 'start', 'seven_day_streak': 'start',
    'voice_user': 'start', 'hundred_messages': 'start',
    'first_gift': 'romance', 'first_date': 'romance', 'ten_dates': 'romance',
    'date_collector': 'romance', 'photo_collector': 'romance', 'premium_member': 'romance',
    'anniv_7': 'romance', 'anniv_30': 'romance', 'anniv_90': 'romance',
    'first_creation': 'creator', 'community_publish': 'creator', 'views_100': 'creator',
    'first_video': 'creator', 'first_spicy_photo': 'creator',
    # V3.55.0: gallery-set collecting sits with the other photo-loop missions.
    'gallery_set_first': 'romance', 'gallery_set_five': 'romance',
}
# key → (button label, bot callback_data). CTAs reuse live handlers only.
MISSION_CTA: dict[str, tuple[str, str]] = {
    'first_creation': ('🎨 Создать персонажа', 'constructor:start'),
    'community_publish': ('🌍 Опубликовать', 'constructor:start'),
    'views_100': ('📈 Кабинет создателя', 'constructor:start'),
    'first_video': ('🎬 Оживить фото', 'video:animate_last'),
    'first_spicy_photo': ('🔥 Пикантное фото', 'spicy:menu'),
    # V3.55.0: the gallery-set badge nudges back to the character page bar.
    'gallery_set_first': ('🖼 К персонажу', 'photo_menu:open'),
    'photo_collector': ('📸 Фото-сюжеты', 'photo_menu:open'),
    # V3.47.1: cover the remaining actionable missions with verified live
    # handlers so a tap in the chat roadmap always lands somewhere real.
    'premium_member': ('⭐ Оформить Premium', 'buy:premium'),
    'first_message': ('💬 Написать ей', 'private_photo:start'),
    'hundred_messages': ('💬 Продолжить общение', 'photo_menu:open'),
    'voice_user': ('🎙 Голос и фото', 'private_photo:start'),
    'first_gift': ('🎁 Сюжеты и свидания', 'quest:list'),
    'first_date': ('❤️ К свиданиям', 'quest:list'),
    'ten_dates': ('❤️ К свиданиям', 'quest:list'),
    'date_collector': ('❤️ К свиданиям', 'quest:list'),
    'three_day_streak': ('💬 Заглянуть в чат', 'photo_menu:open'),
    'seven_day_streak': ('💬 Заглянуть в чат', 'photo_menu:open'),
}
# V3.47.1: the persistent navigation row at the bottom of the chat missions
# screen — every button reuses a verified live callback, so there is always
# somewhere to tap even when a mission is passive (anniversaries, streaks).
MISSION_NAV: tuple[tuple[str, str], ...] = (
    ('💬 Чат', 'photo_menu:open'),
    ('🖼 Галерея', 'private_gallery:view'),
    ('🔥 Наедине', 'private_photo:start'),
    ('⭐ Premium', 'buy:premium'),
    ('🎨 Создать', 'constructor:start'),
)


def achievement_unlock_text(key: str) -> str:
    """V3.46.0: the message sent when an achievement (mission) unlocks."""
    if key not in ACHIEVEMENTS:
        return ''
    name, desc, reward = ACHIEVEMENTS[key]
    chip = reward_preview(reward)
    tail = f' · награда: {chip}' if chip and chip != '🎖' else ''
    return f'🏆 Достижение открыто: {name}{tail}\n{desc}'


def try_unlock(telegram_id: int, key: str) -> str:
    """V3.46.0: unlock a mission and, if it was NEW, return the notify text.
    Returns '' when already unlocked / unknown so the caller skips the ping.
    The reward itself is handed out inside unlock_achievement."""
    return achievement_unlock_text(key) if unlock_achievement(telegram_id, key) else ''


def get_missions(telegram_id: int) -> dict:
    """V3.46.0: the roadmap board — every lifecycle achievement with unlock
    state, reward chip, a progress pair where we have a real counter, and a CTA.
    Ordered by group (start → romance → creator)."""
    board = {it['key']: it for it in get_unified_progress(telegram_id)['items']}
    user = get_user(telegram_id)
    streak = (user.streak_count or 0) if user else 0
    order = {'start': 0, 'romance': 1, 'creator': 2}
    items: list[dict] = []
    for key, (name, desc, reward) in ACHIEVEMENTS.items():
        group = MISSION_GROUP.get(key, 'start')
        cta = MISSION_CTA.get(key)
        progress = None
        if key == 'three_day_streak':
            progress = (min(streak, 3), 3)
        elif key == 'seven_day_streak':
            progress = (min(streak, 7), 7)
        items.append({
            'key': key, 'name': name, 'description': desc,
            'unlocked': board.get(key, {}).get('unlocked', False),
            'reward': reward_preview(reward), 'group': group,
            'progress': progress,
            'has_badge': board.get(key, {}).get('has_badge', False),
            'cta_label': cta[0] if cta else '', 'cta_cb': cta[1] if cta else '',
        })
    items.sort(key=lambda it: (order.get(it['group'], 9), it['key']))
    total = len(items)
    unlocked = sum(1 for it in items if it['unlocked'])
    return {
        'total': total, 'unlocked': unlocked,
        'pct': round(unlocked / total * 100) if total else 0,
        'items': items,
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

    # Streak milestone rewards: grant bonus photo credits once per milestone.
    # Idempotent via grant_photo_credits' marker, so a re-trigger on the same
    # day (or a duplicate touch_activity call) never double-credits.
    reward = STREAK_REWARDS.get(streak, 0)
    if reward > 0 and summary['new_streak_day']:
        try:
            from services.payments import grant_photo_credits
            granted = grant_photo_credits(telegram_id, reward, reason=f"streak_{streak}")
            summary['streak_reward_credits'] = reward if granted >= 0 else 0
            if granted >= 0:
                try:
                    from services.analytics_service import track_event
                    track_event(user.id, 'streak_reward_granted', metadata={'streak': streak, 'credits': reward})
                except Exception:
                    pass
        except Exception:
            logger.exception('streak reward failed user=%s streak=%s', telegram_id, streak)

    # 7-day streak: one free date voucher on top of the photo credits.
    if streak >= FREE_DATE_STREAK and summary['new_streak_day']:
        try:
            grant_free_date_voucher(telegram_id)
            summary['free_date_granted'] = True
        except Exception:
            logger.exception('free date voucher failed user=%s', telegram_id)

    return summary


def _free_date_markers(telegram_id: int) -> tuple[str, str]:
    return (
        f'streak{FREE_DATE_STREAK}_date:{telegram_id}',
        f'streak{FREE_DATE_STREAK}_date_used:{telegram_id}',
    )


def grant_free_date_voucher(telegram_id: int) -> None:
    from services.payments import record_payment
    grant_marker, _ = _free_date_markers(telegram_id)
    record_payment(telegram_id, 'free_date_grant', 0, grant_marker)


def has_free_date(telegram_id: int) -> bool:
    grant_marker, used_marker = _free_date_markers(telegram_id)
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            return False
        found = set(session.scalars(
            select(StarTransaction.telegram_charge_id).where(
                StarTransaction.user_id == user.id,
                StarTransaction.telegram_charge_id.in_([grant_marker, used_marker]),
            )
        ).all())
    return grant_marker in found and used_marker not in found


def consume_free_date(telegram_id: int) -> bool:
    if not has_free_date(telegram_id):
        return False
    from services.payments import record_payment
    _, used_marker = _free_date_markers(telegram_id)
    record_payment(telegram_id, 'free_date_used', 0, used_marker)
    return True


def completed_date_ids(telegram_id: int) -> set[str]:
    """Dates the user has completed — from date:* relationship events."""
    from models.relationship_models import RelationshipEvent, UserCharacterRelationship
    user = get_user(telegram_id)
    if not user:
        return set()
    with SessionLocal() as session:
        rows = session.scalars(
            select(RelationshipEvent.reason)
            .join(UserCharacterRelationship, RelationshipEvent.user_character_id == UserCharacterRelationship.id)
            .where(
                UserCharacterRelationship.user_id == user.id,
                RelationshipEvent.event_type == 'date',
            )
        ).all()
    return {r.split(':', 1)[1] for r in rows if r and r.startswith('date:') and ':' in r}


def unlock_achievement(telegram_id: int, key: str) -> bool:
    if key not in ACHIEVEMENTS:
        return False
    user = get_user(telegram_id)
    if not user:
        return False
    display_name, _desc, reward = ACHIEVEMENTS[key]
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
    # V3.46.0: hand out the perk — only reached on the one successful insert, so
    # a re-trigger (or a duplicate call) can never double-grant.
    _grant_achievement_reward(telegram_id, reward)
    return True


def _grant_achievement_reward(telegram_id: int, reward: list | None) -> None:
    """V3.46.0: dispatch a non-monetized achievement perk. voucher → the same
    free-date rail the streak uses; scene → a sealed private-photo category
    unlocked forever (recorded in user.achievements, honored by
    private_photo_service.consume_free_private_photo). badge/none → nothing."""
    for kind, payload in (reward or []):
        try:
            if kind == REWARD_VOUCHER:
                grant_free_date_voucher(telegram_id)
            elif kind == REWARD_SCENE and payload:
                from services.private_photo_service import grant_achievement
                grant_achievement(telegram_id, payload)
        except Exception:
            logger.exception('achievement reward grant failed user=%s kind=%s', telegram_id, kind)


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


def get_unified_progress(telegram_id: int) -> dict:
    """V3.45.27: ONE achievements board for the whole app and bot.

    The system grew three catalogs that never talked to each other; only two
    are actually live and persist unlocks — this module's lifecycle set (kept
    in the Achievement table) and the private-photo set (kept in the
    ``user.achievements`` CSV). We merge them here into a single ordered list
    with an honest total, so the Mini App shows a correct «N из M» instead of
    the old per-catalog number that matched nothing.
    """
    unlocked_lifecycle = {a.achievement_key for a in list_achievements(telegram_id)}
    unlocked_private: set[str] = set()
    private_names: dict[str, str] = {}
    try:
        from services.private_photo_service import ACHIEVEMENTS as PRIVATE_ACH
        private_names = {k: v.get('name', k) for k, v in PRIVATE_ACH.items()}
        user = get_user(telegram_id)
        if user:
            with SessionLocal() as session:
                row = session.scalar(select(User).where(User.id == user.id))
                if row:
                    unlocked_private = set((row.achievements or '').split(',')) - {''}
    except Exception:
        logger.exception('private achievements merge failed user=%s', telegram_id)
    items: list[dict] = []
    badges = badge_keys()
    for key, (name, desc, reward) in ACHIEVEMENTS.items():
        items.append({'key': key, 'name': name, 'description': desc,
                      'unlocked': key in unlocked_lifecycle, 'group': 'lifecycle',
                      # V3.46.0: the perk chip shown on the board / missions.
                      'reward': reward_preview(reward),
                      # V3.47.1: whether the owner uploaded art for this badge.
                      'has_badge': key in badges})
    for key, name in private_names.items():
        items.append({'key': key, 'name': name, 'description': '',
                      'unlocked': key in unlocked_private, 'group': 'private',
                      'reward': '', 'has_badge': key in badges})
    return {
        'total': len(items),
        'unlocked': sum(1 for it in items if it['unlocked']),
        'items': items,
    }


# ── V3.47.1: admin-uploaded achievement art (badges) ────────────────────────
# One image per achievement/mission key, stored as bytes in PostgreSQL so it
# survives Railway redeploys. The art rides on the unlock notification and on
# the achievements board; nothing changes for achievements with no badge.
BADGE_MAX_BYTES = 8 * 1024 * 1024


def badge_keys() -> set[str]:
    """The achievement keys that currently have an uploaded badge."""
    try:
        with SessionLocal() as session:
            return {k for (k,) in session.execute(select(AchievementBadge.key)).all()}
    except Exception:
        logger.exception('badge_keys failed')
        return set()


def get_badge(key: str) -> tuple[bytes, str] | None:
    """Return (image_bytes, content_type) for an achievement's art, if any."""
    if not key:
        return None
    try:
        with SessionLocal() as session:
            row = session.scalar(select(AchievementBadge).where(AchievementBadge.key == key))
            if not row:
                return None
            return row.image_bytes, (row.content_type or 'image/jpeg')
    except Exception:
        logger.exception('get_badge failed key=%s', key)
        return None


def set_badge(key: str, data: bytes, content_type: str = 'image/jpeg') -> bool:
    """Upsert the admin-uploaded art for an achievement key."""
    if not key or not data:
        return False
    try:
        with SessionLocal() as session:
            row = session.scalar(select(AchievementBadge).where(AchievementBadge.key == key))
            if row:
                row.image_bytes = data
                row.content_type = content_type or 'image/jpeg'
                row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            else:
                session.add(AchievementBadge(key=key, image_bytes=data,
                                             content_type=content_type or 'image/jpeg'))
            session.commit()
        return True
    except Exception:
        logger.exception('set_badge failed key=%s', key)
        return False


def clear_badge(key: str) -> bool:
    """Drop an achievement's art so its message falls back to plain text."""
    if not key:
        return False
    try:
        with SessionLocal() as session:
            row = session.scalar(select(AchievementBadge).where(AchievementBadge.key == key))
            if not row:
                return False
            session.delete(row)
            session.commit()
        return True
    except Exception:
        logger.exception('clear_badge failed key=%s', key)
        return False


def badge_catalog() -> list[tuple[str, str]]:
    """Ordered (key, name) list of every achievement/mission the admin can art.
    Lifecycle missions first (grouped), then the private-photo achievements."""
    catalog: list[tuple[str, str]] = [(k, v[0]) for k, v in ACHIEVEMENTS.items()]
    try:
        from services.private_photo_service import ACHIEVEMENTS as PRIVATE_ACH
        catalog += [(k, v.get('name', k)) for k, v in PRIVATE_ACH.items()]
    except Exception:
        logger.exception('private badge catalog merge failed')
    return catalog
