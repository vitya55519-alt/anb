"""V3.19.0: vision reactions to user photos (WildGrl-style).

When a user sends a photo in chat, the multimodal chat provider describes it
and the active character reacts in-character. Fails silently in the caller —
a missing/broken reaction must never block the normal chat flow.
"""
from __future__ import annotations

import logging

from services.character_card_service import get_card
from services.llm_provider_service import generate_text

logger = logging.getLogger(__name__)

MAX_REACTION_CHARS = 300
MAX_BASE64_BYTES = 3_000_000  # keep the vision payload inside provider limits

REACTION_INSTRUCTION = (
    'Пользователь прислал тебе фото. Опиши коротко, что на нём, и отреагируй '
    'живо, тепло и в своём характере — как отреагировала бы близкая девушка в '
    'переписке. 1–3 коротких предложения, можно с эмоцией или лёгким флиртом, '
    'по ситуации (селфи — комплимент; еда/питомец/зал/место — интерес к детали). '
    'Не упоминай, что анализируешь изображение, и не описывай людей откровенно.'
)


def _character_name(character_id: str) -> str:
    try:
        card = get_card(character_id)
        if card and card.display_name:
            return card.display_name
    except Exception:
        pass
    return 'Анна'


async def react_to_photo(
    image_b64: str,
    *,
    mime_type: str = 'image/jpeg',
    caption: str | None = None,
    character_id: str = 'anna_01',
) -> str | None:
    """Return an in-character reaction to the photo, or None when unavailable.

    Uses the OpenAI-compatible multimodal message format so the existing
    OpenRouter/Gemini chain handles the image natively.
    """
    if not image_b64 or len(image_b64) > MAX_BASE64_BYTES:
        return None
    name = _character_name(character_id)
    text_part = REACTION_INSTRUCTION
    if caption and caption.strip():
        text_part += f'\nПодпись пользователя к фото: «{caption.strip()[:200]}»'
    messages = [
        {
            'role': 'system',
            'content': f'Ты — {name}, персонаж Telegram-бота, общаешься с пользователем лично и тепло.',
        },
        {
            'role': 'user',
            'content': [
                {'type': 'text', 'text': text_part},
                {
                    'type': 'image_url',
                    'image_url': {'url': f'data:{mime_type};base64,{image_b64}'},
                },
            ],
        },
    ]
    try:
        result = await generate_text(
            messages, max_tokens=200, temperature=0.85, purpose='photo_reaction',
        )
    except Exception as exc:
        logger.warning('photo reaction failed: %s: %s', type(exc).__name__, exc)
        return None
    reaction = (result.text or '').strip()
    if not reaction:
        return None
    return reaction[:MAX_REACTION_CHARS]
