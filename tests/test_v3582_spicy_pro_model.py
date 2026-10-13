"""V3.58.2: SpicyAPI moved to Seedream 5.0 Pro. The retired «5.0-lite» id and
the undocumented «size» field made every job fail, so all photo scenes fell
through to the censored fal leg or the over-quota Gemini leg."""
import asyncio
import os
from pathlib import Path

os.environ.setdefault("TELEGRAM_TOKEN", "123456:test-fake-token-for-static-tests-only")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-for-static-tests-only")

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
PRIVATE = (ROOT / 'services' / 'private_photo_service.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')


def test_defaults_are_pro_model_ids():
    assert '"bytedance/seedream-5.0-pro/edit"' in CONFIG
    assert '"bytedance/seedream-5.0-pro/text-to-image"' in CONFIG
    assert '"bytedance/seedream-5.0-lite' not in CONFIG


def test_request_uses_only_documented_fields():
    assert '"size": ' not in PRIVATE
    assert '"aspect_ratio": "3:4"' in PRIVATE
    assert '"resolution": SPICYAPI_RESOLUTION' in PRIVATE
    assert '"enable_thinking": SPICYAPI_ENABLE_THINKING' in PRIVATE
    assert 'body.get("code") not in (200, 201, 202)' in PRIVATE


def test_real_failure_reason_reaches_refusals_screen():
    assert "record_provider('spicyapi', bool(data), None if data else spicyapi_last_error())" in PHOTO
    from services import private_photo_service as pps
    pps._spicy_note_error('')
    assert pps.spicyapi_last_error() == 'empty_result'
    pps._spicy_note_error(RuntimeError('SpicyAPI error: 400 unknown field size ' + 'x' * 300))
    assert pps.spicyapi_last_error().startswith('SpicyAPI error: 400')
    assert len(pps.spicyapi_last_error()) <= 120
    pps._spicy_note_error('')
