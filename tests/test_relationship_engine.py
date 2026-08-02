from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.waifu_models import Base
from services.relationship_engine import (
    RelationshipDelta,
    apply_delta,
    calculate_stage,
)

# Import so SQLAlchemy registers the tables before create_all.
from models.relationship_models import RelationshipEvent, UserCharacterRelationship  # noqa: F401


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_stage_requires_multiple_dimensions():
    assert calculate_stage(90, 90, 20) == "close"
    assert calculate_stage(70, 60, 40) == "intimate"
    assert calculate_stage(90, 90, 70) == "deeply_connected"


def test_deltas_are_bounded_and_audited():
    session = make_session()
    row = apply_delta(
        session,
        user_id=1,
        character_id="anna_01",
        delta=RelationshipDelta(
            relationship=99,
            trust=99,
            intimacy=99,
            event_type="positive_interaction",
            reason="test",
        ),
    )
    assert row.relationship_score == 3
    assert row.trust_score == 3
    assert row.intimacy_score == 3
    assert session.query(RelationshipEvent).count() == 1


def test_committed_stage_requires_all_dimensions():
    assert calculate_stage(90, 85, 80) == "committed"
    assert calculate_stage(100, 100, 79) == "deeply_connected"
