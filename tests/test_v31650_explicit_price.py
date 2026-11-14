"""V3.165.0: один ценник на откровенный кадр — 300 🍑 в обоих режимах.

Владелец правил цену трижды за день («200 → 400 → 300»), и в коде осталось
три независимых числа: «Наедине»/косплей по 200 🍑, «Раздеть» 400 🍑, кружок
4 000 🍑. Теперь все они берутся из одной константы, а экраны Mini App читают
цену из /webapp/api/me, а не хранят её в разметке.

Важно про имена переменных окружения: Railway до сих пор держит старые
PRIVATE_PHOTO_PEACH_COST=2, UNDRESS_PEACH_COST=4, HOT_CIRCLE_PEACH_COST=40 в
старой единице (×100). Если бы новые цены читались из тех же имён, прежние
ценники молча вернулись бы после ближайшего рестарта. Поэтому у цены В3.165.0
новые имена с суффиксом _V165.
"""
from pathlib import Path

import config

ROOT = Path(__file__).resolve().parents[1]
WEBAPP = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
SERVICE = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')


def test_one_price_for_every_explicit_frame():
    assert config.EXPLICIT_PHOTO_PEACH_COST == 300
    assert config.PRIVATE_PHOTO_PEACH_COST == config.EXPLICIT_PHOTO_PEACH_COST
    assert config.COSPLAY_PHOTO_PEACH_COST == config.EXPLICIT_PHOTO_PEACH_COST
    assert config.UNDRESS_PEACH_COST == config.EXPLICIT_PHOTO_PEACH_COST


def test_photo_by_fetish_costs_the_same_frame_price():
    # The fetish plate is billed through the «Наедине» price, so it can never
    # drift away from 300 🍑 on its own.
    assert 'EXPLICIT_PHOTO_PEACH_COST' in SERVICE or 'PRIVATE_PHOTO_PEACH_COST' in SERVICE
    assert config.PRIVATE_PHOTO_PEACH_COST == 300


def test_series_is_four_frames_700_and_hot_circle_2000():
    assert config.PHOTO_SERIES_FRAMES == 4
    assert config.PHOTO_SERIES_PEACH_COST == 700
    # 4 frames bought one by one: the series must be the cheaper path, and the
    # saving is what the caption sells.
    assert config.PHOTO_SERIES_PEACH_COST < config.PHOTO_SERIES_FRAMES * config.EXPLICIT_PHOTO_PEACH_COST
    assert config.HOT_CIRCLE_PEACH_COST == 2000


def test_new_prices_ignore_the_legacy_env_names():
    start = CONFIG.index('EXPLICIT_PHOTO_PEACH_COST =')
    end = CONFIG.index('COSPLAY_PHOTO_PEACH_COST =', start) + len('COSPLAY_PHOTO_PEACH_COST = _peaches("COSPLAY_PHOTO_PEACHES_V165", EXPLICIT_PHOTO_PEACH_COST)')
    block = CONFIG[start:end]
    for legacy in ('_peach_env("PRIVATE_PHOTO_PEACH_COST"', '_peach_env("UNDRESS_PEACH_COST"',
                   '_peach_env("COSPLAY_PHOTO_PEACH_COST"'):
        assert legacy not in block
    for new_name in ('PRIVATE_PHOTO_PEACHES_V165', 'UNDRESS_PEACHES_V165', 'COSPLAY_PHOTO_PEACHES_V165'):
        assert new_name in block
    assert '_peaches("HOT_CIRCLE_PEACHES_V165", 2000)' in CONFIG
    assert '_peaches("PHOTO_SERIES_PEACHES_V165", 700)' in CONFIG


def test_me_carries_the_price_table():
    assert "'peach_prices'" in SERVICE
    for key in ('explicit', 'private', 'cosplay', 'undress', 'series', 'series_frames',
                'circle', 'hot_circle', 'hot_pass_day'):
        assert f"'{key}':" in SERVICE[SERVICE.index("'peach_prices'"):]


def test_shop_has_one_hot_video_row_and_the_three_new_products():
    start = SERVICE.index('def api_shop(')
    block = SERVICE[start:SERVICE.index('    return {', start)]
    rows = block[block.index('items = ['):]
    assert rows.count('HOT_CIRCLE_PEACH_COST') == 1, '«Тайное видео» и «Горячий кружок» были дублями'
    assert 'EXPLICIT_PHOTO_PEACH_COST' in rows   # фото по фетишу
    assert 'PHOTO_SERIES_PEACH_COST' in rows     # серия кадров
    # V3.165.0 (#104): the pass is one table for bot + app, so the shop reads all
    # three terms from it — the old single «HOT_PASS_DAY_PEACHES» row is gone.
    assert 'HOT_PASS_DAY_PEACHES' not in rows
    for term in ('day', 'week', 'month'):
        assert f"HOT_PASS_PRODUCTS['{term}']" in rows
    assert '(с Premium)' not in rows, '18+ товары продаются за персики, тег «с Premium» врёт'


def test_page_no_longer_invents_peach_prices():
    assert '|| 400' not in WEBAPP, 'старая цена «Раздеть» зашита в разметку'
    assert '|| 4000' not in WEBAPP, 'старая цена кружка зашита в разметку'
    assert 'function PP(key)' in WEBAPP
    # the grouping helper is the one the page has always had — an arrow const,
    # not a second declaration of the same name.
    assert "const peachNum = n =>" in WEBAPP
    assert WEBAPP.count('peachNum = n =>') == 1
    assert "cap_hot_circle: n =>" in WEBAPP
    assert '4 000 🍑' not in WEBAPP
    assert 'refreshPriceCaps();' in WEBAPP[WEBAPP.index('async function loadMe('):]
