"""Regression test for streak credit rewards + referral contest leaderboard.

Streak rewards must be granted exactly once per milestone (idempotent), and the
referral leaderboard must rank inviters correctly within the period.

Uses the shared in-memory engine (same pattern as test_per_character_isolation)
with unique telegram IDs and cleans up its own rows so it never pollutes the
shared DB for other tests.
"""
import os

# Match the isolation test's setup exactly: in-memory DB, fakes before import.
os.environ.setdefault("TELEGRAM_TOKEN", "123456:test-fake-token-for-static-tests-only")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-for-static-tests-only")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from datetime import timedelta, datetime, timezone  # noqa: E402
from sqlalchemy import select  # noqa: E402
from models.waifu_models import Base  # noqa: E402
from services.db import engine, SessionLocal  # noqa: E402

Base.metadata.create_all(engine)

from models.app_models import ProductEvent, StarTransaction, User  # noqa: E402
from services.user_service import ensure_user  # noqa: E402
from services.payments import grant_photo_credits, get_photo_credits  # noqa: E402
from services.gamification_service import touch_activity  # noqa: E402
from services.referral_service import referral_leaderboard, referral_rank  # noqa: E402

# Unique IDs (no collision with test_per_character_isolation's 999111).
TID = 999555
INV_A, INV_B, INV_C = 77001, 77002, 77003


def _set_streak(telegram_id: int, streak: int, last_date):
    with SessionLocal() as s:
        u = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        assert u is not None
        u.streak_count = streak
        u.streak_last_date = last_date
        s.commit()


def _cleanup():
    """Remove every row this test created so the shared DB stays clean."""
    with SessionLocal() as s:
        s.query(ProductEvent).delete()
        s.query(StarTransaction).delete()
        s.query(User).filter(User.telegram_id.in_(
            [str(TID), str(INV_A), str(INV_B), str(INV_C)])).delete(synchronize_session=False)
        s.commit()


def test_streak_rewards_and_contest():
    """Streak milestone credits are idempotent; leaderboard ranks inviters."""
    try:
        ensure_user(TID, "streaker")

        # Day 3 milestone: 2-day streak ending yesterday -> one message today
        # bumps streak to 3 and grants the day-3 reward exactly once.
        yesterday = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
        _set_streak(TID, 2, yesterday)

        gam = touch_activity(TID)
        assert gam["streak_count"] == 3, gam
        assert gam.get("streak_reward_credits") == 1, gam
        assert get_photo_credits(TID) == 1, get_photo_credits(TID)

        # Same-day repeat must NOT re-grant (new_streak_day is False -> skipped).
        again = touch_activity(TID)
        assert not again.get("streak_reward_credits"), again
        assert get_photo_credits(TID) == 1, get_photo_credits(TID)
        print("PASS streak milestone idempotency, credits:", get_photo_credits(TID))

        # Day 7 milestone: streak 6 ending yesterday -> 7 -> grant day-7 reward (2 credits).
        _set_streak(TID, 6, yesterday)
        gam7 = touch_activity(TID)
        assert gam7["streak_count"] == 7, gam7
        assert gam7.get("streak_reward_credits") == 2, gam7
        assert get_photo_credits(TID) == 3, get_photo_credits(TID)
        print("PASS day-7 milestone reward, credits:", get_photo_credits(TID))

        # --- Referral leaderboard ---
        inviter_a = ensure_user(INV_A, "Alpha")
        inviter_b = ensure_user(INV_B, "Beta")
        inviter_c = ensure_user(INV_C, "Gamma")

        def add_converted(uid, n):
            with SessionLocal() as s:
                for _ in range(n):
                    s.add(ProductEvent(user_id=uid, event_name="referral_converted", value=0.0))
                s.commit()

        add_converted(inviter_b, 3)
        add_converted(inviter_a, 2)
        add_converted(inviter_c, 1)

        board = referral_leaderboard(limit=10, period_days=30)
        assert len(board) == 3, board
        assert board[0]["name"] == "Beta" and board[0]["count"] == 3, board
        assert board[1]["name"] == "Alpha" and board[1]["count"] == 2, board
        assert board[2]["name"] == "Gamma" and board[2]["count"] == 1, board
        print("PASS leaderboard order:", [(r["name"], r["count"]) for r in board])

        assert referral_rank(INV_B, period_days=30) == (1, 3), referral_rank(INV_B, period_days=30)
        assert referral_rank(INV_C, period_days=30) == (3, 3), referral_rank(INV_C, period_days=30)
        assert referral_rank(999999, period_days=30) == (0, 3)
        print("PASS referral_rank lookups")

        print("ALL PASS")
    finally:
        _cleanup()
