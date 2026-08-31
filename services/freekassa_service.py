"""V3.19.6: FreeKassa card/SBP payments (external scenario).

The bot creates an order row, shows the user a payment link
(https://pay.freekassa.ru/...), and FreeKassa then calls our
``/freekassa/notify`` endpoint with an MD5 signature made from SECRET2.
Only a correctly signed notification grants the product, so the webhook is
safe to expose publicly.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta

from models.app_models import FreeKassaOrder
from services.db import SessionLocal
from config import FREEKASSA_MERCHANT_ID, FREEKASSA_SECRET1, FREEKASSA_SECRET2

logger = logging.getLogger(__name__)


def _md5_sign(parts: list[str]) -> str:
    return hashlib.md5(':'.join(parts).encode('utf-8')).hexdigest()


def create_order(telegram_id: int, product: str, amount: str) -> int:
    with SessionLocal() as session:
        # V3.27.0: direct url-buttons create an order on every keyboard
        # render; drop stale pending duplicates for the same user+product
        # so the table cannot grow without bound.
        cutoff = datetime.utcnow() - timedelta(hours=1)
        session.query(FreeKassaOrder).filter(
            FreeKassaOrder.telegram_id == int(telegram_id),
            FreeKassaOrder.product == product,
            FreeKassaOrder.status == 'pending',
            FreeKassaOrder.created_at < cutoff,
        ).delete()
        row = FreeKassaOrder(
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
        row = session.get(FreeKassaOrder, int(order_id))
        if row is None:
            return None
        return {
            'id': row.id,
            'telegram_id': row.telegram_id,
            'product': row.product,
            'amount': row.amount,
            'status': row.status,
        }


def payment_url(order_id: int, amount: str, currency: str | None = None) -> str:
    """Payment-page link signed with SECRET1 (initiation signature).

    V3.20.1: ``currency`` (e.g. 'USD') selects the invoice currency on a
    multi-currency kassa — international Visa/Mastercard pay in dollars.
    """
    sign = _md5_sign([FREEKASSA_MERCHANT_ID, str(amount), FREEKASSA_SECRET1, str(order_id)])
    url = (
        f'https://pay.freekassa.ru/?m={FREEKASSA_MERCHANT_ID}'
        f'&oa={amount}&o={order_id}&s={sign}&lang=ru'
    )
    if currency:
        url += f'&currency={currency}'
    return url


def verify_notify(params: dict) -> tuple[bool, str]:
    """Check the server-notification signature (SECRET2)."""
    order_id = str(params.get('MERCHANT_ORDER_ID') or params.get('order_id') or '').strip()
    amount = str(params.get('AMOUNT') or params.get('amount') or '').strip()
    sign = str(params.get('SIGN') or params.get('sign') or '').strip().lower()
    if not order_id or not amount or not sign:
        return False, 'missing_fields'
    expected = _md5_sign([FREEKASSA_MERCHANT_ID, amount, FREEKASSA_SECRET2, order_id])
    if sign != expected:
        logger.warning('FreeKassa notify bad signature order=%s', order_id)
        return False, 'bad_signature'
    return True, order_id


def mark_paid(order_id: int, payload: str) -> bool:
    """Idempotent pending->paid transition. False if already paid/unknown."""
    with SessionLocal() as session:
        row = session.get(FreeKassaOrder, int(order_id))
        if row is None:
            return False
        if row.status == 'paid':
            return False
        row.status = 'paid'
        row.paid_payload = payload[:2000]
        session.commit()
        return True
