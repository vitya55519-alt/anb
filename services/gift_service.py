"""V3.55.5: daily streak gift + promo code redemption.

The streak gift replaces the V3.44.0 bonus wheel: days 1..6 pay
DAILY_GIFT_DAY_AMOUNT 🍑, every DAILY_GIFT_JACKPOT_DAY-th day pays
DAILY_GIFT_JACKPOT_AMOUNT, then the cycle restarts. A missed day resets the
streak to 1. The day boundary is 03:00 MSK — Moscow has no DST (fixed UTC+3),
so 03:00 local is exactly the UTC midnight: key = (now_msk - 3h).date()
collapses to now_utc.date().
If the balance already sits at or above DAILY_GIFT_BALANCE_CAP the claim is
refused WITHOUT consuming the day: the user spends first, then claims.

Payouts ride the existing payments.grant_photo_credits rail — idempotent per
(reason, user) — so the day-scoped reason `daily_gift_<iso>` is the money-side
guard and `gift_last_day` (updated in the same guarded UPDATE) is the
series-side guard. Promo grants use reason `promo_<CODE>` → one redemption per
user per code, ever. Analytics rides ProductEvent via track_event; the promo
source_tag feeds the existing acquisition attribution.
"""
import logging
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import or_, select, update

from config import (
    DAILY_GIFT_ENABLED,
    DAILY_GIFT_DAY_AMOUNT,
    DAILY_GIFT_JACKPOT_DAY,
    DAILY_GIFT_JACKPOT_AMOUNT,
    DAILY_GIFT_BALANCE_CAP,
    PROMO_WELCOME_ENABLED,
    PROMO_WELCOME_CODE,
    PROMO_WELCOME_CREDITS,
    PROMO_WELCOME_CAP,
)
from services.db import SessionLocal
from models.app_models import PromoCode, User
from services.analytics_service import track_event
from services.consent_service import has_accepted
from services.payments import grant_photo_credits
from services.user_service import ensure_user

logger = logging.getLogger(__name__)

