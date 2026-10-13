"""V3.60.1: sexier dressed looks at high levels; the photo's time follows his words."""
import services.photo_service as ps


def test_high_levels_are_short_dresses_and_stockings():
    for lvl in (5, 6):
        rule = ps.LEVEL_VISUAL_RULES[lvl]
        assert 'stockings' in rule and 'figure-hugging' in rule
    assert 'maxi' in ps.LEVEL_HEMLINE_RULE and 'garters' in ps.LEVEL_HEMLINE_RULE
    src = open(ps.__file__, encoding='utf-8').read()
    assert "if not private_look and level_key >= 3:" in src


def test_time_named_in_request_wins():
    assert ps.parse_photo_request('пришли фото в парке днём').time_of_day == 'bright daytime light'
    assert ps.parse_photo_request('пришли фото в парке').time_of_day == ''
    assert ps.parse_photo_request('сфоткай себя утром').time_of_day == 'soft morning light'


def test_night_park_gets_street_lamps_not_a_window():
    night = ps._outdoor_light('late night: dim warm bedside or lamp light, deep dark night outside the window, no daylight anywhere', 'park')
    assert 'street lamps' in night and 'window' not in night
    assert ps._outdoor_light('bright daytime light', 'park') == 'bright daytime light'
    assert ps._outdoor_light('late night: x', 'home') == 'late night: x'


def test_inside_is_not_morning():
    assert ps.parse_photo_request('пришли фото внутри кафе').time_of_day == ''
