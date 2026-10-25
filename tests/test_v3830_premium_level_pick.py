from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pick_applies_only_with_premium(monkeypatch):
    from services import test_mode as tm
    monkeypatch.setattr(tm, '_picks_store', lambda: {})
    tm._picks.clear()
    tm._overrides.pop(777001, None); tm._loaded.add(777001)
    tm.pick_stage(777001, 'anna_01', 'devoted')
    monkeypatch.setattr(tm, '_premium', lambda uid: True)
    assert tm.get_stage(777001, 'anna_01') == 'devoted'
    assert tm.get_stage(777001, 'mila_01') is None
    assert tm.get_stage(777001) is None  # callers without a girl see only /testlevel
    assert tm.picked_stages(777001) == {'anna_01': 'devoted'}
    monkeypatch.setattr(tm, '_premium', lambda uid: False)
    assert tm.get_stage(777001, 'anna_01') is None and tm.picked_stages(777001) == {}
    tm.pick_stage(777001, 'anna_01', None)
    monkeypatch.setattr(tm, '_premium', lambda uid: True)
    assert tm.get_stage(777001, 'anna_01') is None


def test_admin_testlevel_wins_over_pick(monkeypatch):
    from services import test_mode as tm
    monkeypatch.setattr(tm, '_picks_store', lambda: {})
    monkeypatch.setattr(tm, '_db_write', lambda *a: None)
    monkeypatch.setattr(tm, '_premium', lambda uid: True)
    tm._picks.clear()
    tm.pick_stage(777002, 'anna_01', 'close')
    tm.set_stage(777002, 'eternal')
    assert tm.get_stage(777002, 'anna_01') == 'eternal'
    tm._overrides.pop(777002, None)


def test_wiring():
    main = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert "add_post('/webapp/api/chat/level/pick', _webapp_api_chat_level_pick)" in main
    assert "{'ok': False, 'error': 'premium'}, status=403" in main
    assert "snap['can_pick'] = bool(premium)" in main
    assert 'любой уровень общения 1–10' in main
    chat = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
    assert 'get_test_stage(user_id, character_id)' in chat
    photo = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
    assert 'get_test_stage(telegram_id, character_id)' in photo
    spa = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
    assert 'async function pickLevel(level, branch)' in spa and "id=\"lvlPickPremium\"" in spa
    shop = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
    assert 'любой уровень общения 1–10' in shop and 'picked_stages(telegram_id)' in shop
