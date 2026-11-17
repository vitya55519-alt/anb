"""V3.101.0 — evening «как прошёл день» tied to what she knows, and pushes on his last topic."""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from models.app_models import Base, Message, User
from services import chat_service
from services.db import SessionLocal, engine

ROOT = Path(__file__).resolve().parents[1]
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')


def _user_with_talk(hours_ago: float, n_user: int = 4):
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        u = User(telegram_id=str(int(datetime.now().timestamp() * 1000) % 10**9 + 7), name='t')
        s.add(u); s.flush()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for i in range(n_user):
            t = now - timedelta(hours=hours_ago, minutes=(n_user - i) * 2)
            s.add(Message(user_id=u.id, character_id='anna_01', role='user', content=f'у меня завтра экзамен {i}', created_at=t))
            s.add(Message(user_id=u.id, character_id='anna_01', role='assistant', content=f'удачи {i}', created_at=t + timedelta(seconds=30)))
        s.commit()
        return int(u.telegram_id)


def _capture(monkeypatch):
    seen = {}

    async def fake(messages, **kw):
        seen['system'] = messages[0]['content']
        seen['last'] = messages[-1]['content']
        return SimpleNamespace(text='ну как там твой экзамен, всё получилось? 🙈', complete=True)
    monkeypatch.setattr(chat_service, 'generate_text', fake)
    return seen


def test_evening_callback_asks_about_his_day(monkeypatch):
    seen = _capture(monkeypatch)
    tg = _user_with_talk(hours_ago=50)
    out = asyncio.run(chat_service.morning_callback(tg, 't', 'ru', 'anna_01', evening=True))
    assert out
    assert 'Сейчас вечер' in seen['system'] and 'как прошёл его день' in seen['system']
    assert seen['last'].startswith('Вечер')


def test_morning_window_stays_36_hours(monkeypatch):
    _capture(monkeypatch)
    tg = _user_with_talk(hours_ago=50)
    assert asyncio.run(chat_service.morning_callback(tg, 't', 'ru', 'anna_01')) == ''


def test_topic_push_uses_the_last_topic_line(monkeypatch):
    seen = _capture(monkeypatch)
    tg = _user_with_talk(hours_ago=30)
    out = asyncio.run(chat_service.proactive_reply(tg, 't', 30, character_id='anna_01', topic=True))
    assert out and 'ТОЧНОЙ теме' in seen['system']
    seen.clear()
    asyncio.run(chat_service.proactive_reply(tg, 't', 30, character_id='anna_01'))
    assert 'ТОЧНОЙ теме' not in seen['system']


def test_topic_composition_does_not_persist_before_app_delivery(monkeypatch):
    from sqlalchemy import select
    from services import app_ping, scheduler_service

    _capture(monkeypatch)
    tg = _user_with_talk(hours_ago=30)
    with SessionLocal() as s:
        uid = s.scalar(select(User.id).where(User.telegram_id == str(tg)))
        before = s.query(Message).filter_by(user_id=uid).count()
    out = asyncio.run(chat_service.proactive_reply(
        tg, 't', 30, character_id='anna_01', topic=True, persist=False))
    assert out
    with SessionLocal() as s:
        assert s.query(Message).filter_by(user_id=uid).count() == before
    notifications = []
    monkeypatch.setattr(app_ping, 'note', lambda *a, **kw: notifications.append((a, kw)))
    bot = object()
    mid = scheduler_service._app_delivery(bot, uid, tg, 'anna_01', out)
    with SessionLocal() as s:
        assert s.query(Message).filter_by(user_id=uid).count() == before + 1
        row = s.get(Message, mid)
        assert row.content == out and row.origin == 'push' and row.role == 'assistant'
        assert row.character_id == 'anna_01'
    assert notifications == [((bot, tg, 'anna_01', ''), {'channel': 'default', 'generic': True})]


def test_topic_push_needs_some_talk(monkeypatch):
    seen = _capture(monkeypatch)
    tg = _user_with_talk(hours_ago=30, n_user=1)
    asyncio.run(chat_service.proactive_reply(tg, 't', 30, character_id='anna_01', topic=True))
    assert 'ТОЧНОЙ теме' not in seen['system']


def test_scheduler_wiring():
    assert "morning_callback(int(tg_id), name, _el, char_id, evening=True)" in SCHED
    assert "evening_callback_sent" in SCHED
    proactive = SCHED[SCHED.index('async def _proactive('):SCHED.index('async def _day1_hook(')]
    # Both tiers compose without saving; the delivery helper owns the one row.
    assert proactive.count('proactive_reply(') == 2
    assert proactive.count('proactive_reply(telegram_id,name,hours,character_id=char_id,topic=True,persist=False)') == 2
    assert proactive.count('if not _app_delivery(bot,uid,telegram_id,char_id,msg):') == 2
    assert 'bot.send_message(' not in proactive and 'bot.send_photo(' not in proactive
    assert "kind=kind+'_topic'" in proactive
