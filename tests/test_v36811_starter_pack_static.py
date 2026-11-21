"""V3.168.1: «Стартовый пак 15 ⭐» (Stars + Platega) и Premium-only бесплатный кадр «Фантазии»."""
from pathlib import Path

import config

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
PAY = (ROOT / 'services' / 'payments.py').read_text(encoding='utf-8')
WS = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
WR = (ROOT / 'services' / 'weekly_report.py').read_text(encoding='utf-8')


def test_config_prices_and_payment_dicts():
    assert config.STARTER_PACK_STARS == 15
    assert config.STARTER_PACK_RUB == 30
    assert config.STARTER_PACK_PEACHES == 5 * config.PEACH_SCALE
    for d in (config.PEACH_PACK_STARS, config.PEACH_PACK_RUB, config.PEACH_PACK_CREDITS):
        assert 'starter_pack' in d
    assert config.PEACH_PACK_STARS['starter_pack'] == 15
    assert config.PEACH_PACK_RUB['starter_pack'] == 30


def test_server_gates_and_events():
    assert 'def starter_pack_eligible' in PAY
    assert "'starter_pack_bought'" in PAY
    assert MAIN.count("product_id == 'starter_pack' and not await asyncio.to_thread(starter_pack_eligible") == 2
    assert "product == 'starter_pack' and not starter_pack_eligible" in MAIN
    assert "payload == 'starter_pack'" in MAIN
    assert "'starter_pack_checkout'" in MAIN
    assert "'starter_pack_eligible'" in WS and "'starter_pack'" in WS
    assert 'starter_pack_bought' in WR


def test_client_starter_first_and_hidden_from_grid():
    assert "x.id !== 'starter_pack'" in SPA
    assert "const want = starterFirst.concat(want0)" in SPA
    assert "ME.starter_pack_eligible && !ME.premium" in SPA


def test_wish_free_frame_is_premium_only_and_window_opens():
    ws = (ROOT / 'services' / 'wish_service.py').read_text(encoding='utf-8')
    assert 'is_premium' in ws.split('def free_available')[1].split('def cost')[0]
    assert "quickBuy('wish', wishSend)" in SPA
    assert SPA.count("quickBuy('wish', wishSend)") == 2
    assert "kind === 'wish'" in SPA
