"""V3.58.0: money safety — atomic peach spend, top-ups that never overwrite a
spend, duplicate payment callbacks, and owner-only diagnostics pages.

Functional part uses the same temp-DB pattern as test_v3555_promo_gift_logic
(unique telegram ids, self-cleanup)."""
import os
from pathlib import Path

os.environ.setdefault("TELEGRAM_TOKEN", "123456:test-fake-token-for-static-tests-only")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-for-static-tests-only")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from sqlalchemy import delete, select  # noqa: E402
from models.waifu_models import Base  # noqa: E402
from services.db import engine, SessionLocal  # noqa: E402

Base.metadata.create_all(engine)

from models.app_models import StarTransaction, Subscription, User  # noqa: E402
from services import payments  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')

# Unique id band: 9958xx.
_TIDS = []


def _user(n: int, credits: int) -> int:
    tid = 995800 + n
    _TIDS.append(tid)
    with SessionLocal() as s:
        s.add(User(telegram_id=str(tid), photo_credits=credits))
        s.commit()
    return tid


def teardown_module(module):
    with SessionLocal() as s:
        ids = [u.id for u in s.scalars(select(User).where(User.telegram_id.in_([str(t) for t in _TIDS])))]
        s.execute(delete(StarTransaction).where(StarTransaction.user_id.in_(ids)))
        s.execute(delete(Subscription).where(Subscription.user_id.in_(ids)))
        s.execute(delete(User).where(User.id.in_(ids)))
        s.commit()


def test_spend_never_goes_negative():
    # V3.65.0: one photo credit (consume_photo_credit) is 100 peaches.
    tid = _user(1, 500)
    assert payments.spend_peaches(tid, 300) is True
    assert payments.spend_peaches(tid, 300) is False
    assert payments.get_photo_credits(tid) == 200
    assert payments.consume_photo_credit(tid) is True
    assert payments.consume_photo_credit(tid) is True
    assert payments.consume_photo_credit(tid) is False
    assert payments.get_photo_credits(tid) == 0


def test_spend_rejects_negative_amount_and_unknown_user():
    tid = _user(2, 5)
    assert payments.spend_peaches(tid, -10) is False
    assert payments.get_photo_credits(tid) == 5
    assert payments.spend_peaches(995899, 1) is False


def test_topup_does_not_overwrite_a_concurrent_spend():
    tid = _user(3, 10)
    # A purchase session loads the user, then a spend lands before it commits:
    # the top-up must add to the fresh balance, not to the stale 10.
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(tid)))
        user.photo_credits = payments._credits_plus(5)
        assert payments.spend_peaches(tid, 4) is True
        s.commit()
    assert payments.get_photo_credits(tid) == 11


def test_duplicate_payment_is_credited_once():
    tid = _user(4, 0)
    payments.record_payment(tid, 'peach_custom_7', 70, 'charge-dup-995804')
    payments.record_payment(tid, 'peach_custom_7', 70, 'charge-dup-995804')
    # V3.65.0: the custom key counts units of 100 peaches.
    assert payments.get_photo_credits(tid) == 700


def test_grant_reason_is_idempotent():
    tid = _user(5, 0)
    assert payments.grant_photo_credits(tid, 3, 'v3578_bonus') == 3
    assert payments.grant_photo_credits(tid, 3, 'v3578_bonus') == -1
    assert payments.get_photo_credits(tid) == 3


def test_diagnostics_pages_are_owner_only():
    assert 'DIAGNOSTICS_KEY = os.getenv("DIAGNOSTICS_KEY", "").strip()' in CONFIG
    for name in ('_diagnostics', '_platega_check'):
        fn = MAIN[MAIN.index(f'async def {name}('):]
        fn = fn[:fn.index('\nasync def ', 10)]
        assert 'if not _owner_diagnostics_allowed(request):' in fn
        assert 'return web.Response(status=404)' in fn
    gate = MAIN[MAIN.index('def _owner_diagnostics_allowed('):]
    gate = gate[:gate.index('\nasync def ')]
    assert 'secrets.compare_digest(key, DIAGNOSTICS_KEY)' in gate
    assert 'webapp_service._is_admin(telegram_id)' in gate
