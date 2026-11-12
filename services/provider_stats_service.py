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


# V3.82.1: the all-time counters still carried the dead fal leg of mid-October,
# so /stats showed «успешность 49%» long after the studio was healthy. Every
# attempt also bumps a per-day row «day:YYYY-MM-DD:<provider>»; /stats reads the
# last 7 days of them. Day rows stay out of provider_snapshot().
DAY_PREFIX = 'day:'


def _bump(s, key: str, ok: bool, error: str | None) -> None:
    row = s.get(ProviderStat, key)
    if row is None:
        row = ProviderStat(provider=key, ok=0, fail=0)
        s.add(row)
    if ok:
        row.ok = (row.ok or 0) + 1
    else:
        row.fail = (row.fail or 0) + 1
        if error:
            row.last_error = str(error)[:256]
    row.updated_at = _now()


def record_provider(provider: str, ok: bool, error: str | None = None) -> None:
    """Bump the ok/fail counter of one engine. Never raises — stats must not
    break the media pipeline they observe."""
    try:
        with SessionLocal() as s:
            _bump(s, provider, ok, error)
            _bump(s, f'{DAY_PREFIX}{_now().date().isoformat()}:{provider}'[:64], ok, error)
            s.commit()
    except Exception:
        pass


def recent_totals(prefix: str, days: int = 7) -> tuple[int, int]:
    """(ok, fail) of providers starting with ``prefix`` over the last ``days``
    days, today included."""
    from datetime import timedelta
    today = _now().date()
    keys = {f'{DAY_PREFIX}{(today - timedelta(days=i)).isoformat()}:' for i in range(days)}
    ok = fail = 0
    try:
        with SessionLocal() as s:
            rows = s.scalars(select(ProviderStat).where(ProviderStat.provider.like(DAY_PREFIX + '%'))).all()
            for r in rows:
                head, _, name = r.provider[len(DAY_PREFIX):].partition(':')
                if f'{DAY_PREFIX}{head}:' in keys and name.startswith(prefix):
                    ok += r.ok or 0
                    fail += r.fail or 0
    except Exception:
        return 0, 0
    return ok, fail


def provider_snapshot() -> list[dict]:
    """All counters, provider name ascending (empty table = nothing ran yet)."""
    try:
        with SessionLocal() as s:
            rows = s.scalars(select(ProviderStat).where(~ProviderStat.provider.like(DAY_PREFIX + '%'))
                             .order_by(ProviderStat.provider)).all()
            return [
                {'provider': r.provider, 'ok': r.ok or 0, 'fail': r.fail or 0,
                 'last_error': r.last_error or ''}
                for r in rows
            ]
    except Exception:
        return []
