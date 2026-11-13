# V3.159.0 — диета пушей (по дампу от 13.11).
#
# 8703 «она написала первой» за два месяца. 15.7% попали в ночь ПО МЕСТНОМУ
# ЧАСУ САМОГО ЧЕЛОВЕКА, ещё 23% легли в окно, где пуш уже был. Рельсы, которые
# смотрят на часы (ритуалы, «жизнь без тебя»), в порядке: 3.9% и 3.1% ночи.
# UTC-кроны на его пояс не смотрели вообще: прогноз совместимости — 42% ночи,
# донат-пинг — 40%, случайный подарок — 34%, ветка «скучаю» — 24%.
#
# Правка: одни ворота (services/push_governor.py) перед каждой такой отправкой.
# Ночью молчим; если в двухчасовом окне уже было два первых сообщения, третье
# пропускаем. Новых таблиц нет — окно считается по тем же product_events.


import asyncio
import datetime as dt
import inspect
from pathlib import Path

from config import (
    LIFE_EVENTS_QUIET_END_HOUR,
    LIFE_EVENTS_QUIET_START_HOUR,
    PUSH_MAX_IN_WINDOW,
    PUSH_SPACING_WINDOW_MINUTES,
)
from models.app_models import ProductEvent
from services import push_governor as pg
from services import scheduler_service as ss
from services.db import SessionLocal
from services.user_service import ensure_user

ROOT = Path(__file__).resolve().parents[1]
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')


def _rail(name: str) -> str:
    return inspect.getsource(getattr(ss, name))


def _events(uid: int, names) -> None:
    with SessionLocal() as s:
        for n in names:
            s.add(ProductEvent(user_id=uid, character_id='anna_01', event_name=n,
                               value=0.0, metadata_json='{}'))
        s.commit()


def test_the_sleeping_window_wraps_around_midnight():
    assert (LIFE_EVENTS_QUIET_START_HOUR, LIFE_EVENTS_QUIET_END_HOUR) == (23, 7)
    for h in (23, 0, 3, 6):
        assert pg.in_quiet_hours(h), h
    for h in (7, 12, 21, 22):
        assert not pg.in_quiet_hours(h), h


def test_the_clock_is_his_not_the_servers():
    from zoneinfo import ZoneInfo
    for tz in ('Asia/Kolkata', 'America/New_York', 'UTC'):
        assert pg.local_hour(tz) == dt.datetime.now(ZoneInfo(tz)).hour
    # битая строка в профиле не роняет рельс — откат на UTC
    assert pg.local_hour('Mars/Olympus') == dt.datetime.now(dt.timezone.utc).hour


def test_a_man_asleep_is_not_written_to(monkeypatch):
    uid = ensure_user(771590001, 'Тест')
    monkeypatch.setattr(pg, 'local_hour', lambda tz: 4)
    assert pg.allow_push(uid, 'Europe/Moscow') == (False, 'night')


def test_the_third_first_message_in_one_window_is_one_too_many(monkeypatch):
    uid = ensure_user(771590002, 'Тест')
    monkeypatch.setattr(pg, 'local_hour', lambda tz: 9)
    assert pg.pushes_in_window(uid) == 0
    _events(uid, ['ritual_morning_sent', 'life_event_sent'])
    assert pg.pushes_in_window(uid) == 2
    assert pg.allow_push(uid, 'Europe/Moscow') == (False, 'burst')


def test_her_words_under_the_photo_are_not_a_second_message(monkeypatch):
    uid = ensure_user(771590003, 'Тест')
    monkeypatch.setattr(pg, 'local_hour', lambda tz: 9)
    # только отметка о картинке-компаньоне и только его ответы в чате
    _events(uid, ['pool_photo_sent', 'morning_photo_sent', 'chat_user_message', 'webapp_opened'])
    assert pg.pushes_in_window(uid) == 0
    assert not any(n.endswith('_photo_sent') for n in pg.PUSH_EVENTS)
    assert not any(n.startswith('chat_') or n.startswith('webapp_') for n in pg.PUSH_EVENTS)


