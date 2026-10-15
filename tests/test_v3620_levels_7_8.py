"""V3.61.9: levels 7-8 give something real — perks, premium teaser, scenes."""
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def _row(stage, **kw):
    base = dict(stage=stage, relationship_score=91, trust_score=86, intimacy_score=81,
                familiarity_score=66, continuity_score=36, connection_score=36,
                total_messages=500, id=None, path_axis=0.0,
                first_interaction_at=datetime.utcnow() - timedelta(days=9))
    base.update(kw)
    return SimpleNamespace(**base)


def test_free_user_at_six_sees_premium_teaser():
    from services.relationship_engine import level_snapshot
    snap = level_snapshot(None, _row('committed'), premium=False)
    assert snap['premium_needed'] is True
    assert snap['next_perks'] and 'прозвищ' in snap['next_perks'][0]


def test_premium_user_progresses_normally_and_sees_perks_at_seven():
    from services.relationship_engine import level_snapshot
    snap = level_snapshot(None, _row('committed'), premium=True)
    assert snap['premium_needed'] is False and snap['bars']
    at7 = level_snapshot(None, _row('devoted'), premium=True)
    assert at7['perks'] and at7['next_perks'] and at7['days_together'] == 10
    top = level_snapshot(None, _row('eternal'), premium=True)  # V3.62.0: level 10 is the top
    assert top['perks'] and not top['next_perks']


def test_chat_voice_changes_at_seven_and_eight():
    from services.relationship_engine import build_relationship_context
    seven = build_relationship_context(_row('devoted'), character_id='anna_01')
    eight = build_relationship_context(_row('soulmate'), character_id='anna_01')
    assert 'вместе уже 10' in seven and 'прозвище' in seven
    assert 'живёте вместе' in eight


def test_level_up_scenes_for_seven_and_eight():
    src = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert 'LEVEL_UP_SCENES = {' in src and "'soulmate': (" in src
    assert 'engagement ring' in src
    assert 'premium=premium, taken=taken)' in src
    spa = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
    assert "id=\"lvlPremium\"" in spa or "id=\\\"lvlPremium\\\"" in spa or 'lvlPremium' in spa
    assert 'j.next_title && !j.premium_needed' in spa


def test_taken_girl_gets_secret_romance_not_a_ring():
    from services.relationship_engine import level_snapshot, build_relationship_context
    snap = level_snapshot(None, _row('devoted'), premium=True, taken=True)
    assert any('тайное место' in p for p in snap['next_perks'])
    eight = build_relationship_context(_row('soulmate'), character_id='anna_01', marital='mar_married')
    assert 'тайное место' in eight and 'живёте вместе' not in eight
    src = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert 'LEVEL_UP_SCENES_TAKEN = {' in src and 'no ring on her fingers' in src
    svc = (ROOT / 'services' / 'relationship_service.py').read_text(encoding='utf-8')
    assert '_marital(user_id, character_id)' in svc


def test_switching_to_free_on_7_8_is_a_scene():
    src = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert 'async def _left_him_scene(' in src
    assert "_eff_new in ('mar_single', 'mar_divorced')" in src
    assert 'a small suitcase beside her' in src and "'left_him': bool(left_him)" in src
