"""V3.48.2 static checks: character cards paginate 6 per page in both segments.

Owner request: «сделай чтобы карточки персонажей были по 6 штук на странице,
персиковый сад и сообщество». The grid renders client-side from the cached
``/webapp/api/characters`` payload in two segments — «🍑 Персиковый сад»
(the official roster) and «👥 Сообщество» (constructor personas). Both must
show exactly 6 character cards per page with a prev/next control, and the
community search must reset to page 1.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_page_size_is_six_per_segment():
    assert 'const CHAR_PAGE_SIZE = 6;' in INDEX
    assert 'let CHAR_PAGE = 0;' in INDEX
    # the slice drives the grid, not the full filtered list
    assert 'const pageItems = shown.slice(CHAR_PAGE * CHAR_PAGE_SIZE, CHAR_PAGE * CHAR_PAGE_SIZE + CHAR_PAGE_SIZE);' in INDEX
    assert 'const cards = pageItems.map(c => {' in INDEX


def test_pager_rendered_and_control_handlers():
    assert 'renderCharPager(pages);' in INDEX
    assert 'function renderCharPager(pages) {' in INDEX
    # the control hides itself when everything fits on one page
    assert "if (pages <= 1) { p.style.display = 'none'; p.innerHTML = ''; return; }" in INDEX
    assert "id=\"pagerPrev\"" in INDEX
    assert "id=\"pagerNext\"" in INDEX
    # prev/next mutate CHAR_PAGE then re-render the cached grid
    assert 'if (CHAR_PAGE > 0) { CHAR_PAGE--; renderCharacters(CHARS);' in INDEX
    assert 'if (CHAR_PAGE < pages - 1) { CHAR_PAGE++; renderCharacters(CHARS);' in INDEX


def test_page_resets_on_segment_search_and_fresh_load():
    # a segment switch lands on page 1
    assert "if (CHAR_SEG !== 'community') CHAR_QUERY = '';\n  CHAR_PAGE = 0;" in INDEX
    # typing a new community search resets to page 1
    assert "CHAR_QUERY = e.target.value || '';\n  CHAR_PAGE = 0;" in INDEX
    # a fresh character load starts on page 1
    assert 'CHAR_PAGE = 0; // V3.48.2: a fresh character load starts on page 1' in INDEX


def test_out_of_range_page_is_clamped():
    assert 'if (CHAR_PAGE > pages - 1) CHAR_PAGE = pages - 1;' in INDEX
    assert 'if (CHAR_PAGE < 0) CHAR_PAGE = 0;' in INDEX
