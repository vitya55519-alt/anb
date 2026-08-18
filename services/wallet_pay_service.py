"""Telegram Wallet Pay integration.

Docs: https://docs.ton.org/develop/dapps/telegram-wallet/connection
API endpoint: POST {WALLET_PAY_API_URL}/store-api/v1/order
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import httpx

from config import WALLET_PAY_TOKEN, WALLET_PAY_API_URL, WALLET_PAY_TIMEOUT_SECONDS
from services.db import SessionLocal
from models.app_models import WalletPayTransaction, User

logger = logging.getLogger(__name__)


def _api_headers() -> dict:
    return {
        "Authorization": f"Bearer {WALLET_PAY_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _find_user_id_by_telegram_id(telegram_id: int) -> int | None:
    from services.user_service import get_user
    user = get_user(telegram_id)
    return user.id if user else None


async def create_invoice(
    telegram_id: int,
    product: str,
    stars_amount: int,
    description: str,
    payload: str | None = None,
) -> dict | None:
    """Create a Wallet Pay invoice. Returns dict with payment_link and invoice_id."""
    if not WALLET_PAY_TOKEN:
        logger.warning("Wallet Pay token not configured")
        return None

    amount_usd = round(stars_amount * 0.02, 2)
    if amount_usd < 0.01:
        amount_usd = 0.01

    user_id = _find_user_id_by_telegram_id(telegram_id)
    if not user_id:
        logger.warning("Wallet Pay invoice requested for unknown user telegram_id=%s", telegram_id)
        return None

    external_id = f"{telegram_id}_{product}_{int(datetime.now(timezone.utc).timestamp())}"
    body = {
        "amount": {
            "currencyCode": "USD",
            "amount": str(amount_usd),
        },
        "description": description[:120],
        "externalId": external_id,
        "timeoutSeconds": 1800,
        "customerTelegramUserId": telegram_id,
    }

    try:
        async with httpx.AsyncClient(timeout=WALLET_PAY_TIMEOUT_SECONDS) as client:
            r = await client.post(
                f"{WALLET_PAY_API_URL}/store-api/v1/order",
                headers=_api_headers(),
                json=body,
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        logger.exception("Wallet Pay create_invoice failed: %s", exc)
        return None

    invoice_id = data.get("id") or data.get("orderId") or external_id
    payment_link = data.get("payLink") or data.get("paymentLink") or data.get("directPayLink")
    if not payment_link:
        logger.warning("Wallet Pay response missing payment link: %s", data)
        return None

    with SessionLocal() as session:
        session.add(
            WalletPayTransaction(
                user_id=user_id,
                invoice_id=invoice_id,
                product=product,
                amount_usd=amount_usd,
                stars_equivalent=stars_amount,
                status="pending",
                payload=payload,
                metadata_json=json.dumps(data, ensure_ascii=False),
            )
        )
        session.commit()

    return {"invoice_id": invoice_id, "payment_link": payment_link, "amount_usd": amount_usd}


async def get_invoice_status(invoice_id: str) -> dict | None:
    """Fetch current invoice status from Wallet Pay API."""
    if not WALLET_PAY_TOKEN:
        return None
    try:
        async with httpx.AsyncClient(timeout=WALLET_PAY_TIMEOUT_SECONDS) as client:
            r = await client.get(
                f"{WALLET_PAY_API_URL}/store-api/v1/order?id={invoice_id}",
                headers=_api_headers(),
            )
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.exception("Wallet Pay get_invoice_status failed: %s", exc)
        return None


def verify_webhook_signature(body_bytes: bytes, signature: str | None) -> bool:
    """Verify Wallet Pay webhook HMAC signature."""
    if not WALLET_PAY_TOKEN or not signature:
        return False
    expected = hmac.new(
        WALLET_PAY_TOKEN.encode(),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def process_webhook(payload_dict: dict) -> bool:
    """Handle Wallet Pay webhook payload. Returns True if payment processed."""
    event_type = payload_dict.get("event", payload_dict.get("type", ""))
    if event_type not in {"ORDER_PAID", "ORDER_COMPLETED", "payment", "paid"}:
        logger.info("Wallet Pay webhook ignored event=%s", event_type)
        return False

    invoice_id = (
        payload_dict.get("id")
        or payload_dict.get("orderId")
        or payload_dict.get("payload", {}).get("id")
    )
    if not invoice_id:
        logger.warning("Wallet Pay webhook missing invoice id")
        return False

    with SessionLocal() as session:
        tx = session.query(WalletPayTransaction).filter_by(invoice_id=invoice_id).first()
        if not tx:
            logger.warning("Wallet Pay webhook unknown invoice_id=%s", invoice_id)
            return False
        if tx.status in {"paid", "completed"}:
            return True

        tx.status = "paid"
        tx.paid_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.commit()

        from services.payments import record_payment
        try:
            record_payment(
                telegram_id=int(tx.user.telegram_id),
                product=tx.product,
                stars=tx.stars_equivalent,
                charge_id=f"walletpay:{invoice_id}",
                provider="wallet_pay",
                provider_payload=json.dumps(payload_dict, ensure_ascii=False),
            )
        except Exception as exc:
            logger.exception("record_payment failed for Wallet Pay invoice %s: %s", invoice_id, exc)
            return False

    logger.info("Wallet Pay payment processed invoice_id=%s product=%s stars=%s", invoice_id, tx.product, tx.stars_equivalent)
    return True