def test_the_diet_is_two_knobs_not_a_wheel(monkeypatch):
    uid = ensure_user(771590004, 'Тест')
    monkeypatch.setattr(pg, 'local_hour', lambda tz: 9)
    monkeypatch.setattr(pg, 'PUSH_MAX_IN_WINDOW', 0)
    _events(uid, list(pg.PUSH_EVENTS[:4]))
    assert pg.allow_push(uid, 'Europe/Moscow') == (True, '')
    monkeypatch.setattr(pg, 'PUSH_MAX_IN_WINDOW', 2)
    monkeypatch.setattr(pg, 'PUSH_SPACING_WINDOW_MINUTES', 0)
    assert pg.pushes_in_window(uid) == 0
    assert pg.allow_push(uid, 'Europe/Moscow') == (True, '')
    assert PUSH_SPACING_WINDOW_MINUTES == 120 and PUSH_MAX_IN_WINDOW == 2


def test_every_rail_that_writes_first_passes_the_gate():
    for name in ('_proactive', '_day1_hook', '_donation_reminder', '_partner_nudge',
                 '_random_gifts', '_daily_compatibility', '_whats_new'):
        assert '_push_ok' in _rail(name), name


def test_the_night_skips_before_anything_is_spent():
    # слот ветки «скучаю» — самый дорогой: штамп last_nudge_at сжигает очередь
    rail = _rail('_proactive')
    assert rail.index('_push_ok') < rail.index('st.last_nudge_at=now')
    # day-1 хук платит LLM-вызовом — ворота должны стоять до него
    hook = _rail('_day1_hook')
    assert hook.index('_push_ok') < hook.index('await morning_callback(')
    # «что нового» помечается до отправки: ночной пропуск не должен съедать раунд
    wn = _rail('_whats_new')
    assert wn.index('_push_ok') < wn.index('wn.mark, uid, cid')
    # донат-пинг ставит метку только после реальной доставки
    don = _rail('_donation_reminder')
    assert don.index('_push_ok') < don.index('mark_donation_ping_sent')


def test_the_gate_fails_open_so_a_broken_clock_never_silences_her():
    src = SCHED[SCHED.index('def _push_ok'):SCHED.index('def _mark_blocked')]
    assert 'return True' in src.split('except Exception')[1]
    # и окно живёт на одних конфигурационных часах с «жизнью без тебя»
    assert 'LIFE_EVENTS_QUIET_START_HOUR' in (ROOT / 'services' / 'push_governor.py').read_text(encoding='utf-8')


def test_the_rails_that_already_watch_the_clock_are_left_alone():
    # ритуалы и «жизнь без тебя» считают часы сами — вторые ворота им ни к чему
    rituals = SCHED[SCHED.index('async def _rituals('):SCHED.index('async def _donation_reminder(')]
    life = SCHED[SCHED.index('async def _life_events('):SCHED.index('async def _rituals(')]
    assert '_push_ok' not in rituals
    assert '_push_ok' not in life


def test_a_night_forecast_is_not_sent_at_all(monkeypatch):
    uid = ensure_user(771590005, 'Тест')
    with SessionLocal() as s:
        u = s.get(ss.User, uid)
        u.proactive_enabled = True
        u.notify_rituals = True
        u.timezone = 'Asia/Kolkata'
        u.last_active_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        s.commit()

    sent = []

    class Bot:
        async def send_message(self, tg_id, text, **_kw):
            sent.append(tg_id)

    monkeypatch.setattr(pg, 'local_hour', lambda tz: 3)
    ss._ritual_sent.clear()
    asyncio.run(ss._daily_compatibility(Bot()))
    assert sent == []
    assert [g for g in ss._ritual_sent if g[0] == uid] == []
