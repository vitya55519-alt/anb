"""V3.162.0 (owner, after the 13 Nov dump): «Раздеть» only for bought peaches,
and a picture from her ready pool no longer spends the one free photo a day."""
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config
from services import chat_photo_allowance as A
from services import trial_caps as T

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def _sub(days: float, product: str):
    from services.db import SessionLocal
    from services.user_service import ensure_user
    from models.app_models import Subscription, StarTransaction
    tid = 812000000 + uuid.uuid4().int % 9999999
    uid = ensure_user(tid, 'V')
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    charge = f'v{tid}'
    with SessionLocal() as s:
        s.add(Subscription(user_id=uid, plan='premium', status='active', stars_amount=0,
                           started_at=now - timedelta(minutes=1), expires_at=now + timedelta(days=days),
                           telegram_charge_id=charge))
        s.add(StarTransaction(user_id=uid, transaction_type='purchase', product=product, stars=1,
                             telegram_charge_id=charge))
        s.commit()
    return tid, uid


def test_trial_has_no_free_undress_but_paid_plans_keep_theirs():
    assert T.CAPS['demo']['undress'] == 0 and T.CAPS['trial']['undress'] == 0
    assert T.CAPS['week']['undress'] == 2 and T.CAPS['month']['undress'] == 6
    # the price he does pay is untouched — owner: «персики покупать не лезь в это»
    assert config.UNDRESS_PEACH_COST == 400
    assert '«Раздеть»' not in T.plan_line('trial')


def test_trial_undress_gate_never_offers_the_free_route():
    _, uid = _sub(3, 'premium_trial')
    # allowance == what was already used, so `used < allowance` is never true
    assert T.undress_allowance_today(uid, 0) == 0
    assert T.undress_allowance_today(uid, 4) == 4
    _, paid_uid = _sub(30, 'premium_month')
    assert T.undress_allowance_today(paid_uid, 0) == 6


def test_pool_photo_leaves_the_free_render_alone():
    from services.user_service import ensure_user
    uid = ensure_user(812999001, 'P')
    left = A.free_chat_photos_left(uid, False)
    A.use_pool_photo(uid, 'anna_01')
    assert A.free_chat_photos_left(uid, False) == left
    assert A.pool_photos_left(uid) == config.CHAT_POOL_PHOTOS_PER_DAY - 1
    A.use_pool_photo(uid, 'anna_01')
    assert A.pool_photos_left(uid) == max(0, config.CHAT_POOL_PHOTOS_PER_DAY - 2)


def test_bot_and_app_pay_the_pool_from_its_own_quota():
    assert 'use_pool_photo, db_uid, character_id' in MAIN      # telegram chat
    assert 'use_pool_photo(uid, character_id)' in MAIN          # mini app chat
    assert 'await asyncio.to_thread(pool_photos_left, db_uid) > 0' in MAIN
    assert 'if pool_photos_left(uid) <= 0:' in MAIN             # _free_photo_from_pool
    # the old double accounting (pool frame + free photo of the day) is gone
    assert MAIN.count('note_today(uid, POOL_EVENT, character_id)') == 0
    assert MAIN.count('note_today, db_uid, POOL_EVENT') == 0
