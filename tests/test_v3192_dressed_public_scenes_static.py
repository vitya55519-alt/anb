"""Static + runtime regression tests for v3.19.2: fully-clothed public scenes.

Owner policy change: at relationship levels 5-6 the character must stay fully
clothed in every public venue scene (restaurant, car, gym, cinema, fashion,
embankment, evening, bar, karaoke, rooftop, club). Lingerie content lives only
in the at-home selfie/home/mirror sets (existing HOME_LINGERIE_SCENES) and the
dedicated private scenes (personal/lingerie/private_fashion). The retired
'peek'/'dressing' scenes and the level-5 "daring cut" escalation were the main
source of visible-lingerie public photos and of Seedream HTTP 422 rejections.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')

PUBLIC_SCENES = (
    'restaurant', 'car', 'gym', 'cinema', 'fashion', 'embankment',
    'evening', 'bar', 'karaoke', 'rooftop', 'club',
)


def test_public_scenes_still_routable_and_clothed():
    from services.photo_service import SCENES, SCENE_LEVELS
    for scene in PUBLIC_SCENES:
        assert scene in SCENES and scene in SCENE_LEVELS
    # No "visible lingerie" wording survives in the level 5-6 visual rules.
    rules = PHOTO[PHOTO.index('LEVEL_VISUAL_RULES = {'):PHOTO.index('LEVEL_UNDERLAY_RULES = {')]
    assert 'visible lace details' not in rules
    assert 'no visible lingerie' in rules


def test_runtime_public_scene_level6_has_no_lingerie_naming():
    from services.photo_service import PhotoRequest, _build_prompt
    for scene in PUBLIC_SCENES:
        request = PhotoRequest(scene=scene, clothing='an elegant fitted dress',
                               underwear_color='black', underwear_style='lace')
        prompt = _build_prompt(request, 0, seedream=True, relationship_level=6, character_id='anna_01')
        # Underwear is never named in public scenes, even at max level.
        assert 'The lingerie she wears beneath her outfit is' not in prompt
        assert 'daring, revealing cut' not in prompt
        assert 'HOME LINGERIE LOOK:' not in prompt
        # The underlay rule actively hides the lingerie.
        assert 'completely hidden underneath' in prompt or 'completely invisible' in prompt


def test_private_scenes_still_get_lingerie_naming():
    from services.photo_service import PhotoRequest, _build_prompt
    request = PhotoRequest(scene='lingerie', clothing='an elegant black lingerie set',
                           underwear_color='black', underwear_style='lace')
    prompt = _build_prompt(request, 0, seedream=True, relationship_level=5, character_id='anna_01')
    assert 'The lingerie she wears beneath her outfit is black (lace)' in prompt


def test_home_lingerie_selfies_still_work_at_level_5plus():
    # The owner-approved intimate route: at-home selfie/home/mirror sets.
    from services.photo_service import PhotoRequest, _build_prompt
    for scene in ('selfie', 'home', 'mirror'):
        request = PhotoRequest(scene=scene, clothing='casual home outfit', underwear_color='deep red')
        prompt = _build_prompt(request, 0, seedream=True, relationship_level=6, character_id='anna_01')
        assert 'HOME LINGERIE LOOK:' in prompt


def test_peek_dressing_not_routable():
    from services.photo_service import scene_allowed_for_stage
    for stage in ('stranger', 'acquaintance', 'close', 'intimate', 'deeply_connected', 'committed'):
        assert not scene_allowed_for_stage('peek', stage)
        assert not scene_allowed_for_stage('dressing', stage)


def test_seedream_failure_falls_back_to_other_engines():
    # A Seedream HTTP 422 must not kill the photo: the routed set falls back
    # Gemini -> OpenAI -> Pollinations before surfacing the error.
    dispatch = PHOTO[PHOTO.index('async def _run_routed_photo_set'):PHOTO.index('async def generate_photo_set')]
    seedream_block = dispatch[dispatch.index("if provider == 'seedream45':"):dispatch.index("if provider == 'gemini_image':")]
    assert 'except PhotoGenerationError as exc:' in seedream_block
    assert 'from=seedream45 to=gemini_image' in seedream_block
    assert 'from=seedream45 to=openai' in seedream_block
    assert 'from=seedream45 to=pollinations' in seedream_block
