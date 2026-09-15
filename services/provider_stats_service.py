"""V3.40.0: per-provider success/failure counters.

The studio and the video/circle chains each try several engines in order; a
silent outage of one of them used to be visible only in Railway logs. Every
engine attempt now bumps a row here, and the admin «🩺 Отказы провайдеров»
screen renders the table, so a flaky provider is diagnosable in one tap.
"""
from datetime import datetime, timezone

from sqlalchemy import select

from models.app_models import ProviderStat
from services.db import SessionLocal


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def record_provider(provider: str, ok: bool, error: str | None = None) -> None:
    """Bump the ok/fail counter of one engine. Never raises — stats must not
    break the media pipeline they observe."""
    try:
        with SessionLocal() as s:
            row = s.get(ProviderStat, provider)
            if row is None:
                row = ProviderStat(provider=provider, ok=0, fail=0)
                s.add(row)
            if ok:
                row.ok = (row.ok or 0) + 1
            else:
                row.fail = (row.fail or 0) + 1
                if error:
                    row.last_error = str(error)[:256]
            row.updated_at = _now()
            s.commit()
    except Exception:
        pass


def provider_snapshot() -> list[dict]:
    """All counters, provider name ascending (empty table = nothing ran yet)."""
    try:
        with SessionLocal() as s:
            rows = s.scalars(select(ProviderStat).order_by(ProviderStat.provider)).all()
            return [
                {'provider': r.provider, 'ok': r.ok or 0, 'fail': r.fail or 0,
                 'last_error': r.last_error or ''}
                for r in rows
            ]
    except Exception:
        return []
