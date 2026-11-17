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
import json
import threading

from config import LIFE_EVENTS_DIGEST_AFTER_HOURS, LIFE_EVENTS_UNANSWERED_MAX

logger = logging.getLogger(__name__)

#: сводка — про возврат, а не про отсутствие: позже суток после его реплики
#: она уже не «что я пропустил», а «почему ты молчишь»
RETURN_WINDOW_HOURS = 24

# V3.167.5 (владелец ТЗ §9, 16.11): чья строка в диалоге. Пишется в
# messages.origin и только по ней видно, что ОНА написала первой: обыкновенный
# ответ на его сообщение — не неотвеченный пуш, и кап накопления, и «ответил ли
# он на её день» считаются по этим трём меткам.
PUSH_ORIGIN = 'push'          # маркетинг, лестница замолкания, ритуалы, карточка
LIFE_ORIGIN = 'life'          # «её день» (жизнь, живая ситуация)
DIGEST_ORIGIN = 'digest'      # сводка на возврат
PUSHED_ORIGINS = (PUSH_ORIGIN, LIFE_ORIGIN, DIGEST_ORIGIN)

_digest_store = None            # DialogStore('life_backlog'), создаётся на первый вызов


def _store():
    global _digest_store
    if _digest_store is None:
        from services import dialog_store
        _digest_store = dialog_store.DialogStore('life_backlog')
    return _digest_store


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def local_day(tz_name=None, now: dt.datetime | None = None) -> tuple[str, dt.datetime]:
    """His date and its midnight in naive UTC, matching persisted timestamps."""
    from zoneinfo import ZoneInfo
    utc = now or _utcnow()
    utc = utc.replace(tzinfo=dt.timezone.utc) if utc.tzinfo is None else utc
    try:
        local = utc.astimezone(ZoneInfo(tz_name or 'UTC'))
    except Exception:
        local = utc.astimezone(dt.timezone.utc)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return local.date().isoformat(), start.astimezone(dt.timezone.utc).replace(tzinfo=None)


_journal_lock = threading.RLock()
_denial_memo: dict[tuple[int, str, str], str] = {}


def note_denial(uid: int, rail: str, reason: str, tz_name=None) -> None:
    """push_denied(rail, reason), once per user's local day, including restarts."""
    if not uid:
        return
    try:
        from sqlalchemy import select
        from models.app_models import ProductEvent, User
        from services.db import SessionLocal
        with _journal_lock, SessionLocal() as s:
            if tz_name is None:
                tz_name = s.scalar(select(User.timezone).where(User.id == int(uid)))
            today, start = local_day(tz_name)
            key = (int(uid), rail, reason)
            if _denial_memo.get(key) == today:
                return
            prior = s.scalars(select(ProductEvent.metadata_json).where(
                ProductEvent.user_id == int(uid), ProductEvent.event_name == 'push_denied',
                ProductEvent.created_at >= start)).all()
            hit = any((json.loads(raw or '{}').get('rail'), json.loads(raw or '{}').get('reason'))
                      == (rail, reason) for raw in prior)
            if not hit:
                from services.analytics_service import track_event
                track_event(int(uid), 'push_denied', metadata={'rail': rail, 'reason': reason})
            if len(_denial_memo) > 20000:
                _denial_memo.clear()
            _denial_memo[key] = today
    except Exception:
        logger.debug('life denial journal failed user=%s', uid, exc_info=True)


def _pushed(uid: int, character_id: str, limit: int = 6) -> list[tuple[str, dt.datetime, str]]:
    """Её собственные ходы в диалоге: (текст, когда, чей рельс)."""
    from sqlalchemy import func, select
    from models.app_models import Message
    from services.db import SessionLocal
    with SessionLocal() as s:
        last_his = s.scalar(select(func.max(Message.created_at)).where(
            Message.user_id == uid, Message.character_id == character_id, Message.role == 'user'))
        q = select(Message.content, Message.created_at, Message.origin).where(
            Message.user_id == uid, Message.character_id == character_id, Message.role == 'assistant',
            Message.origin.in_(PUSHED_ORIGINS))
        if last_his:
            q = q.where(Message.created_at > last_his)
        rows = s.execute(q.order_by(Message.created_at.asc()).limit(int(limit))).all()
    return [(str(r[0] or '').strip(), r[1], str(r[2] or '')) for r in rows if (r[0] or '').strip()]


def unanswered(uid: int, character_id: str, limit: int = 6) -> list[tuple[str, dt.datetime]]:
    """Её реплики после его последнего слова — то, на что он ещё не ответил.
    V3.167.5: считаются только строки с меткой рельса (messages.origin): ответ
    на его сообщение неотвеченным пушем быть не может."""
    return [(text, when) for text, when, _origin in _pushed(uid, character_id, limit)]


def note_replied(uid: int, character_id: str) -> int:
    """V3.167.5 §9: «ответы на её день ≥12%» из DoD владельца. Вызывается на
    ЕГО ходу, до того как его сообщение легло в диалог, — иначе хвост уже пуст и
    ответить не на что. Считает только её строки жизни и сводки: ответ на
    маркетинговый пуш измеряется прежним proactive_replied."""
    try:
        rows = _pushed(int(uid), character_id, LIFE_EVENTS_UNANSWERED_MAX)
        life = sum(1 for _t, _w, origin in rows if origin in (LIFE_ORIGIN, DIGEST_ORIGIN))
        if not life:
            return 0
        from services.analytics_service import track_event
        track_event(int(uid), 'life_event_replied',
                    metadata={'character_id': character_id, 'unanswered': len(rows), 'life': life})
        return life
    except Exception:
        logger.debug('life reply track failed user=%s', uid, exc_info=True)
        return 0


