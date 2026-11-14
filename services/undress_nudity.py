"""V3.165.0 (#107, owner): «Раздеть» — один раз в сутки.

A successful reveal marks her nude in this dialog for 24 hours. Inside that
window the second tap on «🔥 Раздеть» renders and charges nothing: there is
nothing left to take off, so she answers that she is already naked and offers
the next frame instead. Keyed per character inside ``dialog_sessions``
(DictStore), the same way ``undress_credits`` stores its one-off credits — no
new schema.
"""
from __future__ import annotations

import time

from services import dialog_store

WINDOW_SECONDS = 24 * 3600
_store = dialog_store.DialogStore('undress_nudity')


def mark(telegram_id: int, character_id: str) -> None:
    states = dict(_store.get(int(telegram_id)) or {})
    states[str(character_id)] = int(time.time())
    _store[int(telegram_id)] = states


def is_nude(telegram_id: int, character_id: str) -> bool:
    got = (_store.get(int(telegram_id)) or {}).get(str(character_id))
    try:
        at = int(got or 0)
    except (TypeError, ValueError):
        return False
    return bool(at) and (time.time() - at) < WINDOW_SECONDS
