"""V3.107.0 — «Без сюрпризов»: an honest card on every Mini App open.

Owner: «когда человек переходит в бот… маленькое окошечко с крестиком… что
она умеет, что не умеет, чтобы сразу все видели». Market research
(plans/market-research-2026-11.md): rivals are blamed for hidden prices,
forgetting, hard refunds and murky privacy — this card answers each upfront.

Every number on the card comes from the live config, never a hand-written
claim, so it cannot drift from what the bot really does. No social proof,
no counters: only facts.

Flag: HONEST_CARD_ENABLED (default on).
"""
from __future__ import annotations

import os

from config import (
    FREE_MESSAGES_PER_DAY, FREE_MESSAGES_PER_DAY_LATE, FREE_LATE_FROM_DAY,
    CHAT_FREE_PHOTOS_PER_DAY, PLATEGA_ENABLED, PLATEGA_PREMIUM_WEEKLY_PRICE_RUB,
    PREMIUM_WEEKLY_STARS, SUPPORT_BOT_USERNAME,
)

ENABLED = os.getenv('HONEST_CARD_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')


def facts() -> dict:
    """The live numbers the card shows (the Mini App renders the words)."""
    try:
        from services import voice_taste
        free_voice = voice_taste.FREE_REPLIES if voice_taste.ENABLED else 0
    except Exception:
        free_voice = 0
    return {
        'enabled': ENABLED,
        'free_messages': int(FREE_MESSAGES_PER_DAY),
        'free_messages_later': int(min(FREE_MESSAGES_PER_DAY, FREE_MESSAGES_PER_DAY_LATE)),
        'later_from_day': int(FREE_LATE_FROM_DAY),
        'free_photos': int(CHAT_FREE_PHOTOS_PER_DAY),
        'free_voice': int(free_voice),
        'week_rub': int(PLATEGA_PREMIUM_WEEKLY_PRICE_RUB) if PLATEGA_ENABLED else None,
        'week_stars': int(PREMIUM_WEEKLY_STARS),
        'support': SUPPORT_BOT_USERNAME or '',
    }
