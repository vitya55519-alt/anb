from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from services.db import SessionLocal
from models.app_models import Subscription, StarTransaction, User
from config import PREMIUM_MONTHLY_STARS, PREMIUM_MONTHLY_PHOTO_CREDITS, PHOTO_COST_STARS, CUSTOM_PHOTO_COST_STARS, VIDEO_COST_STARS

PRODUCTS={"photo":PHOTO_COST_STARS,"custom_photo":CUSTOM_PHOTO_COST_STARS,"premium_month":PREMIUM_MONTHLY_STARS,"video":VIDEO_COST_STARS}

def record_payment(telegram_id:int, product:str, stars:int, charge_id:str):
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    with SessionLocal() as s:
        if s.scalar(select(StarTransaction).where(StarTransaction.telegram_charge_id==charge_id)): return
        user=s.scalar(select(User).where(User.telegram_id==str(telegram_id)))
        if not user: raise ValueError("user not found")
        s.add(StarTransaction(user_id=user.id,transaction_type="purchase",product=product,stars=stars,telegram_charge_id=charge_id))
        if product=="premium_month":
            current=s.scalar(select(Subscription).where(Subscription.user_id==user.id,Subscription.status=="active",Subscription.expires_at>now).order_by(Subscription.expires_at.desc()))
            start=current.expires_at if current and current.expires_at and current.expires_at>now else now
            s.add(Subscription(user_id=user.id,plan="premium",status="active",stars_amount=stars,started_at=now,expires_at=start+timedelta(days=30),telegram_charge_id=charge_id))
            user.photo_credits=(user.photo_credits or 0)+PREMIUM_MONTHLY_PHOTO_CREDITS
        elif product in {"photo","custom_photo"}:
            user.photo_credits=(user.photo_credits or 0)+1
        s.commit()

def consume_photo_credit(telegram_id:int)->bool:
    with SessionLocal() as s:
        user=s.scalar(select(User).where(User.telegram_id==str(telegram_id)))
        if not user or (user.photo_credits or 0)<=0: return False
        user.photo_credits-=1; s.commit(); return True

def get_photo_credits(telegram_id:int)->int:
    with SessionLocal() as s:
        user=s.scalar(select(User).where(User.telegram_id==str(telegram_id)))
        return int(user.photo_credits or 0) if user else 0


def record_refund(telegram_id:int, charge_id:str, stars:int=0, product:str='refund'):
    with SessionLocal() as s:
        user=s.scalar(select(User).where(User.telegram_id==str(telegram_id)))
        if not user: return False
        marker=f'refund:{charge_id}'
        if s.scalar(select(StarTransaction).where(StarTransaction.telegram_charge_id==marker)): return True
        s.add(StarTransaction(user_id=user.id,transaction_type='refund',product=product,stars=-abs(int(stars or 0)),telegram_charge_id=marker))
        s.commit(); return True
