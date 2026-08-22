from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func

from services.db import SessionLocal
from services.user_service import ensure_user, get_user
from services.analytics_service import track_event
from models.app_models import User, ProductEvent
from config import (
    REFERRAL_REFERRER_CREDITS,
    REFERRAL_INVITEE_CREDITS,
    FIRST_START_BONUS_CREDITS,
    FIRST_START_PREMIUM_TRIAL_DAYS,
)

logger = logging.getLogger(__name__)

# Per-user lock guards against double-granting a bonus/referral on rapid
# concurrent /start re-entries or parallel background jobs. It is coarse
# (process-local) but sufficient for a single-worker Railway deployment.
_bonus_locks: dict[int, asyncio.Lock] = {}


def _user_lock(telegram_id: int) -> asyncio.Lock:
    lock = _bonus_locks.get(telegram_id)
    if lock is None:
        lock = asyncio.Lock()
        _bonus_locks[telegram_id] = lock
    return lock


# Public alias used by main.py handlers to guard referral/bonus application.
referral_user_lock = _user_lock


# In-memory bridge between /start (which sees the deep-link payload) and
# consent_accept (which should actually grant the bonus). Cleared once the
# invitee accepts 18+/terms or after a short TTL. This is intentionally
# in-memory only: if the worker restarts mid-onboarding the user can simply
# tap /start again to re-open the deep link, so no persistent record is needed.
_pending_referrals: dict[int, tuple[int, float]] = {}
_PENDING_TTL_SECONDS = 30 * 60


def remember_referral(invitee_telegram_id: int, referrer_telegram_id: int) -> None:
    """Stash the referrer id from the deep-link payload until consent is accepted."""
    if invitee_telegram_id == referrer_telegram_id:
        return
    _pending_referrals[invitee_telegram_id] = (referrer_telegram_id, _now().timestamp())


def pending_referral(invitee_telegram_id: int) -> int | None:
    """Return a still-valid pending referrer id, or None if expired/absent."""
    entry = _pending_referrals.pop(invitee_telegram_id, None)
    if not entry:
        return None
    referrer_id, created_at_ts = entry
    if _now().timestamp() - created_at_ts > _PENDING_TTL_SECONDS:
        return None
    return referrer_id

# How fresh User.created_at must be for this /start to count as the user's
# very first contact with the bot. ensure_user() creates the row on first
# contact and referral/bonus processing runs synchronously right after, so a
# short window is enough and avoids re-granting bonuses to returning users.
_NEW_USER_WINDOW = timedelta(minutes=5)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_referral_payload(args: str | None) -> int | None:
    """Extract a referrer telegram id from the /start deep-link payload.

    Supported formats: `ref_<id>`, `ref-<id>`, `ref<id>`, or a bare numeric id.
    Returns None when the payload is empty or not a referral link.
    """
    if not args:
        return None
    args = args.strip()
    if args.lower().startswith("ref"):
        payload = args[3:].lstrip("_-")
        if payload.isdigit():
            return int(payload)
    if args.isdigit():
        return int(args)
    return None


def _is_freshly_created(telegram_id: int) -> bool:
    uid = ensure_user(telegram_id)
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.id == uid))
        if not user or not user.created_at:
            return False
        return _now() - user.created_at <= _NEW_USER_WINDOW


def _event_count(uid: int, event_name: str) -> int:
    with SessionLocal() as s:
        return int(s.scalar(
            select(func.count()).select_from(ProductEvent).where(
                ProductEvent.user_id == uid,
                ProductEvent.event_name == event_name,
            )
        ) or 0)


