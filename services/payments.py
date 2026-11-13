from datetime import datetime, timedelta, timezone
import logging
from sqlalchemy import case, func, select, update
from sqlalchemy.exc import IntegrityError
from services.db import SessionLocal
from models.app_models import Subscription, StarTransaction, User
from config import PREMIUM_TRIAL_STARS, PREMIUM_TRIAL_DAYS, PREMIUM_MONTHLY_STARS, PREMIUM_MONTHLY_PHOTO_CREDITS, PREMIUM_WEEKLY_STARS, PREMIUM_WEEKLY_PHOTO_CREDITS, PREMIUM_QUARTERLY_STARS, PREMIUM_QUARTERLY_PHOTO_CREDITS, PHOTO_COST_STARS, CUSTOM_PHOTO_COST_STARS, VIDEO_COST_STARS, VIDEO_PREMIUM_FREE_DAILY, PREMIUM_DISCOUNT_STARS, PEACH_PACK_10_STARS, PEACH_PACK_30_STARS, PEACH_PACK_100_STARS, PEACH_PACK_CREDITS, PEACH_SCALE, PEACH_CUSTOM_UNIT
from services.access_service import is_premium

logger = logging.getLogger(__name__)

def _credits_plus(amount):
    """V3.58.0: «balance + amount» evaluated inside the UPDATE, so a top-up
    racing a spend can never overwrite it with a stale balance."""
    return func.coalesce(User.photo_credits, 0) + int(amount)


def _bonus_plus(amount):
    """V3.123.0: same atomic «+amount» for the bonus wallet."""
    return func.coalesce(User.bonus_peaches, 0) + int(amount)

PRODUCTS={"photo":PHOTO_COST_STARS,"custom_photo":CUSTOM_PHOTO_COST_STARS,"premium_month":PREMIUM_MONTHLY_STARS,"premium_month_discount":PREMIUM_DISCOUNT_STARS,"premium_week":PREMIUM_WEEKLY_STARS,"premium_trial":PREMIUM_TRIAL_STARS,"premium_quarter":PREMIUM_QUARTERLY_STARS,"video":VIDEO_COST_STARS,"peach_pack_10":PEACH_PACK_10_STARS,"peach_pack_30":PEACH_PACK_30_STARS,"peach_pack_100":PEACH_PACK_100_STARS}

def trial_eligible(telegram_id: int) -> bool:
    """V3.88.0: the 3-day trial is for people who never bought Premium and
    are not Premium right now (one cheap first purchase per user)."""
    try:
        if is_premium(telegram_id):
            return False
        with SessionLocal() as s:
            user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
            if not user:
                return True
            bought = s.scalar(select(func.count(StarTransaction.id)).where(
                StarTransaction.user_id == user.id,
                StarTransaction.product.like('premium%')))
            return not bought
    except Exception:
        logger.exception('trial eligibility check failed user=%s', telegram_id)
        return False


