# V3.159.1 — учёт перестаёт врать.
#
# Дамп 13.11: 31 строка в subscriptions, из них 29 истекли ещё в сентябре, но
# все как одна значатся «active». Деньги это не трогает — каждая читалка
# (is_premium, payments, autopay) сверяется с expires_at, — зато любой новый
# запрос, который про дату забудет, выдаст вечный Premium. Плюс 50 «pending»
# заказов FreeKassa: касса ретайрена в V3.44.21, модели таблицы больше нет,
# читателй ноль — это архив, и трогать его нечем.
#
# Правка: раз в сутки (00:25 UTC, за пять минут до ночного дампа) просроченные
# строки получают честный статус.


import datetime as dt
from pathlib import Path

from models.app_models import Subscription
from services import payments
from services.db import SessionLocal
from services.user_service import ensure_user

ROOT = Path(__file__).resolve().parents[1]
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')


def _mk(tg: int, started: dt.datetime, expires: dt.datetime, status: str = 'active') -> int:
    uid = ensure_user(tg, 'Тест')
    with SessionLocal() as s:
        sub = Subscription(user_id=uid, plan='premium', status=status, stars_amount=0,
                           started_at=started, expires_at=expires,
                           telegram_charge_id=f'housekeeping:{tg}')
        s.add(sub)
        s.commit()
        return sub.id


def test_the_expired_row_stops_claiming_to_be_active():
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    stale = _mk(771591001, now - dt.timedelta(days=40), now - dt.timedelta(days=30))
    live = _mk(771591002, now - dt.timedelta(days=1), now + dt.timedelta(days=29))
    gone = _mk(771591003, now - dt.timedelta(days=40), now - dt.timedelta(days=10), status='expired')
    assert payments.expire_stale_subscriptions() >= 1
    with SessionLocal() as s:
        assert s.get(Subscription, stale).status == 'expired'
        assert s.get(Subscription, live).status == 'active'
        assert s.get(Subscription, gone).status == 'expired'
        # дата живого Premium не сдвинулась ни на секунду
        assert s.get(Subscription, live).expires_at > now


def test_the_housekeeping_is_idempotent():
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    _mk(771591004, now - dt.timedelta(days=9), now - dt.timedelta(days=2))
    first = payments.expire_stale_subscriptions()
    assert first >= 1
    assert payments.expire_stale_subscriptions() == 0


def test_a_live_premium_man_keeps_his_rights():
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    tg = 771591005
    uid = ensure_user(tg, 'Тест')
    with SessionLocal() as s:
        s.add(Subscription(user_id=uid, plan='premium', status='active', stars_amount=0,
                           started_at=now, expires_at=now + dt.timedelta(days=7),
                           telegram_charge_id='housekeeping:live'))
        s.commit()
    payments.expire_stale_subscriptions()
    from services.access_service import is_premium
    assert is_premium(tg) is True


def test_nobody_grants_premium_on_status_alone():
    # инвариант, из-за которого вранье в таблице было безобидным — пусть и остаётся
    access = (ROOT / 'services' / 'access_service.py').read_text(encoding='utf-8')
    body = access[access.index('def is_premium'):access.index('def can_send_message')]
    assert 'Subscription.status=="active"' in body and 'expires_at>now' in body
    # каждая фильтрующая по статусу строка в учёте смотрит и на дату
    for name in ('payments.py', 'autopay.py', 'analytics_service.py', 'access_service.py'):
        src = (ROOT / 'services' / name).read_text(encoding='utf-8')
        i = src.find('Subscription.status')
        while i != -1:
            window = src[max(0, i - 200):i + 200]
            assert 'expires_at' in window or 'sub.status' in window, (name, window[-160:])
            i = src.find('Subscription.status', i + 1)


def test_the_dead_kassa_is_an_archive_not_a_leak():
    models = "\n".join(p.read_text(encoding='utf-8') for p in (ROOT / 'models').glob('*.py'))
    # таблицы нет ни у одной модели → ORM её не читает и не пишет
    assert "__tablename__ = 'freekassa_orders'" not in models
    assert '__tablename__ = "freekassa_orders"' not in models
    readers = [p.name for p in (ROOT / 'services').glob('*.py')
               if 'freekassa_orders' in p.read_text(encoding='utf-8')]
    assert readers == ['db.py'], readers  # только комментарий «retired, left as history»


def test_the_job_runs_every_day_before_the_backup():
    house = SCHED.index('scheduler.add_job(_ledger_housekeeping')
    backup = SCHED.index('scheduler.add_job(_db_backup')
    assert house < backup
    assert "hour=0,minute=25" in SCHED[house:house + 120]
    rail = SCHED[SCHED.index('async def _ledger_housekeeping'):SCHED.index('async def _db_backup')]
    assert 'expire_stale_subscriptions' in rail
    assert 'logger.exception' in rail  # упавший клининг не будит планировщик
