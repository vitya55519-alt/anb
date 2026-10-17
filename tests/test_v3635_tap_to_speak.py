"""V3.63.5: tap her message in the app chat → she voices it (Premium perk)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_speak_endpoint_is_premium_gated_and_routed():
    i = MAIN.index('async def _webapp_api_chat_speak')
    body = MAIN[i:i + 2600]
    assert "if telegram_id in ADMIN_TELEGRAM_IDS or is_premium(telegram_id):" in body
    assert "{'ok': False, 'error': 'premium_required'}, status=403" in body
    assert 'await synthesize_bytes(clean, voice_style, character_id=character_id)' in body
    assert "app.router.add_post('/webapp/api/chat/speak', _webapp_api_chat_speak)" in MAIN


def test_spa_offers_voice_on_her_text_and_upsells():
    assert "` data-say=\"${esc(m.content)}\"`" in SPA
    assert "fetch('/webapp/api/chat/speak?init_data='" in SPA
    assert "quickBuy('voice')" in SPA
    assert "say_btn: '▶ Голосом'" in SPA and "say_btn: '▶ Voice'" in SPA
