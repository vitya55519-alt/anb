"""V3.68.0: the channel-subscribe bonus is paid after a hold.

Owner (2026-10-21): people subscribed, took the peaches, unsubscribed and never
came back. Now «Проверить подписку» only starts a CHANNEL_BONUS_HOLD_DAYS hold
(a 0-star StarTransaction marker, so no schema change); the bonus lands when
the user is still subscribed after the hold — on their next check or from the
hourly scheduler job, which also pings them in the bot."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from config import CHANNEL_BONUS_HOLD_DAYS
from models.app_models import StarTransaction, User
from services.db import SessionLocal

logger = logging.getLogger(__name__)

_PREFIX = 'channel_pending:'


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _marker(telegram_id: int) -> str:
    return f'{_PREFIX}{int(telegram_id)}'


def hold_started(telegram_id: int) -> datetime | None:
    with SessionLocal() as s:
        tx = s.scalar(select(StarTransaction).where(StarTransaction.telegram_charge_id == _marker(telegram_id)))
        return tx.created_at if tx else None


def start_hold(telegram_id: int) -> datetime | None:
    """Start the hold once; returns its start (the existing one if any)."""
    started = hold_started(telegram_id)
    if started:
        return started
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            return None
        now = _now()
        s.add(StarTransaction(user_id=user.id, transaction_type='pending', product='channel_subscribe',
                              stars=0, telegram_charge_id=_marker(telegram_id), created_at=now))
        try:
            s.commit()
        except Exception:
            s.rollback()
            return hold_started(telegram_id)
        return now


def clear_hold(telegram_id: int) -> None:
    with SessionLocal() as s:
        tx = s.scalar(select(StarTransaction).where(StarTransaction.telegram_charge_id == _marker(telegram_id)))
        if tx:
            s.delete(tx)
            s.commit()


def hold_due_at(started: datetime) -> datetime:
    return started + timedelta(days=CHANNEL_BONUS_HOLD_DAYS)


def days_left(started: datetime) -> int:
    """Whole days until the bonus (1..HOLD), 0 when due."""
    secs = (hold_due_at(started) - _now()).total_seconds()
    if secs <= 0:
        return 0
    return int(-(-secs // 86400))


def due_hold_ids(limit: int = 200) -> list[int]:
    """Telegram ids whose hold has run out and who were not paid yet."""
    cutoff = _now() - timedelta(days=CHANNEL_BONUS_HOLD_DAYS)
    with SessionLocal() as s:
        rows = s.scalars(select(StarTransaction.telegram_charge_id).where(
            StarTransaction.telegram_charge_id.like(_PREFIX + '%'),
            StarTransaction.created_at <= cutoff,
        ).limit(limit)).all()
    out = []
    for r in rows:
        try:
            out.append(int(r[len(_PREFIX):]))
        except (TypeError, ValueError):
            continue
    return out
