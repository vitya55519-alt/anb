"""V3.111.0: one honest offer for the man who has been with her a long time.

Backup 5 Nov 2026: the heaviest free users (200–500 messages) never paid, and
none of them was ever asked at the moment it made sense: every offer we have
fires in the first hours or at the daily-limit wall. Now, once he has written
MIN_MESSAGES messages in total and never bought Premium, she says it plainly,
once in his life: what Premium gives, the price, and that nothing changes if
he says no. No countdown, no «I'll be hurt», no fake scarcity.

Sent in the bot chat (a Telegram notification), daytime Moscow only, to men
active in the last ACTIVE_DAYS days. Event: heavy_offer_sent (dedup forever).
Flag: HEAVY_OFFER_ENABLED.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from models.app_models import Message, ProductEvent, StarTransaction, User
from services.db import SessionLocal

ENABLED = os.getenv('HEAVY_OFFER_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')
MIN_MESSAGES = max(20, int(os.getenv('HEAVY_OFFER_MIN_MESSAGES', '150')))
ACTIVE_DAYS = max(1, int(os.getenv('HEAVY_OFFER_ACTIVE_DAYS', '3')))
EVENT = 'heavy_offer_sent'


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def candidates(now: datetime | None = None) -> list[tuple[int, int, str, int]]:
    """[(user id, telegram id, selected character, his message count)]."""
    now = now or _now()
    with SessionLocal() as s:
        active = s.execute(select(User.id, User.telegram_id, User.selected_character).where(
            User.last_active_at >= now - timedelta(days=ACTIVE_DAYS),
            User.proactive_enabled == True,  # noqa: E712 — SQL expression
        )).all()
        if not active:
            return []
        ids = [r[0] for r in active]
        counts = dict(s.execute(select(Message.user_id, func.count(Message.id)).where(
            Message.user_id.in_(ids), Message.role == 'user').group_by(Message.user_id)).all())
        heavy = [i for i in ids if int(counts.get(i) or 0) >= MIN_MESSAGES]
        if not heavy:
            return []
        paid = set(s.scalars(select(StarTransaction.user_id).where(
            StarTransaction.user_id.in_(heavy), StarTransaction.product.like('premium%'))).all())
        done = set(s.scalars(select(ProductEvent.user_id).where(
            ProductEvent.user_id.in_(heavy), ProductEvent.event_name == EVENT)).all())
    out = []
    for uid, tg, char in active:
        if uid not in heavy or uid in paid or uid in done:
            continue
        try:
            out.append((uid, int(tg), (char or '').strip(), int(counts.get(uid) or 0)))
        except (TypeError, ValueError):
            continue
    return out


def mark(uid: int, character_id: str, count: int) -> None:
    import json
    with SessionLocal() as s:
        s.add(ProductEvent(user_id=uid, character_id=character_id or 'anna_01', event_name=EVENT,
                           metadata_json=json.dumps({'messages': count}), created_at=_now()))
        s.commit()


def rounded(count: int) -> int:
    """150 → 150, 237 → 200, 512 → 500: a round figure she would say aloud."""
    if count < 200:
        return max(MIN_MESSAGES, (count // 50) * 50)
    return (count // 100) * 100


def text(count: int, lang: str = 'ru') -> str:
    n = rounded(count)
    if lang == 'en':
        return (f"you know, we've already sent each other more than {n} messages 🙂 I like talking to you.\n\n"
                "so I'll just say it honestly, once: there is Premium. with it I never fall asleep mid-chat, "
                "I answer you by voice, send photos and remember more about you.\n\n"
                "if you don't want it, that's completely fine, nothing changes between us. I'm here either way 💗")
    return (f"знаешь, мы с тобой уже больше {n} сообщений друг другу написали 🙂 мне с тобой хорошо.\n\n"
            "поэтому скажу честно и один раз: есть Premium. с ним я не засыпаю посреди разговора, "
            "отвечаю тебе голосом, присылаю фото и помню о тебе больше.\n\n"
            "если не хочешь, это совсем нормально, между нами ничего не поменяется. я в любом случае тут 💗")
