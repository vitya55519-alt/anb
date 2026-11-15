"""V3.166.2: one daily ceiling for the whole account — the owner's economy rule.

Before this release the counter only burned on an explicit turn while the
«После полуночи» flag was on, and free text was unlimited
(``can_send_message`` returned True for everybody). The owner ruled it out on
15 ноя: «30 любых сообщений в сутки на весь аккаунт, независимо от режима и
интерфейса. Безлимит дается только платным подписчикам».

So this module counts EVERY accepted conversational turn — his text and his
voice note, in the Mini App and in the bot, whichever mode he entered with —
and the ceiling is hard: at 30 the account is blocked until midnight Moscow,
and the only way out is Premium.

* ``used_today``/``left`` — what the surfaces quote (never a second number in
  the SPA: the entry cards, the chat note and the wall all read ``left``).
* ``note_message`` — burns one message and stashes the thin line the delivery
  layer puts under her reply (the bot and the app each read it once).
* ``has_left`` — what ``access_service.can_send_message`` answers with.

``CHAT_MSGS_PER_DAY = 0`` switches the wall off for everybody, which is the
emergency lever the owner keeps in the environment; the texts then fall back to
the old «no ceiling» wording instead of printing «0 сообщений».
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from config import CHAT_MSGS_PER_DAY
from models.app_models import User
from services.db import SessionLocal

MSK = timezone(timedelta(hours=3))
# The number every surface quotes next to the wall. Same value the counter
# enforces — never a hard-coded 30 in the bot copy or the SPA.
DAILY_CAP = CHAT_MSGS_PER_DAY

# Owner asked for a soft lead-in, not a metronome: the count only starts
# showing when the day is almost spent. The line at 0 is different — it is the
# last thing he reads before the wall, so it is said once per Moscow day.
HINT_AT_LEFT = 5

# telegram_id -> {'left', 'reached', 'text', 'at'}: only the reply that was
# just generated carries the hint, and only one surface may draw it.
_pending: dict[int, dict] = {}
_PENDING_TTL_SECONDS = 900.0
_closed_shown: dict[int, date] = {}


def msk_today() -> date:
    return datetime.now(MSK).date()


def used_today(user_row) -> int:
    if user_row is None or getattr(user_row, 'chat_day', None) != msk_today():
        return 0
    return int(getattr(user_row, 'chat_used', 0) or 0)


def left(user_row, *, premium: bool) -> int | None:
    """How many messages are still allowed today. ``None`` = no ceiling, which
    is only ever true for Premium (or the owner switched the wall off)."""
    if premium or not CHAT_MSGS_PER_DAY:
        return None
    return max(0, CHAT_MSGS_PER_DAY - used_today(user_row))


def has_left(telegram_id: int) -> bool:
    """The counter's answer for a non-Premium account: is he still under the
    ceiling? True when the wall is switched off."""
    if not CHAT_MSGS_PER_DAY:
        return True
    try:
        with SessionLocal() as s:
            return left(s.scalar(select(User).where(User.telegram_id == str(telegram_id))),
                        premium=False) != 0
    except Exception:
        return True


def reached_line(lang: str = 'ru') -> str:
    """The line shown after his last free message of the day."""
    if not CHAT_MSGS_PER_DAY:
        return ''
    if (lang or 'ru').startswith('en'):
        return (f'today’s {CHAT_MSGS_PER_DAY} messages are used up — I’ll be waiting for you '
                'after midnight. Premium has no ceiling at all 💜')
    return (f'на сегодня {CHAT_MSGS_PER_DAY} сообщений использовано — я буду ждать тебя после '
            'полуночи. С Premium потолка нет вовсе 💜')


def hint_line(lang: str = 'ru', left_count: int | None = None) -> str:
    if left_count is None:
        return ''
    if left_count <= 0:
        return reached_line(lang)
    if (lang or 'ru').startswith('en'):
        return f'{left_count} messages left today'
    return f'осталось {left_count} сообщений на сегодня'


def note_message(telegram_id: int, *, language: str = 'ru') -> dict | None:
    """Burn one message of today's ceiling and stash the line for the surface
    that delivers this reply. ``None`` when there is nothing to say (the wall
    is off, the day is still young, or the «на сегодня всё» line was already
    shown today)."""
    if not CHAT_MSGS_PER_DAY:
        return None
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if user is None:
            return None
        today = msk_today()
        if getattr(user, 'chat_day', None) != today:
            user.chat_day = today
            user.chat_used = 0
        user.chat_used = int(user.chat_used or 0) + 1
        remaining = max(0, CHAT_MSGS_PER_DAY - int(user.chat_used))
        s.commit()
    if remaining > HINT_AT_LEFT:
        return None
    if remaining == 0 and _closed_shown.get(int(telegram_id)) == msk_today():
        return None
    hint = {'left': remaining, 'reached': remaining == 0, 'text': hint_line(language, remaining)}
    if remaining == 0:
        _closed_shown[int(telegram_id)] = msk_today()
    _pending[int(telegram_id)] = {**hint, 'at': time.monotonic()}
    return hint


def take_hint(telegram_id: int) -> dict | None:
    entry = _pending.pop(int(telegram_id), None)
    if not entry:
        return None
    if time.monotonic() - float(entry.get('at') or 0) > _PENDING_TTL_SECONDS:
        return None
    return {k: entry.get(k) for k in ('left', 'reached', 'text')}
