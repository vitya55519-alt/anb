"""V3.61.1: ready constructor templates + the opening scene she starts a chat
with (since V3.165.0 #106 the «С сюжетом / Без сюжета» picker is gone)."""
from pathlib import Path

from services.character_card_service import OPENING_SCENES, SCENARIO_HOOKS, get_opening_scene
from services.custom_character_service import (
    CONSTRUCTOR_STEPS, CONSTRUCTOR_TEMPLATES, STEP_GROUPS,
)

ROOT = Path(__file__).resolve().parents[1]


def _options(key):
    for step in CONSTRUCTOR_STEPS:
        if step['key'] == key:
            return {opt[0] for opt in step.get('options', [])}, step
    return None, None


def test_every_builtin_girl_has_an_opening_scene():
    for cid in SCENARIO_HOOKS:
        assert get_opening_scene(cid), cid
    assert all('*' in scene for scene in OPENING_SCENES.values())


def test_opening_step_is_free_text_in_story_group():
    _, step = _options('opening')
    assert step and step.get('free_text')
    assert STEP_GROUPS['opening'] == 'story'


def test_templates_use_valid_option_values():
    assert len(CONSTRUCTOR_TEMPLATES) >= 6
    for tpl in CONSTRUCTOR_TEMPLATES:
        assert tpl['id'] and tpl['title'] and tpl['name']
        for key, value in tpl['params'].items():
            opts, step = _options(key)
            assert step is not None, (tpl['id'], key)
            if not step.get('free_text'):
                assert value in opts, (tpl['id'], key, value)
        assert tpl['params'].get('opening')


def test_chat_start_endpoint_and_spa_wiring():
    main = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert "'/webapp/api/chat/start'" in main
    assert "'templates'" in main
    html = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
    assert 'data-tpl' in html
    # V3.165.0 (#106): the «С сюжетом / Без сюжета» sheet is gone — the app asks
    # for her opening scene by itself, so the endpoint is the only wiring left.
    assert 'requestChatOpener' in html
    assert 'openStartSheet' not in html
    assert 'startStory' not in html and 'startPlain' not in html
