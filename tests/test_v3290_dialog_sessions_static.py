# -*- coding: utf-8 -*-
"""V3.29.0: dialog wizards persist in the dialog_sessions table.

Static pins guard the wiring; runtime tests exercise DialogStore against a
throwaway sqlite engine (SessionLocal is monkeypatched, the production DB is
never touched).
"""
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
DB = (ROOT / 'services' / 'db.py').read_text(encoding='utf-8')
STORE = (ROOT / 'services' / 'dialog_store.py').read_text(encoding='utf-8')


# ------------------------------------------------------------------ static pins
def test_dialog_session_model_defined():
    assert 'class DialogSession(Base):' in MODELS
    assert '__tablename__ = "dialog_sessions"' in MODELS
    assert "UniqueConstraint('telegram_id', 'session_key'" in MODELS
    for col in ('telegram_id', 'session_key', 'payload_json', 'created_at', 'updated_at'):
        assert col in MODELS


def test_db_imports_dialog_session():
    assert 'DialogSession' in DB


def test_main_wires_dialog_stores():
    assert 'from services import dialog_store' in MAIN
    assert "_custom_drafts = dialog_store.DialogStore('custom_drafts')" in MAIN
    assert "_pending_adult_photo = dialog_store.DialogStore('pending_adult_photo', codec='photo_request')" in MAIN
    assert "_photo_offer_pending = dialog_store.DialogStore('photo_offer_pending')" in MAIN
    assert "_photo_offer_expression = dialog_store.DialogStore('photo_offer_expression')" in MAIN
    assert "_fantasy_pending = dialog_store.DialogStore('fantasy_pending')" in MAIN
    assert "_constructor_sessions = dialog_store.DialogStore('constructor_sessions')" in MAIN


def test_legacy_in_memory_declarations_gone():
    for legacy in (
        '_custom_drafts: dict[int, dict] = {}',
        '_pending_adult_photo: dict[int, PhotoRequest] = {}',
        '_photo_offer_pending: dict[int, float] = {}',
        '_photo_offer_expression: dict[int, str | None] = {}',
        '_fantasy_pending: dict[int, tuple[str, int]] = {}',
        '_constructor_sessions: dict[int, dict] = {}',
    ):
        assert legacy not in MAIN


def test_nested_mutations_rewritten_to_write_back():
    # In-place nested mutations would be lost by the write-through facade.
    assert "cons['params'][key] = value" not in MAIN
    assert "_custom_drafts.setdefault" not in MAIN
    assert "cons['params'] = params" in MAIN
    assert "_custom_drafts[cq.from_user.id] = draft" in MAIN


def test_startup_prunes_stale_sessions():
    assert 'dialog_store.cleanup_stale_sessions()' in MAIN
    assert MAIN.index('dialog_store.cleanup_stale_sessions()') < MAIN.index("logger.info('AnnaBot started')")


def test_dialog_store_facade_shape():
    assert 'class DialogStore:' in STORE
    assert 'class _PersistentDict(MutableMapping):' in STORE
    assert 'MAX_PAYLOAD_CHARS' in STORE
    assert '__b64__' in STORE
    assert "codec: str = 'json'" in STORE


# ------------------------------------------------------------------ runtime
@pytest.fixture()
def store_db(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from models import app_models
    from services import dialog_store

    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    app_models.Base.metadata.create_all(engine)
    monkeypatch.setattr(dialog_store, 'SessionLocal', sessionmaker(bind=engine))
    return dialog_store


def test_json_store_round_trip(store_db):
    store = store_db.DialogStore('constructor_sessions')
    uid = 111
    assert uid not in store
    store[uid] = {'params': {'name': 'Luna'}, 'step': 2}
    assert uid in store
    cons = store.get(uid)
    assert cons['step'] == 2
    assert cons['params']['name'] == 'Luna'
    cons['step'] = 3  # write-through must flush to the DB row
    fresh = store_db.DialogStore('constructor_sessions')
    assert fresh.get(uid)['step'] == 3
    assert fresh.pop(uid)['step'] == 3
    assert uid not in fresh
    assert fresh.pop(uid, None) is None
    with pytest.raises(KeyError):
        fresh[uid]


def test_scalar_and_none_values(store_db):
    pending = store_db.DialogStore('photo_offer_pending')
    expr = store_db.DialogStore('photo_offer_expression')
    pending[42] = 1717000000.5
    assert pending.get(42, 0) == pytest.approx(1717000000.5)
    expr[42] = None  # stored null; membership must still be True
    assert 42 in expr
    assert expr.pop(42, None) is None
    assert 42 not in expr


def test_tuple_stored_as_list_unpacks(store_db):
    fantasy = store_db.DialogStore('fantasy_pending')
    fantasy[7] = ('charge-1', 150)
    charge, amount = fantasy[7]
    assert charge == 'charge-1' and amount == 150
    del fantasy[7]
    assert 7 not in fantasy


def test_bytes_round_trip(store_db):
    store = store_db.DialogStore('constructor_sessions')
    store[5] = {'params': {}, 'step': 0, 'face_bytes': b'\xff\xd8jpeg-bytes'}
    cons = store.get(5)
    assert cons['face_bytes'] == b'\xff\xd8jpeg-bytes'


def test_photo_request_codec_round_trip(store_db):
    from services.photo_service import PhotoRequest

    store = store_db.DialogStore('pending_adult_photo', codec='photo_request')
    req = PhotoRequest(scene='bedroom', mood='bold', pack_outfits=('outfit-a',))
    store[99] = req
    got = store.pop(99)
    assert isinstance(got, PhotoRequest)
    assert got.scene == 'bedroom' and got.mood == 'bold'
    assert got.pack_outfits == ('outfit-a',)


def test_cleanup_removes_only_stale_sessions(store_db):
    from datetime import datetime, timedelta

    from models.app_models import DialogSession

    store = store_db.DialogStore('custom_drafts')
    store[1] = {'color': 'black'}
    store[2] = {'color': 'red'}
    with store_db.SessionLocal() as s:
        row = s.query(DialogSession).filter(DialogSession.telegram_id == 1).first()
        row.updated_at = datetime.utcnow() - timedelta(hours=48)
        s.commit()
    removed = store_db.cleanup_stale_sessions(hours=24)
    assert removed == 1
    assert 1 not in store
    assert 2 in store
