"""Static + runtime regression tests for v3.28.0: persistent job registry.

Every long-running generation (photo / video / circle / constructor) now gets
a `background_jobs` DB row through `_spawn_job`, so a redeploy no longer loses
jobs silently: startup marks stale rows `recovered` and notifies the users.
This is the foundation for future multi-worker scaling (priority column).
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
DB = (ROOT / 'services' / 'db.py').read_text(encoding='utf-8')
JOBS = (ROOT / 'services' / 'jobs_service.py').read_text(encoding='utf-8')


def test_background_job_model():
    block = MODELS.split('class BackgroundJob', 1)[1].split('\nclass ', 1)[0]
    assert '__tablename__ = "background_jobs"' in block
    assert 'telegram_id: Mapped[int] = mapped_column(BigInteger' in block
    assert 'kind: Mapped[str]' in block
    assert 'status: Mapped[str] = mapped_column(String(16), default="running"' in block
    assert 'priority: Mapped[int] = mapped_column(Integer, default=0)' in block
    assert 'payload_json' in block
    assert 'BackgroundJob' in DB  # imported so create_all/migrations see it


def test_all_generation_spawns_go_through_spawn_job():
    assert 'def _spawn_job(kind: str, telegram_id: int, coro' in MAIN
    assert 'async def _track_job(job_id: int, coro):' in MAIN
    assert 'priority = 1 if is_premium(telegram_id) else 0' in MAIN
    # no untracked raw spawns of the long pipelines may remain
    for coro in ('_run_photo_background(', '_run_video_background(',
                 '_run_circle_background(', '_finish_constructor('):
        assert f'asyncio.create_task({coro}' not in MAIN, coro
    assert MAIN.count('_spawn_job(') >= 10  # helper def + 10 call sites


def test_startup_recovers_stale_jobs_before_polling():
    assert 'from services import jobs_service' in MAIN
    assert 'jobs_service.recover_stale_jobs()' in MAIN
    assert MAIN.index('jobs_service.recover_stale_jobs()') < MAIN.index('await dp.start_polling(bot)')


def test_jobs_service_contract():
    assert "ACTIVE_STATUSES = ('queued', 'running')" in JOBS
    assert "def begin_job(telegram_id: int, kind: str" in JOBS
    assert "'superseded'" in JOBS
    assert "def finish_job(job_id: int, status: str = 'done'" in JOBS
    assert 'def recover_stale_jobs()' in JOBS


@pytest.fixture()
def jobs_db(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.waifu_models import Base
    import models.app_models  # noqa: F401  (register tables)
    from services import jobs_service

    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    monkeypatch.setattr(jobs_service, 'SessionLocal',
                        sessionmaker(bind=engine, expire_on_commit=False))
    return jobs_service


def test_runtime_begin_finish_recover(jobs_db):
    j1 = jobs_db.begin_job(111, 'video', {'preset': 'kiss'}, priority=1)
    assert j1 > 0
    # a fresh start for the same user+kind supersedes the stale row
    j2 = jobs_db.begin_job(111, 'video', {'preset': 'auto'})
    assert j2 != j1
    jobs_db.finish_job(j2, 'done')

    # another user with two jobs — recovery must dedupe per user
    jobs_db.begin_job(222, 'photo')
    jobs_db.begin_job(222, 'constructor')

    from models.app_models import BackgroundJob
    with jobs_db.SessionLocal() as s:
        first = s.get(BackgroundJob, j1)
        assert first.status == 'superseded'
        second = s.get(BackgroundJob, j2)
        assert second.status == 'done'
        assert second.priority == 0

    affected = jobs_db.recover_stale_jobs()
    assert sorted(uid for uid, _ in affected) == [222]
    assert affected[0][1] in ('photo', 'constructor')

    with jobs_db.SessionLocal() as s:
        active = s.query(BackgroundJob).filter(
            BackgroundJob.status.in_(('queued', 'running'))).count()
        assert active == 0


def test_runtime_failed_job_keeps_error(jobs_db):
    jid = jobs_db.begin_job(333, 'video')
    jobs_db.finish_job(jid, 'failed', 'engine timeout ' * 100)
    from models.app_models import BackgroundJob
    with jobs_db.SessionLocal() as s:
        row = s.get(BackgroundJob, jid)
        assert row.status == 'failed'
        assert len(row.error) <= 500
