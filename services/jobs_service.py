"""V3.28.0: persistent background-job registry (scaling foundation).

Long-running generation tasks (photo / video / circle / constructor) used to
exist only as asyncio.Task handles in in-memory dicts: a redeploy killed
them silently and no other process could see them. Every job now also gets
a ``background_jobs`` row, so restarts can recover interrupted jobs and a
future worker instance can pick jobs up by priority.
"""
from __future__ import annotations

import json
import logging

from models.app_models import BackgroundJob
from services.db import SessionLocal

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ('queued', 'running')


def begin_job(telegram_id: int, kind: str, payload: dict | None = None, priority: int = 0) -> int:
    """Register a running job. A fresh start supersedes any stale active row
    for the same user+kind (that task cannot be alive in this process)."""
    with SessionLocal() as s:
        s.query(BackgroundJob).filter(
            BackgroundJob.telegram_id == int(telegram_id),
            BackgroundJob.kind == kind,
            BackgroundJob.status.in_(ACTIVE_STATUSES),
        ).update({'status': 'superseded'}, synchronize_session=False)
        row = BackgroundJob(
            telegram_id=int(telegram_id),
            kind=kind,
            status='running',
            priority=int(priority or 0),
            payload_json=json.dumps(payload or {}, ensure_ascii=False, default=str),
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return row.id


def finish_job(job_id: int, status: str = 'done', error: str | None = None) -> None:
    with SessionLocal() as s:
        row = s.get(BackgroundJob, int(job_id))
        if row is None:
            return
        row.status = status
        if error:
            row.error = str(error)[:500]
        s.commit()


def recover_stale_jobs() -> list[tuple[int, str]]:
    """Startup sweep: everything still queued/running belongs to the previous
    process. Mark it recovered and return affected users (once each) so the
    bot can tell them to retry."""
    with SessionLocal() as s:
        rows = s.query(BackgroundJob).filter(
            BackgroundJob.status.in_(ACTIVE_STATUSES),
        ).all()
        affected: list[tuple[int, str]] = []
        seen_users: set[int] = set()
        for row in rows:
            row.status = 'recovered'
            if row.telegram_id not in seen_users:
                seen_users.add(row.telegram_id)
                affected.append((row.telegram_id, row.kind))
        s.commit()
        return affected
