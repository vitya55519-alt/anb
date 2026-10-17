"""V3.62.14: «я скучала» pool — one-hand poses, and pre-fix generated photos are never sent."""
import datetime as dt


def test_every_gift_shot_names_the_phone_hand():
    from services.gift_pool_service import GIFT_SHOTS, GIFT_FRAMING
    assert 'exactly two arms' in GIFT_FRAMING
    for shot in GIFT_SHOTS:
        angle = shot[3]
        assert 'one hand' in angle and 'hugs' not in angle, angle


def test_gift_request_pins_its_own_pose():
    from services.gift_pool_service import GIFT_SHOTS, GIFT_POSE, gift_request
    from services.photo_service import _pose_note
    req = gift_request(GIFT_SHOTS[0])
    assert req.pose_rotation == (GIFT_POSE,)
    note = _pose_note(req, req.angle, 0)
    assert note.startswith(GIFT_POSE) and 'other hand holds the phone' in note


def test_photos_from_broken_window_are_retired_but_videos_stay():
    from services.retention_features_service import proactive_photo_retired
    bad = dt.datetime(2026, 10, 16, 12, 0)
    assert proactive_photo_retired('photo', bad)
    assert not proactive_photo_retired('video', bad)
    assert not proactive_photo_retired('gif', bad)
    assert not proactive_photo_retired('photo', dt.datetime(2026, 10, 16, 19, 30))
    assert not proactive_photo_retired('photo', dt.datetime(2026, 10, 10))
