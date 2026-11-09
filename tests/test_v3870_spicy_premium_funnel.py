"""V3.87.0: nude / lingerie / private / hot-circle media are Premium-only, so
free peaches never buy them — every such tap opens the Premium pay sheet."""
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
    gate = MAIN[i:i + 3200]  # V3.93.0: the free-photo tiers made the gate longer
    assert "return 'spicy'" in gate
    assert gate.index("return 'spicy'") < gate.index("return 'peaches'")
    assert "'spicy': (" in MAIN
    # app media picker / «Наедине» / hot circle
    assert "kind in ('hot', 'hotcircle')" in MAIN
    # bot photo keyboard and bot «Наедине»
    assert "if not is_premium(telegram_id) and spicy_needs_premium(request):" in MAIN
    i = MAIN.index('async def private_photo_generate(')
    assert "CHAT_PHOTO_BLOCK_TEXT['spicy']" in MAIN[i:i + 1500]
    # every block counts as a paywall view (admin funnel «видели предложение»)
    assert MAIN.count("'product': 'spicy_") >= 3


def test_app_opens_the_premium_sheet():
    assert "(kind === 'limit' || kind === 'voice' || kind === 'spicy') ? trialFirst.concat(['premium_week', 'premium'])" in INDEX
    assert "if (j.photo_block === 'spicy') {" in INDEX
    assert "if (j.error === 'premium_required') { quickBuy('spicy', () => requestMedia(kind, scene)); return; }" in INDEX
    assert "quickBuy(action === 'undress' ? 'undress' : 'spicy', () => photoAction(action, mediaUrl, btn));" in INDEX
    assert INDEX.count('qb_spicy:') >= 2 and INDEX.count('sc_prem_only:') >= 2


def test_shop_sells_it():
    assert "'откровенные фото: в белье, обнажённые, «Раздеть», «Наедине», 18+ картинки'" in WEB


def test_free_selfie_then_undress_tease():
    # «покажи себя» stays a free selfie (not a spicy scene)…
    assert "'покажи себя'" in PS
    # …and her first photo in a chat is followed by «🔥 Раздеть её» on that photo
    assert 'function undressTease(mediaUrl) {' in INDEX
    assert 'undressTease(j.photo_url);' in INDEX
    assert "if (kind === 'photo') undressTease(j.url);" in INDEX
    assert INDEX.count('undress_tease_btn:') >= 2
