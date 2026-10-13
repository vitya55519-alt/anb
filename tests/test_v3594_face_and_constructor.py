"""V3.59.4: face kept on hot photos, path bar for all, constructor scenarios + nice bios."""
import asyncio
import os
from pathlib import Path

os.environ.setdefault("TELEGRAM_TOKEN", "123456:test-fake-token-for-static-tests-only")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-for-static-tests-only")

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_hot_faces_keep_identity():
    from services import photo_expression_service as e
    for key in ('pleasure', 'breathless'):
        line = e.expression_description(key, 'Anna')
        assert 'rolled softly upward' not in line and 'across her face' not in line
        assert 'face identity' in line
    from services import photo_service, private_photo_service
    for pool in (photo_service.PRIVATE_POSE_POOL, private_photo_service.PRIVATE_POSE_POOL):
        for pose in pool:
            if 'five correct fingers' in pose:
                assert 'all fours' not in pose
                assert 'exactly the same face as reference image 1' in pose


def test_path_bar_for_every_girl():
    assert "renderPathBar(typeof c.path === 'number' ? c.path : 0);" in SPA


def test_constructor_has_ten_scenarios_that_shape_the_chat():
    from services import custom_character_service as c
    step = c.CONSTRUCTOR_STEPS[c.step_index('scenario')]
    assert len(step['options']) == 10
    assert set(c.SCENARIO_STORY) == {v for v, _, _ in step['options']}
    assert c.STEP_GROUPS['scenario'] == 'character'
    ctx = c.build_persona_context({'scenario': 'scn_boss'}, 'Кира')
    assert 'начальница' in ctx


def test_bio_writer_falls_back_quietly(monkeypatch):
    from services import custom_character_service as c, llm_provider_service as llm

    async def boom(*a, **k):
        raise RuntimeError('down')
    monkeypatch.setattr(llm, 'generate_text', boom)
    assert asyncio.run(c.write_card_bio({'scenario': 'scn_ex'}, 'Кира')) is None
    assert 'nice_bio = await asyncio.wait_for(write_card_bio(params, display_name), timeout=25)' in MAIN
    assert "callback_data='admin:biofix'" in MAIN


def test_constructor_relationship_status_shapes_the_chat():
    from services import custom_character_service as c
    step = c.CONSTRUCTOR_STEPS[c.step_index('marital')]
    assert {v for v, _, _ in step['options']} == set(c.RELATIONSHIP_STORY)
    assert 'mar_married' in c.RELATIONSHIP_STORY and 'mar_divorced' in c.RELATIONSHIP_STORY
    ctx = c.build_persona_context({'marital': 'mar_married'}, 'Кира')
    assert 'Ты замужем' in ctx


def test_glued_bios_are_detected_and_replaced():
    from services import custom_character_service as c
    params = {'style': 'style_real', 'age': 'age_confident', 'face': 'face_soft', 'body': 'body_slim',
              'temperament': 'temper_naughty', 'profession': 'prof_business', 'role': 'role_secret'}
    glued = c.legacy_glued_bio(params, 'Ию')
    assert glued.startswith('Ию — реалистичная, 34+, мягкое, женственное, стройная')
    assert c.bio_looks_glued(glued + ' Любит кофе.', params, 'Ию')
    nice = c.template_card_bio(params, 'Ию')
    assert not c.bio_looks_glued(nice, params, 'Ию')
    assert 'тайная возлюбленная' in nice and 'реалистичная' not in nice
    assert '_spawn_background(_startup_fix_glued_bios())' in MAIN
    assert 'bio = nice_bio or template_card_bio(params, display_name)' in MAIN
