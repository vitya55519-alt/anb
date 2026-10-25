from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_testlevel_7_to_10_build_a_chat_context_on_the_passion_path():
    from types import SimpleNamespace
    from services.relationship_engine import build_relationship_context, BRANCH_TONE
    for stage in ('devoted', 'soulmate', 'voyage', 'eternal'):
        row = SimpleNamespace(stage=stage, branch='passion', relationship_score=60.0, trust_score=60.0,
                              intimacy_score=80.0, path_axis=60.0, first_interaction_at=None)
        ctx = build_relationship_context(row, None, 'anna_01', '')
        assert BRANCH_TONE['passion'][stage] in ctx


def test_chat_test_mode_has_no_level_1_6_table():
    src = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
    assert 'stage_prompts[test_stage]' not in src
    assert "'eternal':10" in src


def test_testlevel_accepts_7_of_10():
    src = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert "m = re.search(r'\\d+', arg)" in src


def test_own_path_shows_level_perks():
    spa = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
    assert "(x.perks && x.perks.length ? '<span class=\"pp\">' + (x.state === 'other' || x.state === 'choose'" in spa
