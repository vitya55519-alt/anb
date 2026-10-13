"""V3.60.0: higher level = she gives in further, no more «это всё фантазии»."""
from services.relationship_engine import OPENNESS_LADDER, STAGE_ORDER, build_relationship_context
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
