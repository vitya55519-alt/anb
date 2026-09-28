"""V3.44.21 static + runtime pins: Platega replaces FreeKassa end to end.

Owner request: «это апи ключ от новой кассы замени freekassa везде, итегрируй
новую» — the FreeKassa merchant was retired and every ruble path now runs on
Platega (docs.platega.io):

- ``POST /v2/transaction/process`` creates the transaction; its ``url`` is
  the payment page (the payer picks SBP / card / crypto there — no
  payment-system ids, no currencies in button callbacks);
- the status callback hits ``/platega/callback`` authenticated ONLY by the
  X-MerchantId / X-Secret headers (the docs' auth model — there is no payload
  signature), is re-verified through ``GET /transaction/{id}`` and the paid
  amount is checked before anything is granted;
- the orders table is a fresh ``platega_orders`` (BigInteger telegram_id —
  the V3.26.2 lesson; ``transaction_id`` stores the Platega UUID);
- both endpoints were verified live with the production merchant credentials
  BEFORE this shipped (200 + a working pay-page URL), per the V3.44.19
  dead-route lesson.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
PLATEGA = (ROOT / 'services' / 'platega_service.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
PARTNER = (ROOT / 'services' / 'partner_service.py').read_text(encoding='utf-8')
METHODS = (ROOT / 'services' / 'payment_method_service.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
ENV = (ROOT / '.env.example').read_text(encoding='utf-8')


def test_version_bumped():
    assert VERSION in ('3.44.4',)


def test_freekassa_is_gone_everywhere():
    # the service module and its env knobs are deleted, not just disabled
    assert not (ROOT / 'services' / 'freekassa_service.py').exists()
    assert 'FREEKASSA_' not in CONFIG
    assert 'FREEKASSA_' not in ENV
    for needle in ("'freekassa': FREEKASSA_ENABLED", 'fk:premium', 'fkapi:',
                   'async def _fk_notify', 'def _fk_amount_for',
                   '/freekassa/notify', '/fkcheck'):
        assert needle not in MAIN, needle
    assert 'if (x.rub && s.freekassa)' not in INDEX


def test_config_platega_block():
    assert 'PLATEGA_MERCHANT_ID = os.getenv("PLATEGA_MERCHANT_ID", "").strip()' in CONFIG
    assert 'PLATEGA_API_KEY = os.getenv("PLATEGA_API_KEY", "").strip()' in CONFIG
    assert 'PLATEGA_ENABLED = bool(PLATEGA_MERCHANT_ID and PLATEGA_API_KEY)' in CONFIG
    assert 'PLATEGA_API_BASE = os.getenv("PLATEGA_API_BASE", "https://app.platega.io").strip().rstrip("/")' in CONFIG
    assert 'PLATEGA_PREMIUM_PRICE_RUB = max(1, int(os.getenv("PLATEGA_PREMIUM_PRICE_RUB", "899")))' in CONFIG
    assert 'PLATEGA_PREMIUM_WEEKLY_PRICE_RUB = max(1, int(os.getenv("PLATEGA_PREMIUM_WEEKLY_PRICE_RUB", "299")))' in CONFIG
    assert 'PLATEGA_PREMIUM_QUARTERLY_PRICE_RUB = max(1, int(os.getenv("PLATEGA_PREMIUM_QUARTERLY_PRICE_RUB", "1799")))' in CONFIG
    # the USD premium price survived as a display-only tag
    assert 'PREMIUM_PRICE_USD = max(1, int(os.getenv("PREMIUM_PRICE_USD", "5")))' in CONFIG


def test_order_model_is_platega():
    block = MODELS.split('class PlategaOrder', 1)[1].split('\nclass ', 1)[0]
    assert '__tablename__ = "platega_orders"' in block
    assert 'telegram_id: Mapped[int] = mapped_column(BigInteger' in block
    # the Platega UUID — the callback maps back to exactly this row
    assert 'transaction_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)' in block
    assert 'paid_payload' in block
    assert 'class FreeKassaOrder' not in MODELS


def test_service_auth_and_create_payment_body():
    # auth = the two cabinet headers on every request (docs «Начало работы»)
    assert "'X-MerchantId': PLATEGA_MERCHANT_ID" in PLATEGA
    assert "'X-Secret': PLATEGA_API_KEY" in PLATEGA
    assert "f'{PLATEGA_API_BASE}/v2/transaction/process'" in PLATEGA
    # required + antifraud body fields per docs
    assert "'paymentDetails': {'amount': round(float(amount), 2), 'currency': currency}" in PLATEGA
    assert "'return': return_url," in PLATEGA
    assert "'failedUrl': failed_url," in PLATEGA
    assert "f'{ORDER_PAYLOAD_PREFIX}{order_id}'" in PLATEGA
    assert "'orderId': str(order_id)," in PLATEGA
    assert "'metadata': {'userId': str(telegram_id or 0), 'userName': user_ref}" in PLATEGA
    # the transaction UUID is stored on the order row for the callback mapping
    assert 'row.transaction_id = transaction_id[:64]' in PLATEGA
    # status re-check endpoint
    assert "f'{PLATEGA_API_BASE}/transaction/{transaction_id}'" in PLATEGA


def test_callback_header_check_is_timing_safe():
    assert 'import hmac' in PLATEGA
    assert 'hmac.compare_digest(merchant, PLATEGA_MERCHANT_ID)' in PLATEGA
    assert 'hmac.compare_digest(secret, PLATEGA_API_KEY)' in PLATEGA
    # disabled kassa never accepts a callback
    from services import platega_service
    assert platega_service.verify_callback_headers(
        {'X-MerchantId': 'x', 'X-Secret': 'y'}) is False


def test_runtime_payload_mapping_helpers():
    from services import platega_service
    assert platega_service.parse_order_ref('anb_order:42') == 42
    assert platega_service.parse_order_ref('anb_order:nope') is None
    assert platega_service.parse_order_ref('') is None
    assert platega_service.parse_order_ref(None) is None
    assert platega_service.amount_covers(899, '899') is True
    assert platega_service.amount_covers(898.99, '899') is True   # 0.01 tolerance
    assert platega_service.amount_covers(898, '899') is False
    assert platega_service.amount_covers(None, '899') is False


def test_pay_button_and_handler():
    assert "callback_data=f'platega:{product}'" in MAIN
    handler = MAIN[MAIN.index("@dp.callback_query(F.data.startswith('platega:'))"):]
    handler = handler[:handler.index("@dp.callback_query(F.data.startswith('paymethod:'))")]
    assert 'platega_service.create_order(cq.from_user.id, product, str(amount))' in handler
    assert 'await platega_service.create_payment(' in handler
    # no SCI fallback exists — a failed create_payment must SAY so, not send
    # a dead link (the V3.44.19 lesson)
    assert 'не получилось создать счёт' in handler
    # the payer picks the method on the payment page
    assert 'Способ оплаты выберешь на странице платежа.' in handler


def test_callback_route_verifies_before_granting():
    callback = MAIN[MAIN.index('async def _platega_callback('):]
    callback = callback[:callback.index('async def _platega_success(')]
    # 401 unless the X-MerchantId/X-Secret headers match the cabinet values
    assert 'platega_service.verify_callback_headers(request.headers)' in callback
    assert "return web.Response(text='NO|auth', status=401)" in callback
    # order mapping: transaction UUID first, then the anb_order: payload
    assert 'platega_service.find_order(transaction_id, payload)' in callback
    # defense in depth on CONFIRMED: provider re-check + paid-amount check
    assert 'await platega_service.get_transaction(transaction_id)' in callback
    assert 'platega_service.amount_covers(body.get(\'amount\'), order[\'amount\'])' in callback
    assert 'platega_service.mark_paid(order[\'id\'], json.dumps(body, ensure_ascii=False))' in callback
    # every grant lands in the shared record_payment choke point with the
    # partner-commission payload
    assert "f'platega:{order[\"id\"]}', provider='platega'," in callback
    assert "provider_payload=f'amount={order[\"amount\"]}'" in callback
    # CANCELED / CHARGEBACKED only touch the order row
    assert 'platega_service.mark_canceled(' in callback
    assert "'chargedback' if status == platega_service.STATUS_CHARGEBACKED else 'canceled'" in callback
    # always 200 OK so Platega stops retrying (60s timeout, 3×5min retries)
    assert callback.count("web.Response(text='OK')") >= 4


def test_grant_chain_covers_every_product():
    callback = MAIN[MAIN.index('async def _platega_callback('):]
    callback = callback[:callback.index('async def _platega_success(')]
    for needle in ("if product == 'constructor_rub':",
                   "elif product.startswith('tokens_'):",
                   "elif product == 'premium_week':",
                   "elif product == 'premium_quarter':",
                   "elif product == 'photo':",
                   'elif product in PEACH_PACK_CREDITS:'):
        assert needle in callback, needle


def test_web_routes():
    server = MAIN[MAIN.index('async def _start_web_server()'):]
    assert "app.router.add_route('*', '/platega/callback', _platega_callback)" in server
    assert "app.router.add_route('*', '/platega/success', _platega_success)" in server
    assert "app.router.add_route('*', '/platega/fail', _platega_fail)" in server
    assert "app.router.add_get('/platega/check', _platega_check)" in server
    # the web server must start before polling so callbacks never 404
    assert MAIN.index('await _start_web_server()') < MAIN.index('await dp.start_polling(bot)')


def test_diagnostics_probe_probes_the_real_flow():
    check = MAIN[MAIN.index('async def _platega_check('):MAIN.index('async def _root(')]
    assert 'PLATEGA_ENABLED={PLATEGA_ENABLED}' in check
    assert "platega_service.create_order(0, 'plategacheck', '10')" in check
    assert 'await platega_service.create_payment(order_id, \'10\')' in check
    assert 'await platega_service.get_transaction(transaction_id)' in check
    # the V3.33.1 webapp diagnostics ride on the same page
    assert 'WEBAPP_SELF_PROBE=' in check


def test_pay_link_sbp_uses_platega():
    handler = MAIN[MAIN.index('async def _webapp_api_pay_link('):]
    handler = handler[:handler.index('async def _webapp_api_select(')]
    assert 'if not PLATEGA_ENABLED or not product.get(\'rub\'):' in handler
    assert 'platega_service.create_order(telegram_id, order_product, amount)' in handler
    assert 'await platega_service.create_payment(' in handler
    # no SCI fallback — a failed link is a 502, not a dead tab
    assert "{'ok': False, 'error': 'invoice'}, status=502" in handler


def test_shop_flags_and_builtin_rows():
    assert "'platega': PLATEGA_ENABLED," in WEBAPP_SVC
    assert "'rub': PLATEGA_PREMIUM_PRICE_RUB if PLATEGA_ENABLED else None," in WEBAPP_SVC
    assert "'rub': PLATEGA_PREMIUM_WEEKLY_PRICE_RUB if PLATEGA_ENABLED else None," in WEBAPP_SVC
    # the frontend SBP row follows the same flag
    assert 'if (x.rub && s.platega)' in INDEX
    # built-in keyboard rows: one rub set + tokens (the fk trio collapsed)
    assert '"platega_rub"' in METHODS
    assert '"platega_tokens"' in METHODS
    for dead in ('"freekassa_rub"', '"freekassa_sbp"', '"freekassa_usd"', '"freekassa_tokens"'):
        assert dead not in METHODS, dead
    # leftover freekassa_% rows are switched off, not left active
    assert "PaymentMethod.method_key.like('freekassa_%')" in METHODS


def test_partner_commission_keeps_working():
    # the 30/40% partner cut reads amount=X from provider_payload — the same
    # shape Platega orders send, with both providers accepted
    assert 'if provider in ("freekassa", "platega"):' in PARTNER
    assert 'def _freekassa_amount_rub(' in PARTNER


def test_env_example_documents_the_cabinet():
    assert 'PLATEGA_MERCHANT_ID=' in ENV
    assert 'PLATEGA_API_KEY=' in ENV
    assert 'PLATEGA_API_BASE=https://app.platega.io' in ENV
    # the callback URL the owner must paste into the Platega cabinet
    assert '/platega/callback' in ENV
