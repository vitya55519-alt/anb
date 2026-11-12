"""V3.62.11: Premium is reachable from the bot's main menu again."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI_LANG = (ROOT / 'services' / 'ui_lang.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def test_premium_row_in_main_menu():
    # V3.149.0: the peaches/Premium rows moved to the admin block of the menu.
    from services.ui_lang import menu_rows
    rows = menu_rows(True)
    assert ['premium'] in rows
    assert rows.index(['premium']) == rows.index(['credits']) + 1


def test_premium_button_has_handler():
    assert "@dp.message(F.text.in_(kb_pair('premium')))" in MAIN
