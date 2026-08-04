from services.photo_service import scene_allowed_for_stage, parse_photo_request

def test_photo_stage_rules():
    assert scene_allowed_for_stage('selfie','stranger')
    assert scene_allowed_for_stage('evening','close')
    assert not scene_allowed_for_stage('lingerie','close')
    assert scene_allowed_for_stage('lingerie','intimate')

def test_photo_request_parser():
    r=parse_photo_request('покажись в парке с высоким хвостом')
    assert r and r.scene=='park' and r.hairstyle=='high ponytail'
    r=parse_photo_request('сделай фото в черном платье со спины')
    assert r and r.scene=='outfit' and 'black' in r.clothing and r.angle

def test_explicit_request_is_normalized_to_safe_fashion():
    r=parse_photo_request('сделай голое фото')
    assert r and r.scene=='fashion' and 'non-explicit' in r.clothing
