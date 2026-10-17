"""V3.63.1: fixes for errors seen in Railway logs."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
LIFE = (ROOT / 'services' / 'life_event_service.py').read_text(encoding='utf-8')


def test_life_moment_sends_a_user_turn():
    # system-only requests were rejected by MiniMax and Gemini (400)
    i = LIFE.index('async def build_life_moment')
    body = LIFE[i:i + 2500]
    assert "{'role': 'user', 'content': 'Напиши ему это сообщение сейчас.'}" in body


def test_daily_gift_marks_blocked_by_telegram_id():
    daily = SCHED[SCHED.index('async def _daily_gift(bot):'):]
    assert '_mark_blocked_tg(tid)' in daily
    assert '_mark_blocked(int(tid))' not in daily
    assert 'User.telegram_id == str(telegram_id)' in SCHED  # column is String(64)


def test_chat_not_found_stops_retries():
    assert 'from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError' in SCHED
    assert SCHED.count("'chat not found' in str(e).lower()") >= 2
