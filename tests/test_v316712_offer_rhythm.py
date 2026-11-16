# V3.167.12 — «пусть чаще всем пользователям приходит предложение оплаты»
# (владелец, 16.11). Что именно сдвинулось и чем это подтверждается:
# 1) очереди first_offer и heavy_offer были просто выключены в PUSH_RAILS,
#    то есть письма не уходили ни у кого;
# 2) честное предложение порождалось на 150 сообщениях — при потолке 30 в
#    сутки это пять тяжёлых дней, до порога доходили единицы; метка EVENT
#    читалась как «один раз в жизни»;
# 3) обе очереди писали мимо push_governor: ночное окно и его два пуша в
#    сутки на них не действовали. Теперь ворота стоят до того, как сожжён
#    слот, поэтому отказ — это пауза, а не потерянное предложение.

import datetime as dt
import inspect
from itertools import count
from pathlib import Path

from config import CHAT_MSGS_PER_DAY, PUSH_RAILS, push_rail_on
from models.app_models import Base, Message, ProductEvent, User
from services import heavy_offer as ho
from services import push_governor as pg
from services import scheduler_service as ss
from services.db import SessionLocal, engine, init_db

ROOT = Path(__file__).resolve().parents[1]
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')

_tg = count(77167120000)


def _now():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def _free_talker(messages: int, *, hours_ago: float = 0.0) -> int:
    """Живой бесплатный аккаунт: переписывается и не прочь получить письмо."""
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        u = User(telegram_id=str(next(_tg)), name='t', selected_character='anna_01',
                 last_active_at=_now() - dt.timedelta(hours=hours_ago), proactive_enabled=True)
        s.add(u)
        s.commit()
        for i in range(messages):
            s.add(Message(user_id=u.id, character_id='anna_01', role='user', content=f'м{i}'))
        s.commit()
        return u.id


def _asked() -> set[int]:
    """Кому честное предложение положено прямо сейчас."""
    return {r[0] for r in ho.candidates()}


def _push_back(uid: int, days: int) -> None:
    """Отматывает последнюю метку предложения в прошлое: так в тесте проходит
    окно REPEAT_DAYS, которого в живой переписке ждут неделю."""
    with SessionLocal() as s:
        row = s.query(ProductEvent).filter_by(user_id=uid, event_name=ho.EVENT).order_by(
            ProductEvent.id.desc()).first()
        row.created_at = _now() - dt.timedelta(days=days)
        s.commit()


# ── 1. очереди включены ─────────────────────────────────────────────────────
def test_both_offer_queues_run_by_default():
    assert push_rail_on('first_offer') and push_rail_on('heavy_offer')
    assert {'first_offer', 'heavy_offer'} <= PUSH_RAILS


def test_the_offer_jobs_are_registered_by_their_names():
    src = inspect.getsource(ss.start_scheduler)
    for name in ('first_offer', 'heavy_offer'):
        assert f"push_rail_on('{name}')" in src, name
        assert f"id='{name}'" in src, name


# ── 3. диета пушей стоит перед слотом ───────────────────────────────────────
def test_the_gate_holds_before_the_slot_is_burned():
    i = SCHED.index('async def _first_offer(bot):')
    body = SCHED[i:SCHED.index('async def _showcase_voice(', i)]
    assert 0 < body.index('_push_ok') < body.index('fos.mark_offered(telegram_id)')
    j = SCHED.index('async def _heavy_offer(bot):')
    rail = SCHED[j:SCHED.index('async def _whats_new(bot):', j)]
    assert 0 < rail.index('_push_ok') < rail.index('ho.mark,')


def test_an_offer_spends_his_two_marketing_pushes_a_day(monkeypatch):
    init_db()
    monkeypatch.setattr(pg, 'local_hour', lambda tz: 12)
    monkeypatch.setattr(pg, 'PUSH_SPACING_WINDOW_MINUTES', 0)   # только дневной кап
    uid = _free_talker(ho.MIN_MESSAGES)
    assert pg.allow_push(uid, 'Europe/Moscow') == (True, '')
    with SessionLocal() as s:
        for name in ('first_offer_sent', 'heavy_offer_sent_ok'):
            s.add(ProductEvent(user_id=uid, character_id='anna_01', event_name=name,
                               value=0.0, created_at=_now(), metadata_json='{}'))
        s.commit()
    assert pg.pushes_today(uid, 'Europe/Moscow') == 2
    assert pg.allow_push(uid, 'Europe/Moscow') == (False, 'daily')


def test_an_offer_never_wakes_him_up(monkeypatch):
    init_db()
    monkeypatch.setattr(pg, 'local_hour', lambda tz: 3)
    uid = _free_talker(ho.MIN_MESSAGES)
    assert pg.allow_push(uid, 'Europe/Moscow') == (False, 'night')


# ── 2. порог и окно ─────────────────────────────────────────────────────────
def test_the_honest_offer_starts_where_people_really_are():
    # старый порог требовал пяти дней по 30 сообщений; теперь одного обычного
    assert ho.MIN_MESSAGES < CHAT_MSGS_PER_DAY == 30
    assert ho.MIN_MESSAGES == 15 and ho.ACTIVE_DAYS == 7


def test_the_offer_comes_again_after_the_window():
    uid = _free_talker(ho.MIN_MESSAGES)
    assert uid in _asked()
    ho.mark(uid, 'anna_01', ho.MIN_MESSAGES)
    assert uid not in _asked()                     # в окне она не повторяется
    _push_back(uid, ho.REPEAT_DAYS + 1)
    assert uid in _asked()                         # через неделю снова можно


def test_a_man_without_a_conversation_is_not_asked():
    uid = _free_talker(ho.MIN_MESSAGES - 1)
    assert uid not in _asked()


def test_a_man_who_stopped_coming_is_not_asked():
    uid = _free_talker(ho.MIN_MESSAGES + 5, hours_ago=24 * (ho.ACTIVE_DAYS + 1))
    assert uid not in _asked()


def test_the_words_no_longer_promise_a_once():
    ru, en = ho.text(ho.MIN_MESSAGES, 'ru'), ho.text(ho.MIN_MESSAGES, 'en')
    assert f'больше {ho.MIN_MESSAGES} сообщений' in ru and 'один раз' not in ru
    assert 'once' not in en
    for bad in ('осталось', 'только сегодня', 'обижусь', 'последний шанс'):
        assert bad not in ru
