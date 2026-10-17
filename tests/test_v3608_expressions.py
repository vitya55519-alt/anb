"""V3.60.8: «Наедине» gets real mimicry; the tongue stops showing on every frame."""
from services import photo_expression_service as e
from services import private_photo_service as pps


def test_rotation_has_no_tongue_face():
    # V3.64.3: the owner called the tongue face «ящерица» — no tongue in rotations.
    for _ in range(50):
        assert not set(e.shuffled_sensual_variety_keys()) & e.TONGUE_KEYS
        assert not set(e.shuffled_private_sensual_keys()) & e.TONGUE_KEYS
    for faces in pps._MOOD_EXPRESSIONS.values():
        assert not set(faces) & e.TONGUE_KEYS


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


def test_private_scene_has_no_out_of_place_location_or_pose():
    # V3.64.3: «пляж, балкон, около окна — не вписываются»
    ids = {loc['id'] for loc in pps.LOCATIONS}
    assert not ids & {'beach', 'balcony', 'nature'}
    assert not any('window' in p for p in pps.PRIVATE_POSE_POOL)
    assert not any('bed' in p for p in pps._pose_pool_for('closet'))
    req = pps.PrivatePhotoRequest(category='fully_nude', type_id='shower', location_id='beach', mood_id='passionate', character_id='zlata_01')
    prompt = pps.build_private_photo_prompt(req, 'x')
    assert 'Location: In shower' in prompt and 'Beach' not in prompt
