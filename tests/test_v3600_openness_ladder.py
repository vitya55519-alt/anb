"""V3.60.0: higher level = she gives in further, no more «это всё фантазии»."""
from services.relationship_engine import INITIATIVE_LADDER, OPENNESS_LADDER, STAGE_ORDER, build_relationship_context
from models.relationship_models import UserCharacterRelationship


def test_every_stage_has_a_rung():
    assert set(OPENNESS_LADDER) == set(STAGE_ORDER)


def test_low_level_teases_high_level_drops_fantasy_framing():
    assert "рано" in OPENNESS_LADDER["stranger"]
    for stage in ("deeply_connected", "committed", "devoted", "soulmate"):
        assert "фантазии" in OPENNESS_LADDER[stage] and "Никаких" in OPENNESS_LADDER[stage] or "без оговорок" in OPENNESS_LADDER[stage]


def test_ladder_reaches_the_prompt_with_limits():
    row = UserCharacterRelationship(stage="committed", relationship_score=0, trust_score=0, intimacy_score=0)
    ctx = build_relationship_context(row)
    assert OPENNESS_LADDER["committed"] in ctx
    assert "только взрослые и только взаимное желание" in ctx


def test_she_starts_it_herself_at_higher_levels():
    assert set(INITIATIVE_LADDER) == set(STAGE_ORDER)
    for stage in ("deeply_connected", "committed"):
        assert "выпрашивать" in INITIATIVE_LADDER[stage]
    row = UserCharacterRelationship(stage="intimate", relationship_score=0, trust_score=0, intimacy_score=0)
    assert INITIATIVE_LADDER["intimate"] in build_relationship_context(row)


def test_explicit_rule_needs_adult_and_level():
    from services.chat_service import EXPLICIT_CHAT_RULE, explicit_chat_line
    assert explicit_chat_line('committed', adult_confirmed=True) == EXPLICIT_CHAT_RULE
    assert explicit_chat_line('committed', adult_confirmed=False) == ''
    assert explicit_chat_line('close', adult_confirmed=True, spicy=True) == ''
    assert explicit_chat_line('intimate', adult_confirmed=True, spicy=True) == EXPLICIT_CHAT_RULE
    assert explicit_chat_line('intimate', adult_confirmed=True) == ''
    assert 'только взрослые' in EXPLICIT_CHAT_RULE and 'согласие' in EXPLICIT_CHAT_RULE


def test_admin_test_level_gets_the_ladder():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / 'services' / 'chat_service.py').read_text(encoding='utf-8')
    assert "OPENNESS_LADDER.get(test_stage, '')" in src
    assert 'explicit_chat_line(test_stage or rel_stage' in src
