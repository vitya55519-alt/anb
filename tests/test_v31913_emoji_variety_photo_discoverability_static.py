"""Static pins for v3.19.13: emoji variety + in-chat photo discoverability.

Owner feedback: the character kept repeating a single smiley in chat, and a
new user could not tell that photos can be requested right inside the
conversation. The character prompt now carries an explicit emoji-variety
block and a hint line where she herself tells the user that photos can be
asked for in chat; the /features text names the in-chat photo request.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAR = (ROOT / 'services' / 'character_service.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def test_emoji_variety_block_in_character_prompt():
    assert 'ЭМОДЗИ' in CHAR
    # No single-emoji fixation: the model must rotate emoji by mood.
    assert 'Не залипай на одном' in CHAR
    assert 'не ставь один и тот же эмодзи в двух сообщениях подряд' in CHAR
    # Bounded, human-like usage.
    assert '0–2 эмодзи на сообщение' in CHAR
    # A varied palette is offered, not one smiley.
    for emoji in ('😏', '😘', '🥰', '😈', '💋', '🙄', ''):
        assert emoji in CHAR


def test_character_hints_user_that_photos_can_be_asked_in_chat():
    assert 'просто попроси фотку прямо здесь' in CHAR
    assert 'Он может не знать, что это возможно' in CHAR


def test_features_text_names_in_chat_photo_request():
    block = MAIN[MAIN.index('def abilities_text'):MAIN.index('def abilities_inline_keyboard')]
    assert 'фото прямо в чате' in block
    assert 'скинь фото' in block
    assert 'иногда предлагает сама' in block
