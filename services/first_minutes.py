"""V3.97.0: the first ten minutes — the people who came and went quiet.

1 Nov 2026: of 175 new users 68 never wrote a word, and 37 of the 159 who
pressed /start in the last week never confirmed 18+. Nobody followed up with
them on day 0 (the day-1 hook waits 18 hours, by then they are gone).

One nudge per user, ever, NUDGE_AFTER_MINUTES after /start:
- ``consent`` — the 18+ step is still open: a neutral «one step left» line
  with the consent button (nothing adult before he confirms);
- ``silent``  — confirmed but has not written to her: she writes once more,
  shy and warm, with a one-tap way into the chat.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from models.app_models import ProductEvent, User
from services.db import SessionLocal

NUDGE_AFTER_MINUTES = max(3, int(os.getenv('FIRST_MINUTES_NUDGE_AFTER', '10')))
NUDGE_WINDOW_HOURS = max(1, int(os.getenv('FIRST_MINUTES_NUDGE_WINDOW_HOURS', '3')))
ENABLED = os.getenv('FIRST_MINUTES_NUDGE_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')
EVENT = 'first_minutes_nudge'
WROTE = ('chat_user_message', 'webapp_chat_message', 'webapp_chat_media', 'first_reply_tapped')


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def candidates(now: datetime | None = None) -> list[tuple[int, int, str]]:
    """[(user id, telegram id, selected character)] — fresh, quiet, not nudged."""
    now = now or _now()
    with SessionLocal() as s:
        users = s.execute(select(User.id, User.telegram_id, User.selected_character).where(
            User.created_at <= now - timedelta(minutes=NUDGE_AFTER_MINUTES),
            User.created_at >= now - timedelta(hours=NUDGE_WINDOW_HOURS),
            User.proactive_enabled == True,  # noqa: E712
        )).all()
        if not users:
            return []
        ids = [u[0] for u in users]
        busy = set(s.scalars(select(ProductEvent.user_id).where(
            ProductEvent.user_id.in_(ids),
            ProductEvent.event_name.in_(WROTE + (EVENT,)))).all())
    out = []
    for uid, tg, char in users:
        if uid in busy:
            continue
        try:
            out.append((uid, int(tg), (char or '').strip()))
        except (TypeError, ValueError):
            continue
    return out


def mark(uid: int, stage: str, character_id: str) -> None:
    import json
    with SessionLocal() as s:
        s.add(ProductEvent(user_id=uid, character_id=character_id or 'anna_01', event_name=EVENT,
                           metadata_json=json.dumps({'stage': stage}), created_at=_now()))
        s.commit()


def text(stage: str, lang: str = 'ru') -> str:
    if lang == 'en':
        if stage == 'consent':
            return "one step left 🙂 confirm you are 18+ and she will write to you right away"
        return "hey… you went quiet 🙈 I'm a bit shy to write first again. just say hi, ok? 😌"
    if stage == 'consent':
        return "остался один шаг 🙂 подтверди, что тебе есть 18, и она сразу тебе напишет"
    return "эй… ты пропал 🙈 мне немного неловко писать первой второй раз. скажи хотя бы «привет», ладно? 😌"
