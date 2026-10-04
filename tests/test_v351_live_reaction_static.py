"""V3.51.0: the live reaction after a story choice. The shared resolver tail
(``_finalize_choice``) asks the LLM for one short in-character line through
``chat_service.story_reaction`` and, on any exception or empty output, falls
back to the curated ``reaction`` shipped on the option/route. The winning line
is written exactly once into the shared dialog (assistant) so both the bot and
the Mini App show it. ``story_reaction`` is fully fail-silent. Static pins, in
the style of the other V3.x files."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUESTS_SRC = (ROOT / 'services' / 'quest_service.py').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')


def test_finalize_choice_calls_the_llm_in_a_guard_and_falls_back():
    assert 'async def _finalize_choice(' in QUESTS_SRC
    assert 'reaction = await chat_service.story_reaction(' in QUESTS_SRC
    tail = QUESTS_SRC[QUESTS_SRC.index('async def _finalize_choice('):QUESTS_SRC.index('async def resolve_story_choice(')]
    assert 'try:' in tail and 'except Exception:' in tail
    # generation lives before the except, and the curated line is the fallback
    assert tail.index('await chat_service.story_reaction') < tail.index('except Exception:')
    assert "reaction = (curated_reaction or '').strip()" in tail
    assert 'if not reaction:' in tail


def test_reaction_persisted_once_to_shared_dialog():
    assert "save_message(uid, character_id, 'assistant', reaction)" in QUESTS_SRC
    tail = QUESTS_SRC[QUESTS_SRC.index('async def _finalize_choice('):QUESTS_SRC.index('async def resolve_story_choice(')]
    # only saved when non-empty (one write per choice)
    assert "if reaction:" in tail
    assert tail.count("save_message(uid, character_id, 'assistant', reaction)") == 1


def test_story_reaction_is_async_dialogue_and_fail_silent():
    assert 'async def story_reaction(' in CHAT
    assert "purpose='dialogue'" in CHAT
    tail = CHAT[CHAT.index('async def story_reaction('):]
    assert 'try:' in tail
    # any error returns an empty string -> the caller uses the curated fallback
    assert tail.rstrip().endswith("return ''")
    assert 'return out[:400]' in tail
