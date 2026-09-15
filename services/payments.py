from datetime import datetime, timedelta, timezone
import logging
from sqlalchemy import select
from services.db import SessionLocal
from models.app_models import Subscription, StarTransaction, User
from config import PREMIUM_MONTHLY_STARS, PREMIUM_MONTHLY_PHOTO_CREDITS, PREMIUM_WEEKLY_STARS, PREMIUM_WEEKLY_PHOTO_CREDITS, PHOTO_COST_STARS, CUSTOM_PHOTO_COST_STARS, VIDEO_COST_STARS, VIDEO_PREMIUM_FREE_DAILY, PREMIUM_DISCOUNT_STARS
from services.access_service import is_premium

logger = logging.getLogger(__name__)

PRODUCTS={"photo":PHOTO_COST_STARS,"custom_photo":CUSTOM_PHOTO_COST_STARS,"premium_month":PREMIUM_MONTHLY_STARS,"premium_month_discount":PREMIUM_DISCOUNT_STARS,"premium_week":PREMIUM_WEEKLY_STARS,"video":VIDEO_COST_STARS}

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
        if product in {"premium_month","premium_month_discount","premium_week"}:
            # V3.34.1: premium_week grants 7 days + the weekly credit share;
            # the monthly plans keep 30 days + the monthly share.
            days=7 if product=="premium_week" else 30
            credits=PREMIUM_WEEKLY_PHOTO_CREDITS if product=="premium_week" else PREMIUM_MONTHLY_PHOTO_CREDITS
            current=s.scalar(select(Subscription).where(Subscription.user_id==user.id,Subscription.status=="active",Subscription.expires_at>now).order_by(Subscription.expires_at.desc()))
            start=current.expires_at if current and current.expires_at and current.expires_at>now else now
            s.add(Subscription(user_id=user.id,plan="premium",status="active",stars_amount=stars,started_at=now,expires_at=start+timedelta(days=days),telegram_charge_id=charge_id))
            user.photo_credits=(user.photo_credits or 0)+credits
            try:
                from services.gamification_service import unlock_achievement
                unlock_achievement(telegram_id, 'premium_member')
            except Exception:
                pass
        elif product in {"photo","custom_photo"}:
            user.photo_credits=(user.photo_credits or 0)+1
        s.commit()
        payer_user_id = user.id
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
    with SessionLocal() as s:
        user=s.scalar(select(User).where(User.telegram_id==str(telegram_id)))
        if not user or (user.photo_credits or 0)<=0: return False
        user.photo_credits-=1; s.commit(); return True

def get_photo_credits(telegram_id:int)->int:
    with SessionLocal() as s:
        user=s.scalar(select(User).where(User.telegram_id==str(telegram_id)))
        return int(user.photo_credits or 0) if user else 0


def grant_photo_credits(telegram_id:int, amount:int, reason:str="bonus")->int:
    """Add bonus photo credits to a user. Idempotent per (reason, user): a second
    call with the same reason is a no-op and returns -1, so milestone/streak
    rewards can never be double-granted even if the triggering code runs twice.
    Returns the new balance, 0 if the user is unknown, or -1 if already granted.
    """
    marker=f"credit_grant:{reason}:{telegram_id}"
    with SessionLocal() as s:
        if s.scalar(select(StarTransaction).where(StarTransaction.telegram_charge_id==marker)):
            return -1
        user=s.scalar(select(User).where(User.telegram_id==str(telegram_id)))
        if not user:
            return 0
        user.photo_credits=(user.photo_credits or 0)+max(0,int(amount))
        s.add(StarTransaction(user_id=user.id,transaction_type="grant",product=reason,stars=0,telegram_charge_id=marker))
        s.commit()
        return int(user.photo_credits or 0)


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
        user.photo_credits=(user.photo_credits or 0)+PREMIUM_MONTHLY_PHOTO_CREDITS
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


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def premium_video_free_left(telegram_id: int) -> int:
    """Free photo-animation slots left today for a Premium user."""
    if not VIDEO_PREMIUM_FREE_DAILY or not is_premium(telegram_id):
        return 0
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            return 0
        if (user.video_free_date or '') != _today_utc():
            return VIDEO_PREMIUM_FREE_DAILY
        return max(0, VIDEO_PREMIUM_FREE_DAILY - int(user.video_free_used or 0))


def consume_premium_video_free(telegram_id: int) -> bool:
    """Atomically consume one free Premium animation slot for today."""
    if not VIDEO_PREMIUM_FREE_DAILY or not is_premium(telegram_id):
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
        user.video_free_used = int(user.video_free_used or 0) + 1
        s.commit()
        return True
