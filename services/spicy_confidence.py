# V3.167.14 этап 6: рост уровня раскрепощённости за действия в режиме «Без цензуры 18+».
# Экономика (персики, лимиты, цены) не тронута — здесь только счётчик очков и уровень.
from __future__ import annotations

import logging

from sqlalchemy import select

from config import CHARACTER_ID
from models.relationship_models import UserCharacterRelationship
from services.db import SessionLocal

_logger = logging.getLogger(__name__)

# Пороги в очках: 1 сообщение = +1, успешная генерация кадра = +3.
# Premium сразу поднимает до 10 (см. apply_progress / current_level).
SPICY_THRESHOLDS: dict[int, int] = {
    2: 15,
    3: 40,
    4: 70,
    5: 110,
    6: 160,
    7: 220,
    8: 300,
    9: 400,
    10: 550,
}

_MESSAGE_DELTA = 1
_PHOTO_DELTA = 3


def _find_row(session, db_user_id: int, character_id: str) -> UserCharacterRelationship | None:
    return session.scalar(select(UserCharacterRelationship).where(
        UserCharacterRelationship.user_id == db_user_id,
        UserCharacterRelationship.character_id == character_id,
    ))


def _level_from_progress(progress: int) -> int:
    level = 1
    for candidate, threshold in sorted(SPICY_THRESHOLDS.items()):
        if progress >= threshold:
            level = candidate
    return level


def is_adult_mode(telegram_id: int) -> bool:
    try:
        from services import explicit_mode
        return bool(explicit_mode.is_on_for(telegram_id))
    except Exception:
        return False


def current_level(telegram_id: int, character_id: str = CHARACTER_ID) -> int:
    """1-10, если пользователь в режиме 18+; иначе 0. Не пишет в БД."""
    if not is_adult_mode(telegram_id):
        return 0
    try:
        from services.user_service import ensure_user
        db_user_id = ensure_user(telegram_id)
        with SessionLocal() as session:
            rel = _find_row(session, db_user_id, character_id)
            if rel is None:
                return 0
            level = int(rel.spicy_confidence_level or 0)
            return level if 1 <= level <= 10 else 0
    except Exception:
        _logger.warning('spicy_confidence.current_level failed user=%s character=%s',
                        telegram_id, character_id, exc_info=True)
        return 0


def apply_progress(telegram_id: int, character_id: str = CHARACTER_ID, *, kind: str = 'message') -> int:
    """Начисляет очки за действие и возвращает новый уровень (0 — если 18+ выключен).

    kind='message' — +1 очко; kind='photo' — +3. Уровень только растёт, никогда не падает.
    Premium сразу ставит 10 (без списаний и без правок платёжного кода).
    """
    if not is_adult_mode(telegram_id):
        return 0
    delta = _PHOTO_DELTA if kind == 'photo' else _MESSAGE_DELTA
    try:
        from services.user_service import ensure_user
        db_user_id = ensure_user(telegram_id)
        with SessionLocal() as session:
            rel = _find_row(session, db_user_id, character_id)
            if rel is None:
                return 0
            progress = int(rel.spicy_confidence_progress or 0) + delta
            target = _level_from_progress(progress)
            try:
                from services.access_service import is_premium
                if is_premium(telegram_id):
                    target = 10
            except Exception:
                pass
            current = int(rel.spicy_confidence_level or 1)
            new_level = max(current, target, 1)
            rel.spicy_confidence_progress = progress
            rel.spicy_confidence_level = new_level
            session.commit()
            return new_level
    except Exception:
        _logger.warning('spicy_confidence.apply_progress failed user=%s character=%s kind=%s',
                        telegram_id, character_id, kind, exc_info=True)
        return 0
