"""V3.20.1 static pins: USD Visa/Mastercard premium button, spoken circles
(Veo-native voice), and Gemini 2.5 TTS as the primary voice provider."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
VOICE = (ROOT / 'services' / 'voice_service.py').read_text(encoding='utf-8')
FK = (ROOT / 'services' / 'freekassa_service.py').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


def test_version_bumped():
    # Superseded by V3.21.0 (couple layer); the USD/circle/TTS pins below stay valid.
    assert VERSION in ('3.20.1', '3.21.0', '3.22.0', '3.23.0', '3.24.0', '3.25.0', '3.26.0', '3.26.1', '3.30.0', '3.30.1', '3.30.2', '3.30.3')


def test_usd_price_config():
    assert 'FREEKASSA_PREMIUM_PRICE_USD = max(1, int(os.getenv("FREEKASSA_PREMIUM_PRICE_USD", "5")))' in CONFIG


def test_payment_url_supports_currency():
    assert 'currency: str | None = None' in FK
    assert '&currency=' in FK


def test_usd_button_in_premium_keyboard():
    kb = MAIN[MAIN.index('def premium_keyboard('):MAIN.index('def adult_keyboard():')]
    assert "callback_data='fk:premium_usd'" in kb
    assert 'Visa/Mastercard' in kb


def test_usd_handler_invoices_usd():
    handler = MAIN[MAIN.index("@dp.callback_query(F.data == 'fk:premium_usd')"):
                   MAIN.index("@dp.callback_query(F.data.startswith('walletpay:'))")]
    assert 'FREEKASSA_PREMIUM_PRICE_USD' in handler
    assert "currency='USD'" in handler
    assert "'premium_month'" in handler


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
