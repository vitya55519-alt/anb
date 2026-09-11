"""V3.31.3 — «Support the project» donation layer (CloudTips).

The owner asked to (1) show a donation link to every new user in the welcome,
(2) remind active users about once a week, and (3) craft a message that
motivates a donation. This module centralises the motivating copy, the CTA
button, and the DB helpers that decide who is due a weekly reminder, so main.py
(welcome) and services/scheduler_service.py (weekly job) share one source.

The link and cadence are configurable via Railway env vars (see config.py);
the reminder is optional and always respects the user's proactive_enabled
opt-out, so it never messages people who turned notifications off.
"""
from __future__ import annotations

import datetime as dt

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from config import (
    DONATION_LINK,
    DONATION_REMINDER_ACTIVE_DAYS,
    DONATION_REMINDER_INTERVAL_DAYS,
)
from models.app_models import User
from services.db import SessionLocal
from services.ui_lang import EN, RU


# Motivational copy WITHOUT the link — the link lives on the CTA button so the
# message stays clean. Kept warm and optional-feeling (never a hard sell).
_APPEAL_RU = (
    '💖 Поддержать проект\n\n'
    'Привет! Этот бот живёт и развивается благодаря таким людям, как ты 🥹\n\n'
    'Твой донат помогает:\n'
    '• добавлять новых персонажей и истории\n'
    '• делать фото и видео ещё лучше\n'
    '• чтобы всё работало быстро и без сбоев\n\n'
    'Это совсем не обязательно — но если тебе здесь нравится и хочется сказать '
    '«спасибо», любая сумма очень поддержит меня ❤️\n\n'
    'Спасибо, что ты рядом!'
)

_APPEAL_EN = (
    '💖 Support the project\n\n'
    'Hi! This bot lives and grows thanks to people like you 🥹\n\n'
    'Your donation helps:\n'
    '• add new characters and stories\n'
    '• make photos and videos even better\n'
    '• keep everything fast and running smoothly\n\n'
    "It's never required — but if you enjoy it here and want to say "
    '"thank you", any amount means a lot ❤️\n\n'
    'Thank you for being here!'
)


def donation_appeal(lang: str = RU) -> str:
    """Motivating support-the-project message (link is on the button)."""
    return _APPEAL_EN if lang == EN else _APPEAL_RU


def donation_keyboard(lang: str = RU) -> InlineKeyboardMarkup:
    """Single CTA button that opens the CloudTips donation link."""
    label = '💖 Support the project' if lang == EN else '💖 Поддержать проект'
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, url=DONATION_LINK)],
    ])


def due_donation_pings(now: dt.datetime) -> list[tuple[int, int, str]]:
    """Active, opted-in users whose last donation ping is older than the
    weekly interval (or was never sent).

    Returns ``(user_id, telegram_id, lang)`` tuples. Only users who confirmed
    18+ (``adult_confirmed``), kept proactive notifications on
    (``proactive_enabled``) and were active within ``DONATION_REMINDER_ACTIVE_DAYS``
    are eligible, so the reminder reaches people who actually use the bot.
    """
    active_cutoff = now - dt.timedelta(days=DONATION_REMINDER_ACTIVE_DAYS)
    ping_cutoff = now - dt.timedelta(days=DONATION_REMINDER_INTERVAL_DAYS)
    due: list[tuple[int, int, str]] = []
    with SessionLocal() as session:
        users = session.scalars(select(User).where(
            User.proactive_enabled == True,  # noqa: E712
            User.adult_confirmed == True,  # noqa: E712
            User.last_active_at >= active_cutoff,
        )).all()
        for u in users:
            last = u.last_donation_ping_at
            if last is None or last <= ping_cutoff:
                lang = EN if (u.ui_lang or '').strip().lower() == EN else RU
                try:
                    telegram_id = int(u.telegram_id)
                except (TypeError, ValueError):
                    continue
                due.append((u.id, telegram_id, lang))
    return due


def mark_donation_ping_sent(user_id: int, now: dt.datetime) -> None:
    """Record that the weekly donation reminder was just sent to this user."""
    with SessionLocal() as session:
        user = session.get(User, user_id)
        if user is not None:
            user.last_donation_ping_at = now
            session.commit()
