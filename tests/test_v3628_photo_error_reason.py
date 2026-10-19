"""V3.62.3: when SpicyAPI fails and fal fails too, the admin toast keeps
SpicyAPI's own cause instead of only fal's transport error."""
import asyncio

import services.photo_service as ps
from services.photo_service import PhotoGenerationError, PhotoRequest


def test_spicy_reason_carries_last_error():
    assert ps._spicy_reason('breaker_open', 'http_402 balance') == 'breaker_open:http_402 balance'
    assert ps._spicy_reason('empty_result', '') == 'empty_result'


def test_spicy_failure_is_final_without_fal(monkeypatch):
    # V3.64.5: fal is removed; SpicyAPI's own cause reaches the toast as-is
    async def spicy(*a, **k):
        raise PhotoGenerationError('spicyapi', 'breaker_open:http_402')

    async def fal(*a, **k):
        raise AssertionError('fal must not be called')

    monkeypatch.setattr(ps, '_run_spicy_set', spicy)
    monkeypatch.setattr(ps, '_run_seedream_set', fal)
    monkeypatch.setattr(ps, 'track_event', lambda *a, **k: None)
    monkeypatch.setattr(ps, 'ensure_user', lambda uid: uid)
    req = PhotoRequest(scene='selfie')
    try:
        asyncio.run(ps._run_routed_photo_set({}, 1, req, 'spicyapi', frames=1))
    except PhotoGenerationError as exc:
        assert exc.reason == 'breaker_open:http_402'
    else:
        raise AssertionError('expected failure')
