"""V3.44.21: Platega card/SBP payments — the external (non-Telegram) scenario.

Replaces the retired FreeKassa integration end to end (docs.platega.io):

- ``POST /v2/transaction/process`` creates a transaction; the response's
  ``url`` is the payment page handed to the user. The payer picks the method
  (SBP / card / crypto) on that page themselves — no payment-system ids.
- The transaction is echoed back to us as a JSON callback on
  ``/platega/callback`` authenticated by the ``X-MerchantId`` / ``X-Secret``
  headers (the docs' auth model — there is no payload signature). Only a
  callback whose headers match the cabinet credentials grants the product,
  and the transaction is re-verified through ``GET /transaction/{id}``
  before anything is granted.
- ``payload`` sent on creation is echoed by the status endpoint and the
  callback; we put ``anb_order:{id}`` there and also store the transaction
  UUID on the order row, so a callback maps to its order two ways.

Both endpoints were verified live before this shipped (200 + a working
pay-page URL with the production merchant credentials).
"""
from __future__ import annotations

import hmac
import logging
from datetime import datetime, timedelta

import aiohttp

from models.app_models import PlategaOrder
from services.db import SessionLocal
from config import (
    PLATEGA_MERCHANT_ID, PLATEGA_API_KEY, PLATEGA_ENABLED,
    PLATEGA_API_BASE, PUBLIC_BASE_URL, BOT_USERNAME,
)

logger = logging.getLogger(__name__)

# Transaction statuses the callback / status endpoint can report.
STATUS_PENDING = 'PENDING'
STATUS_CONFIRMED = 'CONFIRMED'
STATUS_CANCELED = 'CANCELED'
STATUS_CHARGEBACKED = 'CHARGEBACKED'

# Marker embedded in the create-request ``payload`` and parsed back from the
# callback — the belt-and-braces order mapping next to the transaction UUID.
ORDER_PAYLOAD_PREFIX = 'anb_order:'


def _auth_headers() -> dict[str, str]:
    return {
        'X-MerchantId': PLATEGA_MERCHANT_ID,
        'X-Secret': PLATEGA_API_KEY,
        'Content-Type': 'application/json',
    }


