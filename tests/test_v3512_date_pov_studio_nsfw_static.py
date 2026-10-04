"""V3.51.2: two owner-requested changes to the photo pipeline.

1. Date reward photos are now a first-person POV — his hand holding hers in the
   foreground, her seen ahead at arm's length — so the shot reads like a real
   photo the user took on the date, not a portrait of her alone. The POV framing
   rides ``PhotoRequest.angle`` (which ``_shot_variant`` honours verbatim) and is
   wired into BOTH the bot reward path and the Mini App date action, so it never
   touches the shared scene menu used by ordinary photos.
2. The «Картинки» studio gains an uncensored leg. fal Seedream is censored and
   answers HTTP 422 content_policy_violation on an explicit prompt, so an
   adult-confirmed user's render now rides the same SpicyAPI text-to-image the
   «Наедине» nude flow uses, and the mandatory SFW tail is swapped for a
   quality-only tail. Minors/coercion stay hard-blocked before any engine.

Static pins (no imports -> the suite runs without a DB/LLM key)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATES = (ROOT / 'services' / 'dates_service.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')


def test_date_pov_angle_defined():
    assert 'DATE_POV_ANGLE = (' in DATES
    low = DATES.lower()
    assert 'first-person pov' in low
    assert 'holding her hand' in low
    # it must NOT leak a second person's body into the frame
    assert "no other person's body or face appears" in DATES


def test_angle_overrides_shot_framing():
    # _shot_variant returns the requested angle verbatim, which is what lets a
    # date pin the POV framing without editing the shared SCENES dict.
    variant = PHOTO[PHOTO.index('def _shot_variant('):PHOTO.index('def _build_prompt(')]
    assert 'if requested_angle:' in variant
    assert 'return requested_angle' in variant
    assert 'CAMERA/POSE: {angle}' in PHOTO


def test_media_scene_threads_angle():
    assert "async def _webapp_media_scene(telegram_id: int, character_id: str, scene: str, angle: str = ''):" in MAIN
    scene_fn = MAIN[MAIN.index('async def _webapp_media_scene('):MAIN.index('async def _webapp_api_chat_media(')]
    assert "PhotoRequest(scene=scene, mood='romantic', angle=angle)" in scene_fn


def test_both_date_paths_use_pov():
    # app date action + bot reward path both pin the POV angle
    assert 'await _webapp_media_scene(telegram_id, character_id, date.scene, dates_service.DATE_POV_ANGLE)' in MAIN
    assert "PhotoRequest(scene=date.scene, mood='romantic', angle=dates_service.DATE_POV_ANGLE)" in MAIN
    # the ordinary chat-media photo menu keeps the default (no angle) framing
    assert 'await _webapp_media_scene(telegram_id, character_id, scene)' in MAIN


def test_studio_prompt_builder_supports_adult():
    assert 'PICTURE_PROMPT_SUFFIX_ADULT' in WEBAPP_SVC
    # the adult tail must NOT carry the SFW/no-nudity constraint
    assert 'no nudity' not in WEBAPP_SVC[WEBAPP_SVC.index('PICTURE_PROMPT_SUFFIX_ADULT'):WEBAPP_SVC.index('PICTURE_PROMPT_MAX_LEN')]
    assert "def picture_final_prompt(prompt: str, style: str = 'anime', fmt: str = 'square', adult: bool = False) -> str:" in WEBAPP_SVC
    assert 'tail = PICTURE_PROMPT_SUFFIX_ADULT if adult else PICTURE_PROMPT_SUFFIX' in WEBAPP_SVC


def test_studio_routes_adult_to_uncensored_engine():
    gen = MAIN[MAIN.index('async def _webapp_api_picture_generate('):MAIN.index('async def _webapp_pipeline_photo(')]
    assert 'adult_ok = is_adult_confirmed(telegram_id)' in gen
    assert 'picture_final_prompt(prompt, style, fmt, adult=adult_ok)' in gen
    assert 'from services.private_photo_service import generate_private_photo_t2i' in gen
    assert 'generate_private_photo_t2i(final_prompt)' in gen
    # the minors/coercion hard block still runs BEFORE any adult routing
    assert gen.index('picture_prompt_allowed(prompt)') < gen.index('adult_ok = is_adult_confirmed(')
    # the censored chain is kept only as a non-adult / fallback leg
    assert 'if not data:' in gen and 'generate_custom_avatar(final_prompt, None)' in gen
