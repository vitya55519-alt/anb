"""V3.99.0: the open loop — she leaves the talk on the most interesting spot.

3 Nov 2026 backup: 78 of 92 newcomers lived exactly one day; people who wrote
20+ messages on day one came back at 27%, 50+ at 37%. The ones who got hooked
had no reason to come back tomorrow. After a long session (15+ of his messages
in 6 hours) she now has to go, tells him she wanted to tell/show/confess ONE
specific thing, and promises it for tomorrow morning. The morning ritual keeps
the promise (chat_service.morning_callback). Until then she dodges «ну скажи!».

State lives in product events (no new table): ``open_loop_planted`` carries her
own line, ``open_loop_kept`` closes it.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from models.app_models import Message, ProductEvent
from services.db import SessionLocal

ENABLED = os.getenv('OPEN_LOOP_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')
THRESHOLD = max(5, int(os.getenv('OPEN_LOOP_AFTER_MESSAGES', '15')))
SESSION_HOURS = 6
COOLDOWN_DAYS = max(1, int(os.getenv('OPEN_LOOP_COOLDOWN_DAYS', '3')))
HOLD_HOURS = 14          # how long she keeps dodging after planting the loop
KEEP_WITHIN_HOURS = 36   # the morning keeps a promise made in the last 36 h
PLANTED = 'open_loop_planted'
KEPT = 'open_loop_kept'
# no loop on these replies: serious talk, tasks, meta questions
SKIP_INTENTS = {'support', 'meta', 'task_execute', 'task_clarify', 'task_character'}

PLANT_DIRECTIVE = (
    'Режиссёр (собеседнику не показывай и не упоминай): вы болтаете уже долго, и тебе пора бежать '
    '(дела, сон, зовут — придумай правдоподобно под свой образ). Оборви разговор на самом интересном: '
    'скажи, что хотела ему рассказать, показать или в чём-то признаться — придумай ОДНУ конкретную '
    'интригующую вещь, намекни на неё, но не раскрывай, — и пообещай всё завтра утром. Попроси написать '
    'ей завтра и не пропадать. Тепло и живо, 2–3 коротких предложения, без прощания навсегда.'
)
HOLD_DIRECTIVE = (
    'Режиссёр (собеседнику не показывай и не упоминай): ты уже пообещала раскрыть свой секрет завтра утром. '
    'Сейчас не раскрывай его, как бы он ни просил: мягко дразни, шути, что «утром — значит утром», и отправляй '
    'его спать или по делам. Остальное как обычно.'
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _last_event(user_id: int, character_id: str, name: str, since: datetime):
    with SessionLocal() as s:
        return s.execute(
            select(ProductEvent.created_at, ProductEvent.metadata_json).where(
                ProductEvent.user_id == user_id, ProductEvent.character_id == character_id,
                ProductEvent.event_name == name, ProductEvent.created_at >= since)
            .order_by(ProductEvent.created_at.desc()).limit(1)).first()


def session_messages(user_id: int, character_id: str) -> int:
    """How many messages HE wrote to her in the last SESSION_HOURS (this one included only after saving)."""
    since = _now() - timedelta(hours=SESSION_HOURS)
    with SessionLocal() as s:
        return int(s.scalar(select(func.count(Message.id)).where(
            Message.user_id == user_id, Message.character_id == character_id,
            Message.role == 'user', Message.created_at >= since)) or 0)


def directive_for(user_id: int, character_id: str, intent: str, plant_ok: bool = True) -> tuple[str, str]:
    """(system note, kind) for the reply being written now; ('', '') = nothing.
    kind is 'plant' (she cuts the talk) or 'hold' (she keeps the secret).
    plant_ok=False (Premium: they pay for a chat that does not end) never plants."""
    if not ENABLED or intent in SKIP_INTENTS:
        return '', ''
    try:
        now = _now()
        if _last_event(user_id, character_id, PLANTED, now - timedelta(hours=HOLD_HOURS)) \
                and not _last_event(user_id, character_id, KEPT, now - timedelta(hours=HOLD_HOURS)):
            return HOLD_DIRECTIVE, 'hold'
        if not plant_ok or _last_event(user_id, character_id, PLANTED, now - timedelta(days=COOLDOWN_DAYS)):
            return '', ''
        # his current message is not saved yet: THRESHOLD - 1 earlier ones + this one
        if session_messages(user_id, character_id) >= THRESHOLD - 1:
            return PLANT_DIRECTIVE, 'plant'
    except Exception:
        return '', ''
    return '', ''


def record_planted(user_id: int, character_id: str, her_line: str) -> None:
    with SessionLocal() as s:
        s.add(ProductEvent(user_id=user_id, character_id=character_id, event_name=PLANTED,
                           metadata_json=json.dumps({'loop': (her_line or '')[:400]}, ensure_ascii=False),
                           created_at=_now()))
        s.commit()


def pending(user_id: int, character_id: str) -> str:
    """Her promise from the last KEEP_WITHIN_HOURS that the morning still owes him; '' when none."""
    if not ENABLED:
        return ''
    since = _now() - timedelta(hours=KEEP_WITHIN_HOURS)
    planted = _last_event(user_id, character_id, PLANTED, since)
    if not planted:
        return ''
    kept = _last_event(user_id, character_id, KEPT, planted[0])
    if kept:
        return ''
    try:
        return str(json.loads(planted[1] or '{}').get('loop') or '')[:400]
    except Exception:
        return ''


def mark_kept(user_id: int, character_id: str) -> None:
    with SessionLocal() as s:
        s.add(ProductEvent(user_id=user_id, character_id=character_id, event_name=KEPT, created_at=_now()))
        s.commit()