def record_payment(telegram_id:int, product:str, stars:int, charge_id:str, provider:str="stars", provider_payload:str|None=None):
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    with SessionLocal() as s:
        if s.scalar(select(StarTransaction).where(StarTransaction.telegram_charge_id==charge_id)): return
        user=s.scalar(select(User).where(User.telegram_id==str(telegram_id)))
        if not user: raise ValueError("user not found")
        s.add(StarTransaction(
            user_id=user.id,
            transaction_type="purchase",
            product=product,
            stars=stars,
            telegram_charge_id=charge_id,
            provider=provider,
            provider_payload=provider_payload,
        ))
        if product in {"premium_month","premium_month_discount","premium_week","premium_quarter","premium_trial"} or product == "premium_month_vip":
            # V3.34.1: premium_week grants 7 days + the weekly credit share;
            # V3.43.0: premium_quarter grants 90 days + three credit shares;
            # the monthly plans keep 30 days + the monthly share.
            if product == "premium_week":
                days, credits = 7, PREMIUM_WEEKLY_PHOTO_CREDITS
            elif product == "premium_trial":
                # V3.88.0: the 99 ₽ first-purchase trial — Premium only, no gift.
                days, credits = PREMIUM_TRIAL_DAYS, 0
            elif product == "premium_quarter":
                days, credits = 90, PREMIUM_QUARTERLY_PHOTO_CREDITS
            else:
                days, credits = 30, PREMIUM_MONTHLY_PHOTO_CREDITS
            current=s.scalar(select(Subscription).where(Subscription.user_id==user.id,Subscription.status=="active",Subscription.expires_at>now).order_by(Subscription.expires_at.desc()))
            start=current.expires_at if current and current.expires_at and current.expires_at>now else now
            s.add(Subscription(user_id=user.id,plan="premium",status="active",stars_amount=stars,started_at=now,expires_at=start+timedelta(days=days),telegram_charge_id=charge_id))
            user.photo_credits=_credits_plus(credits)
            try:
                from services.gamification_service import unlock_achievement
                unlock_achievement(telegram_id, 'premium_member')
            except Exception:
                pass
        elif product == "undress_one":
            # V3.132.0: one «Раздеть» bought on its own (committed below with the ledger row).
            pass
        elif product in {"photo","custom_photo"}:
            # V3.65.0: one photo credit is PEACH_SCALE peaches now.
            user.photo_credits=_credits_plus(PEACH_SCALE)
        elif product in PEACH_PACK_CREDITS:
            # V3.43.1: the peach pack ladder grants the whole pack at once.
            user.photo_credits=_credits_plus(PEACH_PACK_CREDITS[product])
        elif product.startswith('peach_custom_'):
            # V3.44.23: the custom-peach tile — the count is encoded in the key.
            # V3.65.0: the key counts units of PEACH_CUSTOM_UNIT peaches.
            try:
                _n = max(1, int(product.split('_')[-1]))
            except (ValueError, IndexError):
                _n = 1
            user.photo_credits=_credits_plus(_n * PEACH_CUSTOM_UNIT)
        try:
            s.commit()
        except IntegrityError:
            # V3.58.0: a concurrent copy of the same payment callback won the
            # race on the unique telegram_charge_id — already credited once.
            s.rollback()
            logger.info('duplicate payment ignored charge=%s', charge_id)
            return
        payer_user_id = user.id
    if product == "undress_one":
        from services import undress_credits
        undress_credits.add(telegram_id, 1)
    # V3.37.0: after the purchase commits, credit the payer's referrer in the
    # partner ledger (money commission). Outside the payment transaction on
    # purpose — a ledger failure must never roll back the user's purchase.
    try:
        from services import partner_service
        partner_service.accrue_commission(
            payer_user_id, product, stars, charge_id, provider=provider, provider_payload=provider_payload,
        )
    except Exception:
        logger.exception('partner commission accrual failed user=%s charge=%s', telegram_id, charge_id)

def consume_photo_credit(telegram_id:int)->bool:
    # V3.65.0: one photo credit = PEACH_SCALE peaches.
    # V3.123.0: a photo is a paid render — bought peaches only.
    return spend_peaches(telegram_id, PEACH_SCALE, paid_only=True)


# V3.44.2: spend multiple peaches at once (e.g. for constructor)
def spend_peaches(telegram_id: int, amount: int, *, paid_only: bool = False) -> bool:
    """Deduct `amount` peaches from user balance. Returns True if successful.

    V3.58.0: one conditional UPDATE instead of read-then-write, so two taps
    landing at the same moment can never both pass the balance check and
    drive the balance negative (double spend).

    V3.123.0: owner — «баланс разделить: бонусный за задания и канал, и
    покупной». Two wallets: ``photo_credits`` holds bought peaches (packs,
    Premium gift, admin grants, refunds of paid spends) and ``bonus_peaches``
    holds the free ones (missions, channel, referrals, daily gift, promo).
    ``paid_only`` spends (every photo / video / circle render — the things
    that cost real money at SpicyAPI) take bought peaches only. Other spends
    (wardrobe, dates, constructor…) take the bonus first, then bought.
    Both columns are read before either is written inside the single UPDATE,
    so the split is exact and atomic."""
    amount = int(amount)
    if amount <= 0:
        return amount == 0
    paid = func.coalesce(User.photo_credits, 0)
    bonus = func.coalesce(User.bonus_peaches, 0)
    with SessionLocal() as s:
        if paid_only:
            stmt = (update(User)
                    .where(User.telegram_id == str(telegram_id), paid >= amount)
                    .values(photo_credits=paid - amount))
        else:
            from_bonus = case((bonus >= amount, amount), else_=bonus)
            stmt = (update(User)
                    .where(User.telegram_id == str(telegram_id), paid + bonus >= amount)
                    .values(bonus_peaches=bonus - from_bonus,
                            photo_credits=paid - (amount - from_bonus)))
        result = s.execute(stmt.execution_options(synchronize_session=False))
        s.commit()
        return result.rowcount == 1

def get_photo_credits(telegram_id:int)->int:
    """The whole peach balance (bought + bonus) — what the user sees."""
    with SessionLocal() as s:
        user=s.scalar(select(User).where(User.telegram_id==str(telegram_id)))
        return int((user.photo_credits or 0) + (user.bonus_peaches or 0)) if user else 0


