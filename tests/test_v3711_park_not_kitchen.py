from pathlib import Path


def test_explicit_place_button_beats_chat_scene_card():
    src = Path('services/photo_service.py').read_text()
    assert 'elif card_scene and request.scene not in PLACE_BUTTON_SCENES:' in src
