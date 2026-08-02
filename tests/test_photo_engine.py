from services.photo_service import scene_allowed_for_stage, suggest_scene_from_text


def test_photo_limits_follow_relationship_stage():
    assert scene_allowed_for_stage("selfie", "stranger")
    assert scene_allowed_for_stage("evening", "close")
    assert not scene_allowed_for_stage("evening", "acquaintance")
    assert scene_allowed_for_stage("personal", "intimate")
    assert not scene_allowed_for_stage("personal", "close")


def test_scene_suggestions():
    assert suggest_scene_from_text("Я сейчас сижу в кафе") == "cafe"
    assert suggest_scene_from_text("Что на тебе сегодня?") == "outfit"
    assert suggest_scene_from_text("покажись 😊") == "selfie"
    assert suggest_scene_from_text("Расскажи про работу") is None


def test_sixth_stage_and_lingerie_states():
    assert scene_allowed_for_stage("lingerie", "intimate")
    assert scene_allowed_for_stage("lingerie_bed", "deeply_connected")
    assert scene_allowed_for_stage("lingerie_red", "committed")
    assert not scene_allowed_for_stage("lingerie_red", "deeply_connected")
