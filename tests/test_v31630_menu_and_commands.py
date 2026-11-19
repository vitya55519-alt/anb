"""V3.163.0 — owner ТЗ of 13 Nov 2026: «через палочку видно все команды бота.
Сделай так, чтобы их видел только я как админ. Добавь это меню у пользователя.
Третье: добавь „Поддержать проект“ и тот пост с поддержкой».

1. The slash list is no longer global: Telegram's default and all-private-chats
   command scopes are cleared at startup, and the full list installs only into
   each ADMIN_TELEGRAM_IDS chat. The handlers stay, so a command typed by hand
   still works — it is simply never offered to a stranger.
2. Support and the donation post remain in the menu. On 19 Nov the owner
   removed stories, collection and features from the menu, not their handlers.
"""
import os
from pathlib import Path

import pytest

os.environ.setdefault('TELEGRAM_TOKEN', '123456:test-fake-token-for-static-tests-only')
os.environ.setdefault('GEMINI_API_KEY', 'x')

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
UI = (ROOT / 'services' / 'ui_lang.py').read_text(encoding='utf-8')

ADMIN_ID = 916300001
USER_ID = 916300002


def _main(monkeypatch):
    import main
    monkeypatch.setattr(main, 'PUBLIC_BASE_URL', 'https://example.test')
    monkeypatch.setattr(main, 'ADMIN_TELEGRAM_IDS', {ADMIN_ID})
    return main


# ── 1. the command list is the owner's ─────────────────────────────────────
def test_the_command_list_is_never_installed_globally():
    boot = MAIN[MAIN.index('async def main():'):]
    assert 'await bot.set_my_commands(public_commands)' not in boot
    assert 'await bot.delete_my_commands(scope=_scope)' in boot
    assert 'types.BotCommandScopeDefault()' in boot
    assert 'types.BotCommandScopeAllPrivateChats()' in boot


def test_the_full_list_survives_only_in_the_admin_chat_scope():
    boot = MAIN[MAIN.index('async def main():'):]
    i = boot.index('for admin_id in ADMIN_TELEGRAM_IDS:')
    assert 'scope=types.BotCommandScopeChat(chat_id=admin_id)' in boot[i:]
    assert "public_commands + [types.BotCommand(command='admin'" in boot[i:]


def test_the_commands_a_user_needed_stay_registered():
    """Hiding the list must not break the flows behind it — /start especially."""
    for cmd in ('start', 'menu', 'support', 'paysupport', 'collection', 'stories', 'features'):
        assert f"Command('{cmd}'" in MAIN, cmd


# ── 2. the reduced menu keeps all other buttons ────────────────────────────
def test_the_user_menu_keeps_only_the_requested_rows():
    from services.ui_lang import menu_rows
    assert menu_rows(False) == [
        ['app'], ['gallery'], ['alarm'], ['reminder'], ['support'], ['donate'],
    ]


def test_removed_menu_keys_keep_their_legacy_labels_and_routes():
    from services.ui_lang import KB_LABELS, menu_rows
    for key in ('stories', 'collection', 'features', 'support', 'donate'):
        assert key in KB_LABELS, key
    for key in ('stories', 'collection', 'features'):
        assert not any(key in row for row in menu_rows(True)), key
    for key in ('support', 'donate'):
        assert any(key in row for row in menu_rows(False)), key
    assert KB_LABELS['donate'][0] == '💖 Поддержать проект'


@pytest.mark.parametrize('lang', ['ru', 'en'])
@pytest.mark.parametrize('tid', [USER_ID, ADMIN_ID])
def test_removed_buttons_are_absent_from_both_keyboards(monkeypatch, lang, tid):
    from services.ui_lang import kb_label
    main = _main(monkeypatch)
    monkeypatch.setattr(main, 'user_lang', lambda _: lang)
    inline = main.menu_markup(tid, lang).inline_keyboard
    reply = main.main_keyboard(tid == ADMIN_ID, tid).keyboard
    removed = {kb_label(key, lang) for key in ('stories', 'collection', 'features')}
    expected = [[kb_label(key, lang)] for key in
                ('app', 'gallery', 'alarm', 'reminder', 'support', 'donate')]
    for rows in (inline, reply):
        assert [[button.text for button in row] for row in rows[:6]] == expected
        assert not removed & {button.text for row in rows for button in row}
    callbacks = {b.callback_data for row in inline for b in row if b.callback_data}
    assert not {'quest:list', 'menu:collection', 'onboard:abilities'} & callbacks
    assert {'menu:support', 'donate:open'} <= callbacks


def test_the_kitchen_is_still_not_in_his_menu(monkeypatch):
    main = _main(monkeypatch)
    user = {b.text for row in main.menu_markup(USER_ID).inline_keyboard for b in row}
    admin = {b.text for row in main.menu_markup(ADMIN_ID).inline_keyboard for b in row}
    for kitchen in ('🍑 Персики', '🚀 Премиум', '🛠 Админка', '💰 Партнёрская программа'):
        assert kitchen in admin and kitchen not in user, kitchen


def test_every_new_callback_has_a_handler():
    for cb in ('menu:collection', 'menu:support', 'quest:list', 'onboard:abilities', 'donate:open'):
        assert f"F.data == '{cb}'" in MAIN, cb


def test_the_reply_keyboard_twins_answer_the_same_labels():
    for key in ('stories', 'collection', 'features', 'support', 'donate'):
        assert f"kb_pair('{key}')" in MAIN, key


# ── 3. the screens themselves ───────────────────────────────────────────────
def test_the_collection_report_is_built_for_the_tapper():
    """cq.message is the bot's own bubble — its from_user is the bot, so the
    menu row must read cq.from_user or every user would see Anna's collection."""
    body = MAIN[MAIN.index("async def menu_collection_cb("):]
    body = body[:body.index("@dp.message(Command('menu'))")]
    assert '_collection_lines(cq.from_user.id)' in body
    assert 'cq.message.from_user' not in body
    assert 'await message.answer(_collection_lines(message.from_user.id))' in MAIN


def test_the_support_row_opens_the_support_bot_not_the_command_wall():
    body = MAIN[MAIN.index("async def menu_support_cb("):]
    body = body[:body.index("@dp.message(Command('menu'))")]
    assert "url=f'https://t.me/{SUPPORT_BOT_USERNAME}'" in body
    assert 'legal_service.support_text' not in body


def test_the_donation_post_is_one_source_for_both_paths(monkeypatch):
    main = _main(monkeypatch)
    ru_text, ru_kb = main._donation_post('ru')
    en_text, en_kb = main._donation_post('en')
    assert ru_text.startswith('💖 Поддержать проект') and 'СБП' in ru_text
    assert en_text.startswith('💖 Support the project')
    assert [b.text for b in ru_kb.inline_keyboard[0]] == ['💸 50 ₽', '💸 100 ₽', '💸 500 ₽']
    assert 'donation_service.donation_amounts_keyboard(lang)' in MAIN


def test_hidden_commands_are_not_recommended_to_users_as_the_only_path():
    """The hints a user actually sees must offer the button, not a list he
    can no longer open."""
    assert '«👥 Поддержка» в меню' in MAIN
