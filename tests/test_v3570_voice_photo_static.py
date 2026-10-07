"""V3.57.0 — voice messages and user photos in the Mini App chat.

The mic button records locally (MediaRecorder), the SPA posts base64 audio to
/webapp/api/chat/voice, Whisper transcribes it and the turn continues through
the exact text pipeline; her reply may come back with a voice note when the
user has voice replies enabled (Premium perk, same gate as Telegram).
📎 posts a photo to /webapp/api/chat/photo — the vision model looks at it and
she reacts in character (compliments him). Static pins only, no network.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_voice_and_photo_routes_registered():
    assert "app.router.add_post('/webapp/api/chat/voice', _webapp_api_chat_voice)" in MAIN
    assert "app.router.add_post('/webapp/api/chat/photo', _webapp_api_chat_photo)" in MAIN


def test_shared_gate_and_turn_helpers():
    assert 'def _webapp_chat_gate(' in MAIN
    assert 'async def _webapp_chat_turn(' in MAIN
    # the text, voice and photo endpoints all pass through the same gate
    assert MAIN.count('gate = _webapp_chat_gate(character_id, telegram_id)') == 3
    assert MAIN.count('return await _webapp_chat_turn(') == 2


def test_voice_endpoint_transcribes_then_reuses_the_text_pipeline():
    body = MAIN[MAIN.index('async def _webapp_api_chat_voice('):MAIN.index('async def _webapp_api_chat_photo(')]
    assert 'await transcribe(io.BytesIO(data))' in body
    # 5 MB hard cap, and an empty transcription never reaches the model
    assert "if not data or len(data) > 5 * 1024 * 1024:" in body
    assert "'no_speech'" in body
    # the heard text goes back so the SPA can show his bubble
    assert "extra={'user_text': heard}" in body


def test_reply_voice_note_keeps_the_premium_gate():
    body = MAIN[MAIN.index('async def _webapp_reply_voice_url('):MAIN.index('async def _webapp_chat_turn(')]
    # same rules as the Telegram _send_voice_note: toggle + Premium (admins bypass)
    assert "getattr(user, 'voice_enabled', False)" in body
    assert 'if telegram_id not in ADMIN_TELEGRAM_IDS and not is_premium(telegram_id):' in body
    assert 'await synthesize_bytes(clean, user.voice_style, character_id=character_id)' in body
    assert "save_chat_media(telegram_id, audio, 'ogg', 'audio/ogg')" in body
    # a broken TTS must never eat the text reply
    assert 'return None' in body
    # and the reply payload carries it
    turn = MAIN[MAIN.index('async def _webapp_chat_turn('):MAIN.index('async def _webapp_api_chat_send(')]
    assert "payload['voice_url'] = voice_url" in turn


def test_photo_endpoint_reuses_vision_reaction():
    body = MAIN[MAIN.index('async def _webapp_api_chat_photo('):MAIN.index('async def _webapp_api_chat_persona(')]
    assert 'await react_to_photo(image_b64, mime_type=mime, character_id=character_id)' in body
    # same cooldown as the bot photo reaction, same size cap
    assert '_photo_reaction_ts.get(telegram_id, 0) < PHOTO_REACTION_COOLDOWN_SECONDS' in body
    assert 'len(data) > MAX_BASE64_BYTES' in body
    # only real image formats, and the dialog keeps both sides of the moment
    assert "('image/jpeg', 'image/png', 'image/webp')" in body
    assert "save_message(uid, character_id, 'user', '📷', media_kind='photo', media_url=url)" in body
    assert "save_message(uid, character_id, 'assistant', reaction)" in body


def test_spa_mic_and_attach_buttons_exist():
    assert 'id="chatMic"' in SPA
    assert 'id="chatAttach"' in SPA
    assert 'id="chatFileIn"' in SPA
    # V3.57.1: the mic moved to pointer events (hold-to-send like Telegram)
    assert "_micBtn.addEventListener('pointerdown'" in SPA
    assert "document.getElementById('chatFileIn').addEventListener('change'" in SPA


def test_spa_records_with_mediarecorder_and_posts_base64():
    assert 'navigator.mediaDevices.getUserMedia({ audio: true })' in SPA
    assert "MediaRecorder.isTypeSupported('audio/ogg;codecs=opus')" in SPA
    assert "'/webapp/api/chat/voice?init_data='" in SPA
    assert "'/webapp/api/chat/photo?init_data='" in SPA
    # 60 s auto-stop like a Telegram voice note; too-short takes are dropped
    assert 'if (s >= 60 && _rec) _rec.stop();' in SPA
    assert 'L.mic_short' in SPA
    assert 'L.mic_denied' in SPA


def test_spa_renders_heard_text_voice_and_photo_reply():
    assert 'function renderChatReply(' in SPA
    assert "media_kind: 'voice', media_url: j.voice_url" in SPA
    # his bubble shows what the recognition actually heard
    assert "content: '🎤 ' + (j.user_text || '')" in SPA
    # the photo path renders her compliment
    assert 'async function sendChatPhoto(' in SPA
    # the old sendChat must render through the shared helper now
    send = SPA[SPA.index('async function sendChat('):SPA.index('function renderChatReply(')]
    assert 'renderChatReply(j);' in send


def test_spa_locale_strings_for_ru_and_en():
    for key in ('stt_wait', 'mic_denied', 'mic_short', 'mic_nospeech', 'mic_err', 'attach_err', 'attach_big'):
        assert SPA.count(f'{key}:') >= 2, key
