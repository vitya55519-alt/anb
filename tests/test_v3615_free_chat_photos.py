"""V3.61.5: 2 free chat photos a day, and «*шлю тебе ещё фотку*» really sends one."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_free_allowance_counts_down_per_day():
    from services.db import init_db
    init_db()
    from config import CHAT_FREE_PHOTOS_PER_DAY
    from services.chat_photo_allowance import free_chat_photos_left, use_free_chat_photo
    assert CHAT_FREE_PHOTOS_PER_DAY == 2
    uid = 9_100_001
    assert free_chat_photos_left(uid) == 2
    use_free_chat_photo(uid, 'vika_01')
    assert free_chat_photos_left(uid) == 1
    use_free_chat_photo(uid, 'anna_01')
    assert free_chat_photos_left(uid) == 0


def test_her_action_line_counts_as_a_photo_promise():
    import main
    for said in ('*шлю тебе ещё фотку* 🔥', '*отправляет тебе селфи*', 'скинула тебе фото', 'вот ещё фоточка'):
        assert main.PHOTO_PROMISE.search(said), said
    for said in ('я не люблю фотографироваться', 'хочешь ещё? 😏'):
        assert not main.PHOTO_PROMISE.search(said), said


def test_gate_and_delivery_use_the_free_photos_first():
    src = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert 'free_chat_photos_left(ensure_user(telegram_id)) <= 0' in src
    assert 'use_free_chat_photo(uid, character_id)' in src
    assert "'free_photos_left': free_chat_photos_left(uid)" in src
