import io
from openai import AsyncOpenAI
from config import TTS_API_KEY, TTS_MODEL, TTS_VOICE, AI_BASE_URL
client=AsyncOpenAI(api_key=TTS_API_KEY,base_url=AI_BASE_URL)
VALID_VOICES=('alloy','echo','fable','nova','onyx','shimmer')
async def transcribe(voice_bytes:io.BytesIO)->str:
    voice_bytes.seek(0)
    r=await client.audio.transcriptions.create(model='whisper-1',file=('voice.ogg',voice_bytes,'audio/ogg'))
    return r.text
async def synthesize_bytes(text:str,voice:str|None=None)->bytes:
    v=voice if voice in VALID_VOICES else TTS_VOICE
    r=await client.audio.speech.create(model=TTS_MODEL,voice=v,input=text,response_format='opus')
    return r.content
