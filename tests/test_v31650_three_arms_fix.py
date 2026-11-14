"""V3.165.0: третий руки на фото после покупки наряда больше нет.

Бракованный кадр владельца: купил «Лане» бельё в магазине — получил девушку с
тремя руками. Причина не в движке, а в трёх противоречащих строках промпта:

1. AMATEUR HOT FRAME («её рука и телефон в кадре») ехал в начало промпта,
   HANDS_RULE («ровно две руки») — в конец, и _fit_spicy_prompt срезал его
   первым при переполнении лимита SpicyAPI. Провайдер дочитывал кадр с
   телефоном и не дочитывал запрет третьей руки.
2. _is_handheld_selfie узнавал только слова «selfie», а варианты камеры сцены
   lingerie («mirror-style lingerie fashion portrait») их не содержат —
   двух-рукие позы не заменялись на одно-рукие.
3. В «Наедине» тот же конфликт: amateur-замок добавлялся к промпту, а
   PRIVATE_POSE_POOL предлагал «both hands free», «hands in hair».
"""
import re
from pathlib import Path

import services.photo_service as ps
import services.private_photo_service as pps

ROOT = Path(__file__).resolve().parents[1]
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
PRIVATE = (ROOT / 'services' / 'private_photo_service.py').read_text(encoding='utf-8')


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


def test_mirror_lingerie_angle_counts_as_phone_in_hand():
    for angle in ps.SHOT_VARIANTS['lingerie']:
        if 'mirror' in angle.lower():
            assert ps._is_handheld_selfie(angle), angle
    assert ps._is_handheld_selfie('front-camera selfie at arm’s length')
    assert not ps._is_handheld_selfie('full-body photo from behind on the path')
    assert not ps._is_handheld_selfie('self-timer photo sitting on a park bench')


def test_phone_frame_never_keeps_a_two_hand_pose():
    class Req:
        pose_rotation = ('arms loosely crossed with a relaxed confident stance',)

    note = ps._pose_note(Req(), 'tasteful adult glamour portrait, non-explicit', 0, True)
    assert 'crossed' not in note
    assert 'her other hand holds the phone' in note
    assert note.startswith('her free hand') or 'free' in note.split(' (')[0]


def test_pose_note_without_a_phone_frame_stays_as_is():
    class Req:
        pose_rotation = ('arms loosely crossed with a relaxed confident stance',)

    assert ps._pose_note(Req(), 'full-body framing', 0) == Req.pose_rotation[0]


def test_hot_private_frame_spends_one_hand_on_the_phone():
    assert "pose = f'{_one_hand_pose(pose, random.randrange(1000))} (her other hand holds the phone)'" in PRIVATE
    assert 'amateur_hot = True' in PRIVATE

    # a two-hand private pose really collapses to a free-hand one
    two_hand = [p for p in pps.PRIVATE_POSE_POOL if any(m in p.lower() for m in ps._TWO_HAND_MARKERS)]
    assert two_hand, 'private pool lost its two-hand poses — the guard is untested'
    for pose in two_hand:
        fixed = ps._one_hand_pose(pose, 0)
        assert not any(m in fixed.lower() for m in ps._TWO_HAND_MARKERS if m != 'tripod'), pose


def test_wardrobe_tryon_scene_lingerie_is_covered():
    # the exact frame the owner bought: an adult gift item rendered on the
    # lingerie scene must land on a one-hand pose, not on three arms
    from services.wardrobe_catalog import ITEMS
    lingerie = [i for i in ITEMS if i.tryon == 'lingerie']
    assert lingerie
    variants = ps.SHOT_VARIANTS['lingerie']
    assert any('mirror' in v.lower() for v in variants)
    assert 'her other hand holds the phone' in PHOTO
