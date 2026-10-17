"""V3.63.2: she wakes him by voice in her character; one free trial alarm."""
import asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def test_scheduler_wakes_with_her_voice_and_stop_button():
    assert 'wake_service.wake_line(telegram_id,char_id,idx' in SCHED
    assert 'await bot.send_voice(telegram_id,BufferedInputFile(audio' in SCHED
    assert "callback_data='wake:up'" in SCHED
    assert "@dp.callback_query(F.data == 'wake:up')" in MAIN


def test_alarm_gates_go_through_trial_helper():
    assert MAIN.count("await _maybe_set_alarm(message, text,") == 3
    assert 'trial = (not premium) and wake and wake_trial_available(tid)' in MAIN
    assert 'if not premium and wake_trial_available(message.from_user.id):' in MAIN


def test_wake_request_detection():
    from services.reminder_service import is_wake_request
    assert is_wake_request('разбуди меня в 7:30')
    assert is_wake_request('/wake 08:00')
    assert not is_wake_request('напомни в 14:30 позвонить')
    assert not is_wake_request('разбуди меня пораньше')


def test_wake_line_falls_back_without_llm(monkeypatch):
    from services import wake_service, llm_provider_service

    async def boom(*a, **k):
        raise RuntimeError('no llm')
    monkeypatch.setattr(llm_provider_service, 'generate_text', boom)
    line = asyncio.run(wake_service.wake_line(1, 'anna_01', 9))
    assert line == wake_service.WAKE_FALLBACK[-1]


def test_wake_line_sends_user_turn(monkeypatch):
    from services import wake_service, llm_provider_service
    seen = {}

    class R:
        text = 'Вставай, соня, кофе уже ждёт тебя'

    async def fake(messages, **k):
        seen['messages'] = messages
        return R()
    monkeypatch.setattr(llm_provider_service, 'generate_text', fake)
    line = asyncio.run(wake_service.wake_line(1, 'anna_01', 0, name='Витя'))
    assert line == R.text
    assert seen['messages'][-1]['role'] == 'user'
