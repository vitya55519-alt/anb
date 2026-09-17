"""Static + behavioral regression tests for v3.43.8: character styling diversity.

Each built-in heroine now has her own hair-color palette, hairstyle set and
age-appropriate wardrobe in visual_identity.photo_style. Bodies, bust sizes
and reference protocols remain unchanged.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
CHARACTERS_DIR = ROOT / 'data' / 'characters'

BUILT_IN_HEROINES = [
    'anna', 'alena_01', 'maria_01', 'erika_01',
    'sonya_01', 'vika_01', 'alisa_01', 'mila_01',
]


# ── JSON metadata: every heroine has photo_style ──────────────────────────

def test_all_heroines_have_photo_style():
    for name in BUILT_IN_HEROINES:
        data = json.loads((CHARACTERS_DIR / f'{name}.json').read_text(encoding='utf-8'))
        style = data.get('visual_identity', {}).get('photo_style', {})
        assert style, f'{name}.json missing visual_identity.photo_style'
        assert 'hair_colors' in style and len(style['hair_colors']) >= 2
        assert 'hairstyles' in style and len(style['hairstyles']) >= 3
        assert 'wardrobe' in style and isinstance(style['wardrobe'], dict)


def test_photo_style_wardrobe_groups():
    expected_groups = {'day_casual', 'warm_outdoor', 'home', 'fashion', 'evening', 'gym'}
    for name in BUILT_IN_HEROINES:
        data = json.loads((CHARACTERS_DIR / f'{name}.json').read_text(encoding='utf-8'))
        wardrobe = data['visual_identity']['photo_style']['wardrobe']
        for group in expected_groups:
            assert group in wardrobe, f'{name} missing wardrobe group {group}'
            assert len(wardrobe[group]) >= 2, f'{name} has fewer than 2 outfits in {group}'


def test_photo_style_no_orange_in_colors():
    for name in BUILT_IN_HEROINES:
        data = json.loads((CHARACTERS_DIR / f'{name}.json').read_text(encoding='utf-8'))
        colors = data['visual_identity']['photo_style'].get('colors', [])
        for c in colors:
            assert 'orange' not in c.lower(), f'{name} has orange in palette: {c}'


def test_all_outfits_fully_clothed():
    # Every outfit must be clearly fully clothed — no sheer, transparent,
    # see-through, or exposed wording. Normal garments (jeans, dresses,
    # blazers, trousers) are inherently opaque.
    forbidden = ('sheer', 'see-through', 'transparent', 'nude mesh', 'naked')
    for name in BUILT_IN_HEROINES:
        data = json.loads((CHARACTERS_DIR / f'{name}.json').read_text(encoding='utf-8'))
        wardrobe = data['visual_identity']['photo_style']['wardrobe']
        for group, outfits in wardrobe.items():
            for outfit in outfits:
                low = outfit.lower()
                for word in forbidden:
                    assert word not in low, \
                        f'{name}/{group} outfit has forbidden sheer/exposed wording: {outfit[:80]}'


# ── Photo service: per-character styling helpers ──────────────────────────

def test_photo_style_helper_exists():
    assert 'def _photo_style(character_id: str) -> dict:' in PHOTO
    assert "resolve_character(character_id)" in PHOTO


def test_adult_only_lock_no_twenties():
    # The universal "in her twenties" assumption is gone.
    assert 'in her twenties' not in PHOTO
    assert 'fictional adult woman described above' in PHOTO


def test_wardrobe_pool_accepts_character_id():
    assert 'def _wardrobe_pool(scene: str, level: int, season: str, *, character_id' in PHOTO
    assert "_photo_style(character_id)" in PHOTO


def test_choose_progression_outfits_skips_color_for_character_wardrobe():
    assert 'has_char_wardrobe' in PHOTO


def test_resolve_request_uses_character_hairstyles():
    block = PHOTO[PHOTO.index('def _resolve_request'):PHOTO.index('def _shot_variant')]
    assert "style.get('hairstyles'" in block
    assert "style.get('hair_colors'" in block


def test_build_prompt_injects_character_age():
    assert "adult_lock = ADULT_ONLY_LOCK" in PHOTO
    assert "ADULT_ONLY_LOCK.replace(" in PHOTO
    assert "f'{adult_lock}\\n'" in PHOTO


def test_hair_color_prompt_line_updated():
    assert "+ (f'HAIR COLOR:" in PHOTO
    assert "HAIR COLOR THIS MONTH" not in PHOTO


# ── Body rules: unchanged ─────────────────────────────────────────────────

def test_body_specs_unchanged():
    assert 'BODY_SPECS = {' in PHOTO
    for cid in ('alena_01', 'maria_01', 'erika_01', 'sonya_01', 'vika_01', 'alisa_01', 'mila_01'):
        assert f"'{cid}'" in PHOTO[PHOTO.index('BODY_SPECS = {'):PHOTO.index('}\nDEFAULT_FEMALE')]
    assert 'Russian size 5, E cup' in PHOTO


def test_bust_consistency_rule_unchanged():
    assert 'BUST_CONSISTENCY_RULE' in PHOTO
    assert 'neither larger nor smaller' in PHOTO


def test_reference_protocol_unchanged():
    assert 'REFERENCE PROTOCOL' in PHOTO
    assert 'body measurements, bust size and figure' in PHOTO


def test_openai_retry_has_character_id():
    # V3.43.8: the OpenAI compatibility single-reference retry now forwards
    # character_id so the fallback uses the correct character's identity.
    block = PHOTO[PHOTO.index('OpenAI compatibility retry single-reference'):]
    block = block.split('\n\n', 3)[0]
    assert 'character_id=character_id' in block


# ── Behavioral: _build_prompt with character age ──────────────────────────

def test_build_prompt_injects_age_for_non_anna():
    import os
    os.environ.setdefault('TELEGRAM_TOKEN', '123456:TEST_TOKEN')
    os.environ.setdefault('OPENEROUTER_API_KEY', 'test-key')
    from services.photo_service import PhotoRequest, _build_prompt
    prompt = _build_prompt(
        PhotoRequest(scene='fashion', clothing='an elegant dress', hair_color='dark golden blonde'),
        0, seedream=True, relationship_level=3, character_id='erika_01',
    )
    assert 'HARD SUBJECT LOCK' in prompt
    assert '38 years old' in prompt
    assert 'in her twenties' not in prompt


def test_build_prompt_anna_keeps_original_lock():
    import os
    os.environ.setdefault('TELEGRAM_TOKEN', '123456:TEST_TOKEN')
    os.environ.setdefault('OPENEROUTER_API_KEY', 'test-key')
    from services.photo_service import PhotoRequest, _build_prompt
    prompt = _build_prompt(
        PhotoRequest(scene='fashion', clothing='an elegant dress'),
        0, seedream=True, relationship_level=3, character_id='anna_01',
    )
    assert 'HARD SUBJECT LOCK' in prompt
    # Anna's lock still says "adult woman" without an injected age because
    # her identity already specifies age 26.
    assert 'SCENE:' in prompt
