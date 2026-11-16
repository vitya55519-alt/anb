"""V3.167.9 (владелец, скрин 16.11): «мыслей нет, он троит общение, и долго
ответ идет».

Три дыры, три проверки:
1) пустая цепочка провайдеров была тихой — ход уходил в запасную фразу, а
   владелец не знал, кто именно молчит;
2) её же запасная фраза лежала в истории и модель подхватывала её как свою
   манеру говорить — диалог ходил по кругу;
3) у цепочки не было общего бюджета: висящий primary с запасными держал его в
   «печатает…» полторы минуты.
Модель та же — MiniMax M3; повтор после пустого ответа просто просит меньшую
глубину размышления.
"""
import asyncio
import logging
import time
from pathlib import Path
from types import SimpleNamespace

import services.chat_service as cs
import services.llm_provider_service as llm
from services.chat_service import STALL_LINES_RU, is_stall_line, stall_line
from services.llm_provider_service import LLMResult
from services.memory_service import save_message
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


# ── 2. цикл самоповтора ────────────────────────────────────────────────

def test_stall_line_is_recognised_through_emoji_and_truncation():
    for line in STALL_LINES_RU:
        assert is_stall_line(line), line
        # diversify_emoji меняет только смайлик
        assert is_stall_line(line.replace('😌', '😇').replace('🙈', '🙊').replace('😏', '😔')), line
        # обрезанная строка всё равно её: совпадение по началу
        assert is_stall_line(line[:16]), line
    assert not is_stall_line('мм, идём уже домой или ты ещё в маршрутке?')
    assert not is_stall_line('ок')
    assert not is_stall_line('')


def test_stall_choice_does_not_repeat_the_same_line_under_another_emoji():
    line = STALL_LINES_RU[0]
    recent = [x.replace('😌', '😇').replace('🙈', '🙊').replace('😏', '😔')
              for x in STALL_LINES_RU if x != line]
    assert stall_line('ru', recent) == line


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
        STALL_LINES_RU[0],                       # её запасная, ещё раз
        STALL_LINES_RU[1].replace('😌', '😇'),   # та же, но смайлик другой
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
    assert answer in STALL_LINES_RU, answer
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
    assert answer in STALL_LINES_RU, answer
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


# ── 3. общий бюджет хода и дешёвый повтор ──────────────────────────────

def _patch_chain(monkeypatch, minimax=None, gemini=None, openrouter=None):
    monkeypatch.setattr(llm, '_minimax', minimax)
    monkeypatch.setattr(llm, '_gemini', gemini)
    monkeypatch.setattr(llm, '_openrouter', openrouter)


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
    mm = _FakeProvider([_resp('', 'length'), _resp('', 'length'), _resp('не дойдёт')])
    gem = _FakeProvider([_resp('наконец-то я тут 😌')])
    _patch_chain(monkeypatch, minimax=mm, gemini=gem)
    out = asyncio.run(llm.generate_text([{'role': 'user', 'content': 'x'}], max_tokens=40, purpose='dialogue'))
    assert len(mm.calls) == 2, 'повтор один, дальше — запасной провайдер'
    assert out.provider == 'gemini' and 'наконец-то' in out.text
    assert out.error == ''


def test_unknown_parameter_falls_back_to_the_plain_retry(monkeypatch):
    mm = _FakeProvider([_resp('', 'length'),
                        TypeError("create() got unexpected keyword 'reasoning_effort'"),
                        _resp('я всё равно рядом 💛')])
    _patch_chain(monkeypatch, minimax=mm)
    out = asyncio.run(llm.generate_text([{'role': 'user', 'content': 'x'}], max_tokens=40, purpose='dialogue'))
    assert 'reasoning_effort' in mm.calls[1] and 'reasoning_effort' not in mm.calls[2]
    assert 'рядом' in out.text


def test_empty_result_always_carries_a_reason(monkeypatch):
    mm = _FakeProvider([_resp('', 'length'), _resp('', 'length')])
    gem = _FakeProvider([_resp('')])
    _patch_chain(monkeypatch, minimax=mm, gemini=gem)
    out = asyncio.run(llm.generate_text([{'role': 'user', 'content': 'x'}], max_tokens=40, purpose='dialogue'))
    assert out.text == ''
    assert 'MiniMax' in out.error and 'finish=length' in out.error, out.error


def test_static_budget_and_hook_shape():
    assert "LLM_CHAIN_BUDGET_SECONDS = _env_float('LLM_CHAIN_BUDGET_SECONDS', 55.0)" in LLM_SRC
    assert 'def _slice(cap: float, reserve: float = 0.0) -> float:' in LLM_SRC
    assert 'timeout=_slice(LLM_TIMEOUT_SECONDS, LLM_FALLBACK_RESERVE_SECONDS)' in LLM_SRC
    assert "error=f'{type(exc).__name__}: {str(exc)[:300]}'" in CHAT
    assert "if not (m.role == 'assistant' and is_stall_line(m.content))]" in CHAT
