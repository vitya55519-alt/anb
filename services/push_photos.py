"""V3.63.2: owner-uploaded photos for pushes, per character.

The repository is public, so the owner's 18+ shots must not live in git. The
owner sends a photo to the bot with the caption ``/storyphoto <name>`` and we
keep only Telegram's ``file_id`` (the file stays on Telegram's servers),
grouped by character. Story hooks show one of them with the story, and the
first-evening offer blurs one of them into its locked cover — each girl
pushes with her own pictures instead of the default heroine's café shot.

Stored in DialogStore under a fixed key (0) — no schema change.
"""
from __future__ import annotations

import random

from services import dialog_store

_store = dialog_store.DialogStore('push_photos')
_KEY = 0
MAX_PER_CHARACTER = 30


def _all() -> dict[str, list[str]]:
    try:
        raw = _store.get(_KEY) or {}
        return {str(k): list(v) for k, v in dict(raw).items()}
    except Exception:
        return {}


def add(character_id: str, file_id: str) -> int:
    """Remember a photo for ``character_id``; returns how many she has now."""
    data = _all()
    items = [f for f in data.get(character_id, []) if f != file_id]
    items.append(file_id)
    data[character_id] = items[-MAX_PER_CHARACTER:]
    _store[_KEY] = data
    return len(data[character_id])


def clear(character_id: str) -> int:
    data = _all()
    removed = len(data.pop(character_id, []))
    _store[_KEY] = data
    return removed


def counts() -> dict[str, int]:
    return {k: len(v) for k, v in _all().items() if v}


def pick(character_id: str) -> str | None:
    items = _all().get(character_id or '', [])
    return random.choice(items) if items else None


def resolve_character(name: str, cards) -> str | None:
    """Match «Вика», «vika» or «vika_01» against the character cards."""
    q = (name or '').strip().lower()
    if not q:
        return None
    for card in cards:
        cid = card.character_id.lower()
        if q in (cid, card.display_name.strip().lower(), cid.split('_', 1)[0]):
            return card.character_id
    for card in cards:
        if card.display_name.strip().lower().startswith(q):
            return card.character_id
    return None
