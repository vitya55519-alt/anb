"""Static regression tests for v3.16.9 + v3.17.4: community photo pool.

v3.16.9: every AI-generated frame enters the shared pool (community_shared),
and the pool is a safety net when AI providers fail.
v3.17.4: free/story sets are served from the pool FIRST when it holds a full
unseen set; paid credit sets always generate fresh AI photos.

Delivery priority (free/story): community pool -> AI generation -> pool/library
fallback. Paid: AI generation only.
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

def test_pool_first_policy_for_free_and_story():
    # v3.17.4: free/story sets consult the community pool before AI generation.
    deliver_fn = PHOTO[PHOTO.index('async def deliver_photo('):PHOTO.index('async def _send_frame(')]
    assert 'query_community_photos(' in deliver_fn
    assert "delivery_type in {'free', 'story'}" in deliver_fn
    assert 'COMMUNITY_POOL_FIRST' in deliver_fn
    # Only a full unseen set is served proactively — partial pools fall through to AI.
    assert 'len(community_photos) >= PHOTO_SET_SIZE' in deliver_fn
    # Paid credit sets never take the pool path (the condition above is
    # limited to free/story), so paying users always get fresh AI photos.


def test_community_pool_is_also_failure_fallback():
    # Community pool appears in the error handler (except PhotoGenerationError)
    # as the recovery path when AI generation fails.
    deliver_start = PHOTO.index('async def deliver_photo(')
    except_in_deliver = PHOTO.index('except PhotoGenerationError as exc:', deliver_start)
    except_block = PHOTO[except_in_deliver:except_in_deliver + 3000]
    assert 'community_pool_fallback' in except_block
    assert 'query_community_photos' in except_block


def test_fallback_order_community_before_library():
    # In the error handler, community pool is checked before the curated library.
    deliver_start = PHOTO.index('async def deliver_photo(')
    except_in_deliver = PHOTO.index('except PhotoGenerationError as exc:', deliver_start)
    except_block = PHOTO[except_in_deliver:except_in_deliver + 3000]
    community_idx = except_block.index('community_pool_fallback')
    library_idx = except_block.index('_deliver_library_failure_fallback')
    assert community_idx < library_idx


def test_ai_generated_photos_are_community_shared():
    # _send_frame marks frames community_shared so the photo enters the pool
    # (high-level at-home lingerie sets are the explicit exception, v3.17.5)
    assert 'community_shared=not home_lingerie_mode,' in PHOTO


def test_community_pool_skips_private_scenes():
    # Private scenes never use community pool even as fallback.
    deliver_start = PHOTO.index('async def deliver_photo(')
    except_in_deliver = PHOTO.index('except PhotoGenerationError as exc:', deliver_start)
    except_block = PHOTO[except_in_deliver:except_in_deliver + 3000]
    assert '_PRIVATE_LIBRARY_SCENES' in except_block


def test_insert_delivery_row_supports_community_params():
    # The insert helper accepts community_shared and source_delivery_id.
    assert 'community_shared: bool = False' in PHOTO
    assert 'source_delivery_id: int | None = None' in PHOTO
    assert 'community_shared=community_shared,' in PHOTO
    assert 'source_delivery_id=source_delivery_id,' in PHOTO


# ── Library fallback respects character_id ────────────────────────────────

def test_library_failure_fallback_uses_character_id_parameter():
    # _deliver_library_failure_fallback must pass the character_id parameter
    # to choose_fallback_pack, NOT the hardcoded CHARACTER_ID constant.
    fallback_fn = PHOTO[PHOTO.index('async def _deliver_library_failure_fallback('):PHOTO.index('return sent_messages', PHOTO.index('async def _deliver_library_failure_fallback('))]
    assert 'choose_fallback_pack(telegram_id, character_id, level, scene_order)' in fallback_fn
    # Must NOT use the hardcoded CHARACTER_ID constant.
    assert 'choose_fallback_pack(telegram_id, CHARACTER_ID' not in fallback_fn


def test_library_partial_topup_uses_character_id_parameter():
    # _deliver_library_partial_topup must accept and use character_id.
    topup_fn = PHOTO[PHOTO.index('async def _deliver_library_partial_topup('):PHOTO.index('return sent_messages', PHOTO.index('async def _deliver_library_partial_topup('))]
    assert 'character_id: str = CHARACTER_ID' in topup_fn
    assert 'choose_fallback_pack(telegram_id, character_id, level, scene_order)' in topup_fn
