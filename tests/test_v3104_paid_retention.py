"""V3.104.0 — keep and renew the people who paid: welcome card + her word,
next-day message, «останешься?» before the end, loyalty month, memory gift."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from models.app_models import Base, Memory, ProductEvent, StarTransaction, Subscription, User
from services import memory_gift as mg
from services import paid_welcome as pw
from services import renewal_care as rc
from services import vip_offer
from services.db import SessionLocal, engine

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _user(**kw):
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        u = User(telegram_id=str(int(_now().timestamp() * 1e6) % 10 ** 12), name='t', **kw)
        s.add(u); s.commit()
        return u.id, int(u.telegram_id)


def _pay(uid, product, at, days):
    with SessionLocal() as s:
        charge = f'test:{uid}:{product}:{at.timestamp()}'
        s.add(StarTransaction(user_id=uid, transaction_type='purchase', product=product, stars=1,
                              telegram_charge_id=charge, created_at=at))
        s.add(Subscription(user_id=uid, plan='premium', status='active', started_at=at,
                           expires_at=at + timedelta(days=days), telegram_charge_id=charge))
        s.commit()


def _mem(uid, key, content, mtype='fact', age_h=24, importance=0.5):
    with SessionLocal() as s:
        m = Memory(user_id=uid, character_id='anna_01', memory_key=key, content=content, memory_type=mtype,
                   importance=importance, created_at=_now() - timedelta(hours=age_h),
                   updated_at=_now() - timedelta(hours=age_h))
        s.add(m); s.commit()
        return m.id


# --- memory gift -----------------------------------------------------------

def test_memory_gift_due_only_after_a_pause():
    assert mg.is_due(_now() - timedelta(hours=mg.GAP_HOURS + 1))
    assert not mg.is_due(_now() - timedelta(minutes=5))
    assert not mg.is_due(None)


def test_memory_gift_picks_plans_and_worries_first_never_the_name():
    uid, _ = _user()
    _mem(uid, 'name', 'его зовут Витя', importance=0.9)
    _mem(uid, 'work', 'работает водителем', importance=0.6)
    worry = _mem(uid, 'interview', 'в пятницу у него собеседование в банке', mtype='pending', importance=0.5)
    _mem(uid, 'fresh', 'только что купил кофе', mtype='pending', age_h=0)
    got = mg.pick(uid, 'anna_01')
    assert got and got[0] == worry and 'собеседование' in got[1]
    note = mg.directive(got[1])
    assert 'собеседование' in note and 'не показывай' in note


def test_memory_gift_once_a_day_and_not_repeated():
    uid, _ = _user()
    first = _mem(uid, 'trip', 'на выходных едет к брату в Казань', mtype='pending')
    _mem(uid, 'work', 'работает в автосервисе')
    got = mg.pick(uid, 'anna_01')
    assert got[0] == first
    mg.mark_used(uid, 'anna_01', first)
    assert mg.pick(uid, 'anna_01') is None  # cooldown
    with SessionLocal() as s:  # a day later the same memory is skipped, the next one comes
        ev = s.query(ProductEvent).filter(ProductEvent.user_id == uid, ProductEvent.event_name == mg.EVENT).one()
        ev.created_at = _now() - timedelta(hours=mg.COOLDOWN_HOURS + 1)
        s.commit()
        assert 'Казань' not in (ev.metadata_json or '')  # only the id is stored
    got = mg.pick(uid, 'anna_01')
    assert got and 'автосервис' in got[1]


def test_memory_gift_wired_into_reply_and_extraction():
    assert 'memory_gift.is_due' in CHAT and 'memory_gift.directive(gift[1])' in CHAT
    assert 'memory_gift.mark_used' in CHAT
    mem = (ROOT / 'services' / 'memory_service.py').read_text(encoding='utf-8')
    assert '_EXTRACT_PROMPT_V3104 if memory_gift.ENABLED else _EXTRACT_PROMPT_OLD' in mem
    assert 'key "name"' in mem and 'type "worry"' in mem and 'медицинские диагнозы' in mem


# --- loyalty month ---------------------------------------------------------

def test_loyalty_opens_on_first_week_and_stays_open_while_premium():
    uid, tg = _user()
    _pay(uid, 'premium_week', _now(), 7)
    assert not vip_offer.open_loyalty(tg, 'premium_month')
    assert vip_offer.open_loyalty(tg, 'premium_week')
    assert not vip_offer.open_loyalty(tg, 'premium_week')  # once ever
    info = vip_offer.info(tg)
    assert info['active'] and info['loyal'] and info['stars'] == vip_offer.VIP_STARS
    assert 7 * 24 < info['hours_left'] <= 7 * 24 + vip_offer.LOYAL_GRACE_HOURS + 1
    _pay(uid, 'premium_month_vip', _now() + timedelta(seconds=1), 30)  # he stayed → closed
    assert not vip_offer.info(tg).get('loyal')


def test_loyalty_not_for_someone_who_bought_a_month_before():
    uid, tg = _user()
    _pay(uid, 'premium_month', _now() - timedelta(days=40), 30)
    _pay(uid, 'premium_week', _now(), 7)
    assert not vip_offer.open_loyalty(tg, 'premium_week')


# --- day after the payment -------------------------------------------------

def test_day1_candidate_once_and_not_while_he_is_here():
    uid, tg = _user(last_active_at=_now() - timedelta(hours=10))
    _pay(uid, 'premium_week', _now() - timedelta(hours=pw.DAY1_MIN_HOURS + 2), 7)
    assert (uid, tg, '', 'premium_week') in pw.day1_candidates()
    pw.mark(uid, pw.DAY1_EVENT, 'anna_01', 'premium_week')
    assert all(r[0] != uid for r in pw.day1_candidates())

    uid2, _ = _user(last_active_at=_now() - timedelta(minutes=20))
    _pay(uid2, 'premium_trial', _now() - timedelta(hours=pw.DAY1_MIN_HOURS + 2), 3)
    assert all(r[0] != uid2 for r in pw.day1_candidates())

    uid3, _ = _user(last_active_at=_now() - timedelta(hours=10))
    _pay(uid3, 'premium_week', _now() - timedelta(hours=2), 7)  # too early
    assert all(r[0] != uid3 for r in pw.day1_candidates())


def test_unlocked_card_lists_real_premium_things():
    ru = pw.unlocked_text('premium_week', 'ru')
    for part in ('без дневного лимита', '1 по 10', 'Пошлый режим', 'Фетиши', 'Раздеть', 'голосовые', '(7 дн.)'):
        assert part in ru
    assert '(3 дн.)' in pw.unlocked_text('premium_trial', 'ru', 3)
    assert 'no daily limit' in pw.unlocked_text('premium_month', 'en')
    line = pw.loyal_line(50, 349, 699, 250, 'ru')
    assert '349 ₽ вместо 699 ₽' in line


# --- before the end --------------------------------------------------------

def test_renewal_soon_then_ended_for_a_week_not_for_trial():
    uid, tg = _user()
    _pay(uid, 'premium_week', _now() - timedelta(days=7) + timedelta(hours=10), 7)  # ends in 10 h
    rows = [r for r in rc.candidates() if r[0] == uid]
    assert rows == [(uid, tg, '', 'soon', 'premium_week')]
    rc.mark(uid, 'soon', 'anna_01')
    assert not [r for r in rc.candidates() if r[0] == uid]
    later = _now() + timedelta(hours=12)  # 2 h after the end
    assert [r for r in rc.candidates(later) if r[0] == uid][0][3] == 'ended'

    tuid, _ = _user()
    _pay(tuid, 'premium_trial', _now() - timedelta(days=3) + timedelta(hours=5), 3)
    assert not [r for r in rc.candidates() if r[0] == tuid]


def test_no_pressure_or_guilt_in_her_lines():
    from services.chat_service import PAID_MOMENT_LINES
    texts = list(PAID_MOMENT_LINES.values()) + [v for v in rc.FALLBACK.values()] + \
        [pw.fallback(m, l) for m in ('welcome', 'day1') for l in ('ru', 'en')]
    for t in texts:
        low = t.lower()
        assert 'последний шанс' not in low and 'last chance' not in low
        assert 'только сегодня' not in low and 'осталось всего' not in low
    assert 'Без давления' in PAID_MOMENT_LINES['renew_soon'] and 'без вины' in PAID_MOMENT_LINES['renew_soon']
    assert 'не упоминай деньги' in PAID_MOMENT_LINES['welcome']


def test_wiring():
    assert 'if payload in PAID_PREMIUM_PRODUCTS:' in MAIN
    assert MAIN.count('_after_premium_paid(') >= 3  # def + Stars + Platega
    assert 'vip_offer.open_loyalty' in MAIN
    assert "id='paid_day1'" in SCHED and "id='renewal_care'" in SCHED
    assert 'stay_buttons' in SCHED and '_msk_daytime()' in SCHED
