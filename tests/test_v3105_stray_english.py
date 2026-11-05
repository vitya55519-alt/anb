"""V3.105.0 — no English words in the middle of a Russian reply."""
import asyncio
from pathlib import Path

from services import lang_guard as lg

CHAT = (Path(__file__).resolve().parents[1] / 'services' / 'chat_service.py').read_text(encoding='utf-8')


def test_finds_stray_words_only_in_russian_text():
    assert lg.stray_english('понимаю, немного переживать нормально, especially когда это важное дело') == ['especially']
    assert lg.stray_english('ну anyway, baby, иди ко мне скорее 🥰') == ['anyway', 'baby']
    assert lg.stray_english('hey baby, how are you?') == []  # an English reply is not touched
    assert lg.stray_english('я тебе в Telegram написала, оформи Premium, ok?') == []
    assert lg.stray_english('у меня новый iPhone и BMW, а ещё смотрела Netflix') == []
    assert lg.stray_english('ты написал cool, и мне это нравится, cool') == ['cool']
    assert lg.stray_english('ты написал cool, и мне это нравится', ['это так cool']) == []
    assert lg.stray_english('ссылка https://example.com и @Anna67901_bot тут') == []


def test_repair_keeps_text_or_falls_back(monkeypatch):
    import services.chat_service as cs

    class R:
        text = 'понимаю, немного переживать нормально, особенно когда это важное дело'
    async def ok(*a, **k):
        return R()
    monkeypatch.setattr(cs, 'generate_text', ok)
    src = 'понимаю, немного переживать нормально, especially когда это важное дело'
    assert asyncio.run(cs._fix_stray_english(src, [])) == R.text

    class Bad:
        text = 'да'
    async def bad(*a, **k):
        return Bad()
    monkeypatch.setattr(cs, 'generate_text', bad)
    assert asyncio.run(cs._fix_stray_english(src, [])) == src  # changed too much → original kept


def test_wired_into_dialogue():
    assert 'lang_guard.RU_DIRECTIVE' in CHAT and '_fix_stray_english(answer' in CHAT
    assert 'LANG_RU_PURITY_ENABLED' in (Path(lg.__file__)).read_text(encoding='utf-8')
