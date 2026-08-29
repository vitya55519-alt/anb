"""Static regression tests for v3.16.3: welcome features list, per-character
multilingual voices and gradual outfit-reveal progression by relationship level.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
VOICE = (ROOT / 'services' / 'voice_service.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')


def test_welcome_message_lists_bot_abilities():
    start = MAIN[MAIN.index('@dp.message(CommandStart())'):]
    start = start.split('@dp.callback_query', 1)[0]
    for fragment in ('Что я умею', '📸', '🎬', '🎙', 'уровням 1–8'):
        assert fragment in start


def test_abilities_text_covers_video_and_voice():
    block = MAIN[MAIN.index('def abilities_text'):]
    block = block.split('\n\n\ndef ', 1)[0]
    assert 'Оживить фото' in block
    assert 'свой милый голос' in block
    assert 'на твоём языке' in block
    assert 'уровням 1–8' in block


def test_three_characters_have_distinct_voice_profiles():
    assert 'CHARACTER_VOICE_PROFILES' in VOICE
    for cid in ('anna_01', 'alena_01', 'maria_01'):
        assert f"'{cid}'" in VOICE
    # Russian voices answer Russian users.
    assert 'ru-RU-SvetlanaNeural' in VOICE
    assert 'ru-RU-DariyaNeural' in VOICE
    # Distinct cute English voices, one per girl.
    assert 'en-US-AriaNeural' in VOICE
    assert 'en-US-JennyNeural' in VOICE
    assert 'en-US-MichelleNeural' in VOICE


def test_voice_language_follows_user_text():
    assert 'def detect_voice_language' in VOICE
    assert '\\u0400' in VOICE  # Cyrillic range detection
    assert "return 'ru'" in VOICE


def test_synthesize_accepts_character_id():
    assert 'character_id' in VOICE
    assert 'def pick_edge_voice' in VOICE
    assert 'synthesize_bytes(text, user.voice_style, character_id=character_id)' in MAIN


def test_level_rules_gradual_reveal_with_lingerie_hint():
    rules = PHOTO[PHOTO.index('LEVEL_VISUAL_RULES = {'):]
    rules = rules.split('}\nOPENAI_LEVEL_VISUAL_RULES', 1)[0]
    # Level 1 stays fully clothed, no exposure, but a bra outline under a
    # blouse is allowed as a tasteful hint.
    assert 'level 1/6' in rules
    assert 'bra outline under a thin blouse' in rules
    assert 'never exposed' in rules
    # Reveal grows with levels, but V3.19.2 caps it: levels 5-6 stay fully
    # covered in public scenes (no visible lingerie), intimacy moved to the
    # private scenes.
    assert 'open back or off-shoulder' in rules
    assert 'no visible lingerie' in rules
    # Every level stays non-explicit.
    for key in ('level 1/6', 'level 4/6', 'level 6/6'):
        assert key in rules


def test_openai_level_rules_share_reveal_progression():
    rules = PHOTO[PHOTO.index('OPENAI_LEVEL_VISUAL_RULES = {'):]
    rules = rules.split('}\n\nSEASON_RULES', 1)[0]
    assert 'bra outline under a thin blouse' in rules
    assert 'open back or off-shoulder' in rules
    assert 'fully clothed' in rules


def test_quality_block_max_realism():
    block = PHOTO[PHOTO.index('QUALITY_BLOCK = ('):]
    block = block.split(')\n', 1)[0]
    assert 'authentic candid amateur photo feel' in block
    assert 'micro-imperfections' in block
    assert 'no CGI' in block
