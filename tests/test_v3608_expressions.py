"""V3.60.8: «Наедине» gets real mimicry; the tongue stops showing on every frame."""
from services import photo_expression_service as e
from services import private_photo_service as pps


def test_rotation_keeps_one_tongue_face():
    for _ in range(50):
        assert len(set(e.shuffled_sensual_variety_keys()) & e.TONGUE_KEYS) == 1
        assert len(set(e.shuffled_private_sensual_keys()) & e.TONGUE_KEYS) == 1


def test_mood_faces_exist():
    for faces in pps._MOOD_EXPRESSIONS.values():
        for key in faces:
            assert key in e.EXPRESSIONS


def test_private_prompt_has_expression():
    for mood in ('random', 'shy', 'passionate'):
        req = pps.PrivatePhotoRequest(category='lingerie', type_id='lace', location_id='bedroom', mood_id=mood, character_id='zlata_01')
        prompt = pps.build_private_photo_prompt(req, 'x')
        assert 'EXPRESSION: she has' in prompt
        assert prompt.strip().splitlines()[-1].startswith('FACE LOCK')
