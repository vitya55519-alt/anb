"""V3.112.0 — photo animation only with Premium for a month or longer, one a day,
nothing free, not sold for Stars or tokens."""
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_one_a_day_by_default():
    from config import VIDEO_PREMIUM_FREE_DAILY, VIDEO_MIN_PLAN_DAYS
    assert VIDEO_PREMIUM_FREE_DAILY == 1 and VIDEO_MIN_PLAN_DAYS == 28


def test_bot_gate_has_no_stars_or_token_route():
    i = MAIN.index('async def _video_gate(')
    body = MAIN[i:MAIN.index('def _video_month_wall_text(', i)]
    assert 'has_monthly_premium(cq.from_user.id)' in body
    assert 'send_stars_invoice' not in body and 'spend_tokens' not in body
    assert "elif payload.startswith('video:'):" in MAIN
    j = MAIN.index("elif payload.startswith('video:'):")
    assert 'ok = False' in MAIN[j:j + 500]


def test_app_paths_require_month():
    assert MAIN.count("'month_required'") >= 2
    assert "j.error === 'month_required'" in SPA and "kind === 'month' ? ['premium', 'premium_quarter']" in SPA


def test_has_monthly_premium_counts_plan_length():
    from services.db import SessionLocal, engine
    from models.app_models import Base, Subscription, User
    from services.payments import has_monthly_premium, consume_premium_video_free
    Base.metadata.create_all(engine)
    now = dt.datetime.utcnow()
    with SessionLocal() as s:
        week = User(telegram_id='311201'); month = User(telegram_id='311202')
        s.add_all([week, month]); s.commit()
        s.add(Subscription(user_id=week.id, plan='premium', status='active', started_at=now, expires_at=now + dt.timedelta(days=7)))
        s.add(Subscription(user_id=month.id, plan='premium', status='active', started_at=now, expires_at=now + dt.timedelta(days=30)))
        s.commit()
    assert not has_monthly_premium(311201) and not consume_premium_video_free(311201)
    assert has_monthly_premium(311202)
    assert consume_premium_video_free(311202) and not consume_premium_video_free(311202)
