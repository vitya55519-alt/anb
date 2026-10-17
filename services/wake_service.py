"""V3.63.2: the alarm is HER waking him — a line in her own character, sent as
a voice note (free edge/Gemini TTS, no extra keys), escalating gently over the
attempts, with a «☀️ я проснулся» button that stops it. Fail-soft: any LLM or
TTS failure falls back to the old fixed lines as plain text."""
import logging

logger = logging.getLogger(__name__)

# Old fixed lines — still the fallback when the LLM is unavailable.
WAKE_FALLBACK = (
    'доброе утро ☀️ подъём',
    'эй, ты там проснулся? 😂',
    'соня, вставай уже',
    'я всё ещё здесь 🙄',
    'ну всё, последний шанс 😌',
    'ладно, сдаюсь 😂',
)
WAKE_DELAYS = (2, 3, 5, 7, 10, 10)
WAKE_ATTEMPTS = len(WAKE_FALLBACK)

_STAGE_HINT = (
    'Первое, ласковое пробуждение: нежно, тепло, с «доброе утро».',
    'Он не ответил. Чуть настойчивее, игриво.',
    'Всё ещё спит. Подразни его, придумай повод встать.',
    'Уже немного обиженно-шутливо, но любя.',
    'Последний шанс: пообещай что-то приятное, если он встанет прямо сейчас.',
    'Сдаёшься с юмором и тёплым пожеланием хорошего дня.',
)


def fallback_line(attempt: int) -> str:
    return WAKE_FALLBACK[min(max(attempt, 0), WAKE_ATTEMPTS - 1)]


async def wake_line(telegram_id: int, character_id: str, attempt: int,
                    name: str = '', lang: str = 'ru') -> str:
    """One short wake-up line in her voice; falls back to the fixed list."""
    idx = min(max(attempt, 0), WAKE_ATTEMPTS - 1)
    try:
        from services.life_event_service import _character_ingredients
        her_name, _tastes, temperament = _character_ingredients(character_id)
        bits = [
            f'Ты — {her_name}.' if her_name else 'Ты — его девушка.',
            temperament,
            'Он сам попросил тебя разбудить его утром, и сейчас это время.',
            _STAGE_HINT[idx],
            f'Его зовут {name}.' if name and name != 'ты' else '',
            'Напиши ОДНУ короткую фразу (до 120 знаков), которую ты скажешь ему голосом. '
            'Живо, от первого лица, без эмодзи, без кавычек, не упоминай, что ты ИИ.',
            'Пиши по-английски.' if lang == 'en' else '',
        ]
        from services.llm_provider_service import generate_text
        r = await generate_text([
            {'role': 'system', 'content': ' '.join(b for b in bits if b)},
            {'role': 'user', 'content': 'Разбуди его сейчас.'},
        ], max_tokens=70, temperature=0.95, purpose='wake')
        text = (getattr(r, 'text', '') or '').strip().strip('"«»').strip()
        if len(text) >= 6:
            return text[:200]
    except Exception:
        logger.warning('wake line LLM failed user=%s', telegram_id, exc_info=True)
    return fallback_line(idx)


async def wake_voice(text: str, character_id: str, voice_style: str | None = None) -> bytes | None:
    """Her voice for the line, or None when TTS fails (caller sends text)."""
    clean = ''.join(ch for ch in text if ch.isalnum() or ch in ' .,!?:;-—…()\'\n')
    if not clean.strip():
        return None
    try:
        from services.voice_service import synthesize_bytes
        return await synthesize_bytes(clean, voice_style, character_id=character_id)
    except Exception:
        logger.warning('wake voice TTS failed char=%s', character_id, exc_info=True)
        return None
