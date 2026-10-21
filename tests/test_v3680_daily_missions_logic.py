"""V3.68.0 functional checks: daily missions (anti-spam counting, once-a-day
claims) and the channel-bonus hold, on a temp in-memory DB."""
import os

os.environ.setdefault("TELEGRAM_TOKEN", "123456:test-fake-token-for-static-tests-only")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-for-static-tests-only")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from datetime import datetime, timedelta  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402
from models.waifu_models import Base  # noqa: E402
from services.db import engine, SessionLocal  # noqa: E402

Base.metadata.create_all(engine)

from models.app_models import Message, StarTransaction, User  # noqa: E402
from services import channel_bonus_service as cbs  # noqa: E402
from services import gamification_service as gam  # noqa: E402
from services.payments import get_photo_credits  # noqa: E402
from services.user_service import ensure_user  # noqa: E402

NOON = datetime(2031, 5, 10, 12, 0, 0)


@pytest.fixture(autouse=True)
def _pinned_day(monkeypatch):
    # pin the day so the test never straddles 03:00 MSK (and never leaks)
    monkeypatch.setattr(gam, '_today', lambda: NOON)


def _user(tid: int) -> int:
    return ensure_user(tid, 'tester')


def _say(uid: int, text: str, at: datetime):
    with SessionLocal() as s:
        s.add(Message(user_id=uid, character_id='anna', role='user', content=text, created_at=at))
        s.commit()


def test_spam_does_not_count():
    uid = _user(996801)
    start = NOON - timedelta(hours=2)
    _say(uid, 'а', start)                                        # too short
    _say(uid, 'ок', start + timedelta(minutes=1))
    _say(uid, 'привет как дела', start + timedelta(minutes=2))   # counts
    _say(uid, 'Привет, как дела?!', start + timedelta(minutes=3))  # same text → no
    _say(uid, 'что делаешь сегодня', start + timedelta(minutes=2, seconds=3))  # burst → no
    _say(uid, 'что делаешь вечером', start + timedelta(minutes=5))  # counts
    _say(uid, 'вчерашнее сообщение тоже', start - timedelta(days=1))  # yesterday → no
    st = gam.daily_stats(uid)
    assert st['count'] == 2
    assert st['span_minutes'] == 3


def test_daily_chat_claims_once_and_long_needs_time():
    tid = 996802
    uid = _user(tid)
    start = NOON - timedelta(minutes=10)
    for i in range(10):
        _say(uid, f'сообщение номер {"абвгдежзик"[i]} про жизнь', start + timedelta(seconds=30 * i))
    rows = {d['key']: d for d in gam.daily_missions(tid)}
    assert rows['daily_chat']['claimable'] is True
    assert rows['daily_long']['done'] is False
    before = get_photo_credits(tid)
    r = gam.claim_mission(tid, 'daily_chat')
    assert r['ok'] and r['amount'] == 100
    assert get_photo_credits(tid) == before + 100
    assert gam.claim_mission(tid, 'daily_chat')['error'] == 'claimed'
    assert gam.claim_mission(tid, 'daily_long')['error'] == 'locked'
    # 25 real messages but all within 5 minutes: still no «долгий разговор»
    for i in range(15):
        _say(uid, f'ещё одна мысль {i} вслух', start + timedelta(minutes=5, seconds=15 * i))
    assert gam.claim_mission(tid, 'daily_long')['error'] == 'locked'


def test_one_off_missions_pay_nothing_now():
    assert gam.MISSION_PEACHES == {}
    assert set(gam.DAILY_MISSIONS) == {'daily_chat', 'daily_long'}
    assert all(v[4] == 100 for v in gam.DAILY_MISSIONS.values())


def test_channel_hold_starts_once_and_becomes_due():
    tid = 996803
    _user(tid)
    started = cbs.start_hold(tid)
    assert started is not None
    assert cbs.start_hold(tid) == started
    assert cbs.days_left(started) == 3
    assert tid not in cbs.due_hold_ids()
    with SessionLocal() as s:
        tx = s.scalar(select(StarTransaction).where(StarTransaction.telegram_charge_id == f'channel_pending:{tid}'))
        tx.created_at = tx.created_at - timedelta(days=3, minutes=1)
        s.commit()
    assert tid in cbs.due_hold_ids()
    assert cbs.days_left(cbs.hold_started(tid)) == 0
    cbs.clear_hold(tid)
    assert cbs.hold_started(tid) is None
    assert tid not in cbs.due_hold_ids()
    # the hold marker never touches the balance
    with SessionLocal() as s:
        u = s.scalar(select(User).where(User.telegram_id == str(tid)))
        assert int(u.photo_credits or 0) == 0
