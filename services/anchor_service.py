"""V3.155.0: owner ТЗ (Фогель, Модуль 3) — «Эмоциональные якоря».

Якорь — это не факт о нём (для этого есть таблица ``memories``), а общий
момент пары: первая ночь, сцена, где их чуть не застали, его признание, шутка,
понятная только им двоим. Поэтому у якорей своя таблица ``user_character_anchors``
и свой промпт: «память» намеренно не хранит интимную историю, а здесь это и есть
предмет.

Каждые ``ANCHOR_EVERY_MESSAGES`` его сообщений фоновый worker перечитает
последний кусок диалога и вытащит ОДИН новый якорь; хранятся только последние
``ANCHOR_MAX`` на пару. Блок ``[SHARED EMOTIONAL MEMORY (ЯКОРЯ ВАШЕЙ ИСТОРИИ)]``
едет в системный промпт каждого ответа, а «вспомни вслух именно сейчас»
выпадает раз в ``ANCHOR_ECHO_MIN..MAX`` реплик — иначе память звучит как
зачитывание базы, а не как человека, которого что-то цепануло.

Блок живёт ТОЛЬКО в системном промпте: озвучка (TTS) читает текст её сообщения,
поэтому служебная инструкция никогда не звучит голосом.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import random

from sqlalchemy import delete, func, select

from config import (ANCHOR_ECHO_MAX, ANCHOR_ECHO_MIN, ANCHOR_EVERY_MESSAGES,
                    ANCHOR_MAX, ANCHOR_WINDOW_MESSAGES, ANCHORS_ENABLED)
from models.app_models import Message, UserCharacterAnchor
from services import dialog_store
from services.db import SessionLocal

logger = logging.getLogger(__name__)

# per (user, girl): {'left': replies until the next recollection, 'i': which
# anchor comes next} — the rhythm survives a restart, the schema does not change
_state = dialog_store.DialogStore('anchors')

_MAX_ANCHOR_CHARS = 140

EXTRACT_PROMPT = (
    'Из переписки выбери ОДИН самый яркий эмоциональный момент, который они '
    'пережили вдвоём: первое признание или первая ночь, сцена, где их чуть не '
    'застали, ревность и примирение, его откровенный разговор, шутка, понятная '
    'только им. Пиши от её лица и про вас двоих, коротко (до 15 слов): «как мы…», '
    '«тот вечер, когда…». Бери только то, что реально было в этих сообщениях, — '
    'ничего не выдумывай и не додумывай. Не сохраняй пароли, платёжные данные, '
    'точные адреса и названия компаний. Верни только JSON: {"anchor":"..."}; если '
    'яркого момента в этих сообщениях нет: {"anchor":""}.'
)


def _now():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def user_message_count(user_id: int, character_id: str) -> int:
    with SessionLocal() as s:
        return int(s.scalar(
            select(func.count(Message.id))
            .where(Message.user_id == int(user_id),
                   Message.character_id == str(character_id),
                   Message.role == 'user')
        ) or 0)


def dialog_window(user_id: int, character_id: str, limit: int = ANCHOR_WINDOW_MESSAGES) -> str:
    """The last stretch of the dialog as a plain transcript — the only thing the
    worker is allowed to remember from."""
    with SessionLocal() as s:
        rows = s.scalars(
            select(Message)
            .where(Message.user_id == int(user_id), Message.character_id == str(character_id))
            .order_by(Message.created_at.desc()).limit(max(4, int(limit)))
        ).all()
    lines = []
    for m in reversed(rows):
        text = (m.content or '').strip()
        if not text:
            continue
        lines.append(('Он: ' if m.role == 'user' else 'Она: ') + text[:400])
    return '\n'.join(lines)


def add_anchor(user_id: int, character_id: str, content: str) -> None:
    """Store one anchor and keep only the ANCHOR_MAX brightest of the pair."""
    content = ' '.join(str(content or '').split())[:_MAX_ANCHOR_CHARS]
    if not content:
        return
    with SessionLocal() as s:
        exists = s.scalar(
            select(UserCharacterAnchor.id)
            .where(UserCharacterAnchor.user_id == int(user_id),
                   UserCharacterAnchor.character_id == str(character_id),
                   UserCharacterAnchor.content == content)
        )
        if exists:
            return
        s.add(UserCharacterAnchor(user_id=int(user_id), character_id=str(character_id),
                                  content=content, created_at=_now()))
        s.commit()
        keep = [a.id for a in s.scalars(
            select(UserCharacterAnchor)
            .where(UserCharacterAnchor.user_id == int(user_id),
                   UserCharacterAnchor.character_id == str(character_id))
            .order_by(UserCharacterAnchor.created_at.desc(), UserCharacterAnchor.id.desc())
            .limit(ANCHOR_MAX)
        ).all()]
        if keep:
            s.execute(delete(UserCharacterAnchor)
                      .where(UserCharacterAnchor.user_id == int(user_id),
                             UserCharacterAnchor.character_id == str(character_id),
                             UserCharacterAnchor.id.not_in(keep)))
        s.commit()


def list_anchors(user_id: int, character_id: str) -> list[str]:
    """The latest ANCHOR_MAX moments, oldest first — she remembers them in order."""
    with SessionLocal() as s:
        rows = s.scalars(
            select(UserCharacterAnchor)
            .where(UserCharacterAnchor.user_id == int(user_id),
                   UserCharacterAnchor.character_id == str(character_id))
            .order_by(UserCharacterAnchor.created_at.desc(), UserCharacterAnchor.id.desc())
            .limit(ANCHOR_MAX)
        ).all()
    return [r.content for r in reversed(list(rows))]


def _echo_state(user_id: int, character_id: str, total: int) -> int:
    """How many live replies are left before the next recollection; the count
    lives in DialogStore('anchors'), so a restart does not reset the rhythm.
    Returns the index of the anchor she should remember in THIS answer, or -1
    for «not this time». ТЗ: раз в 4–5 сообщений — neither every reply nor a
    remembered date every tenth line reads as a person."""
    if total <= 0:
        return -1
    data = dict(_state.get(int(user_id)) or {})
    item = data.get(str(character_id))
    if not isinstance(item, dict):
        # the reply that first found the anchors starts the clock, it does not
        # already recollect: «раз в 4–5», а не «сразу же»
        data[str(character_id)] = {'left': random.randint(ANCHOR_ECHO_MIN, ANCHOR_ECHO_MAX) - 1,
                                   'i': 0}
        _echo_save(user_id, data)
        return -1
    left = int(item.get('left') or 0)
    idx = int(item.get('i') or 0) % total
    if left > 0:
        item['left'] = left - 1
        _echo_save(user_id, data)
        return -1
    item['left'] = random.randint(ANCHOR_ECHO_MIN, ANCHOR_ECHO_MAX) - 1
    item['i'] = idx + 1
    _echo_save(user_id, data)
    return idx


def _echo_save(user_id: int, data: dict) -> None:
    try:
        _state[int(user_id)] = data
    except Exception:
        logger.warning('anchor echo state save failed user=%s', user_id)


def anchors_block(user_id: int, character_id: str, *, tick: bool = False) -> str:
    """The system-prompt block. ``tick=True`` (a live reply only) spends one
    step of the recollection counter and, when it lands, names the exact anchor
    to remember in THIS answer."""
    if not ANCHORS_ENABLED:
        return ''
    anchors = list_anchors(user_id, character_id)
    if not anchors:
        return ''
    lines = ['[SHARED EMOTIONAL MEMORY (ЯКОРЯ ВАШЕЙ ИСТОРИИ)]']
    lines += [f'- {a}' for a in anchors]
    lines.append(
        'Это ваши настоящие общие моменты, они и правда были. Не выдумывай '
        'деталей, которых среди них нет.')
    lines.append(
        'Периодически — раз в 4–5 сообщений — естественно отсылайся к одному из '
        'них: одной живой деталью в своих мыслях (THOUGHT) или в словах (MESSAGE), '
        'как живой человек, которого что-то цепануло. Не повторяй тот же якорь '
        'дважды подряд, не пересказывай момент целиком и не превращай '
        'воспоминание в монолог — рядом всегда должен быть сегодняшний разговор.')
    if tick:
        pick = _echo_state(user_id, character_id, len(anchors))
        if 0 <= pick < len(anchors):
            lines.append(f'ИМЕННО В ЭТОМ ОТВЕТЕ вспомни: «{anchors[pick]}» — между '
                         'делом, одной короткой деталью, без объяснений, откуда это взялось.')
    return '\n'.join(lines)


async def maybe_extract_anchor(user_id: int, character_id: str) -> None:
    """Background worker: every ANCHOR_EVERY_MESSAGES of his messages, pull one
    new anchor out of the last stretch of the dialog."""
    if not ANCHORS_ENABLED:
        return
    try:
        count = await asyncio.to_thread(user_message_count, user_id, character_id)
    except Exception:
        logger.warning('anchor count failed user=%s', user_id, exc_info=True)
        return
    if count % ANCHOR_EVERY_MESSAGES:
        return
    transcript = await asyncio.to_thread(dialog_window, user_id, character_id)
    if len(transcript) < 200:
        # «ок / ага» for fifteen lines is not a story, and the round trip would
        # only invent a moment the two of them never had
        return
    from services.llm_provider_service import generate_text
    try:
        r = await generate_text(
            messages=[{'role': 'system', 'content': EXTRACT_PROMPT},
                      {'role': 'user', 'content': transcript[:6000]}],
            max_tokens=120, temperature=0.6, purpose='anchor_extraction')
    except Exception:
        logger.warning('anchor extraction failed user=%s', user_id, exc_info=True)
        return
    anchor = parse_anchor(r.text)
    if not anchor:
        return
    await asyncio.to_thread(add_anchor, user_id, character_id, anchor)


def parse_anchor(text: str) -> str:
    """The worker returns one JSON line; anything else (prose, a second anchor,
    a refusal) is simply not stored."""
    from services.memory_service import _extract_json
    data = _extract_json(text or '')
    if not isinstance(data, dict):
        return ''
    value = data.get('anchor')
    if isinstance(value, list):
        value = value[0] if value else ''
    content = ' '.join(str(value or '').split())
    if not content or content.lower() in {'none', 'null', 'нет', ''}:
        return ''
    return content[:_MAX_ANCHOR_CHARS]
