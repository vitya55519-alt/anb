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
    assert len(sc.SCENARIOS) >= 6
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
    sc.set_cover('office_brat', 'FILE1')
    sc.set_cover('night_shift', 'FILE2')
    first = sc.pick_next(1, allowed, current='nika_01')
    assert first.key == 'night_shift'  # his own girl's scene goes first
    sc.mark_sent(1, first.key)
    assert sc.last_sent_at(1) is not None
    second = sc.pick_next(1, allowed, current='nika_01')
    assert second.key == 'office_brat'
    sc.mark_sent(1, second.key)
    assert sc.pick_next(1, allowed) is None


def test_hidden_heroine_is_skipped():
    sc.set_cover('office_brat', 'FILE1')
    assert sc.pick_next(2, {'anna_01'}) is None


def test_start_turns_the_scene_on_for_her_only_and_pays_bonus_once_sent():
    assert sc.start(3, 'office_brat') == {'sent': False, 'bonus_due': False}
    assert sc.active(3, 'diana_01').key == 'office_brat'
    assert sc.active(3, 'anna_01') is None
    line = sc.direction_for(3, 'diana_01', 'Диана')
    assert 'РОЛЕВАЯ СЦЕНА' in line and 'взрослые' in line
    assert sc.direction_for(3, 'anna_01') == ''
    sc.mark_sent(4, 'office_brat')
    assert sc.start(4, 'office_brat')['bonus_due'] is True
    assert sc.stop(4, 'diana_01') is True
    assert sc.active(4, 'diana_01') is None


def test_scene_expires(monkeypatch):
    sc.start(5, 'office_brat')
    later = sc._now() + timedelta(hours=sc.ACTIVE_HOURS + 1)
    monkeypatch.setattr(sc, '_now', lambda: later)
    assert sc.active(5, 'diana_01') is None


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


# ── V3.76.0: every card brings a new girl ───────────────────────────────────

POOLS = ['MORNING_MESSAGES', 'EVENING_MESSAGES', 'MISS_TEXTS', 'JEALOUSY_TEXTS',
         'CLIFFHANGER_TEXTS', 'GIFT_MESSAGES', 'STORY_TEMPLATES', 'MINI_QUESTS', 'WEEKLY_DATES']


def _block(rel, start):
    return (ROOT / rel).read_text(encoding='utf-8').split(start, 1)[1].split('\n}', 1)[0]


def test_card_girls_are_new_and_fully_registered():
    old = {'anna_01', 'alena_01', 'maria_01', 'erika_01', 'sonya_01', 'vika_01', 'alisa_01', 'mila_01',
           'kate_01', 'sasha_01', 'rex_01', 'violetta_01', 'darina_01', 'eva_01', 'romina_01',
           'kristina_01', 'zlata_01', 'veronika_01'}
    assert not (sc.SCENARIO_GIRLS & old)
    for cid in sc.SCENARIO_GIRLS:
        data = json.loads((ROOT / 'data' / 'characters' / f'{cid}.json').read_text(encoding='utf-8'))
        assert data['is_adult'] is True and data['age'] >= 21
        assert data['boundaries']['no_nudity_generation'] is True
        assert f'"{cid}":' in _block('services/character_card_service.py', 'DEFAULT_CARDS = {')
        assert f'"{cid}":' in _block('services/character_card_service.py', 'SCENARIO_HOOKS = {')
        assert f'"{cid}":' in _block('services/character_card_service.py', 'OPENING_SCENES = {')
        assert f"'{cid}':" in _block('services/webapp_service.py', '_FACE_REFERENCES = {')
        assert f"'{cid}':" in _block('services/relationship_engine.py', 'CHARACTER_PACE = {')
        assert f"'{cid}':" in _block('services/relationship_engine.py', 'PACE_HINTS = {')
        assert f"'{cid}':" in _block('services/photo_service.py', 'BODY_SPECS = {')
        assert f"'{cid}':" in _block('services/voice_service.py', 'GEMINI_TTS_VOICES = {')
        assert f"'{cid}':" in _block('services/voice_samples.py', 'VOICE_SAMPLES')
        assert f"'{cid}':" in _block('services/daily_life.py', 'ROUTINES')
        for pool in POOLS:
            assert f"'{cid}': [" in _block('services/retention_features_service.py', f'{pool} = {{'), (cid, pool)


def test_card_girl_references_exist():
    for cid in sc.SCENARIO_GIRLS:
        f = cid.replace('_01', '')
        assert (ROOT / 'data' / 'references' / f / f'00_{f}_canonical_face.png').exists(), cid
        assert (ROOT / 'data' / 'references' / f / f'01_{f}_canonical_look.png').exists(), cid


def test_card_girls_unlock_with_their_card():
    assert sc.unlocked(7, 'anna_01') is True
    assert sc.unlocked(7, 'nika_01') is False
    sc.mark_sent(7, 'night_shift')
    assert sc.unlocked(7, 'nika_01') is True
    sc.start(8, 'party_ride')
    assert sc.unlocked(8, 'ksyusha_01') is True
    webapp = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
    assert 'scenario_cards.unlocked(telegram_id' in webapp
    assert 'if card.character_id in SCENARIO_GIRLS' in MAIN


def test_card_girls_are_semi_realistic_and_their_photos_need_premium():
    from services import photo_service
    # owner's pick: all card girls in the competitor's «drawn photo» look
    assert {photo_service.art_style(cid) for cid in sc.SCENARIO_GIRLS} == {'semi'}
    out = photo_service.apply_art_style('Photorealistic smartphone photo, natural skin texture', 'nika_01')
    assert out.startswith('ART STYLE') and 'semi-realistic' in out and 'Photorealistic' not in out
    assert photo_service.apply_art_style('Photorealistic', 'anna_01') == 'Photorealistic'
    for s in sc.SCENARIOS:
        assert 'ART STYLE' in sc.still_prompt(s)
    assert "return 'premium'" in MAIN and '_card_girl_photo_locked(character_id, telegram_id)' in MAIN
    assert "j.photo_block === 'premium'" in INDEX
