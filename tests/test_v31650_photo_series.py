"""V3.165.0 (#104 / задача 112): «Серия кадров» — продукт целиком.

Владелец: «завести продукт целиком: кнопка, списание, генерация 4 кадров,
доставка», подпись — «выгоднее, чем по отдельности» (4 × 300 = 1200 🍑 против
700 🍑 за сет).

Что фиксируют эти проверки:
 • серия — это N свежих рендеров одной сцены, а не N копий одного кадра: в
   режиме серии выключены и дневный даром-кадр, и цена одного кадра, и кэш, и
   накопленный запас («она отдаёт одно и то же»);
 • платится один раз за весь сет и только купленными персиками; если кадр не
   получился, списывается доля, а не полная цена;
 • экран берёт оба числа из /webapp/api/me и сам ничего не выдумывает.
"""
from pathlib import Path

import config

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
WEBAPP = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def _run_block() -> str:
    return MAIN[MAIN.index('async def _series_run('):MAIN.index('def _series_deliver_frame(')]


def test_the_set_is_four_frames_and_cheaper_than_the_sum():
    assert config.PHOTO_SERIES_FRAMES == 4
    assert config.PHOTO_SERIES_PEACH_COST == 700
    assert config.PHOTO_SERIES_PEACH_COST < config.PHOTO_SERIES_FRAMES * config.EXPLICIT_PHOTO_PEACH_COST


def test_the_product_is_a_button_a_bill_a_render_and_a_delivery():
    assert "app.router.add_post('/webapp/api/series', _webapp_api_series)" in MAIN
    run = _run_block()
    assert 'for _ in range(PHOTO_SERIES_FRAMES)' in run
    assert 'series=True' in run, 'each frame must render in series mode'
    assert '_series_deliver_frame' in run
    assert 'paid_only=True' in run, 'бонусные персики не оплачивают четыре рендера'


def test_a_series_frame_spends_nothing_on_its_own():
    hot = MAIN[MAIN.index('async def _webapp_media_hot('):MAIN.index('async def _webapp_media_circle(')]
    assert 'series: bool = False' in hot
    assert 'series else _hot_frame_is_free' in hot, 'даром-кадр дня не входит в сет'
    assert 'cached = None if series else cache_get' in hot, 'сет — это разные кадры'
    assert 'None if (series or telegram_id in ADMIN_TELEGRAM_IDS) else pool_get' in hot
    assert hot.count('if not free_used and not series:') == 2, 'плата за кадр вне сцены сета'


def test_an_incomplete_set_is_billed_by_what_arrived():
    run = _run_block()
    assert 'PHOTO_SERIES_PEACH_COST * delivered // PHOTO_SERIES_FRAMES' in run
    assert 'if delivered and telegram_id not in ADMIN_TELEGRAM_IDS:' in run
    assert 'delivered >= PHOTO_SERIES_FRAMES' in run


def test_the_page_offers_both_prices_from_the_server_table():
    step = WEBAPP[WEBAPP.index('function hotShowPriceStep('):WEBAPP.index('async function requestSeries(')]
    for key in ("PP('explicit')", "PP('series_frames')", "PP('series')"):
        assert key in step
    assert 'L.ser_sub(frames, set, one * frames)' in step
    assert "requestSeries(hotScene())" in step
    # В3.165.0 (#103): the screens never invent a peach price.
    assert '|| 300' not in step and '|| 700' not in step and '|| 4' not in step


def test_the_app_waits_for_the_whole_set():
    assert "fetch('/webapp/api/series?init_data='" in WEBAPP
    assert 'waitForSeriesPhotos(CHAT.id' in WEBAPP
    wait = WEBAPP[WEBAPP.index('function waitForSeriesPhotos('):]
    assert "m.media_kind === 'photo'" in wait
    assert 'n - base >= total' in wait
    assert 'loadChatHistory(characterId)' in wait
    assert 'L.ser_part' in wait, 'неполный сет — честная подпись, а не вечный кружок'


def test_the_series_strings_exist_in_both_languages():
    en = WEBAPP[WEBAPP.index('const L_EN'):WEBAPP.index('const L_RU')]
    ru = WEBAPP[WEBAPP.index('const L_RU'):WEBAPP.index('const L_OV')]
    for key in ('ser_h', 'ser_title', 'ser_sub', 'ser_one', 'ser_set', 'ser_wait',
                'ser_part', 'ser_slow', 'ser_need', 'ser_busy'):
        assert f'{key}:' in en, key
        assert f'{key}:' in ru, key
    assert 'выгоднее, чем по отдельности' in ru
