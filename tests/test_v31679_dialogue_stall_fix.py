"""V3.167.9 (владелец, скрин 16.11) в форме V3.167.1 (СРОЧНО, «стоп по новым
релизам»).

1) пустая цепочка провайдеров была тихой — ход уходил в запасную фразу, а
   владелец не знал, кто именно молчит; причина по-прежнему доезжает до хука;
2) её же запасные фразы лежали в истории и модель подхватывала их как свою
   манеру говорить — диалог ходил по кругу. Пул отравошников выпилен совсем
   (V3.167.1), старые строки лишь фильтруются из промпта как legacy-история;
3) у цепочки не было общего бюджета: висящий primary с запасными держал его в
   «печатает…» полторы минуты. Схема хода: прямой MiniMax (30 с) → авто-повтор
   MiniMax (30 с) → нейтральная заглушка про связь; бюджет хода 90 с.
Модель та же — MiniMax M3; повтор после пустого ответа просит меньшую глубину
размышления. Gemini из диалога убран (429 на каждую вторую реплику), чат-
агрегатор выпилен (его лег отвечал ровно 401 на тот же ключ).
"""
import asyncio
import logging
import time
from pathlib import Path
from types import SimpleNamespace

import services.chat_service as cs
import services.llm_provider_service as llm
from services.chat_service import STUB_REPLY_RU, _RETIRED_STALL_LINES, is_stall_line
from services.llm_provider_service import LLMResult
from services.memory_service import get_recent_messages, save_message
from services.user_service import ensure_user

logging.getLogger('services.llm_provider_service').setLevel(logging.CRITICAL)
logging.getLogger('services.chat_service').setLevel(logging.CRITICAL)

CHAT = open(cs.__file__, encoding='utf-8').read()
LLM_SRC = open(llm.__file__, encoding='utf-8').read()
MAIN = open(Path(cs.__file__).parent.parent / 'main.py', encoding='utf-8').read()


def _resp(text: str, finish: str = 'stop'):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=finish)],
        usage=None,
    )