def apply_first_start_bonuses(telegram_id: int) -> dict:
    """Grant the welcome bonus to a brand-new user, once.

    Grants FIRST_START_BONUS_CREDITS photo credits (default 2) so the user
    can generate a photo immediately without paying, and optionally
    FIRST_START_PREMIUM_TRIAL_DAYS of Premium (default 0 = disabled).
    Idempotent: guarded by the `first_start_bonus` ProductEvent.
    """
    uid = ensure_user(telegram_id)

    if _event_count(uid, "first_start_bonus") > 0:
        return {"credits": 0, "trial_days": 0, "already_granted": True}

    if not _is_freshly_created(telegram_id):
        # Existing user re-running /start: no bonus, no event recorded so a
        # genuinely new signup later is never blocked by this check.
        return {"credits": 0, "trial_days": 0, "already_granted": False}

    granted_credits = 0
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.id == uid))
        if not user:
            return {"credits": 0, "trial_days": 0, "already_granted": False}
        if FIRST_START_BONUS_CREDITS > 0:
            user.photo_credits = (user.photo_credits or 0) + FIRST_START_BONUS_CREDITS
            granted_credits = FIRST_START_BONUS_CREDITS
        # Idempotency marker is recorded in the SAME transaction as the credit
        # grant, so a crash between credit update and analytics event can't
        # leave the user without their bonus (or with a doubled one).
        s.add(ProductEvent(
            user_id=uid,
            event_name="first_start_bonus",
            value=float(granted_credits),
            metadata_json=__import__("json").dumps({"credits": granted_credits}, ensure_ascii=False),
        ))
        s.commit()

    track_event(uid, "first_start_bonus", value=float(granted_credits), metadata={"credits": granted_credits})

    granted_trial_days = 0
    if FIRST_START_PREMIUM_TRIAL_DAYS > 0:
        from services.payments import grant_premium
        if grant_premium(telegram_id, days=FIRST_START_PREMIUM_TRIAL_DAYS):
            granted_trial_days = FIRST_START_PREMIUM_TRIAL_DAYS

    return {"credits": granted_credits, "trial_days": granted_trial_days, "already_granted": False}


def apply_referral(invitee_telegram_id: int, referrer_telegram_id: int) -> dict:
    """Record a referral and grant bonuses to both sides, once per invitee.

    Guards: no self-referral, no double-crediting an invitee, only genuinely
    new invitees trigger a payout.
    """
    if invitee_telegram_id == referrer_telegram_id:
        return {"status": "self_referral", "awarded": False}

    referrer_user = get_user(referrer_telegram_id)
    if not referrer_user:
        return {"status": "unknown_referrer", "awarded": False}

    invitee_uid = ensure_user(invitee_telegram_id)

    if _event_count(invitee_uid, "referral_invited") > 0:
        return {"status": "already_referred", "awarded": False}

    if not _is_freshly_created(invitee_telegram_id):
        return {"status": "not_new", "awarded": False}

    referrer_uid = referrer_user.id
    import json as _json
    with SessionLocal() as s:
        invitee = s.scalar(select(User).where(User.id == invitee_uid))
        referrer = s.scalar(select(User).where(User.id == referrer_uid))
        if not invitee or not referrer:
            return {"status": "user_missing", "awarded": False}
        if REFERRAL_INVITEE_CREDITS > 0:
            invitee.photo_credits = (invitee.photo_credits or 0) + REFERRAL_INVITEE_CREDITS
        if REFERRAL_REFERRER_CREDITS > 0:
            referrer.photo_credits = (referrer.photo_credits or 0) + REFERRAL_REFERRER_CREDITS
        # Record the idempotency marker in the SAME transaction as the credit
        # grants, so a crash after the commit to credits but before the analytics
        # event can never result in a double-grant on a retried /start.
        s.add(ProductEvent(
            user_id=invitee_uid,
            event_name="referral_invited",
            value=float(REFERRAL_INVITEE_CREDITS),
            metadata_json=_json.dumps({"referrer_telegram_id": str(referrer_telegram_id)}, ensure_ascii=False),
        ))
        s.commit()

    track_event(referrer_uid, "referral_converted", value=float(REFERRAL_REFERRER_CREDITS),
                metadata={"invitee_telegram_id": str(invitee_telegram_id)})

    logger.info(
        "referral awarded referrer=%s invitee=%s referrer_credits=%s invitee_credits=%s",
        referrer_telegram_id, invitee_telegram_id, REFERRAL_REFERRER_CREDITS, REFERRAL_INVITEE_CREDITS,
    )
    return {
        "status": "awarded",
        "awarded": True,
        "referrer_credits": REFERRAL_REFERRER_CREDITS,
        "invitee_credits": REFERRAL_INVITEE_CREDITS,
    }


def referral_count(telegram_id: int) -> int:
    uid = ensure_user(telegram_id)
    return _event_count(uid, "referral_converted")


