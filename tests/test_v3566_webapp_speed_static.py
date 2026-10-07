"""V3.56.6 static checks: the Mini App stops downloading 280KB on every open.

The owner: «сама загрузка и прогрузка мини приложения долго» — chat, missions
and history all lag, while photos/messages are fine. The page used to be a raw
FileResponse with no-cache: never gzipped (FileResponse cannot), never 304,
281KB re-downloaded on every WebView open; the JSON APIs (characters, chats,
history — tens of KB) were uncompressed too.

Pins:
1. _webapp_index serves cached bytes with ETag + gzip + 304 revalidation;
2. a gzip middleware is registered on the web app and only touches
   JSON/text bodies ≥1KB that are not already encoded;
3. the photo/media byte routes stay out of the middleware's way (content-type
   guard), so canonical references and generated images are served as before.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')

INDEX_FN = MAIN[MAIN.index('async def _webapp_index('):MAIN.index('async def _webapp_api_me(')]


def test_index_page_is_cached_gzipped_and_revalidatable():
    assert '_WEBAPP_PAGE_CACHE' in INDEX_FN
    assert '_gzip.compress(raw, 6)' in INDEX_FN
    assert 'If-None-Match' in INDEX_FN and 'status=304' in INDEX_FN
    assert "'Content-Encoding': 'gzip'" in INDEX_FN
    # no-cache stays (fresh ETag check every open) — but the check now costs 304
    assert "'Cache-Control': 'no-cache'" in INDEX_FN
    # the old uncompressed FileResponse path is gone
    assert 'FileResponse(index' not in INDEX_FN


def test_gzip_middleware_registered_and_guarded():
    assert '@web.middleware\nasync def _webapp_gzip(' in MAIN
    assert 'app.middlewares.append(_webapp_gzip)' in MAIN
    # only text/json ≥1KB, never already-encoded bodies
    assert "ctype.startswith('application/json') or ctype.startswith('text/')" in MAIN
    assert "response.headers.get('Content-Encoding')" in MAIN
    assert 'len(payload) < 1024' in MAIN


def test_middleware_registered_before_routes():
    server = MAIN[MAIN.index('async def _start_web_server()'):]
    assert server.index('app.middlewares.append(_webapp_gzip)') < server.index("app.router.add_get('/webapp'")
