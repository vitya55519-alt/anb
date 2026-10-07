"""V3.48.3 static checks: the daily-quest menu survives a transient failure.

Owner report: tapping «🎯 Задание» in the app chat showed «Не получилось
ответить — попробуй ещё раз». The quest branch itself is pure (deterministic
``couple_service.daily_quest``), so the failure was an unhandled exception in the
shared feature-menu prologue (``get_relationship_level`` -> ``ensure_user`` writes
on every call) surfacing as a raw HTTP 500, which the SPA renders as the generic
retry string. Two guards: the endpoint never 500s, and the SPA retries once.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_feature_endpoint_is_exception_guarded():
    # the public name stays the route target; it now wraps a try/except over impl
    assert 'async def _webapp_api_feature(request: web.Request) -> web.Response:' in MAIN
    assert 'def _webapp_api_feature_impl(request: web.Request) -> web.Response:' in MAIN
    wrapper = MAIN[MAIN.index('async def _webapp_api_feature('):MAIN.index('def _webapp_api_feature_impl(')]
    assert 'return await asyncio.to_thread(_webapp_api_feature_impl, request)' in wrapper
    assert "logger.exception('webapp feature menu failed')" in wrapper
    assert "'temporarily_unavailable'" in wrapper
    # the route still registers the guarded wrapper, not the impl
    assert "add_get('/webapp/api/feature', _webapp_api_feature)" in MAIN


def test_openfeature_retries_once_before_showing_the_error():
    fn = INDEX[INDEX.index('async function openFeature(kind) {'):INDEX.index('async function featurePost(')]
    assert 'for (let attempt = 0; attempt < 2; attempt++)' in fn
    assert 'if (parsed && parsed.ok) { j = parsed; break; }' in fn
    # a silent backoff between the two attempts
    assert 'await new Promise(res => setTimeout(res, 450));' in fn
    # the generic error only shows after both attempts failed
    assert 'if (!j) { fail(); return; }' in fn
