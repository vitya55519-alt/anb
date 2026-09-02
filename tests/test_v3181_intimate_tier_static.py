"""Static tests for v3.18.1: intimate photo tier (nude/tease scenes at level 6)
and sensual video animation prompts.

These tests verify that:
- New adult scenes ('nude', 'tease') are defined in all photo-service registries
- They are level-gated at 6, adult-confirmed, and treated as custom (paid)
- The Seedream safety checker is disabled for adult scenes only
- Adult photos never enter the community pool
- parse_photo_request maps explicit text to nude/tease instead of blocking
- The sensual animation prompt is used for adult/intimate video scenes
"""
import importlib
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'services' / 'photo_service.py'
PSRC = SRC.read_text(encoding='utf-8')

CLOUD_VIDEO_SRC = (ROOT / 'services' / 'cloud_video_service.py').read_text(encoding='utf-8')
MAIN_SRC = (ROOT / 'main.py').read_text(encoding='utf-8')


# --- Module-level fixtures ---------------------------------------------------

@pytest.fixture(scope='module', autouse=True)
def _env():
    import os
    os.environ.setdefault('TELEGRAM_TOKEN', 'test-token')
    os.environ.setdefault('OPENROUTER_API_KEY', 'test-key')
    yield


@pytest.fixture(scope='module')
def photo_mod():
    # Force reimport so module-level constants are fresh.
    for mod_name in list(sys.modules):
        if mod_name.startswith('services.photo_service') or mod_name.startswith('services.photo'):
            del sys.modules[mod_name]
    return importlib.import_module('services.photo_service')


# --- Scene registry tests ----------------------------------------------------

class TestAdultSceneRegistries:
    def test_adult_scenes_constant(self, photo_mod):
        assert 'nude' in photo_mod.ADULT_SCENES
        assert 'tease' in photo_mod.ADULT_SCENES

    def test_scenes_have_nude_and_tease(self, photo_mod):
        assert 'nude' in photo_mod.SCENES
        assert 'tease' in photo_mod.SCENES
        assert 'nude' in photo_mod.SCENES['nude']
        assert 'teas' in photo_mod.SCENES['tease'].lower() or 'behind' in photo_mod.SCENES['tease']

    def test_scene_levels_gated_at_6(self, photo_mod):
        assert photo_mod.SCENE_LEVELS['nude'] == 6
        assert photo_mod.SCENE_LEVELS['tease'] == 6

    def test_scene_group_is_adult(self, photo_mod):
        assert photo_mod.SCENE_GROUP['nude'] == 'adult'
        assert photo_mod.SCENE_GROUP['tease'] == 'adult'

    def test_auto_captions_exist(self, photo_mod):
        assert 'nude' in photo_mod.AUTO_CAPTIONS
        assert 'tease' in photo_mod.AUTO_CAPTIONS
        assert len(photo_mod.AUTO_CAPTIONS['nude']) >= 2
        assert len(photo_mod.AUTO_CAPTIONS['tease']) >= 2

    def test_shot_variants_exist(self, photo_mod):
        assert 'nude' in photo_mod.SHOT_VARIANTS
        assert 'tease' in photo_mod.SHOT_VARIANTS
        assert len(photo_mod.SHOT_VARIANTS['nude']) == 3
        assert len(photo_mod.SHOT_VARIANTS['tease']) == 3

    def test_private_scene_tiers_exist(self, photo_mod):
        assert 'nude' in photo_mod.PRIVATE_SCENE_TIERS
        assert 'tease' in photo_mod.PRIVATE_SCENE_TIERS
        for scene in ('nude', 'tease'):
            tiers = photo_mod.PRIVATE_SCENE_TIERS[scene]
            assert 'standard' in tiers
            assert 'suggestive' in tiers
            assert 'revealing' in tiers

    def test_adult_safety_string(self, photo_mod):
        assert hasattr(photo_mod, 'ADULT_SAFETY')
        assert 'nudity is allowed' in photo_mod.ADULT_SAFETY.lower()


# --- Access-control tests ----------------------------------------------------

class TestAdultSceneAccessControl:
    def test_is_custom_request_includes_adult(self, photo_mod):
        req = photo_mod.PhotoRequest(scene='nude')
        assert photo_mod.is_custom_request(req)
        req = photo_mod.PhotoRequest(scene='tease')
        assert photo_mod.is_custom_request(req)

    def test_requires_adult_confirmation_for_adult(self, photo_mod):
        req = photo_mod.PhotoRequest(scene='nude')
        assert photo_mod.requires_adult_confirmation(req)
        req = photo_mod.PhotoRequest(scene='tease')
        assert photo_mod.requires_adult_confirmation(req)

    def test_scene_allowed_only_at_committed(self, photo_mod):
        # level 6 = STAGE_INDEX 5 (committed) + 1
        assert photo_mod.scene_allowed_for_stage('nude', 'committed')
        assert photo_mod.scene_allowed_for_stage('tease', 'committed')
        assert not photo_mod.scene_allowed_for_stage('nude', 'deeply_connected')
        assert not photo_mod.scene_allowed_for_stage('tease', 'close')


# --- parse_photo_request tests ---------------------------------------------

class TestParsePhotoRequestAdult:
    def test_explicit_text_maps_to_nude(self, photo_mod):
        req = photo_mod.parse_photo_request('сфоткай себя голую')
        assert req is not None
        assert req.scene == 'nude'

    def test_explicit_text_with_rear_maps_to_tease(self, photo_mod):
        req = photo_mod.parse_photo_request('сфоткай попу, голая')
        assert req is not None
        assert req.scene == 'tease'

    def test_explicit_english_maps_to_nude(self, photo_mod):
        req = photo_mod.parse_photo_request('send me a nude photo')
        assert req is not None
        assert req.scene == 'nude'


