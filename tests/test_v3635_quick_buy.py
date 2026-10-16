"""V3.62.10: quick-buy sheet right where the user hits a limit or runs out of peaches."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
WEB = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_demo_endpoint_registered():
    assert 'async def _webapp_api_demo(' in MAIN
    assert "add_post('/webapp/api/demo', _webapp_api_demo)" in MAIN


def test_limit_body_carries_demo_flag():
    assert "'error': 'limit', 'demo': demo" in MAIN or "'error':'limit','demo':demo" in MAIN


def test_quick_buy_wired_into_paywalls():
    assert 'function quickBuy(' in WEB
    assert WEB.count("quickBuy('peaches'") >= 3
    assert "quickBuy('limit'" in WEB


def test_strings_in_both_languages():
    for k in ('qb_limit', 'qb_peaches', 'qb_more', 'qb_demo', 'qb_demo_on'):
        assert WEB.count(f'{k}:') == 2, k
