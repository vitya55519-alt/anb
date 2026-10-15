"""V3.62.4: SpicyAPI rejects prompts over 5000 characters; every scene prompt
is fitted under the cap while identity and the adult lock survive."""
import services.private_photo_service as pps
from services import photo_service as ps
from services.photo_service import PhotoRequest


def _scene_prompt(cid, level):
    req = PhotoRequest(scene='selfie')
    return ps._build_prompt(req, 0, seedream=True, relationship_level=level, character_id=cid) + (
        '\nCreate exactly ONE photo for this shot. Keep the same hairstyle. '
        'Make this framing clearly different from the previous shot.'
    ) + ' REFERENCE IMAGE 3 is the PREVIOUS photo of this same shoot. Take face and hair identity from images 1–2 only.'


def test_short_prompt_untouched():
    assert pps._fit_spicy_prompt('hello. world.') == 'hello. world.'


def test_real_scene_prompts_fit_and_keep_identity():
    for cid in ('vika_01', 'anna', 'maria_01'):
        for level in (1, 6, 10):
            raw = _scene_prompt(cid, level)
            fitted = pps._fit_spicy_prompt(raw)
            assert len(fitted) <= pps.SPICYAPI_PROMPT_MAX
            assert 'PHOTO IDENTITY:' in fitted
            assert 'Never depict minors' in fitted
            assert 'WARDROBE:' in fitted
            assert 'Create exactly ONE photo' in fitted


def test_least_important_lines_go_first():
    filler = 'x' * 3000 + '.'
    raw = '\n'.join(['PHOTO IDENTITY: keep her. ' + filler, 'LIGHTING: soft. ' + filler, 'WARDROBE: a dress.'])
    fitted = pps._fit_spicy_prompt(raw)
    assert 'LIGHTING:' not in fitted and 'WARDROBE: a dress.' in fitted


def test_request_body_uses_fitted_prompt():
    import inspect
    src = inspect.getsource(pps._spicyapi_render_once)
    assert '"prompt": _fit_spicy_prompt(prompt)' in src
