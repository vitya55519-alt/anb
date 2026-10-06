"""V3.55.7 static checks: the app-chat «Задание» claim survives a transient
failure in its post-claim tail.

Owner report: the daily-quest sheet showed «Не получилось ответить — попробуй
ещё раз» even though every task was marked «Выполнено · +5 внимания». The +5 is
committed inside ``couple_service.claim_quest``; the event track / dialog echo /
best-effort bonus photo that run *after* that commit are plain DB writes, and a
transient blip there raised out of the (previously unguarded) POST handler as a
raw HTTP 500 whose HTML body the Mini App could not parse — so it rendered the
generic retry string while the quest had in fact counted.

Two guards, mirroring the V3.48.3 GET wrapper:
1. the POST action endpoint is exception-guarded (clean JSON, real cause logged);
2. once the claim is committed, the tail is best-effort and the fresh claim
   always answers ``ok: True`` (the user is never told a counted quest failed).

Static pins only (the suite cannot import the runtime without an LLM key)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def test_feature_action_endpoint_is_exception_guarded():
    # the public name stays the route target; it now wraps a try/except over impl
    assert 'async def _webapp_api_feature_action(request: web.Request) -> web.Response:' in MAIN
    assert 'async def _webapp_api_feature_action_impl(request: web.Request) -> web.Response:' in MAIN
    wrapper = MAIN[MAIN.index('async def _webapp_api_feature_action('):
                   MAIN.index('async def _webapp_api_feature_action_impl(')]
    assert 'return await _webapp_api_feature_action_impl(request)' in wrapper
    assert "logger.exception('webapp feature action failed')" in wrapper
    assert "'temporarily_unavailable'" in wrapper
    # the route still registers the guarded wrapper, not the impl
    assert "add_post('/webapp/api/feature/action', _webapp_api_feature_action)" in MAIN


def test_quest_claim_tail_is_best_effort_after_commit():
    # the whole post-claim tail runs inside one try/except so a transient DB
    # blip never turns a committed +5 into a raw 500
    body = MAIN[MAIN.index('async def _webapp_api_feature_action_impl('):
                MAIN.index('async def _webapp_api_story(')]
    assert 'couple_service.claim_quest(telegram_id, quest_key)' in body
    tail = body[body.index('couple_service.claim_quest(telegram_id, quest_key)'):]
    # the guard opens right after the 409 already-claimed early-return
    assert 'except Exception:' in tail
    assert "logger.exception('webapp quest post-claim tail failed" in tail
    # the echo + bonus run under the guard, not before it
    assert tail.index('try:') < tail.index('save_message(')
    assert tail.index('try:') < tail.index('_deliver_bonus_media(')
    # and the fresh-claim success response is emitted after the guard, so a
    # swallowed tail exception still returns ok: True (compare against the FIRST
    # except — the quest tail's own — not the later date-branch guard)
    quest_return = tail.index("return web.json_response({'ok': True, 'kind': kind, 'text': text,")
    assert quest_return > tail.index('except Exception:')
