from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_coffee_not_in_anna_stable_tastes():
    text = (ROOT / 'data/characters/anna.json').read_text(encoding='utf-8').lower()
    assert 'хороший кофе' not in text


def test_emily_is_public_default_name():
    cards = (ROOT / 'services/character_card_service.py').read_text(encoding='utf-8')
    main = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert '"display_name": "Emily"' in cards
    assert "'alena_01': '👱‍♀️ Emily'" in main


def test_dialogue_guard_and_task_clarify_exist():
    guard = (ROOT / 'services/dialogue_guard_service.py').read_text(encoding='utf-8')
    behavior = (ROOT / 'services/behavior_service.py').read_text(encoding='utf-8')
    chat = (ROOT / 'services/chat_service.py').read_text(encoding='utf-8')
    assert 'coffee/cafe' in guard
    assert 'task_character' in behavior
    assert 'build_repetition_guard' in chat
