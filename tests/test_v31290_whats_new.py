"""V3.129.0 — «что у нас нового» once per round for the men who left."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from models.app_models import Base, Message, User
from services import whats_new as wn
from services.db import SessionLocal, engine

ROOT = Path(__file__).resolve().parents[1]
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _user(days_silent: float, *, talked=True, pushes=True) -> int:
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        u = User(telegram_id=str(int(datetime.now().timestamp() * 1e6) % 10**12), name='t',
                 last_active_at=_now() - timedelta(days=days_silent), proactive_enabled=pushes)
        s.add(u); s.commit()
        if talked:
            s.add(Message(user_id=u.id, character_id='anna_01', role='user', content='привет'))
            s.commit()
        return u.id


def _ids():
    return {r[0] for r in wn.candidates(limit=10_000)}


def test_only_men_silent_past_the_push_ladder():
    gone = _user(20)
    fresh = _user(3)
    ancient = _user(wn.MAX_DAYS + 5)
    silent_never_talked = _user(20, talked=False)
    pushes_off = _user(20, pushes=False)
    ids = _ids()
    assert gone in ids
    assert not ids & {fresh, ancient, silent_never_talked, pushes_off}


def test_once_per_round():
    uid = _user(15)
    assert uid in _ids()
    wn.mark(uid, 'anna_01')
    assert uid not in _ids()


def test_text_is_honest_and_once():
    ru = wn.text('Аня', 'ru')
    assert 'Аня' in ru and 'один раз' in ru and 'позвонить' in ru and 'Premium' in ru
    for bad in ('обиделась', 'последний шанс', 'только сегодня', 'осталось'):
        assert bad not in ru
    en = wn.text('Anna', 'en')
    assert 'just once' in en and 'Anna' in en


def test_scheduler_wired_daytime_and_blocked_users():
    assert "id='whats_new'" in SCHED
    body = SCHED.split('async def _whats_new(bot):', 1)[1].split('\nasync def ', 1)[0]
    assert '_msk_daytime()' in body
    assert 'wn.mark,' in body and body.index('wn.mark,') < body.index('send_message(')
    assert '_mark_blocked(uid)' in body
