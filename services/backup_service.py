"""V3.82.0: a daily database backup sent to the owner in Telegram.

Railway's Hobby plan has no Postgres backups, so the bot dumps every table
itself (one gzip'ed JSON-lines file) and sends it to the admins as a
document. Image/video bytes (photo pools, chat media) are left out: they are
large, they would push the file past Telegram's 50 MB bot limit, and they can
be regenerated — users, balances, payments, dialogs and progress are what must
never be lost.

Format: one line per table header {"table": name, "columns": [...]} followed by
one JSON array per row. restore_dump() loads such a file into an EMPTY
database that init_db() has already created.
"""
from __future__ import annotations

import base64
import datetime as dt
import decimal
import gzip
import io
import json
import logging

from sqlalchemy import LargeBinary, MetaData, insert, select

from services.db import engine

logger = logging.getLogger(__name__)

TELEGRAM_DOC_LIMIT = 49 * 1024 * 1024


def _plain(value):
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return {'$dt': value.isoformat(), '$k': type(value).__name__}
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {'$b64': base64.b64encode(bytes(value)).decode()}
    return value


def _restore_value(value):
    if isinstance(value, dict):
        if '$dt' in value:
            kind = value.get('$k')
            if kind == 'date':
                return dt.date.fromisoformat(value['$dt'])
            if kind == 'time':
                return dt.time.fromisoformat(value['$dt'])
            return dt.datetime.fromisoformat(value['$dt'])
        if '$b64' in value:
            return base64.b64decode(value['$b64'])
    return value


def dump_database(include_binary: bool = False) -> tuple[bytes, dict]:
    """Return (gzip bytes, {table: rows}) for every table in the live DB."""
    meta = MetaData()
    meta.reflect(bind=engine)
    buf = io.BytesIO()
    counts: dict[str, int] = {}
    with gzip.GzipFile(fileobj=buf, mode='wb', compresslevel=6) as gz, engine.connect() as conn:
        for table in meta.sorted_tables:
            cols = [c for c in table.columns
                    if include_binary or not isinstance(c.type, LargeBinary)]
            skipped = [c.name for c in table.columns if c not in cols]
            header = {'table': table.name, 'columns': [c.name for c in cols], 'skipped': skipped}
            gz.write((json.dumps(header, ensure_ascii=False) + '\n').encode())
            n = 0
            for row in conn.execution_options(stream_results=True).execute(select(*cols)):
                gz.write((json.dumps([_plain(v) for v in row], ensure_ascii=False) + '\n').encode())
                n += 1
            counts[table.name] = n
    return buf.getvalue(), counts


def restore_dump(data: bytes) -> dict:
    """Load a dump_database() file into an empty, already-created database.
    Tables missing from the target are skipped; returns {table: rows}."""
    meta = MetaData()
    meta.reflect(bind=engine)
    counts: dict[str, int] = {}
    table = None
    columns: list[str] = []
    batch: list[dict] = []

    def _flush(conn):
        if table is not None and batch:
            conn.execute(insert(table), batch)
            counts[table.name] = counts.get(table.name, 0) + len(batch)
            batch.clear()

    with engine.begin() as conn:
        for raw in gzip.decompress(data).splitlines():
            item = json.loads(raw)
            if isinstance(item, dict) and 'table' in item:
                _flush(conn)
                table = meta.tables.get(item['table'])
                columns = list(item.get('columns') or [])
                # rows whose image bytes were left out of the dump cannot come
                # back where those bytes are required (the photo pools)
                if table is not None and any(
                        name in table.c and not table.c[name].nullable
                        for name in item.get('skipped') or []):
                    table = None
                continue
            if table is None:
                continue
            batch.append({name: _restore_value(value) for name, value in zip(columns, item)
                          if name in table.c})
            if len(batch) >= 500:
                _flush(conn)
        _flush(conn)
    return counts


def backup_filename(now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(dt.timezone.utc)
    return f'anb-db-{now.strftime("%Y-%m-%d_%H%M")}.jsonl.gz'


def summary_line(counts: dict, size: int) -> str:
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:5]
    parts = ', '.join(f'{name} {n}' for name, n in top)
    return (f'🗄 бэкап базы: {len(counts)} таблиц, {sum(counts.values())} строк, '
            f'{size / 1024 / 1024:.1f} МБ. Больше всего: {parts}. Фото и видео в бэкап не входят.')
