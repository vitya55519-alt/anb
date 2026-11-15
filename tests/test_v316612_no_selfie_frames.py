"""V3.166.12 (владелец: «просто убери телефон»): селфи-рамки в кадре больше нет.

Третья рука на кадрах — это рука, тянущаяся к камере: промпт одновременно звал
«её рука и телефон в кадре» и двух-рукие позы, а у SpicyAPI нет канала
negative_prompt, чтобы это отменить. Решение — не лечить симптом, а убрать
саму рамку: телефон нигде не в её руках, камера стоит на полке/штативе/таймере.

Проверяем два контура:
1. рукописные строки промпта, где телефон был в её руке, вычищены в источнике;
2. всё, что пишет модель сама (живые ситуации, IMAGE_PROMPT из диалога), и всё,
   что осталось в банках, вычищает no_phone_frame перед отдачей движку.
"""
import re
from pathlib import Path

import services.photo_service as ps
import services.private_photo_service as pps

ROOT = Path(__file__).resolve().parents[1]
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
PRIVATE = (ROOT / 'services' / 'private_photo_service.py').read_text(encoding='utf-8')
LIVE = (ROOT / 'services' / 'live_situation_service.py').read_text(encoding='utf-8')


def _body(prompt: str) -> str:
    """The prompt without the lock line the sanitizer prepends."""
    return prompt.replace(ps.NO_PHONE_LOCK, '')


# «Смартфон» как эстетика кадра остаётся — убирается только само устройство в
# её руке и рука, тянущаяся к камере.
_HANDHELD = re.compile(r'\bphone\b|selfie|handheld|POV|arm[’\']s length', re.IGNORECASE)


def _handheld_bits(text: str) -> list[str]:
    return _HANDHELD.findall(_body(text))


# ── 1. замок и порядок строк ───────────────────────────────────────────────

def test_lock_is_the_first_line_of_a_built_scene_prompt():
    for scene in ('selfie', 'cafe', 'lingerie', 'nude', 'mirror'):
        prompt = ps._build_prompt(ps.PhotoRequest(scene=scene), 0, seedream=True,
                                  relationship_level=6, character_id='anna_01')
        assert prompt.startswith(ps.NO_PHONE_LOCK), scene
        assert 'NO HANDHELD CAMERA:' in prompt


def test_lock_never_pushes_down_the_duo_and_place_head_lines():
    duo = ps.PhotoRequest(scene='selfie', location='a sunny cafe terrace', with_guest='kamila_01')
    prompt = ps._build_prompt(duo, 0, seedream=True, relationship_level=2, character_id='anna_01')
    assert prompt.startswith('TWO WOMEN IN FRAME:')
    assert 'NO HANDHELD CAMERA:' in prompt
    office = ps._build_prompt(ps.PhotoRequest(scene='selfie',
                                              location='her office desk at the end of the workday'),
                              0, seedream=True, relationship_level=5, character_id='anna_01')
    assert office.startswith('PRIVATE PLACE OVERRIDE:')
    assert 'NO HANDHELD CAMERA:' in office


def test_lock_is_trimmed_last_by_the_spicy_fitter():
    filler = ' '.join(['Filler sentence number %d keeps this over the cap.' % i for i in range(400)])
    fitted = pps._fit_spicy_prompt('\n'.join(['SCENE: a cafe. ' + filler, ps.NO_PHONE_LOCK]))
    assert len(fitted) <= pps.SPICYAPI_PROMPT_MAX
    assert 'NO HANDHELD CAMERA:' in fitted


def test_both_render_guards_call_the_sanitizer():
    assert 'return no_phone_frame(' in PHOTO
    assert '"prompt": _fit_spicy_prompt(no_phone_frame(prompt))' in PRIVATE


# ── 2. старые строки с телефоном в руке убраны из промпта ──────────────────

def test_dead_selfie_helpers_are_gone():
    for name in ('_is_handheld_selfie', '_one_hand_pose', '_TWO_HAND_MARKERS', 'SELFIE_POSE_POOL'):
        assert name not in PHOTO, name
    assert 'her other hand holds the phone' not in PHOTO
    assert 'her other hand holds the phone' not in PRIVATE
    assert '(no phone in hand' not in PRIVATE and '(no phone in hand' not in PHOTO


def test_no_head_lock_asks_for_a_device_in_the_frame():
    for name in ('HANDS_RULE', 'AMATEUR_HOT_FRAME_LOCK', 'STARTER_AMATEUR_LOCK'):
        assert not _handheld_bits(getattr(ps, name)), name


def test_prompt_rules_never_park_a_phone_in_her_hand():
    assert 'keep exactly one phone in her own hand' not in LIVE
    assert 'phone in her own hand' not in LIVE
    import main
    assert 'if one hand holds the phone' not in main.UNDRESS_ANATOMY_LOCK
    assert 'keeps holding it' not in main.UNDRESS_ANATOMY_LOCK
    for pose in pps.PRIVATE_POSE_POOL + pps.PRIVATE_CAMERA_POOL + pps.FETISH_CAMERA_POOL:
        assert not _handheld_bits(pose), pose


# ── 3. no_phone_frame вычищает то, что осталось в банках и что пишет LLM ───

def _bank_lines() -> list[str]:
    lines = list(ps.SCENES.values())
    for variants in ps.SHOT_VARIANTS.values():
        lines.extend(variants)
    lines.extend(ps.POSE_POOL)
    from services.gift_pool_service import GIFT_SHOTS
    lines.extend(shot[3] for shot in GIFT_SHOTS)
    import services.live_situation_service as live
    for name in dir(live):
        if name.endswith('_SITUATIONS'):
            lines.extend(sit['image'] for sit in getattr(live, name))
    lines.extend(pps.PRIVATE_POSE_POOL)
    lines.extend(pps.PRIVATE_CAMERA_POOL)
    return lines


def test_every_bank_line_reaches_the_engine_phone_free():
    lines = _bank_lines()
    assert len(lines) > 100, 'bank sweep lost its coverage'
    for line in lines:
        assert not _handheld_bits(ps.no_phone_frame(line)), line


def test_built_scene_prompts_carry_no_handheld_wording():
    for scene in ('selfie', 'cafe', 'lingerie', 'nude', 'mirror', 'park'):
        for level in (2, 5, 6):
            prompt = ps._build_prompt(ps.PhotoRequest(scene=scene), 0, seedream=True,
                                      relationship_level=level, character_id='anna_01')
            assert not _handheld_bits(prompt), (scene, level)


def test_llm_written_image_prompt_is_neutralized():
    raw = ('IMAGE_PROMPT: first-person phone selfie in a mall fitting room, '
           'she holds the phone herself, mirror visible, arm reaching to the camera.')
    assert not _handheld_bits(ps.no_phone_frame(raw)), raw


def test_russian_scene_request_is_neutralized_too():
    raw = ('Камера: зеркальное селфи, телефон в руке, она смотрит в объектив. '
           'Свет тёплый, ванная комнаты.')
    clean = _body(ps.no_phone_frame(raw))
    assert 'селфи' not in clean and 'телефон' not in clean, clean


def test_sanitizer_is_idempotent_and_keeps_a_clean_line():
    once = ps.no_phone_frame('a bedroom photo in warm lamp light')
    assert ps.no_phone_frame(once) == once
    assert once.endswith('a bedroom photo in warm lamp light')
    assert ps.no_phone_frame('') == ''
