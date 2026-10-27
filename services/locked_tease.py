"""V3.88.0: the early locked photo in the Mini App chat.

Owner: «плохие боты продают, наш нет». Competitors drop a blurred private
photo with an «open» button in the first minutes of a chat; ours showed the
first paid offer only after a 20-minute pause, when the user had already left.

Now, on a non-Premium user's TEASE_AT-th message to a girl, her reply comes
with a heavily blurred locked card («🔒 только для тебя»). The tap opens the
Premium pay sheet (the 3-day trial first). Once per girl per stored session
(DialogStore rows are swept after a day, so it may come back the next day).
"""
from __future__ import annotations

from services import dialog_store

TEASE_AT = 3

_store = dialog_store.DialogStore('locked_tease')


def bump(telegram_id: int, character_id: str) -> bool:
    """Count one user message to `character_id`; True exactly once, when this
    message is the TEASE_AT-th one and the tease was not shown yet."""
    key = str(character_id or '')
    try:
        data = dict(_store.get(telegram_id) or {})
    except Exception:
        return False
    entry = dict(data.get(key) or {})
    if entry.get('shown'):
        return False
    count = int(entry.get('n') or 0) + 1
    entry['n'] = count
    fire = count >= TEASE_AT
    if fire:
        entry['shown'] = 1
    data[key] = entry
    try:
        _store[telegram_id] = data
    except Exception:
        return False
    return fire
