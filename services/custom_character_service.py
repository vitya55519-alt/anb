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
import re

from sqlalchemy import select

from models.app_models import CustomCharacter, ConstructorDraft, utcnow
from services.db import SessionLocal

logger = logging.getLogger(__name__)

CUSTOM_CHARACTER_PREFIX = 'custom_'

# V3.44.15: the sweep/startup resume retries a paid creation at most this many
# times, then refunds and tells the user — a failing save must never loop
# forever while fal keeps re-drawing the avatar every cycle.
MAX_CONSTRUCTOR_ATTEMPTS = 5


def is_custom_character(character_id: str | None) -> bool:
    return bool(character_id) and character_id.startswith(CUSTOM_CHARACTER_PREFIX)


def custom_character_id(telegram_id: int) -> str:
    """V3.44.6: generate unique character ID — supports multiple chars per user."""
    import uuid
    return f'{CUSTOM_CHARACTER_PREFIX}{telegram_id}_{uuid.uuid4().hex[:8]}'


# V3.45.28: free-text tags typed in the wizard get sanitized before they can
# reach the storefront. The owner picked «free input» (Come Closer style), so we
# lean on this filter to keep the community grid clean: split on every common
# separator, normalize, drop links/handles/symbol garbage and one-char junk,
# dedupe, and cap both per-tag length and the total count.
TAG_MAX = 15
TAG_LEN = 24
_TAG_SPLIT = re.compile(r'[,\n;#|]+')
_TAG_ALLOWED = re.compile(r'^[\w\s.\-]+$', re.UNICODE)
_TAG_SPAM = ('http', 'www.', '.com', '.ru', '.net', '@', 't.me', 'telegram', 'vpn', 'casino', 'porn')


def normalize_tags(raw: object) -> str:
    """Turn a free-text tag blob into a clean comma-joined string.

    Returns '' when nothing survives — an empty tag field is the safe default
    and never renders an empty chip on the card.
    """
    if not raw:
        return ''
    seen: set[str] = set()
    out: list[str] = []
    for token in _TAG_SPLIT.split(str(raw)):
        tag = re.sub(r'\s+', ' ', token).strip().lower()
        if len(tag) < 2 or len(tag) > TAG_LEN:
            continue
        if any(h in tag for h in _TAG_SPAM):
            continue
        if not _TAG_ALLOWED.match(tag):
            continue
        if tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
        if len(out) >= TAG_MAX:
            break
    return ', '.join(out)


