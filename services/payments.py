from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from services.db import SessionLocal
from models.app_models import Subscription, StarTransaction
from config import PREMIUM_MONTHLY_STARS, PHOTO_COST_STARS, VOICE_COST_STARS

PRODUCTS = {
    "photo": PHOTO_COST_STARS,
    "voice": VOICE_COST_STARS,
    "premium_month": PREMIUM_MONTHLY_STARS,
}

def record_payment(user_id: int, product: str, stars: int, charge_id: str):
    with SessionLocal() as s:
        if s.scalar(select(StarTransaction).where(StarTransaction.telegram_charge_id == charge_id)):
            return
        s.add(StarTransaction(user_id=user_id, transaction_type="purchase", product=product,
                              stars=stars, telegram_charge_id=charge_id))
        if product == "premium_month":
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            s.add(Subscription(user_id=user_id, plan="premium", status="active", stars_amount=stars,
                               started_at=now, expires_at=now + timedelta(days=30),
                               telegram_charge_id=charge_id, auto_renew=True))
        s.commit()
