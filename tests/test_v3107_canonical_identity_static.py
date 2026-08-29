from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
ANNA = (ROOT / 'data' / 'characters' / 'anna.json').read_text(encoding='utf-8')


def test_new_canonical_refs_exist_and_are_configured():
    assert (ROOT / 'data/references/anna/00_anna_canonical_face_v3.png').exists()
    assert (ROOT / 'data/references/anna/01_anna_canonical_look_v3.png').exists()
    assert '00_anna_canonical_face_v3.png' in ANNA
    assert '01_anna_canonical_look_v3.png' in ANNA

def test_legacy_face_refs_not_active_fallbacks():
    block = PHOTO[PHOTO.index('def _openai_reference_paths'):PHOTO.index('def _seedream_reference_path')]
    assert '00_identity_face_new.png' not in block
    assert '00_seedream_face_safe.png' not in block

def test_seedream_uses_new_identity_anchor():
    block = PHOTO[PHOTO.index('def _seedream_reference_path'):PHOTO.index('def _pick_nonrepeat')]
    assert 'seedream_identity_anchor' in block
    assert '01_anna_canonical_look_v3.png' in block
    assert '00_seedream_face_safe.png' not in block

def test_generated_photos_have_smile_instruction():
    assert 'EXPRESSION_IDENTITY' in PHOTO
    assert 'natural warm feminine smile' in PHOTO
    # The identity lock now returns expression text as a tuple value.
    assert "f'{expression_identity}\\n'" in PHOTO

def test_personal_scene_is_lingerie_and_seedream():
    assert "'personal':'adult'" in PHOTO
    assert 'request.scene in SEEDREAM_ADULT_SCENES or INTIMATE_STYLE.search' in PHOTO
    assert 'tasteful private adult lingerie portrait' in PHOTO


def test_personal_safe_retry_stays_lingerie():
    block = PHOTO[PHOTO.index('def _seedream_safe_retry_request'):PHOTO.index('async def _run_seedream_set')]
    assert "request.scene in {'personal', 'lingerie', 'nude', 'tease'}" in block
    assert 'opaque lingerie fashion set' in block
