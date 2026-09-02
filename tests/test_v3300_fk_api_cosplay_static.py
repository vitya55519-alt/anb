"""V3.30.0 static pins: FreeKassa REST API orders + cosplay photoshoot.

Owner requirement: FreeKassa must be integrated through the REST API
(``https://api.fk.life/v1``, JSON), not SCI — HMAC-SHA256 request signature
(docs 2.2), ``POST /orders/create`` returns the payment link in the
``location`` field and that link is handed to the user; the notify webhook
keeps the MD5 SECRET2 signature (docs 1.4/1.7). On top of that the explicit
adult menu buttons are gone and a token-priced cosplay scene with a costume
picker exists.
"""
from __future__ import annotations

import ast
import hashlib
import hmac
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
FK = (ROOT / 'services' / 'freekassa_service.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')


def test_version_bumped():
    assert VERSION == '3.30.0'


def test_config_exposes_api_key_and_server_ip():
    assert 'FREEKASSA_API_KEY = os.getenv("FREEKASSA_API_KEY", "")' in CONFIG
    assert 'FREEKASSA_API_ENABLED = bool(FREEKASSA_MERCHANT_ID and FREEKASSA_API_KEY)' in CONFIG
    assert 'FREEKASSA_SERVER_IP = os.getenv("FREEKASSA_SERVER_IP", "")' in CONFIG
    assert 'COSPLAY_TOKEN_COST = max(1, int(os.getenv("COSPLAY_TOKEN_COST", "10")))' in CONFIG


def test_api_base_and_sbp_qr_id():
    assert "FK_API_BASE = 'https://api.fk.life/v1'" in FK
    # docs: parameter i=44 is SBP QR-code acceptance
    assert 'FK_SBP_QR_PAYMENT_ID = 44' in FK


def test_request_signature_is_hmac_sha256_over_ksort_pipe():
    # docs 2.2: ksort(params), implode('|', values), hash_hmac sha256 api key
    assert 'def _api_signature(params: dict, key: str) -> str:' in FK
    assert "base = '|'.join(str(params[k]) for k in sorted(params))" in FK
    assert 'hashlib.sha256).hexdigest()' in FK
    # known vector: ksort puts nonce before shopId
    from services import freekassa_service
    params = {'shopId': 777, 'nonce': 123456789}
    expected = hmac.new(b'secret', b'123456789|777', hashlib.sha256).hexdigest()
    assert freekassa_service._api_signature(params, 'secret') == expected


def test_create_api_order_posts_orders_create_and_returns_location():
    assert 'async def create_api_order(' in FK
    assert "f'{FK_API_BASE}/orders/create'" in FK
    # the payment link arrives in `location` and is returned to the caller
    assert "(data or {}).get('location')" in FK
    # docs: email = real client email or TGid@telegram.org; ip is required
    # (127.0.0.1 is rejected), so we send our own public egress IP
    assert '@telegram.org' in FK
    assert "'ip': ip," in FK
    assert 'async def _server_ip() -> str:' in FK
    # nonce must always be greater than the previous request
    assert 'def _nonce() -> int:' in FK
    assert 'int(time.time() * 1000)' in FK


def test_notify_signature_still_md5_secret2():
    # docs 1.7: md5(MERCHANT_ID:AMOUNT:SECRET2:MERCHANT_ORDER_ID)
    assert 'def verify_notify(params: dict) -> tuple[bool, str]:' in FK
    assert '_md5_sign([FREEKASSA_MERCHANT_ID, amount, FREEKASSA_SECRET2, order_id])' in FK


def test_keyboard_uses_callback_buttons_and_handler_sends_location():
    assert 'def _fk_pay_button(' in MAIN
    assert 'fkapi:{product}:{currency or' in MAIN
    assert "@dp.callback_query(F.data.startswith('fkapi:'))" in MAIN
    handler = MAIN[
        MAIN.index("@dp.callback_query(F.data.startswith('fkapi:'))"):
        MAIN.index("@dp.callback_query(F.data == 'cosplay:start')")
    ]
    assert 'freekassa_service.create_order(cq.from_user.id, product, str(amount))' in handler
    assert 'freekassa_service.create_api_order(' in handler
    # SCI form link stays only as a fallback inside the handler
    assert 'link = freekassa_service.payment_url(order_id, str(amount), currency=currency)' in handler
    # the SBP QR row passes i=44
    assert 'pay_id=freekassa_service.FK_SBP_QR_PAYMENT_ID' in MAIN
    assert '⚡ Premium —' in MAIN and 'SBP QR' in MAIN


def test_photo_menu_has_no_explicit_adult_buttons():
    tree = ast.parse(MAIN)
    order = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            getattr(t, 'id', '') == 'PHOTO_MENU_ORDER' for t in node.targets
        ):
            order = [elt.value for elt in node.value.elts if isinstance(elt, ast.Constant)]
    assert order is not None and order
    assert 'nude' not in order and 'tease' not in order
    # labels and backend registries stay for old library photos
    assert "'nude': '🔥 Обнажённая'" in MAIN
    assert "'tease': '🍑 Дразнит'" in MAIN
    assert "'nude':" in PHOTO and "'tease':" in PHOTO


def test_cosplay_scene_and_costumes():
    assert "'cosplay':" in PHOTO
    assert "'cosplay': 3," in PHOTO
    assert 'COSPLAY_COSTUMES = {' in MAIN
    assert 'async def cosplay_start(' in MAIN
    assert 'async def cosplay_pick(' in MAIN
    assert "PhotoRequest(scene='cosplay', clothing=costume[1])" in MAIN
    assert 'spend_tokens(cq.from_user.id, COSPLAY_TOKEN_COST)' in MAIN
    # tokens come back when the job cannot start (busy/budget guard)
    assert 'add_tokens(cq.from_user.id, COSPLAY_TOKEN_COST)' in MAIN
    # photo-menu entry point
    assert "callback_data='cosplay:start'" in MAIN
    assert '🎭 Косплей-фотосет' in MAIN
