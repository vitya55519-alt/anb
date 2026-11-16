"""V3.167.4 #173 (владелец ТЗ §6, 16.11): её день не превращается в стену смс.

Пока он не отвечает, «жёлтых цветов» в диалоге накапливается не больше трёх
(LIFE_EVENTS_UNANSWERED_MAX). Рельса просто встаёт и ждёт — слот суток НЕ
сжигается, чтобы после его ответа она заговорила в этой же части суток снова.
Четыре неотвеченные строки читаются как рассылка, и он перестаёт их открывать.

Если он вернулся, а пауза, из которой он вышел, была длиннее трёх суток
(LIFE_EVENTS_DIGEST_AFTER_HOURS), догонять её по одной смс уже поздно: вместо
трёх опозданий приходит одна сводка, что у неё было, пока его не было. Сводка
склеена из её же строк, которые легли между его прошлым и нынешним сообщением:
без провайдера, без новых обещаний, ровно один раз за день.
"""
from __future__ import annotations

import datetime as dt
import logging

from config import LIFE_EVENTS_DIGEST_AFTER_HOURS, LIFE_EVENTS_UNANSWERED_MAX

logger = logging.getLogger(__name__)

#: сводка — про возврат, а не про отсутствие: позже суток после его реплики
#: она уже не «что я пропустил», а «почему ты молчишь»
RETURN_WINDOW_HOURS = 24

_digest_store = None            # DialogStore('life_backlog'), создаётся на первый вызов


def _store():
    global _digest_store
    if _digest_store is None:
        from services import dialog_store
        _digest_store = dialog_store.DialogStore('life_backlog')
    return _digest_store


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def unanswered(uid: int, character_id: str, limit: int = 6) -> list[tuple[str, dt.datetime]]:
    """Её реплики после его последнего слова — то, на что он ещё не ответил."""
    from sqlalchemy import func, select
    from models.app_models import Message
    from services.db import SessionLocal
    with SessionLocal() as s:
        last_his = s.scalar(select(func.max(Message.created_at)).where(
            Message.user_id == uid, Message.character_id == character_id, Message.role == 'user'))
        q = select(Message.content, Message.created_at).where(
            Message.user_id == uid, Message.character_id == character_id, Message.role == 'assistant')
        if last_his:
            q = q.where(Message.created_at > last_his)
        rows = s.execute(q.order_by(Message.created_at.asc()).limit(int(limit))).all()
    return [(str(r[0] or '').strip(), r[1]) for r in rows if (r[0] or '').strip()]


def is_capped(uid: int, character_id: str) -> bool:
    return len(unanswered(uid, character_id, LIFE_EVENTS_UNANSWERED_MAX)) >= LIFE_EVENTS_UNANSWERED_MAX


def _short(text: str, cap: int = 90) -> str:
    line = ' '.join(str(text or '').split())
    if len(line) <= cap:
        return line
    return line[:cap].rsplit(' ', 1)[0].rstrip(' ,;:.—-') + '…'


def digest_text(lines: list[str], lang: str = 'ru') -> str:
    """Одна строка вместо трёх. Нумерация её же, слова её же — ничего нового."""
    en = (str(lang or 'ru').strip().lower()[:2] != 'ru')
    items = [line for line in (_short(t) for t in lines[:LIFE_EVENTS_UNANSWERED_MAX]) if line]
    if not items:
        return ''
    if en:
        head = f"While you were away, I had {len(items)} things happen:"
        tail = 'Start with any of them and I will pick it up 💜'
    else:
        head = f'Пока тебя не было, у меня было {len(items)} истории:'
        tail = 'С любой и начнём 💜'
    return head + '\n' + '\n'.join(f'{i}) «{t}»' for i, t in enumerate(items, 1)) + '\n' + tail


def missed(uid: int, character_id: str) -> list[tuple[str, dt.datetime]]:
    """Её строки за его последнюю паузу — между его прошлым сообщением и тем,
    которым он вернулся. Догонять их по одной смс имеет смысл только сразу."""
    from sqlalchemy import select
    from models.app_models import Message
    from services.db import SessionLocal
    with SessionLocal() as s:
        q = select(Message.created_at).where(Message.user_id == uid,
                                             Message.character_id == character_id,
                                             Message.role == 'user').order_by(Message.created_at.desc())
        his = list(s.scalars(q).all())
        if len(his) < 2:
            return []                 # возвращаться пока некуда: он писал один раз
        latest, previous = his[0], his[1]
        rows = s.execute(select(Message.content, Message.created_at).where(
            Message.user_id == uid, Message.character_id == character_id,
            Message.role == 'assistant',
            Message.created_at > previous, Message.created_at < latest
        ).order_by(Message.created_at.asc()).limit(LIFE_EVENTS_UNANSWERED_MAX)).all()
    return [(str(r[0] or '').strip(), r[1]) for r in rows if (r[0] or '').strip()]


def due(uid: int, character_id: str, lang: str = 'ru') -> str:
    """Сводка положена, если пауза была длинной и её было что наполнить."""
    rows = missed(uid, character_id)
    if len(rows) < 2:
        return ''
    oldest = rows[0][1]
    if not oldest or (_utcnow() - oldest).total_seconds() / 3600.0 < LIFE_EVENTS_DIGEST_AFTER_HOURS:
        return ''
    return digest_text([t for t, _ in rows], lang)


def returned_recently(uid: int, character_id: str) -> bool:
    """Он написал за последние сутки — значит это возврат, а не его молчание."""
    try:
        from services.life_event_service import silence_hours
        return silence_hours(uid, character_id) <= RETURN_WINDOW_HOURS
    except Exception:
        return False


def already_sent_today(telegram_id: int, today: str) -> bool:
    try:
        return str((_store().get(int(telegram_id)) or {}).get('date') or '') == today
    except Exception:
        return True


async def maybe_digest(bot, uid: int, telegram_id: int, character_id: str,
                       lang: str = 'ru') -> bool:
    """True — она уже сказала что хотела, обычный пуш в этом скане не нужен."""
    try:
        if not returned_recently(uid, character_id):
            return False                  # он ещё молчит: сводка придёт на возврат
        text = due(uid, character_id, lang)
        if not text:
            return False
        today = _utcnow().date().isoformat()
        if already_sent_today(telegram_id, today):
            return True                       # сегодня уже была сводка — второй не надо
        from services.memory_service import save_message
        save_message(uid, character_id, 'assistant', text)
        await bot.send_message(telegram_id, text)
        _store()[int(telegram_id)] = {'date': today}
        try:
            from services.analytics_service import track_event
            track_event(uid, 'life_digest_sent', metadata={'character_id': character_id})
        except Exception:
            pass
        return True
    except Exception:
        logger.warning('life digest failed user=%s', telegram_id, exc_info=True)
        return False