def get_paid_peaches(telegram_id:int)->int:
    """V3.123.0: bought peaches only — what a render (paid_only) may spend."""
    with SessionLocal() as s:
        user=s.scalar(select(User).where(User.telegram_id==str(telegram_id)))
        return int(user.photo_credits or 0) if user else 0


def get_bonus_peaches(telegram_id:int)->int:
    with SessionLocal() as s:
        user=s.scalar(select(User).where(User.telegram_id==str(telegram_id)))
        return int(user.bonus_peaches or 0) if user else 0


def peach_wallet(telegram_id:int)->dict:
    """{'paid', 'bonus', 'total'} in one read for the UI."""
    with SessionLocal() as s:
        user=s.scalar(select(User).where(User.telegram_id==str(telegram_id)))
        paid=int(user.photo_credits or 0) if user else 0
        bonus=int(user.bonus_peaches or 0) if user else 0
        return {'paid': paid, 'bonus': bonus, 'total': paid + bonus}


def grant_photo_credits(telegram_id:int, amount:int, reason:str="bonus", *, bonus:bool=True)->int:
    """Add bonus photo credits to a user. Idempotent per (reason, user): a second
    call with the same reason is a no-op and returns -1, so milestone/streak
    rewards can never be double-granted even if the triggering code runs twice.
    Returns the new balance, 0 if the user is unknown, or -1 if already granted.

    V3.123.0: lands in the bonus wallet by default (missions, channel, streaks,
    promo, scenario taps); ``bonus=False`` for refunds of bought peaches.
    """
    marker=f"credit_grant:{reason}:{telegram_id}"
    with SessionLocal() as s:
        if s.scalar(select(StarTransaction).where(StarTransaction.telegram_charge_id==marker)):
            return -1
        user=s.scalar(select(User).where(User.telegram_id==str(telegram_id)))
        if not user:
            return 0
        if bonus:
            user.bonus_peaches=_bonus_plus(max(0,int(amount)))
        else:
            user.photo_credits=_credits_plus(max(0,int(amount)))
        s.add(StarTransaction(user_id=user.id,transaction_type="grant",product=reason,stars=0,telegram_charge_id=marker))
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            return -1
        s.refresh(user)
        return int((user.photo_credits or 0) + (user.bonus_peaches or 0))


def has_credit_grant(telegram_id:int, reason:str)->bool:
    """V3.43.0: whether a reason-marker grant already landed — lets the UI show
    «bonus already received» without triggering the grant itself."""
    marker=f"credit_grant:{reason}:{telegram_id}"
    with SessionLocal() as s:
        return bool(s.scalar(select(StarTransaction).where(StarTransaction.telegram_charge_id==marker)))


def revoke_photo_credits(telegram_id:int, amount:int, reason:str)->int:
    """V3.43.0: mirror of grant_photo_credits for the channel bonus — «при
    отписке бонус аннулируется». Subtracts the bonus (never below zero) and
    drops the marker so re-subscribing can grant it again. Returns the new
    balance, or -1 when there was nothing to revoke."""
    marker=f"credit_grant:{reason}:{telegram_id}"
    with SessionLocal() as s:
        tx=s.scalar(select(StarTransaction).where(StarTransaction.telegram_charge_id==marker))
        if not tx: return -1
        user=s.scalar(select(User).where(User.telegram_id==str(telegram_id)))
        if not user: return -1
        s.delete(tx)
        amount=max(0, int(amount))
        # V3.123.0: the channel bonus lives in the bonus wallet — take it back
        # from there first, the remainder (if he already spent it) from bought.
        from_bonus=min(int(user.bonus_peaches or 0), amount)
        user.bonus_peaches=int(user.bonus_peaches or 0)-from_bonus
        user.photo_credits=max(0, (user.photo_credits or 0)-(amount-from_bonus))
        s.commit()
        return int((user.photo_credits or 0) + (user.bonus_peaches or 0))


def record_refund(telegram_id:int, charge_id:str, stars:int=0, product:str='refund'):
    with SessionLocal() as s:
        user=s.scalar(select(User).where(User.telegram_id==str(telegram_id)))
        if not user: return False
        marker=f'refund:{charge_id}'
        if s.scalar(select(StarTransaction).where(StarTransaction.telegram_charge_id==marker)): return True
        s.add(StarTransaction(user_id=user.id,transaction_type='refund',product=product,stars=-abs(int(stars or 0)),telegram_charge_id=marker))
        s.commit(); return True


