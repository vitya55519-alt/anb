"""V3.43.2 static pins: fresh cards reach the grid instantly, living tiles play.

The owner's screenshot showed the OLD heroines on the storefront grid even
though the re-rendered Ken-Burns tiles were already deployed: Telegram's
WebView held every asset for the whole ``max-age`` window and heuristically
cached the characters JSON on top. This release

1. stamps every storefront asset URL with ``?v=<newest mtime in the reference
   folder>`` (``asset_version``), so a rebuilt tile or live clip changes the
   URL and bypasses the stale cache entry; the routes themselves move to a
   week-long immutable max-age because the URL is now content-addressed;
2. marks the characters/select JSON ``no-store`` so the grid never renders a
   cached payload (stale cards, missing ``live`` links) after a deploy;
3. makes the living tiles actually play in WebView — ``preload="metadata"``,
   a manual ``play()`` kick after render and an IntersectionObserver that
   pauses the mp4 loops scrolled off screen;
4. gives heroines the kiss motion rejects (maria) a second i2v pass with the
   simpler turn-and-smile script (``LIVE_TILE_PROMPT_ALT``).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


def test_version_bumped():
    # V3.43.2 shipped this; newer releases keep the pin in their own suite.
    assert VERSION in ('3.44.4', '3.44.3', '3.43.7', '3.43.6', '3.43.5', '3.43.4', '3.43.3', '3.43.2')


# ── 1. content-addressed asset URLs ─────────────────────────────────────────

def test_asset_version_helper_stamps_every_storefront_url():
    assert 'def asset_version(character_id: str) -> str:' in WEBAPP_SVC
    assert 'newest = max(newest, int(item.stat().st_mtime))' in WEBAPP_SVC
    # grid payload: photo, tile, live clip and the gallery strip all carry ?v=
    assert 'ver = asset_version(card.character_id)' in WEBAPP_SVC
    assert "'photo': f\"/webapp/photo/{card.character_id}?v={ver}\"," in WEBAPP_SVC
    assert "'card': (f'/webapp/card/{card.character_id}?v={ver}'" in WEBAPP_SVC
    assert "'live': (f'/webapp/card/{card.character_id}?v={ver}'" in WEBAPP_SVC
    assert "f'/webapp/photo/{card.character_id}?i={idx}&v={ver}'" in WEBAPP_SVC
    # the chat list avatar too
    assert "'photo': f\"/webapp/photo/{character_id}?v={asset_version(character_id)}\"," in WEBAPP_SVC


def test_asset_routes_are_immutable_now_that_urls_carry_the_stamp():
    # four public storefront routes (photo, gif tile, live clip, card media)
    assert MAIN.count("headers={'Cache-Control': 'public, max-age=604800'})") == 4
    assert 'public, max-age=3600' not in MAIN.split('async def _webapp_photo')[1].split('async def _webapp_api_char_view')[0]


# ── 2. the characters JSON is never cached ──────────────────────────────────

def test_characters_json_served_no_store():
    chars = MAIN[MAIN.index('async def _webapp_api_characters'):]
    chars = chars[:chars.index('async def _webapp_api_shop')]
    assert "headers={'Cache-Control': 'no-store'})" in chars
    select = MAIN[MAIN.index("'characters': webapp_service.api_characters(telegram_id),\n    }, headers="):]
    assert "headers={'Cache-Control': 'no-store'})" in select
    # and the grid fetch itself refuses the browser cache
    assert "fetch('/webapp/api/characters' + q, {cache: 'no-store'})" in INDEX


# ── 3. living tiles play in WebView and pause off screen ────────────────────

def test_living_tiles_kick_and_lazy_pause():
    assert 'preload="metadata"' in INDEX
    assert "grid.querySelectorAll('video').forEach(v => { if (liveIO) liveIO.observe(v); v.play().catch(() => {}); });" in INDEX  # noqa: E501
    assert 'new IntersectionObserver(es => es.forEach(e => {' in INDEX
    assert 'if (e.isIntersecting) e.target.play().catch(() => {}); else e.target.pause();' in INDEX


# ── 4. rejected heroines get the backup motion ──────────────────────────────

def test_live_tile_backup_prompt_second_pass():
    assert 'LIVE_TILE_PROMPT_ALT = (' in MAIN
    assert 'slowly turns her head toward the camera and smiles softly' in MAIN
    job = MAIN[MAIN.index('async def _run_live_tiles'):]
    job = job[:job.index("@dp.message(Command('livetiles'))")]
    assert 'for prompt in (LIVE_TILE_PROMPT, LIVE_TILE_PROMPT_ALT):' in job
    assert 'prompt=prompt)' in job
