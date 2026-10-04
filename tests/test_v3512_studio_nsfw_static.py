"""V3.51.2 (studio leg) + V3.51.3 (POV revert guard).

The V3.51.2 uncensored studio leg stays: an adult-confirmed «Картинки» render
routes to the SpicyAPI text-to-image engine (fal Seedream is censored and answers
HTTP 422 content_policy_violation on an explicit prompt), and the mandatory SFW
tail is swapped for a quality-only tail. Minors/coercion stay hard-blocked first.

The V3.51.2 first-person POV date photos were rolled back in V3.51.3 (the owner
didn't like the result), so this file also guards that the POV angle plumbing is
gone and dates are back on the plain scene framing.

Static pins (no imports -> the suite runs without a DB/LLM key)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
DATES = (ROOT / 'services' / 'dates_service.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')


def test_pov_date_plumbing_reverted():
    # V3.51.3: the POV experiment is fully removed.
    assert 'DATE_POV_ANGLE' not in DATES
    assert 'DATE_POV_ANGLE' not in MAIN
    assert "async def _webapp_media_scene(telegram_id: int, character_id: str, scene: str):" in MAIN
    assert "PhotoRequest(scene=date.scene, mood='romantic')" in MAIN


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
