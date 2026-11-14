"""V3.165.0 (#104 / задача 111): фото по фетишу.

Владелец: «тема из „🎭 Фетиши“ (17 готовых + своя) подмешивается в промпт кадра
(WARDROBE/сцена), 300 🍑, движок не должен фильтровать промпт».

Что здесь держится на месте:
 • тема — одна строка промпта, которая называет и одежду, и комнату, и что делают
   её руки. Поэтому из мастера кадра в такой промпт не попадают ни POSE, ни
   Location: две случайные фразы про одно и то же и рождали «третью руку» (#99)
   и «душ на пляже» (В3.152.1);
 • категория «fetish» скрыта: у неё свой вход — чип 📸 в листе фетишей, а не
   шестая кнопка в «Наедине»;
 • своя формулировка проверяется тем же жёстким фильтром, что и чат-режим, и
   отказывается ДО генерации, то есть до списания персиков.
"""
from pathlib import Path

import config
from services import fetish_mode, private_photo_service as pps

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def _req(theme: str, **kw) -> pps.PrivatePhotoRequest:
    kw.setdefault('type_id', 'feet')
    kw.setdefault('location_id', 'bedroom')
    kw.setdefault('mood_id', '')
    return pps.PrivatePhotoRequest(category='fetish', theme=theme,
                                   character_id='anna_01', **kw)


def test_fetish_category_is_hidden_and_costs_the_frame_price():
    cat = pps.PRIVATE_PHOTO_CATEGORIES['fetish']
    assert cat['hidden'] is True, 'у темы свой вход — чип 📸, не кнопка в «Наедине»'
    assert cat['peach_cost'] == config.EXPLICIT_PHOTO_PEACH_COST == 300
    assert len(cat['types']) == len(fetish_mode.FETISHES) == 17
    assert [t['id'] for t in cat['types']] == [f[0] for f in fetish_mode.FETISHES]


def test_the_hidden_category_never_reaches_the_wizards():
    # bot menu + the app's «Наедине» payload skip it, and the callback refuses it.
    assert MAIN.count("if cat_data.get('hidden'):") >= 2
    assert "if not cat_data or cat_data.get('hidden'):" in MAIN


def test_theme_line_is_the_last_word_about_her_wardrobe_and_hands():
    theme = fetish_mode.PHOTO_THEMES['bondage']
    prompt = pps.build_private_photo_prompt(_req(theme), 'x')
    assert f'THEME (he chose it himself, 18+ confirmed): {theme}.' in prompt
    assert 'no second body, no extra limbs.' in prompt
    # the theme says where she is → the wizard Location must not contradict it,
    # and she is never left in the old black void (V3.60.1).
    assert prompt.index('THEME (he chose') > prompt.index('PLACE:')
    assert 'Location:' not in prompt
    assert 'never a plain black or empty backdrop' in prompt
    # a second random pose on top of the theme is the third-arm bug.
    assert 'POSE:' not in prompt
    assert any(cam in prompt for cam in pps.FETISH_CAMERA_POOL)
    assert 'NSFW content allowed, uncensored generation' in prompt


def test_a_plain_frame_still_gets_pose_and_location():
    prompt = pps.build_private_photo_prompt(pps.PrivatePhotoRequest(
        category='lingerie', type_id='bra_panties', location_id='bedroom',
        mood_id='', character_id='anna_01'), 'x')
    assert 'POSE:' in prompt and 'Location:' in prompt
    assert 'THEME (' not in prompt


def test_the_reference_photo_only_lends_her_face():
    prompt = pps.build_private_photo_prompt(_req(fetish_mode.PHOTO_THEMES['latex']), 'x',
                                            use_reference=True)
    assert 'REFERENCE IMAGE 1 gives ONLY her face, hair and skin tone.' in prompt
    assert 'exactly as the THEME line says' in prompt


def test_every_ready_theme_is_one_woman():
    # A second body in the prompt is what grew the third arm (#99): the risky
    # themes are written as her playing to someone off camera.
    assert set(fetish_mode.PHOTO_THEMES) == {f[0] for f in fetish_mode.FETISHES}
    for key, line in fetish_mode.PHOTO_THEMES.items():
        low = line.lower()
        for second_body in (' he ', ' a man ', ' two women', ' two girls', ' another woman', ' second girl'):
            assert second_body not in low, f'{key}:{second_body!r}'


def test_the_engine_is_told_not_to_filter_this_prompt():
    assert 'fetish' in pps.ADULT_RENDER_CATEGORIES
    # HOT_PRIVATE_CATEGORIES is pinned elsewhere (V3.152.1) and drives the
    # amateur-selfie lock, which fights the theme wording — keep it out.
    assert 'fetish' not in pps.HOT_PRIVATE_CATEGORIES
    assert 'cat_id in ADULT_RENDER_CATEGORIES or bool(req.theme)' in MAIN


def test_his_own_words_pass_the_hard_limits_before_anything_is_billed():
    ok = fetish_mode.photo_theme_text('чулки и ленты в спальне')
    assert ok and ok['key'] == 'custom' and 'чулки' in ok['visual']
    assert 'only her in the frame' in ok['visual']
    for bad in ('', 'ab', 'инцест', 'он принуждает её', 'малолетняя школьница'):
        assert fetish_mode.photo_theme_text(bad) is None, bad
    # refused inside the gate, before the render and therefore before the charge.
    media = MAIN[MAIN.index('async def _webapp_api_chat_media'):]
    refused = media.index('photo_theme_text(theme_text)')
    assert 'def _gate():' in media[:refused]
    assert refused < media.index('_webapp_media_hot(telegram_id, character_id, scene, theme_text=theme_text)')
    assert "'theme_refused'" in MAIN
    assert "str(body.get('theme_text') or '')[:120]" in MAIN
