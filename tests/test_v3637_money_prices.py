"""V3.62.12: the shop and quick-buy show rubles/dollars, not Stars; sharper copy."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_every_product_has_money_prices():
    from services.webapp_service import api_invoice_products
    for x in api_invoice_products('ru'):
        assert x['price_rub'] >= 1 and x['price_usd'] > 0, x['id']


def test_pack_copy_names_what_peaches_buy():
    from services.webapp_service import api_invoice_products
    by = {x['id']: x for x in api_invoice_products('ru')}
    assert '«Раздеть»' in by['peach_pack_10']['description']
    assert 'не засыпает' in by['premium']['description']


def test_quick_buy_shows_money_and_opens_method_choice():
    qb = WEB[WEB.index('async function quickBuy('):WEB.index('function openPayCustom(')]
    assert 'esc(money(x))' in qb and '${x.stars} ⭐' not in qb
    assert 'openPay(id, retry)' in qb
    op = WEB[WEB.index('function openPay(id, onPaid)'):WEB.index('async function quickBuy(')]
    assert op.index('data-m="sbp"') < op.index('data-m="stars"')
