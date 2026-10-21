"""V3.61.7: «⬇️ Скачать / 🎬 Оживить / 🔥 Раздеть» under her chat photo."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_routes_and_limits():
    assert "'/webapp/api/chat/photo-action'" in MAIN
    assert "'/webapp/smedia/{uid}/{filename}/{sig}'" in MAIN
    from config import UNDRESS_FREE_PER_DAY, UNDRESS_PEACH_COST
    assert UNDRESS_FREE_PER_DAY == 1 and UNDRESS_PEACH_COST == 300
    assert "count_today(uid, 'undress_free') < _undress_premium_free(telegram_id, character_id)" in MAIN
    assert "if not is_adult_confirmed(telegram_id):" in MAIN


def test_only_her_generated_photos_can_be_edited():
    # a user-uploaded picture must never reach the uncensored engine
    assert "Message.role == 'assistant', Message.media_kind == 'photo'" in MAIN
    assert 'if not _her_photo(uid):' in MAIN


def test_undress_prompt_covers_and_adds_the_husband_when_married(monkeypatch):
    import main
    assert 'nipples fully hidden' in main.UNDRESS_VARIANT_TOPLESS[1]
    monkeypatch.setattr(main, 'get_relationship_level', lambda *a: 2)
    import services.webapp_service as ws
    monkeypatch.setattr(ws, '_batch_marital', lambda tid, ids: {ids[0]: 'mar_married'})
    prompt, secret = main._undress_prompt(1, 'vika_01')
    assert secret and 'husband' in prompt and 'back to the camera' in prompt
    monkeypatch.setattr(ws, '_batch_marital', lambda tid, ids: {ids[0]: 'mar_single'})
    prompt, secret = main._undress_prompt(1, 'vika_01')
    assert not secret and 'husband' not in prompt


def test_buttons_under_her_photo():
    assert "pa_undress: '🔥 Раздеть'" in INDEX and "pa_anim: '🎬 Оживить'" in INDEX
    assert 'data-pact="animate"' in INDEX and 'data-pact="undress"' in INDEX
    assert 'async function photoAction(action, mediaUrl, btn)' in INDEX
