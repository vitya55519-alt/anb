"""Static regression tests for v3.31.8: dates/photos honor the selected character.

Owner complaint: «от свидания я выбираю Эмили или создаю своего персонажа и
нажимаю кнопку свидания и там все равно свидание с Анной» — pressing the date
button with Emily (alena_01) or a constructor persona selected still produced
"a date with Anna". Root causes were Anna hardcoded across the pipeline:

1. Custom personas have no data/characters/<id>.json, so the photo pipeline
   crashed with FileNotFoundError and the voice fell back to Anna's exact
   voice. resolve_character() now synthesizes an identity profile from the
   constructor card + cached avatar reference, and custom girls get their own
   edge/Gemini voice.
2. build_relationship_context hardcoded «Анна» in all stage texts — every
   character got Anna's relationship guidance. Stage texts are name-templated
   per character now.
3. Creating a persona never switched the selection, so the next date still
   went to Anna. _finish_constructor auto-selects the new persona.
4. Library topup delivery rows omitted character_id, polluting the community
   pool with Anna-tagged photos of other girls.
5. chat_service silently used Anna's JSON file as the base identity for custom
   personas (custom_base_character takes precedence now).
6. Invoice titles hardcoded «Анна» — they show the selected girl's name.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
VOICE = (ROOT / 'services' / 'voice_service.py').read_text(encoding='utf-8')
REL = (ROOT / 'services' / 'relationship_engine.py').read_text(encoding='utf-8')
RELSVC = (ROOT / 'services' / 'relationship_service.py').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
CUSTOM = (ROOT / 'services' / 'custom_character_service.py').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


def test_version_bumped():
    assert VERSION in ('3.31.7', '3.31.8', '3.32.0', '3.32.1', '3.33.0', '3.33.1', '3.34.0', '3.34.1', '3.35.0', '3.36.0', '3.37.0', '3.38.0', '3.39.0')


def test_photo_pipeline_resolves_character_without_anna_fallback():
    # resolve_character(): custom profile first, registry fallback — never a
    # crash/Anna fallback for constructor personas.
    assert 'def resolve_character(character_id: str) -> dict:' in PHOTO
    assert '_custom_character_profile(character_id)' in PHOTO
    lock = PHOTO[PHOTO.index('def _character_identity_lock('):PHOTO.index('def ', PHOTO.index('def _character_identity_lock(') + 10)]
    assert 'character = resolve_character(character_id)' in lock
    gen = PHOTO[PHOTO.index('async def generate_photo_set('):]
    gen = gen[:gen.index('\ndef ')]
    assert 'character = resolve_character(character_id)' in gen
    # custom avatar cache hook used by the runtime before photo delivery
    assert 'async def ensure_custom_avatar_cached(bot, character_id: str)' in PHOTO


def test_topup_delivery_rows_tag_character_id():
    # Community pool rows must carry the real girl, not the Anna default.
    topup = PHOTO[PHOTO.index("provider='telegram_library_topup'") - 400:]
    topup = topup[:topup.index("provider='telegram_library_topup'") + 120]
    assert 'character_id=character_id' in topup


def test_custom_voice_distinct_from_anna():
    assert 'CUSTOM_CHARACTER_VOICE_PROFILE = {' in VOICE
    assert "CUSTOM_CHARACTER_GEMINI_TTS_VOICE = 'Erin'" in VOICE
    assert 'CUSTOM_CHARACTER_VOICE_PROFILE' in VOICE[VOICE.index('def pick_edge_voice'):]
    assert 'CUSTOM_CHARACTER_GEMINI_TTS_VOICE' in VOICE[VOICE.index('async def _tts_gemini'):VOICE.index('async def _tts_gemini') + 4000]


def test_relationship_context_names_the_character():
    assert 'character_id: str = CHARACTER_ID' in REL
    assert ".replace('Анна', _character_display_name(character_id))" in REL
    assert 'def _character_display_name(character_id: str) -> str:' in REL
    # service passes the selected character through at both call sites
    assert RELSVC.count('build_relationship_context(row, get_milestones(s, row), character_id)') >= 2


def test_chat_base_identity_prefers_custom_persona():
    assert 'def custom_base_character(character_id' in CUSTOM
    assert CHAT.count('custom_base_character(character_id) or get_character(character_id)') == 2


def test_constructor_auto_selects_new_persona():
    assert 'set_user_character(telegram_id, row.character_id)' in MAIN


def test_photo_background_caches_custom_avatar():
    bg = MAIN[MAIN.index('async def _run_photo_background('):]
    bg = bg[:bg.index('\nasync def ') if '\nasync def ' in bg else len(bg)]
    assert 'ensure_custom_avatar_cached(bot, character_id)' in bg
    assert 'character_id = get_user_character(telegram_id)' in bg


def test_invoice_titles_use_selected_character_name():
    assert "f'Фото от {_character_display_name(get_user_character(telegram_id))}'" in MAIN
    assert 'f"Кастомное фото · {_character_display_name(get_user_character(telegram_id))}"' in MAIN
    assert 'f"Фото · {_character_display_name(get_user_character(telegram_id))}"' in MAIN
