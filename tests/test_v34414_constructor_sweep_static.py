"""V3.44.14 static checks: bounded creation time + periodic draft sweep + status banner.

1. Each avatar attempt is capped by asyncio.wait_for (fal's internal chain can
   otherwise burn 3 routes × 3 retries × 210s ≈ half an hour of SILENT waiting)
   and the in-job loop is two attempts — a paid persona reaches the DB save
   within minutes no matter what providers do.
2. A periodic sweep resumes paid-but-unfinished drafts even when no deploy
   happened (an exception between payment and save used to strand her forever).
   The memory path stamps the claim so the sweep never double-spawns a live run.
3. /webapp/api/constructor/status drives the «Создаю {name}…» banner, so a slow
   avatar reads as progress instead of «её просто нет».
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CCS = (ROOT / 'services' / 'custom_character_service.py').read_text(encoding='utf-8')
HTML = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def _finish_body() -> str:
    return MAIN[MAIN.index('async def _finish_constructor('):MAIN.index('@dp.callback_query(F.data == \'constructor:start\')')]


def test_avatar_attempts_bounded():
    body = _finish_body()
    assert 'for attempt in (1, 2):' in body
    assert 'await asyncio.wait_for(' in body
    assert 'timeout=260,' in body
    # the save still lands after the attempts — she exists no matter what
    assert body.index('save_custom_character(') > body.index('asyncio.wait_for(')


def test_retry_task_also_bounded():
    retry = MAIN[MAIN.index('async def _retry_constructor_avatar('):MAIN.index('async def _constructor_draft_sweep(')]
    assert 'await asyncio.wait_for(' in retry
    assert 'timeout=240,' in retry


def test_sweep_task_resumes_drafts_periodically():
    assert 'async def _constructor_draft_sweep() -> None:' in MAIN
    assert 'await asyncio.sleep(180)' in MAIN
    assert 'for _draft in pending_constructor_drafts():' in MAIN
    # resumed creations ride the job registry like every other spawn
    assert "_spawn_job('constructor', int(_draft.telegram_id)" in MAIN
    # the sweep starts before polling and keeps running alongside it
    assert MAIN.index('asyncio.create_task(_constructor_draft_sweep())') < MAIN.index('await dp.start_polling(bot)')


def test_memory_path_stamps_claim():
    body = _finish_body()
    assert 'claim_constructor_draft(telegram_id)' in body
    # the stamp sits on the memory-session branch, not only the fallback
    assert 'stamp ownership on the draft too' in body


def test_stale_window_covers_worst_bounded_run():
    assert 'stale_minutes: int = 12' in CCS
    assert 'timedelta(minutes=12)' in CCS


def test_status_endpoint_and_route():
    assert 'async def _webapp_api_constructor_status(' in MAIN
    assert "add_get('/webapp/api/constructor/status'" in MAIN
    body = MAIN[MAIN.index('async def _webapp_api_constructor_status('):]
    body = body[:body.index('\nasync def ')]
    assert "web.json_response({'ok': False, 'error': 'auth'}, status=401)" in body
    assert 'draft.paid and not draft.done' in body


def test_frontend_creation_banner():
    assert 'id="creatingBanner"' in HTML
    assert 'async function checkConstructorStatus()' in HTML
    assert '/webapp/api/constructor/status' in HTML
    assert 'creating_banner:' in HTML
    assert 'Создаю {name}' in HTML
    # polled after payment and at boot, and the grid poll outlives 90 seconds
    assert HTML.count('checkConstructorStatus();') >= 3
    assert 'tries >= 40' in HTML
