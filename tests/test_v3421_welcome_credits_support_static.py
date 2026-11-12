"""Static regression tests for v3.42.1: the welcome screen gains a
«🍑 Пополнить персики» (photo credits) button and a «👥 Поддержка» button.

Owner request: «сделай кнопку пополнить персики, в welcome и кнопку поддержка».

Both were reply-keyboard-only before. The welcome screen is an inline
keyboard, so this adds two inline callbacks — ``credits:open`` reuses the
existing app-shop entry (``_send_app_entry``) and ``support:open`` arms the
same pending-ticket flow as the reply button — and surfaces them as full-width
rows in ``_welcome_back_rows``.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
UI_LANG = (ROOT / 'services' / 'ui_lang.py').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


def test_version_bumped():
    assert VERSION in ('3.44.4', '3.44.3', '3.43.7', '3.43.6', '3.43.5', '3.43.4', '3.43.3', '3.43.2', '3.43.1', '3.43.0', '3.42.2', '3.42.1', '3.42.0', '3.41.0')


# ── the two new rows live on the welcome keyboard ─────────────────────────

def test_credits_and_support_left_the_welcome_keyboard():
    # V3.42.1 surfaced «Персики» and «Поддержка» on the welcome screen; the
    # V3.148.0 ТЗ moved the whole shop back into the app, so the welcome
    # keyboard is one button again. The labels stay alive for the legacy reply
    # keyboard, /support and the app deep links.
    assert 'def _welcome_back_rows(' not in MAIN
    rows = MAIN[MAIN.index('def _app_row(lang: str):'):]
    rows = rows[:rows.index('\ndef ', 10)]
    assert "callback_data='credits:open'" not in rows
    assert "text=kb_label('support', lang), url=f'https://t.me/{SUPPORT_BOT_USERNAME}'" not in MAIN
    assert "@dp.callback_query(F.data == 'credits:open')" in MAIN
    assert "url=f'https://t.me/{SUPPORT_BOT_USERNAME}'" in MAIN


def test_credits_and_support_labels_are_the_localized_pairs():
    # V3.43.5: owner shortened the button to the plain «Персики» label.
    assert "'credits': ('🍑 Персики', '🍑 Peaches')," in UI_LANG
    assert "'support': ('👥 Поддержка', '👥 Support')," in UI_LANG


# ── credits:open reuses the app-shop entry ────────────────────────────────

def test_credits_open_callback_opens_the_chat_shop():
    assert "@dp.callback_query(F.data == 'credits:open')" in MAIN
    assert 'async def credits_open(cq: types.CallbackQuery):' in MAIN
    handler = MAIN[MAIN.index('async def credits_open(cq: types.CallbackQuery):'):]
    handler = handler[:handler.index('\nasync def ', 10)]
    assert 'await cq.answer()' in handler
    # V3.95.0: the in-chat shop (pay links + the app button) instead.
    assert '_send_peach_shop(cq.message, cq.from_user)' in handler


# ── support: the welcome callback is gone, the bot link replaced it ────────

def test_support_open_callback_is_gone():
    # V3.43.0: support moved to @Anna67901support_bot — the ticket callback
    # would only dead-end now that the buttons carry a t.me url instead.
    assert "@dp.callback_query(F.data == 'support:open')" not in MAIN
    assert 'async def support_open(cq: types.CallbackQuery):' not in MAIN


def test_reply_support_button_points_at_the_support_bot():
    # the reply-keyboard handler survives but hands over a url button
    assert "@dp.message(F.text.in_(kb_pair('support')))" in MAIN
    assert 'async def support_button(message: types.Message):' in MAIN
    body = MAIN[MAIN.index('async def support_button(message: types.Message):'):]
    body = body[:body.index('async def _deliver_support_message(')]
    assert "url=f'https://t.me/{SUPPORT_BOT_USERNAME}'" in body
    assert '_support_pending[' not in body
    assert '👥 написать в поддержку' in body and '👥 contact support' in body
