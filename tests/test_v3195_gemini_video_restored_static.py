"""Static regression tests for v3.19.5: Gemini/Veo video restored.

Owner decision: Gemini/Veo is the primary video engine again (it was briefly
removed in v3.19.4). Replicate (hailuo), fal.ai and the free HF spaces stay
as the fallback chain. The v3.19.3 key gate is kept, so a dirty-pasted
GEMINI_API_KEY still cannot poison video. Gemini photo generation (Nano
Banana) additionally gets one automatic retry on transient failures.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
VIDEO = (ROOT / 'services' / 'gemini_video_service.py').read_text(encoding='utf-8')


def test_gemini_video_service_restored():
    assert (ROOT / 'services' / 'gemini_video_service.py').exists()
    assert ':predictLongRunning' in VIDEO
    assert 'def video_available()' in VIDEO
    assert 'GEMINI_VIDEO_ENABLED' in VIDEO


def test_gemini_video_enabled_only_with_valid_key():
    assert 'GEMINI_VIDEO_ENABLED = bool(GEMINI_API_KEY_VALID) and _GEMINI_VIDEO_FLAG not in {"0", "false", "no", "off"}' in CONFIG
    assert '"veo-3.1-lite-generate-preview"' in CONFIG


def test_engine_chain_starts_with_gemini():
    job = MAIN[MAIN.index('async def _run_video_background('):]
    job = job.split('\n\n\n@dp.', 1)[0]
    assert "engines.append(('gemini', animate_image))" in job
    order = (
        job.index("engines.append(('gemini'"),
        job.index("engines.append(('replicate'"),
        job.index("engines.append(('fal'"),
        job.index("engines.append(('hf'"),
    )
    assert order == tuple(sorted(order)), 'engine order must be gemini, replicate, fal, hf'
    # The availability helper counts Gemini again.
    helper = MAIN[MAIN.index('def _any_video_engine()'):MAIN.index('def _video_unavailable_text(')]
    assert 'video_available()' in helper


def test_admin_diagnostics_cover_gemini_again():
    assert 'нет/битый GEMINI_API_KEY (должен быть чистый ASCII)' in MAIN
    status = MAIN[MAIN.index('async def gemini_status_cmd('):]
    assert 'Gemini Video' in status
    assert 'video_available()' in status


def test_gemini_photo_gets_transient_retry():
    fn = PHOTO[PHOTO.index('async def _gemini_image_one_frame'):PHOTO.index('async def _run_gemini_set')]
    assert 'retryable_statuses = {408, 429, 500, 502, 503, 504}' in fn
    assert 'for attempt in range(2):' in fn
    assert fn.count('- retrying once') >= 3
    assert 'await asyncio.sleep(2.0)' in fn
