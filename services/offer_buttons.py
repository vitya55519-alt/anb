"""V3.111.0: one set of pay buttons for the bot-chat offers, in his language.

Audit 5 Nov 2026 («проверить, что иностранцы вообще могут заплатить»): 38% of
new users are English-speaking, yet in the bot chat every pay row was either
Russian (card / SBP) or hidden from them (`if PLATEGA_ENABLED and not en`),
so abroad the only way to pay there was Telegram Stars — and one EN user had
already failed with Stars. Platega's page takes crypto too, so EN users now get
Stars first and a «💎 crypto / card» row second; RU users keep card/SBP first.

Rows are plain (text, callback_data) pairs so services and tests need no
aiogram; the caller wraps them into InlineKeyboardButtons.
"""
from __future__ import annotations

from config import (
    PLATEGA_ENABLED, PLATEGA_PREMIUM_PRICE_RUB, PLATEGA_PREMIUM_TRIAL_PRICE_RUB,
    PLATEGA_PREMIUM_WEEKLY_PRICE_RUB, PREMIUM_MONTHLY_STARS, PREMIUM_TRIAL_DAYS,
    PREMIUM_TRIAL_STARS, PREMIUM_WEEKLY_STARS,
)

_RUB = {
    'premium_trial': PLATEGA_PREMIUM_TRIAL_PRICE_RUB,
    'premium_week': PLATEGA_PREMIUM_WEEKLY_PRICE_RUB,
    'premium_month': PLATEGA_PREMIUM_PRICE_RUB,
}


def _platega_on() -> bool:
    if not PLATEGA_ENABLED:
        return False
    try:
        from services.payment_method_service import is_button_enabled
        return is_button_enabled('platega_rub')
    except Exception:
        return True


def plan_rows(trial: bool, en: bool, platega: bool | None = None) -> list[tuple[str, str]]:
    """The cheapest honest first step: the 3-day trial while he may take it,
    else a week. RU: card/SBP (the page takes crypto too) then Stars; EN: Stars then crypto/card."""
    platega = _platega_on() if platega is None else platega
    if trial:
        product, stars_cb = 'premium_trial', 'buy:premium_trial'
        stars, rub = PREMIUM_TRIAL_STARS, _RUB['premium_trial']
        ru_name, en_name = f'{PREMIUM_TRIAL_DAYS} дня Premium', f'{PREMIUM_TRIAL_DAYS} days of Premium'
    else:
        product, stars_cb = 'premium_week', 'buy:premium_week'
        stars, rub = PREMIUM_WEEKLY_STARS, _RUB['premium_week']
        ru_name, en_name = 'неделя Premium', 'a week of Premium'
    if en:
        rows = [(f'⭐ {en_name} — {stars} Stars', stars_cb)]
        if platega:
            rows.append((f'💎 crypto / card — {rub} ₽', f'platega:{product}'))
        return rows
    rows = []
    if platega:
        rows.append((f'💳 {ru_name} — {rub} ₽ · карта / СБП', f'platega:{product}'))
    rows.append((f'⭐ {ru_name} — {stars} Stars', stars_cb))
    return rows


def all_plans_row(en: bool) -> tuple[str, str]:
    return ('all plans' if en else 'все варианты', 'first_offer:open')


def tr(en: bool, ru: str, en_text: str) -> str:
    return en_text if en else ru
