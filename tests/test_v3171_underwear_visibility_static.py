"""Static regression tests for v3.17.1: visible-underwear system.

One random visibility detail per set, level-tiered framing for private scenes
(standard/suggestive/revealing), new 'peek' and 'dressing' scenes at level 4,
and Anna's canonical bust bumped to Russian size 5 (E cup)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')


def test_visibility_details_pool_removed():
    # The visibility-detail injection made the model render lingerie ON TOP of
    # the outfit (v3.17.2 evidence) — it was removed entirely.
    assert 'UNDERWEAR_VISIBILITY_DETAILS' not in PHOTO
    assert 'underlay_rule += ' not in PHOTO
    # Instead the negatives explicitly forbid lingerie as outerwear.
    assert 'underwear worn over the outfit' in PHOTO
    assert 'lingerie as outerwear' in PHOTO


def test_private_scene_tiers_level_mapping():
    assert 'PRIVATE_SCENE_TIERS = {' in PHOTO
    for scene in ('lingerie', 'personal', 'private_fashion'):
        assert f"'{scene}': {{" in PHOTO[PHOTO.index('PRIVATE_SCENE_TIERS = {'):PHOTO.index('# Underwear color variety')]
    start = PHOTO.index('tier_framing = \'\'')
    block = PHOTO[start:PHOTO.index('season = request.season', start)]
    assert "'revealing' if level_key >= 6" in block
    assert "'suggestive' if level_key >= 5" in block
    assert 'PRIVATE SCENE FRAMING:' in block
    # The framing line is part of the final prompt.
    prompt = PHOTO[PHOTO.index('def _build_prompt('):]
    assert "f'{tier_framing}'" in prompt


def test_peek_and_dressing_scenes_retired_from_generation():
    # V3.19.2: 'peek'/'dressing' (visible underwear in everyday scenes) are
    # no longer routable — public venues must stay fully clothed. The scene
    # definitions stay for old library photos, but without a SCENE_LEVELS
    # entry scene_allowed_for_stage() rejects them (default level 99).
    from services.photo_service import SCENES, SCENE_LEVELS, SCENE_GROUP, AUTO_CAPTIONS
    for scene in ('peek', 'dressing'):
        assert scene in SCENES
        assert scene not in SCENE_LEVELS
        assert scene in SCENE_GROUP
        assert scene in AUTO_CAPTIONS and AUTO_CAPTIONS[scene]


def test_bust_bumped_to_size_five():
    assert 'Russian size 5, E cup' in PHOTO
    assert 'Russian size 4, D cup' not in PHOTO
    anna_card = (ROOT / 'data' / 'characters' / 'anna.json').read_text(encoding='utf-8')
    assert 'Russian size 5, E cup' in anna_card


def test_hair_color_line_condition_is_parenthesized():
    # The 'if request.hair_color else ""' condition must apply only to the hair
    # line — without parentheses Python applies it to the whole prompt string.
    assert "+ (f'HAIR COLOR THIS MONTH:" in PHOTO
    assert "if request.hair_color else '')" in PHOTO


def test_build_prompt_returns_full_prompt_without_hair_color():
    import os
    os.environ.setdefault('TELEGRAM_TOKEN', '123456:TEST_TOKEN')
    os.environ.setdefault('OPENEROUTER_API_KEY', 'test-key')
    from services.photo_service import PhotoRequest, _build_prompt
    prompt = _build_prompt(PhotoRequest(scene='selfie', clothing='casual'), 0, relationship_level=1)
    assert 'SCENE:' in prompt and 'BUST CONSISTENCY' in prompt
