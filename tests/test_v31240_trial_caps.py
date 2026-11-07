"""V3.124.0: the short trial Premium has totals, longer plans keep daily rules."""
import os
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault('TELEGRAM_TOKEN', '123:abc')
os.environ.setdefault('GEMINI_API_KEY', 'x')


def _user_with_plan(days: float):
    from services.user_service import ensure_user
    from services.db import SessionLocal
    from models.app_models import Subscription
    tid = 800000000 + uuid.uuid4().int % 99999999
    uid = ensure_user(tid, 'T')
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with SessionLocal() as s:
        s.add(Subscription(user_id=uid, plan='premium', status='active', stars_amount=0,
                           started_at=now - timedelta(minutes=1), expires_at=now + timedelta(days=days),
                           telegram_charge_id=f't{tid}'))
        s.commit()
    return tid, uid


def _msgs(uid, n):
    from services.db import SessionLocal
    from models.app_models import Message
    with SessionLocal() as s:
        for _ in range(n):
            s.add(Message(user_id=uid, character_id='anna', role='user', content='hi'))
        s.commit()


def test_trial_messages_total():
    from services import trial_caps as T
    from services.access_service import can_send_message
    tid, uid = _user_with_plan(3)
    assert T.window_start_uid(uid) is not None
    _msgs(uid, T.TRIAL_MESSAGES - 1)
    assert can_send_message(tid)
    _msgs(uid, 1)
    assert not can_send_message(tid)


def test_week_plan_is_not_trial():
    from services import trial_caps as T
    from services.access_service import can_send_message
    tid, uid = _user_with_plan(7)
    assert T.window_start_uid(uid) is None
    _msgs(uid, T.TRIAL_MESSAGES + 5)
    assert can_send_message(tid)


def test_trial_voice_and_calls_and_photos():
    from services import trial_caps as T, voice_call
    from services.analytics_service import track_event
    from services.chat_photo_allowance import free_chat_photos_left, EVENT
    tid, uid = _user_with_plan(3)
    for _ in range(T.TRIAL_VOICE):
        assert T.take_voice(tid)
    assert not T.take_voice(tid)
    track_event(uid, voice_call.EVENT_PREMIUM, value=float(T.TRIAL_CALL_SECONDS))
    assert voice_call.seconds_left(uid, 'premium') == 0
    for _ in range(T.TRIAL_PHOTOS):
        track_event(uid, EVENT)
    assert free_chat_photos_left(uid, True) == 0
