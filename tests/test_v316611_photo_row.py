"""V3.166.11 (владелец): «в 18+ добавь возможность кнопки фото, как в обычном
режиме. Тут её просто нет».

Он выбрал место — список «✨ Возможности» в чате, и поведение — как в обычном
режиме: тап открывает выбор сцены. Строка «📸 Фото» (#mediaPhoto) с V3.165.0
лежала скрытой под class="gone" в обоих режимах; здесь она возвращается первой
и на всю ширину, чтобы остальные девять строк по-прежнему складывались в пары.

Тесты статические: режут разметку и JS приложения — браузер, база и ключи не
нужны.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')

VISIBLE = ('mediaPhoto', 'featUndress', 'featPlots', 'featWardrobe', 'featGifts',
           'featFetish', 'featHot', 'featHotCircle', 'featCosplay')
GUEST = ('featDuoPhoto', 'featDuoUndress', 'featDuoVideo')
GONE = ('featQuest', 'featStory', 'featDate', 'featApt', 'featVideo')


def _sheet() -> str:
    return INDEX.split('id="capSheet"', 1)[1].split('class="cap-close"', 1)[0]


def _ids(lines: list[str]) -> list[str]:
    return [re.search(r'id="([^"]+)"', l).group(1) for l in lines]


def test_the_photo_row_is_back_in_the_sheet():
    rows = [l for l in _sheet().splitlines() if '<button id=' in l]
    assert _ids([l for l in rows if 'class="gone"' not in l]) == [*GUEST, *VISIBLE]
    assert len([l for l in rows if 'id="mediaPhoto"' in l]) == 1     # один раз, не дубль
    assert 'class="hot full"' in [l for l in rows if 'id="mediaPhoto"' in l][0]


def test_it_leads_the_single_girl_rows_and_stays_after_the_guest_ones():
    sheet = _sheet()
    for guest in ('featDuoPhoto', 'featDuoUndress'):
        assert sheet.index(f'id="{guest}"') < sheet.index('id="mediaPhoto"'), guest
    assert sheet.index('id="mediaPhoto"') < sheet.index('id="featUndress"')
    assert '.capsheet .chat-media button.full { grid-column: 1 / -1; }' in INDEX


def test_the_retired_rows_stay_hidden():
    hidden = [l for l in _sheet().splitlines() if 'class="gone"' in l]
    assert [re.search(r'id="([^"]+)"', l).group(1) for l in hidden] == list(GONE)


def test_the_tap_opens_the_scene_picker_exactly_like_the_normal_mode():
    assert "getElementById('mediaPhoto').addEventListener('click', () => openFeature('photo'))" in INDEX
    menu = MAIN[MAIN.index("if kind == 'photo':"):MAIN.index("if kind == 'hot':")]
    assert 'PHOTO_MENU_ORDER' in menu                           # тот же список сцен
    assert 'spicy_mode' not in menu                            # режим на него не влияет
    assert 'spicy_mode' not in INDEX[INDEX.index('async function openFeature'):
                                     INDEX.index('const PHOTO_MENU_CACHE')]


def test_the_row_is_named_and_explained_in_both_languages():
    assert INDEX.count('media_photo: ') == 8        # название есть во всех языках Settings
    assert INDEX.count('cap_photo: ') == 2          # пояснение — в en и ru
    assert "document.getElementById('lbMediaPhoto').textContent = L.media_photo;" in INDEX
    assert "['dsMediaPhoto', 'cap_photo']" in INDEX


def test_the_button_caption_under_possibilities_lists_photo_first():
    assert "cap_btn_sub: 'фото · раздеть · сюжеты" in INDEX
    assert "cap_btn_sub: 'photo · undress · storylines" in INDEX
