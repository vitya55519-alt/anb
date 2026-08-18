from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
PROVIDER = (ROOT / 'services' / 'llm_provider_service.py').read_text(encoding='utf-8')
VIDEO = (ROOT / 'services' / 'gemini_video_service.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def test_openrouter_is_primary_with_gemini_fallback_and_no_openai_chat():
    assert 'OPENROUTER_API_KEY' in CONFIG
    assert 'OPENROUTER_MODEL' in CONFIG
    assert 'GEMINI_API_KEY' in CONFIG
    assert 'GEMINI_CHAT_MODEL' in CONFIG
    assert 'gemini-3.5-flash' in CONFIG
    # Legacy provider-switching env vars were removed; chain is hard-wired.
    assert 'CHAT_PROVIDER' not in CONFIG
    assert 'CHAT_FALLBACK_OPENAI' not in CONFIG
    assert 'CHAT_FALLBACK_GEMINI' not in CONFIG
    assert 'provider=openrouter' in PROVIDER
    assert 'provider=gemini' in PROVIDER
    assert 'LLM unavailable' in PROVIDER


def test_visible_dialogue_and_proactive_use_shared_provider():
    assert "purpose='dialogue'" in CHAT
    assert "purpose='rewrite'" in CHAT
    assert "purpose='proactive'" in CHAT
    assert 'AsyncOpenAI' not in CHAT


def test_video_is_paid_feature_flagged_and_has_automatic_refund_path():
    assert 'GEMINI_VIDEO_ENABLED' in CONFIG
    assert 'veo-3.1-lite-generate-preview' in CONFIG
    assert 'VIDEO_COST_STARS' in CONFIG
    assert "callback_data='video:animate_last'" in MAIN
    assert "payload.startswith('video:')" in MAIN
    assert 'refund_star_payment' in MAIN


def test_veo_service_uses_image_to_video_long_running_api():
    assert ':predictLongRunning' in VIDEO
    assert "'image':" in VIDEO
    assert "'inlineData'" in VIDEO
    assert "'personGeneration': 'allow_adult'" in VIDEO
    assert 'generateVideoResponse' in VIDEO
