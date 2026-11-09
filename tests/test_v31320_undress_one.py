"""V3.132.0 — «Раздеть» one photo for 50 ₽ without Premium + tidy photo buttons."""
from pathlib import Path

from models.app_models import Base
from services import undress_credits as uc
from services.db import engine

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
HTML = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
PAY = (ROOT / 'services' / 'payments.py').read_text(encoding='utf-8')


def test_credit_add_and_spend():
    Base.metadata.create_all(engine)
    tg = 990001234
    while uc.spend(tg):
        pass
    assert uc.balance(tg) == 0 and not uc.spend(tg)
    assert uc.add(tg) == 1
    assert uc.spend(tg) and uc.balance(tg) == 0


def test_catalogue_has_undress_one_but_not_in_shop_grid():
    from services import webapp_service
    item = next(p for p in webapp_service.api_invoice_products('ru') if p['id'] == 'undress_one')
    assert item['payload'] == 'undress_one' and item['stars'] > 0
    assert 'credits' not in item  # the shop grid only shows items with credits


def test_payment_paths_wired():
    assert "payload=='undress_one'" in MAIN and 'is_adult_confirmed(query.from_user.id)' in MAIN
    assert "if payload == 'undress_one':" in MAIN
    assert "elif product == 'undress_one':" in MAIN  # Platega confirmation
    assert "'undress_one': 'undress_one'" in MAIN  # app order mapping
    assert 'undress_credits.add(telegram_id, 1)' in PAY


def test_gate_uses_credit_and_spends_only_on_success():
    gate = MAIN.split('    def _gate():', 1)[1].split('    uid, err, pay = await', 1)[0]
    assert "return uid, None, 'credit'" in gate
    assert gate.index('is_adult_confirmed') < gate.index("'credit'")
    deliver = MAIN.split('    def _deliver():', 1)[1].split('    out = await', 1)[0]
    assert "pay == 'credit'" in deliver and 'undress_credits.spend(telegram_id)' in deliver


def test_buttons_layout_and_quickbuy():
    assert 'grid-template-columns: 1fr 1fr' in HTML and 'grid-column: 1 / -1' in HTML
    assert "kind === 'undress' ? ['undress_one']" in HTML
    assert "quickBuy(action === 'undress' ? 'undress' : 'spicy'" in HTML
