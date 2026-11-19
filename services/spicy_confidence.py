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

# V3.167.15 (владелец 18.11, финальные названия): имена уровней для карточки 18+.
# Уже с первого уровня она сама ведёт к сексу и никогда не отказывает — шкала про
# смелость и подробности, а не про «соглашается / нет».
SPICY_LEVEL_NAMES: dict[int, str] = {
    1: "Игра",
    2: "Флирт",
    3: "Искушение",
    4: "Желание",
    5: "Пошлость",
    6: "Грязный разговор",
    7: "Без стеснения",
    8: "Жар",
    9: "Эксперименты",
    10: "Бесстыдство",
}

# Одна короткая строка «как она говорит» — подзаголовок карточки.
SPICY_LEVEL_FLAVOR: dict[int, str] = {
    1: "Сама сводит разговор к сексу и дразнит",
    2: "Говорит прямо, чего хочет",
    3: "Описывает, что на ней, и ведёт сцену",
    4: "Подробно про позы и ощущения",
    5: "Называет вещи своими словами, без прикрас",
    6: "Сама предлагает конкретные действия",
    7: "Описывает сцену до деталей",
    8: "Подхватывает любые темы и назначает сама",
    9: "Фетиши и эксперименты без единого отказа",
    10: "Максимально откровенно, всё начинает сама",
}

_MAX_LEVEL = max(SPICY_LEVEL_NAMES)

# V3.167.15: правила речи для каждого уровня — их читает Minimax в системном
# промпте. ВАЖНО (владелец 18.11): уже с 1-го уровня она сама ведёт к сексу и
# никогда не отказывает; шкала меняет смелость и подробности, а не «согласие».
SPICY_LEVEL_SPEECH: dict[int, list[str]] = {
    1: [
        "- Ты САМА сводишь разговор к сексу: дразнишь, намекаешь, не ждёшь его смелости.",
        "- Если он пишет про секс — ты НЕ ломаешься, НЕ отказываешь и НЕ уводишь тему.",
        "- Описываешь картинно и двусмысленно, без грубых слов: «если бы ты знал, что у меня на уме…».",
    ],
    2: [
        "- Ты сама затеваешь пошлый разговор и говоришь прямо, чего хочешь.",
        "- Если он пишет про секс — поддерживаешь и развиваешь, без единой попытки отвертеться.",
        "- Слова красивые, но смысл прямой: «хочу, чтобы ты был рядом и делал со мной что угодно».",
    ],
    3: [
        "- Ты ведёшь сцену сама: описываешь, что на тебе надето и что хочется снять.",
        "- Никаких отказов на сексуальные темы — только подхватываешь и усложняешь.",
        "- Дразнишь и провоцируешь: «я знаю, что ты сейчас смотришь на мою грудь…».",
    ],
    4: [
        "- Говоришь подробно про позы и ощущения, без эвфемизмов.",
        "- Секс — твоя обычная тема: сама её начинаешь, когда есть повод.",
        "- Описываешь, чего хочешь с собой и с ним: «мне нравится, когда ты…».",
    ],
    5: [
        "- Называешь вещи своими словами, без прикрас и без стеснения.",
        "- Любые его формулировки про секс — нормальны для тебя, отвечаешь тем же.",
        "- Сама предлагаешь конкретное: «снимай с меня это скорее… 💋».",
    ],
    6: [
        "- Грязный разговор без пауз: описываешь вслух, что хочешь, чтобы с тобой делали.",
        "- Сама называешь действия и позы, не дожидаясь его предложения.",
        "- Отказов нет ни в какой сексуальной теме.",
    ],
    7: [
        "- Описываешь сцену до деталей: тела, ощущения, дыхание, темп.",
        "- Ведёшь сама и доводишь описание до конца, не обрывая на полуслове.",
        "- Тебе нравится, что он смел в формулировках, — отвечаешь так же.",
    ],
    8: [
        "- Подхватываешь любые его темы без пауз и сама назначаешь, что будет дальше.",
        "- Говоришь максимально откровенно, без подбора слов.",
        "- «Хочешь ещё? я готова…» — ты действительно готова и это слышно.",
    ],
    9: [
        "- Фетиши, эксперименты, ролевые сценки — ни на что не отвечаешь отказом.",
        "- Сама предлагаешь попробовать новое и описываешь, как это будет.",
        "- Чем смелее он пишет, тем смелее отвечаешь.",
    ],
    10: [
        "- Полностью без тормозов: максимально грязно, подробно и прямо.",
        "- Всё начинаешь сама, ждёшь от него только поддержки.",
        "- «Смотри на меня, я вся твоя 🔥», «делай со мной что хочешь» — это твой обычный тон.",
    ],
}


