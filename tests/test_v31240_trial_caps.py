"""Every Premium plan holds a media total for its term; text is unlimited."""
import os
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault('TELEGRAM_TOKEN', '123:abc')
os.environ.setdefault('GEMINI_API_KEY', 'x')


def _user_with_plan(days: float, product: str | None = None):
    from services.user_service import ensure_user
    from services.db import SessionLocal
    from models.app_models import Subscription, StarTransaction
    tid = 800000000 + uuid.uuid4().int % 99999999
    uid = ensure_user(tid, 'T')
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    charge = f't{tid}'
    with SessionLocal() as s:
        s.add(Subscription(user_id=uid, plan='premium', status='active', stars_amount=0,
                           started_at=now - timedelta(minutes=1), expires_at=now + timedelta(days=days),
                           telegram_charge_id=charge))
        if product:
            s.add(StarTransaction(user_id=uid, transaction_type='purchase', product=product, stars=1,
                                  telegram_charge_id=charge))
        s.commit()
    return tid, uid


def _msgs(uid, n):
    from services.db import SessionLocal
    from models.app_models import Message
    with SessionLocal() as s:
        for _ in range(n):
            s.add(Message(user_id=uid, character_id='anna', role='user', content='hi'))
        s.commit()


def test_trial_messages_unlimited_but_media_stays_capped():
    from services import trial_caps as T
    from services.access_service import can_send_message
    tid, uid = _user_with_plan(3, 'premium_trial')
    assert T.window_start_uid(uid) is not None
    assert T.CAPS['trial']['messages'] == -1
    assert T.messages_left(uid) is None
    _msgs(uid, 500)
    assert can_send_message(tid)
    assert T.photos_left(uid, 'chat_free_photo') == T.CAPS['trial']['photos']
    # V3.162.0: owner — «раздеть только за платные персики»: the trial gives none away.
    assert T.CAPS['trial']['undress'] == 0
    assert T.CAPS['month']['undress'] == 6
    assert T.CAPS['trial']['voice'] == 10


def test_paid_plans_unlimited_messages_but_capped_media():
    from services import trial_caps as T, voice_call
    from services.access_service import can_send_message
    from services.analytics_service import track_event
    tid, uid = _user_with_plan(7, 'premium_week')
    assert T.window_start_uid(uid) is None
    _msgs(uid, 500)
    assert can_send_message(tid)
    assert T.photos_left(uid, 'chat_free_photo') == T.CAPS['week']['photos']
    track_event(uid, voice_call.EVENT_PREMIUM, value=float(T.CAPS['week']['call_seconds']))
    assert voice_call.seconds_left(uid, 'premium') == 0


def test_renewal_adds_allowances():
    from services import trial_caps as T
    from services.db import SessionLocal
    from models.app_models import Subscription, StarTransaction
    tid, uid = _user_with_plan(30, 'premium_month')
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with SessionLocal() as s:
        s.add(Subscription(user_id=uid, plan='premium', status='active', stars_amount=0,
                           started_at=now, expires_at=now + timedelta(days=37), telegram_charge_id=f'w{tid}'))
        s.add(StarTransaction(user_id=uid, transaction_type='purchase', product='premium_week', stars=1,
                              telegram_charge_id=f'w{tid}'))
        s.commit()
    assert T.plan_uid(uid)[1]['photos'] == T.CAPS['month']['photos'] + T.CAPS['week']['photos']


def test_trial_voice_and_photos():
    from services import trial_caps as T
    from services.analytics_service import track_event
    from services.chat_photo_allowance import free_chat_photos_left, EVENT
    tid, uid = _user_with_plan(3, 'premium_trial')
    for _ in range(T.TRIAL_VOICE):
        assert T.take_voice(tid)
    assert not T.take_voice(tid)
    for _ in range(T.TRIAL_PHOTOS):
        track_event(uid, EVENT)
    assert free_chat_photos_left(uid, True) == 0


def test_no_premium_is_untouched():
    from services import trial_caps as T
    from services.user_service import ensure_user
    tid = 700000000 + uuid.uuid4().int % 99999999
    uid = ensure_user(tid, 'T')
    assert T.plan_uid(uid) is None and T.take_voice(tid) and T.take_animation(tid)
