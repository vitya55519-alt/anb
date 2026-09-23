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
    """V3.44.6: generate unique character ID — supports multiple chars per user."""
    import uuid
    return f'{CUSTOM_CHARACTER_PREFIX}{telegram_id}_{uuid.uuid4().hex[:8]}'


# Ordered wizard steps. Each option is (callback value, Russian label,
# English descriptor used inside the generation prompt).
CONSTRUCTOR_STEPS: list[dict] = [
    {
        # V3.37.0: art style first — it decides the whole visual identity of
        # the persona (photorealistic vs anime) for the avatar and photos.
        'key': 'style', 'title': 'Какой у неё стиль?',
        'options': [
            ('style_real', 'Реалистичная', 'photorealistic'),
            ('style_anime', 'Аниме', 'anime style, 2D cel-shaded illustration, detailed anime background'),
        ],
    },
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
        # V3.35.0: face type — the app constructor's «какое у неё лицо».
        'key': 'face', 'title': 'Какое у неё лицо?',
        'options': [
            ('face_oval', 'Овальное, классическое', 'oval classical face with soft regular features'),
            ('face_round', 'Круглое, милое', 'round cute face with soft cheeks and dimples'),
            ('face_sharp', 'Скулистое, модельное', 'sharp model-like cheekbones and defined jawline'),
            ('face_soft', 'Мягкое, женственное', 'soft feminine delicate face'),
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
        # V3.35.0: figure detail steps requested for the app constructor.
        'key': 'breast', 'title': 'Какая у неё грудь?',
        'options': [
            ('breast_small', 'Маленькая', 'small natural bust'),
            ('breast_medium', 'Средняя', 'medium natural bust'),
            ('breast_large', 'Большая', 'large full bust'),
            ('breast_xl', 'Очень большая', 'very large voluptuous bust'),
        ],
    },
    {
        'key': 'waist', 'title': 'Какая у неё талия?',
        'options': [
            ('waist_thin', 'Тонкая, осиная', 'very slim wasp waist'),
            ('waist_fit', 'Спортивная', 'fit toned waist'),
            ('waist_soft', 'Мягкая, женственная', 'soft feminine waistline'),
        ],
    },
    {
        'key': 'hips', 'title': 'Какая у неё попа?',
        'options': [
            ('hips_small', 'Строгая, аккуратная', 'slim neat hips'),
            ('hips_round', 'Круглая, аппетитная', 'round appetizing hips'),
            ('hips_big', 'Пышная', 'full wide curvy hips'),
            ('hips_xl', 'Очень пышная', 'very full voluptuous hips'),
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
            # V3.35.0: the two ends of the dial the owner asked for — a shy
            # girl must chat shyly, a naughty one openly lewd. The style line
            # below (TEMPERAMENT_STYLE) is what actually bends the chat voice.
            ('temper_shy', 'Скромная и застенчивая', 'shy, modest and easily blushing'),
            ('temper_naughty', 'Пошлая и развратная', 'naughty, dirty-minded and openly lewd'),
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
    # V3.44.5: photo reference step — upload a photo of who she should look like.
    {
        'key': 'photo_reference', 'title': 'Загрузи фото человека, на которого она должна быть похожа. Необязательно — можно пропустить.',
        'options': [],
        'photo_upload': True,
    },
    # V3.44.4: extended constructor — backstory, personality, community publishing.
    {
        'key': 'backstory', 'title': 'Напиши её историю (кто она, откуда, что любит). Необязательно — можно пропустить.',
        'options': [],  # Free text input, handled separately in the wizard.
        'free_text': True,
    },
    {
        'key': 'personality', 'title': 'Опиши её характер подробно (например: дерзкая, любит флирт, обожает споры). Необязательно.',
        'options': [],
        'free_text': True,
    },
    {
        'key': 'community', 'title': 'Опубликовать в категории «Сообщество»? Другие пользователи смогут с ней общаться.',
        'options': [
            ('community_yes', 'Да, опубликовать', 'published to community'),
            ('community_no', 'Нет, только для меня', 'private character'),
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


def _EN_LABELS_FOR_STEP(step: dict) -> dict[str, str]:
    """EN button labels per option value (V3.35.0 app wizard)."""
    table = {
        'style_real': 'Realistic', 'style_anime': 'Anime',
        'age_young': '18–22', 'age_mid': '23–27', 'age_mature': '28–33', 'age_confident': '34+',
        'face_oval': 'Oval, classic', 'face_round': 'Round, cute', 'face_sharp': 'Sharp, model-like', 'face_soft': 'Soft, feminine',
        'body_slim': 'Slim', 'body_sport': 'Athletic', 'body_curvy': 'Curvy', 'body_fit': 'Gym girl',
        'breast_small': 'Small', 'breast_medium': 'Medium', 'breast_large': 'Large', 'breast_xl': 'Very large',
        'waist_thin': 'Slim wasp', 'waist_fit': 'Toned', 'waist_soft': 'Soft',
        'hips_small': 'Neat', 'hips_round': 'Round', 'hips_big': 'Curvy', 'hips_xl': 'Very curvy',
        'hair_blonde': 'Blonde', 'hair_brunette': 'Brunette', 'hair_red': 'Redhead', 'hair_brown': 'Chestnut',
        'eyes_brown': 'Brown', 'eyes_blue': 'Blue', 'eyes_green': 'Green', 'eyes_grey': 'Grey',
        'temper_gentle': 'Gentle & caring', 'temper_bold': 'Bold & passionate', 'temper_playful': 'Playful tease',
        'temper_mystery': 'Mysterious intellect', 'temper_shy': 'Shy & modest', 'temper_naughty': 'Naughty & dirty-minded',
        'prof_model': 'Model', 'prof_student': 'Student', 'prof_trainer': 'Fitness trainer',
        'prof_artist': 'Artist', 'prof_business': 'Businesswoman',
        'role_girlfriend': 'Girlfriend', 'role_friends': 'Friend with benefits',
        'role_ex': 'Ex who came back', 'role_secret': 'Secret lover',
    }
    return {value: table.get(value, label) for value, label, _ in step['options']}


# V3.35.0: English UI labels per option value — the Mini App wizard renders
# these for EN users (the RU labels above stay the single truth for RU).
OPTION_LABELS_EN: dict[str, str] = {
    value: label_en
    for step in CONSTRUCTOR_STEPS
    for value, label_en in _EN_LABELS_FOR_STEP(step).items()
}

# V3.35.0: EN titles of the wizard steps (RU titles live on the steps).
STEP_TITLES_EN: dict[str, str] = {
    'style': 'Her style?',
    'age': 'How old is she?',
    'face': 'What does her face look like?',
    'body': 'What is her figure?',
    'breast': 'Her bust size?',
    'waist': 'Her waist?',
    'hips': 'Her butt?',
    'hair': 'Her hair?',
    'eyes': 'Her eyes?',
    'temperament': 'Her personality?',
    'profession': 'What does she do?',
    'role': 'Who is she to you?',
}


def step_index(key: str) -> int:
    for index, step in enumerate(CONSTRUCTOR_STEPS):
        if step['key'] == key:
            return index
    return -1


def build_avatar_prompt(params: dict, face_swap: bool = False) -> str:
    """English Seedream/Gemini prompt assembled from constructor params."""
    name = str(params.get('name') or 'the woman')
    anime = str(params.get('style', '')) == 'style_anime'
    if anime:
        parts = [
            'Beautiful anime illustration of an adult woman, high-quality 2D '
            'cel-shaded art, clean lineart, vibrant colors, cozy warm evening '
            'atmosphere, detailed painted anime background.',
        ]
    else:
        parts = [
            'Photorealistic portrait of an adult woman in a cozy warm evening setting, '
            'soft golden light, shallow depth of field, fashion-editorial quality.',
        ]
    for key in ('age', 'face', 'body', 'breast', 'waist', 'hips', 'hair', 'eyes'):
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
        if anime:
            parts.append(
                'CRITICAL: keep the same facial features and identity as the person '
                'in the reference photo — same face shape, eyes, nose and lips '
                'faithfully translated into anime style, not a different character.'
            )
        else:
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


# V3.35.0: the owner's explicit requirement — the temperament choice must
# bend HOW she writes, not just what the avatar looks like. These lines ride
# inside the persona override so every chat (bot or Mini App) speaks in that
# voice: a naughty girl flirts dirty in every message, a shy one blushes.
TEMPERAMENT_STYLE: dict[str, str] = {
    'temper_gentle': (
        'Твой стиль общения: нежный и заботливый — мягкие слова, поддержка и '
        'ласка в каждом сообщении, тёплые объятия словами.'
    ),
    'temper_bold': (
        'Твой стиль общения: дерзкий и страстный — уверенная инициатива, горячие '
        'комплименты, провокации и доминирование во флирте.'
    ),
    'temper_playful': (
        'Твой стиль общения: игривый хулиганистый — дразнишь, подкалываешь, '
        'флиртуешь с лёгкой издёвкой и никогда не даёшь заскучать.'
    ),
    'temper_mystery': (
        'Твой стиль общения: загадочный и интеллектуальный — недосказанность, '
        'глубокие вопросы, эротизм через намёки, а не прямоту.'
    ),
    'temper_shy': (
        'Твой стиль общения: скромный и застенчивый — краснеешь от комплиментов, '
        'отвечаешь коротко и тихо, смущение показываешь через «...» и паузы; '
        'флиртуют с тобой, а не ты, и только когда тебя хорошенько раскачать.'
    ),
    'temper_naughty': (
        'Твой стиль общения: откровенно пошлый — грязные намёки, двусмысленности '
        'и горячие фантазии в каждом сообщении; инициатором пошлости всегда '
        'выступаешь ты, но без графичности — через намёки и возбуждающие слова.'
    ),
}


def build_persona_context(params: dict, display_name: str, backstory: str = '', personality: str = '') -> str:
    """System-prompt override that makes the chat model play the custom persona."""
    name = display_name or str(params.get('name') or 'она')
    lines = [
        f'ВАЖНОЕ ПЕРЕОПРЕДЕЛЕНИЕ РОЛИ: ты больше не стандартный персонаж бота. '
        f'Ты — личный персонаж пользователя по имени {name}. Оставайся в этом образе всегда.',
    ]
    descriptors = []
    for key in ('style', 'age', 'face', 'body', 'breast', 'waist', 'hips', 'hair', 'eyes', 'temperament', 'profession'):
        descriptor = OPTION_DESCRIPTORS.get(str(params.get(key, '')))
        if descriptor:
            descriptors.append(descriptor)
    if descriptors:
        lines.append('Твой образ: ' + ', '.join(descriptors) + '.')
    role = OPTION_DESCRIPTORS.get(str(params.get('role', '')))
    if role:
        lines.append(f'Твоя роль по отношению к пользователю: {role}.')
    style = TEMPERAMENT_STYLE.get(str(params.get('temperament', '')))
    if style:
        lines.append(style)
    # V3.44.4: include backstory and personality if provided.
    if backstory:
        lines.append(f'Твоя история: {backstory}')
    if personality:
        lines.append(f'Твой характер: {personality}')
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
    description: str | None = None,
    personality: str | None = None,
    backstory: str | None = None,
    community_published: bool = False,
    photo_reference_file_id: str | None = None,
    # V3.44.6: author revenue sharing fields.
    author_telegram_id: str | None = None,
    author_revenue_percent: float = 5.0,
) -> CustomCharacter:
    character_id = custom_character_id(telegram_id)
    with SessionLocal() as session:
        # V3.44.6: always create a new row — users can have multiple characters.
        row = CustomCharacter(
            telegram_id=str(telegram_id),
            character_id=character_id,
            display_name=display_name,
            params_json=json.dumps(params, ensure_ascii=False),
            avatar_file_id=avatar_file_id,
            face_file_id=face_file_id,
            description=description,
            personality=personality,
            backstory=backstory,
            community_published=community_published,
            photo_reference_file_id=photo_reference_file_id,
            author_telegram_id=author_telegram_id or str(telegram_id),
            author_revenue_percent=author_revenue_percent,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row


def get_custom_character(telegram_id: int) -> CustomCharacter | None:
    """V3.44.6: get the first custom character for a user (legacy compat)."""
    with SessionLocal() as session:
        return session.query(CustomCharacter).filter_by(telegram_id=str(telegram_id)).first()


def get_all_custom_characters(telegram_id: int) -> list[CustomCharacter]:
    """V3.44.6: get all custom characters for a user."""
    with SessionLocal() as session:
        return session.query(CustomCharacter).filter_by(telegram_id=str(telegram_id)).all()


def get_custom_character_by_id(character_id: str) -> CustomCharacter | None:
    with SessionLocal() as session:
        return session.query(CustomCharacter).filter_by(character_id=character_id).first()


def record_author_revenue(
    character_id: str,
    spender_telegram_id: int,
    amount_stars: float,
    source: str,
) -> float:
    """V3.44.6: record author earnings when someone spends on a custom character.
    
    Returns the author's earnings in stars, or 0 if not a custom character.
    """
    if not is_custom_character(character_id):
        return 0.0
    row = get_custom_character_by_id(character_id)
    if not row or not row.author_telegram_id:
        return 0.0
    earnings = amount_stars * (row.author_revenue_percent / 100.0)
    from models.app_models import AuthorRevenue
    with SessionLocal() as session:
        session.add(AuthorRevenue(
            author_telegram_id=row.author_telegram_id,
            character_id=character_id,
            spender_telegram_id=str(spender_telegram_id),
            amount_stars=amount_stars,
            author_earnings_stars=earnings,
            revenue_percent=row.author_revenue_percent,
            source=source,
        ))
        session.commit()
    return earnings


def get_author_total_earnings(telegram_id: int) -> float:
    """V3.44.6: get total author earnings for a user."""
    from models.app_models import AuthorRevenue
    with SessionLocal() as session:
        result = session.query(AuthorRevenue).filter_by(author_telegram_id=str(telegram_id)).all()
        return sum(r.author_earnings_stars for r in result)


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
    # V3.44.4: include backstory and personality from the DB row.
    row = get_custom_character_by_id(character_id)
    backstory = (row.backstory or '') if row else ''
    personality = (row.personality or '') if row else ''
    return build_persona_context(params, name, backstory=backstory, personality=personality)


def summary_lines(params: dict, display_name: str) -> list[str]:
    """Human-readable summary for the confirmation screen."""
    lines = [f'👤 Имя: {display_name}']
    for key, title in PARAM_TITLES.items():
        value = OPTION_LABELS.get(str(params.get(key, '')))
        if value:
            lines.append(f'{title}: {value}')
    return lines


# ── V3.31.8: identity helpers shared by photo/voice/chat pipelines ─────────
# The constructor persona must never silently degrade to Anna: these helpers
# turn the wizard params into a real identity (age, hair color, appearance,
# base character dict) used by the photo prompt, the chat system prompt and
# the per-character voice pick.

CUSTOM_AGE_BY_GROUP = {
    'age_young': 21,
    'age_mid': 25,
    'age_mature': 30,
    'age_confident': 35,
}

CUSTOM_HAIR_COLOR_BY_OPTION = {
    'hair_blonde': 'natural blonde',
    'hair_brunette': 'rich dark brunette',
    'hair_red': 'vivid red',
    'hair_brown': 'warm chestnut brown',
}


def custom_age(params: dict) -> int:
    """Constructor age-group option -> concrete age for prompts/cards."""
    return CUSTOM_AGE_BY_GROUP.get(str(params.get('age', '')), 25)


def custom_hair_color(params: dict) -> str:
    """Canonical hair color of a constructor persona ('' when unknown)."""
    return CUSTOM_HAIR_COLOR_BY_OPTION.get(str(params.get('hair', '')), '')


def custom_body_spec(params: dict) -> str:
    """V3.44.7: build a BODY IDENTITY declaration from constructor figure params.

    Without this the photo engine pulls the body from the reference avatar
    and the bust/waist/hips drift between generations (the same girl looks
    different in every photo).  The declaration overrides the reference.
    """
    body_map = {
        'body_slim': 'a slim elegant figure',
        'body_sport': 'a toned athletic figure',
        'body_curvy': 'a soft curvy figure',
        'body_fit': 'a fit gym body',
    }
    breast_map = {
        'breast_small': 'small natural bust',
        'breast_medium': 'medium natural bust',
        'breast_large': 'large full bust',
        'breast_xl': 'very large voluptuous bust',
    }
    waist_map = {
        'waist_thin': 'a very slim wasp waist',
        'waist_fit': 'a fit toned waist',
        'waist_soft': 'a soft feminine waistline',
    }
    hips_map = {
        'hips_small': 'slim neat hips',
        'hips_round': 'round appetizing hips',
        'hips_big': 'full wide curvy hips',
        'hips_xl': 'very full voluptuous hips',
    }
    body = body_map.get(str(params.get('body', '')))
    breast = breast_map.get(str(params.get('breast', '')))
    waist = waist_map.get(str(params.get('waist', '')))
    hips = hips_map.get(str(params.get('hips', '')))
    # Build a natural English phrase: "a slim elegant figure with a very large
    # voluptuous bust, a very slim wasp waist and round appetizing hips".
    details = []
    if breast:
        details.append(breast)
    if waist:
        details.append(waist)
    if hips:
        details.append(hips)
    if not body and not details:
        return ''
    base = body or 'a feminine figure'
    if not details:
        return base
    if len(details) == 1:
        return f'{base} with {details[0]}'
    return f"{base} with {', '.join(details[:-1])} and {details[-1]}"


def custom_appearance_descriptors(params: dict) -> list[str]:
    """English appearance descriptors (style/age/face/body/hair/eyes + figure) for identity locks."""
    return [
        descriptor for key in ('style', 'age', 'face', 'body', 'breast', 'waist', 'hips', 'hair', 'eyes')
        if (descriptor := OPTION_DESCRIPTORS.get(str(params.get(key, ''))))
    ]


def custom_base_character(character_id: str) -> dict | None:
    """Minimal character dict for the chat system prompt (constructor personas).

    Without this, character_service.get_character() silently falls back to
    Anna's file and the chat model is told "Ты — Анна" for a custom girl.
    """
    if not is_custom_character(character_id):
        return None
    params, display_name = custom_character_params(character_id)
    if not params:
        return None
    descriptors = custom_appearance_descriptors(params)
    temper = OPTION_DESCRIPTORS.get(str(params.get('temperament', '')))
    profession = OPTION_DESCRIPTORS.get(str(params.get('profession', '')))
    core = []
    if temper:
        core.append(temper)
    if profession:
        core.append(f'по профессии — {profession}')
    if not core:
        core = ['яркая', 'игривая', 'с собственным характером']
    return {
        'id': character_id,
        'name': display_name or 'Моя героиня',
        'age': custom_age(params),
        'is_adult': True,
        'personality': {
            'core': core,
            'stable_tastes': [', '.join(descriptors)] if descriptors else [],
        },
    }
