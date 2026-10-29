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


def test_every_post_text_says_free_today_and_adult():
    # V3.94.0: random inviting texts — every one is honest about the window.
    assert len(g.POST_TEMPLATES) >= 5
    for n in range(len(g.POST_TEMPLATES)):
        text = g.post_caption('Агата', 23, 'Нежная готка', '«хук»', variant=n)
        assert 'Агата' in text and '03:00 МСК' in text and text.endswith('18+'), n
        assert 'Premium' in text or 'бесплатно' in text.lower(), n
        assert len(text) < 900, n


def test_admin_post_flow_wired():
    main = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert "callback_data='gday:menu'" in main  # «📣 Пост в канал» in the admin panel
    assert "Command('girlday', 'post')" in main
    assert "parts[1] == 'pick'" in main and 'girl_of_day.publish(bot, channel, parts[2], variant)' in main


def test_wiring():
    chat = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
    assert 'intim_ok = girl_of_day.is_open(character_id)' in chat
    gate = (ROOT / 'services' / 'intimacy_gate.py').read_text(encoding='utf-8')
    assert 'girl_of_day.is_open(character_id)' in gate
    main = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert "@dp.message(Command('girlday', 'post'))" in main and "F.data.startswith('gday:')" in main
    assert 'girl_of_day.girl_from_payload(' in main or 'girl_of_day.girl_from_payload, command.args' in main
    sched = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
    assert "id='girl_of_day'" in sched
    html = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
    assert 'c.girl_of_day' in html and "girl_of_day: 'Девушка дня · без Premium'" in html
