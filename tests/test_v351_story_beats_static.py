"""V3.51.0: real branching — every canonical route carries a second "beat".
All 16 stories x 2 routes (32 pairs) must have a QUEST_BRANCHES entry with a
prompt and at least two options carrying the full inline payload (label /
result / reaction / memory / inclination), so the choice actually moves the
path and reads as authored content. ``complete_beat`` is idempotent and only
accepts the canonical route. The bot beat callback and the Mini App action
endpoint are wired to the same resolvers.

Structural checks parse the source with ``ast`` (no import -> no LLM/DB key
needed), matching the static style of the other V3.x pins."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUESTS_SRC = (ROOT / 'services' / 'quest_service.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def _literal(name):
    tree = ast.parse(QUESTS_SRC)
    for node in tree.body:
        names = []
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        if name in names and getattr(node, 'value', None) is not None:
            return ast.literal_eval(node.value)
    raise AssertionError(f'{name} not found as a literal assignment')


QUESTS = _literal('QUESTS')
BRANCHES = _literal('QUEST_BRANCHES')


def test_sixteen_stories_and_full_route_coverage():
    assert len(QUESTS) == 16
    pairs = {(q, r) for q, v in QUESTS.items() for r in v['routes']}
    assert len(pairs) == 32
    # every (quest, route) pair has a branch, and no branch points nowhere
    missing = [p for p in pairs if p not in BRANCHES]
    assert not missing, f'routes without a branch: {missing}'
    assert not [p for p in BRANCHES if p not in pairs]


def test_each_branch_has_prompt_and_two_complete_options():
    required = ('label', 'result', 'reaction', 'memory', 'inclination')
    for key, branch in BRANCHES.items():
        assert branch.get('prompt'), f'{key} has no beat prompt'
        opts = branch.get('options') or {}
        assert len(opts) >= 2, f'{key} has fewer than two beat options'
        for ok, opt in opts.items():
            for field in required:
                assert opt.get(field), f'{key}/{ok} missing {field}'
            assert opt['inclination'] in ('romance', 'bold', 'neutral'), f'{key}/{ok} bad inclination'


def test_beat_inclinations_stay_out_of_route_inclination_map():
    # V3.50 pins: the beat nudges ride inline on the option, never the shared
    # ROUTE_INCLINATION table, so the existing axis assertions stay intact.
    assert 'ROUTE_INCLINATION = {' in QUESTS_SRC
    assert "opt.get('inclination', 'neutral')" in QUESTS_SRC


def test_complete_beat_requires_canonical_and_is_idempotent():
    assert 'def complete_beat(telegram_id: int, quest_key: str, route_key: str, opt_key: str, character_id: str | None = None) -> dict:' in QUESTS_SRC
    # only the canonical first route may be continued
    assert "if not row or row.canonical_route != route_key:" in QUESTS_SRC
    assert "return {'error': 'not_canonical'}" in QUESTS_SRC
    # a `route#option` token makes the beat one-shot (can't farm the axis)
    assert "token = f'{route_key}#{opt_key}'" in QUESTS_SRC
    assert "first = token not in done" in QUESTS_SRC
    assert "if first:" in QUESTS_SRC


def test_bot_beat_callback_and_mini_app_action_are_wired():
    assert "@dp.callback_query(F.data.startswith('quest:beat:'))" in MAIN
    assert 'async def quest_beat_cb(' in MAIN
    assert 'callback_data=f\'quest:beat:{quest_key}:{route_key}:{opt_key}\'' in MAIN
    assert "app.router.add_post('/webapp/api/story/action', _webapp_api_story_action)" in MAIN
    assert "app.router.add_get('/webapp/api/story', _webapp_api_story)" in MAIN
