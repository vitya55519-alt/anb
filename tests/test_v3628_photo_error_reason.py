"""V3.62.3: when SpicyAPI fails and fal fails too, the admin toast keeps
SpicyAPI's own cause instead of only fal's transport error."""
import asyncio

import services.photo_service as ps
from services.photo_service import PhotoGenerationError, PhotoRequest


def test_spicy_reason_carries_last_error():
    assert ps._spicy_reason('breaker_open', 'http_402 balance') == 'breaker_open:http_402 balance'
    assert ps._spicy_reason('empty_result', '') == 'empty_result'


def test_fallback_failure_keeps_both_reasons(monkeypatch):
    async def spicy(*a, **k):
        raise PhotoGenerationError('spicyapi', 'breaker_open:http_402')

    async def fal(*a, **k):
        raise PhotoGenerationError('seedream45', 'transport_ReadError')

    monkeypatch.setattr(ps, '_run_spicy_set', spicy)
    monkeypatch.setattr(ps, '_run_seedream_set', fal)
    monkeypatch.setattr(ps, 'track_event', lambda *a, **k: None)
    monkeypatch.setattr(ps, 'ensure_user', lambda uid: uid)
    req = PhotoRequest(scene='selfie')
    try:
        asyncio.run(ps._run_routed_photo_set({}, 1, req, 'spicyapi', frames=1))
    except PhotoGenerationError as exc:
        assert exc.reason == 'spicyapi/breaker_open:http_402 → seedream45/transport_ReadError'
    else:
        raise AssertionError('expected failure')
