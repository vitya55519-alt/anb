"""V3.62.6 → V3.166.12: the phone left the frame, so the pose is only the pose;
the fitter keeps the HANDS, quality and frame-chaining lines; «Раздеть» keeps
both hands free for the reveal."""
import services.photo_service as ps
import services.private_photo_service as pps


class _Req:
    pose_rotation = ('arms loosely crossed with a relaxed confident stance',)


def test_pose_note_no_longer_borrow_a_hand_for_the_camera():
    note = ps._pose_note(_Req(), 0)
    assert note == _Req.pose_rotation[0]
    assert 'phone' not in note.lower() and 'selfie' not in note.lower()


def test_fitter_keeps_hands_quality_and_chain():
    filler = ' '.join(['Filler sentence number %d.' % i for i in range(400)])
    raw = '\n'.join([
        'PHOTO IDENTITY: keep her face.', 'MOOD: warm. ' + filler,
        ps.HANDS_RULE, ps.QUALITY_BLOCK, 'REFERENCE IMAGE 3 is the previous photo.',
    ])
    fitted = pps._fit_spicy_prompt(raw)
    assert len(fitted) <= pps.SPICYAPI_PROMPT_MAX
    assert ps.HANDS_RULE in fitted and ps.QUALITY_BLOCK in fitted
    assert 'REFERENCE IMAGE 3 is the previous photo.' in fitted


def test_undress_tail_keeps_both_hands_free():
    import main
    assert 'exactly two arms and two hands' in main.UNDRESS_TAIL
    assert 'no device and no arm reaching toward the camera' in main.UNDRESS_TAIL
    assert 'holds' not in main.UNDRESS_TAIL.lower()


def test_stats_show_sources():
    import main
    snap = {'sources_24h': [['organic', 30], ['ref', 4], ['link:tgads_7', 6]], 'sources_7d': []}
    block = main._sources_block(snap)
    assert 'без метки' in block and 'по приглашению друга — 4' in block
    assert 'ссылка ?start=tgads_7 — 6' in block and '· нет новых' in block


def test_analytics_snapshot_has_source_windows():
    from services.analytics_service import admin_snapshot
    snap = admin_snapshot()
    assert 'sources_24h' in snap and 'sources_7d' in snap
