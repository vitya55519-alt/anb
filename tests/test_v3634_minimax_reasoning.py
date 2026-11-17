"""MiniMax-M3 disables thinking without headroom; empty answers retry MiniMax."""
import asyncio
from types import SimpleNamespace

import pytest


def _resp(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))], usage=None)


def _setup(monkeypatch, mm_text, gem_text=None, gem_exc=None):
    from services import llm_provider_service as L
    seen = {'mm': [], 'gem': []}

    async def mm_create(**k):
        seen['mm'].append(k)
        return _resp(mm_text)

    async def gem_create(**k):
        seen['gem'].append(k)
        if gem_exc:
            raise gem_exc
        return _resp(gem_text)
    mm = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=mm_create)))
    gem = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=gem_create)))
    monkeypatch.setattr(L, '_minimax', mm)
    monkeypatch.setattr(L, '_gemini', gem)
    monkeypatch.setattr(L, 'LLM_RETRY_PAUSE_SECONDS', 0)
    return L, seen


def test_m3_disables_thinking_without_headroom(monkeypatch):
    L, seen = _setup(monkeypatch, 'привет')
    r = asyncio.run(L.generate_text([{'role': 'user', 'content': 'x'}], max_tokens=90, purpose='rewrite'))
    assert r.text == 'привет'
    assert len(seen['mm']) == 1
    assert seen['mm'][0]['model'] == L.MINIMAX_MODEL == 'MiniMax-M3'
    assert seen['mm'][0]['max_tokens'] == 90
    assert seen['mm'][0]['extra_body'] == {'thinking': {'type': 'disabled'}}
    assert seen['gem'] == []


@pytest.mark.parametrize('purpose', ['life_event', 'dialogue'])
def test_empty_minimax_retries_itself_never_gemini(monkeypatch, purpose):
    # V3.167.1: Gemini из диалога убран (429 на каждую вторую реплику). Пустой
    # MiniMax повторяет себя, а к фото-глазам ход не уходит.
    L, seen = _setup(monkeypatch, '', gem_text='из gemini')
    r = asyncio.run(L.generate_text([{'role': 'user', 'content': 'x'}], max_tokens=90, purpose=purpose))
    assert r.text == '' and r.provider == 'minimax'
    assert len(seen['mm']) == 2
    expected_model = L.MINIMAX_DIALOGUE_MODEL if purpose == 'dialogue' else L.MINIMAX_MODEL
    for call in seen['mm']:
        assert call['model'] == expected_model == 'MiniMax-M3'
        assert call['max_tokens'] == 90
        assert call['extra_body'] == {'thinking': {'type': 'disabled'}}
    assert seen['gem'] == []


def test_empty_everywhere_stays_empty_not_crash(monkeypatch):
    L, _ = _setup(monkeypatch, '', gem_exc=RuntimeError('down'))
    r = asyncio.run(L.generate_text([{'role': 'user', 'content': 'x'}], max_tokens=90, purpose='life_event'))
    assert r.text == ''