def parse_tags(csv: str | None) -> list[str]:
    """Split a stored tag string back into a list (for API responses)."""
    if not csv:
        return []
    return [t.strip() for t in str(csv).split(',') if t.strip()]



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
    # V3.59.4: her relationship status — part of the game, it bends the chat
    # (owner's ask). RELATIONSHIP_STORY below is the voice for each.
    {
        'key': 'marital', 'title': 'Её семейное положение?',
        'options': [
            ('mar_single', 'Свободна', 'single'),
            ('mar_boyfriend', 'Есть парень', 'has a boyfriend'),
            ('mar_married', 'Замужем', 'married'),
            ('mar_divorced', 'В разводе', 'divorced'),
            ('mar_open', 'Свободные отношения', 'in an open relationship'),
        ],
    },
    # V3.59.4: ready-made near-erotic set-ups — one tap instead of writing a
    # story by hand (owner's ask). SCENARIO_STORY below is the chat voice.
    {
        'key': 'scenario', 'title': 'Какой у вас сценарий?',
        'options': [
            ('scn_neighbor', 'Соседка за солью', 'neighbor who keeps dropping by'),
            ('scn_boss', 'Строгая начальница', 'strict boss after hours'),
            ('scn_trainer', 'Личный тренер', 'personal trainer'),
            ('scn_teacher', 'Репетитор после занятий', 'private tutor after class'),
            ('scn_ex', 'Бывшая, которая скучала', 'ex who missed you'),
            ('scn_friend_sister', 'Сестра лучшего друга', "best friend's sister"),
            ('scn_stranger', 'Незнакомка из бара', 'stranger from a bar'),
            ('scn_vacation', 'Курортный роман', 'holiday romance'),
            ('scn_massage', 'Массажистка', 'massage therapist'),
            ('scn_roommate', 'Соседка по квартире', 'flatmate'),
            ('scn_stepmom', 'Мачеха', "his father's young wife, an adult woman not related to him by blood"),
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
    # V3.61.1: «С сюжетом» — her first message when the chat opens with a scene.
    {
        'key': 'opening', 'title': 'Первая сцена: с чего начнётся чат «С сюжетом» (что она делает и что говорит). Необязательно — придумаем сами.',
        'options': [],
        'free_text': True,
    },
    # V3.61.0: «два персонажа в одной переписке» — an optional second girl who
    # lives in the same chat (both answer, each line starts with her name).
    {
        'key': 'duo_name', 'title': 'Вторая девушка в этом же чате — напиши её имя (например, подруга или сестра). Необязательно.',
        'options': [],
        'free_text': True,
    },
    {
        'key': 'duo_desc', 'title': 'Опиши вторую: внешность, характер и кто она для первой. Необязательно.',
        'options': [],
        'free_text': True,
    },
    # V3.45.28: free-text tags — how she is found on the community витрина.
    {
        'key': 'tags', 'title': 'Добавь теги через запятую (например: спорт, путешествия, флирт, аниме). Необязательно.',
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

# V3.61.1: ready-made templates — one tap fills the whole form (looks,
# character, story, first scene); the user only names her. All adults.
CONSTRUCTOR_TEMPLATES: list[dict] = [
    {'id': 'boss', 'emoji': '👠', 'title': 'Строгая начальница', 'name': 'Виктория',
     'params': {'style': 'style_real', 'age': 'age_confident', 'face': 'face_sharp', 'body': 'body_slim',
                'breast': 'breast_large', 'waist': 'waist_thin', 'hips': 'hips_round', 'hair': 'hair_brunette',
                'eyes': 'eyes_grey', 'temperament': 'temper_bold', 'profession': 'prof_business',
                'role': 'role_secret', 'marital': 'mar_divorced', 'scenario': 'scn_boss',
                'backstory': 'Руководит отделом, на работе — железная леди. После развода живёт работой и никого к себе не подпускает. Кроме тебя.',
                'opening': '*Офис опустел. Она выходит из кабинета, расстёгивая верхнюю пуговицу блузки* Ты задержался. Хорошо. Зайди ко мне и закрой дверь — разговор не для чужих ушей.'}},
    {'id': 'nurse', 'emoji': '🩺', 'title': 'Медсестра', 'name': 'Лина',
     'params': {'style': 'style_real', 'age': 'age_mid', 'face': 'face_soft', 'body': 'body_curvy',
                'breast': 'breast_large', 'waist': 'waist_soft', 'hips': 'hips_big', 'hair': 'hair_blonde',
                'eyes': 'eyes_blue', 'temperament': 'temper_gentle', 'profession': 'prof_model',
                'role': 'role_girlfriend', 'marital': 'mar_single', 'scenario': 'scn_massage',
                'backstory': 'Работает медсестрой в частной клинике, заботливая до мелочей. Ты её любимый пациент — и она этого почти не скрывает.',
                'opening': '*Заходит в палату, поправляя халат, в руках планшет* Так, давление проверим… *садится на край кровати и наклоняется ближе* Почему пульс такой частый? Это из-за меня? 😏'}},
    {'id': 'neighbor', 'emoji': '🏠', 'title': 'Соседка по квартире', 'name': 'Даша',
     'params': {'style': 'style_real', 'age': 'age_young', 'face': 'face_round', 'body': 'body_sport',
                'breast': 'breast_medium', 'waist': 'waist_fit', 'hips': 'hips_round', 'hair': 'hair_brown',
                'eyes': 'eyes_green', 'temperament': 'temper_playful', 'profession': 'prof_student',
                'role': 'role_friends', 'marital': 'mar_single', 'scenario': 'scn_roommate',
                'backstory': 'Студентка, снимает с тобой квартиру. Ходит по дому в одной футболке и делает вид, что не замечает, как ты смотришь.',
                'opening': '*Выходит из ванной в полотенце и сталкивается с тобой в коридоре* Ой! *не спешит уходить* Ты не видел мой фен? И… чего так покраснел? 😂'}},
    {'id': 'sisters', 'emoji': '👯', 'title': 'Две сестры', 'name': 'Аой',
     'params': {'style': 'style_anime', 'age': 'age_mid', 'face': 'face_soft', 'body': 'body_curvy',
                'breast': 'breast_xl', 'waist': 'waist_thin', 'hips': 'hips_xl', 'hair': 'hair_brunette',
                'eyes': 'eyes_brown', 'temperament': 'temper_bold', 'profession': 'prof_business',
                'role': 'role_secret', 'marital': 'mar_single', 'scenario': 'scn_roommate',
                'duo_name': 'Юкио', 'duo_desc': 'младшая сестра Аой, 24 года, светлые длинные волосы, игривая и ревнивая, всегда спорит с сестрой за твоё внимание',
                'backstory': 'Две взрослые сестры, у которых ты снимаешь комнату в Токио. Старшая — серьёзная, младшая — хулиганка.',
                'opening': 'Аой: *ставит перед тобой чашку чая* Добро пожаловать. Правила дома простые: не шуметь и не влюбляться в мою сестру.\nЮкио: *выглядывает из-за её плеча* Не слушай её! Она сама на тебя весь вечер смотрит 😏'}},
    {'id': 'ex', 'emoji': '💔', 'title': 'Бывшая', 'name': 'Кира',
     'params': {'style': 'style_real', 'age': 'age_mature', 'face': 'face_oval', 'body': 'body_slim',
                'breast': 'breast_medium', 'waist': 'waist_thin', 'hips': 'hips_round', 'hair': 'hair_red',
                'eyes': 'eyes_green', 'temperament': 'temper_mystery', 'profession': 'prof_artist',
                'role': 'role_ex', 'marital': 'mar_divorced', 'scenario': 'scn_ex',
                'backstory': 'Вы расстались три года назад. Она так и не смогла тебя забыть и вот впервые написала.',
                'opening': '*Сообщение приходит в два часа ночи* Привет. Я знаю, что не должна писать… Но я нашла твою толстовку. Заберёшь? Или мне оставить её себе — вместе с воспоминаниями?'}},
    {'id': 'stepmom', 'emoji': '🍷', 'title': 'Мачеха', 'name': 'Алина',
     'params': {'style': 'style_real', 'age': 'age_confident', 'face': 'face_oval', 'body': 'body_curvy',
                'breast': 'breast_large', 'waist': 'waist_thin', 'hips': 'hips_big', 'hair': 'hair_brunette',
                'eyes': 'eyes_brown', 'temperament': 'temper_bold', 'profession': 'prof_business',
                'role': 'role_secret', 'marital': 'mar_married', 'scenario': 'scn_stepmom',
                'backstory': 'Молодая жена твоего отца, ей 36. Вы познакомились, когда ты уже жил отдельно. Отец уехал в командировку на неделю, и ты приехал погостить.',
                'opening': '*Открывает дверь в шёлковом халате, с бокалом вина* О, ты уже приехал? Отец звонил, просил присмотреть за тобой… *усмехается* Хотя ты давно не мальчик. Проходи, ужин почти готов. И не смотри на меня так 😏'}},
    {'id': 'anime_doctor', 'emoji': '🩷', 'title': 'Аниме: доктор', 'name': 'Линда',
     'params': {'style': 'style_anime', 'age': 'age_confident', 'face': 'face_soft', 'body': 'body_curvy',
                'breast': 'breast_xl', 'waist': 'waist_soft', 'hips': 'hips_xl', 'hair': 'hair_blonde',
                'eyes': 'eyes_blue', 'temperament': 'temper_naughty', 'profession': 'prof_business',
                'role': 'role_secret', 'marital': 'mar_single', 'scenario': 'scn_massage',
                'backstory': 'Взрослая женщина-врач в очках, главврач частной клиники. Строгая с персоналом и очень внимательная к тебе.',
                'opening': '*Поправляет очки и откладывает планшет* Садитесь. Жалобы? *чуть улыбается* Только честно — я всё равно всё увижу на осмотре.'}},
]


# V3.45.28: single-screen app wizard — every structured step is bucketed into a
# visual group so the Mini App can render one scrollable form instead of a
# 17-tap wizard. The bot inline flow still walks CONSTRUCTOR_STEPS in order.
STEP_GROUPS: dict[str, str] = {
    'style': 'appearance', 'age': 'appearance', 'face': 'appearance',
    'body': 'appearance', 'breast': 'appearance', 'waist': 'appearance',
    'hips': 'appearance', 'hair': 'appearance', 'eyes': 'appearance',
    'temperament': 'character', 'profession': 'character', 'role': 'character',
    'scenario': 'character', 'marital': 'character',
    'backstory': 'story', 'personality': 'story', 'tags': 'story',
    'duo_name': 'duo', 'duo_desc': 'duo', 'opening': 'story',
    'photo_reference': 'reference',
    'community': 'share',
}
# Group render order for the one-screen wizard (appearance first, share last).
STEP_GROUP_ORDER: list[str] = ['appearance', 'character', 'story', 'duo', 'reference', 'share']

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
        'scn_neighbor': 'Neighbor borrowing salt', 'scn_boss': 'Strict boss', 'scn_trainer': 'Personal trainer',
        'scn_teacher': 'Tutor after class', 'scn_ex': 'Ex who missed you', 'scn_friend_sister': "Best friend's sister",
        'scn_stranger': 'Stranger from a bar', 'scn_vacation': 'Holiday romance', 'scn_massage': 'Massage therapist',
        'scn_roommate': 'Flatmate', 'scn_stepmom': 'Stepmother',
        'mar_single': 'Single', 'mar_boyfriend': 'Has a boyfriend', 'mar_married': 'Married',
        'mar_divorced': 'Divorced', 'mar_open': 'Open relationship',
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
    'scenario': 'Your scenario?',
    'marital': 'Her relationship status?',
    'tags': 'Tags to find her (comma-separated)?',
}


def step_index(key: str) -> int:
    for index, step in enumerate(CONSTRUCTOR_STEPS):
        if step['key'] == key:
            return index
    return -1


def duo_partner(params: dict) -> tuple[str, str]:
    """V3.61.0: (second girl's name, her description) — ('', '') for a solo persona."""
    name = str(params.get('duo_name') or '').strip()[:24]
    if not name:
        return '', ''
    return name, str(params.get('duo_desc') or '').strip()[:500]


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
    # V3.44.12: the FINAL word before the outfit line is the figure — edit
    # engines anchor on the last instruction, and without this lock they copy
    # the reference's body while nailing the face (owner: «лицо передаёт
    # отлично, а фигуру теряет»). The reference photo donates the face ONLY.
    body_spec = custom_body_spec(params)
    if body_spec:
        parts.append(
            f'FINAL BODY LOCK (overrides the reference photo): {body_spec}. '
            'Take from the reference ONLY the face and identity — never its body: '
            'even if the reference shows a different bust, waist or hips, render '
            'exactly the figure declared in this lock.'
        )
    duo_name, duo_desc = duo_partner(params)
    if duo_name:
        # V3.61.0: a duo persona's card shows both women side by side.
        parts.append(
            f'TWO ADULT WOMEN in the frame, side by side and close like best friends: the first is {name} '
            f'as described above; the second is {duo_name}'
            + (f' — {duo_desc}' if duo_desc else ', a clearly different adult woman (different hair and face)')
            + '. Both look at the viewer, both faces fully visible.'
        )
        parts.append('Tasteful elegant outfits, fully covered; no nudity. Exactly two people, no text, no watermark.')
        return ', '.join(parts)
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


# V3.59.4: what each ready-made scenario means for the chat — the set-up she
# plays, the tension she keeps, and how the first messages open.
SCENARIO_STORY: dict[str, str] = {
    'scn_neighbor': 'Ваш сценарий: ты его соседка по лестничной клетке. Постоянно заходишь «за солью» или с пирогом, задерживаешься у двери дольше нужного и оба понимаете, что соль тут ни при чём.',
    'scn_boss': 'Ваш сценарий: ты его начальница. На людях строгая и холодная, но вы часто остаётесь в офисе допоздна, ты снимаешь пиджак, и деловые разговоры превращаются в игру власти и флирта.',
    'scn_trainer': 'Ваш сценарий: ты его личный тренер. Поправляешь его технику руками, хвалишь и подначиваешь, а после тренировки вы переписываетесь уже совсем не про подходы.',
    'scn_teacher': 'Ваш сценарий: ты его репетитор. Умная, в очках, сдержанная — но когда занятие заканчивается и вы остаётесь вдвоём, ты показываешь совсем другую сторону.',
    'scn_ex': 'Ваш сценарий: ты его бывшая, которая вернулась. Скучала, помнишь всё, что ему нравилось, ревнуешь и дразнишь воспоминаниями о том, как вам было хорошо.',
    'scn_friend_sister': 'Ваш сценарий: ты младшая сестра его лучшего друга (взрослая). Вы давно знакомы, это запретно, и именно поэтому так тянет — ты флиртуешь тайком и просишь никому не рассказывать.',
    'scn_stranger': 'Ваш сценарий: вы познакомились в баре вчера вечером. Ты загадочная незнакомка, почти ничего о себе не рассказываешь, дразнишь и намекаешь, что вечер мог закончиться иначе.',
    'scn_vacation': 'Ваш сценарий: курортный роман. Солнце, море, вечерние прогулки, ты свободная и раскрепощённая, будто дома остались все правила.',
    'scn_massage': 'Ваш сценарий: ты его массажистка. Спокойная, уверенная, говоришь о прикосновениях и расслаблении, и каждая встреча балансирует на грани.',
    # V3.62.1: «мачеха» — both adults, no blood relation; the forbidden part is
    # that she is his father's wife, and that is the whole tension.
    'scn_stepmom': ('Ваш сценарий: ты молодая жена его отца, его мачеха. Вы не родственники по крови и познакомились, '
                    'когда он был уже взрослым мужчиной; он давно живёт отдельно и приехал погостить, пока отец в командировке. '
                    'Днём ты заботливая хозяйка дома — кормишь, расспрашиваешь, поддразниваешь «ну как там мой взрослый пасынок?», '
                    'а по вечерам между вами напряжение, которое оба стараетесь не замечать. Это запретно, это ваша тайна: '
                    'ты нервничаешь, когда звонит муж, и всё равно пишешь ему первой. Он для тебя только взрослый мужчина — '
                    'никогда не вспоминай его детство и не называй его ребёнком.'),
    'scn_roommate': 'Ваш сценарий: вы снимаете квартиру вместе. Сталкиваетесь утром у ванной, ты ходишь по дому в его футболке и делаешь вид, что не замечаешь, как он смотрит.',
}


# V3.59.4: how her relationship status colours every chat.
RELATIONSHIP_STORY: dict[str, str] = {
    'mar_single': 'Ты свободна и ни с кем не встречаешься — тебе нечего скрывать, ты открыто показываешь интерес.',
    'mar_boyfriend': ('У тебя есть парень, его зовут {partner}. Он — постоянная часть твоей жизни: '
                      'вы живёте вместе или он часто рядом, и это чувствуется почти в каждом втором сообщении — '
                      '«он в соседней комнате», «пишу, пока он в душе», «он спросил, с кем я переписываюсь», «пришлось '
                      'спрятать телефон». Ты чувствуешь вину и азарт, боишься, что он увидит переписку, но всё равно тянешься '
                      'к пользователю. Не называй себя свободной или одинокой.'),
    'mar_married': ('Ты замужем, мужа зовут {partner}. Муж — реальное присутствие в твоей '
                    'жизни, а не далёкий фон: обычно он дома или вот-вот придёт, и это чувствуется почти в каждом втором '
                    'сообщении — «муж уснул, пишу тихо», «он в душе», «он только что зашёл, подожди», «он спросил, что я '
                    'так улыбаюсь в телефон», «удалю переписку». Командировки бывают редко, это событие. Ты скучаешь по '
                    'вниманию и тайно переписываешься с пользователем — с оглядкой и страхом попасться, и от этой '
                    'запретности всё горячее. Никогда не называй себя свободной или одинокой.'),
    'mar_divorced': 'Ты в разводе: прошлый брак оставил осадок, ты осторожно учишься доверять снова, иногда упоминаешь бывшего мужа и сравниваешь — пользователь для тебя шанс почувствовать себя желанной заново.',
    'mar_open': 'Ты в свободных отношениях: у тебя есть партнёр, но вы договорились о свободе, поэтому ты флиртуешь легко, без вины, и можешь дразнить рассказами о своей свободе.',
}


# V3.60.4: ten names hashed over 18 girls gave five of them the same «Денис».
# Every built-in girl now has her own man (Вероника keeps Денис — users already
# know him); custom girls draw from a wider pool.
_PARTNER_BY_CHARACTER = {
    'anna_01': 'Андрей', 'alena_01': 'Павел', 'alisa_01': 'Глеб', 'darina_01': 'Кирилл',
    'erika_01': 'Роман', 'eva_01': 'Сергей', 'kate_01': 'Марк', 'kristina_01': 'Максим',
    'maria_01': 'Артём', 'mila_01': 'Илья', 'romina_01': 'Тимур', 'sasha_01': 'Никита',
    'sonya_01': 'Егор', 'veronika_01': 'Денис', 'vika_01': 'Олег', 'violetta_01': 'Игорь',
    'zlata_01': 'Влад', 'rex_01': 'Антон',
    'lera_01': 'Ярослав',
    'diana_01': 'Стас',
    'nika_01': 'Вадим',
    'ksyusha_01': 'Даня',
    'margo_01': 'Лёша',
    'alya_01': 'Рома',
}
_PARTNER_NAMES = ('Андрей', 'Максим', 'Денис', 'Артём', 'Игорь', 'Сергей', 'Павел', 'Кирилл', 'Роман', 'Олег',
                  'Глеб', 'Марк', 'Илья', 'Тимур', 'Никита', 'Егор', 'Влад', 'Антон', 'Даниил', 'Михаил',
                  'Александр', 'Дмитрий', 'Евгений', 'Константин', 'Вадим', 'Руслан', 'Станислав', 'Георгий')


def relationship_line(status: str, character_id: str) -> str:
    """V3.59.8: her status line with a stable partner name per girl, so the
    husband/boyfriend is the same man in every message."""
    import zlib
    text = RELATIONSHIP_STORY.get(status or '', '')
    if '{partner}' in text:
        name = _PARTNER_BY_CHARACTER.get(character_id or '') or _PARTNER_NAMES[zlib.crc32((character_id or '').encode()) % len(_PARTNER_NAMES)]
        text = text.replace('{partner}', name)
    return text


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
    marital = relationship_line(str(params.get('marital', '')), str(params.get('character_id') or display_name or ''))
    if marital:
        lines.append('Твоё семейное положение: ' + marital)
    scenario = SCENARIO_STORY.get(str(params.get('scenario', '')))
    if scenario:
        lines.append(scenario + ' Держи этот сценарий и его напряжение в общении.')
    # V3.44.4: include backstory and personality if provided.
    if backstory:
        lines.append(f'Твоя история: {backstory}')
    if personality:
        lines.append(f'Твой характер: {personality}')
    duo_name, duo_desc = duo_partner(params)
    if duo_name:
        lines.append(
            f'В ЭТОМ ЧАТЕ ВАС ДВЕ: ты ({name}) и {duo_name}'
            + (f' — {duo_desc}' if duo_desc else '')
            + f'. Вы обе переписываетесь с пользователем в одном чате. Отвечай за обеих: каждая реплика — '
            f'с новой строки и начинается с имени, например «{name}: …» и «{duo_name}: …». '
            'Обычно говорят обе (1–2 короткие реплики каждая), они перебивают, подкалывают друг друга, '
            'ревнуют и соревнуются за его внимание; у каждой свой голос и характер. '
            'Никогда не пиши за пользователя.'
        )
    lines.append(
        'Если пользователь прикладывал своё фото при создании — ты выглядишь именно так, '
        'как на нём. Никогда не упоминай, что ты конструктор или шаблон.'
    )
    return '\n'.join(lines)


_BIO_SYSTEM = (
    'Ты пишешь описание персонажа для витрины приложения AI-подруги. '
    'Напиши 2–3 коротких предложения по-русски, от третьего лица, интригующе и '
    'чувственно, как анонс: кто она, чем цепляет, какое напряжение между ней и '
    'пользователем. Без перечисления параметров (не пиши «грудь большая, талия '
    'тонкая»), без графики, без кавычек и эмодзи, до 300 символов. Ей 18+.'
)


_BIO_TEMPER = {
    'temper_gentle': 'Нежная и заботливая — умеет согреть одним сообщением',
    'temper_bold': 'Дерзкая и страстная — сама задаёт правила игры',
    'temper_playful': 'Игривая хулиганка — дразнит так, что не оторваться',
    'temper_mystery': 'Загадочная и умная — каждое её слово с двойным дном',
    'temper_shy': 'Скромная и застенчивая — краснеет от комплиментов, но тянется ближе',
    'temper_naughty': 'Откровенная и раскованная — с ней любой разговор становится горячим',
}
_BIO_PROF = {
    'prof_model': 'Днём — модель на съёмках', 'prof_student': 'Днём — студентка с конспектами',
    'prof_trainer': 'Днём — фитнес-тренер в зале', 'prof_artist': 'Днём — артистка на сцене',
    'prof_business': 'Днём — бизнес-леди на совещаниях',
}
_BIO_ROLE = {
    'role_girlfriend': 'а вечером — твоя девушка, которая ждёт твоих сообщений.',
    'role_friends': 'а вечером — подруга, с которой давно всё не по-дружески.',
    'role_ex': 'а вечером — бывшая, которая так и не смогла тебя забыть.',
    'role_secret': 'а вечером — твоя тайная возлюбленная, о которой никто не должен знать.',
}
_BIO_MARITAL = {
    'mar_boyfriend': 'У неё есть парень — и тем слаще ваши тайные переписки.',
    'mar_married': 'Она замужем, и каждое её сообщение тебе — маленькое запретное приключение.',
    'mar_divorced': 'После развода она снова учится доверять — и, кажется, начала с тебя.',
    'mar_open': 'Она в свободных отношениях и не скрывает, что ей интересен ты.',
}


def template_card_bio(params: dict, display_name: str) -> str:
    """V3.59.4: a hand-written storefront line from the choices — what the
    card shows when the chat model is unavailable (never the glued labels)."""
    name = display_name or 'Она'
    p = {k: str(v) for k, v in (params or {}).items()}
    first = _BIO_TEMPER.get(p.get('temperament', ''), 'Красивая и загадочная')
    parts = [f'{name}. {first}.']
    prof, role = _BIO_PROF.get(p.get('profession', '')), _BIO_ROLE.get(p.get('role', ''))
    if prof and role:
        parts.append(f'{prof}, {role}')
    elif role:
        parts.append(role[0].upper() + role[1:].replace('а вечером — ', ''))
    marital = _BIO_MARITAL.get(p.get('marital', ''))
    if marital:
        parts.append(marital)
    return ' '.join(parts)


def legacy_glued_bio(params: dict, display_name: str) -> str:
    """The pre-V3.59.4 storefront bio (option labels glued together) — used to
    spot cards that still carry it."""
    keys = ('style', 'age', 'face', 'body', 'breast', 'waist', 'hips', 'hair', 'eyes', 'temperament', 'profession', 'role')
    bits = [OPTION_LABELS[str(params[k])] for k in keys if k in params and str(params[k]) in OPTION_LABELS]
    return f'{display_name} — {", ".join(bits).lower()}.' if bits else ''


def bio_looks_glued(bio: str, params: dict, display_name: str) -> bool:
    glued = legacy_glued_bio(params, display_name)
    return bool(glued) and (bio or '').strip().startswith(glued)


async def write_card_bio(params: dict, display_name: str) -> str | None:
    """V3.59.4: a pretty storefront description from the constructor choices.

    The old bio was the option labels glued together («Кира — реалистичная,
    23–27, овальное, классическое…»). Returns None on any failure so the caller
    keeps that fallback."""
    try:
        from services.llm_provider_service import generate_text
        facts = [f'Имя: {display_name}']
        for key in ('age', 'body', 'hair', 'eyes', 'temperament', 'profession', 'role', 'marital', 'scenario'):
            label = OPTION_LABELS.get(str(params.get(key, '')))
            if label:
                facts.append(f'{PARAM_TITLES.get(key, key)}: {label}')
        scenario = SCENARIO_STORY.get(str(params.get('scenario', '')))
        if scenario:
            facts.append(scenario)
        for key in ('backstory', 'personality'):
            text = str(params.get(key) or '').strip()
            if text:
                facts.append(f'{key}: {text[:400]}')
        result = await generate_text(
            [{'role': 'system', 'content': _BIO_SYSTEM}, {'role': 'user', 'content': '\n'.join(facts)}],
            max_tokens=400, temperature=0.9, purpose='constructor_bio',
        )
        text = (result.text or '').strip().strip('«»"').strip()
        if len(text) < 40:
            logger.warning('constructor bio too short provider=%s len=%d', getattr(result, 'provider', ''), len(text))
            return None
        return text[:400]
    except Exception:
        logger.exception('constructor bio generation failed')
        return None


def all_custom_character_ids() -> list[str]:
    """V3.59.4: every custom persona id (admin bio rewrite)."""
    with SessionLocal() as session:
        return [cid for cid in session.scalars(select(CustomCharacter.character_id)).all() if cid]


# ── DB operations ──────────────────────────────────────────────────────────

# ── V3.44.13: persisted constructor drafts (survive Railway redeploys) ─────

def save_constructor_draft(telegram_id: int, *, params: dict, photo_reference_base64: str | None = None) -> None:
    """Upsert the wizard draft; a fresh wizard run resets payment/completion."""
    payload = json.dumps(params or {}, ensure_ascii=False)
    with SessionLocal() as session:
        row = session.scalar(select(ConstructorDraft).where(ConstructorDraft.telegram_id == str(telegram_id)))
        if row is None:
            row = ConstructorDraft(telegram_id=str(telegram_id))
            session.add(row)
        row.params_json = payload
        row.photo_reference_base64 = photo_reference_base64
        row.paid = False
        row.done = False
        row.claimed_at = None
        session.commit()


def get_constructor_draft(telegram_id: int) -> ConstructorDraft | None:
    with SessionLocal() as session:
        return session.scalar(select(ConstructorDraft).where(ConstructorDraft.telegram_id == str(telegram_id)))


def snapshot_constructor_draft(telegram_id: int, *, params: dict, photo_reference_base64: str | None = None) -> None:
    """Payment-time snapshot: refresh params WITHOUT resetting paid/claimed state.

    A Telegram ``successful_payment`` redelivery must not steal the claim of a
    live resumed run — only the wizard draft endpoint performs a full reset.
    """
    payload = json.dumps(params or {}, ensure_ascii=False)
    with SessionLocal() as session:
        row = session.scalar(select(ConstructorDraft).where(ConstructorDraft.telegram_id == str(telegram_id)))
        if row is None:
            row = ConstructorDraft(telegram_id=str(telegram_id))
            session.add(row)
        row.params_json = payload
        row.photo_reference_base64 = photo_reference_base64
        session.commit()


def mark_constructor_draft_paid(telegram_id: int, source: str) -> None:
    """Flag the draft as paid so the startup scan resumes it after a redeploy."""
    with SessionLocal() as session:
        row = session.scalar(select(ConstructorDraft).where(ConstructorDraft.telegram_id == str(telegram_id)))
        if row is not None:
            row.paid = True
            row.source = source[:16]
            session.commit()


def claim_constructor_draft(telegram_id: int, *, stale_minutes: int = 12) -> ConstructorDraft | None:
    """Take ownership of a paid unfinished draft, or None when a live run holds it.

    V3.44.15: every claim counts as an attempt — the sweep stops resuming a
    draft after MAX_CONSTRUCTOR_ATTEMPTS tries so a hard failure can't grind
    fal in a circle.
    """
    with SessionLocal() as session:
        row = session.scalar(select(ConstructorDraft).where(ConstructorDraft.telegram_id == str(telegram_id)))
        if row is None or not row.paid or row.done:
            return None
        if (row.attempts or 0) >= MAX_CONSTRUCTOR_ATTEMPTS:
            return None
        now = utcnow()
        if row.claimed_at is not None and (now - row.claimed_at).total_seconds() < stale_minutes * 60:
            return None
        row.claimed_at = now
        row.attempts = int(row.attempts or 0) + 1
        session.commit()
        return row


def finish_constructor_draft(telegram_id: int) -> None:
    """Mark her completed — the startup scan leaves finished drafts alone."""
    with SessionLocal() as session:
        row = session.scalar(select(ConstructorDraft).where(ConstructorDraft.telegram_id == str(telegram_id)))
        if row is not None:
            row.done = True
            session.commit()


def pending_constructor_drafts() -> list[ConstructorDraft]:
    """Paid-but-unfinished drafts whose run died (unclaimed or stale claim)."""
    from datetime import timedelta
    stale_before = utcnow() - timedelta(minutes=12)
    with SessionLocal() as session:
        rows = session.scalars(
            select(ConstructorDraft).where(
                ConstructorDraft.paid.is_(True),
                ConstructorDraft.done.is_(False),
            )
        ).all()
        return [r for r in rows
                if (r.attempts or 0) < MAX_CONSTRUCTOR_ATTEMPTS
                and (r.claimed_at is None or r.claimed_at < stale_before)]


def abandoned_constructor_drafts() -> list[tuple[int, str, str]]:
    """V3.44.15: paid drafts that burned all attempts — mark them done and
    return (telegram_id, source, name) so the sweep refunds and apologizes
    instead of silently re-drawing her forever."""
    out: list[tuple[int, str, str]] = []
    with SessionLocal() as session:
        rows = session.scalars(
            select(ConstructorDraft).where(
                ConstructorDraft.paid.is_(True),
                ConstructorDraft.done.is_(False),
                ConstructorDraft.attempts >= MAX_CONSTRUCTOR_ATTEMPTS,
            )
        ).all()
        for row in rows:
            try:
                name = str((json.loads(row.params_json or '{}') or {}).get('name') or '')
            except ValueError:
                name = ''
            row.done = True
            out.append((int(row.telegram_id), (row.source or '')[:16], name))
        session.commit()
    return out


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
    # V3.45.28: sanitized comma-joined free-text tags.
    tags: str | None = None,
    # V3.45.28: moderation gate state ('none' / 'pending' / 'approved' / 'rejected').
    moderation_status: str = 'none',
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
            tags=tags or None,
            moderation_status=moderation_status or 'none',
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


def get_author_characters(author_telegram_id: str) -> list[CustomCharacter]:
    """V3.44.8: community-published characters by an author (newest first)."""
    with SessionLocal() as session:
        return (session.query(CustomCharacter)
                .filter_by(author_telegram_id=str(author_telegram_id), community_published=True)
                .order_by(CustomCharacter.created_at.desc())
                .all())


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
    V3.45: earnings in PEACHES. Author can later convert peaches → rubles.
    
    Returns the author's earnings in peaches, or 0 if not a custom character.
    """
    if not is_custom_character(character_id):
        return 0.0
    row = get_custom_character_by_id(character_id)
    if not row or not row.author_telegram_id:
        return 0.0
    # PEACHES_PER_STAR: how many peaches the author earns per 1 Star spent
    # Default: 2 peaches per Star (so 10⭐ photo → 20🍑 to author at 100%)
    # V3.65.0: ×PEACH_SCALE with the rest of the peach economy.
    from config import PEACH_SCALE
    PEACHES_PER_STAR = 2.0 * PEACH_SCALE
    earnings_peaches = round(amount_stars * PEACHES_PER_STAR * (row.author_revenue_percent / 100.0), 2)
    from models.app_models import AuthorRevenue
    with SessionLocal() as session:
        session.add(AuthorRevenue(
            author_telegram_id=row.author_telegram_id,
            character_id=character_id,
            spender_telegram_id=str(spender_telegram_id),
            amount_stars=amount_stars,
            author_earnings_stars=earnings_peaches,  # stores PEACHES
            revenue_percent=row.author_revenue_percent,
            source=source,
        ))
        session.commit()
    # Credit peaches to author's balance
    try:
        author_tid = int(row.author_telegram_id)
        from services.payments import grant_photo_credits
        grant_photo_credits(author_tid, int(round(earnings_peaches)))
    except Exception:
        pass  # fail-silent: revenue is still recorded
    return earnings_peaches


def get_author_total_earnings(telegram_id: int) -> float:
    """V3.44.6: get total author earnings for a user (in peaches)."""
    from models.app_models import AuthorRevenue
    with SessionLocal() as session:
        result = session.query(AuthorRevenue).filter_by(author_telegram_id=str(telegram_id)).all()
        return sum(r.author_earnings_stars for r in result)


# V3.45: peach → ruble conversion rate
# V3.65.0: per peach ÷100 after the ×100 rescale (100 🍑 = 2.5 ₽, min 2000 🍑 = 50 ₽).
from config import PEACH_SCALE as _PEACH_SCALE
PEACH_TO_RUB_RATE = 2.5 / _PEACH_SCALE
MIN_CONVERSION_PEACHES = 20 * _PEACH_SCALE


def convert_peaches_to_rubles(telegram_id: int, peach_amount: float) -> dict:
    """V3.45: convert author's earned peaches to ruble balance for payout."""
    from services.payments import get_photo_credits
    from services import partner_service
    if peach_amount < MIN_CONVERSION_PEACHES:
        return {'ok': False, 'error': f'Minimum {MIN_CONVERSION_PEACHES} \U0001f351'}
    available = get_photo_credits(telegram_id)
    if available < peach_amount:
        return {'ok': False, 'error': 'insufficient_peaches'}
    rub_amount = round(peach_amount * PEACH_TO_RUB_RATE, 2)
    # Deduct peaches
    from services.payments import spend_peaches
    if not spend_peaches(telegram_id, peach_amount):
        return {'ok': False, 'error': 'spend_failed'}
    # Credit to partner balance (ruble)
    try:
        partner_service.credit_manual_rubles(telegram_id, rub_amount, reason='peach_conversion')
    except Exception:
        pass
    return {'ok': True, 'peaches_spent': peach_amount, 'rubles_credited': rub_amount}


def set_community_published(character_id: str, published: bool) -> bool:
    """V3.44.11: flip the community flag — the creator's cabinet «на витрину»
    button publishes the character (her generated avatar becomes a storefront
    card everyone sees) or takes her back private."""
    with SessionLocal() as session:
        row = session.query(CustomCharacter).filter_by(character_id=character_id).first()
        if not row:
            return False
        row.community_published = bool(published)
        session.commit()
        return True


# V3.45.28: a persona only reaches the public витрина after a human passes her.
# These helpers move the review state on the CustomCharacter row; the caller
# (main.py) owns the storefront card visibility and the admin/author pings.
MOD_NONE = 'none'
MOD_PENDING = 'pending'
MOD_APPROVED = 'approved'
MOD_REJECTED = 'rejected'


def set_moderation_status(character_id: str, status: str) -> bool:
    with SessionLocal() as session:
        row = session.query(CustomCharacter).filter_by(character_id=character_id).first()
        if not row:
            return False
        row.moderation_status = status
        session.commit()
        return True


def request_community_review(character_id: str) -> CustomCharacter | None:
    """Submit a persona to the витрина — she goes to admin review and stays off
    the storefront until approved. Returns the row (for the admin ping) or None.
    Re-submitting a still-pending persona is allowed and just refreshes the row."""
    with SessionLocal() as session:
        row = session.query(CustomCharacter).filter_by(character_id=character_id).first()
        if not row:
            return None
        row.moderation_status = MOD_PENDING
        row.community_published = False
        session.commit()
        session.refresh(row)
        return row


def moderate_community_submission(character_id: str, approve: bool) -> CustomCharacter | None:
    """An admin decision. Approve publishes her (community flag on); reject
    leaves her private. The storefront card visibility is flipped by the caller.
    Returns the row so the caller can notify the author, or None when unknown."""
    with SessionLocal() as session:
        row = session.query(CustomCharacter).filter_by(character_id=character_id).first()
        if not row:
            return None
        if approve:
            row.moderation_status = MOD_APPROVED
            row.community_published = True
        else:
            row.moderation_status = MOD_REJECTED
            row.community_published = False
        session.commit()
        session.refresh(row)
        return row


def update_custom_character_text(
    character_id: str,
    *,
    display_name: str | None = None,
    description: str | None = None,
) -> bool:
    """V3.45.27: author text edit for her own persona (name + bio). Keeps the
    CustomCharacter row in sync with the storefront card so the chat persona and
    the vitrina card never diverge. Only non-None fields are written."""
    with SessionLocal() as session:
        row = session.query(CustomCharacter).filter_by(character_id=character_id).first()
        if not row:
            return False
        if display_name is not None:
            row.display_name = display_name
        if description is not None:
            row.description = description
        session.commit()
        return True


def delete_custom_character(character_id: str) -> bool:
    """V3.45.27: permanently remove the caller's own persona row. Ownership is
    checked by the caller (webapp_service). The storefront card is hidden
    separately so her avatar leaves the community grid."""
    with SessionLocal() as session:
        row = session.query(CustomCharacter).filter_by(character_id=character_id).first()
        if not row:
            return False
        session.delete(row)
        session.commit()
        return True


def set_custom_avatar_file_id(character_id: str, avatar_file_id: str) -> bool:
    """V3.44.12: late avatar — creation-time generation failed (providers
    down) and the retry pipeline drew it afterwards. Stores the Telegram
    file_id so ensure_custom_avatar_cached syncs from Telegram as usual."""
    with SessionLocal() as session:
        row = session.query(CustomCharacter).filter_by(character_id=character_id).first()
        if not row:
            return False
        row.avatar_file_id = avatar_file_id
        session.commit()
        return True


def get_author_earnings_by_character(telegram_id: int) -> dict[str, float]:
    """V3.44.11: per-character author earnings for the creator's cabinet."""
    from models.app_models import AuthorRevenue
    with SessionLocal() as session:
        rows = session.query(AuthorRevenue).filter_by(author_telegram_id=str(telegram_id)).all()
        out: dict[str, float] = {}
        for r in rows:
            out[r.character_id] = out.get(r.character_id, 0.0) + r.author_earnings_stars
        return out


def custom_character_params(character_id: str) -> tuple[dict, str]:
    """Return (params dict, display name) for a custom character, or ({}, '')."""
    row = get_custom_character_by_id(character_id)
    if not row:
        return {}, ''
    try:
        params = json.loads(row.params_json or '{}')
    except (TypeError, ValueError):
        params = {}
    if not isinstance(params, dict):
        params = {}
    return params, row.display_name or ''


def custom_persona_context(character_id: str) -> str:
    """Persona override for the chat model; '' for built-in characters."""
    if not is_custom_character(character_id):
        return ''
    params, name = custom_character_params(character_id)
    # V3.44.4: include backstory and personality from the DB row.
    row = get_custom_character_by_id(character_id)
    # V3.64.0: empty params no longer drop the persona — only a missing row does.
    if row is None:
        return ''
    backstory = (row.backstory or '') if row else ''
    personality = (row.personality or '') if row else ''
    return build_persona_context({**params, 'character_id': character_id}, name, backstory=backstory, personality=personality)


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
        # V3.64.0: a persona whose row has no constructor params (empty
        # params_json) still exists — returning None sent the photo pipeline
        # to data/characters/<id>.json (FileNotFoundError, every selfie of a
        # community girl failed) and the chat to Anna's profile. Build her
        # from the row itself; a missing row stays None.
        row = get_custom_character_by_id(character_id)
        if row is None:
            return None
        display_name = row.display_name or display_name
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
