"""V3.56.3 static checks: figure chaining inside a SpicyAPI photo set.

The owner watched Veronika's bust and hips «jump» between frames of one scene
set even though the BODY IDENTITY declaration rides in every prompt. Root
cause: both canonical references (i=0 face, i=1 look) are portrait crops — the
engines get NO visual body anchor, so Seedream re-improvises the figure from
text on every independent frame. Fix: frames 2..N receive the previous shot
(provider's signed asset URL, ~20 min lifetime) as a third reference and are
ordered to copy that body exactly; every frame also carries a plain-language
figure lock next to the abstract size wording.

Pins:
1. _spicyapi_render grows a keyword-only return_url flag; the default contract
   (bytes-or-None) is untouched for the «Наедине» callers;
2. _run_spicy_set chains: prev_url starts None, the third reference is appended
   only when a previous frame delivered, and the unpacked frame_url feeds it;
3. the chain clause and the figure lock are present in the spicy trailer.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
PRIVATE = (ROOT / 'services' / 'private_photo_service.py').read_text(encoding='utf-8')

SPICY_SET = PHOTO[PHOTO.index('async def _run_spicy_set('):PHOTO.index('def choose_photo_provider(')]
RENDER = PRIVATE[PRIVATE.index('async def _spicyapi_render('):PRIVATE.index('async def generate_private_photo_real(')]


def test_render_grows_return_url_without_breaking_legacy_contract():
    assert "scene: str = 'private', *, return_url: bool = False)" in RENDER
    # success hands back (bytes, url); every failure path yields (None, None)
    assert 'return (result, result_url if result else None)' in RENDER
    assert RENDER.count('return (None, None) if return_url else None') == 2
    # the no-flag contract stays bytes-or-None for the «Наедине» pipeline
    assert '\n    return result\n' in RENDER


def test_spicy_set_threads_the_previous_frame_url():
    assert 'prev_url: str | None = None' in SPICY_SET
    assert 'frame_refs = refs + ([prev_url] if prev_url else [])' in SPICY_SET
    assert 'data, frame_url = await _spicyapi_render(SPICYAPI_IMAGE_MODEL, prompt, frame_refs' in SPICY_SET
    assert "return_url=True" in SPICY_SET
    # the url only feeds the chain after a delivered frame
    assert 'prev_url = frame_url' in SPICY_SET
    assert SPICY_SET.index('if not data:') < SPICY_SET.index('prev_url = frame_url')


def test_chain_clause_and_figure_lock_in_the_spicy_trailer():
    assert "if prev_url:" in SPICY_SET
    assert 'REFERENCE IMAGE 3 is the PREVIOUS photo of this same shoot' in SPICY_SET
    assert 'Her figure is locked for this entire shoot' in SPICY_SET
    # the legacy identity wording the older release pins demand is untouched
    assert 'her body always follows the declared BODY IDENTITY — never the reference silhouette.' in SPICY_SET
