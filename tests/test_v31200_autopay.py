"""V3.120.0 — Premium auto-renewal: opt-in Stars subscription and Platega SBP
subscription, honest terms, pre-charge reminder, one-tap cancel."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from models.app_models import AutoRenewal, Base, StarTransaction, Subscription, User
from services import autopay
from services import renewal_care as rc
from services.db import SessionLocal, engine

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
APP = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _user():
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        u = User(telegram_id=str(int(_now().timestamp() * 1e6) % 10 ** 12), name='t')
        s.add(u); s.commit()
        return u.id, int(u.telegram_id)


def test_parse_dt_and_email_mapping():
    assert autopay.parse_dt('2026-11-28T09:00:00Z') == datetime(2026, 11, 28, 9, 0)
    assert autopay.parse_dt(0) == datetime(1970, 1, 1)
    assert autopay.parse_dt('junk') is None
    assert autopay.customer_email(555) == '555@telegram.org'
    assert autopay.telegram_id_from_email('555@telegram.org') == 555
    assert autopay.telegram_id_from_email('a@gmail.com') is None


def test_platega_body_is_a_weekly_or_monthly_sbp_subscription():
    body = autopay.platega_body(7, 555, 'premium_week', 199)
    assert body['paymentMethod'] == 6
    assert body['paymentDetails'] == {'amount': 199, 'currency': 'RUB', 'interval': 2, 'intervalCount': 1}
    assert body['metadata']['user_email'] == '555@telegram.org'
    assert body['payload'] == 'anb_autopay:7'
    assert autopay.platega_body(7, 555, 'premium_month', 699)['paymentDetails']['interval'] == 3


def test_subscription_callback_detection():
    assert autopay.is_subscription_callback({'subscriptionId': 'x', 'status': 'CONFIRMED'})
    assert autopay.is_subscription_callback({'status': 'SUBSCRIPTION_CANCELLED'})
    assert not autopay.is_subscription_callback({'id': 'x', 'status': 'CONFIRMED', 'payload': 'anb_order:5'})


def test_lifecycle_charge_remind_cancel():
    uid, tg = _user()
    row_id = autopay.create_pending(tg, 'platega', 'premium_month', 699, external_id='sub-' + str(tg))
    assert autopay.get_live(tg) is None  # pending is not «on»
    nxt = _now() + timedelta(hours=20)
    assert autopay.record_charge(row_id, nxt) is True
    assert autopay.record_charge(row_id, nxt) is False
    assert autopay.has_active(tg)
    assert autopay.find_by_external('sub-' + str(tg))['id'] == row_id
    due = [r for r in autopay.due_reminders() if r['id'] == row_id]
    assert due and '699 ₽' in autopay.reminder_text(due[0])
    autopay.mark_reminded(row_id, due[0]['next_charge_at'])
    assert not [r for r in autopay.due_reminders() if r['id'] == row_id]
    autopay.set_status(row_id, 'canceled')
    assert not autopay.has_active(tg)


def test_stars_renewal_that_never_came_lapses():
    uid, tg = _user()
    row_id = autopay.create_pending(tg, 'stars', 'premium_month', 500, external_id='ch-' + str(tg))
    autopay.record_charge(row_id, _now() - timedelta(hours=autopay.LAPSE_HOURS + 1))
    changed = [r for r in autopay.lapse_overdue() if r['id'] == row_id]
    assert changed and changed[0]['status'] == 'canceled'


def test_extend_premium_to_next_charge_but_never_far():
    uid, tg = _user()
    now = _now()
    with SessionLocal() as s:
        s.add(Subscription(user_id=uid, plan='premium', status='active', started_at=now,
                           expires_at=now + timedelta(days=30)))
        s.commit()
    autopay.extend_premium_to(tg, now + timedelta(days=31))
    assert autopay.premium_until(tg) >= now + timedelta(days=31)
    autopay.extend_premium_to(tg, now + timedelta(days=60))
    assert autopay.premium_until(tg) < now + timedelta(days=40)


def test_charge_seen_dedupes_callbacks():
    uid, tg = _user()
    charge = f'platega_sub:test-{tg}'
    assert not autopay.charge_seen(charge)
    with SessionLocal() as s:
        s.add(StarTransaction(user_id=uid, transaction_type='purchase', product='premium_month',
                              stars=0, telegram_charge_id=charge))
        s.commit()
    assert autopay.charge_seen(charge)


def test_terms_are_honest():
    ru = autopay.terms_text()
    assert 'списывается сама' in ru and 'Отключить' in ru and 'напомню' in ru
    en = autopay.terms_text(en=True)
    assert 'Turn off' in en and 'remind' in en


def test_wiring_in_main_scheduler_and_app():
    assert "subscription_period=autopay.STARS_PERIOD_SECONDS" in MAIN
    assert "payload=='premium_month_auto'" in MAIN
    assert "edit_user_star_subscription" in MAIN
    assert "autopay.is_subscription_callback(body)" in MAIN
    assert "@dp.message(Command('autopay'))" in MAIN
    assert "_autopay_row(telegram_id" in MAIN
    assert "_autopay_scan" in SCHED and "id='autopay_scan'" in SCHED
    assert "/webapp/api/autopay" in APP and "/webapp/api/autopay" in MAIN


def test_renewal_care_skips_autopay_users():
    src = (ROOT / 'services' / 'renewal_care.py').read_text(encoding='utf-8')
    assert 'autopay.has_active(tg)' in src
