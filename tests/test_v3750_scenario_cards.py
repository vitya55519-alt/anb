"""V3.75.0: scenario cards — a looping cover, a role-play setup and one
button into the scene (the Come Closer push the owner showed)."""
import json
import os
from datetime import timedelta
from pathlib import Path

os.environ.setdefault("TELEGRAM_TOKEN", "123456:test-fake-token-for-static-tests-only")

import pytest  # noqa: E402

from services import scenario_cards as sc  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')


@pytest.fixture(autouse=True)
def _fresh_stores(monkeypatch):
    monkeypatch.setattr(sc, '_state', {})
    monkeypatch.setattr(sc, '_covers', {})


def _ages():
    out = {}
    for f in (ROOT / 'data' / 'characters').glob('*.json'):
        d = json.loads(f.read_text(encoding='utf-8'))
        if isinstance(d, dict) and d.get('id'):
            out[d['id']] = d.get('age')
    return out


def test_catalogue_uses_built_in_adult_heroines_only():
    ages = _ages()
    assert len(sc.SCENARIOS) >= 8
    assert len({s.key for s in sc.SCENARIOS}) == len(sc.SCENARIOS)
    for s in sc.SCENARIOS:
        assert s.character_id in ages, s.key
        assert int(ages[s.character_id]) >= 21, s.key
        # no school / minors framing anywhere in a scene
        blob = ' '.join([s.setup, s.her_role, s.his_role, s.place, s.still]).lower()
        for bad in ('школ', 'школьн', 'студентк', 'student', 'school', 'teen', 'подрост'):
            assert bad not in blob, (s.key, bad)


def test_card_fits_telegram_limits():
    for s in sc.SCENARIOS:
        assert len(sc.caption(s, 100)) < 1024
        assert len(f'scnadm:gen:{s.key}'.encode()) <= 64
        assert len(s.button) <= 32
        assert '<blockquote>' in sc.caption(s, 0)


def test_covers_stay_dressed():
    for s in sc.SCENARIOS:
        assert 'stays dressed' in sc.motion_prompt(s)
        assert 'nud' not in s.still.lower() and 'naked' not in s.still.lower()


def test_only_covered_scenes_go_out_and_never_twice():
    allowed = {s.character_id for s in sc.SCENARIOS}
    assert sc.pick_next(1, allowed) is None  # no covers yet → nothing is sent
    sc.set_cover('boss_late', 'FILE1')
    sc.set_cover('gym_after_hours', 'FILE2')
    first = sc.pick_next(1, allowed, current='kate_01')
    assert first.key == 'gym_after_hours'  # his own girl's scene goes first
    sc.mark_sent(1, first.key)
    assert sc.last_sent_at(1) is not None
    second = sc.pick_next(1, allowed, current='kate_01')
    assert second.key == 'boss_late'
    sc.mark_sent(1, second.key)
    assert sc.pick_next(1, allowed) is None


def test_hidden_heroine_is_skipped():
    sc.set_cover('boss_late', 'FILE1')
    assert sc.pick_next(2, {'anna_01'}) is None


def test_start_turns_the_scene_on_for_her_only_and_pays_bonus_once_sent():
    assert sc.start(3, 'boss_late') == {'sent': False, 'bonus_due': False}
    assert sc.active(3, 'vika_01').key == 'boss_late'
    assert sc.active(3, 'anna_01') is None
    line = sc.direction_for(3, 'vika_01', 'Вика')
    assert 'РОЛЕВАЯ СЦЕНА' in line and 'взрослые' in line
    assert sc.direction_for(3, 'anna_01') == ''
    sc.mark_sent(4, 'boss_late')
    assert sc.start(4, 'boss_late')['bonus_due'] is True
    assert sc.stop(4, 'vika_01') is True
    assert sc.active(4, 'vika_01') is None


def test_scene_expires(monkeypatch):
    sc.start(5, 'boss_late')
    later = sc._now() + timedelta(hours=sc.ACTIVE_HOURS + 1)
    monkeypatch.setattr(sc, '_now', lambda: later)
    assert sc.active(5, 'vika_01') is None


def test_wiring():
    # her replies carry the scene; the card opens the app straight into it
    assert 'direction_for(user_id, character_id' in CHAT
    assert "'/webapp/api/scenario/start'" in MAIN
    assert 'async function startScenario' in INDEX and "sp.get('scene')" in INDEX
    assert 'open=chat&scene=' in SCHED
    assert "id='scenario_cards'" in SCHED
    # admin covers: render once, keep Telegram's file_id
    assert "Command('scenes')" in MAIN and 'scnadm:genall' in MAIN
    assert "reason=f'scenario_{scenario.key}'" in MAIN
