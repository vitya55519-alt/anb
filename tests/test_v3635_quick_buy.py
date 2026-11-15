"""V3.62.10: quick-buy sheet right where the user hits a limit or runs out of
peaches. V3.63.5 put a free demo row on that sheet; V3.166.2 took the demo out
again — the owner's rule is one way through the wall: base Premium.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
WEB = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_the_demo_row_and_its_endpoint_are_gone():
    assert 'async def _webapp_api_demo(' not in MAIN
    assert "add_post('/webapp/api/demo'" not in MAIN
    for dead in ('__demo', 'api/demo', 'qb_demo'):
        assert dead not in WEB, dead


def test_the_limit_answer_carries_only_the_ceiling():
    gate = MAIN[MAIN.index('def _webapp_chat_gate('):MAIN.index('def _tts_text(')]
    assert "'demo'" not in gate
    assert "'error': 'limit'," in gate
    assert "'cap'" in gate            # the sheet prints the counter's own number


def test_quick_buy_wired_into_paywalls():
    assert 'function quickBuy(' in WEB
    assert WEB.count("quickBuy('peaches'") >= 3
    assert "quickBuy('limit'" in WEB


def test_strings_in_both_languages():
    for k in ('qb_limit', 'qb_peaches', 'qb_more'):
        assert WEB.count(f'{k}:') == 2, k
    # V3.166.2: her paywall card is copy, so it lives in both dictionaries too
    for k in ('wall_h', 'wall_t', 'wall_cta'):
        assert WEB.count(f'{k}:') == 2, k
