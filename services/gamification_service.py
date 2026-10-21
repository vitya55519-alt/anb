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

# V3.46.0: achievement perks — a free date voucher (the same rail the streak
# uses), a permanently-unlocked sealed private-photo category
# (private_photo_service.ACHIEVEMENT_SCENE_UNLOCKS), or a cosmetic badge.
# V3.66.0: the owner reversed «no peaches» — every mission also pays
# MISSION_PEACHES, but only through claim_mission (a tap in the app), never
# from the unlock dispatch below.
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


# V3.66.0: owner (2026-10-21): «миссии — для чего они? ничего не вызывают».
# Every mission now pays peaches on top of its perk, claimed by hand in the
# «Миссии» tab (a reason to come back and tap). Amounts are in today's peach
# units (a chat photo is 200 🍑): the first steps pay for a photo, the long
# streaks/anniversaries pay for a pack. Paid by claim_mission through the
# idempotent grant_photo_credits marker, never on unlock.
MISSION_PEACHES: dict[str, int] = {}
# V3.68.0: owner — «не по 700, а просто по 100, ежедневные». The one-off
# missions are plain achievements again; peaches come from DAILY_MISSIONS
# below. (The V3.66.0 amounts were 100–2000 🍑 per mission.)
# V3.66.0: missions with a live counter show a progress bar in the app.
HUNDRED_MESSAGES = 100
TEN_DATES = 10


# V3.68.0: daily missions — 100 🍑 each, a fresh pair every day at 03:00 MSK
# (UTC midnight, the gift day boundary). Only «real» messages count (see
# _meaningful): at least two words and six letters, no repeats that day, so
# «а», «ок» or one pasted line sent ten times earn nothing.
# key → (name, description, messages needed, minimum span in minutes, peaches)
DAILY_MISSIONS: dict[str, tuple[str, str, int, int, int]] = {
    'daily_chat': ('Поболтай с ней', '10 сообщений за день', 10, 0, 100),
    'daily_long': ('Долгий разговор', '25 сообщений, разговор от 20 минут', 25, 20, 100),
}
# a conversation day for the streak needs this many real messages
STREAK_DAY_MESSAGES = 3
# a message sent seconds after the previous counted one is a burst, not talk:
# she needs time to answer, so the burst counts once
MIN_GAP_SECONDS = 8


def _norm_text(text: str) -> str:
    import re
    return re.sub(r'[^0-9a-zа-яё]+', ' ', (text or '').lower()).strip()


def _meaningful(text: str) -> bool:
    t = _norm_text(text)
    letters = sum(ch.isalpha() for ch in t)
    return letters >= 6 and len(t.split()) >= 2


def _day_start(now: datetime | None = None) -> datetime:
    now = now or _today()
    return datetime(now.year, now.month, now.day)


