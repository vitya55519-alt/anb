"""V3.29.0: persistent dialog wizards (scaling foundation, part 2).

Multi-step conversations (character constructor, paid fantasy input, photo
offers, adult-photo confirmation, custom-outfit drafts) used to live in
in-memory dicts: a redeploy made the bot "forget" mid-wizard, which hurt the
most right after a payment. State now lives in the ``dialog_sessions`` table
behind a dict-compatible :class:`DialogStore`, so every existing
``store[uid]`` / ``store.get(uid)`` / ``store.pop(uid)`` call site keeps
working and survives restarts.

Admin-only editor sessions stay in memory on purpose: they are trivial to
restart and not worth persisting.
"""
from __future__ import annotations

import base64
import dataclasses
import json
import logging
from collections.abc import MutableMapping
from datetime import datetime, timedelta

from models.app_models import DialogSession
from services.db import SessionLocal

logger = logging.getLogger(__name__)

MAX_PAYLOAD_CHARS = 4 * 1024 * 1024  # ~4MB JSON guard (constructor face photo)
STALE_AFTER_HOURS = 24

_B64_KEY = '__b64__'
_PHOTO_REQ_KEY = '__photo_request__'


def _encode(value):
    if isinstance(value, bytes):
        return {_B64_KEY: base64.b64encode(value).decode('ascii')}
    if isinstance(value, dict):
        return {str(k): _encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    return value


def _decode(value):
    if isinstance(value, dict):
        if set(value.keys()) == {_B64_KEY}:
            return base64.b64decode(value[_B64_KEY])
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


class _PersistentDict(MutableMapping):
    """dict-like view of one session row; every top-level write flushes to DB."""

    def __init__(self, store: 'DialogStore', telegram_id: int, data: dict):
        self._store = store
        self._telegram_id = telegram_id
        self._data = data

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value
        self._store._write(self._telegram_id, self._data)

    def __delitem__(self, key):
        del self._data[key]
        self._store._write(self._telegram_id, self._data)

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)


class DialogStore:
    """dict[int, ...]-compatible facade over dialog_sessions rows."""

    def __init__(self, session_key: str, codec: str = 'json'):
        self.session_key = session_key
        self.codec = codec

    # -- codecs ---------------------------------------------------------
    def _to_payload(self, value) -> str:
        if self.codec == 'photo_request':
            from services.photo_service import PhotoRequest
            if not isinstance(value, PhotoRequest):
                raise TypeError('photo_request store expects PhotoRequest')
            data = {_PHOTO_REQ_KEY: dataclasses.asdict(value)}
        else:
            data = _encode(value)
        return json.dumps(data, ensure_ascii=False)

    def _from_payload(self, payload: str):
        data = json.loads(payload or 'null')
        if self.codec == 'photo_request':
            from services.photo_service import PhotoRequest
            fields = dict((data or {}).get(_PHOTO_REQ_KEY) or {})
            if 'pack_outfits' in fields:
                fields['pack_outfits'] = tuple(fields['pack_outfits'] or ())
            return PhotoRequest(**fields)
        return _decode(data)

    # -- storage --------------------------------------------------------
    def _write(self, telegram_id: int, value) -> None:
        payload = self._to_payload(value)
        if len(payload) > MAX_PAYLOAD_CHARS:
            logger.warning('dialog session too large to persist key=%s user=%s size=%s',
                           self.session_key, telegram_id, len(payload))
            return
        with SessionLocal() as s:
            row = s.query(DialogSession).filter(
                DialogSession.telegram_id == int(telegram_id),
                DialogSession.session_key == self.session_key,
            ).first()
            if row is None:
                row = DialogSession(telegram_id=int(telegram_id), session_key=self.session_key)
                s.add(row)
            row.payload_json = payload
            s.commit()

    def _read(self, telegram_id: int):
        with SessionLocal() as s:
            row = s.query(DialogSession).filter(
                DialogSession.telegram_id == int(telegram_id),
                DialogSession.session_key == self.session_key,
            ).first()
            if row is None:
                return None
            try:
                return self._from_payload(row.payload_json)
            except Exception:
                logger.exception('dialog session decode failed key=%s user=%s',
                                 self.session_key, telegram_id)
                return None

    def _delete(self, telegram_id: int) -> None:
        with SessionLocal() as s:
            s.query(DialogSession).filter(
                DialogSession.telegram_id == int(telegram_id),
                DialogSession.session_key == self.session_key,
            ).delete()
            s.commit()

    # -- dict-like API ---------------------------------------------------
    def __contains__(self, telegram_id) -> bool:
        with SessionLocal() as s:
            return s.query(DialogSession.id).filter(
                DialogSession.telegram_id == int(telegram_id),
                DialogSession.session_key == self.session_key,
            ).first() is not None

    def __getitem__(self, telegram_id):
        value = self._read(telegram_id)
        if value is None and telegram_id not in self:
            raise KeyError(telegram_id)
        return self._wrap(telegram_id, value)

    def get(self, telegram_id, default=None):
        value = self._read(telegram_id)
        if value is None and telegram_id not in self:
            return default
        return self._wrap(telegram_id, value)

    def __setitem__(self, telegram_id, value):
        self._write(telegram_id, value)

    def __delitem__(self, telegram_id):
        if telegram_id not in self:
            raise KeyError(telegram_id)
        self._delete(telegram_id)

    def pop(self, telegram_id, *default):
        value = self._read(telegram_id)
        exists = value is not None or telegram_id in self
        if exists:
            self._delete(telegram_id)
            return self._wrap(telegram_id, value)
        if default:
            return default[0]
        raise KeyError(telegram_id)

    def _wrap(self, telegram_id, value):
        if isinstance(value, dict):
            return _PersistentDict(self, telegram_id, value)
        return value


def cleanup_stale_sessions(hours: int = STALE_AFTER_HOURS) -> int:
    """Drop wizard sessions nobody touched for ``hours`` (bounded growth)."""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    with SessionLocal() as s:
        removed = s.query(DialogSession).filter(
            DialogSession.updated_at < cutoff,
        ).delete()
        s.commit()
        return removed
