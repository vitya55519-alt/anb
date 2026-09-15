"""Static regression tests for v3.33.0: Telegram Mini App (WebApp) storefront.

Owner benchmarked the payment partner's sample bot (@come_closer_bot) and
asked for a comparable Mini App. v3.33.0 is the skeleton: initData HMAC
authorization, dark-themed page with bottom navigation (Персонажи / Магазин /
Профиль / Документы), character cards with photos, structured shop prices,
profile payload, and the Platega-required legal documents inside the app.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


def test_version_bumped():
    assert VERSION in ('3.32.1', '3.33.0', '3.33.1', '3.34.0', '3.34.1', '3.35.0', '3.36.0', '3.37.0', '3.38.0')


def test_init_data_hmac_validation():
    # the official Telegram algorithm: secret = HMAC("WebAppData", token)
    assert 'def validate_init_data(init_data: str' in WEBAPP_SVC
    assert "hmac.new(b'WebAppData', token.encode(), hashlib.sha256)" in WEBAPP_SVC
    assert 'hmac.compare_digest(calculated, received_hash)' in WEBAPP_SVC
    # freshness window so a captured initData can be replayed only briefly
    assert 'max_age_seconds: int = 86400' in WEBAPP_SVC
    assert 'def init_data_user(pairs: dict) -> dict:' in WEBAPP_SVC


def test_api_payload_builders():
    for fn in (
        'def api_me(telegram_id: int) -> dict:',
        'def api_characters(telegram_id: int | None = None) -> list[dict]:',
        'def api_shop(lang: str = \'ru\') -> dict:',
        'def api_legal(lang: str = \'ru\') -> dict:',
        'def character_photo(character_id: str) -> tuple[bytes, str] | None:',
    ):
        assert fn in WEBAPP_SVC, f'missing: {fn}'
    # profile reads real state, storefront reads real cards
    assert 'is_premium(telegram_id)' in WEBAPP_SVC
    assert 'list_cards(visible_only=True)' in WEBAPP_SVC
    assert 'get_relationship_level(telegram_id, selected_character)' in WEBAPP_SVC
    # shop prices come from the same constants the bot charges
    assert 'PREMIUM_MONTHLY_STARS' in WEBAPP_SVC
    assert 'PHOTO_COST_STARS' in WEBAPP_SVC
    assert 'VIDEO_COST_STARS' in WEBAPP_SVC
    # legal tab reuses the v3.32.0 documents (incl. the чекап word)
    assert 'legal_service.PRIVACY_POLICY' in WEBAPP_SVC
    assert 'legal_service.tariffs_text(lang)' in WEBAPP_SVC
    assert 'LEGAL_CHECK_WORD' in WEBAPP_SVC


def test_character_photos_served_locally():
    # built-ins -> canonical face references; customs -> cached avatar
    assert "base / 'custom_references' / character_id / 'avatar.jpg'" in WEBAPP_SVC
    assert "base / 'references'" in WEBAPP_SVC or "'references'" in WEBAPP_SVC
    assert "is_custom_character(character_id)" in WEBAPP_SVC


def test_webapp_page_structure():
    assert 'telegram-web-app.js' in INDEX
    assert 'const tg = window.Telegram.WebApp;' in INDEX
    assert 'tg.ready()' in INDEX
    # V3.38.0: five tabs in the bottom navigation (Come Closer layout);
    # Партнёрка/Документы became full-screen overlays from the profile tab.
    for tab in ('tab-characters', 'tab-chats', 'tab-pictures', 'tab-shop', 'tab-profile'):
        assert f'id="{tab}"' in INDEX, f'missing tab: {tab}'
    assert 'id="bottomnav"' in INDEX
    assert 'id="partnerview"' in INDEX
    assert 'id="docsview"' in INDEX
    # the page calls our endpoints with absolute paths
    assert "fetch('/webapp/api/me?init_data=' + encodeURIComponent(tg.initData" in INDEX
    assert "fetch('/webapp/api/characters'" in INDEX
    assert "fetch('/webapp/api/shop?lang='" in INDEX
    assert "fetch('/webapp/api/legal?lang='" in INDEX
    assert "fetch('/webapp/api/chats?init_data=' + encodeURIComponent(tg.initData" in INDEX
    assert "fetch('/webapp/api/picture?init_data=' + encodeURIComponent(tg.initData)" in INDEX
    # no real import from main (handlers import the service, not vice versa);
    # the docstring may MENTION main.py, so match actual import statements
    import re as _re
    assert not _re.search(r'^\s*(from main import|import main\b)', WEBAPP_SVC, _re.MULTILINE)


def test_routes_registered():
    server = MAIN[MAIN.index('async def _start_web_server()'):]
    server = server[:server.index('async def main()')]
    for route in (
        "/webapp'",
        '/webapp/api/me',
        '/webapp/api/characters',
        '/webapp/api/shop',
        '/webapp/api/legal',
        '/webapp/photo/{character_id}',
    ):
        assert route in server, f'missing route: {route}'
    assert "add_get('/webapp', _webapp_index)" in MAIN
    assert "add_get('/webapp/photo/{character_id}', _webapp_photo)" in MAIN


def test_me_endpoint_requires_valid_init_data():
    handler = MAIN[MAIN.index('async def _webapp_api_me('):MAIN.index('async def _webapp_api_characters(')]
    assert 'webapp_service.validate_init_data' in handler
    assert "status=401" in handler
    assert 'ensure_user(' in handler
    assert 'webapp_service.api_me(telegram_id)' in handler


def test_photo_endpoint_serves_bytes():
    handler = MAIN[MAIN.index('async def _webapp_api_me('):MAIN.index('async def _start_web_server(')]
    photo = handler[handler.index('async def _webapp_photo('):]
    assert 'webapp_service.character_photo(' in photo
    assert 'return web.Response(status=404)' in photo
    assert 'web.Response(body=data, content_type=content_type' in photo


def test_menu_button_installed_when_public_url_set():
    main_body = MAIN[MAIN.index('async def main():'):]
    assert 'if PUBLIC_BASE_URL:' in main_body
    assert 'types.MenuButtonWebApp(' in main_body
    assert "types.WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp')" in main_body
    assert 'set_chat_menu_button' in main_body
    # the call is guarded — a Telegram API hiccup must not kill startup
    assert "logger.exception('failed to set webapp menu button')" in main_body


def test_guaranteed_app_entry_points():
    # V3.33.1: /app command + settings launcher work even when the profile
    # «Открыть приложение» button is hidden by client caching or BotFather
    # main-mini-app state.
    assert "@dp.message(Command('app'))" in MAIN
    assert "types.BotCommand(command='app', description='🛍 Приложение')" in MAIN
    # web_app buttons: /app (RU+EN branches), settings row, menu button
    assert MAIN.count("web_app=types.WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp')") >= 3 or \
        MAIN.count("web_app=types.WebAppInfo(url=url)") >= 2
    # loud warning instead of a silent skip when the public URL is missing
    main_body = MAIN[MAIN.index('async def main():'):]
    assert "logger.warning('PUBLIC_BASE_URL is not set" in main_body
    # after setting, the actual Telegram state is read back and logged
    assert 'get_chat_menu_button' in main_body
    # /app explains the missing server config instead of failing silently
    app_cmd = MAIN[MAIN.index("@dp.message(Command('app'))"):MAIN.index("@dp.message(Command('support'))")]
    assert 'PUBLIC_BASE_URL' in app_cmd


def test_fkcheck_reports_webapp_diagnostics():
    # V3.33.1: the owner diagnoses the missing app button via /fkcheck
    fk = MAIN[MAIN.index('async def _fk_check('):MAIN.index('async def _root(')]
    assert 'WEBAPP_PUBLIC_URL=' in fk
    assert 'WEBAPP_SELF_PROBE=' in fk
    assert "'WEBAPP_SELF_PROBE=SKIPPED (PUBLIC_BASE_URL not set)'" in fk
