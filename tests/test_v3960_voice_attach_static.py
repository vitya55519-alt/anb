"""V3.96.0 — Telegram's input in the app chat: the 📎 is back, the mic is the
round button.

The owner asked for a Telegram-style voice button instead of the 🎤 emoji in the
field, and for the paperclip so he can send the girl a photo (V3.57.4 had hidden
it on his earlier ask). The round button is the mic while the field is empty and
the paper plane once he types; hold to record, release to send, slide left to
cancel, a quick tap records hands-free. His photo only goes to the vision model
(Gemini) for a text reaction — it is never edited or sent to an image engine.
Static pins only, no network.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
CFG = (ROOT / 'config.py').read_text(encoding='utf-8')
LLM = (ROOT / 'services' / 'llm_provider_service.py').read_text(encoding='utf-8')
REACT = (ROOT / 'services' / 'photo_reaction_service.py').read_text(encoding='utf-8')


def test_photo_intake_is_on_by_default():
    assert 'PHOTO_REACTION_ENABLED = os.getenv("PHOTO_REACTION_ENABLED", "true")' in CFG
    if 'PHOTO_REACTION_ENABLED' not in os.environ:
        import config
        assert config.PHOTO_REACTION_ENABLED is True


def test_attach_button_is_visible_with_a_paperclip_icon():
    assert '#chatAttach { display: none; }' not in SPA
    assert '<button id="chatAttach" class="inbtn" type="button" aria-label="photo"><svg' in SPA


def test_round_button_switches_between_mic_and_send():
    assert '<button id="chatSend" class="mic" type="button" aria-label="send"><svg class="ic-mic"' in SPA
    assert '<svg class="ic-send"' in SPA
    assert "btn.classList.toggle('mic', !_recLocked && !input.value.trim());" in SPA
    assert "document.getElementById('chatText').addEventListener('input', syncSendBtn);" in SPA
    # the emoji mic inside the field is gone
    assert 'id="chatMic"' not in SPA


def test_slide_to_cancel_and_hands_free_send():
    assert 'if (dx > 90) { _recHold = false; cancelChatVoice(); }' in SPA
    assert "if (cancelled) { try { tg.HapticFeedback.notificationOccurred('warning'); } catch (e) {} return; }" in SPA
    assert 'if (_rec && _recLocked) { _rec.stop(); return; }' in SPA
    assert "document.getElementById('recCancel').addEventListener('click', cancelChatVoice);" in SPA
    for key in ('rec_hint', 'rec_cancel', 'attach_wait'):
        assert SPA.count(f'{key}:') >= 2, key


def test_his_voice_note_is_a_player_with_the_heard_text():
    body = SPA[SPA.index('async function sendChatVoice('):SPA.index('function shrinkImage(')]
    assert 'voicePlayer(URL.createObjectURL(blob))' in body
    assert '<div class="vtx"></div>' in body


def test_photo_is_shrunk_and_carries_the_caption():
    body = SPA[SPA.index('async function sendChatPhoto('):SPA.index('// ── V3.39.0: in-app chat media')]
    assert 'const small = await shrinkImage(file);' in body
    assert 'caption: caption' in body
    assert "1280 / Math.max(img.naturalWidth, img.naturalHeight)" in SPA
    ep = MAIN[MAIN.index('async def _webapp_api_chat_photo('):MAIN.index('async def _webapp_api_chat_persona(')]
    assert "caption = str(body.get('caption', '') or '').strip()[:300]" in ep
    assert "'error': 'too_big'" in ep


def test_his_photo_only_goes_to_vision_never_to_an_image_engine():
    ep = MAIN[MAIN.index('async def _webapp_api_chat_photo('):MAIN.index('async def _webapp_api_chat_persona(')]
    for bad in ('spicy', 'Spicy', 'seedream', 'undress', 'edit_image', 'fal'):
        assert bad not in ep, bad
    # vision skips the text-only MiniMax and goes straight to Gemini
    assert "VISION_PURPOSES = frozenset({'photo_reaction', 'evening_photo_qc'})" in LLM
    assert 'if _minimax and purpose not in VISION_PURPOSES:' in LLM
    # hard lines in the prompt: no body talk, nude photos declined, no promises to edit
    assert 'Если на фото обнажённое тело или интим' in REACT
    assert 'Никогда не обещай что-то сделать с фото' in REACT
