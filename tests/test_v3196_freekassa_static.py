"""Static regression tests for v3.19.6: FreeKassa card/SBP premium.

The owner activated a FreeKassa merchant (card / SBP payments). The bot now
shows a ruble payment button, creates an order row, sends the user to
FreeKassa's payment page, and a tiny aiohttp web server receives the signed
server notification (``/freekassa/notify``) which grants premium idempotently.
Only a notification signed with SECRET2 grants anything, so the public
endpoints are safe.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SERVICE = (ROOT / 'services' / 'freekassa_service.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')


def test_config_gates_freekassa_on_three_secrets():
    assert 'FREEKASSA_MERCHANT_ID = os.getenv("FREEKASSA_MERCHANT_ID", "").strip()' in CONFIG
    assert 'FREEKASSA_SECRET1 = os.getenv("FREEKASSA_SECRET1", "").strip()' in CONFIG
    assert 'FREEKASSA_SECRET2 = os.getenv("FREEKASSA_SECRET2", "").strip()' in CONFIG
    assert 'FREEKASSA_ENABLED = bool(FREEKASSA_MERCHANT_ID and FREEKASSA_SECRET1 and FREEKASSA_SECRET2)' in CONFIG
    assert 'PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")' in CONFIG
    assert 'WEB_PORT = int(os.getenv("PORT", "8080"))' in CONFIG


def test_premium_keyboard_shows_card_button_only_when_enabled():
    # v3.27.0: signature gained telegram_id; the gated block is now the
    # one-click url-button branch plus the legacy callback fallback.
    kb = MAIN[MAIN.index('def premium_keyboard(discount: dict | None = None, telegram_id: int | None = None):'):MAIN.index('def adult_keyboard():')]
    assert 'if FREEKASSA_ENABLED and telegram_id:' in kb
    assert 'elif FREEKASSA_ENABLED:' in kb
    assert "callback_data='fk:premium'" in kb
    assert 'картой / СБП' in kb


def test_fk_premium_handler_creates_order_and_sends_link():
    handler = MAIN[MAIN.index("@dp.callback_query(F.data == 'fk:premium')"):MAIN.index("@dp.callback_query(F.data.startswith('walletpay:'))")]
    assert 'freekassa_service.create_order(' in handler
    assert 'freekassa_service.payment_url(' in handler
    assert 'if not FREEKASSA_ENABLED:' in handler


def test_web_server_routes_and_startup():
    server = MAIN[MAIN.index('async def _start_web_server()'):]
    assert "app.router.add_get('/', _root)" in server
    assert "app.router.add_route('*', '/freekassa/notify', _fk_notify)" in server
    assert "app.router.add_route('*', '/freekassa/success', _fk_success)" in server
    assert "app.router.add_route('*', '/freekassa/fail', _fk_fail)" in server
    assert "app.router.add_get('/healthz', _healthz)" in server
    # The web server must start before polling so callbacks never 404.
    # (v3.19.11: the storefront-description apply sits between the two calls.)
    assert '    await _start_web_server()' in MAIN
    assert MAIN.index('await _start_web_server()') < MAIN.index('await dp.start_polling(bot)')


def test_notify_signature_and_idempotent_grant():
    # Initiation signature uses SECRET1; server notification uses SECRET2.
    assert 'FREEKASSA_SECRET1, str(order_id)]' in SERVICE
    assert 'FREEKASSA_SECRET2, order_id]' in SERVICE
    assert 'hashlib.md5' in SERVICE
    # Grant path: verify -> mark_paid (idempotent) -> record_payment -> notify user.
    notify = MAIN[MAIN.index('async def _fk_notify('):MAIN.index('async def _fk_success(')]
    assert 'freekassa_service.verify_notify(params)' in notify
    assert 'freekassa_service.mark_paid(' in notify
    assert "provider='freekassa'" in notify
    assert 'def mark_paid(order_id: int, payload: str) -> bool:' in SERVICE
    assert "if row.status == 'paid':" in SERVICE


def test_order_model_persists_status_and_payload():
    block = MODELS[MODELS.index('class FreeKassaOrder('):]
    assert '__tablename__ = "freekassa_orders"' in block
    assert 'telegram_id' in block
    assert 'paid_payload' in block
    assert "default=\"pending\"" in block
