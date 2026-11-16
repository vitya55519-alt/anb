"""V3.167.3 (ТЗ Фогеля §3 «вернуть первый ход», владелец 16.11: «пусть это будет
всё в мини-приложении идти… в бот только оповещение вам написали»).

Он открыл чат, прочитал её первую строку и замер — что ответить. До этого релиза
на этом первый ход и заканчивался: в боте тишина (V3.148.0), а в приложении она
молчала, пока он сам не наберёт. Теперь, если через 90 с в диалоге нет ни одного
его слова, она пишет сама ещё раз — коротко, без кадра и без списаний, под те же
чипы. Больше двух строк на открытие: дальше это уже не живая девушка, а допрос.

В Telegram от этого ровно то, что там и так положено, — записка «💬 она написала
тебе в приложении» от ``services/app_ping`` и только когда он из приложения
вышел; сидит он внутри — видит её строку на экране.

Состояние живёт в памяти процесса: перезадеплой забывает недосланные строки, и
это правильное падение — лучше не дописать, чем прислать опоздавшую реплику
через час.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Один эпизод открытия живёт не дольше получаса: позже её «ты пропал?» читается
# как баг, а не как нетерпение.
EPISODE_TTL_SECONDS = 1800
# Сколько реплик готово к показу клиенту, прежде чем начнём выкидывать старые.
_MAX_READY = 256

# (telegram_id, character_id) -> эпизод, который ещё может дописать
_episodes: dict[tuple[int, str], dict] = {}
# тот же ключ -> строки, которые она уже написала, но клиент ещё не видел
_ready: dict[tuple[int, str], list[dict]] = {}
_tasks: set[asyncio.Task] = set()

_FIRST_RU = (
    'Эй… ты там? 🙈 Мне немного неловко писать первой дважды, но разговаривать с тобой правда хочется.',
    'Показалось, что я тебя потеряла? Я тут и никуда не ухожу 🙂',
    'Я, наверное, слишком много написала сразу. Скажи хотя бы «привет» — и я пойму твой темп 😌',
)
_SECOND_RU = (
    'Ладно, не буду давить. Просто знай, что этот чат у меня открыт 🙂',
    'Третий раз говорить сама с собой, а? 😅 Всё, замолкаю — но только на сегодня.',
)
_FIRST_EN = (
    'Hey… you there? 🙈 It feels a little awkward writing first twice, but I do want to talk to you.',
    'Did I lose you? I am still here, not going anywhere 🙂',
    'I probably wrote too much at once. Just say «hi» and I will match your pace 😌',
)
_SECOND_EN = (
    "Okay, I won't push. Just know I kept this chat open on my side 🙂",
    'Talking to myself for the third time 😅 Fine, going quiet — for today.',
)


def followup_text(step: int, lang: str = 'ru') -> str:
    """Её вторая (и третья) строка молчанию. Пул только русский и английский:
    всё, что не русский, говорит по-английски — как и остальной интерфейс
    приложения для неподдержанных языков."""
    en = (lang or '').strip().lower() != 'ru'
    if step >= 2:
        return random.choice(_SECOND_EN if en else _SECOND_RU)
    return random.choice(_FIRST_EN if en else _FIRST_RU)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _key(telegram_id: int, character_id: str) -> tuple[int, str]:
    return (int(telegram_id), str(character_id))


# ── серверная часть ───────────────────────────────────────────────────────
def arm(bot, telegram_id: int, uid: int, character_id: str, chips: list | None = None,
        lang: str = 'ru') -> bool:
    """Её первая строка легла в диалог — ждём 90 с и смотрим, ответил ли он."""
    from config import AUTO_OPENING_ENABLED, OPENING_NUDGE_MAX, OPENING_NUDGE_SECONDS
    if not AUTO_OPENING_ENABLED or OPENING_NUDGE_MAX <= 0:
        return False
    try:
        key = _key(telegram_id, character_id)
    except (TypeError, ValueError):
        return False
    episode = {'uid': int(uid), 'chips': [str(c) for c in (chips or []) if str(c).strip()],
               'lang': (lang or 'ru').strip().lower(), 'count': 0, 'start': _utcnow(),
               'at': time.monotonic()}
    _episodes[key] = episode
    if len(_ready) > _MAX_READY:
        cutoff = time.monotonic() - EPISODE_TTL_SECONDS
        for stale in [k for k, v in _ready.items() if not v or v[-1].get('at', 0.0) < cutoff]:
            _ready.pop(stale, None)
    task = asyncio.get_running_loop().create_task(_later(bot, key, episode, OPENING_NUDGE_SECONDS))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return True


def take(telegram_id: int, character_id: str) -> list[dict]:
    """Что клиент имеет право дорисовать прямо сейчас (и больше никогда)."""
    return _ready.pop(_key(telegram_id, character_id), []) or []


async def _later(bot, key: tuple, episode: dict, wait: float) -> None:
    from config import OPENING_NUDGE_MAX, OPENING_NUDGE_SECONDS
    try:
        while episode['count'] < OPENING_NUDGE_MAX:
            await asyncio.sleep(wait)
            wait = OPENING_NUDGE_SECONDS
            if not await _write(bot, key, episode):
                return
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning('opening nudge failed user=%s', key[0], exc_info=True)
    finally:
        if _episodes.get(key) is episode:
            _episodes.pop(key, None)


async def _write(bot, key: tuple, episode: dict) -> bool:
    """Одна её строка в ответ на молчание. False — эпизод закрыт и больше
    возвращаться не к чему."""
    if _episodes.get(key) is not episode:
        return False
    if time.monotonic() - episode['at'] > EPISODE_TTL_SECONDS:
        return False
    if await asyncio.to_thread(_he_wrote, episode['uid'], key[1], episode['start']):
        _episodes.pop(key, None)
        return False
    line = followup_text(episode['count'] + 1, episode['lang'])
    episode['count'] += 1
    from services.memory_service import save_message
    await asyncio.to_thread(save_message, episode['uid'], key[1], 'assistant', line)
    _ready.setdefault(key, []).append({'text': line, 'chips': list(episode['chips']),
                                       'at': time.monotonic()})
    logger.info('opening nudge written user=%s step=%s', key[0], episode['count'])
    # В боте от этого только «вам написали» — и только если он из приложения
    # уже вышел (решает services/app_ping: он внутри — он её видит на экране).
    try:
        from services import app_ping
        app_ping.note(bot, key[0], key[1], line)
    except Exception:
        logger.warning('opening nudge ping failed user=%s', key[0], exc_info=True)
    return True


def _he_wrote(uid: int, character_id: str, since: datetime) -> bool:
    """Его реплика после того, как она открыла диалог, — значит ход сыгран и
    второй раз она лезть не должна."""
    try:
        from sqlalchemy import func, select
        from models.app_models import Message
        from services.db import SessionLocal
        with SessionLocal() as s:
            return bool(s.scalar(select(func.count(Message.id)).where(
                Message.user_id == uid, Message.character_id == character_id,
                Message.role == 'user', Message.created_at >= since)))
    except Exception:
        logger.warning('opening nudge silence check failed', exc_info=True)
        return True


# ── для тестов ────────────────────────────────────────────────────────────
def _reset() -> None:
    _episodes.clear()
    _ready.clear()
    for task in list(_tasks):
        task.cancel()
    _tasks.clear()
