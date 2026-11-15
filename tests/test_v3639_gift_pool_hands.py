"""V3.62.14 → V3.166.12: «я скучала» pool — two hands, nothing held, and
pre-fix generated photos are never sent."""
import datetime as dt


def test_every_gift_shot_keeps_both_hands_busy_and_empty():
    from services.gift_pool_service import GIFT_SHOTS, GIFT_FRAMING
    assert 'exactly two arms' in GIFT_FRAMING
    assert 'never reach toward the camera' in GIFT_FRAMING
    for shot in GIFT_SHOTS:
        angle = shot[3]
        assert 'one hand' in angle and 'hugs' not in angle, angle
        assert 'phone' not in angle.lower() and 'selfie' not in angle.lower(), angle


def test_gift_request_pins_its_own_pose():
    from services.gift_pool_service import GIFT_SHOTS, GIFT_POSE, gift_request
    from services.photo_service import _pose_note
    req = gift_request(GIFT_SHOTS[0])
    assert req.pose_rotation == (GIFT_POSE,)
    note = _pose_note(req, 0)
    assert note.startswith(GIFT_POSE) and 'phone' not in note.lower()


def test_photos_from_broken_window_are_retired_but_videos_stay():
    from services.retention_features_service import proactive_photo_retired
    bad = dt.datetime(2026, 10, 16, 12, 0)
    assert proactive_photo_retired('photo', bad)
    assert not proactive_photo_retired('video', bad)
    assert not proactive_photo_retired('gif', bad)
    assert not proactive_photo_retired('photo', dt.datetime(2026, 10, 16, 19, 30))
    assert not proactive_photo_retired('photo', dt.datetime(2026, 10, 10))
