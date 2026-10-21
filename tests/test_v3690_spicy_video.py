"""V3.69.0: all video and circles on SpicyAPI; circles are square selfie
clips that say a line from the dialogue; user frames never hit the spicy model."""
import asyncio
import io
import os
from pathlib import Path

os.environ.setdefault("TELEGRAM_TOKEN", "123456:test-fake-token-for-static-tests-only")

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SVC = (ROOT / 'services' / 'spicy_video_service.py').read_text(encoding='utf-8')


def test_no_old_engines_in_main():
    for gone in ('gemini_video_service', 'hf_video_service', 'animate_image_replicate',
                 'animate_image_fal', 'animate_image_hf', 'replicate_available()', 'fal_available()'):
        assert gone not in MAIN, gone
    assert MAIN.count('video_engines()') >= 7


def test_frame_route_and_square_circles():
    assert "app.router.add_get('/webapp/vsrc/{token}', _webapp_video_frame)" in MAIN
    assert MAIN.count('square_frame(image_bytes)') == 2
    assert MAIN.count('CIRCLE_PROMPT.format(phrase=phrase)') == 2
    assert 'handheld front-camera selfie' in MAIN


def test_studio_runs_safe_model():
    fn = MAIN[MAIN.index('async def _webapp_api_studio_video('):]
    fn = fn[:fn.index('\nasync def ', 10)]
    assert 'safe=True' in fn
    assert "'upload_admin_only'" in fn


def test_service_safe_switch_and_payload(monkeypatch):
    from services import spicy_video_service as v
    sent = {}

    async def fake_call(method, path, headers=None, **kw):
        if method == 'POST':
            sent.update(kw['json'])
            return {'taskId': 't1'}
        return {'state': 'failed', 'errorCode': 'x'}

    import services.private_photo_service as pps
    monkeypatch.setattr(pps, '_spicyapi_call', fake_call)
    monkeypatch.setattr(v, 'spicy_video_available', lambda: True)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(v.asyncio, 'sleep', lambda *_a, **_k: real_sleep(0))
    try:
        asyncio.run(v.animate_image_spicy(b'img', prompt='smile', safe=True))
    except v.CloudVideoError:
        pass
    assert sent['model'] == v.SPICYAPI_VIDEO_SAFE_MODEL
    assert 'fully clothed' in sent['input']['prompt']
    assert sent['input']['image_url'].split('/webapp/vsrc/')[1]
    token = sent['input']['image_url'].rsplit('/', 1)[1]
    assert v.parked_frame(token) == (b'img', 'image/jpeg')
    assert 3 <= sent['input']['duration_seconds'] <= 15


def test_square_frame_is_square():
    from PIL import Image
    from services.spicy_video_service import square_frame
    buf = io.BytesIO()
    Image.new('RGB', (600, 900), 'red').save(buf, format='JPEG')
    out = Image.open(io.BytesIO(square_frame(buf.getvalue())))
    assert out.size[0] == out.size[1] == 600


def test_spicy_model_is_default_for_her_frames():
    assert 'model = SPICYAPI_VIDEO_MODEL' in SVC
    assert 'if safe:' in SVC
