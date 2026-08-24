from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
LIB = (ROOT / 'services' / 'photo_library_service.py').read_text(encoding='utf-8')


def test_ai_failure_has_library_rescue():
    assert 'def choose_fallback_pack(' in LIB
    assert 'async def _deliver_library_failure_fallback' in PHOTO
    assert "provider='telegram_library_fallback'" in PHOTO
    assert 'AI failed but library fallback recovered' in PHOTO


def test_gpt_ordinary_path_does_not_use_revealing_body_anchor():
    block = PHOTO[PHOTO.index('body_candidates ='):PHOTO.index('body = next', PHOTO.index('body_candidates ='))]
    assert '00_body_canonical_v1.jpg' not in block
    assert '01_anna_canonical_look_v3.png' in block


def test_private_scenes_are_not_broad_fallback_targets():
    assert "_PRIVATE_LIBRARY_SCENES = {'personal', 'lingerie', 'private_fashion', 'peek', 'dressing', 'nude', 'tease'}" in PHOTO
    assert 'scene not in _PRIVATE_LIBRARY_SCENES' in PHOTO


def test_body_identity_uses_neutral_ratio_language():
    body = PHOTO.split('ANNA_BODY_IDENTITY = (', 1)[1].split(')\nOPENAI_REFERENCE_PROTOCOL', 1)[0]
    assert 'slim' in body
    assert 'fit' in body
    assert 'flat-chested' not in body
