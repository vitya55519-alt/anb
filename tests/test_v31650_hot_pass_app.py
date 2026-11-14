"""V3.165.0 (#104 / задача 110): «Сутки без стеснения» переехали из бота в
приложение и из «2 фото в сутки» в связку кадров. Одна таблица цен за спиной у
обоих входов, тратится ровно то, что куплено."""
import re
from pathlib import Path

from services import private_photo_service as pp
from config import HOT_PASS_FREE_DAILY, HOT_PASS_PRODUCTS

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
WEB = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
WEBAPP = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def _hotpass_block():
    start = MAIN.index('async def _webapp_api_hotpass(')
    return MAIN[start:MAIN.index('\nasync def ', start + 10)]


def test_one_price_table_behind_both_doors():
    # the bot keyboard and the app endpoint read the same three rows
    assert MAIN.count('HOT_PASS_PRODUCTS.get(duration)') == 2
    assert "product['peaches'], product['days'], product['frames']" in MAIN
    assert 'app.router.add_post(\'/webapp/api/hotpass\', _webapp_api_hotpass)' in MAIN
    # the shop and /me show the table itself, not a copy of the numbers
    assert "'hot_pass_products': [dict(HOT_PASS_PRODUCTS[k], id=k) for k in ('day', 'week', 'month')]" in WEB
    assert re.search(r"HOT_PASS_PRODUCTS\[k\], id=k.*\n.*'hot_pass': _hot_pass_me_fields", WEB, re.S)


def test_the_pass_is_sold_for_bought_peaches_only():
    block = _hotpass_block()
    assert 'spend_peaches(telegram_id, cost, paid_only=True)' in block
    assert "'error': 'insufficient_peaches', 'cost': cost, 'status': 402" in block
    # 18+ first, then money: the consent check runs before a peach is spent
    assert block.index("{'error': 'consent'") < block.index('spend_peaches(')
    # an admin does not pay, but still gets the frames he clicked for
    assert 'admin = telegram_id in ADMIN_TELEGRAM_IDS' in block
    assert '0 if admin else cost' in block


def test_the_bundle_is_spent_frame_by_frame(tmp_path, monkeypatch):
    from sqlalchemy import select
    from models.app_models import Base, User
    from services.db import SessionLocal, engine
    from services.user_service import ensure_user

    Base.metadata.create_all(engine)
    tid = 316510401
    uid = ensure_user(tid)
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.id == uid))
        user.achievements = ''
        user.private_photo_used = 0
        user.cosplay_photo_used = 0
        user.private_photo_date = None
        user.cosplay_photo_date = None
        user.hot_pass_frames = None
        session.commit()

    day = HOT_PASS_PRODUCTS['day']
    pp.activate_hot_pass(tid, day['days'], day['frames'])
    used = 0
    while pp.consume_free_private_photo(tid, 'lingerie'):
        used += 1
        assert used <= day['frames'], 'пропуск отдал больше кадров, чем в нём куплено'
    assert used == day['frames']
    assert pp.get_private_photo_usage(tid)['hot_pass_left'] == 0
    # a second tap on a running pass stacks frames instead of restarting the clock
    expires_before = pp.get_private_photo_usage(tid)['hot_pass_expires']
    pp.activate_hot_pass(tid, day['days'], day['frames'])
    usage = pp.get_private_photo_usage(tid)
    assert usage['hot_pass_left'] == day['frames']
    assert usage['hot_pass_expires'] >= expires_before


def test_a_pass_from_the_old_model_keeps_its_daily_quota():
    # shipped before this release: no frame counter at all, so it stays «2 в
    # сутки суммарно» until it expires — his money is not re-priced after the fact.
    from sqlalchemy import select
    from models.app_models import Base, User
    from services.db import SessionLocal, engine
    from services.user_service import ensure_user

    Base.metadata.create_all(engine)
    tid = 316510402
    uid = ensure_user(tid)
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.id == uid))
        user.achievements = ''
        user.private_photo_used = 0
        user.cosplay_photo_used = 0
        user.private_photo_date = None
        user.cosplay_photo_date = None
        user.hot_pass_frames = None
        session.commit()
    from datetime import datetime, timedelta
    with SessionLocal() as session:
        session.scalar(select(User).where(User.id == uid)).hot_pass_expires = datetime.utcnow() + timedelta(days=1)
        session.commit()
    assert pp.get_private_photo_usage(tid)['hot_pass_left'] == HOT_PASS_FREE_DAILY
    assert pp.consume_free_private_photo(tid, 'lingerie')
    assert pp.consume_free_private_photo(tid, 'cosplay')
    assert not pp.consume_free_private_photo(tid, 'roleplay')


def test_me_says_what_the_pass_still_owes():
    start = WEB.index('def _hot_pass_me_fields(')
    block = WEB[start:WEB.index('\ndef ', start + 10)]
    assert "'active': bool(usage.get('hot_pass_active'))" in block
    assert "'frames': int(usage.get('hot_pass_left') or 0)" in block
    assert "return {'active': False, 'frames': 0, 'expires': None}" in block


def test_the_wizard_prices_the_frame_the_way_the_backend_charges_it():
    step = WEBAPP[WEBAPP.index('function hotShowPriceStep('):WEBAPP.index('async function requestSeries(')]
    assert "const pass = (ME && ME.hot_pass) || {};" in step
    assert 'pass.active && pass.frames > 0' in step
    # with a pass running the single frame says «по пропуску», not a peach number
    assert 'L.ser_free' in step
    assert "document.getElementById('serPass')" in step
    assert 'buyHotPass(passBtn)' in step
    # the day card is the server's row: its frames and price are read, never typed
    assert "find(p => p.id === 'day')" in step
    assert 'dayPass.frames' in step and 'dayPass.peaches' in step
    # and no invented number sits anywhere in this step
    for forbidden in ('|| 300', '|| 500', '|| 700', '|| 4', "'500 🍑'"):
        assert forbidden not in step, forbidden


def test_buying_the_pass_does_not_throw_him_out_of_the_wizard():
    start = WEBAPP.index('async function buyHotPass(')
    buy = WEBAPP[start:WEBAPP.index('function hotSelectCategory', start)]
    assert "document.getElementById('serOne')" in buy
    assert 'hotShowPriceStep();' in buy
    assert 'renderFeature(_hotData);' in buy
    assert "const r = await fetch('/webapp/api/hotpass?init_data='" in buy


def test_the_pass_strings_exist_in_both_languages():
    en = WEBAPP[WEBAPP.index('const L_EN'):WEBAPP.index('const L_RU')]
    ru = WEBAPP[WEBAPP.index('const L_RU'):]
    for key in ('pass_h', 'pass_sub', 'pass_on', 'pass_day', 'pass_week', 'pass_month',
                'pass_need', 'pass_done', 'pass_fail', 'ser_free'):
        assert re.search(rf"\b{key}:", en), key
        assert re.search(rf"\b{key}:", ru), key
    assert "ser_free: 'по пропуску'" in ru
