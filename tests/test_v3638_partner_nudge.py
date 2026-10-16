"""V3.62.13: active users get a reminder that the partner link pays real money."""
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')


def test_job_registered():
    assert "scheduler.add_job(_partner_nudge,'interval',hours=2" in SCHED
    assert "track_event(uid, 'partner_nudge_sent'" in SCHED
    assert "callback_data='partner:open'" in SCHED


def test_copy_mentions_real_money_and_link():
    from services import partner_service
    t = partner_service.partner_nudge_text('ru', 'https://t.me/x?start=ref_1')
    assert 'реальные деньги' in t and 'https://t.me/x?start=ref_1' in t
    assert partner_service.partner_share_url('ru', 'https://t.me/x?start=ref_1').startswith('https://t.me/share/url?url=https%3A')


def test_due_gating():
    from services.db import SessionLocal, init_db
    from models.app_models import User
    from services import partner_service
    from services.analytics_service import track_event
    init_db()
    now = dt.datetime.utcnow()
    with SessionLocal() as s:
        old = User(telegram_id='990001', adult_confirmed=True, proactive_enabled=True,
                   created_at=now - dt.timedelta(days=5), last_active_at=now - dt.timedelta(hours=3))
        new = User(telegram_id='990002', adult_confirmed=True, proactive_enabled=True,
                   created_at=now - dt.timedelta(hours=10), last_active_at=now - dt.timedelta(hours=1))
        s.add_all([old, new]); s.commit()
        old_id, new_id = old.id, new.id
    due = {r[0] for r in partner_service.due_partner_nudges(now)}
    assert old_id in due and new_id not in due
    track_event(old_id, 'partner_nudge_sent')
    due = {r[0] for r in partner_service.due_partner_nudges(now + dt.timedelta(minutes=1))}
    assert old_id not in due
