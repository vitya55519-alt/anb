"""V3.63.15: messages she writes first got no chat polish and repeated her
own promise («завтра утром пришлю тебе кое-что 🙈 не проси»)."""
import asyncio
import inspect
import os

os.environ.setdefault("TELEGRAM_TOKEN", "123456:test-fake-token-for-static-tests-only")
os.environ.setdefault("GEMINI_API_KEY", "test-key")

from services import life_event_service
from services.dialogue_guard_service import drop_repeated_lines, polish_first_message

VIKA = 'завтра утром пришлю тебе кое-что 🙈 не проси'


def test_repeat_of_her_own_line_is_dropped():
    assert drop_repeated_lines('Завтра утром пришлю тебе кое-что 🙊 не проси!', [VIKA]) == ''
    out = drop_repeated_lines('Сегодня была на йоге, ноги гудят. Завтра утром пришлю тебе кое-что, не проси', [VIKA])
    assert out == 'Сегодня была на йоге, ноги гудят.'


def test_new_text_and_short_lines_stay():
    assert drop_repeated_lines('угадай, где я сейчас 😏', [VIKA]) == 'угадай, где я сейчас 😏'
    assert drop_repeated_lines('не проси', [VIKA]) == 'не проси'
    assert drop_repeated_lines('первая мысль\n\nвторая мысль', []) == 'первая мысль\n\nвторая мысль'


def test_polish_removes_dash_and_monkey_tic():
    out = polish_first_message('Я сегодня в кафе — угадай с кем 🙈.', ['ой 🙈'])
    assert '—' not in out and '🙈' not in out and not out.endswith('.')
    assert polish_first_message(VIKA, [VIKA]) == ''


def test_life_moment_sees_her_recent_lines_and_skips_repeat(monkeypatch):
    seen = {}

    class R:
        text = VIKA

    async def fake_generate(messages, **kw):
        seen['system'] = messages[0]['content']
        return R()

    import services.llm_provider_service as llm
    monkeypatch.setattr(llm, 'generate_text', fake_generate)
    monkeypatch.setattr(life_event_service, '_character_ingredients', lambda c: ('Вика', [], ''))
    monkeypatch.setattr(life_event_service, '_memory_callback', lambda *a: '')
    monkeypatch.setattr(life_event_service, '_pending_hook', lambda *a: '')
    monkeypatch.setattr(life_event_service, '_recent_her_lines', lambda *a, **k: [VIKA])
    assert asyncio.run(life_event_service.build_life_moment(1, 'vika')) == {}
    assert VIKA[:20] in seen['system']


def test_proactive_reply_is_polished():
    from services import chat_service
    src = inspect.getsource(chat_service.proactive_reply)
    assert 'polish_first_message' in src
