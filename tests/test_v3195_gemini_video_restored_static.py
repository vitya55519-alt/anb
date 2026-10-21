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


def test_engine_chain_is_spicyapi_now():
    # V3.69.0: owner moved all video to SpicyAPI; Veo is out of the chain.
    job = MAIN[MAIN.index('async def _run_video_background('):]
    job = job.split('\n\n\n@dp.', 1)[0]
    assert 'engines.extend(video_engines())' in job
    assert "('gemini', animate_image)" not in MAIN
    helper = MAIN[MAIN.index('def _any_video_engine()'):MAIN.index('def _video_unavailable_text(')]
    assert 'spicy_video_available()' in helper


def test_gemini_photo_gets_transient_retry():
    fn = PHOTO[PHOTO.index('async def _gemini_image_one_frame'):PHOTO.index('async def _run_gemini_set')]
    assert 'retryable_statuses = {408, 429, 500, 502, 503, 504}' in fn
    # V3.43.1: two retries with growing backoff instead of a single one.
    assert 'for attempt in range(3):' in fn
    assert fn.count('- retrying') >= 3
    assert 'await asyncio.sleep(2.0 * (attempt + 1))' in fn
