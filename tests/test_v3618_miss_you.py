"""V3.61.8: «я скучала» gift pool, proactive lines in the app chat, welcome back."""
import os
os.environ.setdefault('TELEGRAM_TOKEN', '123456:test-fake')
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_gift_plan_covers_every_heroine_with_face_framing():
    from services import gift_pool_service as g
    plan = g.plan_gift_pool(20, heroines=['a', 'b', 'c', 'd', 'e', 'f'])
    assert {cid for cid, _ in plan} == {'a', 'b', 'c', 'd', 'e', 'f'}
    assert len(plan) >= 20
    for cid in 'abcdef':
        shots = [s for c, s in plan if c == cid]
        assert len(shots) == len(set(shots))  # different moments per heroine
    req = g.gift_request(plan[0][1])
    assert 'ENTIRE face' in req.angle and 'never crop her head' in req.angle
    assert req.customized and req.location


def test_gift_plan_empty_without_heroines():
    from services import gift_pool_service as g
    assert g.plan_gift_pool(20, heroines=[]) == []


def test_admin_has_generate_and_clear_buttons():
    src = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert "callback_data='admin:prophoto:gen'" in src
    assert "callback_data='admin:prophoto:clear:yes'" in src
    assert 'fill_gift_pool' in src


def test_proactive_lines_land_in_app_chat():
    src = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
    assert 'def _to_app_chat(' in src
    assert src.count('_to_app_chat(') >= 4  # def + miss tier + ritual + random gift
    gift = (ROOT / 'services' / 'private_photo_service.py').read_text(encoding='utf-8')
    assert '_to_app_chat(uid, telegram_id, gift_char' in gift


def test_welcome_back_only_after_silence():
    from services.db import init_db, SessionLocal
    from services.presence_service import maybe_welcome_back, WELCOME_BACK_HOURS
    from models.app_models import Message
    init_db()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    uid, cid = 987650, 'anna_01'
    with SessionLocal() as s:
        s.query(Message).filter(Message.user_id == uid).delete()
        s.commit()
    assert maybe_welcome_back(uid, cid, now=now) is None  # empty chat: nothing
    with SessionLocal() as s:
        s.add(Message(user_id=uid, character_id=cid, role='user', content='пока',
                      created_at=now - timedelta(hours=WELCOME_BACK_HOURS + 1)))
        s.commit()
    line = maybe_welcome_back(uid, cid, now=now)
    assert line
    assert maybe_welcome_back(uid, cid, now=now) is None  # no stacking
    with SessionLocal() as s:
        rows = s.query(Message).filter(Message.user_id == uid).order_by(Message.created_at).all()
        assert rows[-1].role == 'assistant' and rows[-1].content == line


def test_welcome_back_only_on_real_open():
    src = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert "opening = request.query.get('open') == '1'" in src
    spa = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
    assert "encodeURIComponent(characterId) + '&open=1'" in spa
