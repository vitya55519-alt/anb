from services import storylines


def test_custom_character_has_seven_plots():
    cid = 'custom_123_abcd1234'
    plots = storylines.for_character(cid)
    assert len(plots) == 7 and all(p.character_id == cid for p in plots)
    assert storylines.get(cid, 'blackout') is not None
    assert storylines.public_list(cid)


def test_unknown_non_custom_stays_empty():
    assert storylines.for_character('nobody_01') == ()
