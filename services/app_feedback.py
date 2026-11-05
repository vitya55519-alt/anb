"""V3.107.0 — «Ждём ваших предложений» in the Mini App's honest card.

Owner: «будем рады вашим пожеланиям, что нужно улучшить в боте… главное,
чтобы оно в бот поддержки приходило автоматически, чтобы я читал».

A wish typed in the card goes to every admin through the support bot as a
card (who wrote, Premium, peaches, money trail — the same card as an appeal),
so the owner reads it where he reads support and can answer by reply.
Kept as a product event 'app_feedback' for the weekly numbers.
"""
from __future__ import annotations

import time

MIN_LEN = 3
MAX_LEN = 1000
PER_HOUR = 3
TITLE = '💡 Предложение из приложения'

_sent: dict[int, list[float]] = {}


def clean(text: str | None) -> str:
    return ' '.join(str(text or '').split())[:MAX_LEN]


def allowed(telegram_id: int, now: float | None = None) -> bool:
    """At most PER_HOUR wishes an hour per user (no spam into the owner's chat)."""
    now = time.time() if now is None else now
    recent = [t for t in _sent.get(int(telegram_id), []) if now - t < 3600]
    _sent[int(telegram_id)] = recent
    return len(recent) < PER_HOUR


def remember(telegram_id: int, now: float | None = None) -> None:
    _sent.setdefault(int(telegram_id), []).append(time.time() if now is None else now)


def admin_card(telegram_id: int, name: str, username: str | None, text: str) -> str:
    from services import support_desk
    card = support_desk.user_card(telegram_id, name, username, text)
    return card.replace('🆘 Обращение от', TITLE + '\nот', 1)
