from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
QUEST = (ROOT / 'services' / 'quest_service.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
CFG = (ROOT / 'config.py').read_text(encoding='utf-8')


def test_all_python_parses():
    for path in ROOT.rglob('*.py'):
        ast.parse(path.read_text(encoding='utf-8'), filename=str(path))


def test_user_menu_and_onboarding_are_product_facing():
    assert "KeyboardButton(text='🎭 Образы')" not in MAIN
    # V3.22.0: the features button label moved to services/ui_lang.py pairs.
    from services.ui_lang import KB_LABELS
    assert KB_LABELS['features'][0] == '✨ Возможности'
    assert "F.text.in_(kb_pair('features'))" in MAIN
    assert 'onboarding_character_keyboard' in MAIN
    assert "onboard:character:" in MAIN
    assert "✅ {card.display_name} · выбрать" in MAIN
    assert "🔒 {card.display_name} · скоро" in MAIN
    assert '00_anna_canonical_face_v3.png' in MAIN
    assert 'FSInputFile' in MAIN
    assert 'abilities_text' in MAIN
    assert "Command('features', 'abilities')" in MAIN


def test_quest_ux_has_unlocks_and_progressive_content():
    assert 'newly_unlocked_quests' in QUEST
    assert 'newly_unlocked_quests' in MAIN
    assert "quest:locked:{item['key']}" in MAIN
    assert 'Открылась новая история' in MAIN
    for key in ('outfit_choice', 'evening_choice', 'weekend_choice', 'date_mood', 'surprise_choice', 'our_story_choice'):
        assert key in QUEST
    for level in range(1, 7):
        assert f"'min_level': {level}" in QUEST
    assert 'canonical_route' in QUEST
    assert 'needs_payment' in QUEST


def test_nano_banana_uses_documented_rest_interactions_path():
    assert 'https://generativelanguage.googleapis.com/v1beta/interactions' in PHOTO
    assert "'x-goog-api-key': api_key" in PHOTO
    assert "body.get('steps')" in PHOTO
    assert "content.get('type') == 'image'" in PHOTO
    assert 'invalid_api_key_non_ascii' in PHOTO
    assert 'GEMINI_IMAGE_ASPECT_RATIO' in CFG
    assert 'GEMINI_IMAGE_SIZE' in CFG
