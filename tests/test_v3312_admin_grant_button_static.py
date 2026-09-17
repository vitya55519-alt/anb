"""Static regression tests for v3.31.2: a button in the admin panel to grant
premium/tokens to any user.

Owner request: «НЕ МОГУ ПОНЯТЬ ГДЕ КНОПКА ... КАК ДАТЬ ЧЕЛОВЕКУ ПРЕМИУМ».
The /grant command already existed but there was no button. Now Админка shows
«🎁 Выдать премиум/токены»: the owner sends the recipient's @username or numeric
id, then taps Premium (30 days) or Tokens (amount). Premium reuses
record_payment so the subscription + monthly credits match a real payment.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


def test_version_bumped():
    assert VERSION in ('3.43.4', '3.43.3', '3.43.2', '3.43.1', '3.43.0', '3.42.2', '3.42.1', '3.42.0', '3.41.0', '3.40.0', '3.31.1', '3.31.2', '3.31.3', '3.31.4', '3.31.5', '3.31.6', '3.31.7', '3.31.8', '3.32.0', '3.32.1', '3.33.0', '3.33.1', '3.34.0', '3.34.1', '3.35.0', '3.36.0', '3.37.0', '3.38.0', '3.39.0')


def test_admin_keyboard_has_grant_button():
    keyboard = MAIN[MAIN.index('def admin_keyboard('):]
    keyboard = keyboard[:keyboard.index('def admin_ideas_keyboard(')]
    assert "callback_data='admin:grant'" in keyboard
    assert '🎁 Выдать премиум/токены' in keyboard


def test_grant_session_state_and_clears():
    assert '_admin_grant_sessions: dict[int, dict] = {}' in MAIN
    # cleared whenever the owner re-enters the panel or cancels
    assert MAIN.count('_admin_grant_sessions.pop(message.from_user.id, None)') >= 1
    assert '_admin_grant_sessions.pop(cq.from_user.id, None)' in MAIN
    assert 'if message.from_user.id in _admin_grant_sessions:' in MAIN
    assert "await message.answer('выдача отменена'" in MAIN


def test_grant_start_handler_prompts_for_target():
    assert "@dp.callback_query(F.data == 'admin:grant')" in MAIN
    assert 'async def admin_grant_start(cq: types.CallbackQuery):' in MAIN
    handler = MAIN[MAIN.index('async def admin_grant_start('):]
    handler = handler[:handler.index('@dp.callback_query(F.data.startswith(\'admin:grantdo:premium:\'))')]
    assert "if cq.from_user.id not in ADMIN_TELEGRAM_IDS:" in handler
    assert "_admin_grant_sessions[cq.from_user.id] = {'step': 'target'}" in handler


def test_grant_premium_button_uses_record_payment_not_grant_premium():
    assert "@dp.callback_query(F.data.startswith('admin:grantdo:premium:'))" in MAIN
    assert 'async def admin_grant_do_premium(cq: types.CallbackQuery):' in MAIN
    handler = MAIN[MAIN.index('async def admin_grant_do_premium('):]
    handler = handler[:handler.index("@dp.callback_query(F.data.startswith('admin:grantdo:tokens:'))")]
    # admin-only + subscription via record_payment (grant_premium would double-grant)
    assert 'if cq.from_user.id not in ADMIN_TELEGRAM_IDS:' in handler
    assert "record_payment(target, 'premium_month', 0," in handler
    assert "provider='manual'" in handler
    assert 'grant_premium(target' not in handler
    # the user gets the same confirmation as after a real payment
    assert 'Premium активирован на 30 дней' in handler


def test_grant_tokens_flow_two_step():
    assert "@dp.callback_query(F.data.startswith('admin:grantdo:tokens:'))" in MAIN
    assert 'async def admin_grant_do_tokens_ask(cq: types.CallbackQuery):' in MAIN
    ask = MAIN[MAIN.index('async def admin_grant_do_tokens_ask('):]
    ask = ask[:ask.index('def _resolve_grant_target(')]
    assert "{'step': 'tokens', 'target': target}" in ask
    # the amount is captured in the text dispatcher and credited via add_tokens
    disp = MAIN[MAIN.index('grant_sess = _admin_grant_sessions.get(message.from_user.id)'):]
    disp = disp[:disp.index('payment_edit = _payment_method_edit_sessions.get(message.from_user.id)')]
    assert "if step == 'target':" in disp
    assert "if step == 'tokens':" in disp
    assert 'target = _resolve_grant_target(value)' in disp
    assert 'balance = add_tokens(target, count)' in disp
    assert "callback_data=f'admin:grantdo:premium:{target}'" in disp
    assert "callback_data=f'admin:grantdo:tokens:{target}'" in disp


def test_grant_text_step_is_admin_gated():
    disp = MAIN[MAIN.index('grant_sess = _admin_grant_sessions.get(message.from_user.id)'):]
    disp = disp[:disp.index('payment_edit = _payment_method_edit_sessions.get(message.from_user.id)')]
    assert 'if message.from_user.id in ADMIN_TELEGRAM_IDS and grant_sess:' in disp
