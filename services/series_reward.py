"""V3.167.4: награда за серию (владелец 16.11).

Правило одно, без кнопки и без «забери сам»: он зашёл, написал ей пять
сообщений за сутки — получает SERIES_REWARD_PEACHES. Один раз в сутки, на весь
аккаунт, в обоих режимах и с обеих площадок: сообщение считается по его репликам
в диалогах (Premium потолок не жжёт, поэтому дневный лимит сервиса
services/daily_limit счётчиком быть не может).

Серия — тот же счётчик, что и в боте (users.streak_count / streak_last_date),
чтобы в шапке чата и в профиле было одно и то же число. Граница суток —
полночь UTC, то есть 03:00 МСК: та, на которой живут gift_day_key и прошлые
награды за постоянство.

Пропущенный день закрывает заморозка — SERIES_FREEZE_PER_WEEK раз в неделю
(KC-неделя лежит в users.streak_freeze_week). Со вторым пропуском серия
начинается с единицы, но обнуляется только она: близость пары и её незакрытая
тема живут в других таблицах и сюда не заглядывают.

Выплату ведёт идемпотентный reason `series_reward_<iso>` — payments
отказывает повторно, так что гонка двух тапов не удваивает персики.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from config import (
    SERIES_FREEZE_PER_WEEK,
    SERIES_REWARD_ENABLED,
    SERIES_REWARD_MIN_MESSAGES,
    SERIES_REWARD_PEACHES,
)
from models.app_models import Message, User
from services.db import SessionLocal

logger = logging.getLogger(__name__)

# Награда ставится в тот момент, когда он ещё смотрит на экран. Плашку читают
# один раз: Mini App — из payload своего ответа, бот — строкой под её репликой.
_pending: dict[int, dict] = {}
_PENDING_TTL_SECONDS = 900.0


def day_key(now: datetime | None = None) -> str:
    """Суток серии = календарная дата UTC (03:00 МСК — та же граница, что у
    services/gift_service.gift_day_key и у прошлых наград за постоянство)."""
    return (now or datetime.now(timezone.utc).replace(tzinfo=None)).date().isoformat()


def _week_key(key: str) -> str:
    """ISO-неделя вида 2026-W47 — по ней считается «одна заморозка в неделю»."""
    year, week, _ = datetime.fromisoformat(key).date().isocalendar()
    return f'{year}-W{week}'


def _his_messages_today(s, uid: int, since: datetime) -> int:
    return int(s.scalar(select(func.count(Message.id)).where(
        Message.user_id == uid, Message.role == 'user', Message.created_at >= since)) or 0)


def _advance(row, today: str) -> tuple[int, bool]:
    """Счётчик серии на сегодня. Возвращает (дней подряд, сработала ли заморозка)."""
    last = str(getattr(row, 'streak_last_date', None) or '')[:10]
    streak = int(row.streak_count or 0)
    if last == today:
        return max(streak, 1), False
    if last == (datetime.fromisoformat(today) - timedelta(days=1)).date().isoformat():
        return streak + 1, False
    frozen = False
    if (SERIES_FREEZE_PER_WEEK > 0 and streak > 0
            and last == (datetime.fromisoformat(today) - timedelta(days=2)).date().isoformat()
            and str(getattr(row, 'streak_freeze_week', None) or '') != _week_key(today)):
        # Один пропущенный день в неделю серия не рвёт — её закрывает заморозка.
        row.streak_freeze_week = _week_key(today)
        frozen = True
        return streak + 1, frozen
    return 1, False


def note_his_message(telegram_id: int, uid: int) -> dict | None:
    """Его реплика записана в диалог — проверяем серию и платим, если сутки
    закрыты. None, когда платить не за что (мало сообщений, уже получил, флаг
    выключен). Не бросает исключений: награда не имеет права ронять ответ."""
    if not SERIES_REWARD_ENABLED or not uid:
        return None
    today = day_key()
    try:
        with SessionLocal() as s:
            row = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
            if row is None:
                return None
            if str(getattr(row, 'streak_reward_day', None) or '')[:10] == today:
                return None
            since = datetime.fromisoformat(today)
            if _his_messages_today(s, int(uid), since) < SERIES_REWARD_MIN_MESSAGES:
                return None
            streak, frozen = _advance(row, today)
            row.streak_reward_day = since
            row.streak_last_date = since
            row.streak_count = streak
            s.commit()
    except Exception:
        logger.warning('series reward check failed user=%s', telegram_id, exc_info=True)
        return None
    from services.payments import grant_photo_credits
    granted = grant_photo_credits(telegram_id, SERIES_REWARD_PEACHES,
                                  reason=f'series_reward_{today}')
    if granted < 0:
        return None
    notice = {'amount': SERIES_REWARD_PEACHES, 'streak': streak, 'frozen': bool(frozen),
              'at': time.monotonic()}
    _pending[int(telegram_id)] = notice
    try:
        from services.analytics_service import track_event
        track_event(int(uid), 'series_reward',
                    metadata={'streak': streak, 'amount': SERIES_REWARD_PEACHES,
                              'frozen': bool(frozen)})
    except Exception:
        logger.debug('series reward track failed user=%s', telegram_id, exc_info=True)
    logger.info('series reward paid user=%s streak=%s', telegram_id, streak)
    return notice


def take_notice(telegram_id: int) -> dict | None:
    """Одноразовая плашка «сегодня серия N — вот твои персики»."""
    entry = _pending.pop(int(telegram_id), None)
    if not entry:
        return None
    if time.monotonic() - float(entry.get('at') or 0) > _PENDING_TTL_SECONDS:
        return None
    return {k: entry.get(k) for k in ('amount', 'streak', 'frozen')}


def line(notice: dict, lang: str = 'ru') -> str:
    """Как это сказать ему. Та же строка едет в Mini App и в бот."""
    streak = int(notice.get('streak') or 1)
    amount = int(notice.get('amount') or 0)
    if (lang or 'ru').startswith('en'):
        return (f'🔥 {streak} days in a row — +{amount} peaches for staying with me. '
                'Tomorrow the series grows again 💜')
    return (f'🔥 серия {streak} — держи {amount} 🍑 за то, что не пропадаешь. '
            'Завтра продолжим 💜')
