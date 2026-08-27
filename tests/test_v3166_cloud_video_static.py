"""Static regression tests for the cloud i2v providers (Replicate + fal.ai)
added as reliable video fallbacks after the HF public spaces proved flaky."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
CLOUD_VIDEO = (ROOT / 'services' / 'cloud_video_service.py').read_text(encoding='utf-8')
HF_VIDEO = (ROOT / 'services' / 'hf_video_service.py').read_text(encoding='utf-8')
REQUIREMENTS = (ROOT / 'requirements.txt').read_text(encoding='utf-8')


def test_cloud_video_service_exports():
    assert 'class CloudVideoError' in CLOUD_VIDEO
    assert 'async def animate_image_replicate(' in CLOUD_VIDEO
    assert 'async def animate_image_fal(' in CLOUD_VIDEO
    assert 'def replicate_available()' in CLOUD_VIDEO
    assert 'def fal_available()' in CLOUD_VIDEO


def test_cloud_video_dependencies_installed():
    assert 'replicate' in REQUIREMENTS
    assert 'fal-client' in REQUIREMENTS
    assert 'gradio-client' in REQUIREMENTS


def test_config_exposes_replicate_and_fal():
    assert 'REPLICATE_API_TOKEN' in CONFIG
    assert 'REPLICATE_VIDEO_MODEL' in CONFIG
    assert 'minimax/hailuo-2.3-fast' in CONFIG
    assert 'FAL_KEY' in CONFIG
    assert 'FAL_VIDEO_ENDPOINT' in CONFIG
    assert 'fal-ai/wan2.2/image-to-video' in CONFIG


def test_video_job_orchestrates_cloud_engines_before_hf():
    # Cloud providers must be tried in order: gemini -> replicate -> fal -> hf.
    job = MAIN[MAIN.index('async def _run_video_background('):]
    job = job.split('\n\n\n@dp.', 1)[0]
    order = (
        job.index("engines.append(('gemini'"),
        job.index("engines.append(('replicate'"),
        job.index("engines.append(('fal'"),
        job.index("engines.append(('hf'"),
    )
    assert order == tuple(sorted(order)), 'engine order must be gemini, replicate, fal, hf'
    assert 'replicate_available' in MAIN
    assert 'fal_available' in MAIN
    assert 'animate_image_replicate' in MAIN
    assert 'animate_image_fal' in MAIN


def test_any_video_engine_helper_used_everywhere():
    assert 'def _any_video_engine()' in MAIN
    # /videotest, the two video callback gates, and the Stars pre-checkout
    # validation all consult the same unified helper now.
    assert MAIN.count('_any_video_engine()') >= 4
    assert 'video_available() or hf_video_available()' not in MAIN


def test_fal_uses_subscribe_and_data_url():
    assert 'fal_client.subscribe' in CLOUD_VIDEO
    assert 'data_url' in CLOUD_VIDEO
    # Both providers share the same animation prompt to keep output consistent.
    assert 'ANIMATION_PROMPT' in CLOUD_VIDEO
