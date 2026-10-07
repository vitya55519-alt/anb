"""V3.56.1 static checks: SpicyAPI renders every scene (owner: «он лучше фаи»).

The owner reversed the V3.44.19 «photos on fal only» policy: the Наедине engine
produces better results than fal AND is cheaper per job ($0.0345 vs $0.04), so
ALL scene photos — public chat scenes, app media, studio prompts — must render
through SpicyAPI first. fal stays as the safety leg when the key is missing or
the engine returns nothing, so the strict-fal refund path is never lost.

Pins:
1. PHOTO_SPICY_FIRST knob (default on, env-off);
2. choose_photo_provider returns 'spicyapi' only when the knob is on AND a key
   is present — with no key every legacy fal-only assertion still holds;
3. _run_spicy_set reuses the seedream prompt builder (identity locks), the two
   canonical reference URLs, returns bytes-carrying GeneratedPhoto, and raises
   only on a zero-delivery set so partial packs survive;
4. the router walks spicyapi → seedream45 with a fallback event;
5. the studio tries spicy (t2i for adult, i2i for clothed no-reference runs)
   before falling back to generate_custom_avatar.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')

CHOOSE = PHOTO[PHOTO.index('def choose_photo_provider('):PHOTO.index('async def _run_routed_photo_set(')]
SPICY_SET = PHOTO[PHOTO.index('async def _run_spicy_set('):PHOTO.index('def choose_photo_provider(')]
ROUTED = PHOTO[PHOTO.index('async def _run_routed_photo_set('):PHOTO.index('async def generate_photo_set(')]


def test_spicy_first_knob():
    assert 'PHOTO_SPICY_FIRST = os.getenv("PHOTO_SPICY_FIRST", "1") == "1"' in CONFIG
    assert 'SPICYAPI_KEY, SPICYAPI_IMAGE_MODEL, SPICYAPI_ESTIMATED_COST_USD, PHOTO_SPICY_FIRST,' in PHOTO


def test_router_prefers_spicy_only_with_key():
    # knob AND key gate the route — no key keeps the legacy fal-only behavior
    assert "if PHOTO_SPICY_FIRST and SPICYAPI_KEY:\n        return 'spicyapi'" in CHOOSE
    assert CHOOSE.index("return 'spicyapi'") < CHOOSE.index('mode = PHOTO_ROUTER_MODE')


def test_spicy_set_reuses_the_seedream_prompt_chain():
    assert '_build_prompt(request, i, seedream=True' in SPICY_SET
    # canonical face+body references, same public endpoints the «Наедине» uses
    assert 'webapp/photo/{character_id}?i=0' in SPICY_SET
    assert 'webapp/photo/{character_id}?i=1' in SPICY_SET
    # bytes ride GeneratedPhoto.data (like the gemini leg), not a URL
    assert "GeneratedPhoto(data=data, provider='spicyapi'" in SPICY_SET
    # provider stats + spend ledger hooks
    assert "record_provider('spicyapi', bool(data)" in SPICY_SET
    assert 'from services.private_photo_service import _spicyapi_render' in SPICY_SET
    # partial packs survive: raise only when nothing was delivered
    assert SPICY_SET.count('raise PhotoGenerationError') == 2
    assert 'if out:' in SPICY_SET and 'break' in SPICY_SET


def test_routed_walks_spicy_then_fal():
    assert "if provider == 'spicyapi':" in ROUTED
    assert '_run_spicy_set(character, telegram_id, resolved' in ROUTED
    assert "from=spicyapi to=seedream45" in ROUTED
    assert ROUTED.index("if provider == 'spicyapi':") < ROUTED.index("if provider == 'seedream45':")


def test_studio_scenes_ride_spicy_before_fal():
    # non-adult studio runs without an uploaded reference try spicy i2i first
    assert "if not data and ref_path is None:" in MAIN
    block = MAIN[MAIN.index("if not data and ref_path is None:"):]
    assert "category='studio'" in block[:600]
    assert 'generate_private_photo_real(_req, character_dna_context(_char), final_prompt)' in block[:900]
    # the fal avatar engine stays as the last leg
    assert 'photo_service.generate_custom_avatar(final_prompt, ref_path)' in block[:1400]
