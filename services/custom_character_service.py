"""V3.19.0: personal character constructor (WildGrl-style).

Users build a private companion through a step-by-step Telegram wizard:
age, body, hair, eyes, temperament, profession, relationship role, name and
an optional face photo (face-swap identity anchor). After a one-time Stars
payment the avatar is generated and the persona plugs into the existing
chat/memory/relationship pipeline through a stable character_id.
"""
from __future__ import annotations

import json
import logging

from models.app_models import CustomCharacter
from services.db import SessionLocal

logger = logging.getLogger(__name__)

CUSTOM_CHARACTER_PREFIX = 'custom_'


def is_custom_character(character_id: str | None) -> bool:
    return bool(character_id) and character_id.startswith(CUSTOM_CHARACTER_PREFIX)


def custom_character_id(telegram_id: int) -> str:
    return f'{CUSTOM_CHARACTER_PREFIX}{telegram_id}'


# Ordered wizard steps. Each option is (callback value, Russian label,
# English descriptor used inside the generation prompt).
CONSTRUCTOR_STEPS: list[dict] = [
    {
        'key': 'age', 'title': 'Сколько ей лет?',
        'options': [
            ('age_young', '18–22', 'early twenties'),
            ('age_mid', '23–27', 'mid twenties'),
            ('age_mature', '28–33', 'around thirty'),
            ('age_confident', '34+', 'confident woman in her mid thirties'),
        ],
    },
    {
        'key': 'body', 'title': 'Какая у неё фигура?',
        'options': [
            ('body_slim', 'Стройная', 'slim elegant figure'),
            ('body_sport', 'Спортивная', 'toned athletic figure'),
            ('body_curvy', 'Пышная', 'soft curvy figure'),
            ('body_fit', 'Фитоняшка', 'fit gym body'),
        ],
    },
    {
        'key': 'hair', 'title': 'Какие у неё волосы?',
        'options': [
            ('hair_blonde', 'Блондинка', 'long blonde hair'),
            ('hair_brunette', 'Брюнетка', 'long dark brunette hair'),
            ('hair_red', 'Рыжая', 'vivid red hair'),
            ('hair_brown', 'Шатенка', 'chestnut brown hair'),
        ],
    },
    {
        'key': 'eyes', 'title': 'Какие у неё глаза?',
        'options': [
            ('eyes_brown', 'Карие', 'warm brown eyes'),
            ('eyes_blue', 'Голубые', 'bright blue eyes'),
            ('eyes_green', 'Зелёные', 'green eyes'),
            ('eyes_grey', 'Серые', 'grey eyes'),
        ],
    },
    {
        'key': 'temperament', 'title': 'Какой у неё характер?',
        'options': [
            ('temper_gentle', 'Нежная и заботливая', 'gentle, caring and affectionate'),
            ('temper_bold', 'Дерзкая и страстная', 'bold, passionate and dominant'),
            ('temper_playful', 'Игривая хулиганка', 'playful mischievous tease'),
            ('temper_mystery', 'Загадочная интеллектуалка', 'mysterious intellectual'),
        ],
    },
    {
        'key': 'profession', 'title': 'Кем она работает?',
        'options': [
            ('prof_model', 'Модель', 'fashion model'),
            ('prof_student', 'Студентка', 'university student'),
            ('prof_trainer', 'Фитнес-тренер', 'fitness trainer'),
            ('prof_artist', 'Артистка', 'performing artist'),
            ('prof_business', 'Бизнес-леди', 'businesswoman'),
        ],
    },
    {
        'key': 'role', 'title': 'Кем она тебе?',
        'options': [
            ('role_girlfriend', 'Девушка', 'loving girlfriend'),
            ('role_friends', 'Подруга с привилегиями', 'flirty friend with benefits'),
            ('role_ex', 'Бывшая, которая вернулась', 'returned ex-girlfriend'),
            ('role_secret', 'Тайная возлюбленная', 'secret lover'),
        ],
    },
]

# Russian labels per option value for summary screens and logs.
OPTION_LABELS: dict[str, str] = {
    value: label
    for step in CONSTRUCTOR_STEPS
    for value, label, _ in step['options']
}
# English descriptors per option value for prompt building.
OPTION_DESCRIPTORS: dict[str, str] = {
    value: descriptor
    for step in CONSTRUCTOR_STEPS
    for value, label, descriptor in step['options']
}

PARAM_TITLES: dict[str, str] = {step['key']: step['title'].rstrip('?') for step in CONSTRUCTOR_STEPS}


def step_index(key: str) -> int:
    for index, step in enumerate(CONSTRUCTOR_STEPS):
        if step['key'] == key:
            return index
    return -1


