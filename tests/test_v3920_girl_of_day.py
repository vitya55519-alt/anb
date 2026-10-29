"""V3.92.0: «🔥 Девушка дня» — one roster girl a day open to everyone."""
import datetime as dt
from pathlib import Path

from services import girl_of_day as g

ROOT = Path(__file__).resolve().parents[1]


def test_rotation_starts_with_agata_and_walks_the_pool():
    girls = ['anna_01', 'agata_01', 'vlada_01']
    assert g.rotation_pick(g.ANCHOR_DATE, girls) == 'agata_01'
    assert g.rotation_pick(g.ANCHOR_DATE + dt.timedelta(days=1), girls) == 'vlada_01'
    assert g.rotation_pick(g.ANCHOR_DATE + dt.timedelta(days=2), girls) == 'anna_01'
    assert g.rotation_pick(g.ANCHOR_DATE, []) is None


def test_caption_says_free_today_and_adult():
    text = g.post_caption('Агата', 23, 'Нежная готка')
    assert 'без Premium' in text and '03:00 МСК' in text and '18+' in text


def test_wiring():
    chat = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
    assert 'intim_ok = girl_of_day.is_open(character_id)' in chat
    gate = (ROOT / 'services' / 'intimacy_gate.py').read_text(encoding='utf-8')
    assert 'girl_of_day.is_open(character_id)' in gate
    main = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert "@dp.message(Command('girlday'))" in main and "F.data.startswith('gday:')" in main
    assert 'girl_of_day.girl_from_payload(' in main or 'girl_of_day.girl_from_payload, command.args' in main
    sched = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
    assert "id='girl_of_day'" in sched
    html = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
    assert 'c.girl_of_day' in html and "girl_of_day: 'Девушка дня · без Premium'" in html
