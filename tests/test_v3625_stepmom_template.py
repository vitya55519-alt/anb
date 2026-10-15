"""V3.62.1: «Мачеха» in the constructor — a scenario and a ready template."""


def test_stepmom_scenario_and_template():
    from services.custom_character_service import CONSTRUCTOR_STEPS, CONSTRUCTOR_TEMPLATES, SCENARIO_STORY
    scn = next(s for s in CONSTRUCTOR_STEPS if s['key'] == 'scenario')
    assert any(v == 'scn_stepmom' for v, _, _ in scn['options'])
    story = SCENARIO_STORY['scn_stepmom']
    assert 'не родственники по крови' in story and 'взрослым' in story
    tpl = next(t for t in CONSTRUCTOR_TEMPLATES if t['id'] == 'stepmom')
    assert tpl['params']['scenario'] == 'scn_stepmom' and tpl['params']['age'] == 'age_confident'
    assert tpl['params']['marital'] == 'mar_married'
