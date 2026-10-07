"""V3.56.5 static checks: stop sleeping on top of the provider.

The owner's Railway log: SpicyAPI finished the image at 16:52:55 but the bot
only noticed at 16:53:08 — the recordInfo backoff (2s start, ×1.5 growth, 15s
cap) slept up to fifteen seconds AFTER the job was already done. recordInfo is
free and the job takes ~45-60s, so polling every ≤3s costs a dozen extra
GETs and saves ~10s of user-visible wait on every single photo. The R2
download also got a hard 30s timeout: a stalled CDN socket used to be able to
hang the request long past the render deadline.

Pins:
1. the poll loop starts at 1.0s and caps at 3.0s;
2. the asset download session carries a 30s ClientTimeout.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = (ROOT / 'services' / 'private_photo_service.py').read_text(encoding='utf-8')

RENDER = PRIVATE[PRIVATE.index('async def _spicyapi_render('):PRIVATE.index('async def generate_private_photo_real(')]


def test_poll_backoff_is_tight():
    assert 'wait = 1.0' in RENDER
    assert 'wait = min(wait * 1.25, 3.0)' in RENDER
    # the old lazy backoff must not come back
    assert '1.5, 15.0' not in RENDER


def test_asset_download_has_a_timeout():
    assert 'aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))' in RENDER