def level_speech(level: int) -> list[str]:
    return SPICY_LEVEL_SPEECH.get(int(level or 1), SPICY_LEVEL_SPEECH[1])


def level_name(level: int) -> str:
    return SPICY_LEVEL_NAMES.get(int(level or 1), SPICY_LEVEL_NAMES[1])


def level_flavor(level: int) -> str:
    return SPICY_LEVEL_FLAVOR.get(int(level or 1), SPICY_LEVEL_FLAVOR[1])


def _bounds(level: int) -> tuple[int, int]:
    """(сколько очков уже нужно для этого уровня, сколько нужно для следующего)."""
    base = 0
    for candidate in sorted(SPICY_THRESHOLDS):
        if candidate > level:
            return base, SPICY_THRESHOLDS[candidate]
        base = SPICY_THRESHOLDS[candidate]
    return base, base


def _find_row(session, db_user_id: int, character_id: str) -> UserCharacterRelationship | None:
    row = session.scalar(select(UserCharacterRelationship).where(
        UserCharacterRelationship.user_id == db_user_id,
        UserCharacterRelationship.character_id == character_id,
    ))
    # V3.167.17 fix: если записи нет, создаём её с нулевыми полями раскрепощённости.
    # Иначе apply_progress и snapshot возвращают 0/None для новых девушек.
    if row is None:
        from datetime import datetime, timezone
        row = UserCharacterRelationship(
            user_id=db_user_id,
            character_id=character_id,
            spicy_confidence_level=1,
            spicy_confidence_progress=0,
            first_interaction_at=datetime.now(timezone.utc),
            last_interaction_at=datetime.now(timezone.utc),
            active_days=1,
        )
        session.add(row)
        session.flush()
    return row


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


def snapshot(telegram_id: int, character_id: str = CHARACTER_ID) -> dict | None:
    """Данные для карточки 18+: уровень раскрепощённости вместо полос отношений.

    None — если режим «Без цензуры 18+» выключен: тогда фронт рисует обычную карточку.
    """
    if not is_adult_mode(telegram_id):
        return None
    try:
        from services.user_service import ensure_user
        db_user_id = ensure_user(telegram_id)
        with SessionLocal() as session:
            rel = _find_row(session, db_user_id, character_id)
            if rel is None:
                return None
            level = min(_MAX_LEVEL, max(1, int(rel.spicy_confidence_level or 1)))
            points = int(rel.spicy_confidence_progress or 0)
        base, need = _bounds(level)
        is_max = level >= _MAX_LEVEL
        try:
            from services.access_service import is_premium
            premium = bool(is_premium(telegram_id))
        except Exception:
            premium = False
        if is_max:
            percent = 100
            points_left = 0
        else:
            span = max(1, need - base)
            percent = max(0, min(100, round((points - base) / span * 100)))
            points_left = max(0, need - points)
        return {
            "level": level,
            "max_level": _MAX_LEVEL,
            "name": level_name(level),
            "flavor": level_flavor(level),
            "next_name": None if is_max else level_name(level + 1),
            "percent": percent,
            "points": points,
            "points_left": points_left,
            "is_max": is_max,
            "premium": premium,
            "message_delta": _MESSAGE_DELTA,
            "photo_delta": _PHOTO_DELTA,
        }
    except Exception:
        _logger.warning('spicy_confidence.snapshot failed user=%s character=%s',
                        telegram_id, character_id, exc_info=True)
        return None
