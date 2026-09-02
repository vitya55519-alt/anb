"""Static regression tests for v3.27.0: ruble shop (FreeKassa one-click buttons).

Feature bundle:
- character constructor payable in rubles (200 RUB, card/SBP) alongside Stars;
- token economy: 1 token = 10 RUB, photo animation costs 5 tokens (50 RUB);
- premium payment is ONE click — the keyboard button itself is a url-button
  that opens the FreeKassa payment page (order created upfront);
- payment-system badges on the buttons (SBP / Visa / Mastercard), not plain text.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
FK = (ROOT / 'services' / 'freekassa_service.py').read_text(encoding='utf-8')


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


def test_premium_keyboard_is_one_click_url_buttons_with_badges():
    assert 'def premium_keyboard(discount: dict | None = None, telegram_id: int | None = None):' in MAIN
    assert 'def _fk_pay_button(' in MAIN
    assert 'link = freekassa_service.payment_url(order_id, str(amount), currency=currency)' in MAIN
    assert 'if FREEKASSA_ENABLED and telegram_id:' in MAIN
    # ruble premium: SBP + card badges
    assert "⚡СБП / карта" in MAIN  # SBP / card
    assert "'premium_month', FREEKASSA_PREMIUM_PRICE_RUB" in MAIN
    # USD premium: Visa + Mastercard badges
    assert "Ⓥ Visa / Ⓜ Mastercard" in MAIN
    assert "currency='USD'" in MAIN
    # token buttons: 1 token and pack
    assert "'tokens_1', TOKEN_PRICE_RUB" in MAIN
    assert "f'tokens_{TOKEN_PACK_SIZE}'" in MAIN
    # legacy callback buttons preserved for callers without telegram_id
    assert 'elif FREEKASSA_ENABLED:' in MAIN
    assert "callback_data='fk:premium'" in MAIN
    assert "callback_data='fk:premium_usd'" in MAIN


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
    assert 'freekassa_credit:{telegram_id}:{int(_time.time() * 1000)}' in MAIN
    assert '_finish_constructor(cq.message, None, telegram_id)' in MAIN


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


def test_fk_notify_grants_by_product():
    assert "if product == 'constructor_rub':" in MAIN
    assert "product.startswith('tokens_')" in MAIN
    assert 'add_constructor_credit(order[\'telegram_id\'], 1)' in MAIN
    assert "int(product.split('_')[1])" in MAIN
    assert "provider='freekassa'" in MAIN


def test_create_order_cleans_stale_pending_duplicates():
    assert 'from datetime import datetime, timedelta' in FK
    assert 'cutoff = datetime.utcnow() - timedelta(hours=1)' in FK
    assert 'FreeKassaOrder.status == \'pending\'' in FK
    assert 'FreeKassaOrder.created_at < cutoff' in FK
    assert ').delete()' in FK
