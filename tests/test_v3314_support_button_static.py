"""Static regression tests for v3.31.4: «Support the project» button in the menu.

Owner request (after v3.31.3 put the donation link in the welcome + a weekly
reminder): also surface a prominent «Support the project» button in the bot's
main menu / settings, not only in the welcome.

The main menu is a ReplyKeyboardMarkup — Telegram forbids URL buttons there —
so the reply button opens the shared donation appeal whose CTA is the CloudTips
URL button. The /settings inline menu additionally gets a real one-tap URL
button. Both reuse services/donation_service.py so the copy never diverges from
the welcome / weekly reminder wording.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
UI_LANG = (ROOT / 'services' / 'ui_lang.py').read_text(encoding='utf-8')
DONATION = (ROOT / 'services' / 'donation_service.py').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()

LINK = 'https://pay.cloudtips.ru/p/7afc7b16'


def test_version_bumped():
    assert VERSION in ('3.31.3', '3.31.4', '3.31.5', '3.31.6', '3.31.7', '3.31.8', '3.32.0', '3.32.1', '3.33.0', '3.33.1', '3.34.0', '3.34.1')


def test_support_key_added_to_reply_menu():
    # RU/EN label pair exists (dual-language, ru != en) ...
    assert "'support': ('💖 Поддержать проект', '💖 Support the project')," in UI_LANG
    # ... and the button rides as its own full-width row in the main keyboard.
    assert "['support']," in UI_LANG
    rows = UI_LANG[UI_LANG.index('MAIN_KB_ROWS = ['):UI_LANG.index('LEVEL_NAMES_EN')]
    assert "'support'" in rows


def test_donation_service_exposes_reusable_button():
    # extracted so /settings can embed the very same URL button
    assert 'def donation_button(lang: str = RU) -> InlineKeyboardButton:' in DONATION
    assert 'url=DONATION_LINK' in DONATION
    assert 'return InlineKeyboardMarkup(inline_keyboard=[[donation_button(lang)]])' in DONATION
    # the link still points at CloudTips and stays env-configurable
    assert f'DONATION_LINK = os.getenv("DONATION_LINK", "{LINK}").strip()' in CONFIG


def test_support_button_handler_wired():
    # dual-language match (required by test_v3220) + reuses the shared copy
    assert "@dp.message(F.text.in_(kb_pair('support')))" in MAIN
    assert 'async def support_button(message: types.Message):' in MAIN
    body = MAIN[MAIN.index('async def support_button(message: types.Message):'):]
    body = body[:body.index('# V3.21.0: first-row discovery buttons')]
    assert 'donation_service.donation_appeal(lang)' in body
    assert 'donation_service.donation_keyboard(lang)' in body
    assert 'ensure_user(' in body
    assert 'lang = user_lang(message.from_user.id)' in body


def test_settings_menu_has_url_button():
    block = MAIN[MAIN.index("@dp.message(Command('settings'))"):]
    block = block[:block.index("@dp.message(Command('profile'))")]
    # a real one-tap URL button now rides alongside the rituals toggle
    assert 'donation_service.donation_button(lang)' in block
    # the rituals toggle is untouched (test_v3210 depends on it)
    assert "callback_data='toggle:rituals'" in block


def test_support_button_registered_before_catchall():
    # reply-button handlers must precede the generic text catch-all
    assert MAIN.index("kb_pair('support')") < MAIN.index('@dp.message(F.text)\n')
