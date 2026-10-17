"""V3.64.1: «Квартира / Свидание не цепляют» — a tap is played as a live scene.

His action is saved as his own message and she answers through the normal
dialog pipeline with a scene direction that asks for detail, initiative and a
hook at the end. The old canned lines stay as the fallback.
"""
from pathlib import Path

from services import apartment_service, dates_service

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_every_room_action_has_his_line_and_a_scene_direction():
    for room in apartment_service.ROOMS:
        for title, action_id in room.actions:
            assert apartment_service.USER_ACTIONS[action_id].startswith('*')
            d = apartment_service.scene_direction(room, action_id)
            assert room.name.lower() in d and title in d and 'крючком' in d


def test_every_date_has_a_scene_direction():
    for date in dates_service.get_all():
        assert date.name in dates_service.scene_direction(date)
        assert dates_service.user_action(date).startswith('*')


def test_reply_takes_the_scene_line_before_his_action():
    assert "scene: str = '') -> str:" in CHAT
    assert 'if scene:\n        messages.append({"role": "system", "content": scene})' in CHAT


def test_endpoint_plays_the_scene_and_keeps_the_fallback():
    assert 'async def _feature_scene_turn(' in MAIN
    assert 'apartment_service.scene_direction(room, action_id)' in MAIN
    assert 'dates_service.scene_direction(date)' in MAIN
    assert "await asyncio.to_thread(save_message, uid, character_id, 'assistant', text)" in MAIN


def test_app_shows_his_action_bubble_and_a_wait_line():
    assert "chatBubble({ role: 'user', content: j.user_text, ts: null })" in INDEX
    assert INDEX.count('apt_wait: ') == 2
