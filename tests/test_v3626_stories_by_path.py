"""V3.62.2: stories of the romance and passion paths, the other path locked."""


def test_each_path_has_a_story_on_levels_4_to_10():
    from services.quest_service import PATH_QUESTS, QUESTS, ROUTE_INCLINATION
    for path in ('romance', 'passion'):
        levels = sorted(q['min_level'] for q in PATH_QUESTS.values() if q['path'] == path)
        assert levels == list(range(4, 11))
    for key, q in PATH_QUESTS.items():
        assert key in QUESTS and len(q['routes']) == 2
        for rk in q['routes']:
            assert ROUTE_INCLINATION[(key, rk)] == ('romance' if q['path'] == 'romance' else 'bold')


def test_story_status_locks_the_other_path(monkeypatch):
    from services import quest_service as qs
    monkeypatch.setattr(qs, '_quests_completed', lambda tid: 999)
    monkeypatch.setattr(qs, 'progress', lambda *a, **k: None)
    monkeypatch.setattr(qs, '_branch', lambda tid, cid: 'passion')
    st = {x['key']: x for x in qs.story_status(1, 10, 'anna_01')}
    assert st['pas_dare']['unlocked'] and not st['rom_first_letter']['unlocked']
    assert st['rom_first_letter']['path_ok'] is False and st['morning_routine']['unlocked']
    monkeypatch.setattr(qs, '_branch', lambda tid, cid: None)
    st = {x['key']: x for x in qs.story_status(1, 10, 'anna_01')}
    assert not st['pas_dare']['unlocked'] and not st['rom_first_letter']['unlocked']


def test_app_and_bot_show_the_lock():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    spa = (root / 'webapp' / 'index.html').read_text(encoding='utf-8')
    main = (root / 'main.py').read_text(encoding='utf-8')
    assert 'function storyPathLock(s)' in spa and "story_locked_romance: 'Только на пути романтики'" in spa
    assert "'path_ok': st.get('path_ok', True)" in main and "where = 'на пути романтики'" in main
