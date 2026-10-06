"""V3.51.3 — sensual private-scene expressions + photo-pool reuse.

Two behaviours, both wanted by the owner for the «наедине» boudoir shots:

1. Sensual mimicry (tongue grazing the lip, bitten lip, smouldering bedroom
   eyes, seductive pout) is now the DEFAULT per-frame expression rotation on
   EVERY scene, public included — the owner asked for sensual emotion across all
   photos, not just the private ones. An explicit chat-mood expression_key still
   overrides the rotation.

2. Pool reuse: once a character's shared cache (user_id=0 rows) has stockpiled
   at least PRIVATE_POOL_MIN ready shots for the SAME scene, a random one is
   sent instead of paying the provider again. Generation still happens to build
   the stockpile; the user is still charged — only the redundant render is
   skipped.

Static pins (no imports -> the suite runs without a DB/LLM key)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPR = (ROOT / 'services' / 'photo_expression_service.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
PRIVATE = (ROOT / 'services' / 'private_photo_service.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def test_sensual_expression_keys_defined():
    # the four desirous faces the owner asked for (tongue up / bitten lip / smolder)
    for key in ("'desire'", "'biting_lip'", "'bedroom_eyes'", "'blow_kiss'"):
        assert key in EXPR
    # tongue note actually describes the grazing motion, not just a label
    assert 'tongue' in EXPR[EXPR.index("'desire'"):EXPR.index("'biting_lip'")]
    # the private rotation walks SENSUAL_KEYS, not the public VARIETY_KEYS
    assert 'SENSUAL_KEYS: tuple[str, ...]' in EXPR
    assert 'def shuffled_sensual_variety_keys()' in EXPR
    assert 'random.shuffle(keys)' in EXPR[EXPR.index('def shuffled_sensual_variety_keys'):]


def test_sensual_rotation_applies_to_all_scenes():
    # V3.51.4: the sensual pool is now the default rotation on EVERY scene — no
    # per-scene branch back to the tasteful rotation is left in the resolver.
    assert 'expression_rotation = tuple(request.expression_rotation) or (' in PHOTO
    # V3.55.6: the tender-persona branch is the ONLY way the soft pool reaches
    # the resolver — the sensual pool stays the default for every scene.
    assert '() if request.expression_key else (' in PHOTO
    assert 'shuffled_variety_keys() if _persona_style_is_tender(telegram_id, character_id)' in PHOTO
    assert 'else shuffled_sensual_variety_keys()' in PHOTO
    # the sensual-only helper is what the resolver imports and calls
    assert 'from services.photo_expression_service import shuffled_sensual_variety_keys' in PHOTO
    # an explicit chat-mood expression still short-circuits the rotation
    assert '() if request.expression_key else' in PHOTO
    # the widened sensual pool carries the tongue + pout notes
    assert "'licking_lips'" in EXPR and "'pouty_seductive'" in EXPR
    assert "'licking_lips'" in EXPR[EXPR.index('SENSUAL_KEYS'):EXPR.index('VARIETY_KEYS')]


def test_pool_get_stockpile_helper():
    # threshold + signature live in the private-photo service
    assert 'PRIVATE_POOL_MIN = 10' in PRIVATE
    assert 'def pool_get(character_id: str, category: str, type_id: str,' in PRIVATE
    # only the shared cache rows (user_id=0) are eligible, never another user's gallery
    body = PRIVATE[PRIVATE.index('def pool_get('):PRIVATE.index('def cache_save(')]
    assert 'PrivateGallery.user_id == 0' in body
    assert 'PrivateGallery.character_id == character_id' in body
    assert 'PrivateGallery.category == category' in body
    # a short pool returns None so the caller still generates
    assert 'return None' in body
    # a stocked pool returns a RANDOM ready shot (not always the newest)
    assert 'random.choice(shots)' in body


def test_media_hot_wires_pool_reuse():
    hot = MAIN[MAIN.index('async def _webapp_media_hot('):MAIN.index('async def _webapp_media_circle(')]
    # pool_get imported alongside the cache helpers
    assert 'pool_get' in hot[hot.index('from services.private_photo_service import'):hot.index('from services.character_dna_service')]
    # the reuse check runs AFTER the exact cache miss and BEFORE provider generation
    assert 'pooled = pool_get(character_id, cat_id, req.type_id)' in hot
    assert hot.index('cached = cache_get(prompt, character_id)') < hot.index('pooled = pool_get(')
    assert hot.index('pooled = pool_get(') < hot.index('image_bytes = await generate_private_photo_t2i(prompt)')
    # a pooled shot is saved into the user's gallery and still charged like any send
    pool_block = hot[hot.index('pooled = pool_get('):hot.index('# Generate: adult')]
    assert 'gallery_save(telegram_id, character_id, cat_id, req.type_id, pooled)' in pool_block
    assert 'spend_peaches(telegram_id, peach_cost)' in pool_block
    assert 'return pooled' in pool_block