def daily_stats(user_id: int, extra_text: str | None = None) -> dict:
    """Real messages today (all girls): count, first and last time. ``extra_text``
    is the message being sent right now (not saved yet)."""
    from models.app_models import Message
    start = _day_start()
    with SessionLocal() as session:
        rows = session.execute(
            select(Message.content, Message.created_at).where(
                Message.user_id == user_id, Message.role == 'user',
                Message.created_at >= start,
            ).order_by(Message.created_at)
        ).all()
    seen: set[str] = set()
    count, first, last = 0, None, None
    items = list(rows) + ([(extra_text, _today())] if extra_text is not None else [])
    for content, at in items:
        if not _meaningful(content or ''):
            continue
        key = _norm_text(content)
        if key in seen:
            continue
        if last is not None and at is not None and (at - last).total_seconds() < MIN_GAP_SECONDS:
            continue
        seen.add(key)
        count += 1
        first = first or at
        last = at
    span = int((last - first).total_seconds() // 60) if first and last else 0
    return {'count': count, 'span_minutes': span}


def _daily_reason(key: str) -> str:
    return f'daily_{key}_{_day_start().strftime("%Y%m%d")}'


def _daily_done(stats: dict, key: str) -> bool:
    _n, _d, need, span, _p = DAILY_MISSIONS[key]
    return stats['count'] >= need and stats['span_minutes'] >= span


def daily_missions(telegram_id: int) -> list[dict]:
    from services.payments import has_credit_grant
    user = get_user(telegram_id)
    if not user:
        return []
    stats = daily_stats(user.id)
    out = []
    for key, (name, desc, need, span, peaches) in DAILY_MISSIONS.items():
        done = _daily_done(stats, key)
        claimed = has_credit_grant(telegram_id, _daily_reason(key))
        out.append({'key': key, 'name': name, 'description': desc, 'peaches': peaches,
                    'progress': (min(stats['count'], need), need),
                    'span': (min(stats['span_minutes'], span), span) if span else None,
                    'done': done, 'claimed': claimed, 'claimable': done and not claimed})
    return out


def claim_daily(telegram_id: int, key: str) -> dict:
    """Pay one finished daily mission, once per day (the server recounts)."""
    if key not in DAILY_MISSIONS:
        return {'ok': False, 'error': 'unknown'}
    user = get_user(telegram_id)
    if not user:
        return {'ok': False, 'error': 'unknown'}
    if not _daily_done(daily_stats(user.id), key):
        return {'ok': False, 'error': 'locked'}
    from services.payments import grant_photo_credits
    amount = DAILY_MISSIONS[key][4]
    balance = grant_photo_credits(telegram_id, amount, reason=_daily_reason(key))
    if balance < 0:
        return {'ok': False, 'error': 'claimed'}
    try:
        from services.analytics_service import track_event
        track_event(user.id, 'daily_mission_claimed', metadata={'key': key, 'peaches': amount})
    except Exception:
        pass
    return {'ok': True, 'key': key, 'amount': amount, 'balance': balance}


def _mission_marker_reason(key: str) -> str:
    return f'mission_{key}'


def claimed_mission_keys(telegram_id: int) -> set[str]:
    """V3.66.0: missions whose peaches were already claimed (one query over
    the grant markers grant_photo_credits writes)."""
    prefix = 'credit_grant:mission_'
    suffix = f':{telegram_id}'
    with SessionLocal() as session:
        rows = session.scalars(
            select(StarTransaction.telegram_charge_id).where(
                StarTransaction.telegram_charge_id.like(prefix + '%' + suffix)
            )
        ).all()
    return {r[len(prefix):-len(suffix)] for r in rows if r and r.endswith(suffix)}


def claim_mission(telegram_id: int, key: str) -> dict:
    """V3.66.0: pay a finished mission's peaches. Only an unlocked mission
    pays, and only once (grant_photo_credits is idempotent per reason)."""
    if key in DAILY_MISSIONS:
        return claim_daily(telegram_id, key)
    amount = MISSION_PEACHES.get(key, 0)
    if key not in ACHIEVEMENTS or amount <= 0:
        return {'ok': False, 'error': 'unknown'}
    if key not in {a.achievement_key for a in list_achievements(telegram_id)}:
        return {'ok': False, 'error': 'locked'}
    from services.payments import grant_photo_credits
    balance = grant_photo_credits(telegram_id, amount, reason=_mission_marker_reason(key))
    if balance < 0:
        return {'ok': False, 'error': 'claimed'}
    try:
        from services.analytics_service import track_event
        user = get_user(telegram_id)
        if user:
            track_event(user.id, 'mission_claimed', metadata={'key': key, 'peaches': amount})
    except Exception:
        pass
    return {'ok': True, 'key': key, 'amount': amount, 'balance': balance}


def _user_message_count(user_id: int) -> int:
    from sqlalchemy import func
    from models.app_models import Message
    with SessionLocal() as session:
        return int(session.scalar(
            select(func.count(Message.id)).where(Message.user_id == user_id, Message.role == 'user')
        ) or 0)


def note_app_chat_message(telegram_id: int, voice: bool = False, text: str | None = None) -> list[str]:
    """V3.66.0: the Mini App chat never ran the bot's streak/first-message
    hooks, so app users' series and «Первые шаги» stood still. Called once per
    app chat turn, before the message is saved (``text`` is that message);
    returns the mission keys that finished just now — achievements and
    V3.68.0 daily missions. The streak day only counts once there were
    STREAK_DAY_MESSAGES real messages today (one «привет» a day is no streak)."""
    user = get_user(telegram_id)
    if not user:
        return []
    before = {a.achievement_key for a in list_achievements(telegram_id)}
    prev = daily_stats(user.id)
    stats = daily_stats(user.id, extra_text=text or '')
    if stats['count'] >= STREAK_DAY_MESSAGES:
        touch_activity(telegram_id)
    if 'first_message' not in before or 'hundred_messages' not in before:
        count = _user_message_count(user.id) + 1
        if count >= 1:
            unlock_achievement(telegram_id, 'first_message')
        if count >= HUNDRED_MESSAGES:
            unlock_achievement(telegram_id, 'hundred_messages')
    if voice:
        unlock_achievement(telegram_id, 'voice_user')
    after = {a.achievement_key for a in list_achievements(telegram_id)}
    fresh = [k for k in ACHIEVEMENTS if k in after and k not in before]
    fresh += [k for k in DAILY_MISSIONS if _daily_done(stats, k) and not _daily_done(prev, k)]
    return fresh


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
    # V3.66.0: the peaches wait in the app «Миссии» tab.
    peaches = MISSION_PEACHES.get(key, 0)
    claim = f'\n🍑 +{peaches} персиков ждут тебя — забери во вкладке «Миссии»' if peaches else ''
    return f'🏆 Достижение открыто: {name}{tail}\n{desc}{claim}'


def try_unlock(telegram_id: int, key: str) -> str:
    """V3.46.0: unlock a mission and, if it was NEW, return the notify text.
    Returns '' when already unlocked / unknown so the caller skips the ping.
    The reward itself is handed out inside unlock_achievement."""
    return achievement_unlock_text(key) if unlock_achievement(telegram_id, key) else ''


def get_missions(telegram_id: int) -> dict:
    """V3.46.0: the roadmap board — every lifecycle achievement with unlock
    state, reward chip, a progress pair where we have a real counter, and a CTA.
    Ordered by group (start → romance → creator). V3.66.0: each mission also
    carries its peaches and whether they are claimed / waiting to be claimed."""
    board = {it['key']: it for it in get_unified_progress(telegram_id)['items']}
    user = get_user(telegram_id)
    streak = (user.streak_count or 0) if user else 0
    claimed = claimed_mission_keys(telegram_id) if user else set()
    messages = None
    dates = None
    order = {'start': 0, 'romance': 1, 'creator': 2}
    items: list[dict] = []
    for key, (name, desc, reward) in ACHIEVEMENTS.items():
        group = MISSION_GROUP.get(key, 'start')
        cta = MISSION_CTA.get(key)
        unlocked = board.get(key, {}).get('unlocked', False)
        progress = None
        if key == 'three_day_streak':
            progress = (min(streak, 3), 3)
        elif key == 'seven_day_streak':
            progress = (min(streak, 7), 7)
        elif key == 'hundred_messages' and user and not unlocked:
            if messages is None:
                messages = _user_message_count(user.id)
            progress = (min(messages, HUNDRED_MESSAGES), HUNDRED_MESSAGES)
        elif key == 'ten_dates' and user and not unlocked:
            if dates is None:
                try:
                    dates = len(completed_date_ids(telegram_id))
                except Exception:
                    dates = 0
            progress = (min(dates, TEN_DATES), TEN_DATES)
        peaches = MISSION_PEACHES.get(key, 0)
        items.append({
            'key': key, 'name': name, 'description': desc,
            'unlocked': unlocked,
            'reward': reward_preview(reward), 'group': group,
            'progress': progress,
            'peaches': peaches,
            'claimed': key in claimed,
            'claimable': bool(unlocked and peaches and key not in claimed),
            'has_badge': board.get(key, {}).get('has_badge', False),
            'cta_label': cta[0] if cta else '', 'cta_cb': cta[1] if cta else '',
        })
    items.sort(key=lambda it: (order.get(it['group'], 9), it['key']))
    daily = daily_missions(telegram_id) if user else []
    total = len(items)
    unlocked = sum(1 for it in items if it['unlocked'])
    return {
        'total': total, 'unlocked': unlocked,
        'pct': round(unlocked / total * 100) if total else 0,
        'items': items,
        'streak': streak,
        'peaches_total': sum(it['peaches'] for it in items),
        'peaches_earned': sum(it['peaches'] for it in items if it['claimed']),
        'peaches_ready': sum(it['peaches'] for it in items if it['claimable']),
        # V3.68.0: today's missions on top of the board.
        'daily': daily,
        'daily_ready': sum(d['peaches'] for d in daily if d['claimable']),
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
