"""V3.82.0: the daily DB backup dumps every table and restores into an empty DB."""
import gzip
import json


def test_dump_and_restore_roundtrip():
    from services.db import init_db, engine
    init_db()
    from sqlalchemy import MetaData, delete
    from services import backup_service as B
    from services.user_service import ensure_user, get_user
    from services.payments import grant_photo_credits
    ensure_user(982001, 'Тест')
    grant_photo_credits(982001, 777, reason='backup_test')
    before = get_user(982001)
    data, counts = B.dump_database()
    assert counts.get('users', 0) >= 1
    lines = gzip.decompress(data).splitlines()
    headers = [json.loads(x) for x in lines if x.startswith(b'{"table"')]
    pp = next(h for h in headers if h['table'] == 'proactive_photos')
    assert 'image_bytes' in pp['skipped']          # no image bytes in the file
    # wipe everything, then restore
    meta = MetaData()
    meta.reflect(bind=engine)
    with engine.begin() as conn:
        for table in reversed(meta.sorted_tables):
            conn.execute(delete(table))
    assert get_user(982001) is None
    restored = B.restore_dump(data)
    assert restored.get('users') == counts['users']
    after = get_user(982001)
    assert after and after.photo_credits == before.photo_credits
    assert after.created_at == before.created_at


def test_backup_job_is_scheduled_and_command_exists():
    import inspect
    from services import scheduler_service
    src = inspect.getsource(scheduler_service.start_scheduler)
    assert "id='db_backup'" in src
    import main
    assert callable(main.admin_backup_cmd)
