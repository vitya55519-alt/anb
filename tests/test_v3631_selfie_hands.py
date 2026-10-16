"""V3.62.6: a handheld selfie keeps one free hand; the fitter keeps the HANDS,
quality and frame-chaining lines; «Раздеть» keeps the phone hand."""
import services.photo_service as ps
import services.private_photo_service as pps


class _Req:
    pose_rotation = ('arms loosely crossed with a relaxed confident stance',)


def test_selfie_replaces_two_hand_pose():
    note = ps._pose_note(_Req(), 'front-camera selfie at arm’s length', 0)
    assert 'crossed' not in note and 'her other hand holds the phone' in note


def test_non_selfie_keeps_pose():
    assert ps._pose_note(_Req(), 'full-body framing', 0) == _Req.pose_rotation[0]


def test_one_hand_pose_kept_in_selfie():
    class R:
        pose_rotation = ('a soft glance back over her shoulder',)
    assert ps._pose_note(R(), 'mirror selfie', 0).startswith('a soft glance back')


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


def test_undress_tail_keeps_phone_hand():
    import main
    assert 'keeps holding it and the reveal uses only her other hand' in main.UNDRESS_TAIL


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
