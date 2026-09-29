"""V3.44.23: custom-peach tile + channel bonus 100 → 30.

1. The shop grid's sixth tile lets the user type any number of peaches;
   the per-unit price matches the small pack (PEACH_PACK_10 rates).
2. All three payment chains (Stars, Platega, Wallet Pay) carry the custom
   amount through to record_payment, which grants the exact count.
3. The channel-subscribe bonus default dropped from 100 to 30 peaches.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PAYMENTS = (ROOT / 'services' / 'payments.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


# ── 1. config: per-unit prices and channel bonus ────────────────────────────

def test_custom_peach_constants_derived_from_pack10():
    assert 'PEACH_CUSTOM_STARS_PER_UNIT = max(1, PEACH_PACK_10_STARS // 10)' in CONFIG
    assert 'PEACH_CUSTOM_RUB_PER_UNIT = max(1, PEACH_PACK_10_RUB // 10)' in CONFIG


def test_channel_bonus_default_is_thirty():
    assert 'CHANNEL_SUBSCRIBE_BONUS_CREDITS = int(os.getenv("CHANNEL_SUBSCRIBE_BONUS_CREDITS", "30"))' in CONFIG


# ── 2. webapp_service: the custom product in the invoice list ───────────────

def test_invoice_products_includes_custom_peach():
    assert "'id': 'peach_custom'" in WEBAPP_SVC
    assert "'custom': True" in WEBAPP_SVC
    assert 'PEACH_CUSTOM_STARS_PER_UNIT' in WEBAPP_SVC
    assert 'PEACH_CUSTOM_RUB_PER_UNIT' in WEBAPP_SVC


def test_custom_product_has_both_languages():
    assert "'Своё количество'" in WEBAPP_SVC
    assert "'Custom amount'" in WEBAPP_SVC


# ── 3. main.py: _platega_amount_for handles peach_custom_N ──────────────────

def test_platega_amount_for_custom_peach():
    fn = MAIN[MAIN.index('def _platega_amount_for('):]
    fn = fn[:fn.index("@dp.callback_query(F.data.startswith('platega:'))")]
    assert "product.startswith('peach_custom_')" in fn
    assert 'PEACH_CUSTOM_RUB_PER_UNIT' in fn


# ── 4. main.py: pre_checkout validates the custom Stars amount ──────────────

def test_pre_checkout_validates_custom_peach():
    pre = MAIN[MAIN.index('@dp.pre_checkout_query()'):MAIN.index('@dp.message(F.successful_payment)')]
    assert "payload.startswith('peach_custom_')" in pre
    assert 'PEACH_CUSTOM_STARS_PER_UNIT' in pre


# ── 5. main.py: successful_payment grants custom peaches ────────────────────

def test_successful_payment_grants_custom_peaches():
    sp = MAIN[MAIN.index('@dp.message(F.successful_payment)'):]
    sp = sp[:sp.index("if payload == 'photo_pack':")]
    assert "payload.startswith('peach_custom_')" in sp
    assert 'record_payment(message.from_user.id, payload, payment.total_amount, charge)' in sp


# ── 6. main.py: Platega callback confirms custom peaches ────────────────────

def test_platega_callback_confirms_custom_peaches():
    cb = MAIN[MAIN.index("async def _platega_callback"):]
    cb = cb[:cb.index('else:') if "confirm = '💖 Оплата прошла!" in cb[cb.index("elif product in PEACH_PACK_CREDITS:"):] else len(cb)]
    assert "product.startswith('peach_custom_')" in cb


# ── 7. payments.py: record_payment grants the custom count ──────────────────

def test_record_payment_grants_custom_peach_count():
    assert "product.startswith('peach_custom_')" in PAYMENTS
    assert "int(product.split('_')[-1])" in PAYMENTS


# ── 8. main.py: webapp invoice endpoint handles custom amount ───────────────

def test_webapp_invoice_handles_custom_peach():
    inv = MAIN[MAIN.index('async def _webapp_api_invoice('):]
    inv = inv[:inv.index('async def _webapp_api_pay_link(')]
    assert "product_id == 'peach_custom'" in inv
    assert "PEACH_CUSTOM_STARS_PER_UNIT" in inv
    assert "(body or {}).get('amount'" in inv


# ── 9. main.py: webapp pay_link endpoint handles custom amount ──────────────

def test_webapp_pay_link_handles_custom_peach():
    pl = MAIN[MAIN.index('async def _webapp_api_pay_link('):]
    pl = pl[:pl.index('async def _webapp_api_select(')]
    assert "product_id == 'peach_custom'" in pl
    assert "PEACH_CUSTOM_RUB_PER_UNIT" in pl
    assert "f'peach_custom_{_ca}'" in pl


# ── 10. frontend: custom tile rendering and L10N ────────────────────────────

def test_custom_tile_l10n_strings():
    assert "shop_custom_ph:" in INDEX
    assert "shop_custom_btn:" in INDEX
    assert 'How many peaches?' in INDEX
    assert 'Сколько персиков?' in INDEX


def test_custom_tile_css():
    assert '.pack.custom' in INDEX
    assert '.pack.custom input[type=number]' in INDEX


def test_custom_tile_rendered_in_shop():
    assert "const customItem = purchases.find(x => x.custom)" in INDEX
    assert "const regularPurchases = purchases.filter(x => !x.custom)" in INDEX
    assert 'id="customN"' in INDEX
    assert 'id="customGet"' in INDEX


def test_open_pay_custom_function():
    assert 'function openPayCustom(n)' in INDEX
    assert "payVia('peach_custom'" in INDEX


def test_buy_function_accepts_extra():
    assert 'async function buy(productId, btn, extra)' in INDEX
    assert 'Object.assign({ product: productId }, extra || {})' in INDEX


def test_pay_via_accepts_extra():
    assert 'async function payVia(id, method, btn, extra)' in INDEX
    assert 'Object.assign({ product: id, method }, extra || {})' in INDEX


# ── 11. frontend: CHAN default matches the new bonus ────────────────────────

def test_chan_default_bonus_is_thirty():
    assert "bonus: 30" in INDEX


# ── 12. platega_pay invoice title for custom peaches ────────────────────────

def test_platega_pay_title_for_custom_peach():
    pp = MAIN[MAIN.index("async def platega_pay("):]
    pp = pp[:pp.index("@dp.callback_query(F.data == 'donate:open')")]
    assert "product.startswith('peach_custom_')" in pp
    assert 'персиков — {amount} ₽' in pp
