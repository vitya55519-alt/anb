"""Voice service: TTS (text-to-speech) and STT (speech-to-text).

Provider priority:
  TTS: Gemini 2.5 TTS (natural human-like voices, V3.20.1)
       → edge-tts (free, no API key) → OpenAI TTS (if key present)
  STT: faster-whisper (local, free) → OpenAI Whisper (if key present)
"""
import asyncio
import base64
import io
import logging
import tempfile
from pathlib import Path

from config import (
    TTS_API_KEY, TTS_MODEL, TTS_VOICE, AI_BASE_URL, OPENAI_VOICE_AVAILABLE,
    GEMINI_API_KEY, GEMINI_TTS_ENABLED, GEMINI_TTS_MODEL, GEMINI_VIDEO_BASE_URL,
)

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

# ── Gemini 2.5 TTS prebuilt voices (V3.20.1): one cute female voice per girl ─
GEMINI_TTS_VOICES = {
    'anna_01': 'Leda',
    'alena_01': 'Kore',
    'maria_01': 'Aoede',
}
_DEFAULT_GEMINI_TTS_VOICE = GEMINI_TTS_VOICES['anna_01']

# V3.25.0: Google rotates TTS model names (2.5 preview was superseded by the
# 3.1 preview).  Walk the chain on 404/400 so the human-like voice survives
# model shutdowns; an explicit GEMINI_TTS_MODEL env override is tried first.
_TTS_MODEL_CHAIN = tuple(dict.fromkeys(
    [GEMINI_TTS_MODEL, 'gemini-3.1-flash-tts-preview', 'gemini-2.5-flash-preview-tts']
))
_tts_good_model: str | None = None


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

    # V3.20.1: Gemini TTS first — a natural, human-like cute voice (the same
    # audio family heard in Veo videos); edge-tts sounded robotic to the owner.
    if GEMINI_TTS_ENABLED:
        try:
            return await _tts_gemini(text, character_id)
        except Exception as exc:
            logger.warning('gemini-tts failed: %s; falling back to edge-tts', exc)

    # Try edge-tts (free, no API key needed)
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


async def _tts_gemini(text: str, character_id: str | None = None) -> bytes:
    """V3.20.1: Gemini Flash TTS over REST — natural cute female voices.

    V3.25.0: model chain with a remembered working model; one backoff retry
    on 429/503 per model.  Returns opus when ffmpeg is available, else a WAV
    container (Telegram still plays it as a voice file).
    """
    global _tts_good_model
    voice_name = GEMINI_TTS_VOICES.get(character_id or '', _DEFAULT_GEMINI_TTS_VOICE)
    models = ([_tts_good_model] if _tts_good_model in _TTS_MODEL_CHAIN else []) + [
        m for m in _TTS_MODEL_CHAIN if m != _tts_good_model
    ]
    last_error: Exception = RuntimeError('gemini_tts_no_model')
    for model in models:
        for attempt in range(2):
            try:
                audio = await _tts_gemini_model(text, voice_name, model)
            except RuntimeError as exc:
                last_error = exc
                status = str(exc).removeprefix('gemini_tts_http_')
                if status in {'429', '503'} and attempt == 0:
                    await asyncio.sleep(2.0)
                    continue
                break  # 404/400/etc: this model is dead for us, try the next
            except Exception as exc:
                last_error = exc
                break
            _tts_good_model = model
            return audio
    raise last_error


async def _tts_gemini_model(text: str, voice_name: str, model: str) -> bytes:
    import httpx

    payload = {
        'contents': [{'parts': [{'text': text}]}],
        'generationConfig': {
            'responseModalities': ['AUDIO'],
            'speechConfig': {
                'voiceConfig': {'prebuiltVoiceConfig': {'voiceName': voice_name}},
            },
        },
    }
    headers = {'x-goog-api-key': GEMINI_API_KEY, 'Content-Type': 'application/json'}
    url = f'{GEMINI_VIDEO_BASE_URL}/models/{model}:generateContent'
    timeout = httpx.Timeout(60.0, connect=20.0, read=60.0, write=60.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, headers=headers, json=payload)
        if r.status_code >= 400:
            logger.warning('Gemini TTS failed model=%s status=%s body=%s', model, r.status_code, r.text[:400])
            raise RuntimeError(f'gemini_tts_http_{r.status_code}')
        data = r.json()
    pcm_b64 = None
    for part in ((data.get('candidates') or [{}])[0].get('content') or {}).get('parts') or []:
        inline = part.get('inlineData') or part.get('inline_data') or {}
        if inline.get('data'):
            pcm_b64 = inline['data']
            break
    if not pcm_b64:
        raise RuntimeError('gemini_tts_empty_audio')
    wav = _pcm16_to_wav(base64.b64decode(pcm_b64), rate=24000)
    try:
        return await _convert_wav_to_opus(wav)
    except Exception:
        return wav


def _pcm16_to_wav(pcm: bytes, rate: int = 24000) -> bytes:
    """Wrap raw 16-bit mono PCM (Gemini TTS output) into a WAV container."""
    import struct
    header = b'RIFF' + struct.pack('<I', 36 + len(pcm)) + b'WAVE'
    header += b'fmt ' + struct.pack('<IHHIIHH', 16, 1, 1, rate, rate * 2, 2, 16)
    header += b'data' + struct.pack('<I', len(pcm))
    return header + pcm


async def _convert_wav_to_opus(wav_bytes: bytes) -> bytes:
    """Convert wav bytes to opus using pydub + ffmpeg (for voice bubbles)."""
    import asyncio

    def _convert():
        from pydub import AudioSegment
        audio = AudioSegment.from_wav(io.BytesIO(wav_bytes))
        out = io.BytesIO()
        audio.export(out, format='opus', codec='libopus', bitrate='64k')
        return out.getvalue()

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _convert)
