"""Static regression tests for v3.31.0: owner-configured payment methods go
public + manual premium/token grants by @username.

Two owner-reported gaps:
- a method switched to «active» in the admin panel never appeared in the
  user-facing payment keyboard (only the admin list showed it);
- there was no way to grant premium/tokens after an off-bot payment — the
  owner receives money externally and must activate the purchase manually.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
USERS = (ROOT / 'services' / 'user_service.py').read_text(encoding='utf-8')
METHODS = (ROOT / 'services' / 'payment_method_service.py').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


def test_version_bumped():
    assert VERSION in ('3.30.9', '3.31.0', '3.31.1', '3.31.2', '3.31.3', '3.31.4')


def test_user_row_keeps_username():
    # The Bot API cannot look users up by username, so we persist the last
    # seen one to resolve /grant targets.
    assert 'username: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)' in MODELS
    assert 'def ensure_user(telegram_id: int, name: str | None = None, language_code: str | None = None,' in USERS
    assert 'username: str | None = None) -> int:' in USERS
    assert 'if username and user.username != username:' in USERS
    assert 'def find_user_by_username(username: str) -> int | None:' in USERS
    assert 'func.lower(User.username) == clean' in USERS


def test_public_payment_methods_helper():
    # Only active, ready-to-show external methods reach the user keyboard.
    assert 'def public_payment_methods() -> list[PaymentMethodView]:' in METHODS
    assert "if method.status != 'active' or method.method_type not in {'link', 'qr', 'wallet_pay'}:" in METHODS
    assert 'if method.method_type == \'link\' and not method.external_url:' in METHODS


def test_premium_keyboard_shows_active_methods():
    # V3.31.0 fix: the admin-panel methods must render for users.
    assert 'for method in public_payment_methods():' in MAIN
    assert "rows.append([InlineKeyboardButton(text=f'💳 {method.display_name}', url=method.external_url)])" in MAIN
    assert "callback_data=f'paymethod:{method.id}'" in MAIN


def test_paymethod_handler_sends_qr_and_instructions():
    assert "@dp.callback_query(F.data.startswith('paymethod:'))" in MAIN
    assert 'async def paymethod_show(cq: types.CallbackQuery):' in MAIN
    handler = MAIN[MAIN.index('@dp.callback_query(F.data.startswith(\'paymethod:\'))'):]
    handler = handler[:handler.index('@dp.callback_query(F.data == \'cosplay:start\')')]
    assert 'method.qr_photo_file_id' in handler
    assert 'send_photo' in handler
    # the manual-grant hint closes the off-bot payment loop
    assert 'он активирует покупку вручную' in handler


def test_grant_command_resolves_username_and_grants():
    assert "@dp.message(Command('grant'))" in MAIN
    assert 'async def admin_grant(message: types.Message, command: CommandObject):' in MAIN
    assert 'def _resolve_grant_target(ref: str) -> int | None:' in MAIN
    assert 'find_user_by_username(clean)' in MAIN
    body = MAIN[MAIN.index('@dp.message(Command(\'grant\'))'):]
    body = body[:body.index('@dp.callback_query(F.data == \'admin:ideas\')')]
    # admin-only
    assert 'if message.from_user.id not in ADMIN_TELEGRAM_IDS:' in body
    # premium branch: record_payment creates/extends the subscription like a
    # real payment; grant_premium on top would double-grant credits+days
    assert "record_payment(target, 'premium_month', 0," in body
    assert 'grant_premium(target' not in body
    assert "provider='manual'" in body
    # tokens branch: counted top-up + user notification
    assert 'balance = add_tokens(target, count)' in body
    # username is remembered on every chat message and on /start
    assert 'username=message.from_user.username' in MAIN
    # command is listed for admins
    assert "types.BotCommand(command='grant'" in MAIN
