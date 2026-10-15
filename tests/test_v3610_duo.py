"""V3.61.0: constructor duo (two girls in one chat) and 3 🍑 creation."""
from pathlib import Path

from services import custom_character_service as ccs


def test_duo_steps_and_price():
    keys = [s['key'] for s in ccs.CONSTRUCTOR_STEPS]
    assert 'duo_name' in keys and 'duo_desc' in keys
    assert ccs.STEP_GROUPS['duo_name'] == 'duo' and 'duo' in ccs.STEP_GROUP_ORDER
    import config
    assert config.CONSTRUCTOR_COST_PEACHES == 3


def test_duo_persona_and_avatar():
    params = {'name': 'Аой', 'duo_name': 'Юкио', 'duo_desc': 'младшая сестра, блондинка', 'style': 'style_anime'}
    ctx = ccs.build_persona_context(params, 'Аой')
    assert 'ВАС ДВЕ' in ctx and '«Юкио: …»' in ctx
    avatar = ccs.build_avatar_prompt(params)
    assert 'TWO ADULT WOMEN' in avatar and 'One person only' not in avatar
    solo = ccs.build_avatar_prompt({'name': 'Аой'})
    assert 'One person only' in solo
    assert ccs.duo_partner({'name': 'x'}) == ('', '')


def test_duo_wired_into_photos_and_spa():
    photo = Path('services/photo_service.py').read_text(encoding='utf-8')
    assert 'identity += _duo_identity_line(character_id, name)' in photo
    html = Path('webapp/index.html').read_text(encoding='utf-8')
    assert "CHAT.duo = j.duo || null" in html and 'duo-nm' in html
    assert "'story', 'duo', 'reference'" in html
