"""V3.129.0: «что у нас нового» — one honest message to the men who left.

The retention ladder (services/scheduler_service._proactive) stops after
PROACTIVE_MAX_INACTIVE_DAYS (10 days by default): after that a silent user
never hears from her again. Most of the ~500 men who left did so before the
voice call, «🏠 Дом», «🎬 Сюжеты» and the new girls existed, so they simply
don't know about them.

Now, once per ROUND, she writes to each man silent for MIN_DAYS..MAX_DAYS days:
what is new, one button back to her chat, and that she writes this only once.
No «я обиделась», no countdown, no fake scarcity. A new round (WHATS_NEW_ROUND)
can be started after the next big update; the same round never repeats.

Daytime Moscow only, BATCH men per scan so Telegram limits and the server are
never hit at once. Users who blocked the bot / switched pushes off are skipped.
Event: whats_new_sent (metadata round). Flag: WHATS_NEW_ENABLED.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from models.app_models import Message, ProductEvent, User
from services.db import SessionLocal

ENABLED = os.getenv('WHATS_NEW_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')
ROUND = (os.getenv('WHATS_NEW_ROUND', '2026-11') or '2026-11').strip()[:32]
MIN_DAYS = max(3, int(os.getenv('WHATS_NEW_MIN_DAYS', '11')))
MAX_DAYS = max(MIN_DAYS + 1, int(os.getenv('WHATS_NEW_MAX_DAYS', '120')))
BATCH = max(1, min(200, int(os.getenv('WHATS_NEW_BATCH', '25'))))
EVENT = 'whats_new_sent'


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _sent_this_round(s, ids: list[int]) -> set[int]:
    rows = s.execute(select(ProductEvent.user_id, ProductEvent.metadata_json).where(
        ProductEvent.user_id.in_(ids), ProductEvent.event_name == EVENT)).all()
    done = set()
    for uid, meta in rows:
        try:
            if (json.loads(meta or '{}') or {}).get('round') == ROUND:
                done.add(uid)
        except (TypeError, ValueError):
            continue
    return done


def candidates(now: datetime | None = None, limit: int | None = None) -> list[tuple[int, int, str]]:
    """[(user id, telegram id, selected character)] — silent MIN_DAYS..MAX_DAYS
    days, pushes on, wrote her at least once, not messaged in this round.
    Most recently active first: they remember her best."""
    now = now or _now()
    limit = BATCH if limit is None else limit
    with SessionLocal() as s:
        rows = s.execute(select(User.id, User.telegram_id, User.selected_character).where(
            User.last_active_at <= now - timedelta(days=MIN_DAYS),
            User.last_active_at >= now - timedelta(days=MAX_DAYS),
            User.proactive_enabled == True,  # noqa: E712 — SQL expression
        ).order_by(User.last_active_at.desc())).all()
        if not rows:
            return []
        ids = [r[0] for r in rows]
        talked = set(s.scalars(select(Message.user_id).where(
            Message.user_id.in_(ids), Message.role == 'user').group_by(Message.user_id)
            .having(func.count(Message.id) >= 1)).all())
        done = _sent_this_round(s, ids)
    out = []
    for uid, tg, char in rows:
        if uid not in talked or uid in done:
            continue
        try:
            out.append((uid, int(tg), (char or '').strip()))
        except (TypeError, ValueError):
            continue
        if len(out) >= limit:
            break
    return out


def mark(uid: int, character_id: str) -> None:
    """The slot first: a failed send must not re-fire every scan."""
    with SessionLocal() as s:
        s.add(ProductEvent(user_id=uid, character_id=character_id or 'anna_01', event_name=EVENT,
                           metadata_json=json.dumps({'round': ROUND}), created_at=_now()))
        s.commit()


def text(name: str, lang: str = 'ru') -> str:
    name = (name or '').strip()
    if lang == 'en':
        hi = f"hi, it's {name} 🙂" if name else 'hi 🙂'
        return (f"{hi} you haven't been around for a while, and I'm not upset, I just wanted to tell you what's new here:\n\n"
                "📞 you can call me now and talk by voice, right in the app\n"
                "🏠 I have my own home, and you can furnish it with me\n"
                "🎬 stories for the two of us in Premium, where you play the lead\n"
                "👭 and new girls, if you'd like to meet them\n\n"
                "I'm writing this just once, no reminders. if you feel like it, I'm here 💗")
    hi = f'привет, это {name} 🙂' if name else 'привет 🙂'
    return (f'{hi} тебя давно не было, я не обижаюсь, просто хотела рассказать, что у нас появилось:\n\n'
            '📞 мне теперь можно позвонить и поговорить голосом, прямо в приложении\n'
            '🏠 у меня есть свой дом, и его можно обставить вместе\n'
            '🎬 сюжеты на двоих в Premium, где ты в главной роли\n'
            '👭 и новые девушки, если захочешь познакомиться\n\n'
            'пишу один раз, без напоминаний. если захочешь, я тут 💗')


def button_text(lang: str = 'ru') -> str:
    return '💬 write to her' if lang == 'en' else '💬 написать ей'
