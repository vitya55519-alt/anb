"""V3.55.6 functional checks — premium level-6 floor + persona_style.

In-memory sqlite (same pattern as test_v3555): DATABASE_URL is set before
services.db import, so every service shares one throwaway pool. The floor is
driven through the registered provider callback, exactly like production:
tests flip the provider, never the engine internals."""
import os

os.environ.setdefault("TELEGRAM_TOKEN", "123456:test-fake-token-only")
os.environ.setdefault("GEMINI_API_KEY", "test-local-only")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402

from services.db import engine, SessionLocal  # noqa: E402
from models.waifu_models import Base  # noqa: E402
from models.relationship_models import UserCharacterRelationship  # noqa: E402
from services import relationship_engine as reng  # noqa: E402
from services.relationship_engine import (  # noqa: E402
    RelationshipDelta, apply_delta, apply_premium_floor, set_premium_floor_provider,
)

Base.metadata.create_all(engine)

UID = 99160001
CHAR = 'v3556_premium_girl'


@pytest.fixture(autouse=True)
def _clean_rows():
    set_premium_floor_provider(None)
    yield
    set_premium_floor_provider(None)
    with SessionLocal() as s:
        s.query(UserCharacterRelationship).filter(
            UserCharacterRelationship.user_id == UID
        ).delete()
        s.commit()


def _row():
    with SessionLocal() as s:
        return s.scalar(select(UserCharacterRelationship).where(
            UserCharacterRelationship.user_id == UID,
            UserCharacterRelationship.character_id == CHAR,
        ))


def test_floor_lifts_new_pair_to_committed():
    set_premium_floor_provider(lambda uid, cid: uid == UID and cid == CHAR)
    with SessionLocal() as s:
        row = apply_premium_floor(s, UID, CHAR)
    assert row is not None
    assert row.stage == 'committed'
    assert (row.relationship_score, row.trust_score, row.intimacy_score) == (90.0, 85.0, 80.0)
    assert (row.familiarity_score, row.continuity_score, row.connection_score) == (65.0, 35.0, 35.0)


def test_floor_skipped_without_provider():
    # no provider registered -> no row is even created
    assert apply_premium_floor(SessionLocal(), UID, CHAR) is None


def test_floor_is_idempotent_and_never_demotes():
    set_premium_floor_provider(lambda uid, cid: True)
    with SessionLocal() as s:
        apply_premium_floor(s, UID, CHAR)
    with SessionLocal() as s:
        row = s.scalar(select(UserCharacterRelationship).where(
            UserCharacterRelationship.user_id == UID,
            UserCharacterRelationship.character_id == CHAR,
        ))
        row.stage = 'soulmate'  # a higher real level must survive the floor
        s.commit()
    with SessionLocal() as s:
        again = apply_premium_floor(s, UID, CHAR)
        first_scores = (again.relationship_score, again.familiarity_score)
        again2 = apply_premium_floor(s, UID, CHAR)
        assert again2.relationship_score == first_scores[0]
    assert again2.stage == 'soulmate'


def test_negative_deltas_cannot_sink_below_the_floor():
    set_premium_floor_provider(lambda uid, cid: True)
    with SessionLocal() as s:
        apply_premium_floor(s, UID, CHAR)
    for _ in range(3):
        with SessionLocal() as s:
            apply_delta(s, UID, CHAR, RelationshipDelta(
                relationship=-5, trust=-5, intimacy=-5,
                event_type='negative_interaction', reason='test',
            ))
    row = _row()
    assert row.stage == 'committed'
    assert row.relationship_score >= 90.0
    assert row.trust_score >= 85.0
    assert row.intimacy_score >= 80.0


def test_free_user_keeps_the_normal_ladder():
    set_premium_floor_provider(lambda uid, cid: False)
    with SessionLocal() as s:
        apply_delta(s, UID, CHAR, RelationshipDelta(relationship=1, trust=1, intimacy=1))
    row = _row()
    assert row.stage in ('stranger', 'acquaintance')
    assert row.relationship_score < 90.0


def test_persona_style_roundtrip():
    set_premium_floor_provider(lambda uid, cid: True)
    with SessionLocal() as s:
        row = apply_premium_floor(s, UID, CHAR)
        assert row.persona_style is None
        row.persona_style = 'tender'
        s.commit()
    assert _row().persona_style == 'tender'
