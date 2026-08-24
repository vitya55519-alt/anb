"""Static regression tests for v3.17.4: community pool first for free sets.

Free/story photo sets are served from the shared community pool when it holds
a full unseen set for the user; AI generation runs only as the fallback.
Paid credit sets always generate fresh AI photos."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')


def test_pool_first_config_flag():
    assert 'COMMUNITY_POOL_FIRST' in CONFIG
    assert 'COMMUNITY_POOL_FIRST", "true"' in CONFIG


def test_proactive_pool_block_runs_before_generation():
    deliver_fn = PHOTO[PHOTO.index('async def deliver_photo('):PHOTO.index('async def _send_frame(')]
    # Proactive pool serve returns before any AI call.
    assert "'photo_community_pool_served'" in deliver_fn
    assert 'return sent_messages' in deliver_fn
    assert "provider='community_pool'" in deliver_fn
    assert "source_delivery_id=cp['id']" in deliver_fn
    # Usage accounting stays consistent with the delivery type.
    assert '_bump_photo_usage(telegram_id, delivery_type, character_id=character_id)' in deliver_fn


def test_pool_first_respects_private_scenes():
    assert "'personal', 'lingerie', 'private_fashion', 'peek', 'dressing'" in PHOTO
    deliver_fn = PHOTO[PHOTO.index('async def deliver_photo('):PHOTO.index('async def _send_frame(')]
    assert 'request.scene not in _PRIVATE_LIBRARY_SCENES' in deliver_fn


def test_ai_frames_still_feed_the_pool():
    # Fresh generations keep entering the pool for other users.
    assert 'community_shared=True,' in PHOTO
