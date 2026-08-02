import tempfile
from openai import AsyncOpenAI
from config import TTS_API_KEY, TTS_MODEL, TTS_VOICE, AI_BASE_URL

client = AsyncOpenAI(api_key=TTS_API_KEY, base_url=AI_BASE_URL)

async def synthesize(text: str) -> str:
    response = await client.audio.speech.create(model=TTS_MODEL, voice=TTS_VOICE, input=text, response_format="mp3")
    fd, path = tempfile.mkstemp(prefix="anna_voice_", suffix=".mp3")
    with open(fd, "wb", closefd=True) as f:
        f.write(response.content)
    return path
