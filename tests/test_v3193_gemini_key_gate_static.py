"""Static regression tests for v3.19.3: broken GEMINI_API_KEY isolation.

A GEMINI_API_KEY pasted with non-ASCII characters (the production incident:
`gemini_image/invalid_api_key_non_ascii`) used to poison every Gemini call —
chat fallback and Nano Banana photos — while the engine still reported READY.
Now such a key is treated as absent: engines skip it, the fallback chains
continue, and the owner gets a loud startup warning.
The photo fallback chains are additionally hardened so one broken fallback
engine can no longer stop the chain. (Veo video was removed entirely in
v3.19.4.)
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
LLM = (ROOT / 'services' / 'llm_provider_service.py').read_text(encoding='utf-8')


def test_key_validity_gate_defined_in_config():
    assert 'GEMINI_API_KEY_VALID = bool(GEMINI_API_KEY) and GEMINI_API_KEY.isascii()' in CONFIG
    assert 'not any(ch.isspace() for ch in GEMINI_API_KEY)' in CONFIG
    # Loud startup warning for the owner (visible in Railway logs).
    assert 'CONFIG WARNING: GEMINI_API_KEY contains non-ASCII or whitespace characters' in CONFIG


def test_gemini_engines_gated_on_valid_key():
    # V3.19.4: Gemini/Veo video is gone from config entirely.
    assert 'GEMINI_VIDEO_ENABLED' not in CONFIG
    assert 'and bool(GEMINI_API_KEY_VALID)\n)' in CONFIG  # GEMINI_IMAGE_ENABLED
    # Chat fallback client is not built for a broken key.
    assert 'GEMINI_API_KEY_VALID' in LLM
    assert 'if GEMINI_API_KEY_VALID else None' in LLM
    assert "'gemini_key_present': bool(GEMINI_API_KEY_VALID)" in LLM


def test_seedream_fallback_chain_is_hardened():
    dispatch = PHOTO[PHOTO.index('async def _run_routed_photo_set'):PHOTO.index('async def generate_photo_set')]
    seedream_block = dispatch[dispatch.index("if provider == 'seedream45':"):dispatch.index("if provider == 'gemini_image':")]
    # Every fallback engine is wrapped in its own try/except and the chain
    # only raises after ALL engines failed.
    assert 'last_error = exc' in seedream_block
    assert 'raise last_error' in seedream_block
    assert seedream_block.count('PHOTO ROUTE FALLBACK FAILED') >= 3
    assert 'from=seedream45 to=gemini_image' in seedream_block
    assert 'from=seedream45 to=openai' in seedream_block
    assert 'from=seedream45 to=pollinations' in seedream_block


def test_gemini_route_falls_through_openai_to_seedream():
    dispatch = PHOTO[PHOTO.index('async def _run_routed_photo_set'):PHOTO.index('async def generate_photo_set')]
    gemini_block = dispatch[dispatch.index("if provider == 'gemini_image':"):dispatch.index("if provider == 'pollinations':")]
    assert 'from=gemini_image to=openai' in gemini_block
    assert 'from=gemini_image to=seedream45' in gemini_block
    # A failing OpenAI fallback must still hand over to Seedream.
    assert 'engine=openai reason=%s' in gemini_block


def test_video_alert_lists_missing_engine_keys():
    main_src = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert 'нет REPLICATE_API_TOKEN' in main_src
    assert 'Gemini/Veo' not in main_src
