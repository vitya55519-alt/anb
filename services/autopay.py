"""V3.120.0: Premium auto-renewal (автопродление) — only when he turns it on.

Two rails, both opt-in, both cancellable in one tap:

- **Telegram Stars** — a native Stars subscription: ``create_invoice_link``
  with ``subscription_period`` = 30 days (the only period Telegram allows).
  Telegram charges the same amount every 30 days and sends us a
  ``successful_payment`` with ``is_recurring``; the first payment's
  ``telegram_payment_charge_id`` cancels it via ``editUserStarSubscription``.
  He also sees and can cancel it in Telegram's own settings.
- **Platega SBP subscription** (docs.platega.io «Рекуррентные СБП-подписки»):
  ``POST /transaction/process`` with ``paymentMethod: 6`` and
  ``interval`` week/month; he confirms the bank link once on the page, then
  Platega debits on schedule. Every debit is a CONFIRMED callback carrying
  ``subscriptionId`` + ``nextChargeAt``; ``POST /subscription/{id}/cancel``
  stops it. Crypto has no recurring rail — it stays one-time.

Honesty rules (owner: no hidden auto-charges):
- the one-time plans stay exactly as they were; auto-renewal is a separate
  button with the terms spelled out before the pay link;
- a reminder with the amount, the date and an «Отключить» button goes out
  before every charge (REMIND_HOURS ahead, Moscow daytime);
- cancelling keeps every paid day; renewal_care's «останешься?» is not sent
  to someone whose Premium renews by itself.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import aiohttp
from sqlalchemy import select

from models.app_models import AutoRenewal, Subscription, User
from services.db import SessionLocal

logger = logging.getLogger(__name__)


def _flag(name: str, default: str = 'true') -> bool:
    return os.getenv(name, default).strip().lower() not in ('0', 'false', 'no', 'off')


ENABLED = _flag('AUTOPAY_ENABLED')
STARS_ENABLED = _flag('AUTOPAY_STARS_ENABLED')
PLATEGA_SUB_ENABLED = _flag('AUTOPAY_PLATEGA_ENABLED')
# Hours before the charge the reminder may go out (sent in Moscow daytime,
# so 30 h guarantees it lands at least ~8 h before a night-time charge).
REMIND_HOURS = max(2, int(os.getenv('AUTOPAY_REMIND_HOURS', '30')))
# A Stars renewal Telegram never sent (he cancelled in Telegram settings, or
# the balance ran dry) — after this many hours past the date the row lapses.
LAPSE_HOURS = max(6, int(os.getenv('AUTOPAY_LAPSE_HOURS', '48')))
PLATEGA_SUB_PATH = os.getenv('PLATEGA_SUBSCRIPTION_PATH', '/transaction/process').strip() or '/transaction/process'

STARS_PERIOD_SECONDS = 30 * 24 * 3600  # Telegram: subscription_period must be 2592000
STARS_PAYLOAD = 'premium_month_auto'
PLAN_DAYS = {'premium_week': 7, 'premium_month': 30}
# Platega interval codes: 1 day, 2 week, 3 month, 4 year.
PLATEGA_INTERVAL = {'premium_week': 2, 'premium_month': 3}
PLATEGA_METHOD_SUBSCRIPTION = 6
SUB_STATUSES = {
    'SUBSCRIPTION_ACTIVATED': 'active',
    'SUBSCRIPTION_CANCELLED': 'canceled',
    'SUBSCRIPTION_CANCELED': 'canceled',
    'SUBSCRIPTION_PAST_DUE': 'past_due',
    'SUBSCRIPTION_FAILED': 'failed',
}
LIVE = ('active', 'past_due')


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_dt(value) -> datetime | None:
    """ISO string (``2026-11-28T09:00:00Z``), unix seconds or datetime → naive UTC."""
    if value is None or value == '':
        return None
    try:
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
        else:
            raw = str(value).strip().replace('Z', '+00:00')
            dt = datetime.fromisoformat(raw)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except (TypeError, ValueError, OverflowError):
        return None


def customer_email(telegram_id: int) -> str:
    """Platega wants a stable ``metadata.user_email`` per buyer; the docs list
    ``{telegram_id}@telegram.org`` as an accepted form."""
    return f'{int(telegram_id)}@telegram.org'


def telegram_id_from_email(email: str | None) -> int | None:
    raw = str(email or '').strip().lower()
    if not raw.endswith('@telegram.org'):
        return None
    try:
        return int(raw.split('@', 1)[0])
    except ValueError:
        return None


def _row_dict(row: AutoRenewal | None) -> dict | None:
    if row is None:
        return None
    return {
        'id': row.id, 'telegram_id': int(row.telegram_id), 'provider': row.provider,
        'plan': row.plan, 'amount': int(row.amount or 0), 'status': row.status,
        'external_id': row.external_id, 'next_charge_at': row.next_charge_at,
        'reminded_for': row.reminded_for, 'charges': int(row.charges or 0),
    }


# ---------------------------------------------------------------- queries

def get_live(telegram_id: int) -> dict | None:
    """His auto-renewal that is on (active / past_due), newest first."""
    with SessionLocal() as s:
        row = s.scalar(select(AutoRenewal).where(
            AutoRenewal.telegram_id == int(telegram_id), AutoRenewal.status.in_(LIVE),
        ).order_by(AutoRenewal.id.desc()).limit(1))
        return _row_dict(row)


def charge_seen(charge_id: str) -> bool:
    """Callback idempotency (docs: dedupe by payment ``id``)."""
    from models.app_models import StarTransaction
    with SessionLocal() as s:
        return s.scalar(select(StarTransaction.id).where(
            StarTransaction.telegram_charge_id == str(charge_id)).limit(1)) is not None


def has_active(telegram_id: int) -> bool:
    try:
        row = get_live(telegram_id)
    except Exception:
        logger.exception('autopay lookup failed user=%s', telegram_id)
        return False
    return bool(row and row['status'] == 'active')


def get(row_id: int) -> dict | None:
    with SessionLocal() as s:
        return _row_dict(s.get(AutoRenewal, int(row_id)))


def find_by_external(external_id: str | None) -> dict | None:
    ext = str(external_id or '').strip()
    if not ext:
        return None
    with SessionLocal() as s:
        row = s.scalar(select(AutoRenewal).where(AutoRenewal.external_id == ext)
                       .order_by(AutoRenewal.id.desc()).limit(1))
        return _row_dict(row)


def latest_platega_for(telegram_id: int) -> dict | None:
    """Fallback mapping (callback id unknown to us): his newest Platega row
    that is still waiting or on."""
    with SessionLocal() as s:
        row = s.scalar(select(AutoRenewal).where(
            AutoRenewal.telegram_id == int(telegram_id), AutoRenewal.provider == 'platega',
            AutoRenewal.status.in_(('pending',) + LIVE),
        ).order_by(AutoRenewal.id.desc()).limit(1))
        return _row_dict(row)


# ---------------------------------------------------------------- writes

def create_pending(telegram_id: int, provider: str, plan: str, amount: int,
                   external_id: str | None = None) -> int:
    with SessionLocal() as s:
        # taps that never turned into a payment — keep the table small
        s.query(AutoRenewal).filter(
            AutoRenewal.telegram_id == int(telegram_id), AutoRenewal.status == 'pending',
            AutoRenewal.created_at < _now() - timedelta(days=2),
        ).delete()
        row = AutoRenewal(telegram_id=int(telegram_id), provider=provider, plan=plan,
                          amount=int(amount), status='pending', external_id=external_id)
        s.add(row)
        s.commit()
        s.refresh(row)
        return row.id


def set_external(row_id: int, external_id: str) -> None:
    with SessionLocal() as s:
        row = s.get(AutoRenewal, int(row_id))
        if row is not None:
            row.external_id = str(external_id)[:255]
            s.commit()


def record_charge(row_id: int, next_charge_at: datetime | None) -> bool:
    """A successful (first or recurring) charge: row → active, +1 charge.
    Returns True when this was the first charge (the subscription just
    started). Any other live auto-renewal of his is closed so two rails can
    never both charge him."""
    with SessionLocal() as s:
        row = s.get(AutoRenewal, int(row_id))
        if row is None:
            return False
        first = int(row.charges or 0) == 0
        row.status = 'active'
        row.charges = int(row.charges or 0) + 1
        if next_charge_at:
            row.next_charge_at = next_charge_at
        elif row.next_charge_at is None or row.next_charge_at <= _now():
            row.next_charge_at = _now() + timedelta(days=PLAN_DAYS.get(row.plan, 30))
        s.commit()
        return first


def set_status(row_id: int, status: str) -> None:
    with SessionLocal() as s:
        row = s.get(AutoRenewal, int(row_id))
        if row is None:
            return
        row.status = status
        if status in ('canceled', 'failed'):
            row.canceled_at = _now()
        s.commit()


def mark_reminded(row_id: int, for_dt: datetime | None) -> None:
    with SessionLocal() as s:
        row = s.get(AutoRenewal, int(row_id))
        if row is not None:
            row.reminded_for = for_dt
            s.commit()


def extend_premium_to(telegram_id: int, until: datetime | None) -> None:
    """Keep Premium on until the next charge (+6 h) — a calendar-month SBP
    debit can land on day 31 while one charge grants 30 days."""
    if not until:
        return
    target = until + timedelta(hours=6)
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            return
        sub = s.scalar(select(Subscription).where(
            Subscription.user_id == user.id, Subscription.status == 'active',
        ).order_by(Subscription.expires_at.desc()).limit(1))
        if sub is None or sub.expires_at is None or sub.expires_at >= target:
            return
        # never stretch more than a few days past what was paid
        if target - sub.expires_at > timedelta(days=3):
            return
        sub.expires_at = target
        s.commit()


def due_reminders(now: datetime | None = None) -> list[dict]:
    """Active rows whose next charge is within REMIND_HOURS and not yet reminded."""
    now = now or _now()
    with SessionLocal() as s:
        rows = s.scalars(select(AutoRenewal).where(
            AutoRenewal.status == 'active',
            AutoRenewal.next_charge_at.is_not(None),
            AutoRenewal.next_charge_at > now + timedelta(hours=1),
            AutoRenewal.next_charge_at <= now + timedelta(hours=REMIND_HOURS),
        )).all()
        return [_row_dict(r) for r in rows if r.reminded_for != r.next_charge_at]


def lapse_overdue(now: datetime | None = None) -> list[dict]:
    """Rows whose charge date passed LAPSE_HOURS ago with no charge: Stars →
    canceled (Telegram tells us nothing when he cancels in its settings),
    Platega → past_due. Returns the rows that changed."""
    now = now or _now()
    changed = []
    with SessionLocal() as s:
        rows = s.scalars(select(AutoRenewal).where(
            AutoRenewal.status == 'active', AutoRenewal.next_charge_at.is_not(None),
            AutoRenewal.next_charge_at < now - timedelta(hours=LAPSE_HOURS),
        )).all()
        for r in rows:
            r.status = 'canceled' if r.provider == 'stars' else 'past_due'
            if r.status == 'canceled':
                r.canceled_at = now
            changed.append(_row_dict(r))
        s.commit()
    return changed


# ---------------------------------------------------------------- Platega API

def _platega_headers() -> dict[str, str]:
    from config import PLATEGA_API_KEY, PLATEGA_MERCHANT_ID
    return {'X-MerchantId': PLATEGA_MERCHANT_ID, 'X-Secret': PLATEGA_API_KEY,
            'Content-Type': 'application/json'}


def platega_body(row_id: int, telegram_id: int, plan: str, amount: int,
                 username: str | None = None) -> dict:
    from config import BOT_USERNAME, PUBLIC_BASE_URL
    if PUBLIC_BASE_URL:
        ok_url, fail_url = f'{PUBLIC_BASE_URL}/platega/success', f'{PUBLIC_BASE_URL}/platega/fail'
    else:
        ok_url = fail_url = f'https://t.me/{BOT_USERNAME}' if BOT_USERNAME else 'https://t.me/'
    period = 'неделя' if plan == 'premium_week' else 'месяц'
    return {
        'paymentMethod': PLATEGA_METHOD_SUBSCRIPTION,
        'paymentDetails': {'amount': int(amount), 'currency': 'RUB',
                           'interval': PLATEGA_INTERVAL[plan], 'intervalCount': 1},
        'description': f'AnnaBot Premium · автопродление · {period}',
        'return': ok_url,
        'failedUrl': fail_url,
        'payload': f'anb_autopay:{row_id}',
        # docs: metadata is required, user_email stable per buyer
        'metadata': {'user_email': customer_email(telegram_id), 'userId': str(telegram_id),
                     'userName': f'@{username}' if username else str(telegram_id)},
    }


async def platega_create(row_id: int, telegram_id: int, plan: str, amount: int,
                         username: str | None = None) -> str | None:
    """Create the SBP subscription; returns the page where he confirms the
    bank link (None on any failure — the caller offers the one-time plans)."""
    from config import PLATEGA_API_BASE, PLATEGA_ENABLED
    if not (PLATEGA_ENABLED and PLATEGA_SUB_ENABLED) or plan not in PLATEGA_INTERVAL:
        return None
    body = platega_body(row_id, telegram_id, plan, amount, username)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f'{PLATEGA_API_BASE}{PLATEGA_SUB_PATH}', json=body,
                                    headers=_platega_headers(),
                                    timeout=aiohttp.ClientTimeout(total=20)) as resp:
                status = resp.status
                data = await resp.json(content_type=None)
    except Exception as exc:
        logger.error('Platega subscription request failed row=%s err=%s', row_id, exc)
        return None
    data = data or {}
    url = str(data.get('redirect') or data.get('url') or '').strip()
    tid = str(data.get('transactionId') or data.get('subscriptionId') or '').strip()
    if status != 200 or not url:
        logger.error('Platega subscription rejected row=%s status=%s resp=%s', row_id, status, str(data)[:300])
        return None
    if tid:
        set_external(row_id, tid)
    logger.info('Platega subscription created row=%s id=%s plan=%s', row_id, tid or '-', plan)
    return url


async def platega_get_subscription(subscription_id: str) -> dict | None:
    from config import PLATEGA_API_BASE, PLATEGA_ENABLED
    if not PLATEGA_ENABLED or not subscription_id:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'{PLATEGA_API_BASE}/subscription/{subscription_id}',
                                   headers=_platega_headers(),
                                   timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return None
                return await resp.json(content_type=None)
    except Exception as exc:
        logger.warning('Platega subscription lookup failed id=%s err=%s', subscription_id, exc)
        return None


async def platega_cancel(subscription_id: str) -> bool:
    from config import PLATEGA_API_BASE, PLATEGA_ENABLED
    if not PLATEGA_ENABLED or not subscription_id:
        return False
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f'{PLATEGA_API_BASE}/subscription/{subscription_id}/cancel',
                                    headers=_platega_headers(),
                                    timeout=aiohttp.ClientTimeout(total=15)) as resp:
                ok = resp.status == 200
                if not ok:
                    logger.error('Platega subscription cancel http=%s id=%s body=%s',
                                 resp.status, subscription_id, (await resp.text())[:300])
                return ok
    except Exception as exc:
        logger.error('Platega subscription cancel failed id=%s err=%s', subscription_id, exc)
        return False


def is_subscription_callback(body: dict) -> bool:
    status = str((body or {}).get('status') or '').upper()
    return bool((body or {}).get('subscriptionId')) or status.startswith('SUBSCRIPTION_') \
        or str((body or {}).get('payload') or '').startswith('anb_autopay:')


async def resolve_callback_row(body: dict) -> dict | None:
    """Map a Platega subscription callback to our row: subscriptionId, then the
    callback id, then our payload, then GET /subscription → customerEmail."""
    sub_id = str(body.get('subscriptionId') or '').strip()
    for ext in (sub_id, str(body.get('id') or '').strip()):
        row = find_by_external(ext)
        if row:
            return row
    payload = str(body.get('payload') or '')
    if payload.startswith('anb_autopay:'):
        try:
            row = get(int(payload.split(':', 1)[1]))
        except ValueError:
            row = None
        if row:
            if sub_id and row.get('external_id') != sub_id:
                set_external(row['id'], sub_id)
            return row
    if sub_id:
        info = await platega_get_subscription(sub_id)
        tg = telegram_id_from_email((info or {}).get('customerEmail'))
        if tg:
            row = latest_platega_for(tg)
            if row:
                set_external(row['id'], sub_id)
                row['external_id'] = sub_id
                return row
    return None


# ---------------------------------------------------------------- texts

def fmt_date(dt: datetime | None, en: bool = False) -> str:
    if not dt:
        return '—'
    msk = dt + timedelta(hours=3)
    if en:
        return msk.strftime('%b %d')
    months = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля',
              'августа', 'сентября', 'октября', 'ноября', 'декабря']
    return f'{msk.day} {months[msk.month - 1]}'


def price_label(row: dict, en: bool = False) -> str:
    if row['provider'] == 'stars':
        return f"{row['amount']} Stars"
    return f"{row['amount']} ₽"


def period_label(plan: str, en: bool = False) -> str:
    if plan == 'premium_week':
        return 'every 7 days' if en else 'раз в неделю'
    return 'every month' if en else 'раз в месяц'


def terms_text(en: bool = False) -> str:
    if en:
        return ('🔁 <b>Premium auto-renewal</b>\n\n'
                'How it works, honestly:\n'
                '• you pay now and Premium turns on right away;\n'
                '• then the same amount is charged automatically every 30 days;\n'
                '• a day before each charge I remind you how much and when;\n'
                '• turn it off any time: /autopay → «Turn off». Paid days stay yours;\n'
                '• a Stars subscription is also visible and cancellable in Telegram settings.\n\n'
                'If you want to pay once — just pick a plan in /premium, nothing will renew.')
    return ('🔁 <b>Автопродление Premium</b>\n\n'
            'Как это работает — честно:\n'
            '• платишь сейчас, Premium включается сразу;\n'
            '• дальше та же сумма списывается сама: неделя — раз в 7 дней, месяц — раз в месяц;\n'
            '• накануне каждого списания я напомню, сколько и когда спишется;\n'
            '• отключить можно в любой момент: /autopay → «Отключить». Оплаченные дни остаются;\n'
            '• подписку в Stars видно и можно отменить ещё и в настройках Telegram.\n\n'
            'Хочешь заплатить один раз — просто выбери тариф в /premium, ничего продлеваться не будет.')


def status_text(row: dict, en: bool = False) -> str:
    when = fmt_date(row.get('next_charge_at'), en)
    price = price_label(row, en)
    period = period_label(row['plan'], en)
    if row['status'] == 'past_due':
        return (f'🔁 Auto-renewal is on, but the last charge did not go through. Premium is open until {when}.'
                if en else
                f'🔁 Автопродление включено, но последнее списание не прошло. '
                f'Premium открыт до {when}. Можно продлить вручную в /premium или отключить автопродление.')
    via = ('Telegram Stars' if row['provider'] == 'stars' else ('SBP' if en else 'СБП'))
    if en:
        return (f'🔁 Auto-renewal is on: {price} {period} via {via}.\n'
                f'Next charge: {when}. A reminder comes the day before.\n'
                'Turn it off any time — paid days stay yours.')
    return (f'🔁 Автопродление включено: {price} {period} через {via}.\n'
            f'Следующее списание: {when}. Накануне я напомню.\n'
            'Отключить можно в любой момент — оплаченные дни останутся.')


def reminder_text(row: dict, en: bool = False) -> str:
    when = fmt_date(row.get('next_charge_at'), en)
    price = price_label(row, en)
    extra_en = (" If you already cancelled it in Telegram settings, nothing will be charged."
                if row['provider'] == 'stars' else '')
    extra_ru = (' Если ты уже отменил её в настройках Telegram — ничего не спишется.'
                if row['provider'] == 'stars' else '')
    if en:
        return (f'🔁 Honest heads-up: on {when} your Premium renews automatically — {price} will be charged.'
                f'{extra_en}\nDon\'t want it? Turn it off below, your paid days stay.')
    return (f'🔁 Честно предупреждаю: {when} Premium продлится автоматически — спишется {price}.'
            f'{extra_ru}\nНе хочешь — отключи кнопкой ниже, оплаченные дни останутся.')


def renewed_text(row: dict, until: datetime | None, first: bool, en: bool = False) -> str:
    when = fmt_date(until, en)
    if first:
        return (f'✅ Auto-renewal is on. Premium is open, next charge {when}. Manage: /autopay'
                if en else
                f'✅ Автопродление включено. Premium открыт, следующее списание {when}. '
                f'Управлять или отключить: /autopay')
    price = price_label(row, en)
    return (f'🔁 Premium renewed: {price} charged, next charge {when}. Turn off: /autopay'
            if en else
            f'🔁 Premium продлён: списано {price}, следующее списание {when}. Отключить: /autopay')


def canceled_text(until: datetime | None, en: bool = False) -> str:
    when = fmt_date(until, en)
    if until and until > _now():
        return (f'Auto-renewal is off. Nothing more will be charged; Premium stays until {when} 💗'
                if en else
                f'Автопродление отключено. Больше ничего не спишется, Premium остаётся до {when} 💗')
    return ('Auto-renewal is off. Nothing more will be charged 💗' if en
            else 'Автопродление отключено. Больше ничего не спишется 💗')


def premium_until(telegram_id: int) -> datetime | None:
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            return None
        return s.scalar(select(Subscription.expires_at).where(
            Subscription.user_id == user.id, Subscription.status == 'active',
        ).order_by(Subscription.expires_at.desc()).limit(1))
