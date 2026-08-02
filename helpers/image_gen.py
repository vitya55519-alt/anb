import logging
import openai
from openai import AsyncOpenAI
from config import AI_KEY

logger = logging.getLogger(__name__)
_client = AsyncOpenAI(api_key=AI_KEY)

_ROLE_APPEARANCES = {
    'estudiante': 'adult woman, youthful university style, long hair, casual outfit, warm smile',
    'trabajadora': 'adult woman around 30, elegant business-casual style, confident expression',
    'artista': 'adult woman with a bohemian creative style, expressive eyes, natural smile',
    'deportista': 'adult athletic woman in tasteful sportswear, energetic expression',
    'gamer': 'adult woman with headphones, cozy hoodie, playful expression',
    'misteriosa': 'adult woman with a dark elegant aesthetic, distinctive eyes, subtle confident expression',
}
_DEFAULT_APPEARANCE = 'adult woman with warm eyes, natural proportions and a gentle confident smile'


def _get_default_appearance(role_description: str) -> str:
    desc_lower = role_description.lower() if role_description else ''
    for keyword, appearance in _ROLE_APPEARANCES.items():
        if keyword in desc_lower:
            return appearance
    return _DEFAULT_APPEARANCE


async def generate_selfie(waifu_name: str, role_description: str, appearance: str | None = None, scene: str = 'selfie') -> str:
    """Generate a conversational photo. Appearance is treated as a stable identity profile."""
    base_appearance = appearance or _get_default_appearance(role_description)
    scene_text = {
        'selfie': 'natural smartphone selfie in an ordinary everyday setting',
        'cafe': 'natural smartphone photo in a cozy cafe with coffee',
        'home': 'casual smartphone photo at home during a relaxed evening',
        'park': 'natural smartphone photo during a walk in a green city park',
        'evening': 'stylish evening smartphone photo in a tasteful adult outfit',
        'mirror': 'natural full-body mirror photo in a tidy apartment',
        'outfit': 'natural smartphone photo showing a casual everyday outfit',
    }.get(scene, 'natural smartphone selfie')
    prompt = (
        f"Realistic smartphone photograph of the same fictional adult woman named {waifu_name}. "
        f"Stable character appearance: {base_appearance}. "
        f"Scene: {scene_text}. Preserve the described face, eye color, hair, body proportions and overall visual identity "
        f"as consistently as possible from the text profile. Natural skin texture, realistic anatomy, ordinary phone-camera framing, "
        f"unretouched candid feel, coherent lighting. No anime, no illustration, no text, no watermark. "
        f"She is an adult fictional character."
    )
    try:
        response = await _client.images.generate(
            model="dall-e-3", prompt=prompt, size="1024x1024", quality="standard", n=1,
        )
        return response.data[0].url
    except openai.APIError as e:
        logger.error("Image generation failed: %s", e)
        raise