# upper/strip normalisation happens before this gate; anything odd is simply
# "unknown code" — no enumeration signal about format vs existence.
PROMO_CODE_RE = re.compile(r'^[A-Z0-9]{4,24}$')


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def gift_day_key(now: datetime | None = None) -> date:
    """Day key with the fixed 03:00 MSK boundary — matches the competitor's
    «Обновится в 03:00» ritual window. (now_msk - 3h).date() on a UTC+3-with-no
    DST clock is just the naive UTC date."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is not None:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)
    return now.date()


def _payout_for(streak: int) -> int:
    return DAILY_GIFT_JACKPOT_AMOUNT if streak and streak % DAILY_GIFT_JACKPOT_DAY == 0 else DAILY_GIFT_DAY_AMOUNT


def _slot(streak: int) -> int:
    """Raw streak (grows forever while the user keeps the habit) → display day
    1..7 of the current cycle: 7 → 7, 8 → 1, 14 → 7. 0 = nothing earned yet."""
    streak = int(streak or 0)
    if streak <= 0:
        return 0
    slot = streak % DAILY_GIFT_JACKPOT_DAY
    return slot if slot else DAILY_GIFT_JACKPOT_DAY


def gift_status(telegram_id: int) -> dict:
    """Read-only status for /profile and api_me. Never mutates anything."""
    key = gift_day_key()
    claimed_today = False
    streak = 0
    capped = False
    try:
        with SessionLocal() as s:
            user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
            if not user:
                return {'enabled': DAILY_GIFT_ENABLED, 'available': False,
                        'claimed_today': False, 'streak': 0, 'capped': False, 'amount': 0}
            claimed_today = user.gift_last_day == key
            if claimed_today:
                streak = int(user.gift_streak or 0)
            elif user.gift_last_day == key - timedelta(days=1):
                # series alive — show the days banked so far, next claim adds one
                streak = int(user.gift_streak or 0)
            else:
                # missed day (or first-ever): the series restarts from 1
                streak = 0
            capped = int(user.photo_credits or 0) >= DAILY_GIFT_BALANCE_CAP
            next_streak = streak + 1 if not claimed_today else 0
    except Exception:
        logger.exception('gift_status failed user=%s', telegram_id)
        return {'enabled': DAILY_GIFT_ENABLED, 'available': False,
                'claimed_today': False, 'streak': 0, 'capped': False, 'amount': 0}
    amount = _payout_for(next_streak) if next_streak else 0
    available = bool(DAILY_GIFT_ENABLED and not claimed_today and not capped and has_accepted(telegram_id))
    return {'enabled': DAILY_GIFT_ENABLED, 'available': available,
            'claimed_today': claimed_today, 'streak': _slot(streak), 'capped': capped,
            'amount': amount}


def claim_daily_gift(telegram_id: int) -> dict:
    """Consume today's gift: guarded once-per-day UPDATE of the series columns,
    then the idempotent credit grant. Returns
    {ok, amount, streak, balance, capped, error?}."""
    if not DAILY_GIFT_ENABLED:
        return {'ok': False, 'error': 'inactive', 'amount': 0, 'streak': 0, 'balance': 0, 'capped': False}
    if not has_accepted(telegram_id):
        return {'ok': False, 'error': 'consent', 'amount': 0, 'streak': 0, 'balance': 0, 'capped': False}
    key = gift_day_key()
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            return {'ok': False, 'error': 'auth', 'amount': 0, 'streak': 0, 'balance': 0, 'capped': False}
        if int(user.photo_credits or 0) >= DAILY_GIFT_BALANCE_CAP:
            # копилка полная — day is NOT consumed, streak does not move
            return {'ok': False, 'capped': True, 'error': 'capped',
                    'amount': 0, 'streak': _slot(user.gift_streak),
                    'balance': int(user.photo_credits or 0)}
        streak = (int(user.gift_streak or 0) + 1) if user.gift_last_day == key - timedelta(days=1) else 1
        amount = _payout_for(streak)
        res = s.execute(
            update(User)
            .where(
                User.telegram_id == str(telegram_id),
                or_(User.gift_last_day.is_(None), User.gift_last_day < key),
            )
            .values(gift_last_day=key, gift_streak=streak)
        )
        s.commit()
        if not res.rowcount:
            return {'ok': False, 'error': 'duplicate', 'amount': 0,
                    'streak': _slot(user.gift_streak), 'balance': int(user.photo_credits or 0),
                    'capped': False}
    balance = grant_photo_credits(telegram_id, amount, reason=f'daily_gift_{key.isoformat()}')
    if balance < 0:
        # marker already exists (crash between grant and response, replayed
        # day key): the money did land, treat as claimed, do not roll back the
        # streak — rolling back would let the series farm the next day twice.
        status = gift_status(telegram_id)
        return {'ok': False, 'error': 'duplicate', 'amount': 0, 'streak': status['streak'],
                'balance': balance_amount(telegram_id), 'capped': False}
    track_event(ensure_user(telegram_id), 'daily_gift', metadata={'streak': streak, 'amount': amount})
    return {'ok': True, 'amount': amount, 'streak': _slot(streak), 'balance': int(balance), 'capped': False}


def balance_amount(telegram_id: int) -> int:
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        return int(user.photo_credits or 0) if user else 0


def ensure_welcome_promo() -> None:
    """V3.55.5: seed the welcome shelf once per DB — idempotent on every boot.
    Economics: the streak-gift cap (15 🍑) plus this code (5 🍑) reaches the
    20 🍑 studio video, so the free rails can actually afford the cheapest
    paid render. Admin can toggle the row off later in «🎟 Промокоды»."""
    if not PROMO_WELCOME_ENABLED:
        return
    code = _normalize_code(PROMO_WELCOME_CODE)
    if not PROMO_CODE_RE.match(code):
        logger.warning('welcome promo code %r rejected by the format gate', PROMO_WELCOME_CODE)
        return
    try:
        with SessionLocal() as s:
            if s.scalar(select(PromoCode).where(PromoCode.code == code)):
                return
            s.add(PromoCode(code=code, credits=PROMO_WELCOME_CREDITS,
                            max_activations=PROMO_WELCOME_CAP, activated_count=0,
                            expires_at=None, source_tag='welcome', active=True))
            s.commit()
            logger.info('welcome promo seeded: %s +%s 🍑 cap=%s',
                        code, PROMO_WELCOME_CREDITS, PROMO_WELCOME_CAP)
    except Exception:
        logger.exception('welcome promo seed failed')


def _normalize_code(raw: str | None) -> str:
    return (raw or '').strip().upper()


def _decrement_activation(pc_id: int) -> None:
    """Give the reserved activation slot back when the grant did not land
    (duplicate user / unknown user). Floor at 0 — never negative."""
    try:
        with SessionLocal() as s:
            s.execute(
                update(PromoCode)
                .where(PromoCode.id == pc_id, PromoCode.activated_count > 0)
                .values(activated_count=PromoCode.activated_count - 1)
            )
            s.commit()
    except Exception:
        logger.exception('promo activation decrement failed id=%s', pc_id)


def redeem_promo(telegram_id: int, raw_code: str) -> dict:
    """Redeem a promo code for photo credits. One per user per code (grant
    idempotency), global cap enforced atomically. Returns
    {ok, credits, balance, error?} with errors:
    consent/unknown/expired/exhausted/inactive/duplicate/auth."""
    code = _normalize_code(raw_code)
    if not has_accepted(telegram_id):
        return {'ok': False, 'error': 'consent', 'credits': 0}
    if not PROMO_CODE_RE.match(code):
        return {'ok': False, 'error': 'unknown', 'credits': 0}
    with SessionLocal() as s:
        pc = s.scalar(select(PromoCode).where(PromoCode.code == code))
        if not pc:
            return {'ok': False, 'error': 'unknown', 'credits': 0}
        if not pc.active:
            return {'ok': False, 'error': 'inactive', 'credits': 0}
        if pc.expires_at is not None and pc.expires_at < _utcnow():
            return {'ok': False, 'error': 'expired', 'credits': 0}
        pc_id, credits, src = pc.id, int(pc.credits or 0), (pc.source_tag or '')
        # atomic reserve: only succeeds while the global cap still has room
        res = s.execute(
            update(PromoCode)
            .where(
                PromoCode.id == pc_id,
                PromoCode.active.is_(True),
                or_(PromoCode.max_activations == 0, PromoCode.activated_count < PromoCode.max_activations),
            )
            .values(activated_count=PromoCode.activated_count + 1)
        )
        s.commit()
        if not res.rowcount:
            return {'ok': False, 'error': 'exhausted', 'credits': 0}
    balance = grant_photo_credits(telegram_id, credits, reason=f'promo_{code}')
    if balance == 0:
        _decrement_activation(pc_id)
        return {'ok': False, 'error': 'auth', 'credits': 0}
    if balance == -1:
        _decrement_activation(pc_id)
        return {'ok': False, 'error': 'duplicate', 'credits': 0}
    track_event(ensure_user(telegram_id), 'promo_redeem', metadata={'code': code, 'src': src})
    return {'ok': True, 'credits': credits, 'balance': int(balance)}
