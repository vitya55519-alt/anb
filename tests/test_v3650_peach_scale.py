"""V3.65.0: peaches ×100 — the one-time balance rescale, packs, the custom
tile's units (orders created before the rescale keep their value) and the
shop tiles. Same temp-DB pattern as test_v3580_money_safety."""
import os
from pathlib import Path

os.environ.setdefault("TELEGRAM_TOKEN", "123456:test-fake-token-for-static-tests-only")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-for-static-tests-only")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from sqlalchemy import delete, select, text  # noqa: E402
from models.waifu_models import Base  # noqa: E402
from services import db  # noqa: E402
from services.db import engine, SessionLocal  # noqa: E402

Base.metadata.create_all(engine)

import config  # noqa: E402
from models.app_models import PromoCode, StarTransaction, User  # noqa: E402
from services import payments  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')

# Unique id band: 9965xx.
_TIDS = []


def _user(n: int, credits: int) -> int:
    tid = 996500 + n
    _TIDS.append(tid)
    with SessionLocal() as s:
        s.add(User(telegram_id=str(tid), photo_credits=credits))
        s.commit()
    return tid


def teardown_module(module):
    with SessionLocal() as s:
        ids = [u.id for u in s.scalars(select(User).where(User.telegram_id.in_([str(t) for t in _TIDS])))]
        s.execute(delete(StarTransaction).where(StarTransaction.user_id.in_(ids)))
        s.execute(delete(User).where(User.id.in_(ids)))
        s.execute(delete(PromoCode).where(PromoCode.code == 'SCALE7'))
        s.commit()


def test_scale_constants():
    assert config.PEACH_SCALE == 100
    assert config.CHAT_PHOTO_PEACH_COST == 200
    assert config.DAILY_GIFT_DAY_AMOUNT == 100
    assert config.PEACH_PACK_CREDITS == {'peach_pack_10': 1000, 'peach_pack_30': 3000, 'peach_pack_100': 10000}
    # the bulk discount told as a gift: 125⭐ buys 2500 at the small rate, 350⭐ buys 7000
    assert config.PEACH_PACK_BONUS == {'peach_pack_10': 0, 'peach_pack_30': 500, 'peach_pack_100': 3000}
    assert config.REFERRAL_BONUS_TIERS[0] == (3, 1000, 0)
    assert config.PEACH_CUSTOM_UNIT == 100


def test_env_override_stays_in_old_units(monkeypatch):
    monkeypatch.setenv('CHAT_PHOTO_PEACH_COST', '3')
    assert config._peach_env('CHAT_PHOTO_PEACH_COST', 2) == 300
    monkeypatch.setenv('MARITAL_CHANGE_PEACHES', '0')
    assert config._peach_env('MARITAL_CHANGE_PEACHES', 5, 0) == 0


def test_rescale_runs_once():
    with engine.begin() as conn:
        conn.execute(text('DROP TABLE IF EXISTS app_migrations'))
    tid = _user(1, 7)
    zero = _user(2, 0)
    with SessionLocal() as s:
        s.add(PromoCode(code='SCALE7', credits=5, max_activations=0, activated_count=0, active=True))
        s.commit()
    db._rescale_peaches()
    db._rescale_peaches()  # a restart / second instance: no double multiply
    assert payments.get_photo_credits(tid) == 700
    assert payments.get_photo_credits(zero) == 0
    with SessionLocal() as s:
        assert s.scalar(select(PromoCode).where(PromoCode.code == 'SCALE7')).credits == 500


def test_packs_and_single_credit_grant_scaled():
    tid = _user(3, 0)
    payments.record_payment(tid, 'peach_pack_30', 125, 'charge-v3650-pack')
    assert payments.get_photo_credits(tid) == 3000
    payments.record_payment(tid, 'photo', 25, 'charge-v3650-photo')
    assert payments.get_photo_credits(tid) == 3100
    assert payments.consume_photo_credit(tid) is True
    assert payments.get_photo_credits(tid) == 3000


def test_custom_order_counts_units():
    # an order key minted before the rescale («peach_custom_5» = 5 old peaches)
    # grants the same value after it: 500 new peaches
    tid = _user(4, 0)
    payments.record_payment(tid, 'peach_custom_5', 25, 'charge-v3650-custom')
    assert payments.get_photo_credits(tid) == 500


def test_custom_units_from_app_body():
    ns = {'PEACH_CUSTOM_UNIT': 100}
    src = MAIN[MAIN.index('def _custom_peach_units('):MAIN.index('async def _webapp_api_demo(')]
    exec(src, ns)
    units = ns['_custom_peach_units']
    assert units({'peaches': 500}) == 5
    assert units({'peaches': 550}) == 6       # rounded up to whole units
    assert units({'peaches': 1}) == 1
    assert units({'amount': 7}) == 7          # a page cached before the rescale
    assert units({'peaches': 'x'}) == 1
    assert units(None) == 1


def test_shop_tiles():
    from services import webapp_service
    items = {x['id']: x for x in webapp_service.api_invoice_products('ru')}
    assert items['peach_pack_10']['title'] == '1 000 персиков'
    assert items['peach_pack_100']['badge'] == '+3 000 🎁'
    assert '7 000 + 3 000 в подарок' in items['peach_pack_100']['description']
    assert 'badge' not in items['peach_pack_10']
    assert items['peach_custom']['unit'] == 100
    assert webapp_service.WEBAPP_PICTURE_COST_CREDITS == 1000
    # the app custom tile sends new-unit peaches, prices come from the tile
    assert "payVia('peach_custom', b.dataset.m, b, { peaches: n })" in INDEX
    assert 'const stars = units * item.stars;' in INDEX
