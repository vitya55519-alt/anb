"""V3.30.2 static pins: payment-page fix — «страница не загружается».

Root causes (owner reported payment page would not open):

1. The legacy SCI host ``pay.freekassa.ru`` stopped serving the payment
   form (TLS timeout) — switched to ``pay.fk.money`` (docs 1.5).
2. The API parameter ``i`` (payment-system ID, section 1.8) is
   **Required** by ``orders/create``; our code only sent it when
   ``/currencies`` resolved something, so when the lookup failed the API
   rejected the order silently and the caller fell back to the dead SCI
   link. Now ``i`` is always present: explicit param → /currencies →
   documented static fallback from section 1.8.
3. ``/fkcheck`` web route probes every piece of the payment path live
   so the owner can verify the deployment from a browser.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
FK = (ROOT / 'services' / 'freekassa_service.py').read_text(encoding='utf-8')


def test_version_bumped():
    assert VERSION in ('3.30.0', '3.30.1', '3.30.2')


def test_sci_host_is_pay_fk_money_not_dead_ru():
    # pay.freekassa.ru died (TLS timeout); pay.fk.money is the live form.
    # (The old domain may appear in docstrings/comments — check the base URL.)
    assert "FK_SCI_BASE = 'https://pay.fk.money'" in FK
    assert "FK_SCI_BASE = 'https://pay.freekassa.ru'" not in FK


def test_sci_signature_includes_currency_per_docs_1_5():
    # docs 1.5 sign order: Merchant:Amount:Secret1:Currency:Order
    assert 'FREEKASSA_SECRET1, cur, str(order_id)]' in FK
    # and the URL sends the currency param
    assert '&currency={cur}' in FK


def test_api_order_always_sends_required_i():
    # Section 1.8: i is REQUIRED; the static fallback map must exist.
    assert 'FK_CURRENCY_PAYMENT_IDS = {' in FK
    assert "'RUB': 42," in FK    # СБП
    assert "'USD': 2," in FK     # FK WALLET USD
    assert "'EUR': 3," in FK     # FK WALLET EUR
    # The pay_id chain: explicit → /currencies → static fallback
    assert 'or FK_CURRENCY_PAYMENT_IDS.get(currency.upper())' in FK


def test_api_amount_is_numeric_not_string():
    # docs: amount is numeric; round to 2 decimals
    assert "'amount': round(float(amount), 2)," in FK


def test_fkcheck_diagnostics_route():
    assert "app.router.add_get('/fkcheck', _fk_check)" in MAIN
    assert 'async def _fk_check(' in MAIN
    assert 'freekassa_service._server_ip()' in MAIN
    assert 'freekassa_service._default_payment_id(' in MAIN
    assert 'freekassa_service.create_api_order(' in MAIN
    # the route prints the deployed VERSION so owner can verify the build
    assert "VERSION = (Path(__file__).resolve().parent / 'VERSION')" in MAIN


def test_config_api_key_gate_present():
    from pathlib import Path as P
    config = (ROOT / 'config.py').read_text(encoding='utf-8')
    assert 'FREEKASSA_API_KEY = os.getenv("FREEKASSA_API_KEY", "")' in config
    assert 'FREEKASSA_API_ENABLED = bool(FREEKASSA_MERCHANT_ID and FREEKASSA_API_KEY)' in config


def test_legacy_handlers_try_api_first_then_sci():
    # Both legacy handlers must still exist and try API before SCI fallback.
    h_rub = MAIN[MAIN.index("@dp.callback_query(F.data == 'fk:premium')"):
                 MAIN.index("@dp.callback_query(F.data == 'fk:premium_usd')")]
    h_usd = MAIN[MAIN.index("@dp.callback_query(F.data == 'fk:premium_usd')"):
                 MAIN.index("@dp.callback_query(F.data.startswith('fkapi:'))")]
    for h in (h_rub, h_usd):
        assert 'freekassa_service.create_api_order(' in h
        assert 'freekassa_service.payment_url(' in h
