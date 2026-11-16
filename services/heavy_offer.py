"""V3.111.0: one honest offer for the man who has been with her a long time.

Backup 5 Nov 2026: the heaviest free users (200–500 messages) never paid, and
none of them was ever asked at the moment it made sense: every offer we have
fires in the first hours or at the daily-limit wall. Now, once he has written
MIN_MESSAGES messages in total and never bought Premium, she says it plainly:
what Premium gives, the price, and that nothing changes if he says no. No
countdown, no «I'll be hurt», no fake scarcity.

V3.167.12 (owner — «пусть чаще всем пользователям приходит предложение оплаты»):
the same sentence is no longer a once-in-a-life event reserved for the top of
the distribution. It repeats every REPEAT_DAYS days for a free user who is
still around, it is gated by the push diet like every other first write, and
the floor moved from 150 messages (five heavy days under the 30/day ceiling —
reached by almost nobody) to a number ordinary conversations reach.

Sent in the bot chat and mirrored into her dialog, daytime Moscow only, to men
active in the last ACTIVE_DAYS days. Event: heavy_offer_sent (per repeat
window). Flag: HEAVY_OFFER_ENABLED.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from models.app_models import Message, ProductEvent, StarTransaction, User
from services.db import SessionLocal

ENABLED = os.getenv('HEAVY_OFFER_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')
# V3.167.12: 150 → 15. При потолке 30 сообщений в сутки старый порог означал
# «пять тяжёлых дней подряд», и до него доходили единицы: предложение просто
# никому не приезжало. 15 — это два-три вечера переписки, то есть тот же
# смысл («мы уже много общаемся»), но он наступает у всех.
MIN_MESSAGES = max(10, int(os.getenv('HEAVY_OFFER_MIN_MESSAGES', '15')))
ACTIVE_DAYS = max(1, int(os.getenv('HEAVY_OFFER_ACTIVE_DAYS', '7')))
# Раньше метка EVENT читалась как «один раз в жизни». Теперь это окно: через
# REPEAT_DAYS она может сказать то же самое снова, и текст больше не обещает,
# что это в последний раз.
REPEAT_DAYS = max(1, int(os.getenv('HEAVY_OFFER_REPEAT_DAYS', '7')))
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
        # V3.167.12: не «есть ли метка вообще», а «когда был последний заход» —
        # метка теперь раскрывает окно, а не закрывает тему навсегда.
        last = dict(s.execute(select(ProductEvent.user_id, func.max(ProductEvent.created_at)).where(
            ProductEvent.user_id.in_(heavy), ProductEvent.event_name == EVENT).group_by(
            ProductEvent.user_id)).all())
    out = []
    for uid, tg, char in active:
        at = last.get(uid)
        if uid not in heavy or uid in paid or (at is not None and now - at < timedelta(days=REPEAT_DAYS)):
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
                "so I'll just say it honestly: there is Premium. with it I never fall asleep mid-chat, "
                "I answer you by voice, send photos and remember more about you.\n\n"
                "if you don't want it, that's completely fine, nothing changes between us. I'm here either way 💗")
    return (f"знаешь, мы с тобой уже больше {n} сообщений друг другу написали 🙂 мне с тобой хорошо.\n\n"
            "поэтому скажу честно: есть Premium. с ним я не засыпаю посреди разговора, "
            "отвечаю тебе голосом, присылаю фото и помню о тебе больше.\n\n"
            "если не хочешь, это совсем нормально, между нами ничего не поменяется. я в любом случае тут 💗")