def grant_premium(telegram_id:int, days:int=30)->bool:
    """Admin tool: activate Premium for testing without a real Stars payment."""
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    with SessionLocal() as s:
        user=s.scalar(select(User).where(User.telegram_id==str(telegram_id)))
        if not user: return False
        if s.scalar(select(Subscription).where(Subscription.user_id==user.id,Subscription.status=="active",Subscription.expires_at>now)):
            return True
        s.add(Subscription(user_id=user.id,plan="premium",status="active",stars_amount=0,started_at=now,expires_at=now+timedelta(days=days),telegram_charge_id=f"admin_grant:{int(now.timestamp())}"))
        user.photo_credits=_credits_plus(PREMIUM_MONTHLY_PHOTO_CREDITS)
        s.commit(); return True


def revoke_premium(telegram_id:int)->bool:
    """Admin tool: turn Premium off for testing. Photo credits are kept."""
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    with SessionLocal() as s:
        user=s.scalar(select(User).where(User.telegram_id==str(telegram_id)))
        if not user: return False
        active=s.scalars(select(Subscription).where(Subscription.user_id==user.id,Subscription.status=="active",Subscription.expires_at>now)).all()
        if not active: return False
        for sub in active:
            sub.status='cancelled'; sub.expires_at=now
        s.commit(); return True


def expire_stale_subscriptions() -> int:
    """V3.159.1: in the 13.11 dump every one of the 31 subscription rows said
    'active', 29 of them expired months ago. Nothing grants Premium from them
    (all readers compare expires_at), so the state was only ever lying — to the
    owner reading a dump and to any query that forgets the date. Stamp the
    truth once a day instead of filtering around it forever."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with SessionLocal() as s:
        rows = s.scalars(select(Subscription).where(
            Subscription.status == "active",
            Subscription.expires_at.is_not(None),
            Subscription.expires_at <= now,
        )).all()
        for sub in rows:
            sub.status = 'expired'
        s.commit()
        return len(rows)


def revoke_all_premium()->int:
    """V3.56.0 admin tool: cancel every currently-active Premium subscription in
    one shot (the test/admin grants). History rows are kept and photo credits
    are left untouched — only the live entitlement is pulled. Returns the number
    of subscriptions revoked."""
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    with SessionLocal() as s:
        active=s.scalars(select(Subscription).where(Subscription.status=="active",Subscription.expires_at>now)).all()
        for sub in active:
            sub.status='cancelled'; sub.expires_at=now
        s.commit()
        return len(active)


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def has_monthly_premium(telegram_id: int) -> bool:
    """V3.112.0: an active Premium bought for a month or longer (month,
    discounted / VIP month, quarter, or an admin grant of 28+ days). The
    3-day trial, the week and the free demo do not count."""
    from config import VIDEO_MIN_PLAN_DAYS
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        with SessionLocal() as s:
            user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
            if not user:
                return False
            subs = s.scalars(select(Subscription).where(
                Subscription.user_id == user.id, Subscription.status == "active",
                Subscription.expires_at > now)).all()
            for sub in subs:
                if sub.started_at and sub.expires_at and \
                        sub.expires_at - sub.started_at >= timedelta(days=VIDEO_MIN_PLAN_DAYS):
                    return True
            return False
    except Exception:
        logger.exception('monthly premium check failed user=%s', telegram_id)
        return False


def premium_video_free_left(telegram_id: int) -> int:
    """Photo-animation slots left today (monthly Premium only, V3.112.0)."""
    if not VIDEO_PREMIUM_FREE_DAILY or not has_monthly_premium(telegram_id):
        return 0
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            return 0
        if (user.video_free_date or '') != _today_utc():
            return VIDEO_PREMIUM_FREE_DAILY
        return max(0, VIDEO_PREMIUM_FREE_DAILY - int(user.video_free_used or 0))


def consume_premium_video_free(telegram_id: int) -> bool:
    """Atomically consume one monthly-Premium animation slot for today."""
    if not VIDEO_PREMIUM_FREE_DAILY or not has_monthly_premium(telegram_id):
        return False
    today = _today_utc()
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            return False
        if (user.video_free_date or '') != today:
            user.video_free_date = today
            user.video_free_used = 0
        if int(user.video_free_used or 0) >= VIDEO_PREMIUM_FREE_DAILY:
            s.commit()
            return False
        # V3.124.0: the plan's animation total (month 2, quarter 4 by default).
        from services import trial_caps
        if not trial_caps.take_animation(telegram_id):
            s.commit()
            return False
        user.video_free_used = int(user.video_free_used or 0) + 1
        s.commit()
        return True
