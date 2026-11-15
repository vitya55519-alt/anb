"""V3.165.0: третий руки на фото после покупки наряда больше нет.

Бракованный кадр владельца: купил «Лане» бельё в магазине — получил девушку с
тремя руками. Причина не в движке, а в противоречащих строках промпта:

1. AMATEUR HOT FRAME («её рука и телефон в кадре») ехал в начало промпта,
   HANDS_RULE («ровно две руки») — в конец, и _fit_spicy_prompt срезал его
   первым при переполнении лимита SpicyAPI. Провайдер дочитывал кадр с
   телефоном и не дочитывал запрет третьей руки.
2. Кадр одновременно звал двух-рукие позы и «руку с телефоном к камере».

V3.166.12 (владелец: «просто убери телефон»): руки с камерой в кадре больше нет
вовсе, поэтому конфликтующей ветки не существует. На месте остались только
порядок строк в промпте и право движка их не обрезать — их и проверяют тесты.
"""
from pathlib import Path

import services.photo_service as ps
import services.private_photo_service as pps

ROOT = Path(__file__).resolve().parents[1]
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')


def _hands_lock_rides_before_the_scene():
    start = PHOTO.index('hands_lock = f')
    return start < PHOTO.index("f'SCENE: {scene}", start)


def test_hands_lock_rides_at_the_head_of_the_prompt():
    assert _hands_lock_rides_before_the_scene()
    assert "+ f'{hands_lock}'" in PHOTO
    # and it left the tail for good
    assert "f'{HANDS_RULE}\\n'\n        f'{personal}\\n'" not in PHOTO


def test_hands_lock_is_trimmed_last_not_first():
    tier_of_hands = [n for n, prefixes in enumerate(pps._SPICY_TIERS, 1)
                     if 'HANDS:' in prefixes]
    assert tier_of_hands == [len(pps._SPICY_TIERS)]


def test_fitter_keeps_hands_lock_in_an_overflowing_prompt():
    filler = ' '.join([f'Sentence number {i} keeps this prompt over the cap.' for i in range(500)])
    raw = '\n'.join([ps.HANDS_RULE, 'MOOD: warm. ' + filler, ps.AMATEUR_HOT_FRAME_LOCK])
    fitted = pps._fit_spicy_prompt(raw)
    assert len(fitted) <= pps.SPICYAPI_PROMPT_MAX
    assert fitted.startswith('HANDS:'), fitted[:80]


def test_no_phone_arm_lock_is_trimmed_last_too():
    tier_of_lock = [n for n, prefixes in enumerate(pps._SPICY_TIERS, 1)
                    if 'NO HANDHELD CAMERA:' in prefixes]
    assert tier_of_lock == [len(pps._SPICY_TIERS)]


def test_amateur_lock_no_longer_puts_a_device_in_the_frame():
    assert 'phone' not in ps.AMATEUR_HOT_FRAME_LOCK.lower()
    assert 'selfie' not in ps.AMATEUR_HOT_FRAME_LOCK.lower()
    assert 'both her hands are free' in ps.AMATEUR_HOT_FRAME_LOCK


def test_pose_note_has_no_camera_hand_left():
    class Req:
        pose_rotation = ('arms loosely crossed with a relaxed confident stance',)

    note = ps._pose_note(Req(), 0)
    assert note == Req.pose_rotation[0]
    assert 'phone' not in note.lower()


def test_wardrobe_tryon_scene_lingerie_is_covered():
    # the exact frame the owner bought: an adult gift item rendered on the
    # lingerie scene must not put a hand on the way to the camera
    from services.wardrobe_catalog import ITEMS
    assert [i for i in ITEMS if i.tryon == 'lingerie']
    prompt = ps._build_prompt(ps.PhotoRequest(scene='lingerie'), 0, seedream=True,
                              relationship_level=5, character_id='anna_01')
    assert 'NO HANDHELD CAMERA:' in prompt
    assert 'her other hand holds the phone' not in prompt
    body = prompt.replace(ps.NO_PHONE_LOCK, '').lower().replace('smartphone', '')
    assert 'phone' not in body and 'selfie' not in body
