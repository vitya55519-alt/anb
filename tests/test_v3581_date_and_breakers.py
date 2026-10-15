"""V3.58.1: the app-chat date answers at once (photo in the background), the
SPA shows progress and blocks double taps, and dead image engines are skipped
by circuit breakers instead of being waited on for every render."""
import asyncio
import os
from pathlib import Path

os.environ.setdefault("TELEGRAM_TOKEN", "123456:test-fake-token-for-static-tests-only")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-for-static-tests-only")

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')


def test_date_photo_renders_in_background():
    impl = MAIN[MAIN.index('async def _webapp_api_feature_action_impl('):]
    impl = impl[:impl.index('\nasync def _webapp_api_story(')]
    assert '_spawn_background(_deliver_date_photo(' in impl
    assert "'photo_pending': True" in impl
    assert 'await _webapp_media_scene(' not in impl.split('_BACKGROUND_TASKS')[0]
    deliver = MAIN[MAIN.index('async def _deliver_date_photo('):]
    deliver = deliver[:deliver.index('\nasync def ', 10)]
    assert 'await _webapp_media_scene(telegram_id, character_id, scene)' in deliver
    assert "media_kind='photo'" in deliver


def test_spa_shows_progress_and_blocks_double_taps():
    fp = INDEX[INDEX.index('async function featurePost(payload) {'):]
    fp = fp[:fp.index('\n}\n')]
    assert 'if (featBusy) return;' in fp
    assert "payload.kind === 'date'" in fp and 'L.date_wait' in fp
    assert 'if (j.photo_pending) waitForDatePhoto(CHAT.id);' in fp
    assert 'featBusy = false;' in fp
    assert INDEX.count('date_wait:') == 2 and INDEX.count('date_photo_wait:') == 2


def test_spicy_breaker_opens_after_misses_and_is_per_leg():
    from services import private_photo_service as pps

    calls = []

    async def fake_once(model, prompt, image_urls, scene='private', *, return_url=False):
        calls.append(model)
        return (None, None) if return_url else None

    async def run():
        orig = pps._spicyapi_render_once
        pps._spicyapi_render_once = fake_once
        pps._spicy_fail_streak.clear(); pps._spicy_skip_until.clear()
        try:
            for _ in range(pps.SPICYAPI_BREAKER_FAILURES):
                await pps._spicyapi_render('m-edit', 'p', ['ref'])
            assert pps.spicyapi_breaker_open('m-edit', ['ref'])
            before = len(calls)
            assert await pps._spicyapi_render('m-edit', 'p', ['ref']) is None
            assert len(calls) == before  # skipped, no provider call
            # the reference-free leg is unaffected
            assert not pps.spicyapi_breaker_open('m-edit', None)
        finally:
            pps._spicyapi_render_once = orig
            pps._spicy_fail_streak.clear(); pps._spicy_skip_until.clear()

    asyncio.run(run())


def test_gemini_429_cooldown_wired():
    assert 'if response.status_code == 429:' in PHOTO
    assert 'if gemini_on_cooldown():' in PHOTO
    assert "raise PhotoGenerationError('spicyapi', _spicy_reason('breaker_open', spicyapi_last_error()))" in PHOTO
