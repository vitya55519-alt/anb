"""V3.34.1 static checks: the weekly Premium plan — chat paywall, payment
handlers, Mini App shop product and the Platega legal tariffs all expose the
same 7-day option priced from the same config constant."""
import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PAYMENTS = (ROOT / 'services' / 'payments.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
LEGAL = (ROOT / 'services' / 'legal_service.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_version_bumped():
    assert VERSION in ('3.34.0', '3.34.1', '3.35.0', '3.36.0', '3.37.0')


def test_config_declares_weekly_plan():
    cfg = importlib.import_module('config')
    assert cfg.PREMIUM_WEEKLY_STARS >= 1
    assert cfg.PREMIUM_WEEKLY_PHOTO_CREDITS >= 1
    assert cfg.PREMIUM_WEEKLY_STARS * 4 > cfg.PREMIUM_MONTHLY_STARS, (
        'buying 4 weeks must cost more Stars than the month — the month stays the better deal'
    )
    assert 'PREMIUM_WEEKLY_STARS' in CONFIG and 'PREMIUM_WEEKLY_PHOTO_CREDITS' in CONFIG


def test_payments_grant_week():
    # the product is priced from the same constant pre_checkout validates
    # (PRODUCTS uses the module's compact key:value style)
    assert '"premium_week":PREMIUM_WEEKLY_STARS' in PAYMENTS
    grant = PAYMENTS[PAYMENTS.index('if product in {"premium_month","premium_month_discount","premium_week"}'):]
    grant = grant[:grant.index('elif product')]
    assert 'days=7 if product=="premium_week" else 30' in grant
    assert 'credits=PREMIUM_WEEKLY_PHOTO_CREDITS if product=="premium_week" else PREMIUM_MONTHLY_PHOTO_CREDITS' in grant
    assert 'timedelta(days=days)' in grant


def test_bot_payment_handlers_validate_and_grant_week():
    pre = MAIN[MAIN.index('@dp.pre_checkout_query()'):MAIN.index('@dp.message(F.successful_payment)')]
    assert "elif payload=='premium_week':" in pre
    assert 'ok=amount==PREMIUM_WEEKLY_STARS' in pre

    pay = MAIN[MAIN.index('@dp.message(F.successful_payment)'):]
    week = pay[pay.index("if payload == 'premium_week':"):pay.index("if payload == 'premium_month_discount':")]
    assert "record_payment(message.from_user.id, 'premium_week', payment.total_amount, charge)" in week
    assert "metadata={'product': 'premium_week'}" in week
    # bilingual confirmation with the live weekly credit amount
    assert "f'done ✨ Premium is active for 7 days and I added {PREMIUM_WEEKLY_PHOTO_CREDITS}" in week
    assert "f'готово ✨ Premium активирован на 7 дней, и я добавила {PREMIUM_WEEKLY_PHOTO_CREDITS}" in week


def test_chat_paywall_offers_week_button():
    kb = MAIN[MAIN.index('def premium_keyboard('):MAIN.index('def adult_keyboard():')]
    assert "callback_data='buy:premium_week'" in kb
    assert "f'⭐ Premium на неделю — {PREMIUM_WEEKLY_STARS} Stars" in kb
    # the invoice callback shares the chat pipeline
    assert "@dp.callback_query(F.data == 'buy:premium_week')" in MAIN
    assert "'premium_week', PREMIUM_WEEKLY_STARS)" in MAIN
    # the pitch lists both plans instead of a monthly-only heading
    assert "f'• тарифы: неделя — {PREMIUM_WEEKLY_STARS} Stars" in MAIN
    assert "f'• plans: a week — {PREMIUM_WEEKLY_STARS} Stars" in MAIN


def test_rub_prices_next_to_stars():
    # V3.34.1 owner request: «рядом со звездочками пропиши цену в рублях» —
    # and the rub price must be a real card/SBP charge, not a display number.
    cfg = importlib.import_module('config')
    assert cfg.FREEKASSA_PREMIUM_WEEKLY_PRICE_RUB >= 1
    assert cfg.FREEKASSA_PREMIUM_WEEKLY_PRICE_RUB * 4 > cfg.FREEKASSA_PREMIUM_PRICE_RUB
    kb = MAIN[MAIN.index('def premium_keyboard('):MAIN.index('def adult_keyboard():')]
    # V3.36.0: the stars buttons carry rub + dollar inline via fiat_suffix,
    # using the real card prices when FreeKassa is on.
    assert 'fiat_suffix(PREMIUM_MONTHLY_STARS, rub=FREEKASSA_PREMIUM_PRICE_RUB, usd=FREEKASSA_PREMIUM_PRICE_USD' in kb
    assert 'fiat_suffix(PREMIUM_WEEKLY_STARS, rub=FREEKASSA_PREMIUM_WEEKLY_PRICE_RUB, usd=PREMIUM_WEEKLY_PRICE_USD' in kb
    # the weekly plan is payable by card/SBP: its own fkapi row + price lookup
    assert "_fk_pay_button(\n                'premium_week', FREEKASSA_PREMIUM_WEEKLY_PRICE_RUB," in MAIN
    assert "f'💳 Premium на неделю — {FREEKASSA_PREMIUM_WEEKLY_PRICE_RUB} ₽ · ⚡СБП / карта'" in MAIN
    amount_fn = MAIN[MAIN.index('def _fk_amount_for('):MAIN.index('@dp.callback_query(F.data.startswith(\'fkapi:\')')]
    assert "if product == 'premium_week':" in amount_fn
    assert 'return FREEKASSA_PREMIUM_WEEKLY_PRICE_RUB' in amount_fn
    # the invoice title and the webhook confirmation name the week correctly
    assert "title = f'💳 Premium на неделю — {sign}{amount}'" in MAIN
    assert "elif product == 'premium_week':" in MAIN[MAIN.index('async def _fk_notify('):]
    assert "confirm = '💖 Оплата прошла! Premium активирован на 7 дней." in MAIN
    # the Mini App products carry the rub price for both plans
    assert "'rub': FREEKASSA_PREMIUM_PRICE_RUB if FREEKASSA_ENABLED else None," in WEBAPP_SVC
    assert "'rub': FREEKASSA_PREMIUM_WEEKLY_PRICE_RUB if FREEKASSA_ENABLED else None," in WEBAPP_SVC
    assert 'const moRub = premBuy ? fiat(premBuy) : \'\'' in INDEX
    assert 'const wkRub = premWeek ? fiat(premWeek) : \'\'' in INDEX
    # the legal tariffs price the week in rubles too (Platega) — via fiat_suffix
    assert 'fiat_suffix(PREMIUM_WEEKLY_STARS, rub=FREEKASSA_PREMIUM_WEEKLY_PRICE_RUB, usd=PREMIUM_WEEKLY_PRICE_USD' in LEGAL


def test_mini_app_sells_week():
    assert "'id': 'premium_week'" in WEBAPP_SVC
    assert "'payload': 'premium_week'" in WEBAPP_SVC
    assert "'stars': PREMIUM_WEEKLY_STARS," in WEBAPP_SVC
    assert 'Premium · 7 дней' in WEBAPP_SVC
    assert 'Premium · 7 days' in WEBAPP_SVC
    # frontend: ghost CTA under the monthly button on the Premium hero
    assert 'data-buy="premium_week"' in INDEX
    assert "premWeek.stars} — ${esc(L.week)}" in INDEX
    assert 'cta ghost' in INDEX
    assert "week: '7 days'" in INDEX and "week: '7 дней'" in INDEX


def test_legal_tariffs_list_week():
    # Platega requires actual prices for every plan — RU and EN tariffs
    assert "f'⭐ Premium — подписка на 7 дней: {PREMIUM_WEEKLY_STARS}⭐{fiat_suffix(PREMIUM_WEEKLY_STARS" in LEGAL
    assert "f'⭐ Premium — 7-day subscription: {PREMIUM_WEEKLY_STARS}⭐{fiat_suffix(PREMIUM_WEEKLY_STARS" in LEGAL
    assert 'PREMIUM_WEEKLY_PHOTO_CREDITS' in LEGAL