def build_avatar_prompt(params: dict, face_swap: bool = False) -> str:
    """English Seedream/Gemini prompt assembled from constructor params."""
    name = str(params.get('name') or 'the woman')
    parts = [
        'Photorealistic portrait of an adult woman in a cozy warm evening setting, '
        'soft golden light, shallow depth of field, fashion-editorial quality.',
    ]
    for key in ('age', 'body', 'hair', 'eyes'):
        descriptor = OPTION_DESCRIPTORS.get(str(params.get(key, '')))
        if descriptor:
            parts.append(descriptor)
    temper = OPTION_DESCRIPTORS.get(str(params.get('temperament', '')))
    if temper:
        parts.append(f'personality reads as {temper}')
    prof = OPTION_DESCRIPTORS.get(str(params.get('profession', '')))
    if prof:
        parts.append(f'styled like a {prof}')
    if face_swap:
        parts.append(
            'CRITICAL: preserve the exact same face, facial features and identity '
            'as the person in the reference photo — same nose, lips, jawline and '
            'eye shape. Do not beautify or change the face.'
        )
    parts.append('She looks directly at the viewer with a warm confident smile.')
    parts.append(
        'Tasteful elegant outfit, fully covered; no nudity. One person only, '
        'no text, no watermark.'
    )
    return ', '.join(parts)


def build_persona_context(params: dict, display_name: str) -> str:
    """System-prompt override that makes the chat model play the custom persona."""
    name = display_name or str(params.get('name') or 'она')
    lines = [
        f'ВАЖНОЕ ПЕРЕОПРЕДЕЛЕНИЕ РОЛИ: ты больше не стандартный персонаж бота. '
        f'Ты — личный персонаж пользователя по имени {name}. Оставайся в этом образе всегда.',
    ]
    descriptors = []
    for key in ('age', 'body', 'hair', 'eyes', 'temperament', 'profession'):
        descriptor = OPTION_DESCRIPTORS.get(str(params.get(key, '')))
        if descriptor:
            descriptors.append(descriptor)
    if descriptors:
        lines.append('Твой образ: ' + ', '.join(descriptors) + '.')
    role = OPTION_DESCRIPTORS.get(str(params.get('role', '')))
    if role:
        lines.append(f'Твоя роль по отношению к пользователю: {role}.')
    lines.append(
        'Если пользователь прикладывал своё фото при создании — ты выглядишь именно так, '
        'как на нём. Никогда не упоминай, что ты конструктор или шаблон.'
    )
    return '\n'.join(lines)


# ── DB operations ──────────────────────────────────────────────────────────

def save_custom_character(
    telegram_id: int,
    *,
    display_name: str,
    params: dict,
    avatar_file_id: str | None = None,
    face_file_id: str | None = None,
) -> CustomCharacter:
    character_id = custom_character_id(telegram_id)
    with SessionLocal() as session:
        row = session.query(CustomCharacter).filter_by(telegram_id=str(telegram_id)).first()
        if row is None:
            row = CustomCharacter(telegram_id=str(telegram_id), character_id=character_id)
            session.add(row)
        row.display_name = display_name
        row.params_json = json.dumps(params, ensure_ascii=False)
        if avatar_file_id:
            row.avatar_file_id = avatar_file_id
        if face_file_id:
            row.face_file_id = face_file_id
        session.commit()
        session.refresh(row)
        return row


def get_custom_character(telegram_id: int) -> CustomCharacter | None:
    with SessionLocal() as session:
        return session.query(CustomCharacter).filter_by(telegram_id=str(telegram_id)).first()


def get_custom_character_by_id(character_id: str) -> CustomCharacter | None:
    with SessionLocal() as session:
        return session.query(CustomCharacter).filter_by(character_id=character_id).first()


def custom_character_params(character_id: str) -> tuple[dict, str]:
    """Return (params dict, display name) for a custom character, or ({}, '')."""
    row = get_custom_character_by_id(character_id)
    if not row:
        return {}, ''
    try:
        params = json.loads(row.params_json or '{}')
    except (TypeError, ValueError):
        params = {}
    return params, row.display_name or ''


def custom_persona_context(character_id: str) -> str:
    """Persona override for the chat model; '' for built-in characters."""
    if not is_custom_character(character_id):
        return ''
    params, name = custom_character_params(character_id)
    if not params:
        return ''
    return build_persona_context(params, name)


def summary_lines(params: dict, display_name: str) -> list[str]:
    """Human-readable summary for the confirmation screen."""
    lines = [f'👤 Имя: {display_name}']
    for key, title in PARAM_TITLES.items():
        value = OPTION_LABELS.get(str(params.get(key, '')))
        if value:
            lines.append(f'{title}: {value}')
    return lines
