from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')


def test_pollinations_config_exists():
    assert 'POLLINATIONS_ENABLED' in CONFIG
    assert 'POLLINATIONS_MODEL' in CONFIG
    assert 'POLLINATIONS_TIMEOUT_SECONDS' in CONFIG
    assert 'POLLINATIONS_WIDTH' in CONFIG
    assert 'POLLINATIONS_HEIGHT' in CONFIG
    # Free provider: must not require any API key in config.
    block = CONFIG[CONFIG.index('POLLINATIONS_ENABLED'):CONFIG.index('POLLINATIONS_HEIGHT')]
    assert 'API_KEY' not in block


def test_pollinations_provider_functions_exist():
    assert 'async def _pollinations_one_frame(' in PHOTO
    assert 'async def _run_pollinations_set(' in PHOTO
    assert 'image.pollinations.ai' in PHOTO
    assert "provider='pollinations'" in PHOTO
    assert 'estimated_cost_usd=0.0' in PHOTO


def test_pollinations_is_free_last_resort_fallback():
    block = PHOTO[PHOTO.index('async def generate_photo_set'):PHOTO.index('async def generate_photo(')]
    assert '_run_pollinations_set' in block
    assert 'PhotoGenerationError as exc' in block
    # Private scenes must never be routed to the free public provider.
    assert "resolved.scene not in {'personal', 'lingerie', 'private_fashion'}" in block
    # No infinite loop: do not fall back to pollinations when it already failed.
    assert "provider != 'pollinations'" in block


def test_hybrid_route_includes_pollinations_before_seedream():
    block = PHOTO[PHOTO.index('# HYBRID routing'):PHOTO.index('async def _run_routed_photo_set')]
    assert 'POLLINATIONS_ENABLED' in block
    assert block.index('POLLINATIONS_ENABLED') < block.index('Ultimate fallback to Seedream')


def test_pollinations_frame_guard_validates_image_bytes():
    block = PHOTO[PHOTO.index('async def _pollinations_one_frame'):PHOTO.index('async def _run_pollinations_set')]
    assert "data.startswith(b'\\xff\\xd8')" in block
    assert "data.startswith(b'\\x89PNG')" in block


def test_pollinations_prompt_is_flattened_single_line():
    # Pollinations returns 404 for prompts containing newline characters, so
    # the structured multi-line prompt must be flattened before quoting.
    block = PHOTO[PHOTO.index('async def _pollinations_one_frame'):PHOTO.index('async def _run_pollinations_set')]
    flatten_idx = block.index("prompt.split('\\n')")
    assert block.index('quote(prompt)') > flatten_idx
