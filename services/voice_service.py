"""Voice service: TTS (text-to-speech) and STT (speech-to-text).

Provider priority:
  TTS: edge-tts (free, no API key) → OpenAI TTS (if key present)
  STT: faster-whisper (local, free) → OpenAI Whisper (if key present)
"""
import io
import logging
import tempfile
from pathlib import Path

from config import TTS_API_KEY, TTS_MODEL, TTS_VOICE, AI_BASE_URL, OPENAI_VOICE_AVAILABLE

logger = logging.getLogger(__name__)

# ── edge-tts voices mapping (OpenAI voice → closest edge-tts equivalent) ──
_EDGE_VOICE_MAP = {
    'alloy': 'en-US-AriaNeural',
    'echo': 'en-US-GuyNeural',
    'fable': 'en-GB-RyanNeural',
    'nova': 'en-US-JennyNeural',
    'onyx': 'en-US-ChristopherNeural',
    'shimmer': 'en-US-AriaNeural',
}

# Public constant used by main.py for /voice_style command validation.
VALID_VOICES = tuple(_EDGE_VOICE_MAP.keys())

# ── per-character cute female voices, one profile per language ─────────────
# Each girl has her own voice; the language is picked from the text itself
# (user writes Russian → Russian voice, English → English voice).
CHARACTER_VOICE_PROFILES = {
    'anna_01': {
        'ru': ('ru-RU-SvetlanaNeural', {'rate': '+3%', 'pitch': '+2Hz'}),
        'en': ('en-US-AriaNeural', {'rate': '+2%', 'pitch': '+2Hz'}),
    },
    'alena_01': {
        'ru': ('ru-RU-DariyaNeural', {'rate': '+4%', 'pitch': '+3Hz'}),
        'en': ('en-US-JennyNeural', {'rate': '+3%', 'pitch': '+2Hz'}),
    },
    'maria_01': {
        'ru': ('ru-RU-SvetlanaNeural', {'rate': '+1%', 'pitch': '+7Hz'}),
        'en': ('en-US-MichelleNeural', {'rate': '+1%', 'pitch': '+4Hz'}),
    },
}
_DEFAULT_VOICE_PROFILE = CHARACTER_VOICE_PROFILES['anna_01']


def detect_voice_language(text: str) -> str:
    """Reply voice follows the user's language: Cyrillic text → ru, else en."""
    return 'ru' if any('\u0400' <= ch <= '\u04FF' for ch in text) else 'en'


def pick_edge_voice(text: str, character_id: str | None = None) -> tuple[str, dict]:
    """Return (edge_voice, edge_kwargs) for a character and the text language."""
    profile = CHARACTER_VOICE_PROFILES.get(character_id or '', _DEFAULT_VOICE_PROFILE)
    return profile[detect_voice_language(text)]

# ── OpenAI client (optional, only if key is present) ──────────────────────
_openai_client = None
if OPENAI_VOICE_AVAILABLE:
    try:
        from openai import AsyncOpenAI
        _openai_client = AsyncOpenAI(api_key=TTS_API_KEY, base_url=AI_BASE_URL)
    except Exception:
        _openai_client = None


async def transcribe(voice_bytes: io.BytesIO) -> str:
    """Transcribe voice message (ogg/opus) to text."""
    # Try faster-whisper first (local, free, no API)
    try:
        return await _transcribe_faster_whisper(voice_bytes)
    except ImportError:
        pass
    except Exception as exc:
        logger.warning('faster-whisper failed: %s; falling back to OpenAI', exc)

    # Fallback to OpenAI Whisper (requires API key)
    if _openai_client:
        return await _transcribe_openai(voice_bytes)

    raise RuntimeError('No STT provider available. Install faster-whisper: pip install faster-whisper')


async def _transcribe_faster_whisper(voice_bytes: io.BytesIO) -> str:
    """Use faster-whisper for local speech-to-text."""
    import asyncio
    from faster_whisper import WhisperModel

    voice_bytes.seek(0)
    audio_data = voice_bytes.read()

    # Write to temp file (faster-whisper needs a file path)
    with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as tmp:
        tmp.write(audio_data)
        tmp_path = tmp.name

    try:
        loop = asyncio.get_event_loop()
        model = WhisperModel('base', device='cpu', compute_type='int8')
        segments, _ = await loop.run_in_executor(None, model.transcribe, tmp_path)
        text = ' '.join(seg.text for seg in segments).strip()
        return text
    finally:
        Path(tmp_path).unlink(missing_ok=True)


async def _transcribe_openai(voice_bytes: io.BytesIO) -> str:
    """Use OpenAI Whisper API."""
    voice_bytes.seek(0)
    r = await _openai_client.audio.transcriptions.create(
        model='whisper-1',
        file=('voice.ogg', voice_bytes, 'audio/ogg'),
    )
    return r.text


async def synthesize_bytes(text: str, voice: str | None = None, character_id: str | None = None) -> bytes:
    """Synthesize text to speech audio bytes (opus format).

    The voice follows the character (each girl has her own cute voice) and the
    language of the text itself. An explicit legacy `voice` style still wins.
    """
    v = voice if voice in _EDGE_VOICE_MAP else TTS_VOICE

    # Try edge-tts first (free, no API key needed)
    try:
        return await _tts_edge_tts(text, v, character_id)
    except ImportError:
        pass
    except Exception as exc:
        logger.warning('edge-tts failed: %s; falling back to OpenAI', exc)

    # Fallback to OpenAI TTS
    if _openai_client:
        return await _tts_openai(text, v)

    raise RuntimeError('No TTS provider available. Install edge-tts: pip install edge-tts')


async def _tts_edge_tts(text: str, voice: str, character_id: str | None = None) -> bytes:
    """Use edge-tts (free Microsoft TTS) to synthesize speech.

    A known character uses that girl's own voice in the text's language;
    an explicit /voice_style choice keeps the legacy single-voice behavior.
    """
    import edge_tts

    if voice in _EDGE_VOICE_MAP and voice != TTS_VOICE:
        communicate = edge_tts.Communicate(text, _EDGE_VOICE_MAP[voice])
    else:
        edge_voice, edge_kwargs = pick_edge_voice(text, character_id)
        communicate = edge_tts.Communicate(text, edge_voice, **edge_kwargs)

    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk['type'] == 'audio':
            buf.write(chunk['data'])

    audio_bytes = buf.getvalue()
    if not audio_bytes:
        raise RuntimeError('edge-tts produced empty audio')

    # edge-tts outputs mp3; convert to opus for Telegram voice messages
    try:
        return await _convert_mp3_to_opus(audio_bytes)
    except Exception:
        # If conversion fails, return mp3 (Telegram can play it)
        return audio_bytes


async def _convert_mp3_to_opus(mp3_bytes: bytes) -> bytes:
    """Convert mp3 bytes to opus using pydub + ffmpeg."""
    import asyncio

    def _convert():
        from pydub import AudioSegment
        audio = AudioSegment.from_mp3(io.BytesIO(mp3_bytes))
        out = io.BytesIO()
        audio.export(out, format='opus', codec='libopus', bitrate='64k')
        return out.getvalue()

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _convert)


async def _tts_openai(text: str, voice: str) -> bytes:
    """Use OpenAI TTS API."""
    v = voice if voice in ('alloy', 'echo', 'fable', 'nova', 'onyx', 'shimmer') else TTS_VOICE
    r = await _openai_client.audio.speech.create(
        model=TTS_MODEL, voice=v, input=text, response_format='opus',
    )
    return r.content
