"""V3.165.0 (задача #105): панели на карточке девушки — одна свёрнутая строка.

ТЗ владельца: каждая панель читается «метка · значение» («💍 Семейное положение ·
Свободно»), подпись «смена 500 🍑» убрана — тап по «Замужем» меняет положение
сразу за 500 🍑. В режиме «После полуночи» три шкалы (уровень близости, галерея,
характер связи) не показываются вовсе, а в «✨ Возможностях» остаются девять
строк: свидание втроём, раздеть её фото, сюжеты, гардероб, подарки, фетиши,
наедине, горячее видео, косплей.

Тесты статические: пилят разметку и JS приложения, чтобы проверка не зависела от
браузера, базы и ключей.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
LINES = INDEX.splitlines()

FOLDED = ('charRelBar', 'charCollectBar', 'charPathBar', 'charMarital', 'charPlots', 'charTrophies')
# девять строк, которые владелец оставил в «Возможностях» (плюс три гостевые —
# они видны только когда в чате вторая девушка)
SHEET_KEPT = ('featDuo', 'featUndress', 'featPlots', 'featWardrobe', 'featGifts', 'featFetish',
              'featHot', 'featHotCircle', 'featCosplay')
SHEET_GUEST = ('featDuoPhoto', 'featDuoUndress', 'featDuoVideo')
SHEET_GONE = ('mediaPhoto', 'featQuest', 'featStory', 'featDate', 'featApt', 'featVideo')


def _block(id_name: str) -> str:
    """Разметка строки: её открывающий div и несколько следующих строк."""
    at = [i for i, l in enumerate(LINES) if f'id="{id_name}"' in l and 'charblock' in l][0]
    return '\n'.join(LINES[at:at + 6])


def _slice(start: str, end: str) -> str:
    return INDEX[INDEX.index(start):INDEX.index(end)]


def test_every_panel_is_one_label_value_line():
    for id_name in FOLDED:
        block = _block(id_name)
        assert 'charblock foldable fold' in block, id_name     # свёрнута по умолчанию
        assert '<div class="foldhead">' in block, id_name
        assert 'class="pl" id=' in block and 'class="pv" id=' in block, id_name
        assert '<div class="pbody">' in block, id_name
    # один вид на все шесть строк и один селектор, прячущий содержимое
    assert '.charblock.foldable .foldhead { display: flex' in INDEX
    assert '.charblock.foldable .foldhead .pv { margin-left: auto' in INDEX
    assert '.charblock.fold .pbody { display: none; }' in INDEX
    assert '.charblock.fold .tbody' not in INDEX               # старых селекторов больше нет


def test_one_tap_and_one_reset_cover_every_fold():
    wiring = _slice('// V3.131.0: tap the row title', 'const MARITAL_KEYS')
    assert "#charview .charblock.foldable > .foldhead" in wiring
    assert "classList.toggle('fold')" in wiring
    assert wiring.count(".addEventListener('click'") == 1      # один обработчик на все строки
    page = _slice('function openCharPage(el)', 'async function openAuthor(authorId)')
    assert "querySelectorAll('#charview .charblock.foldable').forEach(el => el.classList.add('fold'))" in page
    # шкалы больше не являются дверью в sheet настроек: тап по строке открывает строку
    assert 'relBar.onclick' not in INDEX and 'pathBar.onclick' not in INDEX
    assert 'tuneBtn.onclick = () => openCharTune(c);' in INDEX


def test_the_price_moved_from_the_caption_into_the_chip():
    assert 'charMaritalPrice' not in INDEX                     # подпись «смена 500 🍑» убрана
    assert 'L.marital_confirm' not in INDEX                    # и диалог подтверждения тоже
    render = _slice('function renderMarital(c)', 'async function loadMaritalArc(')
    assert "const cost = price ? peachNum(price) + ' 🍑' : L.marital_free;" in render
    assert "' <small>· ' + esc(cost) + '</small>'" in render    # цена сидит в самом чипе
    assert "chooseMarital(c, b.dataset.ms)" in render           # тап меняет сразу
    assert '.mchip small { float: right' in INDEX
    choose = _slice('async function chooseMarital(', 'async function choosePersona(')
    assert "const wasPrice = Number(c.marital_price) || 0;" in choose
    assert "−' + peachNum(wasPrice) + ' 🍑'" in choose          # чек после списания


def test_spicy_mode_hides_the_three_tender_meters():
    helper = _slice('function showPanel(id, on)', '// V3.59.5')
    assert '!!(ME && ME.spicy_mode)' in helper
    assert "el.style.display = hide ? 'none' : ''" in helper
    assert "if (hide) el.classList.add('fold');" in helper
    page = _slice('function openCharPage(el)', 'async function openAuthor(authorId)')
    assert "showPanel('charRelBar', lvl > 0)" in page
    assert "showPanel('charPathBar', true)" in page
    assert "showPanel('charCollectBar', false)" in page
    assert "showPanel('charPathBar', true)" in _slice('function applyAxisToCard(', 'const STORY = {')
    assert "showPanel('charCollectBar', true)" in _slice('function renderCollectBar(g)', 'async function loadCollection(')
    # прямого назначения display этим трём строкам больше нигде нет — режим решает один раз
    for id_name in ('charRelBar', 'charCollectBar', 'charPathBar'):
        assert f"getElementById('{id_name}').style.display" not in INDEX, id_name
    # «Сюжеты» и «Трофеи» остаются: их владелец не просил прятать
    assert "plotsBox.style.display = ''" in page


def test_the_sheet_keeps_nine_rows_and_hides_the_retired_six():
    sheet = INDEX.split('id="capSheet"', 1)[1].split('class="cap-close"', 1)[0]
    rows = [l for l in sheet.splitlines() if '<button id=' in l or 'class="duobanner"' in l]
    ids = [re.search(r'id="([^"]+)"', l).group(1) for l in rows]
    assert [i for l, i in zip(rows, ids) if 'class="gone"' not in l] == \
        ['featDuo', *SHEET_GUEST, *SHEET_KEPT[1:]]
    assert [i for l, i in zip(rows, ids) if 'class="gone"' in l] == list(SHEET_GONE)
    assert '.capsheet .chat-media button.gone { display: none; }' in INDEX
    # спрятанные строки остаются живыми: deep link и её 18+ лист их открывают
    for id_name in SHEET_GONE:
        assert f"getElementById('{id_name}')" in INDEX, id_name


def test_the_undress_row_undresses_her_newest_photo():
    assert "getElementById('lbFeatUndress').textContent = L.hot_undress;" in INDEX
    wiring = _slice("getElementById('featUndress').addEventListener",
                    "getElementById('featDuoPhoto').addEventListener")
    assert "photoAction('undress', url, null)" in wiring
    assert "openFeature('photo')" in wiring                    # фото ещё нет — сначала сцена
    assert 'function lastHerPhotoUrl()' in INDEX
    for key in ('cap_undress:', 'cap_undress_prem:'):
        assert INDEX.count(key) == 2, key                      # en + ru
    assert "L.cap_undress((ME && ME.undress_peaches) || PP('undress'))" in INDEX
