"""V3.57.8 — faster replies + no third hand in photos.

1. The chat reply no longer waits for memory extraction / style analysis
   (two extra LLM round trips the user never reads): they run in the background.
2. LLM clients carry explicit timeouts; the primary provider has no SDK retries,
   so a hung provider falls through to the next one in ~25 s, not ~10 minutes.
3. Owner screenshot: a mirror selfie with the «shush» mimicry rendered THREE
   hands (finger at lips + phone + hand on hip). Hand-gesture expressions now
   use the free hand only, and every prompt carries a two-hands rule.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
LLM = (ROOT / 'services' / 'llm_provider_service.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
EXPR = (ROOT / 'services' / 'photo_expression_service.py').read_text(encoding='utf-8')


def _reply_body() -> str:
    start = CHAT.index('async def reply(')
    return CHAT[start:CHAT.index('async def proactive_reply(')]


def test_reply_does_not_await_memory_extraction():
    body = _reply_body()
    assert 'await asyncio.gather(' not in body
    assert "_spawn_background(extract_memory(" in body
    assert "_spawn_background(maybe_analyze_profile(" in body


def test_background_tasks_are_kept_alive_and_guarded():
    assert '_BACKGROUND_TASKS: set[asyncio.Task] = set()' in CHAT
    assert '_BACKGROUND_TASKS.add(task)' in CHAT
    assert 'task.add_done_callback(_BACKGROUND_TASKS.discard)' in CHAT


def test_adaptation_context_built_once():
    assert _reply_body().count('build_adaptation_context(') == 1


def test_llm_clients_have_timeouts():
    assert "LLM_TIMEOUT_SECONDS = _env_float('LLM_TIMEOUT_SECONDS', 25.0)" in LLM
    for client in ('_minimax', '_gemini'):
        block = LLM[LLM.index(f'{client} = ('):]
        block = block[:block.index('\n)\n')]
        assert 'timeout=LLM_TIMEOUT_SECONDS' in block and 'max_retries=0' in block
    block = LLM[LLM.index('_openrouter = ('):]
    block = block[:block.index('\n)\n')]
    assert 'timeout=LLM_FALLBACK_TIMEOUT_SECONDS' in block


def test_hand_gesture_expressions_use_the_free_hand():
    for key in ("'shush'", "'blow_kiss'"):
        start = EXPR.index(key + ': (')
        block = EXPR[start:EXPR.index('),', start)]
        assert 'free hand' in block and 'exactly two hands' in block


def test_prompt_carries_two_hands_rule():
    assert 'HANDS_RULE = (' in PHOTO and 'exactly two arms and two hands' in PHOTO
    assert "f'{HANDS_RULE}\\n'" in PHOTO
    neg = PHOTO[PHOTO.index('NEGATIVE_BLOCK = ('):PHOTO.index('@dataclass(frozen=True)\nclass GeneratedPhoto')]
    assert 'a third hand or arm' in neg
