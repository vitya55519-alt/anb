"""V3.44.20 static checks: fal transport resilience + a callable default route.

Production evidence (Railway log, 2026-09-28 17:33 UTC): every webapp chat photo
died as ``services.photo_service.PhotoGenerationError: seedream45: ReadError``.
Two root causes:

1. The fal.ai SANDBOX id d96lp9cregjb2a5jepag shipped as the FAL_MODEL default
   in V3.44.19 is a playground-internal id — https://fal.run/d96lp9cregjb2a5jepag
   answers 404 (probed; the proven routes answer 401 «exists, needs auth»), so
   every photo POSTed to a dead route.
2. ``httpx.ReadError`` (connection reset mid-request) was NOT in _seedream_request's
   retry tuple — it escaped the retry loop entirely: zero retries, no candidate
   walk, the photo just died. That hole predates V3.44.19 and is a likely chunk
   of the studio's 52% failure rate.

This release: FAL_MODEL default -> the proven bytedance/seedream/v5/pro/edit
partner route, and ReadError/RemoteProtocolError join the retried transport
faults (backoff retry, then walk to the next candidate route).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')


def test_default_model_is_a_real_fal_run_route():
    # probed: fal.run/bytedance/seedream/v5/pro/edit -> 401 (exists);
    # fal.run/d96lp9cregjb2a5jepag -> 404 (playground-internal, not callable)
    assert 'FAL_MODEL = os.getenv("FAL_MODEL", "bytedance/seedream/v5/pro/edit")' in CONFIG
    assert 'd96lp9cregjb2a5jepag' not in CONFIG.split('FAL_MODEL = ')[1].split('\n')[0]
    # the config documents WHY the sandbox id is not the default, so the next
    # owner who opens the sandbox page does not paste the id back blindly
    assert 'fal.run answers 404 for it' in CONFIG


def test_readerror_is_retried_not_fatal():
    # the exact production crash: httpx.ReadError escaped the except tuple
    assert 'except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.WriteTimeout, httpx.PoolTimeout, httpx.ReadError, httpx.RemoteProtocolError) as exc:' in PHOTO
    # the old tuple (without ReadError) must be gone
    assert 'except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as exc:' not in PHOTO


def test_transport_exhaustion_walks_to_the_next_candidate():
    # after the last attempt the loop breaks to the next candidate route
    # instead of raising straight through generate_photo_set
    assert "last_error = PhotoGenerationError('seedream45', f'transport_{type(exc).__name__}')" in PHOTO
    assert 'Seedream transport failed label=%s model=%s attempt=%s/%s elapsed=%.1fs type=%s' in PHOTO
    # the retry/backoff path itself is unchanged
    assert 'await asyncio.sleep(FAL_RETRY_BACKOFF_SECONDS * attempt)' in PHOTO


def test_404_walk_still_moves_routes():
    # a retired/renamed route (like the sandbox id would be) falls through to
    # the next candidate on HTTP 404
    assert "if response.status_code == 404 and candidate != candidates[-1]:" in PHOTO
    assert "last_error = PhotoGenerationError('seedream45', f'HTTP 404 {candidate}')" in PHOTO


def test_timeout_retry_path_survives():
    # timeouts keep their retry semantics (and the smoke-test pin string)
    assert 'httpx.ReadTimeout' in PHOTO
    assert 'max_attempts = FAL_RETRIES + 1' in PHOTO
