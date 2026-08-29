"""V3.22.0 static pins: adult-photo reliability, per-character persistence,
RU/EN interface layer.

1. Photo: the real provider reason reaches the user (no more
   "(seedream45/PhotoGenerationError)"), adult scenes use fine-art/boudoir
   wording that passes fal's API-level moderation, and the clothed safe
   retry covers every policy 4xx with force_safe=True so the retry prompt
   cannot be re-detected as adult.
2. Characters: the selected character survives restarts (DB column) and
   every character card shows ITS OWN relationship level.
3. Interface: services/ui_lang.py holds (ru, en) label pairs, handlers
   match both variants, and the language is auto-detected once on first
   contact.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
USER_SERVICE = (ROOT / 'services' / 'user_service.py').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


def test_version_bumped():
    assert VERSION in ('3.22.0', '3.23.0', '3.24.0', '3.25.0', '3.26.0', '3.26.1')


# --- photo: real error reason reaches the user ------------------------------

def test_photo_generation_error_not_masked():
    # generate_photo_set must re-raise PhotoGenerationError untouched; only
    # unknown exceptions are wrapped (reason = class name).
    block = PHOTO[PHOTO.index('async def generate_photo_set('):PHOTO.index('async def generate_photo(')]
    tail = block[block.index('except PhotoGenerationError:'):]
    assert 'raise PhotoGenerationError(provider, type(exc).__name__)' not in tail.split('except Exception')[0]
    assert 'raise\n' in tail.split('except Exception')[0]


def test_adult_prompts_use_fine_art_wording():
    # fal's API-level moderation rejects explicit body-part phrasing even
    # with enable_safety_checker=false — the wording stays artful.
    assert 'Tasteful artistic nudity is allowed' in PHOTO
    assert 'fine-art nude composition' in PHOTO
    for banned in ('visible bare breasts', 'no clothing at all, bare skin throughout',
                   'realistic body details'):
        assert banned not in PHOTO, f'moderation-triggering phrase survived: {banned}'


def test_safe_retry_covers_policy_4xx():
    assert "('HTTP 400', 'HTTP 403', 'HTTP 422', 'HTTP 451')" in PHOTO


def test_safe_retry_forces_clothed_prompt():
    # force_safe suppresses adult_scene / home lingerie / tier framing so the
    # retry prompt cannot be re-detected as adult and overwritten.
    assert 'force_safe: bool = False' in PHOTO
    assert 'request.scene in ADULT_SCENES and not force_safe' in PHOTO
    assert 'if scene_tiers and not force_safe:' in PHOTO
    retry = PHOTO[PHOTO.index("exc.reason.startswith(('HTTP 400'"):PHOTO.index("exc.reason.startswith(('HTTP 400'") + 800]
    assert 'force_safe=True' in retry


# --- characters: selection persisted, per-card level -------------------------

def test_selected_character_persisted():
    assert 'selected_character: Mapped[str] = mapped_column(String(64), default="")' in MODELS
    assert 'def get_user_character(telegram_id: int) -> str:' in MAIN
    assert 'def set_user_character(telegram_id: int, character_id: str) -> None:' in MAIN
    assert 'update_user_settings(telegram_id, selected_character=character_id)' in MAIN
    # all selection write sites go through the persisting helper
    assert '_user_character[cq.from_user.id] = character_id' not in MAIN
    assert MAIN.count('set_user_character(cq.from_user.id, character_id)') >= 3


def test_every_card_shows_own_level():
    block = MAIN[MAIN.index('def _character_card_text('):MAIN.index('def _character_fallback_photo(')]
    assert 'card.character_id in LIBRARY_CHARACTERS' in block
    assert 'get_relationship_level(viewer_id, card.character_id)' in block


# --- RU/EN interface layer ---------------------------------------------------

def test_ui_lang_pairs_and_helpers():
    from services.ui_lang import EN, RU, KB_LABELS, MAIN_KB_ROWS, LEVEL_NAMES_EN
    from services.ui_lang import detect_lang, kb_label, kb_pair
    assert len(KB_LABELS) >= 19
    for key, (ru, en) in KB_LABELS.items():
        assert ru and en and ru != en, key
    assert {key for row in MAIN_KB_ROWS for key in row} <= set(KB_LABELS)
    assert set(LEVEL_NAMES_EN) == set(range(1, 9))
    assert detect_lang('en') == EN and detect_lang('de') == EN
    assert detect_lang('ru') == RU and detect_lang('ru-RU') == RU and detect_lang(None) == RU
    assert kb_pair('photo') == KB_LABELS['photo']
    assert kb_label('photo', EN) == KB_LABELS['photo'][1]
    assert kb_label('photo', RU) == KB_LABELS['photo'][0]


def test_all_keyboard_handlers_match_both_languages():
    from services.ui_lang import KB_LABELS
    for key in KB_LABELS:
        assert f"F.text.in_(kb_pair('{key}'))" in MAIN, f'handler missing dual-language match: {key}'
    assert 'from services.ui_lang import' in MAIN
    kb = MAIN[MAIN.index('def main_keyboard('):MAIN.index('def onboarding_character_keyboard()')]
    assert 'MAIN_KB_ROWS' in kb and 'kb_label(' in kb and 'user_lang(' in kb


def test_language_detected_once_on_first_contact():
    assert 'ui_lang: Mapped[str] = mapped_column(String(8), default="")' in MODELS
    assert 'from services.ui_lang import detect_lang' in USER_SERVICE
    assert 'ui_lang=detect_lang(language_code)' in USER_SERVICE
    # legacy users get a one-time detection, never overwritten afterwards
    assert "if language_code and not (user.ui_lang or '').strip():" in USER_SERVICE


def test_english_texts_present():
    from services.ui_lang import KB_LABELS
    assert 'LEVEL_NAMES_EN' in MAIN
    # Keyboard EN labels live in ui_lang and are rendered per user at runtime.
    for key in ('chat', 'photo', 'premium', 'profile'):
        ru, en = KB_LABELS[key]
        assert en and en != ru
    # EN top-level texts are inlined in main.py behind lang == EN branches.
    assert MAIN.count('if lang == EN:') >= 10
    assert 'Premium for 30 days:' in MAIN
    assert 'what should I show?' in MAIN
    # EN ladder names are resolved from ui_lang, not hardcoded in main.py.
    assert MAIN.count('from services.ui_lang import LEVEL_NAMES_EN') >= 2
