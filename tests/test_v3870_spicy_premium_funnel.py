"""V3.87.0: nude / lingerie / private / hot-circle media are gated so free
peaches never buy them. V3.165.0 (#104) moved the door from Premium to money:
every 18+ frame is sold to anyone for bought peaches (paid_only), Premium only
decides what is free — and these pins keep both surfaces honest."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PS = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
WEB = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_spicy_scene_set_covers_lingerie_and_nude():
    assert 'PREMIUM_SPICY_SCENES = frozenset(SEEDREAM_ADULT_SCENES | ADULT_SCENES)' in PS
    assert 'def spicy_needs_premium(request: PhotoRequest) -> bool:' in PS
    assert "'lingerie'" in PS.split('SEEDREAM_ADULT_SCENES = ')[1].split('\n')[0]
    assert "'nude'" in PS.split('ADULT_SCENES = ')[1].split('\n')[0]


def test_every_spicy_route_is_gated():
    # app chat text requests
    i = MAIN.index('def _chat_photo_gate(')
    # V3.165.0: a character window used to be the slice (3200 grew twice) — take
    # the function itself, so the gate can gain lines without breaking the pin.
    gate = MAIN[i:MAIN.index('\ndef ', i + 10)]
    assert "return 'spicy'" in gate
    assert gate.index("return 'spicy'") < gate.index("return 'peaches'")
    assert "'spicy': (" in MAIN
    # V3.87.0 put «Наедине» and the hot circle behind Premium. V3.165.0 (#104,
    # owner) opened both to a man without Premium: what still has to stop a
    # render is money — the bought peaches must cover the price before a pixel.
    assert "if kind == 'hot' and telegram_id not in ADMIN_TELEGRAM_IDS and not is_premium(telegram_id):" in MAIN
    assert 'get_paid_peaches(telegram_id) < get_category_cost(cat_id)' in MAIN
    assert 'if telegram_id not in ADMIN_TELEGRAM_IDS and get_paid_peaches(telegram_id) < HOT_CIRCLE_PEACH_COST:' in MAIN
    # bot photo keyboard and bot «Наедине»
    assert "if not is_premium(telegram_id) and spicy_needs_premium(request):" in MAIN
    i = MAIN.index('async def private_photo_generate(')
    assert "CHAT_PHOTO_BLOCK_TEXT['spicy']" in MAIN[i:i + 1500]
    # every block counts as a paywall view (admin funnel «видели предложение»)
    assert MAIN.count("'product': 'spicy_") >= 3


def test_app_opens_the_premium_sheet():
    assert "(kind === 'limit' || kind === 'voice' || kind === 'spicy') ? trialFirst.concat(['premium_week', 'premium'])" in INDEX
    assert "if (j.photo_block === 'spicy') {" in INDEX
    assert "if (j.error === 'premium_required') { quickBuy('spicy', () => requestMedia(kind, scene, opts)); return; }" in INDEX
    assert "quickBuy(action === 'undress' ? 'undress' : 'spicy', () => photoAction(action, mediaUrl, btn));" in INDEX
    assert INDEX.count('qb_spicy:') >= 2 and INDEX.count('sc_prem_only:') >= 2


def test_shop_sells_it():
    # V3.165.0 (#104): the old line promised «18+ картинки» as a Premium feature.
    # The honest one says what Premium still buys — the free frame of the day.
    start = WEB.index('def api_shop(')
    block = WEB[start:WEB.index('    return {', start)]
    assert "'откровенные фото: «Наедине», «Раздеть», косплей — один кадр даром каждый день'" in block


def test_free_selfie_then_undress_tease():
    # «покажи себя» stays a free selfie (not a spicy scene)…
    assert "'покажи себя'" in PS
    # …and her first photo in a chat is followed by «🔥 Раздеть её» on that photo
    assert 'function undressTease(mediaUrl) {' in INDEX
    assert 'undressTease(j.photo_url);' in INDEX
    assert "if (kind === 'photo') undressTease(j.url);" in INDEX
    assert INDEX.count('undress_tease_btn:') >= 2
