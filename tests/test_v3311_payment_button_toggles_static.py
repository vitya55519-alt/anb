"""Static regression tests for v3.31.1: owner can remove payment buttons.

Owner request: «И ДАЙ ВОЗМОЖНОСТЬ МНЕ УБИРАТЬ КНОПКИ». The built-in FreeKassa
rows of the user payment keyboard were hard-coded — only custom methods could
be hidden. Now every built-in row is backed by an admin-managed 'builtin'
PaymentMethod switch (Админка → Способы оплаты → Статус), so any button can be
removed from the user menu without a deploy.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
METHODS = (ROOT / 'services' / 'payment_method_service.py').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()

BUILTIN_KEYS = ('freekassa_rub', 'freekassa_sbp', 'freekassa_usd', 'freekassa_tokens')


def test_version_bumped():
    assert VERSION in ('3.43.7', '3.43.6', '3.43.5', '3.43.4', '3.43.3', '3.43.2', '3.43.1', '3.43.0', '3.42.2', '3.42.1', '3.42.0', '3.41.0', '3.40.0', '3.31.0', '3.31.1', '3.31.2', '3.31.3', '3.31.4', '3.31.5', '3.31.6', '3.31.7', '3.31.8', '3.32.0', '3.32.1', '3.33.0', '3.33.1', '3.34.0', '3.34.1', '3.35.0', '3.36.0', '3.37.0', '3.38.0', '3.39.0')


def test_builtin_rows_are_seeded_and_system():
    # The four built-in keyboard rows exist as default methods and cannot be
    # deleted (is_system), only switched off.
    assert '"builtin": "Встроенная кнопка меню оплаты",' in METHODS
    for key in BUILTIN_KEYS:
        block = METHODS[METHODS.index(f'"{key}": {{'):]
        block = block[:block.index('},')]
        assert '"method_type": "builtin"' in block
        assert '"is_system": True' in block
        assert '"status": "active"' in block


def test_is_button_enabled_helper():
    # Missing row keeps the default (behaviour never breaks before seeding);
    # an existing row is visible only while status='active'.
    assert 'def is_button_enabled(method_key: str, default: bool = True) -> bool:' in METHODS
    assert 'ensure_default_payment_methods()' in METHODS[METHODS.index('def is_button_enabled'):]
    assert 'return str(row.status or "disabled") == "active"' in METHODS


def test_premium_keyboard_gates_builtin_rows():
    assert 'public_payment_methods, is_button_enabled,' in MAIN
    keyboard = MAIN[MAIN.index('def premium_keyboard('):]
    keyboard = keyboard[:keyboard.index('def adult_keyboard(')]
    for key in BUILTIN_KEYS:
        assert f"if is_button_enabled('{key}'):" in keyboard
    # the legacy (no telegram_id) branch obeys the same switches
    legacy = keyboard[keyboard.index('elif FREEKASSA_ENABLED:'):]
    assert "is_button_enabled('freekassa_rub')" in legacy
    assert "is_button_enabled('freekassa_usd')" in legacy


def test_admin_summary_explains_builtin_switch():
    assert "elif method.method_type == 'builtin':" in MAIN
    assert 'видна пользователям, пока статус «включён»' in MAIN
