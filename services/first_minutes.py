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

from sqlalchemy import func, select

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


# ── V3.168.0: 90 seconds after the 18+ tap ────────────────────────────────
# D1 is 7%: a third of the newcomers confirm 18+ and then say nothing. The 10-minute
# nudge above comes too late for them. If he confirmed and has been silent for
# ADULT_NUDGE_SECONDS, she writes ONE short teasing line with two one-tap replies.
# It rides no unanswered / day-norm limit (the man just stood in front of her).
ADULT_NUDGE_SECONDS = max(30, int(os.getenv('ADULT_NUDGE_SECONDS', '90')))
ADULT_NUDGE_WINDOW_MINUTES = max(3, int(os.getenv('ADULT_NUDGE_WINDOW_MINUTES', '20')))
ADULT_NUDGE_ENABLED = os.getenv('ADULT_NUDGE_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')
ADULT_NUDGE_EVENT = 'adult_nudge_sent'
ADULT_NUDGE_TEXT = ('Ты уже тут, а молчишь 😏 Я как раз собиралась переодеться — '
                    'подсмотришь или отвернёшься?')
ADULT_NUDGE_OPTIONS = (('Подсмотрю 😈', 'peek'), ('Отвернусь', 'look_away'))


def adult_nudge_candidates(now: datetime | None = None) -> list[tuple[int, int, str]]:
    """[(user id, telegram id, selected character)] who confirmed 18+ between
    ADULT_NUDGE_WINDOW_MINUTES and ADULT_NUDGE_SECONDS ago and wrote nothing."""
    now = now or _now()
    with SessionLocal() as s:
        rows = s.execute(select(ProductEvent.user_id, func.max(ProductEvent.created_at)).where(
            ProductEvent.event_name == 'consent_accepted',
            ProductEvent.created_at <= now - timedelta(seconds=ADULT_NUDGE_SECONDS),
            ProductEvent.created_at >= now - timedelta(minutes=ADULT_NUDGE_WINDOW_MINUTES),
        ).group_by(ProductEvent.user_id)).all()
        if not rows:
            return []
        ids = [r[0] for r in rows if r[0]]
        busy = set(s.scalars(select(ProductEvent.user_id).where(
            ProductEvent.user_id.in_(ids),
            ProductEvent.event_name.in_(WROTE + (ADULT_NUDGE_EVENT,)))).all())
        users = s.execute(select(User.id, User.telegram_id, User.selected_character).where(
            User.id.in_([i for i in ids if i not in busy]),
            User.proactive_enabled == True)).all()  # noqa: E712
    out = []
    for uid, tg, char in users:
        try:
            out.append((uid, int(tg), (char or '').strip()))
        except (TypeError, ValueError):
            continue
    return out
