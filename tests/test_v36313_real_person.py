"""V3.63.13: she lives her own day, writes casually, and her second bubble comes after «печатает…»."""
import datetime as dt
from pathlib import Path

from services.daily_life import ROUTINES, her_moment
from services.dialogue_guard_service import casual_punctuation
from services.voice_samples import VOICE_SAMPLES

ROOT = Path(__file__).resolve().parents[1]


def test_every_stock_girl_has_a_full_day():
    assert set(ROUTINES) == set(VOICE_SAMPLES)
    for cid, routine in ROUTINES.items():
        assert set(routine) == {'night', 'morning', 'late_morning', 'day', 'evening', 'late'}, cid
        for variants in routine.values():
            assert len(variants) == 2 and all(v.strip() for v in variants), cid


def test_moment_follows_his_clock_and_changes_by_day():
    noon = dt.datetime(2026, 10, 19, 11, 30)
    assert 'урок' in her_moment('alisa_01', noon) or 'класс' in her_moment('alisa_01', noon)
    assert 'понедельник' in her_moment('alisa_01', noon) and '11:30' in her_moment('alisa_01', noon)
    night = dt.datetime(2026, 10, 19, 1, 0)
    assert her_moment('erika_01', night) != her_moment('erika_01', noon)
    assert her_moment('erika_01', night) != her_moment('erika_01', night + dt.timedelta(days=1))
    assert her_moment('custom_123', noon) == ''


def test_casual_punctuation():
    assert casual_punctuation('Ну ты даёшь.') == 'ну ты даёшь'
    assert casual_punctuation('Привет.\n\nЯ скучала.') == 'привет\n\nя скучала'
    assert casual_punctuation('Эрика тут…') == 'Эрика тут…'
    assert casual_punctuation('Москва красивая...') == 'Москва красивая...'
    assert casual_punctuation('```code.```') == '```code.```'


def test_wiring():
    chat = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
    assert 'moment = her_moment(character_id, now_local)' in chat
    assert 'state_context(user_id, character_id)' in chat
    assert "answer = casual_punctuation(answer)" in chat
    state = (ROOT / 'services' / 'state_service.py').read_text(encoding='utf-8')
    assert 'настроение Анны' not in state and 'истории Анны' not in state
    main = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert 'await asyncio.sleep(_bubble_pause(part))' in main
    html = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
    assert 'function splitBubbles(text)' in html and 'async function playFollowups(parts)' in html
    assert "typing_now: 'печатает…'" in html