# --- _build_prompt adult branch tests ---------------------------------------

class TestBuildPromptAdult:
    def test_adult_prompt_has_nude_wardrobe(self, photo_mod):
        req = photo_mod.PhotoRequest(scene='nude', hairstyle='long loose', makeup='natural', accessory='none',
                                     time_of_day='evening', hair_color='brunette',
                                     underwear_color='black', underwear_style='lace bra and panties',
                                     mood='confident, intimate')
        prompt = photo_mod._build_prompt(req, 0, seedream=True, relationship_level=6, character_id='anna_01')
        # V3.22.0: fine-art/boudoir wording instead of explicit body-part phrasing
        # (fal's API-level moderation rejects the old wording with 400/422).
        assert 'fine-art nude composition' in prompt
        assert 'ADULT_SAFETY' not in prompt  # constant name shouldn't appear
        assert 'nudity is allowed' in prompt.lower()

    def test_adult_prompt_has_tease_wardrobe(self, photo_mod):
        req = photo_mod.PhotoRequest(scene='tease', hairstyle='long loose', makeup='natural', accessory='none',
                                     time_of_day='evening', hair_color='brunette',
                                     underwear_color='black', underwear_style='lace bra and panties',
                                     mood='playful, teasing')
        prompt = photo_mod._build_prompt(req, 0, seedream=True, relationship_level=6, character_id='anna_01')
        assert 'fine-art nude composition' in prompt

    def test_non_adult_prompt_has_no_nudity(self, photo_mod):
        req = photo_mod.PhotoRequest(scene='selfie', hairstyle='long loose', makeup='natural', accessory='none',
                                     time_of_day='daytime', hair_color='brunette',
                                     underwear_color='white', underwear_style='cotton bra and panties',
                                     mood='casual')
        prompt = photo_mod._build_prompt(req, 0, seedream=True, relationship_level=1, character_id='anna_01')
        assert 'fine-art nude composition' not in prompt
        assert 'No nudity' in prompt or 'non-explicit' in prompt


# --- _seedream_request allow_adult tests ------------------------------------

class TestSeedreamRequestAdult:
    def test_allow_adult_parameter_exists(self):
        # Static check: the function signature has allow_adult
        assert 'allow_adult: bool = False' in PSRC

    def test_enable_safety_checker_uses_allow_adult(self):
        assert "'enable_safety_checker': not allow_adult" in PSRC

    def test_run_seedream_set_passes_allow_adult(self):
        assert 'allow_adult = request.scene in SEEDREAM_ADULT_SCENES' in PSRC
        assert 'allow_adult=allow_adult' in PSRC


# --- Provider routing tests -------------------------------------------------

class TestProviderRoutingAdult:
    def test_choose_provider_routes_adult_to_seedream(self, photo_mod):
        req = photo_mod.PhotoRequest(scene='nude')
        assert photo_mod.choose_photo_provider(0, req) == 'seedream45'
        req = photo_mod.PhotoRequest(scene='tease')
        assert photo_mod.choose_photo_provider(0, req) == 'seedream45'

    def test_private_library_scenes_includes_adult(self, photo_mod):
        assert 'nude' in photo_mod._PRIVATE_LIBRARY_SCENES
        assert 'tease' in photo_mod._PRIVATE_LIBRARY_SCENES


# --- Community pool protection test ------------------------------------------

class TestCommunityPoolProtection:
    def test_community_shared_excludes_adult(self):
        # The community_shared flag must exclude ADULT_SCENES
        assert 'not in ADULT_SCENES' in PSRC

    def test_safe_retry_includes_adult(self):
        # The safe retry should map nude/tease to safe lingerie
        idx = PSRC.index("'nude', 'tease'")
        assert idx > 0


# --- Video animation prompt tests -------------------------------------------

class TestSensualAnimationPrompt:
    def test_sensual_prompt_exists_in_cloud_video(self):
        assert 'SENSUAL_ANIMATION_PROMPT' in CLOUD_VIDEO_SRC
        assert 'sensual' in CLOUD_VIDEO_SRC.lower()

    def test_sensual_prompt_imported_in_main(self):
        assert 'SENSUAL_ANIMATION_PROMPT' in MAIN_SRC

    def test_main_uses_scene_aware_prompt(self):
        assert "delivery.get('scene')" in MAIN_SRC
        assert 'anim_prompt' in MAIN_SRC
        assert 'prompt=anim_prompt' in MAIN_SRC

    def test_main_photo_labels_have_adult(self):
        assert "'nude'" in MAIN_SRC
        assert "'tease'" in MAIN_SRC
        assert 'Обнажённая' in MAIN_SRC
        assert 'Дразнит' in MAIN_SRC

    def test_main_photo_menu_order_has_adult(self):
        # V3.30.0: the nude/tease BUTTONS left the menu (image providers
        # moderate them into HTTP 422 almost every time); labels and the
        # backend registries stay for old library photos.
        idx = MAIN_SRC.index('PHOTO_MENU_ORDER')
        chunk = MAIN_SRC[idx:idx + 400]
        assert "'nude'" not in chunk
        assert "'tease'" not in chunk
        assert "'nude'" in MAIN_SRC and "'tease'" in MAIN_SRC
