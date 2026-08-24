"""Static + runtime regression tests for v3.17.5: at-home lingerie sets at
relationship levels 5-6.

At level 5+ the at-home scenes (selfie, home, mirror) are shot in only her
lingerie (Seedream route); other ordinary scenes get a more revealing wardrobe
cut. These generations never enter the community pool and the pool never
serves low-level clothed photos into a high-level home set. Bust stays the
canonical Russian size 5 (E cup).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')


def _build_fn():
    return PHOTO[PHOTO.index('def _build_prompt('):PHOTO.index('def _extract_openai_many(')]


def test_home_lingerie_scenes_constant():
    assert "HOME_LINGERIE_SCENES = {'selfie', 'home', 'mirror'}" in PHOTO


def test_build_prompt_home_lingerie_override():
    fn = _build_fn()
    # Only on the Seedream route at level 5+, only for the at-home scenes.
    assert 'home_lingerie = seedream and level_key >= 5 and request.scene in HOME_LINGERIE_SCENES' in fn
    # The lingerie set becomes the entire outfit.
    assert "worn as the entire outfit in the privacy of her home, no outerwear at all" in fn
    assert 'Her lingerie is the outfit itself in this private at-home moment' in fn
    assert 'HOME LINGERIE LOOK:' in fn


def test_revealing_cut_for_other_scenes_at_level_5plus():
    fn = _build_fn()
    assert "styled with a daring, revealing cut that shows more skin while staying a real outfit" in fn
    # Private-tier scenes keep their own framing; the OpenAI fallback route
    # stays general-audience (seedream guard).
    assert 'elif seedream and level_key >= 5 and not scene_tiers:' in fn


def test_pool_protection_for_home_lingerie_sets():
    deliver_fn = PHOTO[PHOTO.index('async def deliver_photo('):PHOTO.index('async def _send_frame(') if 'async def _send_frame(' in PHOTO else len(PHOTO)]
    # home_lingerie_mode gates both directions of the community pool.
    assert 'home_lingerie_mode = (' in PHOTO
    assert 'request.scene in HOME_LINGERIE_SCENES' in PHOTO
    assert 'and not home_lingerie_mode' in PHOTO
    assert 'community_shared=not home_lingerie_mode,' in PHOTO


def test_bust_stays_size_5_e_cup():
    assert 'Russian size 5, E cup' in PHOTO
    assert 'Russian size 4, D cup' not in PHOTO


def test_runtime_home_scene_level6_is_lingerie_only():
    from services.photo_service import PhotoRequest, _build_prompt
    request = PhotoRequest(scene='home', clothing='casual home outfit', underwear_color='black', underwear_style='lace')
    prompt = _build_prompt(request, 0, seedream=True, relationship_level=6, character_id='anna_01')
    assert 'HOME LINGERIE LOOK:' in prompt
    assert 'only her black lingerie (lace) set' in prompt
    assert 'no outerwear at all' in prompt
    assert 'Russian size 5, E cup' in prompt


def test_runtime_home_scene_level4_stays_clothed():
    from services.photo_service import PhotoRequest, _build_prompt
    request = PhotoRequest(scene='home', clothing='casual home outfit', underwear_color='black', underwear_style='lace')
    prompt = _build_prompt(request, 0, seedream=True, relationship_level=4, character_id='anna_01')
    assert 'HOME LINGERIE LOOK:' not in prompt
    assert 'no outerwear at all' not in prompt


def test_runtime_other_scene_level5_gets_revealing_cut():
    from services.photo_service import PhotoRequest, _build_prompt
    request = PhotoRequest(scene='park', clothing='summer dress')
    prompt = _build_prompt(request, 0, seedream=True, relationship_level=5, character_id='anna_01')
    assert 'daring, revealing cut' in prompt
    # OpenAI fallback route stays general-audience.
    prompt_openai = _build_prompt(request, 0, seedream=False, relationship_level=5, character_id='anna_01')
    assert 'daring, revealing cut' not in prompt_openai
    assert 'HOME LINGERIE LOOK:' not in prompt_openai
