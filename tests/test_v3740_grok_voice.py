"""V3.74.0: her voice replies go through Grok TTS (SpicyAPI) first; free
Gemini TTS stays the fallback."""
import asyncio
import os

os.environ.setdefault("TELEGRAM_TOKEN", "123456:test-fake-token-for-static-tests-only")

from services import voice_service as vs  # noqa: E402


def test_voice_per_girl():
    assert vs.grok_voice_for('anna_01') == 'eve'
    assert vs.grok_voice_for('maria_01') == 'ara'
    assert vs.grok_voice_for('custom_abc') == 'eve'
    assert vs.grok_voice_for(None) == 'eve'


def test_grok_first_then_gemini(monkeypatch):
    from services import spicy_jobs, spend_service
    sent = []

    async def fake_run(model, block, *, timeout, first_wait=3.0):
        sent.append((model, dict(block)))
        return b'ID3mp3', 'audio/mpeg', 0.001

    async def fake_opus(mp3):
        return b'OggS' + mp3

    monkeypatch.setattr(vs, 'SPICY_TTS_ENABLED', True)
    monkeypatch.setattr(vs, 'SPICYAPI_KEY', 'k')
    monkeypatch.setattr(spicy_jobs, 'run', fake_run)
    monkeypatch.setattr(spend_service, 'record_image_spend', lambda *a, **k: None)
    monkeypatch.setattr(vs, '_convert_mp3_to_opus', fake_opus)
    out = asyncio.run(vs.synthesize_bytes('Привет, я скучала', character_id='maria_01'))
    assert out == b'OggSID3mp3'
    (model, block), = sent
    assert model == 'xai/grok-tts/text-to-speech'
    assert block == {'text': 'Привет, я скучала', 'voice_id': 'ara', 'language': 'ru'}


def test_grok_failure_falls_back_to_gemini(monkeypatch):
    from services import spicy_jobs

    async def boom(*a, **k):
        raise spicy_jobs.SpicyJobError('failed: x')

    async def fake_gemini(text, character_id=None):
        return b'gemini'

    monkeypatch.setattr(vs, 'SPICY_TTS_ENABLED', True)
    monkeypatch.setattr(vs, 'SPICYAPI_KEY', 'k')
    monkeypatch.setattr(vs, 'GEMINI_TTS_ENABLED', True)
    monkeypatch.setattr(spicy_jobs, 'run', boom)
    monkeypatch.setattr(vs, '_tts_gemini', fake_gemini)
    assert asyncio.run(vs.synthesize_bytes('hello there', character_id='anna_01')) == b'gemini'
