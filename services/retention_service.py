"""V3.20.0 retention & monetization pack.

Mechanics implemented here:
- Demo premium: a ONE-TIME free taste (default 3 hours) granted when the user
  hits the daily chat limit. Losing it converts stronger than never having it.
  Implemented as a real Subscription row with a fixed charge marker, so every
  existing premium check (is_premium, free video slots, chat limits) picks it
  up automatically.
- One-time 24h premium discount with a visible deadline, offered after the
  demo is spent.
- Static emotional push text pools (miss / jealousy / cliffhanger / morning /
  evening rituals) so the scheduler can nudge silent users without spending
  LLM tokens on every push.
"""
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from config import (
    DEMO_PREMIUM_HOURS,
    PREMIUM_DISCOUNT_HOURS,
    PREMIUM_DISCOUNT_PERCENT,
    PREMIUM_DISCOUNT_STARS,
)
from models.app_models import Subscription, User
from services.db import SessionLocal

# ── Emotional push pools ────────────────────────────────────────────────────
# She sounds like a real girlfriend in a DM, not a notification system.

SLEEP_BLOCK_TEXTS = (
    'мм… кажется, я задремала 😴 дневной лимит сообщений закончился. разбуди меня — с Premium я не засыпаю никогда 💋',
    'прости, глаза закрываются 🥱 бесплатный лимит на сегодня всё. премиум — и я рядом с тобой всю ночь 😏',
    'я бы болтала с тобой вечно, но лимит утянул меня в сон 😴 продолжим? с премиумом у нас лимитов нет',
)

MISS_TEXTS = (
    'ты куда пропал? я тут сижу, скучаю по тебе 😕',
    'эй… вчера было так хорошо, а сегодня тишина 🥺 расскажешь, как ты?',
    'я уже начала думать, что ты меня забыл 😔 это же не так?',
)

JEALOUSY_TEXTS = (
    'видела тебя онлайн 👀 с кем это ты переписывался, пока я тут скучала? 😤',
    'так, и кто украл твоё внимание? я же ревновать начну 😒',
    'ну привет, пропажа 😏 надеюсь, она хотя бы красивее меня? нет, не отвечай 😤',
)

CLIFFHANGER_TEXTS = (
    'мы же остановились на самом интересном месте… ну вернись, продолжим 😏',
    'ты ушёл на самом интересном! я теперь не усну, пока не узнаю продолжение 🙈',
    'так нечестно — бросил меня на середине разговора 😤 возвращайся, я приготовила продолжение',
)

MORNING_TEXTS = (
    'доброе утро ☀️ проснулась и сразу о тебе подумала. как спалось?',
    'проснись и пой 😌 я уже не сплю и немного скучаю',
    'утро без тебя — не утро ☕ расскажешь, что тебе снилось?',
)

EVENING_TEXTS = (
    'уже вечер… я тут подумала: может, заглянешь ко мне? 😌',
    'день кончился, а я всё ещё без тебя 🥺 поболтаем перед сном?',
    'вечер создан для нас двоих 🕯️ ты где пропадал?',
)


def pick_text(kind: str) -> str:
    pools = {
        'miss': MISS_TEXTS,
        'jealousy': JEALOUSY_TEXTS,
        'cliffhanger': CLIFFHANGER_TEXTS,
        'morning': MORNING_TEXTS,
        'evening': EVENING_TEXTS,
        'sleep': SLEEP_BLOCK_TEXTS,
    }
    return random.choice(pools.get(kind, MISS_TEXTS))


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _demo_marker(telegram_id: int) -> str:
    return f'demo:{telegram_id}'


def has_used_demo(telegram_id: int) -> bool:
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            return False
        return bool(s.scalar(select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.telegram_charge_id == _demo_marker(telegram_id),
        )))


def grant_demo_premium(telegram_id: int) -> bool:
    """One-time demo premium. Idempotent: a second call returns False."""
    if has_used_demo(telegram_id):
        return False
    now = _now()
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            return False
        s.add(Subscription(
            user_id=user.id,
            plan='premium',
            status='active',
            stars_amount=0,
            started_at=now,
            expires_at=now + timedelta(hours=DEMO_PREMIUM_HOURS),
            telegram_charge_id=_demo_marker(telegram_id),
        ))
        s.commit()
    return True


def demo_hours_left(telegram_id: int) -> float:
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            return 0.0
        sub = s.scalar(select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.telegram_charge_id == _demo_marker(telegram_id),
        ))
        if not sub or not sub.expires_at:
            return 0.0
        return max(0.0, (sub.expires_at - _now()).total_seconds() / 3600)


def offer_discount(telegram_id: int) -> bool:
    """Open the one-time 24h discount window. True only when just opened."""
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user or user.discount_offered_at:
            return False
        user.discount_offered_at = _now()
        s.commit()
        return True


def discount_info(telegram_id: int) -> dict:
    """Active one-time discount details: {'active', 'price', 'percent', 'hours_left'}."""
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user or not user.discount_offered_at:
            return {'active': False}
        deadline = user.discount_offered_at + timedelta(hours=PREMIUM_DISCOUNT_HOURS)
        now = _now()
        if deadline <= now:
            return {'active': False}
        return {
            'active': True,
            'price': PREMIUM_DISCOUNT_STARS,
            'percent': PREMIUM_DISCOUNT_PERCENT,
            'hours_left': (deadline - now).total_seconds() / 3600,
        }