def is_capped(uid: int, character_id: str) -> bool:
    return len(unanswered(uid, character_id, LIFE_EVENTS_UNANSWERED_MAX)) >= LIFE_EVENTS_UNANSWERED_MAX


def _short(text: str, cap: int = 90) -> str:
    from services.chat_service import message_block
    line = ' '.join(message_block(str(text or '')).split())
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


def missed(uid: int, character_id: str, *, on_open: bool = False) -> list[tuple[str, dt.datetime]]:
    """Её строки за его последнюю паузу — между его прошлым сообщением и тем,
    которым он вернулся. Догонять их по одной смс имеет смысл только сразу."""
    from sqlalchemy import select
    from models.app_models import Message
    from services.db import SessionLocal
    with SessionLocal() as s:
        q = select(Message.created_at).where(Message.user_id == uid,
                                             Message.character_id == character_id,
                                             Message.role == 'user').order_by(Message.created_at.desc())
        his = list(s.scalars(q.limit(2)).all())
        if not his or (not on_open and len(his) < 2):
            return []
        latest, previous = (_utcnow(), his[0]) if on_open else (his[0], his[1])
        # A previous summary is a real boundary, never a synthetic user turn.
        summarized = s.scalar(select(Message.created_at).where(
            Message.user_id == uid, Message.character_id == character_id,
            Message.origin == DIGEST_ORIGIN).order_by(Message.created_at.desc()).limit(1))
        if summarized:
            previous = max(previous, summarized)
        rows = s.execute(select(Message.content, Message.created_at).where(
            Message.user_id == uid, Message.character_id == character_id,
            Message.role == 'assistant', Message.origin.in_((PUSH_ORIGIN, LIFE_ORIGIN)),
            Message.created_at > previous, Message.created_at < latest
        ).order_by(Message.created_at.asc()).limit(LIFE_EVENTS_UNANSWERED_MAX)).all()
    return [(str(r[0] or '').strip(), r[1]) for r in rows if (r[0] or '').strip()]


def due(uid: int, character_id: str, lang: str = 'ru', *, on_open: bool = False) -> str:
    """Сводка положена, если пауза была длинной и её было что наполнить."""
    rows = missed(uid, character_id, on_open=on_open)
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


def _persist_digest(uid: int, telegram_id: int, character_id: str, lang: str,
                    *, on_open: bool = False) -> tuple[bool, int | None]:
    """Commit the summary and daily marker together, before any notification."""
    from sqlalchemy import select
    from models.app_models import DialogSession, Message, User
    from services.db import SessionLocal
    if not on_open and not returned_recently(uid, character_id):
        return False, None
    # UPDATE also serializes separate SQLite processes, unlike FOR UPDATE.
    from sqlalchemy import update
    with _journal_lock, SessionLocal() as s:
        s.execute(update(User).where(User.id == uid).values(chat_used=User.chat_used))
        user = s.get(User, uid)
        if not user or str(user.telegram_id) != str(telegram_id):
            return False, None
        today, start = local_day(user.timezone)
        prior = s.scalar(select(Message.id).where(
            Message.user_id == uid, Message.origin == DIGEST_ORIGIN,
            Message.created_at >= start).limit(1))
        if prior:
            return True, None
        text = due(uid, character_id, lang, on_open=on_open)
        if not text:
            return False, None
        row = Message(user_id=uid, character_id=character_id, role='assistant',
                      content=text, origin=DIGEST_ORIGIN)
        s.add(row)
        marker = s.scalar(select(DialogSession).where(
            DialogSession.telegram_id == int(telegram_id), DialogSession.session_key == 'life_backlog'))
        if marker is None:
            marker = DialogSession(telegram_id=int(telegram_id), session_key='life_backlog')
            s.add(marker)
        marker.payload_json = json.dumps({'date': today})
        s.commit()
        mid = row.id
    try:
        from services.analytics_service import track_event
        track_event(uid, 'digest_shown', metadata={'character_id': character_id})
    except Exception:
        pass
    return True, mid


def digest_on_open(uid: int, telegram_id: int, character_id: str, lang: str = 'ru') -> int | None:
    """Summarize once on explicit open, without generation or a synthetic user turn."""
    try:
        return _persist_digest(uid, telegram_id, character_id, lang, on_open=True)[1]
    except Exception:
        logger.warning('life open digest failed user=%s', telegram_id, exc_info=True)
        return None


async def maybe_digest(bot, uid: int, telegram_id: int, character_id: str,
                       lang: str = 'ru') -> bool:
    """True — она уже сказала что хотела, обычный пуш в этом скане не нужен."""
    try:
        handled, mid = _persist_digest(uid, telegram_id, character_id, lang)
    except Exception:
        logger.warning('life digest failed user=%s', telegram_id, exc_info=True)
        return False
    if mid:
        try:
            from services import app_ping
            app_ping.note(bot, telegram_id, character_id, '', generic=True)
        except Exception:
            logger.warning('digest notification failed user=%s', telegram_id, exc_info=True)
    return handled
