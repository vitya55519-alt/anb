"""V3.123.0: bought vs bonus peaches — renders take bought ones only."""
import os
import uuid

os.environ.setdefault('TELEGRAM_TOKEN', '123:abc')


def _user():
    from services.user_service import ensure_user
    tid = 900000000 + uuid.uuid4().int % 99999999
    ensure_user(tid, 'T')
    return tid


def _set(tid, paid, bonus):
    from services.db import SessionLocal
    from models.app_models import User
    from sqlalchemy import select
    with SessionLocal() as s:
        u = s.scalar(select(User).where(User.telegram_id == str(tid)))
        u.photo_credits, u.bonus_peaches = paid, bonus
        s.commit()


def test_render_spend_ignores_bonus():
    from services.payments import spend_peaches, peach_wallet
    tid = _user(); _set(tid, 100, 500)
    assert not spend_peaches(tid, 300, paid_only=True)
    assert peach_wallet(tid) == {'paid': 100, 'bonus': 500, 'total': 600}
    _set(tid, 400, 500)
    assert spend_peaches(tid, 300, paid_only=True)
    assert peach_wallet(tid) == {'paid': 100, 'bonus': 500, 'total': 600}


def test_other_spend_takes_bonus_first_then_paid():
    from services.payments import spend_peaches, peach_wallet
    tid = _user(); _set(tid, 1000, 300)
    assert spend_peaches(tid, 500)
    assert peach_wallet(tid) == {'paid': 800, 'bonus': 0, 'total': 800}
    assert not spend_peaches(tid, 900)
    assert spend_peaches(tid, 200)
    assert peach_wallet(tid)['paid'] == 600


def test_grants_land_in_bonus_and_refunds_in_paid():
    from services.payments import grant_photo_credits, peach_wallet
    tid = _user(); _set(tid, 0, 0)
    assert grant_photo_credits(tid, 100, reason='t_mission') == 100
    assert grant_photo_credits(tid, 200, reason='t_refund', bonus=False) == 300
    assert peach_wallet(tid) == {'paid': 200, 'bonus': 100, 'total': 300}


def test_chat_photo_price_is_300():
    from config import CHAT_PHOTO_PEACH_COST, CHAT_PREMIUM_PHOTOS_PER_DAY
    if 'CHAT_PHOTO_PRICE_PEACHES' not in os.environ:
        assert CHAT_PHOTO_PEACH_COST == 300
    if 'CHAT_PREMIUM_PHOTOS_PER_DAY' not in os.environ:
        assert CHAT_PREMIUM_PHOTOS_PER_DAY == 2
