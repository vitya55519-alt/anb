"""Static regression tests for v3.27.0: the ruble shop (kassa one-click rows).

Feature bundle (V3.44.21: the rub path runs on Platega now):
- character constructor payable in rubles (200 RUB, card/SBP) alongside Stars;
- token economy: 1 token = 10 RUB, photo animation costs 5 tokens (50 RUB);
- premium payment rows behind the kassa switch — the keyboard carries light
  callback buttons and the ``platega:`` handler creates the order and sends
  the payment-page link (the payer picks the method on the page).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PLATEGA = (ROOT / 'services' / 'platega_service.py').read_text(encoding='utf-8')


def test_config_ruble_prices():
    assert 'CONSTRUCTOR_COST_RUB = max(1, int(os.getenv("CONSTRUCTOR_COST_RUB", "200")))' in CONFIG
    assert 'TOKEN_PRICE_RUB = max(1, int(os.getenv("TOKEN_PRICE_RUB", "10")))' in CONFIG
    assert 'TOKEN_PACK_SIZE = max(1, int(os.getenv("TOKEN_PACK_SIZE", "5")))' in CONFIG
    assert 'VIDEO_TOKEN_COST = max(1, int(os.getenv("VIDEO_TOKEN_COST", "5")))' in CONFIG


def test_user_model_has_token_and_credit_balances():
    block = MODELS.split('class User', 1)[1].split('\nclass ', 1)[0]
    assert 'token_balance: Mapped[int] = mapped_column(Integer, default=0)' in block
    assert 'constructor_credit: Mapped[int] = mapped_column(Integer, default=0)' in block


def test_runtime_user_balances_default_zero():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.waifu_models import Base
    import models.app_models  # noqa: F401  (register tables)
    from models.app_models import User

    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        s.add(User(telegram_id='12345', name='t'))
        s.commit()
    with Session() as s:
        row = s.query(User).first()
        assert row.token_balance == 0
        assert row.constructor_credit == 0


def test_premium_keyboard_rows_are_platega_callbacks():
    # V3.44.21: order creation is a network call, so the rows are callback
    # buttons; the platega: handler answers with the payment-page link.
    assert 'def premium_keyboard(discount: dict | None = None, telegram_id: int | None = None):' in MAIN
    assert 'def _platega_pay_button(' in MAIN
    assert "callback_data=f'platega:{product}'" in MAIN
    assert 'if PLATEGA_ENABLED:' in MAIN
    # ruble premium rows: week / month / quarter
    assert "'premium_month', PLATEGA_PREMIUM_PRICE_RUB" in MAIN
    # token buttons: 1 token and pack
    assert "'tokens_1', TOKEN_PRICE_RUB" in MAIN
    assert "f'tokens_{TOKEN_PACK_SIZE}'" in MAIN


def test_all_premium_keyboard_callers_pass_telegram_id():
    import re
    # one level of nesting is enough — calls wrap discount_info(...)
    calls = re.findall(r'premium_keyboard\((?:[^()]*|\([^()]*\))*\)', MAIN)
    call_sites = [c for c in calls if ': dict' not in c]  # skip the def line
    assert len(call_sites) >= 5
    for call in call_sites:
        assert 'telegram_id=' in call, call


def test_characters_keyboard_offers_ruble_constructor():
    assert 'def characters_keyboard(telegram_id: int | None = None):' in MAIN
    assert "'constructor_rub', CONSTRUCTOR_COST_RUB" in MAIN
    assert 'characters_keyboard(telegram_id=viewer_id)' in MAIN
    assert 'characters_keyboard(telegram_id=message.from_user.id)' in MAIN


def test_constructor_buy_consumes_ruble_credit_before_stars():
    assert 'if consume_constructor_credit(telegram_id):' in MAIN
    assert 'def consume_constructor_credit(' in MAIN
    assert 'def add_constructor_credit(' in MAIN
    # unique charge id per purchase (record_payment dedups on charge_id)
    assert 'rub_credit:{telegram_id}:{int(_time.time() * 1000)}' in MAIN
    assert '_finish_constructor(cq.message.chat.id, None, telegram_id)' in MAIN


def test_video_gate_spends_tokens_before_stars_invoice():
    assert 'def spend_tokens(telegram_id: int, amount: int) -> bool:' in MAIN
    assert 'def add_tokens(telegram_id: int, amount: int) -> int:' in MAIN
    assert 'if spend_tokens(cq.from_user.id, VIDEO_TOKEN_COST):' in MAIN
    assert "'tokens_spent'" in MAIN
    # token spend path must end BEFORE the Stars invoice is built
    gate = MAIN.split('async def _video_gate(', 1)[1]
    spend_idx = gate.find('spend_tokens(cq.from_user.id, VIDEO_TOKEN_COST)')
    invoice_idx = gate.find('send_stars_invoice')
    assert 0 < spend_idx < invoice_idx


def test_platega_callback_grants_by_product():
    assert "if product == 'constructor_rub':" in MAIN
    assert "product.startswith('tokens_')" in MAIN
    assert "add_constructor_credit(order['telegram_id'], 1)" in MAIN
    assert "int(product.split('_')[1])" in MAIN
    assert "provider='platega'" in MAIN


def test_create_order_cleans_stale_pending_duplicates():
    assert 'from datetime import datetime, timedelta' in PLATEGA
    assert 'cutoff = datetime.utcnow() - timedelta(hours=1)' in PLATEGA
    assert "PlategaOrder.status == 'pending'" in PLATEGA
    assert 'PlategaOrder.created_at < cutoff' in PLATEGA
    assert ').delete()' in PLATEGA
