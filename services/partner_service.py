"""V3.37.0: the money affiliate («партнёрка») program.

A referred user is linked to their referrer forever (models.Referral). Every
payment that user makes — Stars or rubles — accrues a percent commission into
the referrer's partner ledger (models.PartnerTransaction, kind='commission').
Once the balance reaches PARTNER_MIN_PAYOUT_RUB the partner can request a
withdrawal: a 'payout' row in status 'pending' is created, the owner gets an
admin message with confirm/reject buttons, and the balance is settled when the
owner marks the payout paid (or cancelled — which refunds the balance).

The whole flow is idempotent:
- commissions are keyed by the unique payment charge id, so a retried
  Stars payment / FreeKassa webhook can never double-credit;
- only one 'pending' payout per user can exist at a time;
- marking a payout paid/cancelled is a single guarded transition.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from config import (
    PARTNER_ENABLED,
    PARTNER_MIN_PAYOUT_RUB,
    REFERRAL_COMMISSION_PCT,
    STARS_FIAT_RUB,
)
from models.app_models import PartnerTransaction, ProductEvent, Referral, User
from services.db import SessionLocal

logger = logging.getLogger(__name__)

# Rubles per Star for star counts missing from the fiat ladder — the same
# conservative fallback fiat_suffix() uses for display.
_FALLBACK_RUB_PER_STAR = 2.0


def register_referral_link(referrer_user_id: int, invitee_user_id: int) -> None:
    """Persist the permanent invitee→referrer link (idempotent per invitee).

    Called from referral_service.apply_referral inside its own transaction
    window; failures here must never break the credit grant, so callers wrap
    this in try/except.
    """
    if referrer_user_id == invitee_user_id:
        return
    with SessionLocal() as s:
        if s.scalar(select(Referral).where(Referral.invitee_user_id == invitee_user_id)):
            return
        s.add(Referral(referrer_user_id=referrer_user_id, invitee_user_id=invitee_user_id))
        try:
            s.commit()
        except IntegrityError:
            s.rollback()  # concurrent /start double-entry — the link exists


def referrer_of_user(user_id: int) -> int | None:
    """The referrer's users.id for a given users.id, or None.

    Reads the Referral table first; falls back to the legacy analytics marker
    (ProductEvent referral_invited whose metadata carries the referrer's
    telegram id) so referrals converted before V3.37.0 still earn commission.
    """
    with SessionLocal() as s:
        row = s.scalar(select(Referral).where(Referral.invitee_user_id == user_id))
        if row:
            return int(row.referrer_user_id)
        marker = s.scalar(
            select(ProductEvent)
            .where(ProductEvent.user_id == user_id, ProductEvent.event_name == "referral_invited")
            .order_by(ProductEvent.created_at.asc())
        )
        if not marker or not marker.metadata_json:
            return None
        try:
            referrer_tgid = int(json.loads(marker.metadata_json).get("referrer_telegram_id", "0"))
        except (TypeError, ValueError):
            return None
        if not referrer_tgid:
            return None
        referrer = s.scalar(select(User).where(User.telegram_id == str(referrer_tgid)))
        return int(referrer.id) if referrer else None


def referred_count(user_id: int) -> int:
    with SessionLocal() as s:
        return int(s.scalar(
            select(func.count()).select_from(Referral).where(Referral.referrer_user_id == user_id)
        ) or 0)


def _freekassa_amount_rub(provider_payload: str | None) -> float:
    """Parse ``amount=299.00`` out of the FreeKassa webhook payload."""
    try:
        for part in str(provider_payload or "").split("&"):
            key, _, value = part.partition("=")
            if key.strip() == "amount" and value.strip():
                return max(0.0, float(value.strip()))
    except ValueError:
        pass
    return 0.0


def payment_rub_value(product: str, stars: int, provider: str, provider_payload: str | None) -> float:
    """Partner-facing ruble value of a payment (0 when not commissionable)."""
    if provider == "freekassa":
        return _freekassa_amount_rub(provider_payload)
    stars_value = int(stars or 0)
    if stars_value <= 0:
        return 0.0
    ladder = STARS_FIAT_RUB.get(stars_value)
    if ladder:
        return float(ladder)
    return stars_value * _FALLBACK_RUB_PER_STAR


def accrue_commission(
    payer_user_id: int,
    product: str,
    stars: int,
    charge_id: str,
    provider: str = "stars",
    provider_payload: str | None = None,
) -> dict | None:
    """Credit the payer's referrer after a real purchase. None when N/A.

    Idempotent by charge_id (unique column). Returns the created transaction
    summary or None (disabled / not referred / zero value / duplicate).
    """
    if not PARTNER_ENABLED or not charge_id:
        return None
    rub_value = payment_rub_value(product, stars, provider, provider_payload)
    if rub_value <= 0:
        return None
    with SessionLocal() as s:
        if s.scalar(select(PartnerTransaction).where(
            PartnerTransaction.source_charge_id == str(charge_id)
        )):
            return None  # duplicate webhook / retried payment
        referrer_id = referrer_of_user(payer_user_id)
        if not referrer_id or referrer_id == payer_user_id:
            return None
        amount = round(rub_value * REFERRAL_COMMISSION_PCT / 100.0, 2)
        if amount <= 0:
            return None
        row = PartnerTransaction(
            user_id=referrer_id,
            kind="commission",
            amount_rub=amount,
            status="done",
            product=product,
            source_charge_id=str(charge_id),
        )
        s.add(row)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            return None
        s.refresh(row)
        logger.info(
            "partner commission referrer_uid=%s payer_uid=%s product=%s rub=%.2f commission=%.2f",
            referrer_id, payer_user_id, product, rub_value, amount,
        )
        return {"id": row.id, "user_id": referrer_id, "amount_rub": amount, "product": product}


def partner_stats(user_id: int) -> dict:
    """Partner screen numbers: invited people and the live ruble balance."""
    with SessionLocal() as s:
        earned = s.scalar(select(func.coalesce(func.sum(PartnerTransaction.amount_rub), 0.0)).where(
            PartnerTransaction.user_id == user_id,
            PartnerTransaction.kind == "commission",
        )) or 0.0
        paid_out = s.scalar(select(func.coalesce(func.sum(PartnerTransaction.amount_rub), 0.0)).where(
            PartnerTransaction.user_id == user_id,
            PartnerTransaction.kind == "payout",
            PartnerTransaction.status.in_(("pending", "paid")),
        )) or 0.0
        pending = s.scalar(select(PartnerTransaction).where(
            PartnerTransaction.user_id == user_id,
            PartnerTransaction.kind == "payout",
            PartnerTransaction.status == "pending",
        ).order_by(PartnerTransaction.created_at.desc()))
    return {
        "invited": referred_count(user_id),
        "earned_rub": round(float(earned), 2),
        "balance_rub": round(float(earned) - float(paid_out), 2),
        "pending_payout_id": int(pending.id) if pending else None,
    }


def request_payout(telegram_id: int) -> dict:
    """Create a pending withdrawal when the balance allows it.

    Returns {"ok": True, "payout_id", "amount_rub"} or
    {"ok": False, "reason": ...} — below_min / pending_exists / zero_balance.
    """
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            return {"ok": False, "reason": "unknown_user"}
        stats = partner_stats(user.id)
        if stats["pending_payout_id"]:
            return {"ok": False, "reason": "pending_exists", "payout_id": stats["pending_payout_id"]}
        balance = float(stats["balance_rub"])
        if balance < PARTNER_MIN_PAYOUT_RUB:
            return {"ok": False, "reason": "below_min", "balance_rub": balance}
        row = PartnerTransaction(
            user_id=user.id,
            kind="payout",
            amount_rub=round(balance, 2),
            status="pending",
            product="partner_payout",
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return {"ok": True, "payout_id": row.id, "amount_rub": row.amount_rub}


def get_payout(payout_id: int) -> dict | None:
    with SessionLocal() as s:
        row = s.get(PartnerTransaction, int(payout_id))
        if row is None or row.kind != "payout":
            return None
        user = s.get(User, row.user_id)
        return {
            "id": row.id,
            "user_id": row.user_id,
            "telegram_id": int(user.telegram_id) if user else 0,
            "amount_rub": row.amount_rub,
            "status": row.status,
        }


def settle_payout(payout_id: int, new_status: str) -> dict | None:
    """Owner-side transition pending -> paid/cancelled (single, guarded).

    Cancelling refunds the balance automatically because only pending+paid
    payouts subtract from it. Returns the payout or None when the transition
    is illegal (already settled / unknown).
    """
    if new_status not in ("paid", "cancelled"):
        return None
    with SessionLocal() as s:
        row = s.get(PartnerTransaction, int(payout_id))
        if row is None or row.kind != "payout" or row.status != "pending":
            return None
        row.status = new_status
        s.commit()
        user = s.get(User, row.user_id)
        return {
            "id": row.id,
            "user_id": row.user_id,
            "telegram_id": int(user.telegram_id) if user else 0,
            "amount_rub": row.amount_rub,
            "status": row.status,
        }
