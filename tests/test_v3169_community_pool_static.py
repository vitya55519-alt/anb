"""Static regression tests for v3.16.9: community photo pool.

AI-generated photos are shared between users requesting the same character+scene.
New photos are generated only when the community pool has nothing unseen for the
requesting user. This saves API cost and fixes the Emily repetition bug where
the curated library served the same photo over and over.

Delivery priority: community pool -> curated library -> AI generation -> fallback.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'photo_models.py').read_text(encoding='utf-8')
DB = (ROOT / 'services' / 'db.py').read_text(encoding='utf-8')


# ── Model and migration ──────────────────────────────────────────────────

def test_community_pool_model_columns():
    assert 'community_shared:Mapped[bool]' in MODELS
    assert 'source_delivery_id:Mapped[int|None]' in MODELS
    assert 'Boolean' in MODELS


def test_community_pool_migration():
    assert "'community_shared': 'BOOLEAN DEFAULT FALSE'" in DB
    assert "'source_delivery_id': 'INTEGER'" in DB


def test_community_pool_config():
    assert 'COMMUNITY_POOL_ENABLED' in CONFIG
    assert 'COMMUNITY_POOL_ENABLED", "true"' in CONFIG


# ── Query function ────────────────────────────────────────────────────────

def test_query_community_photos_function():
    assert 'def query_community_photos(' in PHOTO
    # Must filter by community_shared, character_id, scene, and unseen.
    assert 'PhotoDelivery.community_shared.is_(True)' in PHOTO
    assert 'PhotoDelivery.character_id == character_id' in PHOTO
    assert 'PhotoDelivery.scene == scene' in PHOTO
    assert 'PhotoDelivery.telegram_file_id.isnot(None)' in PHOTO
    # Excludes photos the user already received.
    assert 'source_delivery_id' in PHOTO
    # Random order for fair distribution.
    assert 'func.random()' in PHOTO


# ── Delivery routing ──────────────────────────────────────────────────────

def test_community_pool_checked_before_curated_library():
    # The community pool block appears BEFORE the curated library block.
    community_idx = PHOTO.index('Community pool first')
    library_idx = PHOTO.index('Cost-first routing for beta')
    assert community_idx < library_idx


def test_community_pool_delivery_uses_source_delivery_id():
    # Community re-deliveries link back to the original AI generation.
    assert "source_delivery_id=cp['id']" in PHOTO
    assert "provider='community_pool'" in PHOTO


def test_ai_generated_photos_are_community_shared():
    # _send_frame sets community_shared=True so the photo enters the pool.
    assert 'community_shared=True,' in PHOTO


def test_community_pool_skips_private_scenes():
    # Private scenes (personal/lingerie) never use the community pool.
    community_block = PHOTO[PHOTO.index('Community pool first'):PHOTO.index('Cost-first routing for beta')]
    assert '_PRIVATE_LIBRARY_SCENES' in community_block


def test_community_pool_respects_feature_flag():
    # The community pool is gated by COMMUNITY_POOL_ENABLED.
    community_block = PHOTO[PHOTO.index('Community pool first'):PHOTO.index('Cost-first routing for beta')]
    assert 'COMMUNITY_POOL_ENABLED' in community_block


def test_insert_delivery_row_supports_community_params():
    # The insert helper accepts community_shared and source_delivery_id.
    assert 'community_shared: bool = False' in PHOTO
    assert 'source_delivery_id: int | None = None' in PHOTO
    assert 'community_shared=community_shared,' in PHOTO
    assert 'source_delivery_id=source_delivery_id,' in PHOTO
