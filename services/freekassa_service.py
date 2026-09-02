"""V3.19.6: FreeKassa card/SBP payments (external scenario).

The bot creates an order row, shows the user a payment link, and FreeKassa
then calls our ``/freekassa/notify`` endpoint with an MD5 signature made from
SECRET2 (docs 1.4/1.7). Only a correctly signed notification grants the
product, so the webhook is safe to expose publicly.

V3.30.0: orders are created through the FreeKassa REST API
(``POST https://api.fk.life/v1/orders/create``, JSON, HMAC-SHA256 signature
per docs 2.2); the payment link arrives in the ``location`` response field
and is handed to the user. The legacy SCI form link (SECRET1) stays only as
a fallback for when the API or the server-IP lookup is unreachable.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from datetime import datetime, timedelta

import aiohttp

from models.app_models import FreeKassaOrder
from services.db import SessionLocal
from config import (
    FREEKASSA_MERCHANT_ID, FREEKASSA_SECRET1, FREEKASSA_SECRET2,
    FREEKASSA_API_KEY, FREEKASSA_API_ENABLED, FREEKASSA_SERVER_IP,
    PUBLIC_BASE_URL,
)

logger = logging.getLogger(__name__)

# V3.30.0: every REST request is a JSON POST under this base (docs 2.x).
FK_API_BASE = 'https://api.fk.life/v1'
# Payment-system id passed in ``i`` for SBP QR-code acceptance (docs: i=44).
FK_SBP_QR_PAYMENT_ID = 44

_server_ip_cache: dict[str, object] = {}
_currencies_cache: dict[str, int] = {}


def _api_signature(params: dict, key: str) -> str:
    """Docs 2.2: ksort the params, join the values with '|', HMAC-SHA256."""
    base = '|'.join(str(params[k]) for k in sorted(params))
    return hmac.new(key.encode('utf-8'), base.encode('utf-8'), hashlib.sha256).hexdigest()


def _nonce() -> int:
    """Request id that must always be greater than the previous one."""
    return int(time.time() * 1000)


async def _server_ip() -> str:
    """Public egress IP of this host (orders/create rejects 127.0.0.1).

    Telegram never reveals the user IP to bots, so the docs allow sending
    the server IP instead. Cached for an hour; env override always wins.
    """
    if FREEKASSA_SERVER_IP:
        return FREEKASSA_SERVER_IP
    cached = _server_ip_cache.get('ip')
    if cached and time.monotonic() - float(_server_ip_cache.get('ts', 0.0)) < 3600:
        return str(cached)
    for probe in ('https://api.ipify.org', 'https://ifconfig.me/ip'):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    probe, timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    ip = (await resp.text()).strip()
            if ip and len(ip) <= 45:
                _server_ip_cache.update(ip=ip, ts=time.monotonic())
                return ip
        except Exception as exc:
            logger.warning('FreeKassa server-ip probe %s failed: %s', probe, exc)
    return ''


async def _default_payment_id(currency: str) -> int | None:
    """First enabled payment system for the currency (docs: /currencies)."""
    if currency.upper() in _currencies_cache:
        return _currencies_cache[currency.upper()]
    if not FREEKASSA_API_ENABLED:
        return None
    params: dict = {'shopId': int(FREEKASSA_MERCHANT_ID), 'nonce': _nonce()}
    params['signature'] = _api_signature(params, FREEKASSA_API_KEY)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f'{FK_API_BASE}/currencies', json=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
        for row in (data or {}).get('currencies') or []:
            if row.get('is_enabled') == 1 and str(row.get('currency', '')).upper() == currency.upper():
                _currencies_cache[currency.upper()] = int(row['id'])
                return int(row['id'])
    except Exception as exc:
        logger.warning('FreeKassa currencies lookup failed: %s', exc)
    return None


async def create_api_order(order_id: int, amount: str, currency: str = 'RUB',
                           telegram_id: int | None = None,
                           payment_system: int | None = None) -> str | None:
    """Docs createOrder: POST /orders/create, payment link in ``location``.

    Returns the link the user must open to pay, or None when the API path is
    unavailable (no key / no IP / API error) so the caller falls back to SCI.
    """
    if not FREEKASSA_API_ENABLED:
        return None
    ip = await _server_ip()
    if not ip:
        logger.warning('FreeKassa API order skipped (no server ip) order=%s', order_id)
        return None
    pay_id = payment_system or await _default_payment_id(currency)
    params: dict = {
        'shopId': int(FREEKASSA_MERCHANT_ID),
        'nonce': _nonce(),
        'paymentId': str(order_id),
        # Docs: the real client email or <telegram id>@telegram.org.
        'email': f'{int(telegram_id)}@telegram.org' if telegram_id else f'order{int(order_id)}@telegram.org',
        'ip': ip,
        'amount': str(amount),
        'currency': currency,
    }
    if pay_id:
        params['i'] = int(pay_id)
    if PUBLIC_BASE_URL:
        params['success_url'] = f'{PUBLIC_BASE_URL}/freekassa/success'
        params['failure_url'] = f'{PUBLIC_BASE_URL}/freekassa/fail'
        params['notification_url'] = f'{PUBLIC_BASE_URL}/freekassa/notify'
    params['signature'] = _api_signature(params, FREEKASSA_API_KEY)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f'{FK_API_BASE}/orders/create', json=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()
    except Exception as exc:
        logger.error('FreeKassa API order request failed order=%s err=%s', order_id, exc)
        return None
    location = str((data or {}).get('location') or '').strip()
    if not location:
        logger.error('FreeKassa API order rejected order=%s resp=%s', order_id, str(data)[:300])
        return None
    logger.info('FreeKassa API order created order=%s fk_order=%s', order_id, (data or {}).get('orderId'))
    return location


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
