"""V3.132.0: «Раздеть» bought one at a time (50 ₽ / 40 ⭐), without Premium.

A purchase adds one credit; a successful «Раздеть» in the Mini App spends one.
A failed render spends nothing. Kept in dialog_sessions (DictStore) — no new
schema. Product key / payload: ``undress_one``.
"""
from __future__ import annotations

from services import dialog_store

PRODUCT = 'undress_one'
_store = dialog_store.DialogStore('undress_credits')


def balance(telegram_id: int) -> int:
    got = _store.get(int(telegram_id)) or {}
    try:
        return max(0, int(got.get('n', 0) if hasattr(got, 'get') else 0))
    except (TypeError, ValueError):
        return 0


def add(telegram_id: int, n: int = 1) -> int:
    left = balance(telegram_id) + max(0, int(n))
    _store[int(telegram_id)] = {'n': left}
    return left


def spend(telegram_id: int) -> bool:
    have = balance(telegram_id)
    if have <= 0:
        return False
    _store[int(telegram_id)] = {'n': have - 1}
    return True
