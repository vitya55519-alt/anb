from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PAYMENTS = (ROOT / 'services' / 'payments.py').read_text(encoding='utf-8')


def test_admin_panel_exposes_premium_toggle():
    assert "'admin:premium_toggle'" in MAIN
    block = MAIN[MAIN.index('def admin_keyboard()'):]
    assert 'admin:premium_toggle' in block.split('\ndef ')[0]


def test_admin_keyboard_does_not_index_admin_ids_set():
    # ADMIN_TELEGRAM_IDS is a set; indexing it ([0]) raises TypeError and
    # silently breaks /admin rendering.
    assert 'ADMIN_TELEGRAM_IDS[0]' not in MAIN


def test_admin_premium_toggle_handler_is_admin_only():
    block = MAIN[MAIN.index("async def admin_premium_toggle("):MAIN.index("async def admin_cards(")]
    assert 'ADMIN_TELEGRAM_IDS' in block
    assert 'grant_premium(' in block
    assert 'revoke_premium(' in block
    assert 'is_premium(' in block


def test_payments_grant_revoke_helpers():
    assert 'def grant_premium(' in PAYMENTS
    assert 'def revoke_premium(' in PAYMENTS
    grant_block = PAYMENTS[PAYMENTS.index('def grant_premium('):PAYMENTS.index('def revoke_premium(')]
    # Admin grant creates a real 30-day subscription and photo credits.
    assert 'plan="premium"' in grant_block
    assert 'status="active"' in grant_block
    assert 'PREMIUM_MONTHLY_PHOTO_CREDITS' in grant_block
    # Revoke deactivates instead of deleting history.
    revoke_block = PAYMENTS[PAYMENTS.index('def revoke_premium('):]
    assert "'cancelled'" in revoke_block