class _FakeProvider:
    """chat.completions.create: i-й вызов получает i-й исход. Исключение —
    исключение, корутина — ожидание, остальное — ответ."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        out = self.outcomes[min(len(self.calls) - 1, len(self.outcomes) - 1)]
        if isinstance(out, BaseException):
            raise out
        if asyncio.iscoroutinefunction(out) or asyncio.iscoroutine(out):
            out = await out()
        return out

    @property
    def chat(self):
        return SimpleNamespace(completions=self)


async def _slow():
    await asyncio.sleep(10)
    return _resp('не дойдёт')


# ── 2. legacy-отговорки не попадают в промпт ────────────────────────────

def test_retired_stall_lines_are_recognised_through_emoji_and_truncation():
    for line in _RETIRED_STALL_LINES:
        assert is_stall_line(line), line
        # diversify_emoji меняет только смайлик
        assert is_stall_line(line.replace('😌', '😇').replace('🙈', '🙊').replace('😏', '😔')), line
        # обрезанная строка всё равно её: совпадение по началу
        assert is_stall_line(line[:16]), line
    assert not is_stall_line('мм, идём уже домой или ты ещё в маршрутке?')
    assert not is_stall_line('ок')
    assert not is_stall_line('')


def test_the_pool_of_excuse_lines_is_gone():
    # V3.167.1: у неё больше нет пула живых отравошников — одна строка в коде.
    assert 'def stall_line(' not in CHAT
    assert 'STALL_LINES_RU' not in CHAT


def _seed(tid: int, name: str, extra_assistant=()) -> int:
    uid = ensure_user(tid, name, language_code='ru')
    for i in range(12):
        save_message(uid, 'anna_01', 'user', f'привет {i}')
    for text in extra_assistant:
        save_message(uid, 'anna_01', 'assistant', text)
    return uid


def test_her_own_stall_lines_leave_the_prompt(monkeypatch):
    tid = 559101
    _seed(tid, 'stallloop', extra_assistant=[
        'да, и очень хочу 🔥',
        _RETIRED_STALL_LINES[0],                    # её запасная, ещё раз
        _RETIRED_STALL_LINES[1].replace('😌', '😇'),  # та же, но смайлик другой
    ])
    seen = []

    async def fake(messages, **kw):
        if kw.get('purpose') == 'dialogue':
            seen.append(messages)
        return LLMResult('МЫСЛИ: думаю о тебе\nMESSAGE: скучала 🙈', 'test', 'test')

    monkeypatch.setattr(cs, 'generate_text', fake)
    answer = asyncio.run(cs.reply(tid, 'stallloop', 'расскажи, как день', language_code='ru'))
    assert 'скучала' in answer
    contents = [m['content'] for m in seen[0]]
    assert not any(is_stall_line(c) for c in contents), contents
    assert any('скучала' not in c and 'очень хочу' in c for c in contents), 'живая её строка осталась'


# ── 1. причина пустой цепочки ──────────────────────────────────────────

def test_empty_chain_reason_reaches_the_owner(monkeypatch):
    tid = 559102
    _seed(tid, 'emptyreason')
    notes = []

    async def hook(user_id, where, exc):
        notes.append((user_id, where, str(exc)))

    async def fake(messages, **kw):
        return LLMResult('', 'minimax', 'MiniMax-M3', True,
                         'MiniMax(MiniMax-M3): empty text (finish=length)')

    monkeypatch.setattr(cs, 'generate_text', fake)
    monkeypatch.setattr(cs, 'llm_failure_hook', hook)
    answer = asyncio.run(cs.reply(tid, 'emptyreason', 'приезжай ко мне', language_code='ru'))
    assert answer == STUB_REPLY_RU, answer
    assert notes and notes[0][0] == tid
    assert 'finish=length' in notes[0][2]


def test_provider_exception_reason_reaches_the_hook(monkeypatch):
    tid = 559103
    _seed(tid, 'crashreason')
    notes = []

    async def hook(user_id, where, exc):
        notes.append(str(exc))

    async def fake(messages, **kw):
        raise RuntimeError('LLM unavailable: MiniMax(MiniMax-M3): APIStatusError: balance')

    monkeypatch.setattr(cs, 'generate_text', fake)
    monkeypatch.setattr(cs, 'llm_failure_hook', hook)
    answer = asyncio.run(cs.reply(tid, 'crashreason', 'целую, я поехал', language_code='ru'))
    assert answer == STUB_REPLY_RU, answer
    assert notes and 'balance' in notes[0]


def test_gen_carries_the_reason_and_main_wires_the_hook():
    async def boom(messages, **kw):
        raise RuntimeError('LLM unavailable: no providers configured')

    original = cs.generate_text
    cs.generate_text = boom
    try:
        out = asyncio.run(cs._gen([{'role': 'user', 'content': 'x'}], max_tokens=10, purpose='dialogue'))
    finally:
        cs.generate_text = original
    assert out.text == '' and out.provider == 'failed'
    assert 'no providers configured' in out.error
    assert 'chat_service.llm_failure_hook = _notify_turn_failure' in MAIN
    assert 'await _report_llm_failure(' in CHAT


# ── 3. бюджет хода, две попытки, никакого запасного провайдера ──────────

def _patch_chain(monkeypatch, minimax=None, gemini=None):
    monkeypatch.setattr(llm, '_minimax', minimax)
    monkeypatch.setattr(llm, '_gemini', gemini)
    # V3.167.1: между попытками стоит пауза; ждать её в тесте незачем.
    monkeypatch.setattr(llm, 'LLM_RETRY_PAUSE_SECONDS', 0.0)


def test_chain_budget_cuts_a_hung_provider(monkeypatch):
    _patch_chain(monkeypatch, minimax=_FakeProvider([_slow]))
    monkeypatch.setattr(llm, 'LLM_CHAIN_BUDGET_SECONDS', 1.0)
    started = time.monotonic()
    try:
        out = asyncio.run(llm.generate_text([{'role': 'user', 'content': 'x'}], max_tokens=40))
        raised = ''
    except RuntimeError as exc:
        out, raised = None, str(exc)
    waited = time.monotonic() - started
    assert waited < 5.0, f'ход ждал провайдера {waited:.1f} с'
    assert 'TimeoutError' in raised, raised
    assert out is None


def test_empty_dialogue_retry_asks_for_less_thinking(monkeypatch):
    mm = _FakeProvider([_resp('', 'length'), _resp('да, приезжай 🙈')])
    _patch_chain(monkeypatch, minimax=mm)
    out = asyncio.run(llm.generate_text([{'role': 'user', 'content': 'x'}], max_tokens=40, purpose='dialogue'))
    assert out.text.startswith('да')
    assert len(mm.calls) == 2
    assert mm.calls[1]['reasoning_effort'] == 'low'


def test_second_empty_answer_does_not_ask_a_third_time(monkeypatch):
    # V3.167.1 (владелец, Q1): третьей попытки и запасного провайдера нет —
    # после глухого повтора ход отдаёт нейтральную заглушку про связь.
    mm = _FakeProvider([_resp('', 'length'), _resp('', 'length'), _resp('не дойдёт')])
    gem = _FakeProvider([_resp('наконец-то я тут 😌')])
    _patch_chain(monkeypatch, minimax=mm, gemini=gem)
    out = asyncio.run(llm.generate_text([{'role': 'user', 'content': 'x'}], max_tokens=40, purpose='dialogue'))
    assert len(mm.calls) == 2, 'повтор один, дальше — заглушка'
    assert len(gem.calls) == 0, 'текст она у Gemini не просит'
    assert out.text == '' and out.provider == 'minimax'


def test_a_crash_on_the_retry_does_not_buy_a_third_attempt(monkeypatch):
    mm = _FakeProvider([_resp('', 'length'),
                        TypeError("create() got unexpected keyword 'reasoning_effort'")])
    _patch_chain(monkeypatch, minimax=mm)
    out = asyncio.run(llm.generate_text([{'role': 'user', 'content': 'x'}], max_tokens=40, purpose='dialogue'))
    assert len(mm.calls) == 2
    assert out.text == '' and 'TypeError' in out.error


def test_empty_result_always_carries_a_reason(monkeypatch):
    mm = _FakeProvider([_resp('', 'length'), _resp('', 'length')])
    _patch_chain(monkeypatch, minimax=mm)
    out = asyncio.run(llm.generate_text([{'role': 'user', 'content': 'x'}], max_tokens=40, purpose='dialogue'))
    assert out.text == ''
    assert 'MiniMax' in out.error and 'finish=length' in out.error, out.error


def test_static_budget_and_hook_shape():
    assert "LLM_CHAIN_BUDGET_SECONDS = _env_float('LLM_CHAIN_BUDGET_SECONDS', 90.0)" in LLM_SRC
    assert "LLM_TIMEOUT_SECONDS = _env_float('LLM_TIMEOUT_SECONDS', 30.0)" in LLM_SRC
    assert 'MINIMAX_ATTEMPTS = 2' in LLM_SRC
    assert 'def _slice(cap: float) -> float:' in LLM_SRC
    assert 'timeout=_slice(LLM_TIMEOUT_SECONDS)' in LLM_SRC
    assert "error=f'{type(exc).__name__}: {str(exc)[:300]}'" in CHAT
    assert "if not (m.role == 'assistant' and is_stall_line(m.content))]" in CHAT


def test_the_stub_never_enters_the_dialogue_history(monkeypatch):
    # V3.167.1 (владелец): его строка остаётся (он её писал), её заглушка — нет.
    tid = 559104
    uid = _seed(tid, 'stubnotstored')

    async def fake(messages, **kw):
        return LLMResult('', 'minimax', 'MiniMax-M3', True, 'MiniMax: TimeoutError')

    monkeypatch.setattr(cs, 'generate_text', fake)
    before = len([m for m in get_recent_messages(uid, 'anna_01', 200) if m.role == 'assistant'])
    answer = asyncio.run(cs.reply(tid, 'stubnotstored', 'ты там?', language_code='ru'))
    assert answer == STUB_REPLY_RU
    after = get_recent_messages(uid, 'anna_01', 200)
    assert len([m for m in after if m.role == 'assistant']) == before, 'заглушка не сохранена'
    assert STUB_REPLY_RU not in [m.content for m in after]
    assert any('ты там?' in m.content for m in after), 'его строка сохранена'
