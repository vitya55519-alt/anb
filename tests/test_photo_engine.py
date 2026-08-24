from services.photo_service import (
    scene_allowed_for_stage, parse_photo_request, is_custom_request,
    _wardrobe_pool,
)


def test_photo_stage_rules():
    assert scene_allowed_for_stage('selfie', 'stranger')
    assert scene_allowed_for_stage('shop', 'acquaintance')
    assert scene_allowed_for_stage('restaurant', 'close')
    assert scene_allowed_for_stage('bar', 'intimate')
    assert not scene_allowed_for_stage('club', 'intimate')
    assert scene_allowed_for_stage('club', 'deeply_connected')
    assert scene_allowed_for_stage('private_fashion', 'committed')


def test_photo_request_parser():
    r = parse_photo_request('покажись летом в парке с высоким хвостом')
    assert r and r.scene == 'park' and r.hairstyle == 'a sleek high ponytail' and r.season == 'summer'
    r = parse_photo_request('сделай фото в черном платье со спины')
    assert r and r.scene == 'personal' and 'black' in r.clothing and r.angle
    r = parse_photo_request('сфоткайся в караоке')
    assert r and r.scene == 'karaoke'
    r = parse_photo_request('пришли фото из клуба')
    assert r and r.scene == 'club'


def test_lingerie_customization_parser():
    r = parse_photo_request('сделай фото в красном белье и чулках, волосы хвост')
    assert r and r.scene == 'lingerie'
    assert 'red' in r.clothing and 'stockings' in r.clothing
    assert r.hairstyle == 'a sleek high ponytail'
    assert is_custom_request(r)


def test_explicit_request_maps_to_adult_scene():
    r = parse_photo_request('сделай голое фото')
    assert r and r.scene == 'nude'


def test_summer_park_wardrobe_has_no_heavy_sweater():
    for level in range(1, 7):
        pool = _wardrobe_pool('park', level, 'summer')
        joined = ' '.join(pool).lower()
        assert 'hoodie' not in joined and 'heavy knit' not in joined and 'sweater' not in joined


def test_visual_progression_has_different_level_pools():
    low = set(_wardrobe_pool('home', 1, 'summer'))
    high = set(_wardrobe_pool('home', 6, 'summer'))
    assert low != high
    assert any('dress' in x.lower() for x in high)
