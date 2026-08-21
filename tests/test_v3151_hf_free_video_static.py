from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
REQS = (ROOT / 'requirements.txt').read_text(encoding='utf-8')
SERVICE_PATH = ROOT / 'services' / 'hf_video_service.py'
SERVICE = SERVICE_PATH.read_text(encoding='utf-8')


def test_hf_video_config_exists():
    assert 'HF_VIDEO_ENABLED' in CONFIG
    assert 'HF_VIDEO_SPACE' in CONFIG
    assert 'HF_VIDEO_TIMEOUT_SECONDS' in CONFIG
    assert 'HF_VIDEO_FREE_DAILY_LIMIT' in CONFIG
    # Free public space route: no API key in the config block.
    block = CONFIG[CONFIG.index('HF_VIDEO_ENABLED'):CONFIG.index('HF_VIDEO_FREE_DAILY_LIMIT')]
    assert 'API_KEY' not in block


def test_gradio_client_dependency_present():
    assert 'gradio-client' in REQS


def test_hf_video_service_surface():
    assert 'def hf_video_available()' in SERVICE
    assert 'async def animate_image_hf(' in SERVICE
    assert 'class HfVideoError' in SERVICE
    # Endpoint is discovered from the space API schema, not hardcoded.
    assert 'view_api' in SERVICE
    # Blocking gradio call must run off the event loop.
    assert 'asyncio.to_thread' in SERVICE
    # Identity-preserving, non-explicit animation prompt.
    assert 'no sexual action, no nudity' in SERVICE


def test_main_wires_free_video_route():
    assert "from services.hf_video_service import animate_image_hf, HfVideoError, hf_video_available" in MAIN
    assert "'video:animate_last_free'" in MAIN
    assert 'async def _run_hf_video_background(' in MAIN
    assert '_hf_video_daily_ok' in MAIN
    assert '_hf_video_daily_consume' in MAIN
    # User is warned about the public-server queue wait time.
    assert '1–3 минуты' in MAIN
    # Paid Gemini route stays the priority when enabled.
    assert MAIN.index('if GEMINI_VIDEO_ENABLED') < MAIN.index("'video:animate_last_free'")
