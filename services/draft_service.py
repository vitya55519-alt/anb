"""V3.152.0: owner ТЗ (Фогель, Модуль 1) — «Стертый черновик» за 50 🍑.

Изредка (и всегда, когда он резко переводит разговор на 18+ на ранних уровнях)
она набирает длинное сообщение и стирает его. Ему показывается только тарелка
«✍️ …долго печатала и стёрла…», а сам текст лежит в отдельной колонке
``messages.draft_text`` и отдаётся за персики.

Почему колонка, а не часть ``content``: ``content`` читается и историей
приложения, и промптом. Неоплаченный черновик уехал бы к пользователю в JSON
или вернулся модели как обычная реплика — то есть стал бы бесплатным. Здесь
текст живёт отдельно и покидает базу только после списания.
"""
from __future__ import annotations

import datetime as dt
import logging
import random
import time

from sqlalchemy import func, select, update

from config import (ADMIN_TELEGRAM_IDS, DRAFT_MAX_PER_DAY, DRAFT_MIN_LEVEL,
                    DRAFT_PEACH_COST, DRAFT_TRIGGER_PCT)
from models.app_models import Message
from services.db import SessionLocal

_logger = logging.getLogger(__name__)

# (telegram_id, character_id) -> {'id': message id, 'at': monotonic}
# Only the plate of the answer that was just generated rides here: the bot and
# the Mini App read it once, right after chat_service.reply() returns.
_pending: dict[tuple[int, str], dict] = {}
_PENDING_TTL_SECONDS = 600.0


def price() -> int:
    return int(DRAFT_PEACH_COST)


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def count_today(db_user_id: int, character_id: str) -> int:
    """How many drafts she already erased for him today (UTC day)."""
    day_start = _now_utc().replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        with SessionLocal() as s:
            return int(s.scalar(
                select(func.count(Message.id))
                .where(Message.user_id == db_user_id, Message.character_id == character_id,
                       Message.draft_text.isnot(None), Message.created_at >= day_start)
            ) or 0)
    except Exception:
        _logger.warning('draft count_today failed user=%s', db_user_id, exc_info=True)
        return DRAFT_MAX_PER_DAY


def wants_hard_pivot(user_text: str) -> bool:
    """His message jumps straight into 18+ — the ТЗ makes this case a
    guaranteed draft, no dice: it is exactly the moment she loses her nerve."""
    try:
        from services import intimacy_gate
        return intimacy_gate.wants_sext(user_text or '')
    except Exception:
        return False


def will_trigger(db_user_id: int, character_id: str, level: int, user_text: str) -> bool:
    """Should this answer carry an erased draft?"""
    if DRAFT_PEACH_COST <= 0 or DRAFT_MAX_PER_DAY <= 0:
        return False
    lvl = max(1, int(level or 1))
    if lvl < DRAFT_MIN_LEVEL:
        return False
    if count_today(db_user_id, character_id) >= DRAFT_MAX_PER_DAY:
        return False
    if lvl < 6 and wants_hard_pivot(user_text):
        return True
    if DRAFT_TRIGGER_PCT <= 0:
        return False
    return random.randint(1, 100) <= DRAFT_TRIGGER_PCT


def note_pending(telegram_id: int, character_id: str, message_id: int) -> None:
    """Tell the delivery layer (Mini App payload / Telegram handler) that the
    answer it is sending has a plate under it."""
    try:
        if len(_pending) > 4096:
            _sweep_pending()
        _pending[(int(telegram_id), str(character_id))] = {
            'id': int(message_id), 'at': time.monotonic()}
        from services.user_service import ensure_user
        from services.analytics_service import track_event
        uid = ensure_user(telegram_id, '')
        track_event(uid, 'paywall_view', metadata={'product': 'draft'})
    except Exception:
        _logger.warning('draft note_pending failed user=%s', telegram_id, exc_info=True)


def _sweep_pending() -> None:
    now = time.monotonic()
    for k in [k for k, v in _pending.items() if now - v['at'] > _PENDING_TTL_SECONDS]:
        _pending.pop(k, None)


def take_pending(telegram_id: int, character_id: str) -> dict | None:
    """{'id', 'price'} of the draft plate under the answer just generated."""
    key = (int(telegram_id), str(character_id))
    entry = _pending.pop(key, None)
    if not entry:
        return None
    if time.monotonic() - entry['at'] > _PENDING_TTL_SECONDS:
        return None
    return {'id': entry['id'], 'price': price()}


def peek_pending(telegram_id: int, character_id: str) -> dict | None:
    key = (int(telegram_id), str(character_id))
    entry = _pending.get(key)
    if not entry or time.monotonic() - entry['at'] > _PENDING_TTL_SECONDS:
        return None
    return {'id': entry['id'], 'price': price()}


