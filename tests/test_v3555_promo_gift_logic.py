"""V3.55.5 functional checks: streak gift + promo codes on a temp in-memory DB.

Exercises the money rules end to end (same pattern as test_streak_and_contest:
DATABASE_URL pinned to sqlite BEFORE services.db is imported, unique telegram
ids, self-cleanup). Day rollover is simulated by monkeypatching the module
global gift_service.gift_day_key — claim/status resolve it at call time, so
`gift_last_day` and the idempotent grant reason `daily_gift_<iso>` both move
with the fake clock (real date stays untouched; 03:00 MSK boundary itself is
pinned statically in test_v3555_promo_gift_static.py).
"""
import os

os.environ.setdefault("TELEGRAM_TOKEN", "123456:test-fake-token-for-static-tests-only")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-for-static-tests-only")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from datetime import date, datetime, timedelta, timezone  # noqa: E402
from sqlalchemy import select  # noqa: E402
from models.waifu_models import Base  # noqa: E402
from services.db import engine, SessionLocal  # noqa: E402

Base.metadata.create_all(engine)

from models.app_models import ProductEvent, PromoCode, StarTransaction, User, UserConsent  # noqa: E402
from services import gift_service as g  # noqa: E402
from services.consent_service import accept  # noqa: E402
from services.payments import get_photo_credits  # noqa: E402

# Unique id band: 9915xx (no collision with 999xxx / 77xxx suites).
_BASE = date(2031, 4, 10)
_TIDS = []


def _tid(n: int) -> int:
    tid = 991500 + n
    if tid not in _TIDS:
        _TIDS.append(tid)
    return tid


def _onboard(telegram_id: int, day: date = _BASE, with_consent: bool = True):
    g.ensure_user(telegram_id, 'tester')
    if with_consent:
        accept(telegram_id)
    return telegram_id


def _set_balance(telegram_id: int, value: int):
    with SessionLocal() as s:
        u = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        u.photo_credits = value
        s.commit()


def _gift_state(telegram_id: int):
    with SessionLocal() as s:
        u = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        return u.gift_last_day, int(u.gift_streak or 0)


def _add_code(code: str, credits: int, max_activations: int = 0,
              expires_at: datetime | None = None, active: bool = True,
              source_tag: str | None = None):
    with SessionLocal() as s:
        s.add(PromoCode(code=code, credits=credits, max_activations=max_activations,
                        activated_count=0, expires_at=expires_at, active=active,
                        source_tag=source_tag))
        s.commit()


def _code_counter(code: str) -> int:
    with SessionLocal() as s:
        return int(s.scalar(select(PromoCode).where(PromoCode.code == code)).activated_count)


def _sim_clock(monkeypatch):
    """Freeze gift_day_key to a movable fake date; returns a setter."""
    holder = {'d': _BASE}
    monkeypatch.setattr(g, 'gift_day_key', lambda now=None: holder['d'])

    def _set(day: date):
        holder['d'] = day
    return _set


def _cleanup():
    with SessionLocal() as s:
        ids = [str(t) for t in _TIDS]
        uids = [int(uid) for uid in s.scalars(select(User.id).where(User.telegram_id.in_(ids))).all()]
        if uids:
            s.query(ProductEvent).filter(ProductEvent.user_id.in_(uids)).delete(synchronize_session=False)
            s.query(StarTransaction).filter(StarTransaction.user_id.in_(uids)).delete(synchronize_session=False)
            s.query(UserConsent).filter(UserConsent.user_id.in_(uids)).delete(synchronize_session=False)
        s.query(User).filter(User.telegram_id.in_(ids)).delete(synchronize_session=False)
        s.query(PromoCode).delete(synchronize_session=False)
        s.commit()


# ------------------------------------------------------------------ streak
def test_streak_series_jackpot_and_restart(monkeypatch):
    """Days 1..6 pay 1 🍑, day 7 pays 3 🍑, day 8 restarts the cycle at slot 1."""
    set_day = _sim_clock(monkeypatch)
    try:
        tid = _onboard(_tid(1))
        for i in range(1, 7):
            set_day(_BASE + timedelta(days=i - 1))
            res = g.claim_daily_gift(tid)
            assert res['ok'] and res['amount'] == 1 and res['streak'] == i, res
        set_day(_BASE + timedelta(days=6))
        jack = g.claim_daily_gift(tid)
        assert jack['ok'] and jack['amount'] == 3 and jack['streak'] == 7, jack
        assert get_photo_credits(tid) == 9, get_photo_credits(tid)  # 6*1 + 3
        # day 8: raw streak keeps growing (8) but the UI slot folds back to 1
        set_day(_BASE + timedelta(days=7))
        again = g.claim_daily_gift(tid)
        assert again['ok'] and again['amount'] == 1 and again['streak'] == 1, again
    finally:
        _cleanup()


def test_once_per_day_duplicate(monkeypatch):
    set_day = _sim_clock(monkeypatch)
    try:
        tid = _onboard(_tid(2))
        first = g.claim_daily_gift(tid)
        assert first['ok'], first
        balance = get_photo_credits(tid)
        dup = g.claim_daily_gift(tid)
        assert not dup['ok'] and dup['error'] == 'duplicate', dup
        assert get_photo_credits(tid) == balance
        # the series columns did not move either
        assert _gift_state(tid) == (_BASE, 1)
    finally:
        _cleanup()


def test_missed_day_resets_series(monkeypatch):
    set_day = _sim_clock(monkeypatch)
    try:
        tid = _onboard(_tid(3))
        set_day(_BASE)
        assert g.claim_daily_gift(tid)['ok']
        set_day(_BASE + timedelta(days=1))
        assert g.claim_daily_gift(tid)['ok']
        # skip day 3 — claiming on day 4 restarts at 1
        set_day(_BASE + timedelta(days=3))
        res = g.claim_daily_gift(tid)
        assert res['ok'] and res['streak'] == 1, res
        assert _gift_state(tid)[1] == 1  # raw streak restarted too
    finally:
        _cleanup()


