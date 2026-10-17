"""V3.63.3: live-sounding TTS direction + STT on the live Gemini model."""
from pathlib import Path

VOICE = (Path(__file__).resolve().parents[1] / 'services' / 'voice_service.py').read_text(encoding='utf-8')


def test_tts_gets_a_spoken_style_direction():
    assert "'contents': [{'parts': [{'text': _TTS_STYLE + manner + text}]}]" in VOICE
    assert 'voice message to the man she loves' in VOICE


def test_stt_tries_the_live_chat_model_first():
    from services import voice_service
    from config import GEMINI_CHAT_MODEL
    assert voice_service._STT_MODEL_CHAIN[0] == GEMINI_CHAT_MODEL
    assert 'gemini-2.0-flash' not in voice_service._STT_MODEL_CHAIN


def test_tts_provider_is_logged():
    assert "logger.info('tts ok provider=gemini model=%s voice=%s', model, voice_name)" in VOICE
    assert "logger.info('tts ok provider=edge (robotic fallback)')" in VOICE
