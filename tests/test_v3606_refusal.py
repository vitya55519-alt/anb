"""V3.60.6: a help-desk refusal from the chat model is never sent as is."""
import asyncio
from types import SimpleNamespace

from services import chat_service as cs


def test_refusal_detected():
    text = ('Такого рода ролевые игры я не поддерживаю. Описывать откровенные сексуальные сцены — '
            'за рамками того, чем я могу помочь.')
    assert cs.REFUSAL.search(text)
    assert not cs.REFUSAL.search('ммм, иди ко мне 😏')


def test_refusal_reworded_in_character(monkeypatch):
    async def fake_generate(messages, **kw):
        assert 'Перепиши его от лица Злата' in messages[0]['content']
        return SimpleNamespace(text='ой, тут я притормозлю 🙈 лучше расскажи, как прошёл день')
    monkeypatch.setattr(cs, 'generate_text', fake_generate)
    out = asyncio.run(cs._recover_from_refusal('я не поддерживаю такое', {'name': 'Злата'}))
    assert out.startswith('ой, тут я')


def test_still_refusing_gets_a_safe_in_voice_line(monkeypatch):
    async def fake_generate(messages, **kw):
        return SimpleNamespace(text='Я не могу помочь с этим.')
    monkeypatch.setattr(cs, 'generate_text', fake_generate)
    out = asyncio.run(cs._recover_from_refusal('не поддерживаю', {'name': 'Злата'}))
    assert not cs.REFUSAL.search(out)

