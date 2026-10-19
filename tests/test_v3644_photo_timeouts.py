import asyncio
import pathlib

import httpx
import pytest

import config
from services import photo_service as ps

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_spicy_waits_past_slow_jobs():
    # successful jobs took up to 75s; 90s cut off a live one
    assert config.SPICYAPI_IMAGE_TIMEOUT >= 150


def test_raw_engine_chain_is_admin_only():
    main = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert "if exc.reason and telegram_id in ADMIN_TELEGRAM_IDS else ''" in main


def test_fal_transport_death_skips_other_routes_and_next_calls(monkeypatch):
    calls = []

    class DeadClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, endpoint, **kw):
            calls.append(endpoint)
            raise httpx.ReadError('reset')

    async def no_sleep(*_a, **_k):
        return None

    monkeypatch.setattr(ps, 'FAL_KEY', 'k')
    monkeypatch.setattr(ps, '_fal_down_until', 0.0)
    monkeypatch.setattr(ps.httpx, 'AsyncClient', DeadClient)
    monkeypatch.setattr(ps.asyncio, 'sleep', no_sleep)
    monkeypatch.setattr(ps.spend_service, 'image_generation_allowed', lambda: True)

    with pytest.raises(ps.PhotoGenerationError) as exc:
        asyncio.run(ps._seedream_request('p', ['http://x/a.jpg'], request_label='t'))
    assert exc.value.reason == 'transport_ReadError'
    assert len(set(calls)) == 1  # one route only, not all four
    n = len(calls)

    with pytest.raises(ps.PhotoGenerationError) as exc:
        asyncio.run(ps._seedream_request('p', ['http://x/a.jpg'], request_label='t'))
    assert exc.value.reason == 'fal_down'
    assert len(calls) == n
