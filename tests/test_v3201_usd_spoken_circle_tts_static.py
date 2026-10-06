"""V3.20.1 static pins: spoken circles (Veo-native voice), Gemini 2.5 TTS
as the primary voice provider, and the USD price tag next to the Stars
prices (a display-only number since the multi-currency kassa retired in
V3.44.21 — Platega invoices in rubles)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
VOICE = (ROOT / 'services' / 'voice_service.py').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


def test_version_bumped():
    # Superseded by V3.21.0 (couple layer); the USD/circle/TTS pins below stay valid.
    assert VERSION in ('3.44.4', '3.44.3', '3.43.7', '3.43.6', '3.43.5', '3.43.4', '3.43.3', '3.43.2', '3.43.1', '3.43.0', '3.42.2', '3.42.1', '3.42.0', '3.41.0', '3.40.0', '3.20.1', '3.21.0', '3.22.0', '3.23.0', '3.24.0', '3.25.0', '3.26.0', '3.26.1', '3.30.0', '3.30.1', '3.30.2', '3.30.3', '3.30.4', '3.30.5', '3.30.6', '3.30.7', '3.30.8', '3.30.9', '3.31.0', '3.31.1', '3.31.2', '3.31.3', '3.31.4', '3.31.5', '3.31.6', '3.31.7', '3.31.8', '3.32.0', '3.32.1', '3.33.0', '3.33.1', '3.34.0', '3.34.1', '3.35.0', '3.36.0', '3.37.0', '3.38.0', '3.39.0')


def test_usd_price_config():
    # V3.44.21: display-only — the real USD charge died with the FreeKassa
    # multi-currency kassa; Platega invoices in rubles.
    assert 'PREMIUM_PRICE_USD = max(1, int(os.getenv("PREMIUM_PRICE_USD", "8")))' in CONFIG


def test_circles_are_spoken():
    assert 'CIRCLE_PHRASES' in MAIN
    assert 'soft, cute, natural female' in MAIN
    assert 'CIRCLE_PROMPT.format(phrase=' in MAIN


def test_gemini_tts_primary_provider():
    assert 'GEMINI_TTS_ENABLED' in VOICE
    assert '_tts_gemini' in VOICE
    # Gemini TTS is attempted before the robotic edge-tts.
    assert VOICE.index('return await _tts_gemini(text, character_id)') < \
        VOICE.index('return await _tts_edge_tts(text, v, character_id)')
    assert '_pcm16_to_wav' in VOICE
    assert 'GEMINI_TTS_VOICES' in VOICE
