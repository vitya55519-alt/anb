"""V3.110.0: a ready photo of her comes with the evening voice."""
from pathlib import Path

from services import evening_voice as ev

ROOT = Path(__file__).resolve().parents[1]
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')


def test_evening_photo_uses_ready_photos_only(monkeypatch):
    import services.chat_photo_allowance as cpa
    calls = []

    def fake(char, uid=None):
        calls.append((char, uid))
        return b'jpg', 'image/jpeg', 'jpg'

    monkeypatch.setattr(cpa, 'reused_photo', fake)
    monkeypatch.setattr(ev, 'PHOTO_ENABLED', True)
    assert ev.evening_photo('anna_01', 7) == (b'jpg', 'image/jpeg', 'photo')
    assert calls == [('anna_01', 7)]
    monkeypatch.setattr(ev, 'PHOTO_ENABLED', False)
    assert ev.evening_photo('anna_01', 7) is None


def test_evening_photo_none_when_nothing_ready(monkeypatch):
    import services.chat_photo_allowance as cpa
    monkeypatch.setattr(cpa, 'reused_photo', lambda c, u=None: None)
    monkeypatch.setattr(ev, 'PHOTO_ENABLED', True)
    assert ev.evening_photo('anna_01', 7) is None


def test_no_new_render_and_no_spicy():
    src = (ROOT / 'services' / 'evening_voice.py').read_text(encoding='utf-8')
    block = src[src.index('def evening_photo'):src.index('CAST_LINES')]
    assert 'reused_photo' in block
    for bad in ('spicy', 'generate', 'seedream', 'render_'):
        assert bad not in block.split('"""')[-1].lower()


def test_scheduler_sends_photo_then_voice():
    assert "evening_shot=await asyncio.to_thread(_ev.evening_photo, char_id, uid)" in SCHED
    block = SCHED[SCHED.index('if evening_voice and evening_shot:'):SCHED.index('elif evening_voice and not shot:')]
    assert block.index('send_photo') < block.index('send_voice')
    assert "track_event(uid, 'evening_photo_sent'" in block
    assert 'is_premium' not in block
