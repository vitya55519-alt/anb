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

V3.167.4 (второй его сигнал, уже с замером): «ask: TimeoutError [waited 30.0s
of 30s]; retry: APITimeoutError [waited 30.1s of 40s]». Повтор умер на 30.1 с,
хотя ему дали 40 — срез до провайдера не доходил: AsyncOpenAI построен с
timeout=30 и каждый вызов наследовал именно его. Теперь срез едет в сам create
(+наружняя страховка на коннект), диалог ждёт 40 с с первой попытки, а в
причине лежит ещё и размер отправленного запроса.

V3.167.11 (его же выбор после замеров): 40 с первая попытка больше не держит
ответ ~1000 токенов, поэтому срез диалога вырос до 70 с, а повтор урезается до
остатка бюджета хода — цифры в tests/test_v316711_dialogue_slice.py.
"""
import asyncio
import logging
import time
from types import SimpleNamespace

import pytest

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
    # страховка на коннект в тестах ноль: иначе фальшивое зависание на 2 с
    # успевает «ответить» внутри наружного таймаута, и тест меряет не срез
    monkeypatch.setattr(llm, 'LLM_SLICE_GUARD_SECONDS', 0.0)


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
    assert mm.calls[0]['extra_body'] == {'thinking': {'type': 'disabled'}}
    assert mm.calls[1]['extra_body'] == {'thinking': {'type': 'disabled'}}
    assert all('reasoning_effort' not in call for call in mm.calls)


def test_the_effort_switch_does_not_reenable_m3_thinking(monkeypatch):
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
    # обе попытки висят: первая режется своим половинчатым срезом (1 с), вторая —
    # своим (5 с) и успевает ответить. Пол у среза нарочито маленький, чтобы тест
    # считал секунды, а не ждал настоящих 40.
    mm = _FakeProvider([_hang(2.0), _hang(1.5)])
    _patch(monkeypatch, mm)
    monkeypatch.setattr(llm, 'LLM_DIALOGUE_TIMEOUT_SECONDS', 0.1)
    monkeypatch.setattr(llm, 'LLM_RETRY_TIMEOUT_SECONDS', 5.0)
    monkeypatch.setattr(llm, 'LLM_CHAIN_BUDGET_SECONDS', 90.0)
    started = time.monotonic()
    out = asyncio.run(llm.generate_text([{'role': 'user', 'content': 'x'}],
                                        max_tokens=40, purpose='dialogue'))
    elapsed = time.monotonic() - started
    assert len(mm.calls) == 2
    assert out.text == 'не дойдёт', f'повтор умер раньше своего времени: {out.text!r}'
    assert 1.5 <= elapsed < 4.0, f'ход шёл {elapsed:.1f} с'


def test_the_slice_now_reaches_the_provider_itself(monkeypatch):
    # V3.167.4: его сигнал показал, что повтор умер на 30.1 с при срезе в 40 —
    # таймаут клиента был длиннее, чем запрос. Срез обязан уходить в create(),
    # а не только наружу лежать.
    mm = _FakeProvider([_resp('есть')])
    _patch(monkeypatch, mm)
    monkeypatch.setattr(llm, 'LLM_DIALOGUE_TIMEOUT_SECONDS', 7.5)
    asyncio.run(llm.generate_text([{'role': 'user', 'content': 'x'}],
                                  max_tokens=40, purpose='dialogue'))
    assert mm.calls[0]['timeout'] == 7.5, mm.calls[0]
    assert 'timeout=slice_seconds' in LLM_SRC, 'срез провайдера, а не только наружный'
    assert 'timeout=max(LLM_TIMEOUT_SECONDS, LLM_DIALOGUE_TIMEOUT_SECONDS' in LLM_SRC, \
        'клиент больше не короче самого длинного среза'


def test_a_small_dialogue_gets_real_time(monkeypatch):
    # схема хода: диалог ждёт со своей первой попытки дольше всех (V3.167.11 — 70 с),
    # вспомогательные вызовы — 30
    mm = _FakeProvider([_resp('да, приезжай 🙈'), _resp('да, приезжай 🙈')])
    _patch(monkeypatch, mm)
    asyncio.run(llm.generate_text([{'role': 'user', 'content': 'x'}],
                                  max_tokens=40, purpose='dialogue'))
    assert mm.calls[0]['timeout'] == llm.LLM_DIALOGUE_TIMEOUT_SECONDS == 70.0, mm.calls[0]['timeout']
    mm2 = _FakeProvider([_resp('момент'), _resp('момент')])
    _patch(monkeypatch, mm2)
    asyncio.run(llm.generate_text([{'role': 'user', 'content': 'x'}],
                                  max_tokens=40, purpose='life_event'))
    assert mm2.calls[0]['timeout'] == 30.0, mm2.calls[0]['timeout']


def test_the_reason_carries_the_seconds_it_waited(monkeypatch):
    mm = _FakeProvider([_resp('', 'length'), _hang(5.0)])
    _patch(monkeypatch, mm)
    monkeypatch.setattr(llm, 'LLM_DIALOGUE_TIMEOUT_SECONDS', 0.2)
    monkeypatch.setattr(llm, 'LLM_RETRY_TIMEOUT_SECONDS', 0.3)
    monkeypatch.setattr(llm, 'LLM_CHAIN_BUDGET_SECONDS', 90.0)
    out = asyncio.run(llm.generate_text([{'role': 'user', 'content': 'x'}],
                                        max_tokens=40, purpose='dialogue'))
    assert out.text == ''
    assert 'empty text (finish=length) [waited' in out.error, out.error
    assert 'of 0.2s, sent' in out.error, out.error
    assert 'TimeoutError' in out.error and 'of 0.3s, sent' in out.error, out.error
    assert 'retry' in out.error and 'ask' in out.error


def test_the_reason_says_how_much_was_sent(monkeypatch):
    # «M3 молчит» и «M3 молчит под промптом в 40 тыс. знаков» — разные истории;
    # без этой цифры вторая лечится вслепую
    mm = _FakeProvider([_hang(5.0), _hang(5.0)])
    _patch(monkeypatch, mm)
    monkeypatch.setattr(llm, 'LLM_DIALOGUE_TIMEOUT_SECONDS', 0.1)
    monkeypatch.setattr(llm, 'LLM_RETRY_TIMEOUT_SECONDS', 0.1)
    monkeypatch.setattr(llm, 'LLM_CHAIN_BUDGET_SECONDS', 90.0)
    # молчание по таймауту — это исключение (пустой ответ по finish=length — нет)
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(llm.generate_text([{'role': 'user', 'content': 'y' * 2500}],
                                      max_tokens=40, purpose='dialogue'))
    # V3.167.10: рядом токены — «2.5k» в журнале читалось как тысячи токенов
    assert 'sent 2.5k знаков' in str(exc.value), str(exc.value)


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
