"""Tap-to-speak uses stored sources, explicit paid consent, and persistent replay."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_speak_routes_are_wired_to_authenticated_handlers():
    tree = ast.parse(MAIN)
    expected = {'/webapp/api/chat/speak': '_webapp_api_chat_speak',
                '/webapp/api/chat/speak/event': '_webapp_api_chat_speak_event'}
    routes = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'add_post' and len(node.args) >= 2
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[1], ast.Name)):
            routes[node.args[0].value] = node.args[1].id
    for path, handler in expected.items():
        assert routes[path] == handler
        function = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == handler)
        body = ast.get_source_segment(MAIN, function)
        assert 'validate_init_data' in body and 'init_data_user' in body


def test_speak_contract_uses_reservation_not_a_blanket_premium_wall():
    tree = ast.parse(MAIN)
    function = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                    and n.name == '_webapp_api_chat_speak')
    body = ast.get_source_segment(MAIN, function)
    assert 'voices.reserve' in body
    assert "body.get('allow_paid') is True" in body
    assert 'quoted_price=quoted_price' in body
    assert "'payment_required': 402" in body
    assert 'premium_required' not in body
    assert "body.get('text'" not in body
    assert "reservation['text']" in body


def test_spa_keeps_voice_ui_and_requires_price_and_source_for_paid_requests():
    start = SPA.index('async function speakLazy(')
    body = SPA[start:SPA.index('\nfunction voicePlaybackEvent(', start)]
    assert "fetch('/webapp/api/chat/speak?init_data='" in body
    assert 'message_id: messageId' in body and 'character_id: chatId' in body
    assert "j.error === 'payment_required'" in body
    assert 'confirmVoice(price)' in body
    assert 'allow_paid: true, quoted_price: price' in body
    assert "quickBuy('voice')" not in body
    assert 'premium_required' not in body
    assert '` data-say="${esc(m.content)}"`' in SPA
    assert 'class="vp-wave"' in SPA and 'class="vp-btn"' in SPA
    assert "say_btn: '▶ Голосом'" in SPA and "say_btn: '▶ Voice'" in SPA
