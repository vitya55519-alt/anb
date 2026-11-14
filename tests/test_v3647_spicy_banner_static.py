"""V3.165.0 (Задача 100): the «пошлый режим» banner and its explainer modal are
gone — the mode is now chosen on the entry screen, and the release is explicit
that no second switch may exist anywhere (Settings row, main-screen banner,
«Персонажи» tile).

This file used to pin the banner's place under the channel banner and the one
switch it shared with Settings. It now pins the opposite: the banner is dead,
the entry screen took over, and the screens the owner deleted stay deleted.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def test_the_old_banner_and_modal_are_dead():
    for dead in ('id="spicyBanner"', 'id="spicymodal"', 'id="spicyVal"',
                 'id="rowSpicy"', 'renderSpicyBanner', 'openSpicyModal', 'toggleSpicy',
                 'spicy_banner:', 'spicy_m_text:'):
        assert dead not in INDEX, dead


def test_the_honest_card_and_feedback_block_are_dead():
    # «Честно о нас» + «Будем рады вашим пожеланиям» — removed with this release.
    for dead in ('id="honestmodal"', 'id="fbText"', 'id="fbSend"', 'openHonest',
                 'maybeShowHonest', 'hn_title:', 'fb_title:'):
        assert dead not in INDEX, dead
    # the wishes endpoint stays reachable for the bot side, but the app no
    # longer posts to it from a card that is not drawn anymore
    assert "fetch('/webapp/api/feedback" not in INDEX


def test_entry_screen_is_the_only_mode_choice():
    assert '<div id="modeScreen">' in INDEX
    assert 'id="msCards"' in INDEX
    assert 'function openModeScreen()' in INDEX
    assert 'async function chooseMode(on)' in INDEX
    # the tap is the choice: no «Продолжить» button, the card itself is the CTA
    # and it lands on the heroine roster.
    assert "showTab('characters');" in INDEX
    assert "ms_btn: 'Выбрать героиню'" in INDEX
    # two cards: the ordinary mode and «После полуночи»
    assert "modeCard(false) + modeCard(true)" in INDEX
    assert "ms_spicy_t: 'ПОСЛЕ ПОЛУНОЧИ'" in INDEX
    assert "ms_normal_t: 'Обычный режим'" in INDEX
    # the owner's own pictures, with a glyph fallback while a file is missing
    assert "/webapp/art/mode_normal" in INDEX and "/webapp/art/mode_spicy" in INDEX
    assert r"classList.add(\'nopic\')" in INDEX
    # the ceiling inside the card caption is the number /me sent, not a 30
    # typed a second time into the page
    assert "ME.explicit_cap" in INDEX


def test_screen_opens_on_every_entry_but_not_over_a_deep_link():
    entry = INDEX[INDEX.index('function maybeModeEntry(chars)'):]
    entry = entry[:entry.index('\n}', 10)]
    assert "sp.get('mode') === '1'" in entry
    assert "openModeScreen(); return;" in entry
    assert 'maybeDeepOpenChat(chars);' in entry
    # ...and the boot chain really goes through it
    assert ']).then(() => maybeModeEntry(CHARS));' in INDEX


def test_the_bot_no_longer_offers_a_switch():
    # the bot's old toggle answers with the app link instead of flipping
    handler = MAIN[MAIN.index("F.data == 'toggle:spicy'"):]
    handler = handler[:handler.index('\n@dp.callback_query', 10)]
    assert 'webapp?mode=1' in handler
    assert 'spicy_mode=' not in handler
