"""V3.50.1: the app-chat «Задание» button broke because the GET feature
endpoint's daily-quest branch used ``couple_service`` without importing it in
``_webapp_api_feature_impl``. The V3.48.3 exception wrapper turned that
NameError into a silent ``temporarily_unavailable``, so the sheet only showed
«Не получилось ответить». Static regression pin (the suite cannot import the
runtime without an LLM key): assert the local import exists AND precedes the
first ``couple_service`` use inside each feature function body."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def _func_body(marker: str) -> str:
    start = MAIN.index(marker)
    rest = MAIN[start:]
    nxt = rest.find('\nasync def ', len(marker))
    return rest[:nxt] if nxt != -1 else rest


def test_get_feature_branch_imports_couple_service_before_use():
    body = _func_body('async def _webapp_api_feature_impl(')
    assert 'from services import couple_service' in body, (
        'GET feature endpoint must import couple_service locally before the '
        'daily-quest fall-through branch'
    )
    assert body.index('from services import couple_service') < body.index(
        'couple_service.daily_quests_state('
    ), 'the import must precede the first couple_service use in the function'


def test_post_action_branch_still_imports_before_claim():
    # V3.55.7: the action body moved into _webapp_api_feature_action_impl behind
    # the new exception-guarded wrapper (mirroring the GET _impl); anchor there.
    body = _func_body('async def _webapp_api_feature_action_impl(')
    assert 'from services import couple_service' in body
    assert body.index('from services import couple_service') < body.index(
        'couple_service.claim_quest('
    )
