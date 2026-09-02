"""V3.25.0 static pins: constructor avatar engines, reference downscaling,
fal error transparency, TTS model chain.

Covers:
1. generate_custom_avatar finally has real engines (_seedream_edit face-swap
   and _gemini_edit text-to-image) — before V3.25.0 the two helpers were
   referenced but never defined, so every avatar crashed with NameError.
2. Oversized canonical references (~5 MB PNGs) are downscaled to compact JPEG
   before base64 embedding — multi-MB payloads were a likely fal HTTP 422.
3. fal 4xx bodies are carried (shortened) inside the PhotoGenerationError
   reason, so the chat error chain shows WHY the request was rejected.
4. Gemini TTS walks a model chain (3.1 preview → 2.5 preview) and remembers
   the working model, so the human-like voice survives model rotation.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
VOICE = (ROOT / 'services' / 'voice_service.py').read_text(encoding='utf-8')
REQ = (ROOT / 'requirements.txt').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


def test_version_bumped():
    assert VERSION in ('3.25.0', '3.26.0', '3.26.1', '3.30.0', '3.30.1')


def test_constructor_avatar_engines_exist():
    assert 'async def _seedream_edit(reference_path: Path | None, prompt: str) -> tuple[bytes, str]:' in PHOTO
    assert 'async def _gemini_edit(prompt: str, reference_path: Path | None = None) -> tuple[bytes, str]:' in PHOTO
    assert 'return await _seedream_edit(reference_path, prompt)' in PHOTO
    assert 'return await _gemini_edit(prompt, reference_path)' in PHOTO
    # face-swap only makes sense with a reference; no-ref goes straight to Gemini
    assert 'if FAL_KEY and reference_path:' in PHOTO


def test_reference_images_downscaled_before_embedding():
    assert '_DATA_URI_CACHE' in PHOTO
    assert 'from PIL import Image' in PHOTO
    assert 'def _image_b64(' in PHOTO
    # the Gemini frame loop and the Seedream/constructor paths use the downscaler
    assert 'data, mime = _image_b64(ref)' in PHOTO
    assert '_file_data_uri(reference_path)' in PHOTO


def test_fal_error_body_reaches_user_reason():
    assert "detail = ' '.join(body.split())[:140]" in PHOTO
    assert "f'HTTP {response.status_code} {detail}'" in PHOTO
    # safe retry trigger still fires on the enriched reasons
    assert "exc.reason.startswith(('HTTP 400', 'HTTP 403', 'HTTP 422', 'HTTP 451'))" in PHOTO


def test_tts_model_chain_survives_model_rotation():
    assert 'gemini-3.1-flash-tts-preview' in VOICE
    assert 'gemini-2.5-flash-preview-tts' in VOICE
    assert '_TTS_MODEL_CHAIN' in VOICE
    assert 'async def _tts_gemini_model(' in VOICE
    assert '_tts_good_model = model' in VOICE


def test_pillow_dependency_declared():
    assert 'Pillow' in REQ
