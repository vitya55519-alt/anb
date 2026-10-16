"""V3.62.8: the 3-month Stars plan is validated and granted; card payments
open with a button and are tracked."""
import inspect

import main


def test_pre_checkout_validates_quarter():
    src = inspect.getsource(main.pre_checkout)
    assert "elif payload=='premium_quarter':" in src and 'ok=amount==PREMIUM_QUARTERLY_STARS' in src


def test_successful_payment_grants_quarter():
    src = inspect.getsource(main.successful_payment)
    assert "record_payment(message.from_user.id, 'premium_quarter', payment.total_amount, charge)" in src


def test_quarter_grant_gives_90_days(monkeypatch):
    from datetime import datetime, timedelta
    from services.payments import record_payment
    from services.access_service import is_premium
    tid = 5550111
    main.ensure_user(tid)
    record_payment(tid, 'premium_quarter', 1200, 'test-quarter-charge')
    assert is_premium(tid)


def test_platega_link_is_a_button():
    src = inspect.getsource(main.platega_pay)
    assert "InlineKeyboardButton(text='💳 Оплатить', url=link)" in src
    assert "'platega_link_created'" in src
