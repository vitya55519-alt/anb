"""V3.167.11 (его выбор после замеров 16.11): «дать одной попытке 60–70 секунд».

Причина: с 11 по 15 ноя ответ в диалоге вырос до ~1000 токенов (медиана), а
размышление перед ним — до ~824. На это 40 с перестало хватать, и попытка
умирала ровно на своём срезе («waited 40.1s of 40s»). Первая попытка диалога
теперь ждёт 70 с.

Его же правило «ход ≤ 90 с» остаётся в силе, поэтому срез повтора режется до
того, что реально осталось у хода: раньше в причине лежала цифра, которую
попытка от силы не жила (SDK ждал 40 с, а наружный таймаут снимал на остатке).
"""
import asyncio
import logging
import time
from types import SimpleNamespace

import pytest

import services.llm_provider_service as llm

logging.getLogger('services.llm_provider_service').setLevel(logging.CRITICAL)
LLM_SRC = open(llm.__file__, encoding='utf-8').read()


def _resp(text: str = 'не дойдёт'):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason='stop')],
        usage=None,
    )


class _FakeProvider:
    def __init__(self, delays):
        self.delays = list(delays)
        self.calls = []

    async def create(self, **kwargs):
        waited = self.delays[min(len(self.calls) - 1, len(self.delays) - 1)]
        self.calls.append(kwargs)
        await asyncio.sleep(waited)
        return _resp()

    @property
    def chat(self):
        return SimpleNamespace(completions=self)


def _patch(monkeypatch, mm, *, ask, retry, budget):
    monkeypatch.setattr(llm, '_minimax', mm)
    monkeypatch.setattr(llm, '_gemini', None)
    monkeypatch.setattr(llm, 'LLM_RETRY_PAUSE_SECONDS', 0.0)
    monkeypatch.setattr(llm, 'LLM_SLICE_GUARD_SECONDS', 0.0)
    monkeypatch.setattr(llm, 'LLM_DIALOGUE_TIMEOUT_SECONDS', ask)
    monkeypatch.setattr(llm, 'LLM_RETRY_TIMEOUT_SECONDS', retry)
    monkeypatch.setattr(llm, 'LLM_CHAIN_BUDGET_SECONDS', budget)
    # пол «не мелиться» в тесте ниже: секунды тут дольные, а сам пол проверяется
    # статикой (test_the_seventy_second_attempt_still_leaves_room_inside_his_ninety)
    monkeypatch.setattr(llm, 'MIN_PROVIDER_SLICE_SECONDS', 0.5)


def test_the_first_dialogue_attempt_now_gets_seventy_seconds():
    assert "LLM_DIALOGUE_TIMEOUT_SECONDS = _env_float('LLM_DIALOGUE_TIMEOUT_SECONDS', 70.0)" in LLM_SRC
    assert llm.LLM_DIALOGUE_TIMEOUT_SECONDS == 70.0


def test_the_seventy_second_attempt_still_leaves_room_inside_his_ninety():
    # 70 + страховка + пауза + страховка повтора — и у хода остаётся живой повтор
    spent = (llm.LLM_DIALOGUE_TIMEOUT_SECONDS + 2 * llm.LLM_SLICE_GUARD_SECONDS
             + llm.LLM_RETRY_PAUSE_SECONDS)
    assert spent < llm.LLM_CHAIN_BUDGET_SECONDS, f'повтору не что брать: {spent}'
    assert llm.LLM_CHAIN_BUDGET_SECONDS - spent >= 2 * llm.MIN_PROVIDER_SLICE_SECONDS


def test_the_retry_only_asks_for_what_the_turn_has_left(monkeypatch):
    # зависает дольше своего среза в оба раза: иначе гонка sleep==timeout
    mm = _FakeProvider([2.0, 9.0])
    _patch(monkeypatch, mm, ask=0.5, retry=9.0, budget=3.0)
    with pytest.raises(RuntimeError) as got:
        asyncio.run(llm.generate_text([{'role': 'user', 'content': 'x'}],
                                      max_tokens=40, purpose='dialogue'))
    assert len(mm.calls) == 2, 'повтор был обязан состояться'
    first, second = mm.calls[0]['timeout'], mm.calls[1]['timeout']
    assert first == 0.5
    assert second < 9.0, f'повтор попросил всё, чего хода уже нет: {second}'
    assert 1.0 <= second <= 3.0 - first, second
    assert f'of {second:g}s' in str(got.value), 'в причине — тот срез, что просили'


def test_both_attempts_together_still_never_run_past_the_budget(monkeypatch):
    mm = _FakeProvider([9.0, 9.0])
    _patch(monkeypatch, mm, ask=0.6, retry=9.0, budget=3.0)
    started = time.monotonic()
    with pytest.raises(RuntimeError):
        asyncio.run(llm.generate_text([{'role': 'user', 'content': 'x'}],
                                      max_tokens=40, purpose='dialogue'))
    elapsed = time.monotonic() - started
    assert elapsed < 4.5, f'ход шёл {elapsed:.1f} с при бюджете 3 с'


def test_the_auxiliary_calls_keep_their_own_time(monkeypatch):
    # её жизнь и пуши пишутся той же моделью, но longer slice — не про них
    mm = _FakeProvider([0.2])
    _patch(monkeypatch, mm, ask=0.5, retry=9.0, budget=30.0)
    asyncio.run(llm.generate_text([{'role': 'user', 'content': 'x'}],
                                  max_tokens=40, purpose='life_event'))
    assert mm.calls[0]['timeout'] == llm.LLM_TIMEOUT_SECONDS == 30.0
