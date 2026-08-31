"""Static + runtime regression tests for v3.26.2: BIGINT freekassa telegram_id.

Production incident: creating a FreeKassa order crashed with
psycopg.errors.NumericValueOutOfRange because freekassa_orders.telegram_id
was a 32-bit INTEGER while the owner's Telegram ID (8 267 849 550) exceeds
2^31-1. Fix: the model column is BigInteger and services/db.py widens the
live Postgres column to BIGINT on startup.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
DB = (ROOT / 'services' / 'db.py').read_text(encoding='utf-8')


def test_model_uses_bigint_for_freekassa_telegram_id():
    import_line = MODELS.split('from sqlalchemy import', 1)[1].split('\n', 1)[0]
    assert 'BigInteger' in import_line
    block = MODELS.split('class FreeKassaOrder', 1)[1].split('\nclass ', 1)[0]
    assert 'telegram_id: Mapped[int] = mapped_column(BigInteger' in block


def test_db_widens_live_postgres_column():
    assert 'ALTER TABLE freekassa_orders ALTER COLUMN telegram_id TYPE BIGINT' in DB
    assert '_widen_freekassa_telegram_id()' in DB
    assert "engine.dialect.name != 'postgresql'" in DB


def test_runtime_insert_big_telegram_id():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.waifu_models import Base
    import models.app_models  # noqa: F401  (register table)
    from models.app_models import FreeKassaOrder

    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        s.add(FreeKassaOrder(telegram_id=8267849550, product='premium_month', amount='499'))
        s.commit()
    with Session() as s:
        row = s.query(FreeKassaOrder).first()
        assert row.telegram_id == 8267849550
        assert row.status == 'pending'