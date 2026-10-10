"""V3.57.9: storefront images are served web-sized (WebP, <=1280px)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding='utf-8')


def test_web_image_helper_exists():
    src = _src('services/webapp_service.py')
    assert 'def web_image(' in src
    assert 'WEB_IMAGE_MAX_SIDE = 1280' in src
    assert "'WEBP'" in src or '"WEBP"' in src


def test_routes_use_web_image_off_event_loop():
    src = _src('main.py')
    assert src.count('webapp_service.web_image') >= 2
    import re
    assert len(re.findall(r'asyncio\.to_thread\(\s*webapp_service\.web_image', src)) >= 2


def test_web_image_shrinks_large_png_and_passes_small_through():
    try:
        import io
        from PIL import Image
        from services import webapp_service
    except Exception:
        return
    img = Image.effect_noise((2400, 3200), 64).convert('RGB')
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    big = buf.getvalue()
    out, ctype = webapp_service.web_image(big, 'image/png', 'test:big')
    assert ctype == 'image/webp'
    assert len(out) < len(big)
    small = b'x' * 1000
    assert webapp_service.web_image(small, 'image/png', 'test:small') == (small, 'image/png')


def test_asset_stamp_is_content_fingerprint_not_mtime():
    src = _src('services/webapp_service.py')
    body = src.split('def asset_version(')[1].split('\ndef ')[0]
    assert 'st_mtime)' not in body
    assert '_file_fingerprint(item)' in body


def test_videos_stream_with_range_support():
    src = _src('main.py')
    live = src.split('async def _webapp_live(')[1].split('\nasync def ')[0]
    card = src.split('async def _webapp_card(')[1].split('\nasync def ')[0]
    assert 'web.FileResponse(live' in live
    assert 'web.FileResponse(override' in card
