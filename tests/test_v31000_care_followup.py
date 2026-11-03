"""V3.100.0 — she hears it when he is down and asks the next morning."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from models.app_models import Base, ProductEvent, User
from services import care_followup as cf
from services.db import SessionLocal, engine

ROOT = Path(__file__).resolve().parents[1]
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')


def _uid():
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        u = User(telegram_id=f'care{datetime.now().timestamp()}', name='t')
        s.add(u); s.commit()
        return u.id


def test_classify():
    assert cf.classify('Я так устал сегодня') == 'care'
    assert cf.classify('мне грустно') == 'care'
    assert cf.classify("I'm so tired of everything") == 'care'
    assert cf.classify('не хочу жить') == 'crisis'
    assert cf.classify('I want to die') == 'crisis'
    assert cf.classify('привет, как дела?') == ''
    assert cf.classify('я не устал, всё отлично') == ''
    assert cf.classify('') == ''


def test_records_kind_only_once_and_asks_next_morning():
    uid = _uid()
    note, kind = cf.directive_for(uid, 'anna_01', 'Мне плохо, я так устал')
    assert kind == 'care' and note == cf.CARE_DIRECTIVE
    cf.directive_for(uid, 'anna_01', 'ещё и грустно')  # cooldown: still one record
    with SessionLocal() as s:
        rows = s.query(ProductEvent).filter(ProductEvent.user_id == uid, ProductEvent.event_name == cf.NOTED).all()
    assert len(rows) == 1
    assert 'устал' not in (rows[0].metadata_json or '')  # his words are never stored
    assert cf.pending(uid, 'anna_01') == 'care'
    cf.mark_sent(uid, 'anna_01')
    assert cf.pending(uid, 'anna_01') == ''


def test_crisis_directive_is_serious():
    uid = _uid()
    note, kind = cf.directive_for(uid, 'anna_01', 'я не хочу жить')
    assert kind == 'crisis' and 'всерьёз' in note and 'Не выдумывай номера' in note
    assert cf.pending(uid, 'anna_01') == 'crisis'


def test_old_mood_is_not_asked_about():
    uid = _uid()
    with SessionLocal() as s:
        s.add(ProductEvent(user_id=uid, character_id='anna_01', event_name=cf.NOTED, metadata_json='{"kind": "care"}',
                           created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=48)))
        s.commit()
    assert cf.pending(uid, 'anna_01') == ''


def test_wired_into_chat_before_hook_and_in_morning():
    assert CHAT.index('care_followup.directive_for') < CHAT.index('next_hook(user_id, character_id, behavior_kind')
    assert 'and not care_kind' in CHAT
    assert 'care_followup.pending' in CHAT and 'care_followup.mark_sent' in CHAT
    assert 'care_followup.MORNING_LINE' in CHAT
