"""V3.57.4 — the owner removed the ability to send a photo to the character.

Before this version a user could push his own picture into the dialog two ways:
the 📎 button in the Mini App chat (POST /webapp/api/chat/photo, V3.57.0) and a
plain photo in the Telegram chat (V3.19.0 vision reaction). Both paths are driven
by one switch — PHOTO_REACTION_ENABLED — which now defaults to false, so the app
endpoint answers {'error': 'disabled'} and the bot silently ignores the picture.

Deliberately reversible (the owner asked for hide + disable, not deletion): the
markup, the JS and both handlers stay in the tree; only the control is hidden and
the flag is off. Static pins only, no network.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
CFG = (ROOT / 'config.py').read_text(encoding='utf-8')

_FLAG_LINE = 'PHOTO_REACTION_ENABLED = os.getenv("PHOTO_REACTION_ENABLED", "false")'


def test_photo_intake_is_off_by_default():
    assert _FLAG_LINE in CFG, 'PHOTO_REACTION_ENABLED must default to "false"'


def test_default_flag_actually_disables_the_reaction():
    # Behavioural check: with no env override the imported constant is False.
    if 'PHOTO_REACTION_ENABLED' in os.environ:
        import pytest
        pytest.skip('PHOTO_REACTION_ENABLED is pinned by the test environment')
    import config
    assert config.PHOTO_REACTION_ENABLED is False


def test_one_switch_gates_both_intake_paths():
    # Mini App endpoint refuses while the flag is off...
    photo = MAIN[MAIN.index('async def _webapp_api_chat_photo('):MAIN.index('async def _webapp_api_chat_persona(')]
    assert 'if not PHOTO_REACTION_ENABLED:' in photo
    assert "'error': 'disabled'" in photo
    # ...and the bot chat never downloads or reads the picture.
    react = MAIN[MAIN.index('async def _react_to_user_photo('):MAIN.index('# ── V3.52.0')]
    assert 'if not PHOTO_REACTION_ENABLED or not has_accepted(' in react


def test_spa_hides_the_attach_button():
    assert '#chatAttach { display: none; }' in SPA
    # the 📎 is the only entry point to the photo upload — no drag&drop or paste
    assert SPA.count('sendChatPhoto(') == 2  # definition + the file-input handler
    assert "'drop'" not in SPA and "addEventListener('paste'" not in SPA
    # the text field gives up the space the hidden button used to reserve
    assert '.chat-field input { flex: 1; min-width: 0; padding-right: 48px; }' in SPA


def test_reversibility_the_code_path_is_only_disabled_not_deleted():
    # Flip the env var back to true and the whole feature returns untouched.
    assert 'id="chatAttach"' in SPA
    assert 'id="chatFileIn"' in SPA
    assert 'async function sendChatPhoto(' in SPA
    assert "app.router.add_post('/webapp/api/chat/photo', _webapp_api_chat_photo)" in MAIN
    assert 'await react_to_photo(image_b64, mime_type=mime, character_id=character_id)' in MAIN
