"""V3.63.4: MiniMax reasoning no longer eats short answers; empty → fallback."""
import asyncio
from types import SimpleNamespace


def _resp(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))], usage=None)


def _setup(monkeypatch, mm_text, gem_text=None, gem_exc=None):
    from services import llm_provider_service as L
    seen = {}

    async def mm_create(**k):
        seen['mm_max'] = k['max_tokens']
        return _resp(mm_text)

    async def gem_create(**k):
        if gem_exc:
            raise gem_exc
        return _resp(gem_text)
    mm = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=mm_create)))
    gem = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=gem_create)))
    monkeypatch.setattr(L, '_minimax', mm)
    monkeypatch.setattr(L, '_gemini', gem)
    monkeypatch.setattr(L, '_openrouter', None, raising=False)
    return L, seen


def test_headroom_added(monkeypatch):
    L, seen = _setup(monkeypatch, 'привет')
    r = asyncio.run(L.generate_text([{'role': 'user', 'content': 'x'}], max_tokens=90, purpose='life_event'))
    assert r.text == 'привет' and seen['mm_max'] == 90 + L.MINIMAX_REASONING_HEADROOM


def test_empty_minimax_falls_back_to_gemini(monkeypatch):
    L, _ = _setup(monkeypatch, '', gem_text='из gemini')
    r = asyncio.run(L.generate_text([{'role': 'user', 'content': 'x'}], max_tokens=90, purpose='life_event'))
    assert r.text == 'из gemini' and r.provider == 'gemini'


def test_empty_everywhere_stays_empty_not_crash(monkeypatch):
    L, _ = _setup(monkeypatch, '', gem_exc=RuntimeError('down'))
    r = asyncio.run(L.generate_text([{'role': 'user', 'content': 'x'}], max_tokens=90, purpose='life_event'))
    assert r.text == ''
