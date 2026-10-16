"""V3.62.11: Premium is reachable from the bot's main menu again."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI_LANG = (ROOT / 'services' / 'ui_lang.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def test_premium_row_in_main_menu():
    from services.ui_lang import MAIN_KB_ROWS
    assert ['premium'] in MAIN_KB_ROWS
    assert MAIN_KB_ROWS.index(['premium']) == MAIN_KB_ROWS.index(['credits']) + 1


def test_premium_button_has_handler():
    assert "@dp.message(F.text.in_(kb_pair('premium')))" in MAIN
