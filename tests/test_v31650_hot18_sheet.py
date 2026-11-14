"""V3.165.0 (#107, владелец): лист «🔥 Только 18+» — только название и цена числом.

ТЗ: «только название и цена числом (300 🍑, 2 000 🍑), без пояснений и без
„за 🍑"; строку „Горячий кружок" убрать как дубль, „Тайное видео" переименовать
в „Горячее видео"; в обычном режиме лист оставляем как есть, во всех строках».
Цифры на экран никогда не кладём руками — лист читает их из /webapp/api/me
(PP()), как и остальные экраны V3.165.0.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')

SHEET = INDEX[INDEX.index('function openHot18('):INDEX.index('async function openCharTune(')]


def test_the_sheet_knows_his_mode():
    assert 'const spicy = !!(ME && ME.spicy_mode);' in SHEET
    # подписи строк лист показывает только в обычном режиме
    assert "(spicy ? '' : '<span class=\"ds\">' + esc(r[2]) + '</span>')" in SHEET


def test_the_price_is_a_number_not_a_caption():
    assert ("const peach = n => '<span class=\"pr\">' + esc(peachNum(n)) + ' 🍑</span>';") in SHEET
    # «Раздеть» и «Горячее видео» — обе цены из таблицы /me, никаких чисел в разметке
    assert "peach(undressPeaches)" in SHEET
    assert "peach(PP('hot_circle'))" in SHEET
    for stale in ('300 🍑', '2 000 🍑', '400 🍑', '4 000 🍑'):
        assert stale not in SHEET, stale
    # цена «Раздеть» по-прежнему берётся из me, а не придумывается на странице
    assert "const undressPeaches = (ME && ME.undress_peaches) || PP('undress');" in SHEET


def test_the_duplicate_circle_row_is_only_in_the_normal_sheet():
    assert "if (!spicy) rows.push(['circle', L.hot_circle, L.hot_circle_ds," in SHEET
    assert SHEET.count("'circle'") == 1


def test_the_video_row_is_called_like_the_shop_row_in_spicy_mode():
    assert ("rows.push(spicy ? ['video', L.feat_hot_circle, '', peach(PP('hot_circle'))]" in SHEET)
    # обычный режим — та же строка, что была: то же имя и то же «за 🍑»
    assert "['video', L.hot_video, L.hot_video_ds, '<span class=\"pr\">' + esc(L.hot_peach) + '</span>']" in SHEET


def test_the_spicy_video_tap_opens_the_product_not_the_menu():
    assert "if (spicy) return inChat(() => requestMedia('hotcircle'));" in SHEET
    assert 'return inChat(openCapSheet);' in SHEET  # обычный режим не тронут


def test_the_normal_sheet_still_carries_every_old_row_and_caption():
    for key in ('L.hot_undress_ds', 'L.hot_fet_ds', 'L.hot_plots_ds', 'L.hot_call_ds',
                'L.hot_circle_ds', 'L.hot_video_ds', 'L.hot_peach'):
        assert key in SHEET, key
    assert "if (!spicy) rows.push" in SHEET  # «Горячий кружок» на месте в обычном режиме


def test_no_peach_caption_survives_the_spicy_rows():
    # «за 🍑» остаётся только в ветке обычного режима — в пошлом её нет ни в одной строке
    assert SHEET.count('L.hot_peach') == 2
