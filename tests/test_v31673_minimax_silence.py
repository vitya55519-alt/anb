"""V3.167.3 (владелец, 16.11): его сигнал из кухни —
«🛑 ход чата: провайдеры молчат: MiniMax(MiniMax-M3) ask: empty text
(finish=length); MiniMax(MiniMax-M3) retry: TimeoutError».

Первая попытка в диалоге думала столько, что весь лимит уходил в thinking и
видимого текста не оставалось (пусто + finish=length). Вторая — та же модель,
но уже с малой глубиной размышления — билась в свой 30-секундный таймаут.
Что меняется: low усилие просится с ПЕРВОГО запроса диалога (модель та же),
повтор получает 40 с вместо 30 в пределах тех же 90 с на ход, а в причину
пишется, сколько секунд её ждали. Обе ручки — env: MINIMAX_DIALOGUE_EFFORT и
LLM_RETRY_TIMEOUT_SECONDS.
"""
import asyncio
import logging
import time
from types import SimpleNamespace

import services.llm_provider_service as llm

logging.getLogger('services.llm_provider_service').setLevel(logging.CRITICAL)
LLM_SRC = open(llm.__file__, encoding='utf-8').read()


def _resp(text: str, finish: str = 'stop'):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=finish)],
        usage=None,
    )


class _FakeProvider:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        out = self.outcomes[min(len(self.calls) - 1, len(self.outcomes) - 1)]
        if isinstance(out, BaseException):
            raise out
        if asyncio.iscoroutinefunction(out):
            out = await out()
        return out

    @property
    def chat(self):
        return SimpleNamespace(completions=self)


def _patch(monkeypatch, mm):
    monkeypatch.setattr(llm, '_minimax', mm)
    monkeypatch.setattr(llm, '_gemini', None)
    monkeypatch.setattr(llm, 'LLM_RETRY_PAUSE_SECONDS', 0.0)


def _hang(seconds: float):
    async def _fn():
        await asyncio.sleep(seconds)
        return _resp('не дойдёт')
    return _fn


def test_the_first_dialogue_attempt_already_thinks_less(monkeypatch):
    mm = _FakeProvider([_resp('', 'length'), _resp('да, приезжай 🙈')])
    _patch(monkeypatch, mm)
    out = asyncio.run(llm.generate_text([{'role': 'user', 'content': 'x'}],
                                        max_tokens=40, purpose='dialogue'))
    assert out.text.startswith('да')
    assert mm.calls[0]['reasoning_effort'] == 'low', 'думать меньше — с первого запроса'
    assert mm.calls[1]['reasoning_effort'] == 'low'


def test_the_effort_switch_is_an_env_escape_hatch(monkeypatch):
    # MINIMAX_DIALOGUE_EFFORT= в Railway возвращает прежнюю глубину без правки кода
    mm = _FakeProvider([_resp('обычное размышление 😌')])
    _patch(monkeypatch, mm)
    monkeypatch.setattr(llm, 'MINIMAX_DIALOGUE_EFFORT', '')
    asyncio.run(llm.generate_text([{'role': 'user', 'content': 'x'}],
                                  max_tokens=40, purpose='dialogue'))
    assert 'reasoning_effort' not in mm.calls[0]


def test_only_the_dialogue_asks_for_less_thinking(monkeypatch):
    mm = _FakeProvider([_resp('момент'), _resp('момент')])
    _patch(monkeypatch, mm)
    asyncio.run(llm.generate_text([{'role': 'user', 'content': 'x'}],
                                  max_tokens=40, purpose='life_event'))
    assert 'reasoning_effort' not in mm.calls[0], 'её жизнь пишет та же модель, что и раньше'


def test_the_retry_gets_more_time_than_the_first_attempt(monkeypatch):
    # обе попытки висят: первая режется своимполом среза в 1 с), вторая — своим
    # (5 с) и успевает ответить. Пол у среза нарочито маленький, чтобы тест
    # считал секунды, а не ждал настоящих 30.
    mm = _FakeProvider([_hang(2.0), _hang(1.5)])
    _patch(monkeypatch, mm)
    monkeypatch.setattr(llm, 'LLM_TIMEOUT_SECONDS', 0.1)
    monkeypatch.setattr(llm, 'LLM_RETRY_TIMEOUT_SECONDS', 5.0)
    monkeypatch.setattr(llm, 'LLM_CHAIN_BUDGET_SECONDS', 90.0)
    started = time.monotonic()
    out = asyncio.run(llm.generate_text([{'role': 'user', 'content': 'x'}],
                                        max_tokens=40, purpose='dialogue'))
    elapsed = time.monotonic() - started
    assert len(mm.calls) == 2
    assert out.text == 'не дойдёт', f'повтор умер раньше своего времени: {out.text!r}'
    assert 1.5 <= elapsed < 4.0, f'ход шёл {elapsed:.1f} с'


def test_the_reason_carries_the_seconds_it_waited(monkeypatch):
    mm = _FakeProvider([_resp('', 'length'), _hang(5.0)])
    _patch(monkeypatch, mm)
    monkeypatch.setattr(llm, 'LLM_TIMEOUT_SECONDS', 0.2)
    monkeypatch.setattr(llm, 'LLM_RETRY_TIMEOUT_SECONDS', 0.3)
    monkeypatch.setattr(llm, 'LLM_CHAIN_BUDGET_SECONDS', 90.0)
    out = asyncio.run(llm.generate_text([{'role': 'user', 'content': 'x'}],
                                        max_tokens=40, purpose='dialogue'))
    assert out.text == ''
    assert 'empty text (finish=length) [waited' in out.error, out.error
    assert ' of 0.2s]' in out.error, out.error
    assert 'TimeoutError' in out.error and ' of 0.3s]' in out.error, out.error
    assert 'retry' in out.error and 'ask' in out.error


def test_the_turn_still_never_runs_past_the_chain_budget(monkeypatch):
    mm = _FakeProvider([_hang(30.0), _hang(30.0)])
    _patch(monkeypatch, mm)
    monkeypatch.setattr(llm, 'LLM_CHAIN_BUDGET_SECONDS', 1.0)
    started = time.monotonic()
    try:
        out, raised = None, ''
        asyncio.run(llm.generate_text([{'role': 'user', 'content': 'x'}],
                                      max_tokens=40, purpose='dialogue'))
    except RuntimeError as exc:
        out, raised = None, str(exc)
    waited = time.monotonic() - started
    assert waited < 5.0, f'ход ждал провайдера {waited:.1f} с'
    assert 'TimeoutError' in raised, raised
    assert out is None


def test_static_switches():
    assert "MINIMAX_DIALOGUE_EFFORT = os.getenv('MINIMAX_DIALOGUE_EFFORT', 'low').strip()" in LLM_SRC
    assert "LLM_RETRY_TIMEOUT_SECONDS = _env_float('LLM_RETRY_TIMEOUT_SECONDS', 40.0)" in LLM_SRC
    assert "mm_kwargs['reasoning_effort'] = MINIMAX_DIALOGUE_EFFORT" in LLM_SRC
    assert 'MINIMAX_ATTEMPTS = 2' in LLM_SRC, 'третьей попытки по-прежнему нет'
