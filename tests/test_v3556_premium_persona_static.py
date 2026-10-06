"""V3.55.6 — premium level-6 floor + tender/passionate choice (static pins).

Two owner asks in one build:
1. A Premium user meeting a premium-status character starts at level 6
   («Наша история», committed) right away — the level-6 gates become a
   raise-only floor; the engine itself stays access-free via a callback
   registered in main.py (same pattern as the V3.21.0 premium checker).
2. In the Mini App chat the user then picks her manner once — tender or
   passionate. The choice lives on the relationship row (persona_style) and
   colors the chat tone (shared bot/app pipeline) and the photo expression
   pool (tender -> soft variety rotation).

Static pins only (no imports -> the suite runs without a DB/LLM key)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = (ROOT / 'models' / 'relationship_models.py').read_text(encoding='utf-8')
ENGINE = (ROOT / 'services' / 'relationship_engine.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_persona_style_column():
    assert "persona_style: Mapped[str | None] = mapped_column(String(16), nullable=True)" in MODELS


def test_engine_floor_provider_and_helper():
    assert 'def set_premium_floor_provider(fn):' in ENGINE
    assert "_PREMIUM_FLOOR_RAW = {s: (r, t, i) for s, r, t, i in STAGE_RULES}['committed']" in ENGINE
    assert "_PREMIUM_FLOOR_DIMS = DIMENSION_GATES['committed']" in ENGINE
    assert 'def apply_premium_floor(' in ENGINE
    # raise-only: every axis goes through max()
    floor_fn = ENGINE[ENGINE.index('def _raise_to_premium_floor'):ENGINE.index('def apply_premium_floor')]
    assert floor_fn.count('max(') == 6


def test_apply_delta_uses_the_floor_before_stage_recompute():
    body = ENGINE[ENGINE.index('def apply_delta('):ENGINE.index('def get_state(')]
    assert '_premium_floor_applies(user_id, character_id)' in body
    assert '_raise_to_premium_floor(row)' in body
    assert body.index('_raise_to_premium_floor(row)') < body.index('new_stage = _dimension_stage(row)')


def test_main_registers_provider_and_applies_on_chat_open():
    assert 'set_premium_floor_provider(_premium_floor_needs)' in MAIN
    gate = MAIN[MAIN.index('def _premium_floor_needs'):MAIN.index('set_premium_floor_provider')]
    assert "card.status == 'premium'" in gate
    assert 'ADMIN_TELEGRAM_IDS' in gate
    hist = MAIN[MAIN.index('async def _webapp_api_chat_history'):MAIN.index('def _custom_premium_gate_block')]
    assert 'apply_premium_floor(session, uid, character_id)' in hist
    assert "'persona': persona_info" in hist


def test_persona_endpoint_and_route():
    assert "app.router.add_post('/webapp/api/chat/persona', _webapp_api_chat_persona)" in MAIN
    body = MAIN[MAIN.index('async def _webapp_api_chat_persona'):MAIN.index('async def _webapp_api_chats')]
    assert "style not in ('tender', 'passionate')" in body
    # the same chat gates run first: consent + premium
    assert "error': 'consent'" in body
    assert "error': 'premium_required'" in body
    assert 'row.persona_style = style' in body


def test_chat_service_style_lines():
    assert 'НЕЖНЫЙ СТИЛЬ' in CHAT
    assert 'СТРАСТНЫЙ СТИЛЬ' in CHAT
    assert "(style_line + '\\n' if style_line else '')" in CHAT
    # the style is read for the exact (user, character) pair
    assert 'UserCharacterRelationship.persona_style' in CHAT


def test_photo_rotation_follows_the_style():
    assert 'def _persona_style_is_tender(' in PHOTO
    assert 'shuffled_variety_keys() if _persona_style_is_tender(telegram_id, character_id)' in PHOTO
    # the sensual default stays for unset/passionate
    assert 'else shuffled_sensual_variety_keys()' in PHOTO


def test_spa_banner_and_post():
    assert 'id="personaBanner"' in SPA
    assert 'function renderPersonaBanner(' in SPA
    assert "'/webapp/api/chat/persona?init_data='" in SPA
    assert 'if (j.persona && j.persona.needed) renderPersonaBanner(characterId);' in SPA


def test_i18n_persona_keys_in_all_locales():
    for key in ('persona_q:', 'persona_tender:', 'persona_passionate:',
                'persona_saved_tender:', 'persona_saved_passionate:'):
        assert SPA.count(key) >= 7, key