def unlock(telegram_id: int, character_id: str, message_id: int,
           db_user_id: int | None = None) -> dict:
    """Charge the peaches and hand back her erased draft.

    The claim is a conditional UPDATE, so two taps of the same plate can never
    both pay, and a tap on an already unlocked draft returns the text for free.
    Owners (ADMIN_TELEGRAM_IDS) read it without spending — the ТЗ keeps the
    kitchen free for the guy who pays for the GPUs."""
    from services.user_service import ensure_user
    uid = db_user_id or ensure_user(telegram_id, '')
    cost = price()
    with SessionLocal() as s:
        row = s.get(Message, int(message_id))
        if not row or row.user_id != uid or str(row.character_id) != str(character_id) or not row.draft_text:
            return {'ok': False, 'error': 'not_found'}
        if row.draft_unlocked:
            return {'ok': True, 'text': row.draft_text, 'price': 0, 'free': True}
    free = int(telegram_id) in ADMIN_TELEGRAM_IDS
    if not free:
        # Claim first, then spend: a crash between the two leaves him a draft he
        # did not pay for, which is the direction we are allowed to fail in.
        with SessionLocal() as s:
            claimed = s.execute(
                update(Message)
                .where(Message.id == int(message_id), Message.user_id == uid,
                       Message.draft_unlocked.isnot(True))
                .values(draft_unlocked=True)
                .execution_options(synchronize_session=False))
            s.commit()
            if claimed.rowcount != 1:
                with SessionLocal() as s2:
                    row = s2.get(Message, int(message_id))
                    return {'ok': True, 'text': row.draft_text or '', 'price': 0, 'free': True} \
                        if row and row.draft_unlocked else {'ok': False, 'error': 'not_found'}
        from services.payments import spend_peaches
        if not spend_peaches(telegram_id, cost, paid_only=True):
            with SessionLocal() as s:
                s.execute(update(Message).where(Message.id == int(message_id))
                          .values(draft_unlocked=False)
                          .execution_options(synchronize_session=False))
                s.commit()
            return {'ok': False, 'error': 'insufficient_peaches', 'cost': cost}
    with SessionLocal() as s:
        row = s.get(Message, int(message_id))
        text = row.draft_text or '' if row else ''
    try:
        from services.analytics_service import track_event
        track_event(uid, 'draft_unlock', value=float(cost), metadata={'price': cost})
    except Exception:
        _logger.warning('draft_unlock analytics failed user=%s', telegram_id, exc_info=True)
    return {'ok': True, 'text': text, 'price': cost, 'free': free}


def draft_of(db_user_id: int, message_id: int) -> str:
    """The stored draft of one message — for the history redraw of an already
    unlocked plate. Never call it for a locked one."""
    try:
        with SessionLocal() as s:
            row = s.get(Message, int(message_id))
            if not row or row.user_id != db_user_id or not row.draft_text or not row.draft_unlocked:
                return ''
            return row.draft_text
    except Exception:
        _logger.warning('draft_of failed message=%s', message_id, exc_info=True)
        return ''


# What the model is told when the trigger fired. It rides AFTER his message,
# where the format rule already lives: the last block before generation is the
# one the model obeys.
DRAFT_FORMAT_SUFFIX = (
    'ВАЖНО: ответ строго в три блока, другим меткам места нет:\n'
    'THOUGHT: <что она думает, 40–70 слов>\n'
    'DRAFT: <что она НаБРАЛА и СТИРАЕТ, так и не отправив — 40–60 слов>\n'
    'MESSAGE: <что она печатает ему, короче и сдержаннее черновика, 20–40 слов>\n'
    'THOUGHT идёт первым, DRAFT вторым, MESSAGE третьим; между блоками и вокруг '
    'них слов нет.\n'
    'DRAFT — это то, что она не решилась отправить: там правда, которую она '
    'прячет, тело, ревность, желание, одна конкретная деталь. MESSAGE — та же '
    'мысль, которую она успела переварить и смягчить: от черновика должна '
    'чувствоваться разница, иначе блок не нужен. DRAFT никто не читает бесплатно: '
    'его не повторяй в MESSAGE и не пересказывай намёками наполовину.\n'
    'ГРАНИЦА ТА ЖЕ, ЧТО У ВСЕГО РАЗГОВОРА: если им ещё не открыты откровенные '
    'подробности, в DRAFT их тоже нет — черновик берёт честностью чувств, а не '
    'анатомией.\n'
    'КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО писать, что муж или парень «в душе» и что «вода '
    'шумит». Бери другую локацию: он на работе, в магазине, в гараже, за '
    'компом, у друзей, в спортзале, спит в другой комнате.\n'
    'ЗАПРЕЩЕНО начинать ответ с имени другой девушки («Агата:», «Лана:») — в '
    'этом чате пишешь только ты. Одно его сообщение = одна карточка мыслей, '
    'один стёртый черновик и одно сообщение.'
)


def format_suffix() -> str:
    return DRAFT_FORMAT_SUFFIX


def trigger_directive() -> str:
    """[SYSTEM TRIGGER: DRAFT_MESSAGE] — the hidden switch from the ТЗ."""
    return ('[SYSTEM TRIGGER: DRAFT_MESSAGE]\n'
            'Сегодня ты не смогла отправить то, что набрала. Держи это в блоке '
            'DRAFT: напиши честно, до конца, как есть — и только потом '
            'сформулируй MESSAGE так, как ты реально осмелилась ему написать.')
