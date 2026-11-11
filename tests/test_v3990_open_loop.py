"""V3.99.0 — the open loop: after a long session she leaves a promise for the morning."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services import open_loop
from services.db import SessionLocal, engine
from models.app_models import Base, Message, ProductEvent, User

ROOT = Path(__file__).resolve().parents[1]
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _setup(n_messages: int, hours_ago: float = 1.0):
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        u = User(telegram_id=f'loop{n_messages}{hours_ago}{_now().timestamp()}', name='t')
        s.add(u); s.flush()
        for i in range(n_messages):
            s.add(Message(user_id=u.id, character_id='anna_01', role='user', content=f'm{i}',
                          created_at=_now() - timedelta(hours=hours_ago, minutes=i)))
        s.commit()
        return u.id


def test_short_session_gets_no_loop():
    uid = _setup(5)
    assert open_loop.directive_for(uid, 'anna_01', 'flirt') == ('', '')


def test_long_session_plants_once_then_holds_then_kept():
    uid = _setup(open_loop.THRESHOLD - 1)
    note, kind = open_loop.directive_for(uid, 'anna_01', 'flirt')
    assert kind == 'plant' and note == open_loop.PLANT_DIRECTIVE
    open_loop.record_planted(uid, 'anna_01', 'мне пора бежать, но завтра утром расскажу тебе один секрет 🙈')
    assert open_loop.directive_for(uid, 'anna_01', 'flirt')[1] == 'hold'
    assert 'секрет' in open_loop.pending(uid, 'anna_01')
    open_loop.mark_kept(uid, 'anna_01')
    assert open_loop.pending(uid, 'anna_01') == ''
    # cooldown: no second loop for COOLDOWN_DAYS
    assert open_loop.directive_for(uid, 'anna_01', 'flirt') == ('', '')


def test_old_session_serious_talk_and_premium_skip():
    assert open_loop.directive_for(_setup(open_loop.THRESHOLD, hours_ago=20), 'anna_01', 'flirt') == ('', '')
    uid = _setup(open_loop.THRESHOLD)
    assert open_loop.directive_for(uid, 'anna_01', 'support') == ('', '')
    assert open_loop.directive_for(uid, 'anna_01', 'flirt', plant_ok=False) == ('', '')


def test_chat_never_cuts_a_long_session_but_old_morning_promises_are_kept():
    assert 'open_loop.directive_for' not in CHAT
    assert 'open_loop.record_planted' not in CHAT
    assert 'open_loop.pending' in CHAT and 'open_loop.mark_kept' in CHAT
