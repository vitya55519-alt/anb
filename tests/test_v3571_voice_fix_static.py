"""V3.57.1 — voice send reliability + Telegram-style mic placement.

faster-whisper kept reloading (and re-downloading on cold start) the ~75 MB
model on EVERY transcription, so the first voice message after a deploy timed
out. The model is now a warm singleton, Gemini flash audio is a fallback STT
leg, and the mic/attach buttons live inside the text field with hold-to-record
pointer events. Static pins only.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
VOICE = (ROOT / 'services' / 'voice_service.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_whisper_model_is_a_warm_singleton():
    assert '_whisper_model = None' in VOICE
    assert 'def _get_whisper_model():' in VOICE
    assert 'model = await loop.run_in_executor(None, _get_whisper_model)' in VOICE
    # the heavy constructor must not run inline in the transcription path anymore
    assert VOICE.count("WhisperModel('base', device='cpu', compute_type='int8')") == 1


def test_gemini_stt_fallback_leg():
    assert 'async def _transcribe_gemini(' in VOICE
    assert "if GEMINI_API_KEY:" in VOICE
    body = VOICE[VOICE.index('async def transcribe('):VOICE.index('async def _transcribe_faster_whisper(')]
    # order: local whisper → Gemini audio → OpenAI, and the last error resurfaces
    assert body.index('_transcribe_faster_whisper') < body.index('_transcribe_gemini') < body.index('_transcribe_openai')
    assert "'gemini-2.5-flash'" in VOICE
    assert "'audio/ogg'" in VOICE


def test_spa_buttons_live_inside_the_field():
    # Telegram layout: input + icons in one wrapper, send button stays outside
    assert '.chat-field { position: relative;' in SPA
    assert '.chat-field input { flex: 1; min-width: 0; padding-right: 48px; }' in SPA
    assert '<div class="chat-field">' in SPA
    assert 'class="inbtn"' in SPA
    field = SPA[SPA.index('<div class="chat-field">'):SPA.index('</div>\n    <button id="chatSend">')]
    assert 'id="chatMic"' in field and 'id="chatAttach"' in field
    assert 'id="chatSend"' not in field


def test_hold_to_record_pointer_flow():
    assert "function micDown()" in SPA
    assert "function micUp()" in SPA
    assert 'window.addEventListener(\'pointerup\', micUp)' in SPA
    # release after a hold sends; a quick tap keeps recording hands-free
    assert 'if ((Date.now() - _recStart) > 450) _rec.stop();' in SPA
    # the old click-toggle is gone for good
    assert 'toggleChatMic' not in SPA