def referral_leaderboard(limit: int = 10, period_days: int | None = 30):
    """Top inviters by converted referrals within the period (default: last 30 days).
    period_days=None means all-time. Returns list of dicts: rank, telegram_id,
    name, count. Used by the /contest command for the monthly referral race.
    """
    cutoff = None
    if period_days is not None:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=period_days)
    with SessionLocal() as s:
        q = (
            select(
                ProductEvent.user_id,
                func.count().label("cnt"),
            )
            .where(ProductEvent.event_name == "referral_converted")
            .group_by(ProductEvent.user_id)
            .order_by(func.count().desc())
        )
        if cutoff is not None:
            q = q.where(ProductEvent.created_at >= cutoff)
        rows = s.execute(q.limit(limit)).all()
        # Resolve names in one pass.
        uids = [r[0] for r in rows]
        names: dict[int, str] = {}
        tgids: dict[int, str] = {}
        if uids:
            for u in s.scalars(select(User).where(User.id.in_(uids))).all():
                names[u.id] = u.name or "ты"
                tgids[u.id] = u.telegram_id
        return [
            {
                "rank": idx + 1,
                "telegram_id": int(tgids.get(r[0], "0")) if r[0] in tgids else 0,
                "name": names.get(r[0], "ты"),
                "count": int(r[1]),
            }
            for idx, r in enumerate(rows)
        ]


def referral_rank(telegram_id: int, period_days: int | None = 30) -> tuple[int, int]:
    """Return (rank, total_inviters) for the given user in the period. rank=0 if none."""
    board = referral_leaderboard(limit=100000, period_days=period_days)
    total = len(board)
    uid = ensure_user(telegram_id)
    for i, row in enumerate(board, 1):
        if row["telegram_id"] == int(telegram_id):
            return i, total
    return 0, total


def referral_link(bot_username: str, telegram_id: int) -> str:
    return f"https://t.me/{bot_username}?start=ref_{telegram_id}"


def _converted_in_window(start: datetime, end: datetime) -> list[tuple[int, int]]:
    """Return (telegram_id, converted_count) for referral_converted events in [start, end), best first."""
    with SessionLocal() as s:
        rows = s.execute(
            select(ProductEvent.user_id, func.count().label("cnt"))
            .where(
                ProductEvent.event_name == "referral_converted",
                ProductEvent.created_at >= start,
                ProductEvent.created_at < end,
            )
            .group_by(ProductEvent.user_id)
            .order_by(func.count().desc())
        ).all()
        uids = [r[0] for r in rows if r[0] is not None]
        tgids: dict[int, str] = {}
        if uids:
            for u in s.scalars(select(User).where(User.id.in_(uids))).all():
                tgids[u.id] = u.telegram_id
    return [
        (int(tgids[r[0]]), int(r[1]))
        for r in rows
        if r[0] in tgids and int(r[1] or 0) > 0
    ]


def settle_monthly_contest(top_n: int = 3, premium_days: int = 30) -> dict:
    """Grant Premium to the top inviters of the previous calendar month, once.

    Idempotent via a `contest_settled` marker event carrying the month key, so
    repeated /contest calls or worker restarts never double-grant. Called from
    /contest; the grant itself is the existing grant_premium() admin path.
    """
    import json as _json
    now = _now()
    first_of_this_month = now.date().replace(day=1)
    end = datetime.combine(first_of_this_month, datetime.min.time())
    start = (end - timedelta(days=1)).replace(day=1)
    month_key = start.strftime("%Y-%m")

    with SessionLocal() as s:
        already = int(s.scalar(
            select(func.count()).select_from(ProductEvent).where(
                ProductEvent.event_name == "contest_settled",
                ProductEvent.metadata_json.like(f'%"month": "{month_key}"%'),
            )
        ) or 0)
        if already:
            return {"month": month_key, "already_settled": True, "winners": []}

    winners = _converted_in_window(start, end)[:top_n]
    granted: list[dict] = []
    if winners:
        from services.payments import grant_premium
    for telegram_id, count in winners:
        try:
            if grant_premium(telegram_id, days=premium_days):
                granted.append({"telegram_id": str(telegram_id), "count": count})
        except Exception:
            logger.exception("contest premium grant failed user=%s month=%s", telegram_id, month_key)

    with SessionLocal() as s:
        s.add(ProductEvent(
            user_id=None,
            event_name="contest_settled",
            value=float(len(granted)),
            metadata_json=_json.dumps({"month": month_key, "winners": granted}, ensure_ascii=False),
        ))
        s.commit()

    logger.info("contest settled month=%s winners=%s", month_key, granted)
    return {"month": month_key, "already_settled": False, "winners": granted}
