"""V3.20.0 retention & monetization pack.

Mechanics implemented here:
- The read side of the one-time 24h premium discount.
  V3.166.2 (owner — «убираем полностью разовую раздачу и скидку -30%, они
  размывают фокус»): the free 3-hour demo premium is deleted with its
  callbacks, and nothing opens a fresh discount window any more — the reader
  stays, so a window opened before this release and an in-flight
  `premium_month_discount` order still resolve. Users who already hold an
  active demo Subscription simply run it out: `is_premium` reads the row.
- Static emotional push text pools (miss / jealousy / cliffhanger / morning /
  evening rituals) so the scheduler can nudge silent users without spending
  LLM tokens on every push.
"""
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from config import (
    PREMIUM_DISCOUNT_HOURS,
    PREMIUM_DISCOUNT_PERCENT,
    PREMIUM_DISCOUNT_STARS,
)
from models.app_models import User
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


def discount_info(telegram_id: int) -> dict:
    """Active one-time discount details: {'active', 'price', 'percent', 'hours_left'}.
    V3.166.2: nothing opens a window any more (``offer_discount`` is deleted),
    this only reads one the user already has."""
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
