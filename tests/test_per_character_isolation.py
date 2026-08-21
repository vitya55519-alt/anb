"""Regression test: relationship progress is isolated per character.

Before the fix, record_user_message / get_relationship_level hardcoded
CHARACTER_ID (Anna), so every character's relationship wrote to Anna's row and
Emily never advanced independently. This test proves Anna and Emily get
separate, independent relationship rows and levels.
"""
import os

# Config validates these env vars at import time; set fakes before importing.
os.environ.setdefault("TELEGRAM_TOKEN", "123456:test-fake-token-for-static-tests-only")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-for-static-tests-only")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import asyncio  # noqa: E402

from models.waifu_models import Base  # noqa: E402
from models.relationship_models import UserCharacterRelationship  # noqa: E402
from services.db import engine, SessionLocal  # noqa: E402
from services.relationship_service import record_user_message, get_context  # noqa: E402
from services.photo_service import get_relationship_level, get_relationship_stage  # noqa: E402
from services.user_service import ensure_user  # noqa: E402

ANNA = "anna_01"
EMILY = "alena_01"
TID = 999111


def setup_module(_module):
    Base.metadata.create_all(engine)


def _cleanup_user():
    """Delete only the Emily relationship row for our test user, so a pre-existing
    Emily row left in the shared in-memory DB by other tests can't make the
    `emily_row is None` assertion fail. Anna's row is intentionally left intact
    because test 2 builds on the Anna progress created in test 1."""
    uid = ensure_user(TID, "tester")
    with SessionLocal() as s:
        s.query(UserCharacterRelationship).filter_by(
            user_id=uid, character_id=EMILY).delete(synchronize_session=False)
        s.commit()


def _record(character_id: str, times: int = 6) -> None:
    loop = asyncio.new_event_loop()
    try:
        for _ in range(times):
            loop.run_until_complete(
                record_user_message(
                    TID, "tester",
                    relationship=99, trust=99, intimacy=99,
                    event_type="interaction", reason="test",
                    character_id=character_id,
                )
            )
    finally:
        loop.close()


def test_anna_progress_is_isolated_from_emily():
    _cleanup_user()
    uid = ensure_user(TID, "tester")
    # Record several positive interactions for Anna only.
    _record(ANNA, times=6)

    with SessionLocal() as s:
        anna_row = s.query(UserCharacterRelationship).filter_by(
            user_id=uid, character_id=ANNA).first()
        emily_row = s.query(UserCharacterRelationship).filter_by(
            user_id=uid, character_id=EMILY).first()

    # Anna has a relationship row with real progress; Emily has none yet.
    assert anna_row is not None
    assert anna_row.relationship_score > 0
    assert emily_row is None

    # Anna advanced strictly beyond Emily (who is still a stranger / level 1).
    anna_level = get_relationship_level(TID, ANNA)
    emily_level = get_relationship_level(TID, EMILY)
    assert anna_level > 1
    assert emily_level == 1
    assert get_relationship_stage(TID, ANNA) != "stranger"
    assert get_relationship_stage(TID, EMILY) == "stranger"


def test_emily_progresses_independently_after_anna():
    _cleanup_user()
    uid = ensure_user(TID, "tester")
    anna_before = get_relationship_level(TID, ANNA)

    # Now talk to Emily — she should start her own separate row from scratch.
    _record(EMILY, times=6)

    with SessionLocal() as s:
        emily_row = s.query(UserCharacterRelationship).filter_by(
            user_id=uid, character_id=EMILY).first()
        anna_row = s.query(UserCharacterRelationship).filter_by(
            user_id=uid, character_id=ANNA).first()

    assert emily_row is not None
    assert emily_row.relationship_score > 0
    # Anna's row must be untouched by Emily's interactions.
    assert anna_row.relationship_score > 0
    assert get_relationship_level(TID, ANNA) == anna_before
    assert get_relationship_level(TID, EMILY) > 1


def test_get_context_uses_active_character():
    # get_context must read the requested character's row, not a hardcoded one.
    loop = asyncio.new_event_loop()
    try:
        anna_ctx = loop.run_until_complete(get_context(TID, character_id=ANNA))
        emily_ctx = loop.run_until_complete(get_context(TID, character_id=EMILY))
    finally:
        loop.close()
    assert anna_ctx and "stranger" not in anna_ctx
    assert emily_ctx and "stranger" not in emily_ctx
