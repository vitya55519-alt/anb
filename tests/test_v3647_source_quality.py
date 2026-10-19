def test_stats_show_source_quality():
    import main
    snap = {'sources_24h': [], 'sources_7d': [],
            'source_quality': [['tg_kawa', 29, 14, 3, 1], ['organic', 18, 9, 1, 0]]}
    block = main._sources_block(snap)
    assert 'качество источников (30д)' in block
    assert 'метка src_tg_kawa: 29 → написали 14 → вернулись D1 3 → оплатили 1' in block


def test_source_quality_in_snapshot():
    from services.analytics_service import admin_snapshot, source_quality
    assert isinstance(source_quality(), list)
    assert 'source_quality' in admin_snapshot()


def test_source_quality_counts_per_tag():
    from datetime import timedelta
    from models.app_models import ProductEvent, User
    from services import analytics_service as a
    from services.db import SessionLocal
    now = a._now()
    with SessionLocal() as s:
        u1 = User(telegram_id='sq_1', source_tag='tg_sqtest', created_at=now - timedelta(days=3))
        u2 = User(telegram_id='sq_2', source_tag='tg_sqtest', created_at=now - timedelta(days=3))
        s.add_all([u1, u2]); s.flush()
        s.add_all([
            ProductEvent(user_id=u1.id, character_id='anna', event_name='chat_user_message', created_at=u1.created_at + timedelta(minutes=5)),
            ProductEvent(user_id=u1.id, character_id='anna', event_name='webapp_opened', created_at=u1.created_at + timedelta(hours=30)),
            ProductEvent(user_id=u1.id, character_id='anna', event_name='platega_paid', created_at=u1.created_at + timedelta(hours=31)),
        ])
        s.commit()
    rows = {r[0]: r[1:] for r in a.source_quality(limit=50)}
    assert rows['tg_sqtest'] == [2, 1, 1, 1]
