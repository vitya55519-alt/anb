"""V3.106.0: he hears her voice before he is asked to pay for it.

Backup 5 Nov 2026: the «🔊» Premium wall was hit by 61 people in two weeks —
more than any other wall — and 2 of the 3 people who ever paid hit it right
before paying, in their very first session. Her voice sells; but without
Premium her replies never came as voice at all (only Premium + a toggle).

Now a non-Premium man gets her first FREE_REPLIES replies as voice notes on
their own (from his MIN_MESSAGE-th message, a short or medium line only), and
when they are used up, the next time she would have spoken, a quiet
«🎙 слышать её голос всегда» chip goes under her reply (once a day), leading
to the trial-first pay sheet. Events: voice_taste_sent, voice_taste_offer.
Flag: VOICE_TASTE_ENABLED.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from models.app_models import ProductEvent, User
from services.db import SessionLocal

ENABLED = os.getenv('VOICE_TASTE_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')
FREE_REPLIES = max(0, int(os.getenv('VOICE_TASTE_FREE', '2')))
MIN_MESSAGE = max(1, int(os.getenv('VOICE_TASTE_FROM_MESSAGE', '2')))
OFFER_COOLDOWN_HOURS = max(1, int(os.getenv('VOICE_TASTE_OFFER_HOURS', '24')))
SENT = 'voice_taste_sent'
OFFER = 'voice_taste_offer'
MIN_CHARS, MAX_CHARS = 12, 320


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _uid(s, telegram_id: int):
    return s.scalar(select(User.id).where(User.telegram_id == str(telegram_id)))


def _count(s, uid: int, name: str, since: datetime | None = None) -> int:
    q = select(func.count(ProductEvent.id)).where(ProductEvent.user_id == uid, ProductEvent.event_name == name)
    if since is not None:
        q = q.where(ProductEvent.created_at >= since)
    return int(s.scalar(q) or 0)


def decide(telegram_id: int, answer: str, his_messages: int) -> str:
    """'voice' — send this reply as a free voice note; 'offer' — show the
    «слышать всегда» chip; '' — nothing. Caller checks Premium first."""
    if not ENABLED:
        return ''
    n = len((answer or '').strip())
    if n < MIN_CHARS or n > MAX_CHARS or his_messages < MIN_MESSAGE:
        return ''
    try:
        with SessionLocal() as s:
            uid = _uid(s, telegram_id)
            if not uid:
                return ''
            if _count(s, uid, SENT) < FREE_REPLIES:
                return 'voice'
            if _count(s, uid, OFFER, _now() - timedelta(hours=OFFER_COOLDOWN_HOURS)):
                return ''
            s.add(ProductEvent(user_id=uid, event_name=OFFER, created_at=_now()))
            s.commit()
            return 'offer'
    except Exception:
        return ''


def mark_sent(telegram_id: int, character_id: str) -> None:
    with SessionLocal() as s:
        uid = _uid(s, telegram_id)
        if uid:
            s.add(ProductEvent(user_id=uid, character_id=character_id or 'anna_01', event_name=SENT,
                               created_at=_now()))
            s.commit()
