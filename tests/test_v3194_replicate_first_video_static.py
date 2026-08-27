"""Static regression tests for v3.19.4: Replicate-first video, Gemini/Veo out.

The owner dropped Gemini/Veo video entirely (no paid Google billing). The
video engine chain is now Replicate (default minimax/hailuo-2.3-fast, best
human-motion fit for the kiss/hug/dance presets) -> fal.ai -> HF spaces.
Gemini keeps only chat-fallback + image duties, gated by the v3.19.3 key
validity check.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CLOUD = (ROOT / 'services' / 'cloud_video_service.py').read_text(encoding='utf-8')


def test_gemini_video_engine_removed_completely():
    assert not (ROOT / 'services' / 'gemini_video_service.py').exists()
    assert 'GEMINI_VIDEO_ENABLED' not in CONFIG
    assert 'GEMINI_VIDEO_MODEL' not in CONFIG
    assert 'veo-3.1-lite-generate-preview' not in CONFIG
    assert 'gemini_video_service' not in MAIN
    # Only hf_video_available() may contain the suffix now.
    assert MAIN.count('video_available()') == MAIN.count('hf_video_available()')
    assert 'GeminiVideoError' not in MAIN


def test_replicate_is_default_with_hailuo_model():
    assert 'REPLICATE_VIDEO_MODEL = os.getenv(' in CONFIG
    assert '"minimax/hailuo-2.3-fast"' in CONFIG
    assert '"minimax/video-01"' not in CONFIG


def test_replicate_image_param_maps_per_model_owner():
    assert 'def _replicate_image_param(model: str) -> str:' in CLOUD
    assert "return 'first_frame_image'" in CLOUD  # minimax
    assert "return 'img'" in CLOUD                 # wan-*
    assert "return 'image'" in CLOUD               # kling/luma/etc.
    # The payload uses the mapping instead of a hard-coded key.
    assert '_replicate_image_param(REPLICATE_VIDEO_MODEL): Path(tmp_path)' in CLOUD


def test_engine_chain_is_replicate_fal_hf():
    job = MAIN[MAIN.index('async def _run_video_background('):]
    job = job.split('\n\n\n@dp.', 1)[0]
    assert "engines.append(('gemini'" not in job
    assert "engines.append(('replicate'" in job
    first = job.index("engines.append(('replicate'")
    assert first < job.index("engines.append(('fal'") < job.index("engines.append(('hf'")
    # The unified job raises the cloud error type, not the removed Gemini one.
    assert "raise CloudVideoError('no_video_engine')" in job
    assert "raise last_error or CloudVideoError('no_video_result')" in job


def test_unavailable_alert_lists_cloud_engine_keys_only():
    alert = MAIN[MAIN.index('def _video_unavailable_text('):MAIN.index('from services.llm_provider_service')]
    assert 'нет REPLICATE_API_TOKEN' in alert
    assert 'нет FAL_KEY' in alert
    assert 'GEMINI_API_KEY' not in alert


def test_video_gate_helpers_ignore_gemini():
    helper = MAIN[MAIN.index('def _any_video_engine()'):MAIN.index('def _video_unavailable_text(')]
    assert ' video_available()' not in helper
    assert 'replicate_available()' in helper
    # Keyboard gates consult the unified helper, not the removed Gemini flag.
    assert 'GEMINI_VIDEO_ENABLED' not in MAIN