def create_order(telegram_id: int, product: str, amount: str) -> int:
    """Order row for an in-bot card/SBP purchase (status pending)."""
    with SessionLocal() as session:
        # Direct url-buttons create an order on every keyboard render; drop
        # stale pending duplicates for the same user+product so the table
        # cannot grow without bound (carried over from the FreeKassa flow).
        cutoff = datetime.utcnow() - timedelta(hours=1)
        session.query(PlategaOrder).filter(
            PlategaOrder.telegram_id == int(telegram_id),
            PlategaOrder.product == product,
            PlategaOrder.status == 'pending',
            PlategaOrder.created_at < cutoff,
        ).delete()
        row = PlategaOrder(
            telegram_id=int(telegram_id),
            product=product,
            amount=str(amount),
            status='pending',
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def get_order(order_id: int) -> dict | None:
    with SessionLocal() as session:
        row = session.get(PlategaOrder, int(order_id))
        if row is None:
            return None
        return {
            'id': row.id,
            'telegram_id': row.telegram_id,
            'product': row.product,
            'amount': row.amount,
            'status': row.status,
            'transaction_id': row.transaction_id,
        }


def find_order(transaction_id: str | None, payload: str | None) -> dict | None:
    """Map a callback to its order: by transaction UUID, then by payload."""
    tid = str(transaction_id or '').strip()
    if tid:
        with SessionLocal() as session:
            row = session.query(PlategaOrder).filter(
                PlategaOrder.transaction_id == tid,
            ).first()
            if row is not None:
                return get_order(row.id)
    order_id = parse_order_ref(payload)
    return get_order(order_id) if order_id else None


def parse_order_ref(payload: str | None) -> int | None:
    """``anb_order:42`` → 42 (None when the payload is anything else)."""
    ref = str(payload or '').strip()
    if not ref.startswith(ORDER_PAYLOAD_PREFIX):
        return None
    tail = ref[len(ORDER_PAYLOAD_PREFIX):]
    try:
        return int(tail)
    except ValueError:
        return None


def verify_callback_headers(headers) -> bool:
    """Docs auth model: the callback carries our X-MerchantId + X-Secret."""
    if not PLATEGA_ENABLED:
        return False
    merchant = str(headers.get('X-MerchantId') or '').strip()
    secret = str(headers.get('X-Secret') or '').strip()
    if not merchant or not secret:
        return False
    return (
        hmac.compare_digest(merchant, PLATEGA_MERCHANT_ID)
        and hmac.compare_digest(secret, PLATEGA_API_KEY)
    )


def amount_covers(paid: float | None, expected: str) -> bool:
    """Paid amount must not be lower than the order amount (0.01 tolerance)."""
    try:
        return float(paid or 0.0) >= float(expected) - 0.01
    except (TypeError, ValueError):
        return False


async def create_payment(order_id: int, amount: str, currency: str = 'RUB',
                         telegram_id: int | None = None,
                         description: str | None = None,
                         username: str | None = None) -> str | None:
    """POST /v2/transaction/process → the ``url`` payment page for the user.

    Stores the returned transaction UUID on the order row (the callback
    carries it back). Returns None on any failure so the caller can tell the
    user to retry or pay with Stars instead.
    """
    if not PLATEGA_ENABLED:
        return None
    # ``return`` / ``failedUrl`` are required by the schema. The Railway
    # domain shows our success/fail pages; without it, drop the payer back
    # into the bot chat after the payment page.
    if PUBLIC_BASE_URL:
        return_url = f'{PUBLIC_BASE_URL}/platega/success'
        failed_url = f'{PUBLIC_BASE_URL}/platega/fail'
    else:
        bot_link = f'https://t.me/{BOT_USERNAME}' if BOT_USERNAME else 'https://t.me/'
        return_url = failed_url = bot_link
    user_ref = f'@{username}' if username else str(telegram_id or '-')
    body = {
        'paymentDetails': {'amount': round(float(amount), 2), 'currency': currency},
        'description': (description or f'AnnaBot · заказ #{order_id}')[:200],
        'return': return_url,
        'failedUrl': failed_url,
        'payload': f'{ORDER_PAYLOAD_PREFIX}{order_id}',
        'orderId': str(order_id),
        # docs: metadata.userId feeds the antifraud — always send it.
        'metadata': {'userId': str(telegram_id or 0), 'userName': user_ref},
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f'{PLATEGA_API_BASE}/v2/transaction/process',
                json=body, headers=_auth_headers(),
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                status = resp.status
                data = await resp.json(content_type=None)
    except Exception as exc:
        logger.error('Platega payment request failed order=%s err=%s', order_id, exc)
        return None
    url = str((data or {}).get('url') or '').strip()
    transaction_id = str((data or {}).get('transactionId') or '').strip()
    if status != 200 or not url:
        logger.error('Platega payment rejected order=%s status=%s resp=%s',
                     order_id, status, str(data)[:300])
        return None
    if transaction_id:
        with SessionLocal() as session:
            row = session.get(PlategaOrder, int(order_id))
            if row is not None:
                row.transaction_id = transaction_id[:64]
                session.commit()
    domain = url.split('/')[2] if url.startswith('http') else '-'
    logger.info('Platega payment created order=%s transaction=%s domain=%s expires=%s',
                order_id, transaction_id or '-', domain, (data or {}).get('expiresIn'))
    return url


async def get_transaction(transaction_id: str) -> dict | None:
    """GET /transaction/{id} — status re-check / owner diagnostics."""
    if not PLATEGA_ENABLED or not transaction_id:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f'{PLATEGA_API_BASE}/transaction/{transaction_id}',
                headers=_auth_headers(),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    logger.warning('Platega status check http=%s transaction=%s',
                                   resp.status, transaction_id)
                    return None
                return await resp.json(content_type=None)
    except Exception as exc:
        logger.warning('Platega status check failed transaction=%s err=%s',
                       transaction_id, exc)
        return None


def mark_paid(order_id: int, payload: str) -> bool:
    """Idempotent pending->paid transition. False if already paid/unknown."""
    with SessionLocal() as session:
        row = session.get(PlategaOrder, int(order_id))
        if row is None:
            return False
        if row.status == 'paid':
            return False
        row.status = 'paid'
        row.paid_payload = payload[:2000]
        session.commit()
        return True


def mark_canceled(order_id: int, payload: str, new_status: str = 'canceled') -> bool:
    """pending->canceled on CANCELED; paid->chargedback on CHARGEBACKED
    (money returned to the payer — flagged for manual review, the
    already-granted product is not auto-revoked)."""
    with SessionLocal() as session:
        row = session.get(PlategaOrder, int(order_id))
        if row is None:
            return False
        if new_status == 'chargedback' and row.status in ('paid', 'chargedback'):
            row.status = 'chargedback'
        elif new_status == 'canceled' and row.status == 'pending':
            row.status = 'canceled'
        else:
            return False
        row.paid_payload = (row.paid_payload or '') + '|' + str(payload or '')[:500]
        session.commit()
        return True