def test_cap_blocks_without_consuming_the_day(monkeypatch):
    set_day = _sim_clock(monkeypatch)
    try:
        tid = _onboard(_tid(4))
        set_day(_BASE)
        assert g.claim_daily_gift(tid)['ok']
        set_day(_BASE + timedelta(days=1))
        _set_balance(tid, 15)
        capped = g.claim_daily_gift(tid)
        assert not capped['ok'] and capped['capped'] and capped['error'] == 'capped', capped
        # the day was NOT eaten: gift_last_day is still day 1, streak still 1
        assert _gift_state(tid) == (_BASE, 1)
        # spend below the cap and the same day becomes claimable again
        _set_balance(tid, 5)
        res = g.claim_daily_gift(tid)
        assert res['ok'] and res['streak'] == 2 and res['balance'] == 6, res
    finally:
        _cleanup()


def test_gift_requires_consent_and_status_reads(monkeypatch):
    set_day = _sim_clock(monkeypatch)
    try:
        tid = _onboard(_tid(5), with_consent=False)
        denied = g.claim_daily_gift(tid)
        assert not denied['ok'] and denied['error'] == 'consent', denied
        accept(tid)
        st = g.gift_status(tid)
        assert st['available'] and not st['claimed_today'] and st['amount'] == 1, st
        assert g.claim_daily_gift(tid)['ok']
        after = g.gift_status(tid)
        assert after['claimed_today'] and not after['available'] and after['streak'] == 1, after
    finally:
        _cleanup()


# ------------------------------------------------------------------ promos
def test_promo_normalization_and_one_per_user(monkeypatch):
    set_day = _sim_clock(monkeypatch)  # keeps the fake clock honest for grants
    try:
        tid = _onboard(_tid(6))
        _add_code('WELCOME6', credits=5)
        res = g.redeem_promo(tid, '  welcome6 ')
        assert res['ok'] and res['credits'] == 5 and get_photo_credits(tid) == 5, res
        assert _code_counter('WELCOME6') == 1
        dup = g.redeem_promo(tid, 'WELCOME6')
        assert not dup['ok'] and dup['error'] == 'duplicate', dup
        # the reserved slot was handed back — counter did not drift
        assert _code_counter('WELCOME6') == 1
        assert get_photo_credits(tid) == 5
    finally:
        _cleanup()


def test_promo_global_activation_cap(monkeypatch):
    _sim_clock(monkeypatch)
    try:
        a, b = _onboard(_tid(7)), _onboard(_tid(8))
        _add_code('DROP2', credits=2, max_activations=1)
        assert g.redeem_promo(a, 'DROP2')['ok']
        exhausted = g.redeem_promo(b, 'DROP2')
        assert not exhausted['ok'] and exhausted['error'] == 'exhausted', exhausted
        assert get_photo_credits(b) == 0
        assert _code_counter('DROP2') == 1
    finally:
        _cleanup()


def test_promo_error_matrix(monkeypatch):
    _sim_clock(monkeypatch)
    try:
        tid = _onboard(_tid(9))
        _add_code('OLD9', credits=4, expires_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1))
        _add_code('OFF9', credits=4, active=False)
        assert g.redeem_promo(tid, 'OLD9')['error'] == 'expired'
        assert g.redeem_promo(tid, 'OFF9')['error'] == 'inactive'
        assert g.redeem_promo(tid, 'NOPE9')['error'] == 'unknown'
        assert g.redeem_promo(tid, 'AB')['error'] == 'unknown'          # too short for the regex
        assert g.redeem_promo(tid, 'BAD CODE!')['error'] == 'unknown'   # odd chars never enumerate
        assert g.redeem_promo(tid, 'OLD9')['error'] == 'expired'        # nothing leaked into balances
        assert get_photo_credits(tid) == 0
        # no-consent user is refused before any table lookup
        cold = _tid(10)
        g.ensure_user(cold, 'cold')
        assert g.redeem_promo(cold, 'OFF9')['error'] == 'consent'
    finally:
        _cleanup()


def test_welcome_promo_seed_is_idempotent_and_redeemable(monkeypatch):
    _sim_clock(monkeypatch)
    try:
        # two boots in a row must not mint the row twice
        g.ensure_welcome_promo()
        g.ensure_welcome_promo()
        with SessionLocal() as s:
            rows = s.scalars(select(PromoCode).where(PromoCode.code == 'ANNA5')).all()
        assert len(rows) == 1, rows
        assert rows[0].credits == 5 and rows[0].source_tag == 'welcome'
        # the shelf economics hold: cap 15 🍑 + ANNA5 5 🍑 = the 20 🍑 video
        from config import VIDEO_PEACH_COST
        assert 15 + rows[0].credits == VIDEO_PEACH_COST == 20
        tid = _onboard(_tid(11))
        res = g.redeem_promo(tid, 'anna5')
        assert res['ok'] and res['credits'] == 5, res
        assert g.redeem_promo(tid, 'ANNA5')['error'] == 'duplicate'
        # disabled shelf seeds nothing
        with SessionLocal() as s:
            s.query(PromoCode).delete(synchronize_session=False)
            s.commit()
        monkeypatch.setattr(g, 'PROMO_WELCOME_ENABLED', False)
        g.ensure_welcome_promo()
        with SessionLocal() as s:
            assert s.scalars(select(PromoCode)).all() == []
    finally:
        _cleanup()
