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
    assert len(step['options']) == 11  # V3.62.1: + мачеха
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


def test_marital_status_for_existing_girls():
    assert "app.router.add_post('/webapp/api/chat/marital', _webapp_api_chat_marital)" in MAIN
    assert "row.marital_status = new_value" in MAIN
    # V3.59.6: every change costs peaches (admin free), same pick is free
    assert "if not spend_peaches(telegram_id, MARITAL_CHANGE_PEACHES):" in MAIN
    assert "return None  # same pick again: free, nothing changes" in MAIN
    assert "if (r.status === 402) { c.marital = prev; renderMarital(c); toast(L.marital_no_peaches); showTab('shop'); return; }" in SPA
    assert '.mchips { display: flex; flex-direction: column;' in SPA  # V3.59.9: column, one chip per line
    from config import MARITAL_CHANGE_PEACHES
    assert MARITAL_CHANGE_PEACHES == 5
    assert 'function renderMarital(c)' in SPA and "'/webapp/api/chat/marital?init_data='" in SPA
    chat = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
    assert "'СЕМЕЙНОЕ ПОЛОЖЕНИЕ (выбор пользователя, важнее описания выше): ' + marital_line" in chat
    websvc = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
    assert "'marital': maritals.get(card.character_id) or _default_marital(card.character_id, custom)," in websvc
    assert 'messages.append({"role": "system", "content": marital_reminder})' in chat
    from models.relationship_models import UserCharacterRelationship
    assert hasattr(UserCharacterRelationship, 'marital_status')


def test_marital_status_shows_in_photos_and_story():
    from services.db import init_db, SessionLocal
    init_db()
    from services.user_service import ensure_user
    from models.relationship_models import UserCharacterRelationship
    from services import photo_service as ps
    uid = ensure_user(990077)
    with SessionLocal() as s:
        s.add(UserCharacterRelationship(user_id=uid, character_id='anna_01', path_axis=0.0, marital_status='mar_married'))
        s.commit()
    assert ps.marital_status_for(990077, 'anna_01') == 'mar_married'
    assert 'wedding ring' in ps.marital_photo_detail(990077, 'anna_01', allow_sometimes=False)
    req = ps._resolve_request(990077, ps.PhotoRequest(scene='selfie'), character_id='anna_01')
    prompt = ps._build_prompt(req, 0, seedream=True, character_id='anna_01')
    assert 'STORY DETAIL: a thin gold wedding ring' in prompt
    assert ps.marital_photo_detail(990078, 'anna_01') == ''
    assert MAIN.count('_with_marital_ring(prompt,') == 3
    assert "memory_key='marital:change'" in MAIN


def test_husband_is_present_and_photos_follow_user_clock():
    from services import custom_character_service as c
    line = c.relationship_line('mar_married', 'veronika_01')
    assert '{partner}' not in line and 'почти в каждом втором' in line
    assert line == c.relationship_line('mar_married', 'veronika_01')
    assert 'одинокой' in line
    from services import photo_service as ps
    assert 'request.time_of_day or _local_time_light(telegram_id) or random.choice(DAYLIGHT_POOL)' in (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
    from services.db import init_db
    init_db()
    from services.user_service import ensure_user, update_user_settings
    ensure_user(990099)
    update_user_settings(990099, timezone='Pacific/Kiritimati')
    assert ps._local_time_light(990099)
    assert "Intl.DateTimeFormat().resolvedOptions().timeZone" in SPA
    assert "browser_tz = (request.query.get('tz') or '').strip()[:64]" in MAIN
