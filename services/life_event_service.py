"""V3.52.0: «Жизнь без тебя» — proactive, personality-grounded life moments.

She occasionally writes first NOT as a guilt/«why don't you text» nudge, but
because something happened in her (fictional) day and she wants to share it —
ideally tying in a detail from the two of your shared history and ending on an
open loop that makes replying a single tap. Everything is grounded in the
SELECTED character's own personality (her tastes / tone / temperament), so no
two girls "live" the same life — which also nudges the «все как Анна» gap.

Fail-silent by design: any error (no LLM, no character, empty output) returns
``{}`` and the scheduler simply skips the slot, so a life event can never blank
out a conversation or spam a user.
"""
from __future__ import annotations

import logging
import random

from config import LIFE_EVENTS_PHOTO_CHANCE

logger = logging.getLogger(__name__)

# Universal low-friction tap-backs. The whole point is to turn a one-way push
# into a reply with a single tap (reply-rate is what actually moves D1/D7). The
# value carries the character so the callback can continue HER exact story.
_REPLY_OPTIONS = (
    ('🍿 расскажи дальше', 'tell_more'),
    ('😏 скучал(а) по тебе', 'miss_you'),
)

_WHEN_HINT = {'morning': 'утро', 'day': 'день', 'evening': 'вечер', 'night': 'ночь'}

# When the user tapped the «расскажи дальше» button, this is the stand-in user
# turn fed to the normal reply pipeline so she continues the moment in context.
_TAP_AS_USER_TEXT = {
    'tell_more': 'расскажи, что было дальше 👀',
    'miss_you': 'я тоже по тебе скучал(а) 🥰',
}


def tap_reply_text(key: str) -> str:
    """Map a life-event tap-back key to the natural user line it should send."""
    return _TAP_AS_USER_TEXT.get(str(key or ''), 'расскажи подробнее')


def _character_ingredients(character_id: str) -> tuple[str, list[str], str]:
    """Return (name, hobby/taste pool, temperament line) for grounding."""
    name = ''
    tastes: list[str] = []
    try:
        from services.character_service import get_character
        ch = get_character(character_id) or {}
        name = ch.get('name') or ''
        tastes = list((ch.get('personality') or {}).get('stable_tastes') or [])[:6]
    except Exception:
        logger.debug('life ingredients character lookup failed %s', character_id)
    # constructor / community personas: get_character silently falls back to
    # Anna, so pull their own minimal card instead when they exist.
    if not name or not tastes:
        try:
            from services.custom_character_service import custom_base_character
            cc = custom_base_character(character_id)
            if cc:
                name = cc.get('name') or name
                tastes = list((cc.get('personality') or {}).get('stable_tastes') or [])[:6] or tastes
        except Exception:
            pass
    temperament = ''
    try:
        from services.relationship_engine import PACE_HINTS
        temperament = PACE_HINTS.get(character_id, '') or ''
    except Exception:
        pass
    return (name, tastes, temperament)


def _memory_callback(telegram_id: int, character_id: str) -> str:
    """~45% of the time, surface one stored fact so she references shared history."""
    if random.random() > 0.45:
        return ''
    try:
        from services.user_service import ensure_user
        from services.memory_service import get_memories
        mems = get_memories(ensure_user(telegram_id), character_id, 12)
        if not mems:
            return ''
        return str(getattr(random.choice(mems), 'content', '') or '')[:200]
    except Exception:
        return ''


def _pending_hook(telegram_id: int) -> str:
    """~40% of the time, hand back the user's own unfinished topic to continue."""
    if random.random() > 0.40:
        return ''
    try:
        from services.user_service import get_state
        return str(getattr(get_state(telegram_id), 'pending_hook', '') or '')[:300]
    except Exception:
        return ''


def _system_prompt(name: str, when: str, tastes: list[str], temperament: str,
                   mem: str, hook: str) -> str:
    bits = [
        f'Ты — {name}.' if name else 'Ты — она.',
        temperament,
        f'Сейчас у пользователя {_WHEN_HINT.get(when, "день")}.',
        'Напиши ОДНУ короткую живую строчку (до ~200 знаков) от первого лица: '
        'случайный момент из твоего дня или жизни, которым ты сама решила поделиться. '
        'Это НЕ «скучаю / почему не пишешь» и НЕ вопрос о его активности — это именно '
        'событие из твоей жизни, как настоящая смс в мессенджере.',
    ]
    if tastes:
        bits.append('Зацепка для момента (одна из твоих тем/вкусов): ' + random.choice(tastes) + '.')
    if mem:
        bits.append(f'Можешь естественно вспомнить деталь от пользователя и связать её со своим моментом: «{mem}».')
    if hook:
        bits.append(f'Незакрытая тема пользователя, к которой можно вернуться: «{hook}».')
    bits.append(
        'Закончи открытой петлёй — мини-вопросом или интригой («угадай, что было '
        'дальше»), чтобы в ответ было легко написать одной фразой. Без хэштегов, '
        'не упоминай, что ты ИИ или что это рассылка.'
    )
    return ' '.join(b for b in bits if b)


async def build_life_moment(telegram_id: int, character_id: str, when: str = 'day') -> dict:
    """Compose one spontaneous life message. Returns {} on any failure/empty."""
    try:
        name, tastes, temperament = _character_ingredients(character_id)
        mem = _memory_callback(telegram_id, character_id)
        hook = _pending_hook(telegram_id)
        system = _system_prompt(name, when, tastes, temperament, mem, hook)
        from services.llm_provider_service import generate_text
        r = await generate_text([{'role': 'system', 'content': system}],
                                max_tokens=90, temperature=0.95, purpose='life_event')
        text = (getattr(r, 'text', '') or '').strip().strip('"').strip()
        if len(text) < 8:
            return {}
        photo = None
        if LIFE_EVENTS_PHOTO_CHANCE and random.random() < LIFE_EVENTS_PHOTO_CHANCE:
            try:
                from services.retention_features_service import random_proactive_photo
                photo = random_proactive_photo()
            except Exception:
                photo = None
        options = [(lbl, f'life_reply:{character_id}:{key}') for lbl, key in _REPLY_OPTIONS]
        return {'text': text, 'photo': photo, 'options': options, 'when': when}
    except Exception:
        logger.exception('build_life_moment failed user=%s char=%s', telegram_id, character_id)
        return {}
