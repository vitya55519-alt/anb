"""V3.166.9 (владелец): состояние кадра, который дорисовывается в фоне.

Раньше весь кадр ждался внутри одного HTTP-запроса: её слова уже лежали в
истории, а он висел над «печатает…». Теперь ответ уходит сразу, картинка
дорисовывается фоном, а Mini App забирает её через
``/webapp/api/chat/photo-wait``. Здесь ровно то, что нужно для доставки: чей
кадр в работе и что пришло, когда он закончился. Генерация, гейты и списания
остались там же, где и были — в ``_photo_turn``.

Хранится как анкета кадра — ``DialogStore`` по (пользователь, героиня), новой
таблицы нет. Живёт 10 минут: дольше кадр не рисуется, а просроченная запись не
должна всплывать в следующем разговоре.
"""
from __future__ import annotations

import time
import uuid
from itertools import count

from services import dialog_store

TTL_SECONDS = 600
_store = dialog_store.DialogStore('chat_photo_wait')
# очередь кадров одного диалога: время в секундах различает не всё, а счётчик — всегда
_seq = count(1)


def _items(telegram_id: int, character_id: str) -> dict:
    """Непросроченные кадры этого диалога: {token: запись}."""
    got = (_store.get(int(telegram_id)) or {}).get(str(character_id))
    if not isinstance(got, dict):
        return {}
    now = time.time()
    return {k: v for k, v in got.items()
            if isinstance(v, dict) and now - float(v.get('at') or 0) < TTL_SECONDS}


def _save(telegram_id: int, character_id: str, items: dict) -> None:
    states = dict(_store.get(int(telegram_id)) or {})
    states[str(character_id)] = items
    _store[int(telegram_id)] = states


def begin(telegram_id: int, character_id: str) -> str:
    """Отметить кадр в работе и вернуть токен этой доставки."""
    token = uuid.uuid4().hex[:12]
    items = _items(telegram_id, character_id)
    items[token] = {'at': int(time.time()), 'seq': next(_seq), 'state': 'rendering'}
    _save(telegram_id, character_id, items)
    return token


def deliver(telegram_id: int, character_id: str, token: str, payload: dict) -> bool:
    """Кадр готов — положить ответ. ``False``, если он уже не нужен."""
    items = _items(telegram_id, character_id)
    if token not in items:
        return False
    items[token] = {'at': int(time.time()), 'seq': items[token].get('seq') or next(_seq),
                    'state': 'ready', 'payload': dict(payload)}
    _save(telegram_id, character_id, items)
    return True


def take(telegram_id: int, character_id: str) -> dict | None:
    """Один готовый кадр, старый вперёд; забирается один раз, чтобы SPA не
    показал его дважды."""
    items = _items(telegram_id, character_id)
    ready = [k for k, v in items.items() if v.get('state') == 'ready']
    if not ready:
        return None
    oldest = min(ready, key=lambda k: int(items[k].get('seq') or 0))
    payload = items.pop(oldest).get('payload')
    _save(telegram_id, character_id, items)
    return payload if isinstance(payload, dict) else None


def pending(telegram_id: int, character_id: str) -> bool:
    """Есть ли в этом диалоге кадр, который ещё рисуется."""
    return any(v.get('state') != 'ready' for v in _items(telegram_id, character_id).values())


def waiting(telegram_id: int, character_id: str) -> bool:
    """Осталось ли что-то после того, как SPA забрал один ответ: он продолжит
    ждать, пока в этом диалоге есть и второй кадр."""
    return bool(_items(telegram_id, character_id))
