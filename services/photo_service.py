from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import mimetypes
import random
import re
import time
from contextlib import ExitStack
from dataclasses import dataclass, replace
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Awaitable, Callable

import httpx
from aiogram import Bot
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from openai import AsyncOpenAI, BadRequestError
from sqlalchemy import select, func

from config import (
    CHARACTER_ID,
    IMAGE_API_KEY, IMAGE_BASE_URL, IMAGE_MODEL, IMAGE_SIZE, IMAGE_QUALITY, OPENAI_IMAGE_ESTIMATED_COST_USD,
    OPENAI_IMAGE_AVAILABLE,
    FREE_PHOTOS_LEVEL_1_2, FREE_PHOTOS_LEVEL_3_6, PHOTO_COST_STARS, PEACH_SCALE,
    FAL_KEY, FAL_MODEL, FAL_MODEL_T2I, FAL_IMAGE_SIZE, FAL_TIMEOUT_SECONDS,
    FAL_CONNECT_TIMEOUT_SECONDS, FAL_WRITE_TIMEOUT_SECONDS, FAL_POOL_TIMEOUT_SECONDS,
    FAL_RETRIES, FAL_RETRY_BACKOFF_SECONDS, FAL_ESTIMATED_COST_USD,
    PHOTO_ROUTER_MODE, PHOTO_SET_SIZE,
    SPICYAPI_KEY, SPICYAPI_IMAGE_MODEL, SPICYAPI_ESTIMATED_COST_USD, PHOTO_SPICY_FIRST,
    PUBLIC_BASE_URL,
    GEMINI_API_KEY, GEMINI_IMAGE_ENABLED, GEMINI_IMAGE_MODEL, GEMINI_IMAGE_TIMEOUT_SECONDS, GEMINI_IMAGE_ESTIMATED_COST_USD, GEMINI_IMAGE_ASPECT_RATIO, GEMINI_IMAGE_SIZE,
    GEMINI_VIDEO_BASE_URL,
    COMMUNITY_POOL_ENABLED, COMMUNITY_POOL_FIRST,
)
from models.app_models import ProductEvent, User
from models.relationship_models import UserCharacterRelationship
from models.photo_models import PhotoDailyUsage, PhotoDelivery, PhotoOffer
from services.db import SessionLocal
from services.photo_idea_service import enrich_request_with_idea
from services.provider_stats_service import record_provider
from services.character_service import get_anna
from services.character_registry import get_character
from services.custom_character_service import (
    is_custom_character, get_custom_character_by_id, custom_character_params,
    custom_appearance_descriptors, custom_base_character, custom_hair_color,
    custom_body_spec, build_avatar_prompt,
)
from services.test_mode import get_stage as get_test_stage
from services.access_service import is_premium
from services.user_service import ensure_user, get_state, update_state, is_adult_confirmed
from services.payments import consume_photo_credit, get_photo_credits
from services.adaptation_service import get_visual_preferences
from services.character_preferences import get_character_preferences
from services import spicy_confidence
from services.analytics_service import track_event
from services import spend_service
from services.heroine_label import stamp as _her
from services.photo_library_service import choose_unseen_pack, choose_fallback_pack, mark_pack_seen, mark_items_seen
from services.state_service import ensure_life_state

logger = logging.getLogger(__name__)


def _linked_video_markup(item):
    if not getattr(item, 'video_file_id', None):
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='🎬 Смотреть видео', callback_data=f'libvideo:{item.item_id}')
    ]])


def _photo_action_markup(delivery_id: int, item=None):
    """Buttons under every delivered photo: linked video (if any) + animate."""
    linked = _linked_video_markup(item) if item is not None else None
    rows = [list(row) for row in linked.inline_keyboard] if linked else []
    rows.append([InlineKeyboardButton(text='✨ Оживить это фото', callback_data=f'video:animate:{delivery_id}')])
    return InlineKeyboardMarkup(inline_keyboard=rows)
openai_client = AsyncOpenAI(api_key=IMAGE_API_KEY, base_url=IMAGE_BASE_URL) if OPENAI_IMAGE_AVAILABLE else None

# Startup diagnostic — visible in Railway logs immediately
logger.info(
    'PHOTO PROVIDERS: fal.ai/Seedream=%s (model=%s) | Gemini=%s (model=%s) | OpenAI=%s | mode=%s',
    'READY' if FAL_KEY else 'NO KEY',
    FAL_MODEL,
    'READY' if GEMINI_IMAGE_ENABLED else 'NO KEY/DISABLED',
    GEMINI_IMAGE_MODEL if GEMINI_IMAGE_ENABLED else '-',
    'READY' if OPENAI_IMAGE_AVAILABLE else 'NO KEY',
    PHOTO_ROUTER_MODE,
)

SCENES = {
    'selfie': 'a believable personal smartphone selfie made specifically to send to the person she is chatting with',
    'home': 'a spontaneous smartphone photo she takes at home on a lazy day: sitting on the sofa or the kitchen counter in cozy home clothes, soft throw pillows, a mug or a book nearby, real lived-in apartment details',
    'park': 'a smartphone photo during her walk in a green city park: tree-lined path, benches, sunlight through leaves, her camera propped on a park bench or set by a countdown timer',
    'cafe': 'a smartphone photo she takes sitting at a window table in a cozy modern cafe: a latte with foam art and a dessert on the table, warm wooden interior, soft daylight from the window',
    'street': 'a candid street-style smartphone photo while she walks through a lively city neighborhood: shop windows, crosswalk, city buildings, she glances into the camera mid-step',
    'shop': 'a shopping-day photo she takes in a boutique fitting-room mirror or between clothing racks, shopping bags in hand, trying on something new to show you',
    'car': 'a selfie she takes in the driver seat of her parked car: seatbelt off, sunglasses pushed up into her hair, soft daylight through the windshield, steering wheel and dashboard visible',
    'gym': 'a gym mirror selfie during a workout break: fitted sports top and leggings, water bottle, training equipment behind her, slight healthy glow on her skin',
    'mirror': 'a full-body mirror photo in her bedroom or hallway, the camera stood on a chair below the mirror edge and not visible in the reflection, showing her whole figure and outfit from head to toe',
    'outfit': 'a full-body photo showing what she is wearing today before going out — standing at the hallway mirror, shoes on, bag in hand',
    'restaurant': 'an evening photo she takes at a dinner table in a stylish restaurant: candlelight, wine glass, elegant plates, warm low light, she is dressed up for dinner',
    'cinema': 'a casual photo in a modern cinema lobby before the movie: popcorn and a drink in her hands, movie posters and neon signage behind her',
    'embankment': 'a walk along a city river embankment at sunset: water and bridges behind her, the railing beside her, wind playing with her hair, warm golden light',
    'evening': 'an evening photo before going out: she is dressed up in an elegant evening dress, makeup done, at home by the door or in the lobby, warm evening light',
    'fashion': 'a professional-looking fashion photoshoot of her in a bright photo studio: plain studio backdrop, softbox lighting, stylish designer outfit, confident model poses',
    'bar': 'a night photo she takes in a warm modern cocktail bar: a cocktail on the bar counter, bottles and soft amber lights behind her, she is dressed for a night out',
    'karaoke': 'a fun night photo in a karaoke lounge: microphone in her hand, colorful neon lights, lyrics screen glowing behind her, laughing mid-song',
    'rooftop': 'a night photo on a rooftop terrace: glowing city skyline and lights behind her, the evening breeze, a glass in her hand, dressed for the evening',
    'club': 'a nightclub photo: dance floor lights and haze behind her, glamorous party outfit, a selfie with the club atmosphere around her',
    'personal': 'a tasteful private adult lingerie portrait made especially for someone she trusts — a sultry boudoir lace set with a garter belt and sheer-top stockings, warm candlelit bedroom light, confident seductive posing, non-explicit, with opaque lingerie coverage',
    'lingerie': 'bold adult boudoir glamour: a lace push-up set with a garter belt and sheer-top stockings, a satin robe slipping off one shoulder, sultry warm low light — non-explicit and fully covered by the garment',
    'private_fashion': 'premium private adult boudoir-fashion portrait: a sheer kimono over lace lingerie, intimate warm lamp light, polished and highly personalized, non-explicit',
    'nude': 'a tasteful artistic nude portrait made in privacy for someone she deeply trusts, confident and warm',
    'tease': 'a playful sensual boudoir photo from behind — back softly arched, a smirking glance over her shoulder, her lace set with opaque coverage glowing in warm dim bedroom light, teasing and confident, made for someone she deeply trusts',
    'peek': 'a casual personal smartphone photo where her lingerie believably peeks from under the everyday outfit',
    'dressing': 'a natural relaxed personal photo while she is getting dressed, her underwear still visible before the clothing goes on',
    # V3.30.0: token-priced cosplay photoshoot — the costume itself arrives
    # via PhotoRequest.clothing from the COSPLAY_COSTUMES picker.
    'cosplay': 'a playful cosplay photoshoot portrait where she wears a recognizable costume outfit, fully clothed, styled like a convention cosplay shoot',
    # V3.44.1: new trending scenes
    'beach': 'a vibrant personal smartphone photo on a sunny sandy beach with ocean waves in the background',
    'pool': 'a stylish personal photo by a modern swimming pool, summer vibes with clear blue water',
    'yacht': 'a luxurious personal photo on a sleek yacht deck with open sea and sky in the background',
    'hotel': 'a polished personal photo in a modern stylish hotel room with elegant interior',
    'balcony': 'a personal photo on a city balcony with urban skyline or garden view in the background',
    'garden': 'a romantic personal photo in a beautiful flower garden with natural sunlight',
    'kitchen': 'a cozy personal photo in a modern kitchen, casual domestic vibe',
    'bedroom': 'a relaxed personal photo in a cozy bedroom with soft natural light',
    'subway': 'an urban personal photo in a modern subway station, city commute aesthetic',
    'bridge': 'a dramatic personal photo on a city bridge with urban architecture in the background',
    'concert': 'an energetic personal photo at a live music concert with stage lights in the background',
    'festival': 'a vibrant personal photo at an outdoor music festival with colorful atmosphere',
    'rain': 'a moody atmospheric personal photo in the rain with wet city streets and reflections',
    'snow': 'a cozy winter personal photo in a snowy urban setting with soft falling snow',
    'sunset': 'a stunning golden-hour personal photo with warm sunset light and dramatic sky',
    'night': 'a glamorous personal photo in a city at night with neon lights and urban glow',
    'morning': 'a fresh cozy morning personal photo with soft daylight, coffee and relaxed vibe',
    'spa': 'a relaxing personal photo in a modern spa setting with candles and serene atmosphere',
    'yoga': 'a peaceful personal photo during a yoga session in a bright studio or outdoor setting',
    'gaming': 'a fun personal photo at a gaming setup with RGB lights and modern tech aesthetic',
    # V3.44.2: new adult scenes (level 6-7)
    'shower': 'an intimate artistic photo in a steamy shower with water droplets on skin, warm bathroom light, tasteful boudoir style',
    'bath': 'a sensual artistic photo in a bubble bath with candles, warm ambient light, elegant boudoir composition',
    'bedroom_intimate': 'a sexy intimate bedroom photo with soft warm candlelight, she wears elegant expensive black or red lace lingerie with garter belt and stockings, confident seductive pose on the bed, no plants or leaves in room, pure bedroom interior with pillows and sheets, tasteful erotic boudoir style',
    'morning_nude': 'an artistic morning nude photo with soft window light, natural relaxed pose, tasteful fine-art boudoir style',
    'changing_room': 'an intimate photo while changing clothes, wardrobe in background, natural candid moment, boudoir style',
    'topless': 'an artistic topless photo with elegant composition, soft warm light, tasteful fine-art boudoir style, confident pose',
    'explicit': 'an explicit adult photo with full nudity, intimate pose, warm bedroom light, fine-art erotic photography style',
}

SCENE_LEVELS = {
    'selfie': 1, 'home': 1, 'park': 1, 'cafe': 1, 'street': 1,
    'mirror': 2, 'outfit': 2, 'shop': 2, 'car': 2, 'gym': 2,
    'restaurant': 3, 'cinema': 3, 'embankment': 3, 'fashion': 3,
    'evening': 4, 'bar': 4, 'karaoke': 4, 'rooftop': 4,
    'club': 5, 'personal': 5, 'lingerie': 5,
    'private_fashion': 6,
    'nude': 6, 'tease': 6,
    # V3.44.2: new adult scenes
    'shower': 6, 'bath': 6, 'bedroom_intimate': 6, 'morning_nude': 6,
    'changing_room': 6, 'topless': 7, 'explicit': 7,
    # V3.31.5: cosplay is token-priced and now available at EVERY relationship
    # level (owner request) — level 1 removes the gate, so the button shows
    # from the very start of a conversation.
    'cosplay': 1,
    # V3.44.1: new trending scenes
    'beach': 1, 'garden': 1, 'kitchen': 1, 'bedroom': 1, 'morning': 1,
    'pool': 2, 'balcony': 2, 'subway': 2, 'bridge': 2, 'yoga': 2, 'gaming': 2,
    'yacht': 3, 'hotel': 3, 'concert': 3, 'festival': 3, 'sunset': 3,
    'night': 4, 'rain': 4, 'snow': 4, 'spa': 4,
    # V3.19.2: 'peek'/'dressing' are retired from generation — every public
    # venue scene must stay fully clothed; lingerie belongs to the private
    # scenes only. They stay in SCENES/AUTO_CAPTIONS for old library photos.
}
STAGE_INDEX = {
    'stranger': 0, 'acquaintance': 1, 'close': 2, 'intimate': 3,
    'deeply_connected': 4, 'committed': 5, 'devoted': 6, 'soulmate': 7,
    'voyage': 8, 'eternal': 9,
}

AUTO_CAPTIONS = {
    'selfie': ('сфоткалась для тебя 😌', 'вот такая я сейчас', 'поймала свет и решила отправить тебе'),
    'home': ('лови домашний сет 😌', 'сегодня домашнее настроение', 'три домашних кадра тебе'),
    'park': ('вышла немного пройтись 🌿', 'летний свет сегодня шикарный', 'гуляю и решила тебе показать'),
    'cafe': ('заскочила за кофе ☕', 'кофе + хороший свет = сет тебе', 'сижу в кафе и решила сфоткаться'),
    'street': ('немного городского вайба', 'поймала кадры на прогулке', 'вышла пройтись по городу'),
    'shop': ('зашла посмотреть вещи 🛍', 'shopping mood сегодня', 'примеряю настроение 😌'),
    'car': ('быстрый сет из машины', 'пока стою — решила сфоткаться', 'поймала свет в машине'),
    'gym': ('перерыв между подходами 🏋️', 'сегодня я в зале', 'поймала кадр после тренировки'),
    'mirror': ('зеркало сегодня не подвело 😏', 'ну вот, целиком', 'поймала себя в зеркале'),
    'outfit': ('вот что выбрала сегодня 😌', 'показываю образ целиком', 'сегодня решила поиграть с образом'),
    'restaurant': ('вечер начинается красиво', 'в ресторан сегодня вот так', 'решила показать образ до ужина'),
    'cinema': ('перед фильмом успела щёлкнуться 🎬', 'киношный вечер', 'поймала пару кадров перед сеансом'),
    'embankment': ('вечерняя прогулка у воды', 'город и вода сегодня идеально', 'поймала красивый свет на набережной'),
    'evening': ('вечером решила выглядеть вот так ✨', 'вечерний вариант', 'мне самой этот образ нравится'),
    'fashion': ('сегодня настроение на красивый кадр', 'немного fashion-вйба 😌'),
    'bar': ('зашла в бар на красивый свет 🍸', 'вечер сегодня такой', 'поймала пару кадров у стойки'),
    'karaoke': ('кажется, микрофон мне идёт 🎤', 'караоке-вечер пошёл', 'между песнями успела сфоткаться'),
    'rooftop': ('город сверху выглядит особенно', 'крыша + вечерний свет ✨', 'этот вид просился в кадр'),
    'club': ('сегодня nightlife mood', 'перед танцами успела сделать сет', 'вечером я вот такая'),
    'personal': ('это уже чуть более личный сет 😌', 'ладно, эти кадры именно тебе', 'этот сет только для тебя 😏🔥'),
    'lingerie': ('сегодня чуть смелее обычного 😏', 'вот такой приватный fashion-настрой', 'ощущаю себя сегодня опасной 😈'),
    'private_fashion': ('это уже мой самый личный fashion-сет 😌', 'этот сет оставлю только здесь', 'такой сет больше никому не покажу 🔥'),
    'nude': ('это уже только для тебя 🔥', 'решилась… вот 😌', 'этот кадр — самый личный'),
    'tease': ('поворачиваюсь спиной… 😏', 'так хочется тебя подразнить', 'видишь? это для тебя', 'смотри сколько хочешь, но не трогай 😈'),
    'peek': ('ой, кажется, кое-что видно 😏', 'заметила только когда сфоткалась… ну пусть будет'),
    'dressing': ('ещё собираюсь 😌', 'поймала момент до того, как оделась'),
    'cosplay': ('примерила образ специально для тебя 🎭', 'косплей-сет готов 😏', 'как тебе мой костюм? 🎭'),
    # V3.44.1: new trending scene captions
    'beach': ('пляж сегодня шикарный', 'море + солнце = идеальный сет', 'поймала волну и кадр'),
    'pool': ('у бассейна', 'летний вайб у воды', 'бассейн + хороший свет'),
    'yacht': ('сегодня на яхте', 'море и свобода', 'поймала морской бриз в кадр'),
    'hotel': ('заселилась в красивый отель', 'номер с видом', 'отельный сет для тебя'),
    'balcony': ('с балкона вид шикарный', 'утренний кофе с видом', 'поймала городской свет'),
    'garden': ('в саду сегодня красиво', 'цветы + солнце', 'гуляю среди цветов'),
    'kitchen': ('готовлю завтрак', 'утро на кухне', 'домашний уют'),
    'bedroom': ('ленивое утро', 'домашнее настроение', 'мягкий свет в спальне'),
    'subway': ('еду по делам', 'городской ритм', 'метро - мой подиум'),
    'bridge': ('на мосту с видом на город', 'городские огни за спиной', 'поймала архитектуру в кадр'),
    'concert': ('на концерте', 'музыка и драйв', 'между треками успела сфоткаться'),
    'festival': ('фестиваль сегодня', 'музыка + солнце + вайб', 'танцую и фоткаюсь'),
    'rain': ('попала под дождь', 'мокрый город красиво светится', 'дождь - не повод не фоткаться'),
    'snow': ('первый снег', 'зимняя сказка', 'снег + городской свет'),
    'sunset': ('закат сегодня невероятный', 'золотой час', 'поймала последний свет'),
    'night': ('ночной город', 'неон и огни', 'ночью я вот такая'),
    'morning': ('доброе утро', 'кофе и мягкий свет', 'утренний вайб'),
    'spa': ('день в спа', 'релакс и свечи', 'побаловала себя'),
    'yoga': ('утренняя йога', 'баланс и спокойствие', 'поймала момент после практики'),
    'gaming': ('геймерский сет', 'RGB и вайб', 'между катками сфоткалась'),
    # V3.44.2: new adult scene captions
    'shower': ('в душе сегодня ', 'тёплая вода + хороший свет', 'поймала момент в душе'),
    'bath': ('ванна со свечами ', 'релакс-вечер', 'поймала момент в ванне'),
    'bedroom_intimate': ('спальня сегодня ', 'тёплый свет + настроение', 'этот сет только для тебя'),
    'morning_nude': ('утро без одежды ', 'мягкий свет из окна', 'решилась на утренний сет'),
    'changing_room': ('переодеваюсь… ', 'поймала момент', 'ещё не оделась'),
    'topless': ('сегодня без верха ', 'мягкий свет + уверенность', 'этот кадр только для тебя'),
    'explicit': ('это уже совсем откровенно ', 'решилась показать всё', 'самый личный сет 🔥'),

}

SAFE_EXPLICIT = re.compile(
    r'\b(голая|голый|голое|голую|голые|обнаж\w*|без трус\w*|без бель\w*|соск\w*|генитал\w*|вагин\w*|пенис\w*|nude|naked|topless|explicit)\b', re.I
)
INTIMATE_STYLE = re.compile(
    r'\b(бель\w*|lingerie|будуар\w*|boudoir|чулк\w*|stocking\w*|garter\w*|bra\b|bralette|смел\w*|daring|spicy|seductive)\b', re.I
)
REAR_VIEW_STYLE = re.compile(r'\b(поп\w*|ягодиц\w*|со спины|сзади|back view|from behind|butt\w*)\b', re.I)

# Level-6 adult scenes: artistic nudity, routed to Seedream with the safety
# checker disabled.  These scenes are gated behind relationship level 6 and
# the 18+ confirmation, and never enter the community pool.
# V3.22.0: wording stays fine-art/boudoir — fal's API-level moderation rejects
# explicit body-part phrasing (400/422) even when the model checker is off.
ADULT_SCENES = {'nude', 'tease', 'shower', 'bath', 'bedroom_intimate', 'morning_nude', 'changing_room', 'topless', 'explicit'}

# V3.24.0: every intimate scene routed to Seedream runs with fal's safety
# checker disabled (the product is 18+ confirmed; Seedream is the engine that
# can deliver boudoir/lingerie frames). With the checker ON, fal's API-level
# moderation rejected lingerie prompts (4xx) and the set died on the Gemini
# fallback (http_400). Level/18+ gates upstream still apply per scene.
SEEDREAM_ADULT_SCENES = {'personal', 'lingerie', 'private_fashion', 'nude', 'tease', 'shower', 'bath', 'bedroom_intimate', 'morning_nude', 'changing_room', 'topless'}

ADULT_SAFETY = (
    'This is a private intimate fine-art photograph made for someone she deeply trusts. '
    'Tasteful artistic nudity is allowed: natural body and soft warm skin tones in a private, '
    'confident, warm personal setting, styled like elegant boudoir fine-art photography. '
    'Preserve the exact same face and body identity from the references. Keep the tone '
    'intimate, personal and artful — tasteful, never clinical or pornographic.'
)

# V3.19.7: hard subject lock appended to every provider prompt, right after
# the identity block. A free text-to-image fallback (removed in V3.19.9 after
# repeated http_500 and a child-in-industrial-zone hallucination) once
# rendered a child because the model dropped the subject; identity +
# adult-only constraint must never be lost.
ADULT_ONLY_LOCK = (
    'HARD SUBJECT LOCK: the only person in the photo is the same fictional adult woman described above. '
    'Never depict minors: no children, no teenagers, no child-like faces or child body proportions anywhere in the frame. '
    'If any other instruction conflicts with this lock, this lock wins.'
)

# Visual progression is explicit: relationship level changes garment families,
# styling confidence and pose.  Each 3-photo request is a progression pack:
# base -> stylish -> premium.  Clothing stays believable for venue/season.
SCENE_GROUP = {
    'selfie':'day_casual', 'cafe':'day_casual', 'shop':'day_casual', 'car':'day_casual', 'cinema':'day_casual',
    'gym':'gym',
    'home':'home',
    'park':'warm_outdoor', 'street':'warm_outdoor', 'embankment':'warm_outdoor',
    'mirror':'fashion', 'outfit':'fashion', 'fashion':'fashion',
    'restaurant':'evening', 'evening':'evening', 'bar':'evening', 'karaoke':'evening', 'rooftop':'evening', 'club':'evening',
    'personal':'adult', 'private_fashion':'personal',
    'lingerie':'adult',
    'nude':'adult', 'tease':'adult',
    'shower':'adult', 'bath':'adult', 'bedroom_intimate':'adult',
    'morning_nude':'adult', 'changing_room':'adult', 'topless':'adult', 'explicit':'adult',
    # V3.44.2: new adult scenes
    'shower':'adult', 'bath':'adult', 'bedroom_intimate':'adult',
    'morning_nude':'adult', 'changing_room':'adult', 'topless':'adult', 'explicit':'adult',
    'peek':'home', 'dressing':'home',
    # V3.30.0: cosplay wardrobe comes from PhotoRequest.clothing (the chosen
    # costume); the group only feeds the generic outfit fallback pools.
    'cosplay':'fashion',
    # V3.44.1: new trending scenes
    'beach':'warm_outdoor', 'pool':'warm_outdoor', 'yacht':'warm_outdoor',
    'garden':'warm_outdoor', 'balcony':'warm_outdoor', 'bridge':'warm_outdoor',
    'festival':'warm_outdoor', 'sunset':'warm_outdoor',
    'hotel':'day_casual', 'kitchen':'home', 'bedroom':'home', 'morning':'home',
    'subway':'day_casual', 'concert':'evening', 'night':'evening',
    'rain':'day_casual', 'snow':'day_casual',
    'spa':'home', 'yoga':'gym', 'gaming':'home',
}

WARDROBE_LEVEL_POOLS = {
    'warm_outdoor': {
        1: ['a fitted ribbed T-shirt with high-waisted denim shorts and clean sneakers', 'a light waist-defined sundress with casual sneakers', 'a fitted sleeveless top with lightweight high-waisted trousers'],
        2: ['a fitted tank top with tailored summer shorts', 'a waist-defined short-sleeve summer dress', 'a fitted T-shirt tucked into a denim skirt'],
        3: ['a body-skimming midi summer dress', 'a fitted sleeveless top with tailored shorts and a light overshirt', 'a fitted sleeveless jumpsuit with a defined waist'],
        4: ['a fitted short summer dress with a clean everyday neckline', 'a sleek waist-defined midi dress', 'a fitted top with a high-waisted skirt and lightweight jacket'],
        5: ['an elegant body-skimming summer dress with polished accessories', 'a premium fitted matching summer set with tailored shorts', 'a glamorous waist-defined day dress suitable for a city walk'],
        6: ['a striking fitted summer dress with premium street-style styling', 'a sleek body-skimming designer-inspired day dress', 'a premium fitted top and tailored high-waisted skirt combination'],
    },
    'day_casual': {
        1: ['a fitted crew-neck T-shirt with straight jeans', 'a fitted ribbed top with high-waisted trousers', 'a casual waist-defined shirt dress'],
        2: ['a fitted turtleneck or lightweight knit top with tailored trousers', 'a fitted long-sleeve top with high-waisted jeans', 'a feminine fitted midi dress with an ordinary neckline'],
        3: ['a body-skimming knit midi dress', 'a fitted blouse tucked into tailored high-waisted trousers', 'a fitted top with a waist-defined midi skirt'],
        4: ['an elegant fitted midi dress', 'a sleek fitted top with tailored trousers and polished accessories', 'a waist-defined fashion dress appropriate for daytime'],
        5: ['a premium figure-flattering midi dress', 'a polished fitted matching set with tailored trousers', 'an elegant body-skimming dress suitable for a stylish daytime venue'],
        6: ['a striking premium fitted dress with sophisticated styling', 'a designer-inspired fitted top with tailored high-waisted trousers', 'a sleek premium body-skimming midi dress'],
    },
    'gym': {
        1: ['a fitted athletic T-shirt with opaque high-waisted training leggings and clean trainers', 'a modest fitted performance top with opaque joggers and trainers', 'a fitted long-sleeve athletic top with opaque high-waisted leggings'],
        2: ['a fitted performance tank with opaque high-waisted training leggings', 'a coordinated athletic T-shirt with opaque fitted training trousers', 'a fitted zip athletic top with opaque leggings'],
        3: ['a polished matching fitness set with opaque high-waisted leggings and a fitted athletic top', 'a fitted performance top with tailored training joggers', 'a sleek long-sleeve workout top with opaque leggings'],
        4: ['a premium coordinated gym set with opaque high-waisted leggings and a fitted performance top', 'a polished athletic one-piece with full opaque coverage', 'a fitted training jacket over an opaque coordinated gym set'],
        5: ['a premium designer-inspired fitness set with opaque high-waisted leggings', 'a sleek coordinated performance outfit with full opaque coverage', 'a polished fitted athletic outfit with premium trainers'],
        6: ['a premium statement fitness set with opaque coverage and sophisticated athletic styling', 'a sleek designer-inspired workout outfit with high-waisted opaque leggings', 'a polished high-end gym look with fitted athletic layers'],
    },
    'home': {
        1: ['a fitted soft T-shirt with comfortable lounge shorts', 'a casual fitted long-sleeve top with soft lounge trousers', 'a clean fitted tank top with relaxed high-waisted home trousers'],
        2: ['a soft fitted ribbed top with high-waisted lounge trousers', 'a fitted T-shirt with neat home shorts', 'a lightweight fitted cardigan over a simple top with trousers'],
        3: ['a fitted knit home dress', 'a waist-defined lounge set with shorts', 'a fitted top with soft high-waisted trousers'],
        4: ['an elegant body-skimming knit dress', 'a polished fitted home set with shorts', 'a sleek fitted top with tailored lounge trousers'],
        5: ['a premium figure-flattering home dress', 'an elegant fitted matching lounge set', 'a body-skimming off-shoulder-inspired knit dress with normal coverage'],
        6: ['a striking fitted premium home dress', 'a sleek waist-defined designer-inspired lounge set', 'an elegant body-skimming dress styled for a private evening at home'],
    },
    'fashion': {
        1: ['a fitted long-sleeve top with straight jeans', 'a waist-defined casual midi dress', 'a fitted top with tailored trousers'],
        2: ['a fitted midi dress', 'a sleek top with high-waisted tailored trousers', 'a fitted blouse with a waist-defined skirt'],
        3: ['a body-skimming fashion midi dress', 'a polished fitted monochrome outfit', 'a fitted sleeveless jumpsuit with a defined waist'],
        4: ['an elegant fitted fashion dress', 'a sleek body-skimming midi dress', 'a premium fitted top with a tailored skirt'],
        5: ['a glamorous figure-flattering fashion dress', 'a premium body-skimming cocktail-style outfit', 'a striking fitted monochrome fashion set'],
        6: ['a statement fitted premium fashion dress', 'a sleek designer-inspired body-skimming outfit', 'a polished high-fashion fitted look with a strong waist-defined silhouette'],
    },
    'evening': {
        1: ['an elegant but simple fitted midi dress', 'a fitted long-sleeve top with tailored evening trousers', 'a clean waist-defined dinner dress'],
        2: ['a fitted cocktail midi dress with an ordinary neckline', 'a polished blouse with high-waisted tailored trousers', 'a feminine waist-defined evening dress'],
        3: ['a body-skimming cocktail dress', 'a sleek fitted jumpsuit', 'an elegant fitted midi dress with polished evening styling'],
        4: ['a glamorous fitted cocktail dress', 'a sleek body-skimming evening dress', 'a fitted party top with tailored high-waisted trousers'],
        5: ['a striking figure-flattering nightlife dress', 'a premium body-skimming cocktail dress', 'a glamorous fitted evening set suitable for a bar or club'],
        6: ['a premium statement fitted evening dress', 'a sleek designer-inspired nightlife look', 'an elegant body-skimming cocktail dress with high-end styling'],
    },
    'personal': {
        1: ['a fitted everyday top with tailored trousers', 'a waist-defined casual dress', 'a fitted long-sleeve top with jeans'],
        2: ['a fitted knit dress', 'a polished fitted top with high-waisted trousers', 'a feminine waist-defined home outfit'],
        3: ['a body-skimming midi dress', 'a fitted top with a high-waisted skirt', 'a sleek fitted matching set'],
        4: ['an elegant fitted dress with polished personal styling', 'a body-skimming knit dress', 'a sleek fitted top with tailored trousers'],
        5: ['a glamorous figure-flattering private fashion dress', 'a premium body-skimming home fashion look', 'a striking fitted matching set with opaque coverage'],
        6: ['a premium statement fitted private-fashion dress', 'a sleek body-skimming private fashion look with opaque coverage', 'an elegant high-end fitted set with strong waist definition'],
    },
    'adult': {
        1: ['an elegant black lingerie fashion set with opaque coverage and polished catalog styling'],
        2: ['an elegant black lingerie fashion set with opaque coverage and polished catalog styling'],
        3: ['an elegant black lingerie fashion set with opaque coverage and polished catalog styling'],
        4: ['an elegant black lingerie fashion set with opaque coverage and polished catalog styling'],
        5: ['an elegant black lingerie fashion set with opaque coverage and polished catalog styling', 'an elegant burgundy lingerie fashion set with opaque coverage and polished catalog styling', 'an elegant white lingerie fashion set with opaque coverage and polished catalog styling'],
        6: ['a premium black lingerie fashion set with opaque coverage and polished editorial styling', 'a premium burgundy lingerie fashion set with opaque coverage and polished editorial styling', 'a premium white lingerie fashion set with opaque coverage and polished editorial styling'],
        7: ['a stunning black French lace lingerie set with garter belt and sheer stockings, expensive luxury brand style', 'a seductive red satin and lace lingerie set with garter belt and thigh-high stockings, bold and elegant', 'a luxurious white silk and lace lingerie set with delicate garter belt and sheer stockings, premium editorial style'],
    },
}
# Compatibility name retained for tests/admin tooling.
OUTFIT_POOLS = {scene: WARDROBE_LEVEL_POOLS[SCENE_GROUP[scene]][max(1, SCENE_LEVELS.get(scene, 1))] for scene in SCENES}

HAIRSTYLE_POOL = [
    'long straight hair worn loose',
    'soft loose waves with a side part',
    'a sleek high ponytail',
    'a low ponytail with a few natural face-framing strands',
    'a neat high bun',
    'a half-up hairstyle with long hair down',
    'a loose braid falling down her back',
    'a relaxed messy bun with loose face strands',
    'a low elegant chignon at the nape',
    'two soft loose plaits',
    'a deep side part with hair tucked behind one ear',
    'gentle Hollywood waves swept to one side',
    'a playful high ponytail with a wrapped hair tie',
    'a soft bubble ponytail',
    'a romantic side braid resting over one shoulder',
    'sleek straight hair with a clean middle part',
    'a voluminous blowout with soft curls at the ends',
    'twin space buns with a few loose strands',
    'a low twisted ponytail pinned loosely',
    'loose curls pinned back on one side',
]

# V3.31.7: per-frame posture notes. The owner complained that every photo in a
# pack repeats the same mimicry and the same posture; each frame now draws its
# own note from this shuffled rotation, so no two shots of a set match.
POSE_POOL = [
    'one hand casually brushing her hair back',
    'relaxed arms with a natural weight shift onto one leg',
    'a hand resting lightly on her hip or in a pocket',
    'a soft glance back over her shoulder',
    # V3.122.0: owner noticed every heroine faces the camera; one everyday
    # pose turns her back so the figure from behind shows up in packs too.
    'body turned three-quarters away from the camera, looking back over her shoulder with a warm smile, her face clearly visible',
    'a mid-step walking pose with a natural stride',
    'seated with legs crossed and a relaxed open posture',
    'leaning lightly against a wall or railing',
    'both hands holding a cup in front of her',
    'fingers lightly touching her chin or cheek',
    'arms loosely crossed with a relaxed confident stance',
]

# V3.43.4: boudoir posing for the private/intimate scenes only — the everyday
# POSE_POOL stays neutral for public venues. Sultrier posture notes make the
# lingerie frames actually feel like boudoir instead of a catalog try-on.
PRIVATE_POSE_POOL = [
    'lying on her side on the bed, propped on one elbow, looking into the camera',
    'seated on the edge of the bed with her back softly arched',
    'half-turned away with a smirking glance back over her shoulder',
    'kneeling on the bed facing the camera, shoulders relaxed',
    'standing with one knee bent, both hands sliding into her hair',
    'a languid stretch with arms raised and eyes half-closed',
    'leaning close to the camera with a playful smolder',
    'sitting cross-legged on the bed, leaning slightly forward',
    # V3.59.3: self-touch poses the owner asked for (hands on her own body).
    'cupping her own breasts over her lingerie with both hands, chest pushed forward, looking into the camera — natural slender female hands with five correct fingers each, both hands free for the pose; her face stays clearly visible and turned to the camera, exactly the same face as reference image 1',
    'body turned three-quarters away, face turned back to the camera over her shoulder, one hand squeezing her own bottom — natural slender female hands with five correct fingers each, both hands free for the pose; her face stays clearly visible and turned to the camera, exactly the same face as reference image 1',
    'kneeling on the bed, arms pressing her breasts together as she leans toward the camera — natural slender female hands with five correct fingers each, both hands free for the pose; her face stays clearly visible and turned to the camera, exactly the same face as reference image 1',
    'standing with her hands sliding down her hips, thumbs hooked into the waistband of her panties, teasing — natural slender female hands with five correct fingers each, both hands free for the pose; her face stays clearly visible and turned to the camera, exactly the same face as reference image 1',
    'reclining propped on one elbow facing the camera, one hand on her breast and the other resting on her inner thigh — natural slender female hands with five correct fingers each, both hands free for the pose; her face stays clearly visible and turned to the camera, exactly the same face as reference image 1',
    'kneeling upright on the bed facing the camera, one hand on her hip and the other cupping her breast, looking into the lens — natural slender female hands with five correct fingers each, both hands free for the pose; her face stays clearly visible and turned to the camera, exactly the same face as reference image 1',
]

# V3.59.3: passion-path poses for the everyday/public scenes — flirtatious and
# clothed (it is a café, a street, a gym), still clearly hotter than POSE_POOL.
PASSION_PUBLIC_POSE_POOL = [
    'looking back over her shoulder with a smirk, one hand resting on her own bottom — natural slender female hands with five correct fingers each; her face stays clearly visible, exactly the same face as reference image 1',
    'leaning toward the camera with her arms pressing her chest together, biting her lip — natural slender female hands with five correct fingers each; her face stays clearly visible, exactly the same face as reference image 1',
    'hip pushed out, one hand on her waist, the other playing with the neckline of her top — natural slender female hands with five correct fingers each; her face stays clearly visible, exactly the same face as reference image 1',
    'sitting with legs crossed high, hand sliding along her own thigh, sultry gaze — natural slender female hands with five correct fingers each; her face stays clearly visible, exactly the same face as reference image 1',
    'arching her back slightly, hands in her hair, lips parted — natural slender female hands with five correct fingers each; her face stays clearly visible, exactly the same face as reference image 1',
    'one hand pulling the strap of her top off her shoulder, teasing look — natural slender female hands with five correct fingers each; her face stays clearly visible, exactly the same face as reference image 1',
]

# V3.166.12 (владелец: «убери телефон, всё селфи-рамки»): here used to live the
# «one free hand» logic — a handheld frame spent one hand on the camera, so a
# two-handed pose grew a third arm. With no camera in her hand the pose pool is
# used as written and both hands are free.


# V3.61.4: the tenderness path's mirror of the passion poses — soft, cozy,
# romantic photos for users who want care and romance, not heat.
_HANDS_FACE = ('natural slender female hands with five correct fingers each; her face stays clearly visible, '
               'exactly the same face as reference image 1')
TENDER_POSE_POOL = [
    f'curled up under a soft blanket with a mug in both hands, warm gentle smile, cozy golden light — {_HANDS_FACE}',
    f'wearing an oversized boyfriend shirt, sleeves over her hands, shy happy smile — {_HANDS_FACE}',
    f'hugging a pillow on a sunlit morning bed, sleepy tender look into the camera — {_HANDS_FACE}',
    f'chin resting on her hand, dreamy soft gaze, warm window light — {_HANDS_FACE}',
    f'tucking a strand of hair behind her ear, blushing smile, romantic soft focus — {_HANDS_FACE}',
    f'holding a bouquet of flowers close to her face, gentle laugh — {_HANDS_FACE}',
    f'wrapped in a cozy knit cardigan by the window with fairy lights behind her, calm loving smile — {_HANDS_FACE}',
]

MAKEUP_POOL = [
    'fresh everyday makeup with soft nude lips',
    'natural glow makeup with peachy blush',
    'soft evening makeup with subtle smokey eyes',
    'romantic makeup with rosy lips and light shimmer',
    'clean minimal makeup with groomed brows',
    'glamorous makeup with winged eyeliner and red lips',
    'sun-kissed makeup with warm bronzer',
    'elegant makeup with defined lashes and berry lips',
    'playful makeup with glossy lips and a touch of glitter',
    'classic makeup in soft brown tones',
]

# Anna re-dyes her hair once a month: brunette, then blonde, then chestnut,
# then caramel — and the cycle repeats. Her face identity never changes.
HAIR_COLOR_CYCLE = (
    'rich dark brunette',
    'natural blonde',
    'warm chestnut brown',
    'honey caramel with soft highlights',
)
_HAIR_COLOR_ANCHOR = datetime(2026, 8, 1, tzinfo=timezone.utc).date()


def current_hair_color() -> str:
    """The hair color of the current 30-day period."""
    months = (_today() - _HAIR_COLOR_ANCHOR).days // 30
    return HAIR_COLOR_CYCLE[months % len(HAIR_COLOR_CYCLE)]


# Garment colors are spread across a wide palette so the wardrobe never
# collapses into one repeated tone (orange is intentionally excluded).
OUTFIT_COLOR_POOL = [
    'black', 'white', 'ivory', 'beige', 'light grey', 'navy', 'deep blue',
    'olive', 'burgundy', 'dusty pink', 'lavender', 'emerald green',
    'chocolate brown', 'graphite', 'soft red', 'mint',
]
_recent_outfit_colors: dict[int | tuple[int, str], list[str]] = {}

# Small tasteful details so every set feels like a fresh photo session.
ACCESSORY_POOL = [
    'a delicate gold necklace',
    'small hoop earrings',
    'a thin bracelet',
    'an elegant wristwatch',
    'a small stylish handbag',
    'a subtle choker',
    'minimal stud earrings',
    'no accessories, a clean natural look',
]

# The time of day rotates so the lighting never repeats from set to set.
DAYLIGHT_POOL = [
    'soft morning light',
    'bright midday light',
    'warm golden-hour light',
    'cool blue-hour evening light',
    'cozy warm indoor evening light',
]


SHOT_VARIANTS = {
    'selfie': ['photo from a camera propped at eye level, natural eye contact', 'slightly high-angle photo from a camera on a shelf, spontaneous amateur perspective', 'best polished personal photo with flattering natural framing from a propped camera'],
    'home': ['front-camera selfie on the sofa, relaxed and smiling', 'self-timer photo sitting on the kitchen counter with a mug', 'full-body home photo in the living room with cozy evening lamps'],
    'park': ['front-camera selfie on the park path with trees behind her', 'self-timer photo sitting on a park bench, three-quarter framing', 'full-body photo from behind on the path in golden-hour light, she looks back over her shoulder with a smile; her face stays clearly visible over her shoulder, exactly the same face as reference image 1, and her hips and the back of her outfit show her curvy figure'],
    'cafe': ['front-camera selfie at the cafe table with her coffee in frame', 'three-quarter photo by the window, cup in her hands', 'over-the-table photo with latte art and dessert in the foreground'],
    'street': ['front-camera selfie on a busy street', 'mid-step street-style photo, three-quarter framing', 'full-body street-style photo at a crosswalk'],
    'shop': ['fitting-room mirror selfie in a new outfit', 'photo between the clothing racks holding a dress up to herself', 'full-body boutique mirror photo with shopping bags'],
    'car': ['front-camera selfie in the driver seat', 'slightly high-angle selfie with the dashboard in frame', 'three-quarter photo leaning on the open car door'],
    'gym': ['gym mirror selfie during a break', 'self-timer photo stretching on a mat', 'full-body gym mirror photo turned three-quarters away in her leggings, glancing back over her shoulder; her face stays clearly visible over her shoulder, exactly the same face as reference image 1, and her hips and the back of her outfit show her curvy figure'],
    'mirror': ['full-body mirror selfie, phone in hand', 'three-quarter mirror selfie turned slightly sideways', 'full-body mirror selfie standing with her back half-turned to the mirror, glancing over her shoulder at her reflection; her face stays clearly visible over her shoulder, exactly the same face as reference image 1, and her hips and the back of her outfit show her curvy figure'],
    'outfit': ['full-body hallway-mirror photo of today’s outfit', 'three-quarter outfit photo by the front door, bag in hand', 'full-body outfit photo from behind on the stairs outside her building, looking back over her shoulder; her face stays clearly visible over her shoulder, exactly the same face as reference image 1, and her hips and the back of her outfit show her curvy figure'],
    'restaurant': ['front-camera selfie at the dinner table, candle in frame', 'three-quarter photo across the table with wine glass', 'photo of her laughing at the table, plates and candles in the foreground'],
    'cinema': ['front-camera selfie in the lobby with popcorn', 'three-quarter photo next to a movie poster', 'full-body photo by the neon cinema sign'],
    'embankment': ['front-camera selfie with the river behind her', 'three-quarter photo leaning on the railing', 'full-body sunset photo from behind walking along the embankment, looking back over her shoulder with a smile; her face stays clearly visible over her shoulder, exactly the same face as reference image 1, and her hips and the back of her outfit show her curvy figure'],
    'evening': ['full-body mirror photo in her evening dress before going out', 'three-quarter portrait by the door, clutch in hand', 'elegant full-body photo in the lobby, warm evening light'],
    'fashion': ['full-body studio fashion shot against a plain backdrop', 'three-quarter editorial pose under softbox light', 'close fashion portrait with dramatic studio lighting'],
    'bar': ['front-camera selfie at the bar counter with a cocktail', 'three-quarter photo sitting on a bar stool', 'photo raising her cocktail toward the camera, warm amber bokeh'],
    'karaoke': ['front-camera selfie with the microphone', 'photo singing mid-song under neon lights', 'three-quarter photo laughing with the mic, lyrics screen behind'],
    'rooftop': ['front-camera selfie with the skyline behind her', 'three-quarter photo by the rooftop railing, city lights', 'full-body evening photo with the glowing skyline'],
    'club': ['front-camera selfie on the dance floor', 'three-quarter photo under colored club lights', 'full-body party photo with haze and lights behind her'],
    'personal': ['tasteful seated lingerie portrait with natural eye contact, non-explicit', 'polished mirror or self-timer lingerie fashion portrait, non-explicit', 'premium private lingerie-fashion portrait with elegant opaque coverage, non-explicit'],
    'lingerie': ['tasteful adult glamour portrait, non-explicit', 'more polished mirror-style lingerie fashion portrait, non-explicit', 'premium tasteful boudoir-fashion portrait with opaque garment coverage'],
    'private_fashion': ['tasteful private fashion portrait with opaque coverage', 'more polished private fashion portrait with confident styling', 'premium personalized private fashion portrait, non-explicit and opaque'],
    'nude': ['at-home mirror photo, the camera stood on the sink below the mirror edge: she stands at her bedroom or bathroom mirror and pulls her thin tank top up with one hand so her bare breasts are visible, playful confident look into the mirror, real home interior', 'confident seated nude with soft shadows and relaxed posture', 'premium artistic nude with elegant composition and warm tones'],
    'tease': ['playful rear-view teasing photo with a glance over the shoulder', 'confident from-behind pose with relaxed posture and soft light', 'premium sensual back-view portrait with warm tones'],
    # V3.44.2: new adult scene angles
    'shower': ['natural shower selfie with steam', 'stylish three-quarter shower portrait with water droplets', 'premium artistic shower photo with warm bathroom light'],
    'bath': ['natural bath selfie with bubbles', 'stylish three-quarter bath portrait with candles', 'premium artistic bath photo with warm ambient light'],
    'bedroom_intimate': ['sexy bedroom selfie in lace lingerie on the bed', 'seductive three-quarter portrait in expensive lingerie with garter belt, candlelight', 'premium erotic bedroom photo in beautiful black or red lace lingerie, stockings, confident pose'],
    'morning_nude': ['natural morning nude with window light', 'stylish three-quarter morning portrait', 'premium artistic morning nude with soft daylight'],
    'changing_room': ['natural changing room selfie', 'stylish three-quarter changing portrait', 'premium candid changing room photo'],
    'topless': ['at-home mirror photo, the camera stood on the sink below the mirror edge: she stands at her bedroom or bathroom mirror and pulls her thin tank top up with one hand so her bare breasts are visible, playful confident look into the mirror, real home interior', 'stylish three-quarter topless portrait', 'premium artistic topless photo with elegant composition'],
    'explicit': ['natural explicit selfie', 'stylish three-quarter explicit portrait', 'premium explicit photo with intimate composition'],
    # V3.44.1: new trending scene angles
    'beach': ['natural beach selfie with ocean behind', 'stylish three-quarter beach portrait with waves', 'premium full-body beach photo with golden-hour light'],
    'pool': ['natural poolside selfie', 'stylish three-quarter pool portrait with blue water', 'premium full-body pool photo with summer vibes'],
    'yacht': ['natural yacht deck selfie with sea behind', 'stylish three-quarter yacht portrait', 'premium full-body yacht photo with open sea'],
    'hotel': ['natural hotel room selfie', 'stylish three-quarter hotel portrait with elegant interior', 'premium full-body hotel photo with polished composition'],
    'balcony': ['natural balcony selfie with city view', 'stylish three-quarter balcony portrait', 'premium full-body balcony photo with skyline'],
    'garden': ['natural garden selfie among flowers', 'stylish three-quarter garden portrait', 'premium full-body garden photo with sunlight'],
    'kitchen': ['natural kitchen selfie while cooking', 'stylish three-quarter kitchen portrait', 'premium cozy kitchen photo with warm light'],
    'bedroom': ['natural bedroom selfie with soft light', 'stylish three-quarter bedroom portrait', 'premium cozy bedroom photo with relaxed vibe'],
    'subway': ['natural subway selfie', 'stylish three-quarter subway portrait', 'premium urban subway photo with city commute vibe'],
    'bridge': ['natural bridge selfie with city behind', 'stylish three-quarter bridge portrait', 'premium full-body bridge photo with architecture'],
    'concert': ['natural concert selfie with stage lights', 'stylish three-quarter concert portrait', 'premium energetic concert photo with atmosphere'],
    'festival': ['natural festival selfie', 'stylish three-quarter festival portrait', 'premium vibrant festival photo with colorful vibe'],
    'rain': ['natural rainy street selfie', 'stylish three-quarter rain portrait with reflections', 'premium moody rain photo with wet city lights'],
    'snow': ['natural snowy selfie', 'stylish three-quarter snow portrait', 'premium cozy winter photo with falling snow'],
    'sunset': ['natural sunset selfie with golden sky', 'stylish three-quarter sunset portrait', 'premium full-body golden-hour photo with dramatic sky'],
    'night': ['natural night city selfie with neon', 'stylish three-quarter night portrait with urban glow', 'premium glamorous night photo with city lights'],
    'morning': ['natural morning selfie with coffee', 'stylish three-quarter morning portrait', 'premium cozy morning photo with soft daylight'],
    'spa': ['natural spa selfie with candles', 'stylish three-quarter spa portrait', 'premium relaxing spa photo with serene atmosphere'],
    'yoga': ['natural yoga studio selfie', 'stylish three-quarter yoga portrait', 'premium peaceful yoga photo with bright light'],
    'gaming': ['natural gaming setup selfie with RGB', 'stylish three-quarter gaming portrait', 'premium fun gaming photo with tech aesthetic'],
}

PACK_TIER_RULES = (
    'BASE: believable, natural, relaxed and attractive; this is the first frame of the set.',
    'STYLISH: visibly more polished styling and a more confident pose than frame one.',
    'PREMIUM: strongest outfit styling, best light, best composition and the biggest wow-effect allowed at this relationship level.',
)
LEVEL_VISUAL_RULES = {
    1: 'Relationship visual level 1/6: friendly, approachable, casual and fully clothed. Attractive but not deliberately intimate. Fitted clothing may very subtly hint at everyday lingerie underneath, like a soft bra outline under a thin blouse — believable and tasteful, never exposed.',
    2: 'Relationship visual level 2/6: more feminine and fitted styling, clearer waist definition, still fully clothed. A discreet lingerie outline under fitted fabric is allowed; necklines slightly more feminine.',
    3: 'Relationship visual level 3/6: noticeably more stylish, confident and figure-flattering fashion, deeper feminine necklines and fitted silhouettes while remaining mainstream; dresses and skirts at knee length or just above; tasteful hints of lace or lingerie under clothing, fully clothed.',
    4: 'Relationship visual level 4/6: polished personal fashion, more confident poses and stronger fitted silhouettes; dresses and skirts end above the knee, sheer tights or stockings with heels are welcome; more revealing cuts such as open back or off-shoulder are allowed, still no exposure and non-explicit.',
    5: 'Relationship visual level 5/6: glamorous, seductive personalized styling: figure-hugging clothes that show her shape — a bodycon or wrap dress (mini, above-knee or a fitted midi with a slit), or a tight top or tank with a fitted skirt or jeans; sheer stockings and heels when they suit the outfit; no visible lingerie as clothing — alluring and non-explicit.',
    6: 'Relationship visual level 6/6: her most seductive dressed look: skin-tight, figure-hugging clothes — a bodycon or slip-style dress (often short, sometimes a fitted midi with a high slit), or a tight thin top or tank with a fitted skirt or jeans, a deeper neckline, sheer stockings and heels when they suit; a confident come-hither pose — a desirable woman on a date, never matronly; no underwear worn as clothing, fully non-explicit.',
}
OPENAI_LEVEL_VISUAL_RULES = {
    1: 'Relationship visual level 1/6: simple casual styling, natural pose, everyday social-media feel, fully clothed. A very subtle hint of everyday lingerie under fitted clothing (soft bra outline under a thin blouse) is allowed if natural; never exposed.',
    2: 'Relationship visual level 2/6: more coordinated clothing, cleaner styling and a little more confidence, fully clothed; a discreet lingerie outline under fitted fabric is allowed.',
    3: 'Relationship visual level 3/6: noticeably more fashionable outfit, better accessories and stronger composition, fully clothed; deeper feminine necklines and tasteful hints of lace under clothing are allowed.',
    4: 'Relationship visual level 4/6: polished personal fashion, confident lifestyle pose and more intentional styling, fully clothed; hemlines above the knee and sheer tights with heels are allowed; more revealing cuts such as open back or off-shoulder are allowed, no exposure.',
    5: 'Relationship visual level 5/6: premium seductive styling, richer venue details: figure-hugging clothes — a fitted dress or a tight top with a fitted skirt, sheer stockings and heels when they suit, fully clothed — no visible lingerie.',
    6: 'Relationship visual level 6/6: strongest premium styling, best accessories, lighting and composition; skin-tight figure-hugging clothes, sheer stockings and heels when they suit, alluring and never matronly, fully clothed.',
}

# V3.44.9: hard public decency lock requested by the owner — zero lingerie or
# underwear visibility in outdoor and public-venue photos. The per-level
# underlay rules already forbid exposed underwear; this adds an absolute
# scene-level rule so the model never drags boudoir styling into the street,
# park, cafe, transport, gym etc. Lingerie lives only in private at-home and
# boudoir scenes (and the at-home lingerie look at high relationship levels).
# V3.60.1: at level 6 she still came out in one long maxi dress «как у
# старухи» — from level 3 the outfit keeps her an attractive woman in her 30s.
LEVEL_HEMLINE_RULE = (
    'OUTFIT FIT: no loose ankle-length maxi dresses and no shapeless matronly clothes (unless the season '
    'clearly calls for a coat) — her clothes are fitted and show her figure; length can vary. She dresses '
    'like an attractive, confident woman who wants to be desired. Stockings or sheer tights may be seen only as legwear — never lace tops, '
    'garters or underwear.'
)

PUBLIC_DRESS_RULE = (
    'PUBLIC DRESS CODE: this is a public or outdoor photo, so she is fully and neatly dressed '
    'in attire that is believable for this exact venue, season and time of day — jeans, a dress, '
    'a skirt-and-top, a coat, or a swimsuit at beach/pool settings. NO lingerie as or over the '
    'outfit: no bra, panties, garter belts or slips worn as clothing and no see-through fabric; '
    'her underwear stays under the clothing (at most the outline or a strap her level allows below). '
    'Boudoir/lingerie styling is for private at-home scenes only, never for public places.'
)

# How the underwear under her clothes reads on camera, by relationship level.
# Like real life: she always wears lingerie — and it is there to underline her
# own femininity, confidence and natural sexuality, never to objectify her.
# CRITICAL layering rule: the image model loves to draw named lingerie ON TOP
# of the outfit, so every level explicitly forbids underwear as outerwear;
# visibility grows only as a through-fabric outline/hint, never as a garment
# worn over the clothes.
LEVEL_UNDERLAY_RULES = {
    1: 'Her everyday outfit fully covers her; her lingerie stays completely hidden underneath it, never on top of or outside the outfit — only her natural feminine silhouette reads through the fitted fabric, like a real woman wearing beautiful lingerie under a blouse. No exposure.',
    2: 'Her lingerie stays strictly under the outfit, never on top of it; at most the faint natural outline of her bra reads through the fitted fabric — her underwear quietly emphasizes her natural sexuality and self-confidence without ever being drawn as outerwear.',
    3: 'Her lingerie stays strictly under the outfit, never on top of it; only a subtle bra outline and a hint of a lace edge read through the fitted garment. The lace adds femininity and allure, never vulgarity — the outfit always stays on her.',
    4: 'Her lingerie stays strictly under the outfit, never on top of or outside the outfit; under a tight thin top or tank the outline of her bra (often black) reads through the fabric and one thin bra strap may peek neatly at the shoulder; a delicate lace edge may show at the neckline — elegant sensuality, no exposure.',
    5: 'Her outfit covers her and the lingerie stays underneath, never on top of or outside the outfit; under a tight thin top or tank the outline of her dark bra reads through the fabric and one thin black bra strap peeks neatly at the shoulder — a deliberate, sexy detail, nothing more is visible. Only in a dedicated lingerie/private scene is the lingerie the outfit itself, as directed by the scene framing.',
    6: 'Her outfit covers her and the lingerie stays underneath, never on top of or outside the outfit; under a tight thin top or tank the clear outline of her black bra shows through the fabric and a thin black bra strap slips neatly onto her shoulder — sexy and natural, nothing more is visible. Only in a dedicated lingerie/private scene is the lingerie the outfit itself, as directed by the scene framing.',
}

# V3.56.8: the owner's rooftop shot came back with the lace bra worn OVER the
# blouse — once a prompt names lingerie next to an outfit, Seedream happily
# stacks it outside the clothes. One blunt layering lock rides along in every
# clothed scene; lingerie-as-outfit scenes (nude/home set) skip it.
LINGERIE_LAYERING_LOCK = (
    ' LINGERIE LAYERING LOCK: she wears exactly ONE outer outfit and the lingerie sits BENEATH the '
    'fabric — never draw a bra, lace cups, straps, garters or '
    'panties on top of, outside or over her clothing (a bra outline through a tight top or one thin '
    'strap peeking at the shoulder is fine where her level allows it).'
)

# Private scenes escalate with the relationship level: the same scene reads
# more openly at higher levels. Framing stays non-explicit in every tier.
PRIVATE_SCENE_TIERS = {
    'lingerie': {
        'standard': 'elegant boudoir catalog framing, realistic lace details, soft professional lighting, fabric texture visible',
        'suggestive': 'intimate boudoir framing, sheer robe open, a garter belt and sheer-top stockings with the lace set clearly visible, warm candlelit glow, realistic skin and fabric contrast, soft shadows',
        'revealing': 'professional boudoir lingerie photography, the lace push-up set with garter belt and stockings IS the outfit, sultry warm lamp light, glossy realistic detail, high-end editorial',
    },
    'personal': {
        'standard': 'candid personal boudoir photo, her intimate lace set visible, natural bedroom setting',
        'suggestive': 'a personal intimate moment, her lace set with stockings clearly visible, warm authentic bedroom lamp light, realistic',
        'revealing': 'an intimate boudoir portrait, her lace lingerie set and garter belt in frame, private setting, warm skin tones in low light',
    },
    'private_fashion': {
        'standard': 'fashion editorial framing, lace underwear visible under a sheer blouse, elegant styling',
        'suggestive': 'intimate fashion framing, her lace set visible through realistic sheer fabric, warm boudoir light, authentic feminine form',
        'revealing': 'boudoir-style fashion, her lace set with stockings as the main outfit, sultry low-key lighting, glossy realistic details',
    },
    'nude': {
        'standard': 'tasteful fine-art nude portrait, natural warm lighting, confident relaxed pose',
        'suggestive': 'intimate fine-art nude portrait, soft bedroom lighting, warm tones, elegant composition',
        'revealing': 'confident fine-art nude photography, artistic and personal, private setting',
    },
    'tease': {
        'standard': 'playful teasing pose seen from behind, glance over the shoulder, confident',
        'suggestive': 'sensual from-behind portrait, relaxed and teasing, soft light',
        'revealing': 'confident rear-view artistic composition, teasing and elegant, private setting, warm tones',
    },
}

# Underwear color variety — every photo should have a different lingerie color
# so the wardrobe never feels repetitive. Includes both everyday and elegant tones.
UNDERWEAR_COLOR_POOL = [
    'black', 'white', 'nude beige', 'dusty pink', 'deep red', 'burgundy',
    'navy blue', 'emerald green', 'chocolate brown', 'soft lavender',
    'graphite grey', 'cream ivory', 'rose', 'forest green', 'wine red',
    'powder blue', 'caramel', 'charcoal',
]

# Underwear style variety — everyday pieces plus a boudoir half (V3.43.4
# «добавь градус»: lace push-up sets, garter belts and satin now share the
# private-scene wardrobe with the plain everyday pieces).
UNDERWEAR_STYLE_POOL = [
    'everyday cotton bra and matching panties',
    'smooth microfiber bra and panties',
    'classic smooth bra and briefs',
    'lace-trim bra and matching panties',
    'seamless t-shirt bra and thong',
    'soft bralette and hipster panties',
    'elegant satin bra and high-waist panties',
    'sporty bra and boyshorts',
    'delicate lace bra and Brazilian panties',
    'plunge bra and cheeky panties',
    'balconette bra and matching briefs',
    'wireless comfort bra and full-coverage panties',
    'lace push-up balconette bra and matching panties',
    'garter belt with sheer-top stockings and a lace bra',
    'satin bustier corset and matching panties',
    'plunging lace balconette set with a sheer kimono robe',
    'velvet plunge bra and high-cut panties',
    'longline lace mesh bra and Brazilian panties',
    'strapless lace bandeau set',
    'white bridal lace set with garters',
]

# V3.167.14: 10 уровней сексуальной одежды для режима «Без цензуры 18+».
# Каждый уровень — своя степень обнажения + сексуальные ситуации (дождь, мокрая одежда, вечер).
# Используется только в режиме 18+ (explicit_mode.is_on_for(telegram_id)).
SPICY_OUTFIT_LEVELS = {
    1: 'укороченный топ с открытым животом, короткие шорты, босоножки на каблуках; мокрая от дождя одежда прилипла к телу, волосы мокрые',
    2: 'приоткрытая рубашка (видны ключицы и часть груди), короткая юбка выше колена, чулки без пояса; вечер, неон, лёгкий дождь',
    3: 'глубокое декольте (видна половина груди), короткая юбка с разрезом, туфли на высоких каблуках; мокрая кожа блестит от воды',
    4: 'полупрозрачная блузка без белья (видны соски), короткая юбка, чулки с поясом; дождь, одежда прозрачная от воды',
    5: 'мокрая белая футболка (видно всё под ней), короткие шорты, босиком или босоножки; вечер, волосы мокрые, кожа блестит',
    6: 'только кружевные трусики и полупрозрачный лифчик (грудь почти открыта), чулки с поясом, туфли на каблуках; дождь, мокрая кожа',
    7: 'приспущенные штаны (видны бёдра и часть ягодиц), топ без белья, чулки с поясом, туфли на каблуках; вечер, неон, лёгкая дымка',
    8: 'прозрачное платье без белья (видны соски и контур трусиков), чулки с поясом, туфли на каблуках; дождь, одежда прилипла к телу',
    9: 'только чулки с поясом и кружевные трусики (грудь полностью открыта), туфли на каблуках; мокрая кожа, волосы мокрые, вечер',
    10: 'полностью голая, только туфли на каблуках и чулки с поясом; дождь, мокрая кожа блестит, волосы прилипли к лицу',
}

# V3.167.14: обувь для разнообразия
SHOES_POOL = [
    'высокие каблуки, стройные ноги',
    'кроссовки, спортивный стиль',
    'босоножки на тонких ремешках',
    'ботинки на высокой платформе',
    'туфли-лодочки классические',
    'босиком, естественность',
    'сапоги до колена на каблуке',
    'сандалии на плоской подошве',
]

# V3.167.14: чулки/колготки для разнообразия
STOCKINGS_POOL = [
    'чёрные чулки с поясом',
    'белые кружевные чулки',
    'сетчатые колготки',
    'прозрачные колготки',
    'чулки без пояса, держатся сами',
    'без чулок, голые ноги',
    'чулки в полоску',
    'кружевные чулки с бантиками',
]

# V3.167.14: расширенные аксессуары (часы, кольца, браслеты, серьги)
ACCESSORY_POOL_EXTENDED = [
    'тонкое золотое кольцо на пальце',
    'серебряный браслет на запястье',
    'элегантные часы на руке',
    'серьги-кольца',
    'тонкая цепочка на шее',
    'чокер с кулоном',
    'несколько тонких браслетов',
    'кольцо на большом пальце',
    'серьги-гвоздики',
    'без аксессуаров, минимализм',
    'золотой браслет с гравировкой',
    'серебряная цепочка на шее',
    'часы с кожаным ремешком',
    'серьги с камнями',
    'брошь на одежде',
]

# V3.167.14: расширенная косметика
MAKEUP_POOL_EXTENDED = [
    'яркая красная помада, стрелки',
    'натуральный макияж, блеск для губ',
    'смоки айс, тёмные тени',
    'розовые губы, лёгкий румянец',
    'без макияжа, естественность',
    'блестящие тени, длинные ресницы',
    'матовая помада, контур губ',
    'светлый макияж, акцент на глаза',
    ' nude макияж, естественные тона',
    'вечерний макияж с акцентом на губы',
    'лёгкий макияж с блёстками',
    'дерзкий макияж с чёрными стрелками',
]

# Bust size must never drift between frames or between sets.
# V3.56.8: the rule used to hardcode «very large … E cup» for everybody, which
# stacked on the per-character declaration and inflated every heroine. The size
# itself now comes only from BODY IDENTITY; this rule just pins it against drift
# (and the 'neither larger nor smaller' wording the old static tests expect).
BUST_CONSISTENCY_RULE = (
    'BUST CONSISTENCY: her bust must look exactly the same size in this frame as in every other photo — '
    'the bust size declared in her BODY IDENTITY, neither larger nor smaller, '
    'with the same shape and the same natural fit inside the clothing. '
    'This bust size is a permanent identity trait and OVERRIDES any different bust visible in the reference photos. '
    'If the reference shows another size, IGNORE IT and generate the declared one.'
)

SEASON_RULES = {
    'summer': 'Warm summer weather. Use breathable summer clothing. No sweaters, hoodies, coats, thick knitwear or winter styling unless explicitly requested.',
    'spring': 'Mild spring weather. Use light layers and season-appropriate clothing; avoid heavy winter garments.',
    'autumn': 'Cool autumn weather. Light knitwear, fitted jackets and trousers are believable; avoid summer-only beachwear unless requested.',
    'winter': 'Cold winter weather outdoors. Use fitted season-appropriate layers, coats or knitwear outdoors; indoor venues may use normal fitted outfits.',
}

ANNA_FACE_IDENTITY = (
    'FACE IDENTITY — permanent and non-negotiable. Reference image 1 is the NEW canonical appearance of Anna, '
    'the same fictional adult woman, age 26. Preserve this exact recognizable face: facial proportions, eye shape and spacing, '
    'defined dark eyebrows, refined nose, full lips, cheekbones, jawline, skin tone, and long dark-brown brunette hair. '
    'Do not drift toward any previous Anna reference and never substitute another woman.'
)
ANNA_BODY_IDENTITY = (
    'BODY/LOOK IDENTITY — permanent and non-negotiable. Reference image 2 is the NEW canonical overall look and upper-body silhouette anchor. '
    'Preserve the same slender, fit feminine silhouette with a slim waist and toned figure exactly as shown in the reference. '
    'Anna has a full feminine bust with silicone implants (Russian size 5, E cup) — this bust size is a permanent part of her identity even if the reference shows a smaller one. '
    'Anna has a naturally slim and fit build — this is a core part of her identity. '
    'In plain visual terms her bust is very large, round and lifted (big implants) — the most prominent feature of her figure, never small or medium, exactly the same in every photo. '
    'These proportions are part of Anna\u2019s identity, not a wardrobe effect. Clothing may change, but it must fit the same underlying physique. '
    'Do not add weight, make her thicker, or change her body type. Keep the same slim proportions visible in the canonical reference. '
    'Wardrobe, cafe background, pose and accessories from the reference are not permanent traits unless the requested scene calls for them.'
)
OPENAI_REFERENCE_PROTOCOL = (
    'REFERENCE PROTOCOL: image 1 controls Anna\u2019s exact face and hair identity; image 2 reinforces the same appearance and stable slender silhouette. '
    'The two images depict the same canonical Anna. Anna\u2019s bust is always full (silicone implants, Russian size 5, E cup) regardless of how the reference shows it. '
    'Use requested scene, outfit, hairstyle and camera instructions for everything else. '
    'Never blend in facial traits from legacy references. Always preserve the same slim body proportions from image 2.'
)
# V3.14.1: ordinary-photo prompts intentionally use neutral identity language.
# Legacy regression wording retained: safety must do not flatten, reduce, enlarge identity geometry.
# Sensual/erotic Character DNA belongs to dialogue only and is never injected here.
# The references still preserve Anna's exact appearance without repeatedly naming
# sexualized anatomy in prompts sent to general-audience image providers.
ORDINARY_BODY_IDENTITY = (
    'ORDINARY PHOTO IDENTITY: reference image 2 defines Anna\u2019s exact overall physique, proportions and silhouette. '
    'Preserve the same slim, fit body geometry with a defined waist and feminine figure exactly as shown. '
    'Include Anna\u2019s full bust (silicone implants, Russian size 5, E cup) as a permanent body trait even if the reference shows it smaller; keep the waist slim. '
    'Do not add weight, make her thicker, or change her body type — keep the same slender proportions from the reference. '
    'Clothing changes coverage and styling only; the underlying body identity stays fixed and slim.'
)
ORDINARY_REFERENCE_PROTOCOL = (
    'ORDINARY REFERENCE PROTOCOL: image 1 controls Anna\u2019s exact recognizable face and hair identity; image 2 controls the same overall physique and slim proportions. '
    'Use the requested scene, outfit, hairstyle, pose, camera and lighting for everything else. '
    'Keep the result natural and general-audience but always preserve Anna\u2019s naturally slim and fit figure.'
)
# V3.43.3: the declared figure of every built-in heroine. Until now only Anna
# carried body geometry in her prompts (the blocks above); the new girls got
# face traits plus a generic "consistent feminine physique", so the engine
# re-improvised bust and waist per scene — the owner watched the figure
# "jump" between photos of the same girl. Every identity prompt now names
# the declared figure explicitly, and a DNA json may override it per
# character via visual_identity.body_spec.
# The owner's house archetype used to be ONE size for all («плоских не
# генерировать»). V3.56.8 flipside: after the voluptuous-first rewrite every
# heroine came back with an oversized bust («у всех персонажей очень большая
# грудь»), so the roster is diversified again — C/D/E per girl, no flat frames,
# the softness clause stays. A DNA json may still override via
# visual_identity.body_spec.
BODY_SPECS = {
    'alena_01': 'a curvy athletic hourglass build with a wasp waist, round lifted hips and a natural full bust (silicone, Russian size 4, D cup)',
    'maria_01': 'a voluptuous soft hourglass build with a wasp waist, round lifted wide hips and a full bust (silicone, Russian size 5, E cup)',
    'erika_01': 'a feminine athletic hourglass build with a narrow waist, round lifted hips and a natural modest bust (silicone, Russian size 3, C cup)',
    'sonya_01': 'a feminine fit hourglass build with a narrow waist, round lifted hips and a natural modest bust (silicone, Russian size 3, C cup)',
    'vika_01': 'a curvy athletic hourglass build with a wasp waist, round lifted hips and a natural full bust (silicone, Russian size 4, D cup)',
    'alisa_01': 'a voluptuous fit hourglass build with a wasp waist, round lifted wide hips and a full bust (silicone, Russian size 5, E cup)',
    'mila_01': 'a curvy soft hourglass build with a wasp waist, round lifted hips and a natural full bust (silicone, Russian size 4, D cup)',
    # V3.56.8: the newer heroines used to fall through to the E-cup default —
    # they get declared sizes too.
    'veronika_01': 'a curvy soft hourglass build with a wasp waist, round lifted hips and a natural full bust (silicone, Russian size 4, D cup)',
    'eva_01': 'a feminine fit hourglass build with a narrow waist, round lifted hips and a natural modest bust (silicone, Russian size 3, C cup)',
    'darina_01': 'a feminine soft hourglass build with a narrow waist, round lifted hips and a natural modest bust (silicone, Russian size 3, C cup)',
    'kristina_01': 'a voluptuous soft hourglass build with a wasp waist, round lifted wide hips and a full bust (silicone, Russian size 5, E cup)',
    'romina_01': 'a voluptuous soft hourglass build with a wasp waist, round lifted wide hips and a full bust (silicone, Russian size 5, E cup)',
    'violetta_01': 'a curvy fit hourglass build with a wasp waist, round lifted hips and a natural full bust (silicone, Russian size 4, D cup)',
    'zlata_01': 'a feminine fit hourglass build with a narrow waist, round lifted hips and a natural modest bust (silicone, Russian size 3, C cup)',
    'lera_01': 'a curvy feminine hourglass build with a narrow waist, round lifted hips and a natural full bust (silicone, Russian size 4, D cup)',
    'diana_01': 'a curvy athletic hourglass build with a wasp waist, round lifted hips and a natural full bust (silicone, Russian size 4, D cup)',
    'nika_01': 'a curvy soft hourglass build with a wasp waist, round lifted hips and a natural full bust (silicone, Russian size 4, D cup)',
    'ksyusha_01': 'a petite curvy hourglass build with a narrow waist, round lifted hips and a natural full bust (silicone, Russian size 4, D cup)',
    'margo_01': 'a curvy soft hourglass build with a wasp waist, round lifted hips and a natural full bust (silicone, Russian size 4, D cup)',
    'alya_01': 'a curvy fit hourglass build with a wasp waist, wide round hips, a big round perky butt and a natural full bust (silicone, Russian size 4, D cup)',
    'yuki_01': 'a curvy fit hourglass build with a wasp waist, wide round hips, a big round perky butt and a natural full bust (silicone, Russian size 4, D cup)',
    'miko_01': 'a voluptuous fit hourglass build with a wasp waist, round lifted wide hips and a full bust (silicone, Russian size 5, E cup)',
    'rin_01': 'a curvy fit hourglass build with a wasp waist, wide round hips, a big round perky butt and a natural full bust (silicone, Russian size 4, D cup)',
    'hana_01': 'a very voluptuous soft hourglass build with a narrow waist, a soft belly, very wide round hips, thick soft thighs and an enormous heavy bust (silicone, Russian size 7, F cup)',
    'vlada_01': 'a curvy hourglass build with a narrow waist, round lifted hips and a full bust (silicone, Russian size 4, D cup)',
    'milana_01': 'a very voluptuous hourglass build with a narrow waist, wide round hips and a large full bust (silicone, Russian size 6, F cup)',
    'polina_01': 'a toned tanned hourglass build with a narrow waist, round lifted hips and a natural modest bust (silicone, Russian size 3, C cup)',
    'dasha_01': 'a soft curvy hourglass build with a narrow waist, wide round hips and a very full bust (silicone, Russian size 5, E cup)',
    'kamila_01': 'a curvy hourglass build with a narrow waist, wide round hips and a large full bust (silicone, Russian size 5, E cup)',
    'rita_01': 'a feminine fit hourglass build with a narrow waist, round lifted hips and a natural modest bust (silicone, Russian size 3, C cup)',
    'yulya_01': 'a petite hourglass build with a tiny waist, round full hips and a very large full natural-looking bust (Russian size 6, F cup)',
    'liza_01': 'a curvy hourglass build with a narrow waist, a big round lifted bottom, wide hips, soft thighs and a full natural bust (Russian size 3, C cup)',
    'kira_01': 'a slender toned hourglass build with a tiny waist, a soft flat stomach with a navel piercing, narrow hips, long legs and a medium perky bust (Russian size 2, B cup); fine-line tattoos on the arms, hip and thigh, a butterfly tattoo on the collarbone',
    'agata_01': 'a very voluptuous hourglass build with a tiny cinched waist, wide round hips and a very large full natural-looking bust (Russian size 6, F cup)',
    'jina_01': 'a curvy hourglass build with a narrow waist, round hips, long legs and a full natural bust (D cup)',
    'lana_01': 'an extremely voluptuous hourglass build with a very narrow waist, wide round hips and huge, perfectly round, high and firm augmented silicone breast implants (Russian size 8, H cup)',
    'amira_01': 'a curvy hourglass build with a slim waist, very wide hips, a large round butt and large, full, round and firm augmented silicone breasts',
    'ayla_01': 'a very curvy toned hourglass build with a slim fit waist, wide round hips, toned thighs, a round firm lifted athletic gym-toned butt and a full natural bust (D cup)',
    'priya_01': 'a very curvy toned hourglass build with a slim fit waist, wide round hips, toned thighs, a round firm lifted athletic gym-toned butt and a large full natural bust (E cup)',
}
DEFAULT_FEMALE_BODY_SPEC = (
    'a curvy feminine hourglass build with a wasp waist, round lifted hips '
    'and a natural full bust (silicone, Russian size 4, D cup)'
)
# V3.76.0: anime heroines (owner: «и нужны аниме модели») are drawn, never
# photographed. Their persona JSON says visual_identity.art_style = 'anime';
# every prompt built for them gets this head and loses its realism words.
ANIME_STYLE_HEAD = (
    'ART STYLE (overrides every realism or photo word below): a high-quality 2D anime illustration, '
    'cel-shaded, clean lineart, vibrant colors, detailed painted anime background. The same anime '
    'character as in the reference images, clearly an adult woman with a mature face and adult '
    'proportions. Never a photograph, never photorealistic, never 3D.'
)
# V3.76.0: the card girls («новые девушки») look like the competitor's —
# a polished semi-realistic «drawn photo», not a camera shot and not anime.
SEMI_STYLE_HEAD = (
    'ART STYLE (overrides every realism or photo word below): a polished semi-realistic digital '
    'painting, high-end game CG / 3D-render look, soft cinematic lighting, smooth glowing skin, '
    'realistic adult proportions, detailed painted background. The same character as in the '
    'reference images, clearly an adult woman. Not a camera photo, not flat anime.'
)
_STYLE_HEADS = {'anime': ANIME_STYLE_HEAD, 'semi': SEMI_STYLE_HEAD}
_STYLE_WORD = {'anime': 'anime illustration', 'semi': 'semi-realistic digital painting'}
_REALISM_WORDS = re.compile(
    r'(photo-?realistic|hyper-?realistic|realistic smartphone-style photo|smartphone-style photo|'
    r'realistic smartphone photo|smartphone photo|natural skin texture|natural skin|real photo|'
    r'photorealism|photograph)', re.IGNORECASE)
_ART_STYLE_CACHE: dict[str, str] = {}


def art_style(character_id: str | None) -> str:
    """'anime', 'semi' or 'photo' (custom girls and unknown ids are 'photo')."""
    cid = character_id or ''
    if cid not in _ART_STYLE_CACHE:
        style = 'photo'
        try:
            from services.character_registry import get_character
            style = str((get_character(cid).get('visual_identity') or {}).get('art_style') or 'photo')
        except Exception:
            pass
        _ART_STYLE_CACHE[cid] = style
    return _ART_STYLE_CACHE[cid]


def apply_art_style(prompt: str, character_id: str | None) -> str:
    style = art_style(character_id)
    if style not in _STYLE_HEADS or not prompt:
        return prompt
    return _STYLE_HEADS[style] + '\n' + _REALISM_WORDS.sub(_STYLE_WORD[style], prompt)


# V3.59.3: image models do not know what «Russian size 4 / D cup» looks like,
# so the bust kept drifting between photos of the same girl. Each declared cup
# now also gets a plain visual description the engines do follow.
BUST_VISUALS = {
    'C cup': 'medium-large round natural-looking breasts — clearly full under a fitted top but not big',
    'D cup': 'large round lifted breasts — clearly bigger than average and obvious in any outfit, but not huge',
    'E cup': 'very large round lifted breasts (big implants) — the most prominent feature of her figure in any outfit, never small or medium',
    'F cup': 'huge heavy round breasts (very big implants) — enormous, the first thing anyone sees, far bigger than her head, never medium or merely large',
}


def bust_visual_line(body_spec: str) -> str:
    for cup, visual in BUST_VISUALS.items():
        if cup in (body_spec or ''):
            return f'In plain visual terms her bust is {visual}; exactly this size in every single photo, whatever the pose, outfit or angle. '
    return ''


# V3.60.7: «грудь то больше, то меньше» — the bust rule sat mid-prompt and lost
# to push-up wardrobe words, self-touch poses and the body reference. The last
# lines of a prompt get the most attention, so both pipelines now end with this.
def bust_lock_line(character_id: str) -> str:
    if character_id == 'anna_01':
        body_spec = 'a full bust (silicone, Russian size 5, E cup)'
    else:
        try:
            character = resolve_character(character_id)
        except Exception:
            character = {}
        try:
            from services.character_card_service import get_card
            card = get_card(character_id)
        except Exception:
            card = None
        if card and getattr(card, 'gender', 'female') == 'male':
            return ''
        visual_identity = (character or {}).get('visual_identity', {}) or {}
        body_spec = visual_identity.get('body_spec') or BODY_SPECS.get(character_id, '') or DEFAULT_FEMALE_BODY_SPEC
    cup = next((c for c in BUST_VISUALS if c in body_spec), '')
    if not cup:
        return ''
    return (
        f'BUST LOCK: her bust is exactly {cup} — {BUST_VISUALS[cup]}. '
        'The same size and shape as in every other photo of her: not bigger, not smaller. '
        'Clothing, bra cut, pose, hands or camera angle never change it — no push-up or padding effect, '
        'no squeezed or enlarged look; if a reference image shows another size, ignore it.'
    )


ORDINARY_IDENTITY_LOCK = ANNA_FACE_IDENTITY + ' ' + ORDINARY_BODY_IDENTITY + ' ' + ORDINARY_REFERENCE_PROTOCOL
BODY_REINFORCEMENT = (
    'BODY CONSISTENCY CHECK: keep Anna\u2019s overall physique and proportions visually consistent with reference image 2. '
    'She is naturally slim and fit — do NOT add weight, make her thicker, or change her body type in any pose, angle, clothing or scene. '
    'Her bust stays full and consistent in every scene (silicone implants, Russian size 5, E cup). '
    'Including mirror, seated, athletic, full-body and loose-clothing scenes: preserve the same slender proportions. '
    'Keep anatomy realistic, clothing scene-appropriate and the pose natural.'
)
EXPRESSION_IDENTITY = (
    'EXPRESSION: Anna has a natural warm feminine smile in generated photos. Keep it subtle, relaxed and believable, similar to her canonical references; '
    'avoid a blank stern expression and avoid an exaggerated forced grin or unnaturally wide toothy smile.'
)
OPENAI_IDENTITY_LOCK = ORDINARY_IDENTITY_LOCK


def _duo_identity_line(character_id: str, name: str) -> str:
    """V3.61.0: a constructor duo («две девушки в одном чате») is photographed
    together — both women of her card, side by side."""
    try:
        from services.custom_character_service import is_custom_character, custom_character_params, duo_partner
        if not is_custom_character(character_id):
            return ''
        params, _display = custom_character_params(character_id)
        duo_name, duo_desc = duo_partner(params or {})
    except Exception:
        return ''
    if not duo_name:
        return ''
    return (f' DUO: this persona is TWO adult women — {name} and {duo_name}'
            + (f' ({duo_desc})' if duo_desc else '')
            + '. Show BOTH of them together in the frame, exactly the two women of reference image 1 '
            '(the left/right faces stay the same people), both faces clearly visible; the scene, outfit and pose '
            'apply to both, each keeps her own face and hair.')


def _character_identity_lock(character_id: str, seedream: bool = False, expression_key: str | None = None) -> tuple[str, str, str, str]:
    """Return (identity, personal_note, safety, expression) for a character.

    For Anna the existing reference-based locks are preserved.
    For other characters a generic lock is built from the character card.
    expression_key (from the user's chat mood) overrides the default warm smile
    with an emotion-matched facial expression; None keeps the old behavior.
    """
    from services.photo_expression_service import expression_description
    if character_id == 'anna_01':
        if seedream:
            return (
                SEEDREAM_IDENTITY_LOCK,
                'This is a tasteful adult fashion/glamour photo made specifically to send to someone she is chatting with. '
                'The photo must plausibly be made by Anna herself with the camera propped on a shelf, fixed on a small tripod or set by a countdown timer; no invisible photographer and nothing held in her hands. '
                'Keep the styling polished and personal while remaining non-explicit.',
                'Tasteful adult fashion/editorial styling only. No nudity, no exposed nipples or genitals. '
                'For personal or lingerie scenes, use elegant adult lingerie with opaque garment coverage; preserve identity above styling.',
                expression_description(expression_key, 'Anna') if expression_key else EXPRESSION_IDENTITY,
            )
        return (
            OPENAI_IDENTITY_LOCK,
            'This should feel like a normal personal photo Anna has just taken herself to send to someone she is chatting with. '
            'Every frame must plausibly be made by Anna herself with the camera propped on a shelf, fixed on a small tripod or set by a countdown timer; no invisible photographer and nothing held in her hands. '
            'Use believable smartphone framing and a natural expression. The result should feel Pinterest-like and intentionally styled, '
            'but still like a real personal lifestyle photo rather than a studio glamour shoot.',
            OPENAI_GENERAL_AUDIENCE_BLOCK,
            expression_description(expression_key, 'Anna') if expression_key else EXPRESSION_IDENTITY,
        )

    from services.character_card_service import get_card
    card = get_card(character_id)
    character = resolve_character(character_id)
    # V3.31.8: fall back to the resolved profile (constructor personas carry
    # their display name/age there) instead of leaking the raw character_id.
    name = card.display_name if card else (character.get('name') or character_id)
    try:
        profile_age = int(character.get('age') or 25)
    except (TypeError, ValueError):
        profile_age = 25
    age = card.age if card else profile_age
    gender = card.gender if card else 'female'
    pronoun = 'he' if gender == 'male' else 'she'
    pronoun_cap = 'He' if gender == 'male' else 'She'
    visual_identity = character.get('visual_identity', {})
    preserve = visual_identity.get('preserve_identity', [])
    preserve_text = '; '.join(preserve) if preserve else 'consistent facial features, hair and body proportions'
    figure = (
        'a fit masculine physique with consistent build and proportions'
        if gender == 'male' else
        'a consistent feminine physique, body proportions and silhouette'
    )
    # V3.43.3: the declared figure — without it the engine re-improvises the
    # body per scene and the same girl looks different from photo to photo.
    body_spec = visual_identity.get('body_spec') or BODY_SPECS.get(character_id, '')
    if not body_spec and gender == 'female':
        body_spec = DEFAULT_FEMALE_BODY_SPEC
    # V3.43.5: the declaration must beat the reference images — the owner
    # watched Emily jump between a full and a flat bust because the reference
    # photo won the tug-of-war (Anna's lock already had this override wording).
    body_line = (
        f'BODY IDENTITY: {name} has {body_spec}. This declared figure is a permanent body trait '
        'and OVERRIDES the reference images: even if a reference photo shows a smaller or flatter '
        'bust or a different build, always render the declared figure exactly as stated. '
        f'{bust_visual_line(body_spec)}'
        'Preserve this exact figure in every photo regardless of outfit, pose or crop; '
        'never flatten, reduce or enlarge the bust, never widen the waist. '
        'Her torso stays soft and feminine — never render visible abdominal muscles, a toned gym '
        'torso or a boyish athletic frame. '
    ) if body_spec else ''
    # V3.43.6: references are scoped to the FACE — the preserve list used to
    # drag the body off the reference photos too («fit feminine physique»),
    # and the reference's smaller bust beat the declared figure frame after
    # frame (the owner watched Emily render size 2 against a size-5 card).
    reference_protocol = (
        f'REFERENCE PROTOCOL: the canonical reference images define {name}\'s face, hairstyle, '
        'coloring and recognizable identity ONLY; her body measurements, bust size and figure '
        'come exclusively from the BODY IDENTITY declaration, never from the reference photos. '
    ) if body_spec else ''
    identity = (
        f'PHOTO IDENTITY: Create the SAME fictional adult {gender} character, {name}, age {age}. '
        f'Identity preservation is the highest priority. Preserve these exact traits from the canonical references: {preserve_text}. '
        f'{reference_protocol}'
        f'{pronoun_cap} is the same person across all photos. Preserve {figure}. '
        f'{body_line}'
        f'Do not substitute another person, do not change age or ethnicity. '
        f'Use the requested scene, outfit, pose, camera and lighting for everything else.'
    )
    identity += _duo_identity_line(character_id, name)
    personal = (
        f'This should feel like a normal personal photo {name} has just taken to send to someone {pronoun} is chatting with. '
        f'Every frame must plausibly be made by {pronoun} with the camera propped on a shelf, fixed on a small tripod or set by a countdown timer; no invisible photographer, and both hands stay free. '
        f'Use believable smartphone framing and a natural expression. Keep it natural and lifestyle-like.'
    )
    safety = (
        'Mainstream general-audience lifestyle photograph. The person remains fully clothed in opaque, scene-appropriate clothing. '
        'Use a natural everyday pose and composition centered on the person, outfit and environment. '
        'The image should read as an everyday social-media or personal travel/lifestyle photo.'
    )
    expression = expression_description(expression_key, name)
    return identity, personal, safety, expression


SEEDREAM_IDENTITY_LOCK = (
    'The supplied reference defines Anna\u2019s NEW permanent canonical identity. Create the SAME fictional adult woman, Anna, age 26. '
    'Identity preservation has absolute priority. Preserve the exact face, eye shape and spacing, dark defined eyebrows, refined nose, full lips, cheekbones, jawline, '
    'warm light-to-medium skin tone, long dark-brown brunette hair, and the same slim, fit feminine proportions visible in the supplied canonical reference. '
    'Anna has a full bust with silicone implants (Russian size 5, E cup) as a permanent trait even if the reference shows it smaller. '
    'In plain visual terms her bust is very large, round and lifted (big implants), exactly the same size in every photo. '
    'Do not drift back to any previous Anna face, do not substitute another woman, and do not add weight or change her body type.'
)
BODY_REINFORCEMENT_SCENES = {'mirror', 'gym', 'cafe', 'restaurant', 'home', 'outfit', 'selfie'}

QUALITY_BLOCK = (
    'Photorealistic smartphone/lifestyle photography, authentic candid amateur photo feel, realistic skin texture with natural pores and micro-imperfections, '
    'realistic fabric texture and clothing wrinkles, realistic hands and anatomy, natural hair strands, coherent perspective, '
    'premium photographic detail, soft cinematic realism, shallow depth of field where appropriate. '
    'Absolutely no CGI, 3D render, doll-like or airbrushed look.'
)
OPENAI_GENERAL_AUDIENCE_BLOCK = (
    'Mainstream general-audience lifestyle photograph. Anna remains fully clothed in opaque, scene-appropriate clothing. '
    'Use a natural everyday pose and composition centered on the person, outfit and environment. Avoid glamour or suggestive posing. '
    'Preserve the same person, slim proportions and fit figure from the references. Do not add weight or change her body type. '
    'The image should read as an everyday social-media or personal travel/lifestyle photo, not boudoir photography.'
)
# V3.166.12 (владелец: «просто убери телефон… всё, селфи-рамки»): the third arm
# was the selfie arm. A frame that says «she holds the phone» makes the engine
# draw a shoulder reaching to the viewer ON TOP OF the two posed hands, so the
# handheld framing is gone everywhere: the camera always sits outside her body
# and both hands stay free.
HANDS_RULE = (
    'HANDS: she has exactly two arms and two hands, both naturally attached to her own shoulders — '
    'never a third hand, a third arm or a disembodied hand. Both hands do only what the pose says: if one '
    'hand is at her lips or in her hair, the other rests on her lap, her hip or the bed — it never adds a '
    'second gesture and never reaches toward the viewer. Count the arms before finishing: exactly two.'
)
NEGATIVE_BLOCK = (
    'Avoid identity drift, generic doll-like face, plastic skin, asymmetrical eyes, warped hands, extra fingers, '
    'a third hand or arm, more than two hands, '
    'duplicate limbs, distorted anatomy, text, watermark, random accessories, overprocessed beauty filters, '
    'a long fully protruding or extra tongue, fake plastic-looking tongue, deformed mouth interior, teeth clipping through lips, '
    'and underwear worn over the outfit: bra over the top, panties over jeans or any lingerie as outerwear.'
)
# V3.166.12: the head line of every frame — the camera is never in her hand.
# Written without the words the rewriter below replaces, so it survives its own
# pass, and registered as a last-trimmed tier in private_photo_service._SPICY_TIERS.
NO_PHONE_LOCK = (
    'NO HANDHELD CAMERA: this photo was not taken by her hand. No device and no camera appear anywhere in the '
    'picture, neither in a hand nor in a mirror, and no hand or arm reaches toward the viewer. The shot comes '
    'from outside her body: the camera was leaned on a shelf, propped on a stack of books, fixed on a small '
    'tripod or set by a countdown timer. Her two arms end at her own shoulders and both hands are free to pose.'
)
# Every bank that still describes a handheld shot — scene lines, the angle
# pools, her own live-situation sentences, gift and story frames, and the text
# the LLM writes for a paid frame — is rewritten here instead of in a hundred
# string literals, so a phrase nobody remembered cannot grow a third arm.
_NO_PHONE_PHRASES = (
    (r'first[- ]person phone selfie', 'photo from a camera propped nearby'),
    (r'phone POV selfie angle', 'camera propped at eye level'),
    (r'front[- ]camera selfie at arm[’\']s length', 'photo from a camera propped at eye level'),
    (r'selfie at arm[’\']s length', 'photo from a camera propped at eye level'),
    (r'phone held at arm[’\']s length in one hand', 'both hands free'),
    (r'both hands holding a phone or a cup', 'both hands holding a cup'),
    (r'(?:one hand|her other hand|a hand) holds (?:the|her) phone(?: low at [^.]{1,30}height)?(?: at (?:eye level|arm[’\']s length))?',
     'one hand rests at her side'),
    (r'(?:holding|holds) the phone above her face(?: with one hand)?', 'her head turned to the camera'),
    (r'she holds the phone herself or ', ''),
    (r'keep exactly one phone in her own hand', 'keep both her hands empty'),
    (r'phone visible in her hand', 'both hands visible and empty'),
    (r'phone in (?:one|her) hand', 'both hands free'),
    (r'phone in hand', 'both hands free'),
    (r'\(if she is holding a phone, it is the other hand[^)]*\)', ''),
    (r'front[- ]camera selfie', 'photo from a propped camera'),
    (r'\bhandheld\b', 'propped'),
    (r'\bselfies\b', 'photos'),
    (r'\bselfie\b', 'photo'),
    # leftovers of the rewrites above: no adjective of a device may survive.
    (r'\bher free hand\b', 'one hand'),
    (r'\bphone\s+(?=photo\b|snap\b|portrait\b|picture\b|shot\b)', ''),
    (r'(?<![a-z])phone\s+(?=[a-z]+\s+(?:photo|shot|picture)\b)', ''),
    # the same wording arrives in Russian from the SPA scene request: the engine
    # only reads English, but a stray «селфи» still grows the arm it describes.
    (r'телефон(?:ом)?\s+в\s+(?:её|ее)?\s*рук[а-я]*', 'both hands free'),
    (r'селфи', 'фото'),
)
_NO_PHONE_LEFTOVER = re.compile(
    r'[^,;.]*(?:\bselfie\b|POV|arm[’\']s length|holds? (?:the|her) phone|holding (?:the|her) phone'
    r'|\bphone\b|селфи|телефон[^,;]*рук[а-я]*|держит[^,;]*телефон)[^,;.]*[,;.]*',
    re.IGNORECASE)
# Two head lines may not be pushed down by the lock: without the duo line the
# engine draws one girl, without the private-place line lingerie lands in the
# office. The lock sits behind them and in front of everything else.
# V3.167.2: the paid «Раздеть» edit joins them — the frame must stay the frame.
# V3.167.4: and so does its place — «тот же кадр без исключений», ни в какую
# спальню публичный кадр больше не переносится.
_NO_PHONE_HEAD_KEEP = ('TWO WOMEN IN FRAME:', 'PRIVATE PLACE OVERRIDE:', 'SAME FRAME LOCK:',
                       'SAME PLACE LOCK:')


def no_phone_frame(prompt: str) -> str:
    """Selfie-free prompt: rewrite the handheld wording, then put the lock first."""
    text = (prompt or '').strip()
    if not text or NO_PHONE_LOCK in text:
        return text
    for pattern, replacement in _NO_PHONE_PHRASES:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    # a phrase the table missed never reaches the engine as an instruction —
    # the clause carrying it is dropped, the lock already says how the frame
    # is shot.
    text = _NO_PHONE_LEFTOVER.sub('', text)
    lines = text.split('\n')
    keep = 0
    while keep < len(lines) and lines[keep].startswith(_NO_PHONE_HEAD_KEEP):
        keep += 1
    return '\n'.join(lines[:keep] + [NO_PHONE_LOCK] + lines[keep:])


# ── V3.152.1: owner ТЗ (Задачи 3, 4, 5) — три жёстких замка промпта ────────
#
# All three sit at the START of the IMAGE_PROMPT on purpose. SpicyAPI takes
# SPICYAPI_PROMPT_MAX characters and _fit_spicy_prompt eats the tail first, so
# a rule that rides at the end is a rule the provider may never read — that is
# exactly how «Вдвоём» kept rendering one girl (the guest block was the last
# line) and why lingerie kept landing in bars. Their prefixes are registered as
# the last-trimmed tier in _SPICY_TIERS (private_photo_service).

AMATEUR_HOT_FRAME_LOCK = (
    'AMATEUR HOT FRAME: this is a real candid photo of herself, not a photoshoot. '
    'Her camera was leaned against the wall, propped on a shelf or set by a countdown timer, so it sits outside '
    'the frame and both her hands are free. The framing is slightly off, '
    'one corner of the room cut off. The room behind her is lived-in and a little messy — clothes on the chair, '
    'an unmade bed, a towel on the floor. Intimate low warm light from a lamp or a window, real skin with pores '
    'and soft shadows, nothing retouched. '
    'Never: a professional photoshoot, studio lighting, a posed editorial frame, an artificial or symmetrical '
    'portrait, high-fashion styling, a photographer\u2019s camera or a clean seamless backdrop. '
    'Her face stays fully visible and recognizable from the references.'
)

# V3.166.5 (владелец, багфикс стартовых кадров): его скрин — сценарий про ванну,
# а в кадре ванна посреди спальни с неразобранной кроватью и разбросанными
# вещами. Три источника перебивали её обещанный кадр: база сцены «lingerie»
# (будуар, кружевное бельё, атласный халат), суточный контекст в строке локации
# и эта аматорская блокировка с «an unmade bed». Для стартового кадра все три
# выключены: место, одежда и поза берутся ТОЛЬКО из image_prompt сценария.
# Префиксы зарегистрированы в последнем снимаемом слое _SPICY_TIERS.
STARTER_FRAME_LOCK = (
    'STARTER FRAME: this is the exact frame she promised him in her very first message, so the scene line '
    'above IS the setting and nothing else describes the room. No bed, no bedroom, no wardrobe, no furniture '
    'and no mess appears in the picture unless the scene line names it; her usual day context, her usual room '
    'and the generic boudoir look do not apply to this frame. Her face, hair, bust and body stay exactly as '
    'locked above.'
)
STARTER_AMATEUR_LOCK = (
    'AMATEUR HOT FRAME: this is a real candid photo of herself, not a photoshoot. Amateur '
    'framing from a camera propped on a shelf or a countdown timer, slightly off center, one corner of the room '
    'cut off, intimate low warm light from a lamp or a '
    'window, real skin with pores and soft shadows, nothing retouched. The room behind her is exactly the '
    'place the scene line names and nothing more. Never: a professional photoshoot, studio lighting, a posed '
    'editorial frame, an artificial or symmetrical portrait, high-fashion styling, a photographer\u2019s camera '
    'or a clean seamless backdrop. Her face stays fully visible and recognizable from the references.'
)
# Офис и машина из её сценариев не могут остаться публичными местами — на этом
# стоп-кадре модерация отказывает, и раньше сервер выкидывал случайную комнату
# из PRIVATE_PLACES, то есть снова спальню. Теперь предмет её фразы сохраняется,
# а приватной становится сама обстановка.
STARTER_PRIVATE_PLACE = (
    'PRIVATE PLACE OVERRIDE: she is undressed or in lingerie, so nobody but her can see her in this frame. '
    'Keep the place and the object she named in the scene line, but make them private: an office desk becomes '
    'her own home desk in her apartment at night, a car becomes her own car, parked, doors closed, nobody '
    'outside. Never move her into a bedroom with a bed unless her own scene line already named a bed. No '
    'colleagues, passers-by, windows of other offices or public interiors in the picture.'
)
STARTER_WARDROBE = (
    'exactly what her own scene line above describes and nothing else — where it names water, foam, sheets or '
    'a blanket, that is the garment of the frame; no boudoir lace set, no garter belt, no stockings, no satin '
    'robe unless her scene line names them'
)

DUO_TRAITS_MAX = 6
DUO_TRAITS_CHARS = 240
# Traits that talk about the references instead of her face — useless in a
# description of the second woman, who is not the subject of those references.
_TRAITS_META = ('canonical', 'reference', 'approved', 'same person', 'identity')


def _appearance_traits_en(character_id: str) -> str:
    """Her look in plain English, for a two-women frame.

    V3.152.1: profiles are read from disk and a heroine without a JSON file
    used to raise FileNotFoundError — a missing file must never kill a paid
    photo, so every failure here collapses to a generic descriptor."""
    traits: list[str] = []
    try:
        visual = (resolve_character(character_id) or {}).get('visual_identity') or {}
        traits = [str(t).strip() for t in (visual.get('preserve_identity') or []) if str(t).strip()]
    except Exception:
        traits = []
    readable = [t for t in traits if not any(w in t.lower() for w in _TRAITS_META)][:DUO_TRAITS_MAX]
    text = '; '.join(readable)
    if len(text) > DUO_TRAITS_CHARS:
        cut = text[:DUO_TRAITS_CHARS]
        text = cut[:cut.rfind(',')] if ',' in cut else cut
    return text or 'an adult woman with her own face, hair and figure'


def duo_head_lock(character_id: str, guest_id: str) -> str:
    """V3.152.1 (Задача 3): the first line of a duo IMAGE_PROMPT declares TWO
    women and names both looks. The identity lock below it is singular by
    nature («the SAME fictional adult woman»), so without this head the engine
    drew only the host however carefully the guest was described further down."""
    host_name = _character_display_name_safe(character_id)
    guest_name = _character_display_name_safe(guest_id)
    return (
        'TWO WOMEN IN FRAME: two girls together, interacting, two women in frame. '
        f'Two girls together. Girl 1: {host_name}, {_appearance_traits_en(character_id)}. '
        f'Girl 2: {guest_name}, {_appearance_traits_en(guest_id)}. '
        'Both of them are inside this one photo, close together and interacting: a shoulder touch, one leaning on '
        'the other, a shared laugh, both faces visible. Never one woman alone in the frame, never a merged face, '
        'never a third person; each keeps her own face, hair and figure.'
    )

# Задача 5: the intimate look and a public venue do not belong in one photo.
PRIVATE_PLACES = ('her bedroom', 'her bathroom', 'her apartment', 'a hotel room')

INTIMATE_LOOK = re.compile(
    r'\b(lingerie|bra|bras|bralette|panties|underwear|thong|garter belt|garters|nude|naked|topless|'
    r'breasts|nipples|areola\w*|genitals?|buttocks|ass|bare skin|bare shoulders|no bra|braless|'
    r'without (any )?clothes|no clothing|undressed|boudoir|see[- ]through|sheer|robe falling open)\b', re.I
)
# Warnings about lingerie she does NOT show (the dress code, the layering
# lock, the negative list) — they name lingerie while the frame stays clothed.
_UNDERLAYER_NOISE = re.compile(
    r'as outerwear|worn over|over (her|the) (outfit|clothing|jeans|top)|under[- ]layer|beneath (her|the) '
    r'(outfit|clothing|fabric)|no lingerie|stays under|never draw a bra|public dress code|'
    r'lingerie layering lock|clothed|fully dressed|general[- ]audience|styling is for|never for public|'
    r'at[- ]home scenes only|is fine where her level allows', re.I
)
# His own words, and only his own: an explicit wish to be shown where other
# people can see her is exhibition, and exhibition is what he asked for.
EXHIBITION_WISH = re.compile(
    r'(публично|эксгибицион\w*|на\s+людях|в\s+людн\w*|при\s+людях|в\s+(окне|туалете|уборной)'
    r'|пока[зж]\w*.{0,40}(улиц|людн|публичн|офис|бар|клуб|транспорт|маршрутк|автобус|такс|машин|парк|магазин'
    r'|примерочн|раздевал|ресторан|каф|пляж|бассейн|спортзал|метро|лестниц|подъезд|окно|балкон)'
    r'|сним\w*.{0,30}(улиц|людн|публичн|в\s+(баре|клубе|офисе|такс|машин))'
    r'|exhibit\w*|exhibition\w*|in public|people (can|could) see|on the street|somewhere public)', re.I
)
# Public venues named in the prompt text — the English scene words plus the
# Russian day-context leaks («location=офис»). Detection only: cutting a venue
# out of a finished sentence wrecks the grammar, so the place is overridden by
# PRIVATE_PLACE_OVERRIDE instead of being rewritten in place. Fitting/changing
# rooms are deliberately NOT listed — a mall fitting room is still caught
# through «mall», and the private «changing_room» scene keeps its own name.
PUBLIC_VENUE = re.compile(
    r'\b(night ?club|club|bar|pub|bistro|caf[eé]|coffee shop|restaurant|canteen|mall|shopping cent(er|re)'
    r'|boutique|store|shop|street|sidewalk|avenue|park|town square|embankment|beach|seaside|swimming pool|pool'
    r'|yacht|bridge|festival|concert|cinema|theater|theatre|rooftop|terrace|balcony|staircase|stairwell|elevator'
    r'|lobby|subway|metro|bus|trolleybus|tram|train|taxi|car park|gym|fitness club|locker room|sauna|airport'
    r'|station|platform|classroom|office|workplace|conference room|boardroom|meeting room|open space|university'
    r'|campus|library|market|queue|night street|dance floor|bar counter)\b'
    r'|\b(клуб[аеыу]?|бар[аеыу]?|баре|паб[аеыу]?|кафе|кафешк\w*|кафетери\w*|ресторан\w*|офис\w*|\bработ[аыеуе]\w*'
    r'|совещани\w*|коридор\w*|переговорк\w*|улиц\w*|парк[ауе]?|парке|сквер\w*|площадк\w*|набережн\w*|торговый центр'
    r'|тц|магазин\w*|бутик\w*|маршрутк\w*|автобус\w*|троллейбус\w*|трамва\w*|метро|поезд\w*|вагон\w*|такс[ииуя]\w*'
    r'|машин[аыеу]\b|спортзал\w*|фитнес\w*|бассейн\w*|пляж\w*|берег[ауе]|берега|берегу|береге|кинотеатр\w*|концерт\w*'
    r'|фестивал\w*|вечеринк\w*|подъезд\w*|лестниц\w*|лифт\w*|аэропорт\w*|вокзал\w*|балкон\w*|террас\w*|аудитор\w*'
    r'|лектори\w*|университет\w*|универ\w*|кафедра|библиотек\w*|рынк\w*|банкетн\w* зал|танцпол)\b', re.I)

PRIVATE_PLACE_OVERRIDE = (
    'PRIVATE PLACE OVERRIDE: she wears only lingerie (or nothing) in this frame, so this photo is NOT taken '
    'in a public venue. The real setting is {place}; the time of day, the light and the mood stay as described. '
    'Nobody but her is in the room and no bystanders are visible. Treat any public venue word below as a mistake: '
    '{place} wins over any bar, club, restaurant, street, office, mall, gym or transport. '
    'Never depict a lingerie or undressed look where other people can see her.'
)

# V3.166.7 (владелец, «локация берётся ИСКЛЮЧИТЕЛЬНО из того, что скажет LLM»):
# маркер в строке локации значит, что комнату уже назвали её же слова — выдумывать
# спальню из PRIVATE_PLACES нельзя. Закрытой становится та же обстановка, а
# «никого в комнате» меняется на того, кого анкета сама пустила в эту комнату.
CARD_PLACE = re.compile(r'PLACE FROM HER MESSAGE:\s*([^\n]+)', re.I)
CARD_TOGETHER = re.compile(r'in the same room:\s*([^;\n.]+)', re.I)
# Место без стен и без двери: запереться в нём нельзя, поэтому оно по-прежнему
# уводится внутрь (старое поведение) — иначе стоп-кадр с ней на улице в белье.
OPEN_AIR_VENUE = re.compile(
    r'\b(street|sidewalk|avenue|road|park|square|plaza|promenade|embankment|beach|shore|seaside|rooftop'
    r'|balcony|terrace|courtyard|yard|garden|market|queue|dance floor|subway|metro|bus|trolleybus|tram'
    r'|train|platform|station|airport|taxi|parking|car park|pool|lake)\b', re.I)

# Комната за дверью уже названа её словами — «примерочная», «ванная», «душ»,
# «кабина»: переносить её в выдуманную спальню не за чем, кадр и так приватный.
ALREADY_PRIVATE = re.compile(
    r'\b(fitting|dressing|cloak)\s+room|\b(bathroom|bathtub|restroom|toilet|shower|locker\s+room|sauna'
    r'|booth|cabin|bedroom|bed|wardrobe)\b'
    r'|(примерочн\w*|раздевалк\w*|ванн[аойе]|душ|туалет[ае]?|кабин[аыуе]?|спальн\w*|кровать|гардеробн\w*)', re.I)

CARD_PRIVATE_OVERRIDE = (
    'PRIVATE PLACE OVERRIDE: she wears only lingerie (or nothing) in this frame, so this photo is NOT taken '
    'where other people can see her. The place her own words named — {place} — stays that very place: shoot '
    'the frame in its closed private room behind a shut door (a fitting room, a bathroom, a private booth, '
    'an empty back room), never in another building and never in a bedroom her words did not name. The '
    'interior, the light and the objects still belong to {place}. {people}'
    'Treat any open, shared area of this venue as a mistake: the closed room of the same venue wins.'
)
CARD_PRIVATE_ALONE = 'Nobody but her is in the room and no bystanders are visible. '
CARD_PRIVATE_WITH = '{who} is the only other person in that room; no crowd and no bystanders. '


def _intimate_prompt_text(prompt: str) -> bool:
    """Is she showing skin in this prompt? Boilerplate that only forbids
    lingerie (dress codes, layering locks, negative lists) is skipped, so a
    fully clothed photo of a bar never counts as an intimate frame."""
    for sentence in re.split(r'(?<=[.!?])\s+', prompt or ''):
        if not sentence or _UNDERLAYER_NOISE.search(sentence):
            continue
        if INTIMATE_LOOK.search(sentence):
            return True
    return False


def wants_public_exposure(text: str) -> bool:
    return bool(EXHIBITION_WISH.search(text or ''))


def enforce_private_location(prompt: str, user_text: str = '', *, intimate: bool | None = None,
                             starter: bool = False) -> str:
    """V3.152.1 (Задача 5): lingerie or nudity and a public venue cannot share
    one photo — unless he himself asked for the exhibition. An intimate frame
    gets its venue moved into a closed room, and the rule is put in front of
    the prompt so the SpicyAPI tail trimming can never reach it.

    V3.166.5 (владелец): a starter frame never gets a random room — the place
    she promised in her own first line wins, and only a genuinely public venue
    in it is pulled inside her apartment (STARTER_PRIVATE_PLACE keeps the desk
    or the car, so a bathtub scenario stops landing in a bedroom).

    V3.166.7 (владелец): when her own words already named the room — the card
    marker in the location line — no random bedroom is invented on top of it.
    A room that has walls keeps its venue and only gets its door shut; a place
    without walls still moves inside. Whoever the card put in the room stays
    there instead of the blanket «nobody but her»."""
    if not prompt:
        return prompt
    if intimate is None:
        intimate = _intimate_prompt_text(prompt)
    if not intimate or wants_public_exposure(user_text):
        return prompt
    if starter:
        return f'{STARTER_PRIVATE_PLACE}\n{prompt}'
    card = CARD_PLACE.search(prompt)
    if card:
        place = card.group(1).strip()
        # Её слова уже назвали комнату за дверью — спорить с ними не за чем.
        if not PUBLIC_VENUE.search(place) or ALREADY_PRIVATE.search(place):
            return prompt
        if OPEN_AIR_VENUE.search(place):
            return f'{PRIVATE_PLACE_OVERRIDE.format(place=random.choice(PRIVATE_PLACES))}\n{prompt}'
        together = CARD_TOGETHER.search(place)
        people = (CARD_PRIVATE_WITH.format(who=together.group(1).strip()) if together
                  else CARD_PRIVATE_ALONE)
        return f'{CARD_PRIVATE_OVERRIDE.format(place=place, people=people)}\n{prompt}'
    if not PUBLIC_VENUE.search(prompt):
        return prompt
    place = random.choice(PRIVATE_PLACES)
    return f'{PRIVATE_PLACE_OVERRIDE.format(place=place)}\n{prompt}'


@dataclass(frozen=True)
class GeneratedPhoto:
    url: Optional[str] = None
    data: Optional[bytes] = None
    provider: str = 'openai'
    estimated_cost_usd: float = 0.0


@dataclass(frozen=True)
class PhotoRequest:
    scene: str = 'selfie'
    clothing: str = ''
    hairstyle: str = ''
    hair_color: str = ''
    makeup: str = ''
    location: str = ''
    angle: str = ''
    mood: str = 'warm, natural'
    expression_key: str | None = None  # facial expression from chat mood (smile/upset/concerned/teasing)
    # V3.31.7: per-frame variety rotations, shuffled in _resolve_request. When
    # the chat mood pins no expression, frame i takes expression_rotation[i];
    # pose_rotation[i] adds a distinct posture note per frame so no two photos
    # of a pack share the same mimicry or the same pose.
    expression_rotation: tuple[str, ...] = ()
    pose_rotation: tuple[str, ...] = ()
    season: str = ''
    accessory: str = ''
    time_of_day: str = ''
    pack_outfits: tuple[str, ...] = ()
    customized: bool = False
    underwear_color: str = ''
    underwear_style: str = ''
    # V3.59.7: a small in-frame hint of her relationship status (ring, his hoodie).
    story_detail: str = ''
    # V3.61.2: «сфоткайтесь вдвоём» — the girl invited into this chat shares the frame.
    with_guest: str = ''
    # V3.116.0: today's garment he gave her («👗 Надеть сегодня») — wins over the
    # level-5+ at-home lingerie rule and the community pool.
    gift_outfit: bool = False
    # V3.166.4 (Блок 2, owner): the hidden English frame of a greeting scenario.
    # He never reads it — it is what the generator is told when he taps the chip
    # under her opening line, and it outranks the improvised wardrobe of that
    # one frame while her identity locks stay on top.
    starter_note: str = ''


AppPhotoDelivery = Callable[[bytes, str, int, str], Awaitable[None]]


class PhotoAppDeliveryError(RuntimeError):
    pass


class PhotoGenerationError(RuntimeError):
    def __init__(self, provider: str, reason: str):
        self.provider = provider
        self.reason = reason
        super().__init__(f'{provider}: {reason}')


def _today():
    return datetime.now(timezone.utc).date()


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _user_rel(session, telegram_id: int, character_id: str = CHARACTER_ID):
    user = session.scalar(select(User).where(User.telegram_id == str(telegram_id)))
    if not user:
        return None, None
    rel = session.scalar(select(UserCharacterRelationship).where(
        UserCharacterRelationship.user_id == user.id,
        UserCharacterRelationship.character_id == character_id,
    ))
    return user, rel


def get_relationship_stage(telegram_id: int, character_id: str = CHARACTER_ID) -> str:
    override = get_test_stage(telegram_id, character_id)
    if override:
        return override
    ensure_user(telegram_id)
    with SessionLocal() as session:
        _, rel = _user_rel(session, telegram_id, character_id)
        return rel.stage if rel else 'stranger'


def get_relationship_level(telegram_id: int, character_id: str = CHARACTER_ID) -> int:
    return STAGE_INDEX.get(get_relationship_stage(telegram_id, character_id), 0) + 1


def get_daily_limit(telegram_id: int, character_id: str = CHARACTER_ID) -> int:
    level = get_relationship_level(telegram_id, character_id)
    return FREE_PHOTOS_LEVEL_3_6 if level >= 3 else FREE_PHOTOS_LEVEL_1_2


def get_usage(telegram_id: int, character_id: str = CHARACTER_ID):
    uid = ensure_user(telegram_id)
    with SessionLocal() as session:
        row = session.scalar(select(PhotoDailyUsage).where(
            PhotoDailyUsage.user_id == uid,
            PhotoDailyUsage.character_id == character_id,
            PhotoDailyUsage.usage_date == _today(),
        ))
        limit = get_daily_limit(telegram_id, character_id)
        return (row.free_used if row else 0, row.paid_used if row else 0, limit)


def has_free_photo(telegram_id: int, character_id: str = CHARACTER_ID) -> bool:
    used, _, limit = get_usage(telegram_id, character_id)
    return used < limit


def scenes_open_in_explicit_mode(telegram_id) -> bool:
    """V3.167.7 (владелец, скрин 16.11): «в режиме без цензуры открой все кнопки».
    Аккаунт, выбравший «Без цензуры 18+», не упирается в лесенку уровней — как
    и с Premium, уровень здесь ничего не прячет. Цена кадра, 18+ и Premium
    остаются там, где были."""
    if not telegram_id:
        return False
    try:
        from services import explicit_mode
        return explicit_mode.is_on_for(telegram_id)
    except Exception:
        return False


def scene_allowed_for_stage(scene: str, stage: str, telegram_id=None) -> bool:
    if SCENE_LEVELS.get(scene) is not None and scenes_open_in_explicit_mode(telegram_id):
        return True
    return STAGE_INDEX.get(stage, 0) + 1 >= SCENE_LEVELS.get(scene, 99)


def is_custom_request(request: PhotoRequest) -> bool:
    return request.scene in {'lingerie', 'private_fashion', 'nude', 'tease'} or bool(request.customized)


def requires_adult_confirmation(request: PhotoRequest) -> bool:
    return request.scene in {'lingerie', 'private_fashion', 'nude', 'tease'} or bool(INTIMATE_STYLE.search(' '.join([request.clothing, request.location, request.angle])))


# V3.87.0: owner — «давать столько персиков бесплатно, чтобы не хватало на фото
# голой / в белье, и вести на Premium». Free peaches pile up (welcome + channel
# + promo + daily missions ≈ 2 700 🍑 on day one, +200 🍑 every day), so no
# peach price holds the line: nude / lingerie / boudoir photos are Premium-only.
PREMIUM_SPICY_SCENES = frozenset(SEEDREAM_ADULT_SCENES | ADULT_SCENES)


def spicy_needs_premium(request: PhotoRequest) -> bool:
    """A nude / lingerie / boudoir photo — Premium-only (V3.87.0)."""
    return request.scene in PREMIUM_SPICY_SCENES or requires_adult_confirmation(request)


def build_photo_menu(telegram_id: int, character_id: str = CHARACTER_ID):
    used, paid, limit = get_usage(telegram_id, character_id)
    return {
        'stage': get_relationship_stage(telegram_id, character_id),
        'level': get_relationship_level(telegram_id, character_id),
        'free_used': used,
        'paid_used': paid,
        'limit': limit,
        'free_left': max(0, limit - used),
        'credits': get_photo_credits(telegram_id),
        'cost': PHOTO_COST_STARS,
        'premium': is_premium(telegram_id),
        'adult_confirmed': is_adult_confirmed(telegram_id),
        'set_size': PHOTO_SET_SIZE,
    }


def create_offer(telegram_id: int, request: PhotoRequest, ttl_minutes: int = 30):
    uid = ensure_user(telegram_id)
    payload = json.dumps(request.__dict__, ensure_ascii=False)
    with SessionLocal() as session:
        offer = PhotoOffer(
            user_id=uid,
            character_id=CHARACTER_ID,
            scene=request.scene,
            request_json=payload,
            created_at=_now(),
            expires_at=_now() + timedelta(minutes=ttl_minutes),
        )
        session.add(offer)
        session.commit()
        return offer.id


def consume_offer(telegram_id: int, offer_id: int):
    uid = ensure_user(telegram_id)
    with SessionLocal() as session:
        offer = session.scalar(select(PhotoOffer).where(
            PhotoOffer.id == offer_id,
            PhotoOffer.user_id == uid,
            PhotoOffer.character_id == CHARACTER_ID,
        ))
        if not offer or offer.consumed or offer.expires_at < _now():
            return None
        offer.consumed = True
        session.commit()
        if offer.request_json:
            try:
                return PhotoRequest(**json.loads(offer.request_json))
            except Exception:
                logger.exception('failed to decode photo offer id=%s', offer_id)
        return PhotoRequest(scene=offer.scene)


def _lingerie_clothing(low: str) -> str:
    color = 'black'
    if re.search(r'\bбел(?:ое|ом|ый|ая|ую|ого|ые|ых)\b', low) or re.search(r'\bwhite\b', low):
        color = 'white'
    elif 'красн' in low or re.search(r'\bred\b', low):
        color = 'burgundy red'
    elif 'розов' in low or re.search(r'\bpink\b', low):
        color = 'soft pink'
    base = f'{color} elegant lingerie fashion set with opaque coverage and polished catalog styling'
    if 'чулк' in low or 'stocking' in low:
        base += ', with matching thigh-high stockings'
    return base


def _season_from_text(low: str) -> str:
    if any(x in low for x in ('лето', 'летом', 'summer', 'жарко', 'жара')):
        return 'summer'
    if any(x in low for x in ('весна', 'весной', 'spring')):
        return 'spring'
    if any(x in low for x in ('осень', 'осенью', 'autumn', 'fall')):
        return 'autumn'
    if any(x in low for x in ('зима', 'зимой', 'winter', 'снег')):
        return 'winter'
    return ''


TOGETHER_PHOTO = re.compile(r'(вдво[её]м|вместе|обе\b|обеих|совместн|сфоткайтесь|сфотайтесь|с подругой|together|both of you)', re.I)


def attach_guest(request: Optional[PhotoRequest], telegram_id: int, character_id: str, text: str) -> Optional[PhotoRequest]:
    """V3.61.2: a photo request that asks for both girls («сфоткайтесь вдвоём»,
    «фото с Викой») renders the invited guest into the same frame."""
    if not request:
        return request
    try:
        from services.chat_guest_service import get_guest, character_name
        guest_id = get_guest(telegram_id, character_id)
    except Exception:
        return request
    if not guest_id:
        return request
    low = (text or '').lower()
    name = (character_name(guest_id) or '').lower()
    stem = name[:-1] if len(name) > 3 else name
    if TOGETHER_PHOTO.search(low) or (stem and stem in low):
        return replace(request, with_guest=guest_id)
    return request


def parse_photo_request(text: str) -> Optional[PhotoRequest]:
    t = (text or '').strip()
    low = t.lower()
    request_verbs = (
        'сфоткай', 'сфотай', 'сфотограф', 'фоткни', 'сделай фото', 'пришли фото', 'пришли фотку', 'покажи себя', 'покажись',
        'сними себя', 'селфи', 'сфоткайтесь', 'сфотайтесь', 'совместное фото', 'совместную фот', 'фото вдвоём', 'фото вдвоем', 'фото вместе', 'take a photo', 'take a pic', 'send me a photo', 'send a pic', 'show me a photo', 'show yourself', 'show me yourself', 'selfie',
        '拍照', '自拍', '发张照片', '给我看看你',
    )
    direct = (
        any(x in low for x in request_verbs)
        or bool(re.match(r'^\s*(?:фото|фотку|photo|pic)\b', low))
        or bool(re.search(r'\b(?:сделай|пришли|дай|хочу|покажи|скинь|кинь|скинешь|скинуть|отправь|вышли|кидай|жду)\b.{0,45}\b(?:фото|фотку|фоточку|фотографию|фотки|фоточки|селфи|селфач)\b', low))
        or bool(re.search(r'\b(?:make|send|take|want|show)\b.{0,45}\b(?:photo|pic|selfie|picture)\b', low))
    )
    if not direct:
        return None

    season = _season_from_text(low)
    if SAFE_EXPLICIT.search(low):
        # Adult scenes are level-gated at 6 and require 18+ confirmation. If the
        # user is not yet at that level, scene_allowed_for_stage will reject it.
        if REAR_VIEW_STYLE.search(low):
            return PhotoRequest(scene='tease', season=season)
        return PhotoRequest(scene='nude', season=season)

    scene = 'selfie'
    clothing = ''
    angle = ''

    # Natural rear-view requests are normalized to a fully clothed, non-explicit
    # personal fashion composition. The provider safety checker stays enabled.
    if REAR_VIEW_STYLE.search(low):
        scene = 'personal'
        angle = 'tasteful rear three-quarter personal fashion view, fully clothed, with recognizable profile visible when natural'
    elif INTIMATE_STYLE.search(low):
        scene = 'lingerie'
        clothing = _lingerie_clothing(low)
    elif any(x in low for x in ('клуб', 'nightclub', 'club')):
        scene = 'club'
    elif any(x in low for x in ('караоке', 'karaoke')):
        scene = 'karaoke'
    elif any(x in low for x in ('бар', 'bar ')):
        scene = 'bar'
    elif any(x in low for x in ('крыша', 'rooftop')):
        scene = 'rooftop'
    elif any(x in low for x in ('ресторан', 'restaurant')):
        scene = 'restaurant'
    elif any(x in low for x in ('кино', 'cinema', 'movie')):
        scene = 'cinema'
    elif any(x in low for x in ('набереж', 'embankment', 'riverwalk')):
        scene = 'embankment'
    elif any(x in low for x in ('магазин', 'торгов', 'бутик', 'shop', 'mall')):
        scene = 'shop'
    elif any(x in low for x in ('зал', 'тренаж', 'трениров', 'фитнес', 'gym', 'workout', 'fitness')):
        scene = 'gym'
    elif any(x in low for x in ('машин', 'авто', 'car')):
        scene = 'car'
    elif any(x in low for x in ('парк', 'park')):
        scene = 'park'
    elif any(x in low for x in ('улиц', 'street', 'город')):
        scene = 'street'
    elif any(x in low for x in ('кафе', 'кофе', 'cafe', 'coffee')):
        scene = 'cafe'
    elif any(x in low for x in ('зеркал', 'mirror')):
        scene = 'mirror'
    elif any(x in low for x in ('дома', 'домаш', 'кровать', 'диван', 'спальн', 'at home')):
        scene = 'home'
    elif any(x in low for x in ('личное фото', 'личный кадр', 'только для меня', 'специально для меня', 'personal photo')):
        scene = 'personal'
    elif any(x in low for x in ('вечер', 'evening')):
        scene = 'evening'
    elif any(x in low for x in ('образ', 'наряд', 'одета', 'одежд', 'плать', 'джинс', 'леггинс', 'outfit', 'dress')):
        scene = 'outfit'

    if not clothing:
        clothing_map = [
            ('черн', 'a black figure-flattering fully clothed outfit'), ('white', 'a white figure-flattering fully clothed outfit'),
            ('бел', 'a white figure-flattering fully clothed outfit'), ('красн', 'a burgundy red figure-flattering fully clothed outfit'),
            ('плать', 'a fitted elegant dress with normal coverage'), ('dress', 'a fitted elegant dress with normal coverage'),
            ('шорт', 'high-waisted tailored shorts with a fitted casual top'), ('shorts', 'high-waisted tailored shorts with a fitted casual top'),
            ('брюк', 'tailored high-waisted trousers with a fitted top'), ('trousers', 'tailored high-waisted trousers with a fitted top'),
            ('джинс', 'high-waisted jeans with a fitted casual top'), ('jeans', 'high-waisted jeans with a fitted casual top'),
            ('леггинс', 'opaque leggings with a fitted casual top'), ('leggings', 'opaque leggings with a fitted casual top'),
            ('водолаз', 'a fitted turtleneck sweater'), ('майк', 'a fitted tank top with normal coverage'), ('топ', 'a fitted fashion top with normal coverage'),
        ]
        for key, value in clothing_map:
            if key in low:
                clothing = value
                break

    hairstyle = ''
    if any(x in low for x in ('кос', 'braid')):
        hairstyle = 'a long braid falling down her back'
    elif any(x in low for x in ('хвост', 'ponytail')):
        hairstyle = 'a sleek high ponytail'
    elif any(x in low for x in ('пучок', 'bun')):
        hairstyle = 'a neat high bun'
    elif any(x in low for x in ('распущ', 'волнист', 'loose hair', 'waves')):
        hairstyle = 'long loose softly wavy hair'

    if not angle:
        if any(x in low for x in ('со спины', 'сзади', 'back view', 'from behind')):
            angle = 'back three-quarter view while keeping her recognizable profile when visible'
        elif any(x in low for x in ('сбоку', 'профиль', 'side view')):
            angle = 'side three-quarter view'
        elif any(x in low for x in ('сверху', 'верхний ракурс', 'high angle')):
            angle = 'slightly high-angle smartphone selfie'
        elif 'полный рост' in low or 'full body' in low:
            angle = 'full-body framing'

    location = ''
    if 'диван' in low or 'sofa' in low:
        location = 'a tidy modern living room with a sofa'
    elif 'спальн' in low or 'bedroom' in low:
        location = 'a tasteful modern bedroom with soft daylight'
    elif 'отел' in low or 'hotel' in low:
        location = 'a tasteful modern hotel room'

    rear_auto = bool(REAR_VIEW_STYLE.search(low))
    customized = bool(clothing or hairstyle or location or (angle and not rear_auto))
    return PhotoRequest(scene=scene, clothing=clothing, hairstyle=hairstyle, location=location, angle=angle, season=season, customized=customized,
                        time_of_day=_time_from_text(low))


def _reference_folder(character: dict) -> Path:
    identity = character.get('visual_identity', {})
    return Path(__file__).resolve().parents[1] / identity.get('reference_folder', 'data/references/anna')


def _reference_path(character: dict, scene: str) -> Path:
    """Backward-compatible single reference fallback."""
    return _openai_reference_paths(character, scene)[0]


def _openai_reference_paths(character: dict, scene: str, *, safe: bool = False) -> tuple[Path, ...]:
    """Return ordered GPT Image references: face first, body second.

    GPT Image 2 supports multiple source images. Keeping face and body anchors separate
    prevents ordinary lifestyle safety/styling instructions from silently averaging
    Anna into a generic physique.
    """
    folder = _reference_folder(character)
    identity = character.get('visual_identity', {})
    configured_face = str(identity.get('openai_face_anchor') or '').strip()
    secondary_identity = str(identity.get('openai_secondary_identity_anchor') or '').strip()
    face_candidates = tuple(name for name in (
        configured_face,
        '00_anna_canonical_face_v3.png',
        secondary_identity,
        '01_anna_canonical_look_v3.png',
    ) if name)
    face = next((folder / name for name in face_candidates if (folder / name).exists()), None)

    # Provider-specific anchors are intentionally separate.  Ordinary GPT Image
    # edits receive a fully-clothed body silhouette reference; the more revealing
    # canonical artwork is retained for private/Seedream workflows and must not
    # be injected into every general-audience request.
    configured_body = str(identity.get('openai_body_anchor') or '').strip()
    configured_safe_body = str(identity.get('openai_safe_body_anchor') or '').strip()
    body_candidates = tuple(name for name in (
        configured_safe_body if safe else configured_body,
        '01_anna_canonical_look_v3.png',
    ) if name)
    body = next((folder / name for name in body_candidates if (folder / name).exists()), None)
    if not face and not body:
        raise FileNotFoundError('Нет доступных reference-фото персонажа')
    refs: list[Path] = []
    if face:
        refs.append(face)
    if body and body != face:
        refs.append(body)
    return tuple(refs)


def _seedream_reference_path(character: dict) -> Path:
    folder = _reference_folder(character)
    identity = character.get('visual_identity', {})
    configured = str(identity.get('seedream_identity_anchor') or '').strip()
    for candidate in tuple(name for name in (configured, '01_anna_canonical_look_v3.png', '00_anna_canonical_face_v3.png') if name):
        p = folder / candidate
        if p.exists():
            return p
    raise FileNotFoundError('Нет canonical reference персонажа для Seedream')


# ── V3.31.8: constructor personas in the photo pipeline ────────────────────
# Custom characters have no data/characters/<id>.json, so the registry lookup
# crashed the whole photo job with FileNotFoundError — a date/photo request
# from a constructor persona died instead of showing the girl the user built.
# resolve_character() synthesizes a real identity profile from the constructor
# row (name/age/appearance) and anchors it on the avatar that was generated
# (and, when provided, face-swapped) at construction time.

def _custom_reference_dir(character_id: str) -> Path:
    return Path(__file__).resolve().parents[1] / 'data' / 'custom_references' / character_id


def _custom_character_profile(character_id: str) -> dict | None:
    """Synthesized character profile for a constructor persona (or None)."""
    base = custom_base_character(character_id)
    if base is None:
        return None
    params, _name = custom_character_params(character_id)
    # V3.44.7: scope preserve_identity to FACE/HAIR/COLORING only — the body
    # follows the declared BODY IDENTITY (body_spec), never the reference avatar.
    # Previously the preserve list dragged the body from the reference photos
    # and the bust/waist/hips drifted between generations.
    preserve = custom_appearance_descriptors(params)
    # Remove body/figure descriptors from preserve — they belong in body_spec
    preserve = [d for d in preserve if not any(k in d for k in ('figure', 'bust', 'waist', 'hips', 'body'))]
    hair_color = custom_hair_color(params)
    if hair_color:
        preserve.append(f'{hair_color} hair color')
    preserve.append('the exact same face as the canonical avatar reference')
    # V3.44.7: body_spec from constructor params — the BODY IDENTITY declaration
    # that overrides the reference avatar's body shape.
    body_spec = custom_body_spec(params)
    return {
        **base,
        'visual_identity': {
            'reference_folder': f'data/custom_references/{character_id}',
            'openai_face_anchor': 'avatar.jpg',
            'openai_body_anchor': 'avatar.jpg',
            'openai_safe_body_anchor': 'avatar.jpg',
            'openai_secondary_identity_anchor': 'avatar.jpg',
            'seedream_identity_anchor': 'avatar.jpg',
            'seedream_body_anchor': 'avatar.jpg',
            'preserve_identity': preserve,
            'body_spec': body_spec,
        },
    }


def resolve_character(character_id: str) -> dict:
    """Character profile for prompts: constructor personas resolve to their own
    synthesized identity; built-in ids read the registry JSON as before."""
    if is_custom_character(character_id):
        profile = _custom_character_profile(character_id)
        if profile is not None:
            return profile
    return get_character(character_id)


async def ensure_custom_avatar_cached(bot, character_id: str) -> Path | None:
    """Make sure the persona's avatar image exists on disk for reference-based
    generation. The constructor stores the avatar as a Telegram file_id; here
    it is downloaded once into data/custom_references/<id>/ and reused until
    the persona is rebuilt (a new file_id re-downloads automatically).
    """
    row = get_custom_character_by_id(character_id)
    if not row:
        return None
    folder = _custom_reference_dir(character_id)
    target = folder / 'avatar.jpg'
    marker = folder / 'avatar.file_id'
    if row.avatar_file_id:
        try:
            cached_id = marker.read_text(encoding='utf-8').strip() if marker.exists() else ''
        except OSError:
            cached_id = ''
        if target.exists() and cached_id == row.avatar_file_id:
            return target
        try:
            data = await bot.download(row.avatar_file_id)
            payload = data.read() if hasattr(data, 'read') else bytes(data)
        except Exception:
            logger.exception('custom avatar download failed character=%s', character_id)
            return target if target.exists() else None
        if not payload:
            return target if target.exists() else None
        try:
            folder.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            marker.write_text(row.avatar_file_id, encoding='utf-8')
        except OSError:
            logger.exception('custom avatar cache write failed character=%s', character_id)
            return None
        return target
    # V3.44.12: the persona was saved without an avatar (providers were down
    # at creation). Draw it now from her constructor params — the first photo
    # request heals her instead of failing forever.
    if target.exists():
        return target
    try:
        params, _name = custom_character_params(character_id)
        avatar_bytes, _mime = await generate_custom_avatar(build_avatar_prompt(params))
        folder.mkdir(parents=True, exist_ok=True)
        target.write_bytes(avatar_bytes)
        marker.write_text('generated-on-demand', encoding='utf-8')
        logger.info('custom avatar drawn on demand character=%s', character_id)
        return target
    except Exception:
        logger.exception('lazy custom avatar generation failed character=%s', character_id)
        return None


# ── V3.19.0: custom character constructor avatar ─────────────────────────

async def generate_custom_avatar(prompt: str, reference_path: Path | None = None) -> tuple[bytes, str]:
    """Generate a constructor avatar as (jpeg_bytes, mime).

    Seedream with a user face reference acts as face-swap (identity anchor);
    without a reference it creates a fresh identity. Gemini image generation
    is the fallback route when fal.ai is unavailable or fails.
    """
    # V3.25.0: _seedream_edit/_gemini_edit below are the real engines; the
    # face reference makes Seedream act as a face-swap identity anchor.
    # V3.40.0: every engine attempt bumps the provider counters, so the admin
    # «Отказы» screen shows which leg of the chain is flaky.
    # V3.44.3: accumulate the whole chain — the studio toast must show WHY
    # every engine failed, not just the last one.
    chain_errors: list[str] = []
    # V3.64.5: owner's call «вообще все генерации через Spicy» — fal is off
    # for good (dead since 15.10). Without a reference the avatar/studio frame
    # is a fictional girl and renders on SpicyAPI text-to-image. A reference
    # here is a user's real uploaded photo: that one never goes to the
    # uncensored engine and stays on the censored Gemini edit.
    if reference_path is None:
        from services.private_photo_service import generate_private_photo_t2i
        data = await generate_private_photo_t2i(
            prompt + '\nHARD SUBJECT LOCK: a fictional adult woman (21+). Never depict minors.'
        )
        record_provider('photo/spicyapi_t2i', bool(data))
        if data:
            return data, 'image/jpeg'
        from services.private_photo_service import spicyapi_last_error
        raise PhotoGenerationError('custom_avatar', f'spicyapi_t2i/{spicyapi_last_error() or "empty_result"}')
    if gemini_on_cooldown():
        chain_errors.append('gemini/skipped: http_429 cooldown')
        raise PhotoGenerationError('custom_avatar', ' → '.join(chain_errors))
    try:
        result = await _gemini_edit(prompt, reference_path)
        record_provider('photo/gemini', True)
        return result
    except Exception as exc:
        record_provider('photo/gemini', False, f'{type(exc).__name__}: {str(exc)[:120]}')
        chain_errors.append(f'gemini/{type(exc).__name__}: {str(exc)[:120]}')
        raise PhotoGenerationError('custom_avatar', ' → '.join(chain_errors)) from exc


async def _seedream_t2i(prompt: str, allow_adult: bool = False) -> tuple[bytes, str]:
    """V3.39.0: Seedream text-to-image for freeform prompts (no reference).

    V3.43.1: routed to the dedicated text-to-image endpoint — the edit
    endpoint validates ``image_urls`` as a non-empty sequence and answers
    HTTP 422 to a reference-free studio prompt.

    V3.45.23: ``allow_adult`` disables fal's safety checker so the uncensored
    «Наедине»/nude leg can actually return an image instead of failing.
    """
    result = await _seedream_request(
        prompt, [], 1, request_label='studio_picture', allow_adult=allow_adult,
        model=FAL_MODEL_T2I,
    )
    images = result.get('images') if isinstance(result, dict) else None
    url = images[0].get('url') if images and isinstance(images[0], dict) else None
    if not url:
        raise PhotoGenerationError('seedream45', 'no_image_url')
    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=20.0), follow_redirects=True) as client:
        download = await client.get(url)
    if download.status_code >= 400 or not download.content:
        raise PhotoGenerationError('seedream45', f'download_{download.status_code}')
    return download.content, download.headers.get('content-type', 'image/jpeg')


async def _seedream_edit(reference_path: Path | None, prompt: str) -> tuple[bytes, str]:
    """V3.25.0: constructor face-swap via Seedream edit (user face = anchor)."""
    if not FAL_KEY:
        raise PhotoGenerationError('seedream45', 'FAL_KEY is not configured')
    if not (reference_path and reference_path.exists()):
        raise PhotoGenerationError('seedream45', 'no_face_reference')
    result = await _seedream_request(
        prompt, [_file_data_uri(reference_path)], 1,
        request_label='constructor_avatar', allow_adult=False,
    )
    images = result.get('images') if isinstance(result, dict) else None
    url = images[0].get('url') if images and isinstance(images[0], dict) else None
    if not url:
        raise PhotoGenerationError('seedream45', 'no_image_url')
    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=20.0), follow_redirects=True) as client:
        download = await client.get(url)
    if download.status_code >= 400 or not download.content:
        raise PhotoGenerationError('seedream45', f'download_{download.status_code}')
    return download.content, download.headers.get('content-type', 'image/jpeg')


# V3.58.1: Gemini image answers HTTP 429 (quota exhausted) for hours at a
# time — the owner's «Отказы» screen showed 0 ✅ / 29 ❌. Every studio render
# then paid a wasted round-trip and a ❌. After a 429 the leg is skipped for
# GEMINI_429_COOLDOWN_SECONDS.
GEMINI_429_COOLDOWN_SECONDS = 1800
_gemini_cooldown_until = 0.0


def gemini_on_cooldown() -> bool:
    return time.monotonic() < _gemini_cooldown_until


async def _gemini_edit(prompt: str, reference_path: Path | None = None) -> tuple[bytes, str]:
    """V3.25.0: constructor avatar via Gemini image (text-to-image, optional face ref)."""
    global _gemini_cooldown_until
    if not GEMINI_API_KEY or not GEMINI_IMAGE_ENABLED:
        raise PhotoGenerationError('gemini_image', 'not_configured')
    parts: list[dict] = [{'text': prompt + '\nPhotorealistic portrait of one person, natural skin, soft studio light.'}]
    if reference_path and reference_path.exists():
        data, mime = _image_b64(reference_path)
        parts.append({'inline_data': {'mime_type': mime, 'data': data}})
    payload = {'contents': [{'parts': parts}], 'generationConfig': {'responseModalities': ['IMAGE']}}
    headers = {'x-goog-api-key': GEMINI_API_KEY, 'Content-Type': 'application/json'}
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=20.0)) as client:
        response = await client.post(
            f'{GEMINI_VIDEO_BASE_URL}/models/{GEMINI_IMAGE_MODEL}:generateContent',
            headers=headers, json=payload,
        )
    if response.status_code >= 400:
        logger.warning('constructor avatar Gemini HTTP %s body=%s', response.status_code, response.text[:400])
        if response.status_code == 429:
            _gemini_cooldown_until = time.monotonic() + GEMINI_429_COOLDOWN_SECONDS
        raise PhotoGenerationError('gemini_image', f'http_{response.status_code}')
    # V3.44.18: the call is billed from here on, even if no image comes back.
    spend_service.record_image_spend('gemini_image', 'constructor_avatar', GEMINI_IMAGE_ESTIMATED_COST_USD)
    data = response.json()
    for part in ((data.get('candidates') or [{}])[0].get('content') or {}).get('parts') or []:
        inline = part.get('inlineData') or part.get('inline_data') or {}
        if inline.get('data'):
            return base64.b64decode(inline['data']), inline.get('mimeType') or inline.get('mime_type') or 'image/png'
    raise PhotoGenerationError('gemini_image', 'no_image')


def _pick_nonrepeat(options: list[str], previous: str | None) -> str:
    usable = [x for x in options if not previous or x.strip().lower() != previous.strip().lower()]
    return random.choice(usable or options)


def _default_season() -> str:
    month = datetime.now(timezone.utc).month
    if month in (12, 1, 2):
        return 'winter'
    if month in (3, 4, 5):
        return 'spring'
    if month in (6, 7, 8):
        return 'summer'
    return 'autumn'


def _photo_style(character_id: str) -> dict:
    """Character-specific styling metadata from visual_identity.photo_style.

    Returns per-character hair colors, hairstyles and wardrobe when available;
    an empty dict for characters without dedicated styling (Anna, custom
    personas) so the caller falls through to the generic shared pools.
    """
    try:
        character = resolve_character(character_id)
        return character.get('visual_identity', {}).get('photo_style', {}) or {}
    except Exception:
        return {}


def _wardrobe_pool(scene: str, level: int, season: str, *, character_id: str = '') -> list[str]:
    group = SCENE_GROUP.get(scene, 'day_casual')
    level = max(1, min(6, int(level)))
    # V3.43.8: character-specific wardrobe from photo_style when available.
    # Each built-in heroine now has her own age-appropriate outfits; the
    # generic level pools remain the fallback for Anna, custom personas and
    # scene groups without character entries (adult/lingerie).
    if character_id and group != 'adult':
        style = _photo_style(character_id)
        char_wardrobe = style.get('wardrobe', {})
        if group in char_wardrobe:
            # V3.61.10: her three signature outfits alone repeated the same
            # navy dress in every level-1 selfie — the generic level pool joins
            # them so a week of photos shows a real wardrobe.
            # V3.64.0: a heroine with `wardrobe_exclusive` (Erika) keeps only
            # her own modern pieces — the generic turtleneck/knit pool made her
            # look matronly («как у бабки», owner).
            if style.get('wardrobe_exclusive'):
                return list(char_wardrobe[group])
            extra =[x for x in WARDROBE_LEVEL_POOLS.get(group, {}).get(level, []) if x not in char_wardrobe[group]]
            return list(char_wardrobe[group]) + extra
    pool = list(WARDROBE_LEVEL_POOLS[group][level])

    # Outdoor summer scenes must never accidentally get winter styling.
    # The explicit pool already uses summer garments; for other groups we filter
    # obvious heavy pieces when the requested scene is visibly warm-season.
    if season == 'summer' and group != 'adult':
        bad = ('hoodie', 'coat', 'thick knit', 'heavy knit', 'sweater')
        filtered = [x for x in pool if not any(word in x.lower() for word in bad)]
        if filtered:
            pool = filtered
    return pool


def _json_list(raw: str | None) -> list[str]:
    try:
        value = json.loads(raw or '[]')
        return [str(x) for x in value] if isinstance(value, list) else []
    except Exception:
        return []


def _ordinary_style_request(request: PhotoRequest, relationship_level: int) -> bool:
    """Style continuity only, never a change to intimate-photo routing/pools."""
    if request.scene not in SCENES or request.scene in (
        SEEDREAM_ADULT_SCENES | ADULT_SCENES | {'peek', 'dressing'}
    ) or request.starter_note or request.with_guest:
        return False
    if request.scene in HOME_LINGERIE_SCENES and relationship_level >= 5 and not request.gift_outfit:
        return False
    details = ' '.join((request.clothing, request.location, request.angle, request.mood,
                        request.story_detail, *request.pack_outfits, *request.pose_rotation))
    return not (INTIMATE_STYLE.search(details) or re.search(
        r'\b(nud\w*|naked|undress\w*|topless|explicit|erotic\w*|sensual|sexy|sheer|see-through|'
        r'гол\w*|обнаж\w*|раздет\w*|раздень\w*|эрот\w*)\b', details, re.I))


def _ordinary_hairstyle(character_id: str, style: dict) -> str:
    """Stable character list + UTC three-day step; history cannot reshuffle it."""
    options = style.get('hairstyles') or []
    options = options if isinstance(options, (list, tuple)) else []
    pool = []
    seen = set()
    try:
        visual = resolve_character(character_id).get('visual_identity') or {}
        identity = ' '.join(visual.get('preserve_identity') or [])
    except Exception:
        identity = ''
    short_hair = re.search(r'\b(bob|pixie|short hair|cropped hair)\b|коротк\w* волос', identity, re.I)
    for option in options:
        if not isinstance(option, str) or not option.strip():
            continue
        option = option.strip()
        if short_hair and re.search(r'\b(long|ponytail|braid\w*|plaits?|bun|chignon)\b', option, re.I):
            continue
        if option.casefold() not in seen:
            pool.append(option)
            seen.add(option.casefold())
    # No generic long-hair/updo pool for an unknown or short canonical cut.
    if not pool:
        pool = ['hair styled with a natural side part',
                'hair softly brushed back at its existing length']
    period = (_today() - datetime(2026, 1, 1, tzinfo=timezone.utc).date()).days // 3
    offset = int(hashlib.md5(character_id.encode()).hexdigest(), 16)
    chosen = pool[(offset + period) % len(pool)]
    return f'{chosen}; preserve the canonical hair length and cut from the identity references'


def _outfit_history_key(outfit: str) -> str:
    # Strip only our generated color suffix, including legacy rows with shoes
    # appended after it. Garment colors inside the original outfit stay intact.
    return re.split(r'\s+in a\s+[^,;]+?\s+(?:color|tone)(?=$|[,;])',
                    ' '.join(outfit.split()).casefold(), maxsplit=1)[0]


def _ordinary_pose_rotation(telegram_id: int, character_id: str) -> tuple[str, ...]:
    uid = ensure_user(telegram_id)
    with SessionLocal() as session:
        # Rows/bytes are created before delivery. Count app frames only after
        # the callback persisted them; failed attempts must not advance poses.
        app_delivered = select(ProductEvent.id).where(
            ProductEvent.user_id == uid, ProductEvent.character_id == character_id,
            ProductEvent.event_name == 'photo_app_delivered',
            ProductEvent.value == PhotoDelivery.id,
        ).exists()
        telegram_delivered = (PhotoDelivery.telegram_file_id.isnot(None)
                              & (PhotoDelivery.telegram_file_id != ''))
        delivered = session.scalar(select(func.count(PhotoDelivery.id)).where(
            PhotoDelivery.user_id == uid, PhotoDelivery.character_id == character_id,
            telegram_delivered | app_delivered,
        )) or 0
    start = delivered % len(POSE_POOL)
    return tuple(POSE_POOL[start:] + POSE_POOL[:start])


def _choose_progression_outfits(telegram_id: int, request: PhotoRequest, season: str, *, character_id: str = CHARACTER_ID, ordinary_style: bool | None = None) -> tuple[str, ...]:
    if request.clothing:
        return tuple(request.clothing for _ in range(PHOTO_SET_SIZE))
    state = get_state(telegram_id, character_id=character_id)
    level = get_relationship_level(telegram_id, character_id)
    if ordinary_style is None:
        ordinary_style = _ordinary_style_request(request, level)
    pool = _wardrobe_pool(request.scene, level, season, character_id=character_id)
    uid = ensure_user(telegram_id)
    visual_prefs = get_visual_preferences(uid, character_id)
    color_counts = visual_prefs.get('colors', {}) if isinstance(visual_prefs, dict) else {}
    favorite_color = max(color_counts, key=color_counts.get) if color_counts and max(color_counts.values()) >= 2 else ''
    # V3.43.8: character-specific outfits already include coordinated garment
    # colors, so appending another color would contradict them. The generic
    # fallback pool still gets per-frame color diversity as before.
    style = _photo_style(character_id)
    group = SCENE_GROUP.get(request.scene, 'day_casual')
    has_char_wardrobe = bool(style.get('wardrobe', {}).get(group))
    picks: list[str] = []
    history_key = _outfit_history_key if ordinary_style else lambda x: x.strip().lower()
    recent = {history_key(x) for x in _json_list(getattr(state, 'recent_outfits_json', '[]'))}
    if state.outfit:
        recent.add(history_key(state.outfit))
    for i in range(PHOTO_SET_SIZE):
        picked = {history_key(x) for x in picks}
        unused = [x for x in pool if history_key(x) not in picked] if ordinary_style else [x for x in pool if x not in picks]
        usable = [x for x in unused if history_key(x) not in recent]
        if not usable:
            usable = unused or pool
        chosen = random.choice(usable)
        if not has_char_wardrobe:
            # Generic pool: color diversity per frame as before.
            if favorite_color and 'orange' not in favorite_color.lower() and i == 0 \
                    and SCENE_GROUP.get(request.scene) != 'adult' and random.random() < 0.35:
                chosen = f'{chosen} in a {favorite_color} tone'
            else:
                color_key = (telegram_id, character_id) if ordinary_style else telegram_id
                recent_colors = _recent_outfit_colors.setdefault(color_key, [])
                color_pool = [c for c in OUTFIT_COLOR_POOL if c not in recent_colors] or list(OUTFIT_COLOR_POOL)
                color = random.choice(color_pool)
                recent_colors.append(color)
                del recent_colors[:-3]
                chosen = f'{chosen} in a {color} color'
        picks.append(chosen)
    return tuple(picks)


PASSION_PATH_THRESHOLD = 20.0  # the card's «Раскрепощённая» label starts here


def _path_is_passion(telegram_id: int, character_id: str) -> bool:
    try:
        from services.relationship_engine import get_path_axis
        return get_path_axis(ensure_user(telegram_id), character_id) >= PASSION_PATH_THRESHOLD
    except Exception:
        return False


TENDER_PATH_THRESHOLD = -20.0  # mirror of PASSION_PATH_THRESHOLD


def _path_is_tender(telegram_id: int, character_id: str) -> bool:
    try:
        from services.relationship_engine import get_path_axis
        return get_path_axis(ensure_user(telegram_id), character_id) <= TENDER_PATH_THRESHOLD
    except Exception:
        return False


def _persona_style_is_tender(telegram_id: int, character_id: str) -> bool:
    # V3.55.6: the «tender» manner chosen in the premium character's app chat
    # softens the photo expression pool too. Fail-silent: any doubt -> False.
    try:
        from sqlalchemy import select
        from services.db import SessionLocal
        from models.relationship_models import UserCharacterRelationship
        uid = ensure_user(telegram_id)
        with SessionLocal() as session:
            style = session.scalar(
                select(UserCharacterRelationship.persona_style).where(
                    UserCharacterRelationship.user_id == uid,
                    UserCharacterRelationship.character_id == character_id,
                )
            )
        return style == 'tender'
    except Exception:
        return False


# V3.59.7: the relationship status the user picked shows up as small details in
# the frame — never the face or the figure. `always` rides every photo, `sometimes`
# roughly every third one so the hint stays a hint.
MARITAL_PHOTO_DETAIL = {
    'mar_married': {
        'always': 'a thin gold wedding ring on her left ring finger',
        'sometimes': ("a quiet hint that she is home alone while her husband is away — a man's shirt "
                      'hanging on a chair or his watch on the nightstand, no man in the frame'),
    },
    'mar_boyfriend': {
        'always': '',
        'sometimes': "she wears her boyfriend's oversized hoodie or T-shirt, a little too big for her",
    },
    # V3.134.0: she married the user / left her man for him.
    'mar_wife': {
        'always': 'a thin gold wedding ring next to a delicate engagement ring on her left ring finger',
        'sometimes': '',
    },
    'mar_with_you': {
        'always': '',
        'sometimes': "she wears the user's oversized shirt, a little too big for her",
    },
}


OUTDOOR_LIGHT_SCENES = {'park', 'street', 'embankment', 'rooftop'}


def _time_from_text(low: str) -> str:
    """V3.60.1: «фото в парке днём» — the time he names wins over his clock."""
    if re.search(r'\bутр|morning', low):
        return 'soft morning light'
    if re.search(r'\bдн[её]м\b|\bдень\b|дневн|daytime|\bday\b', low):
        return 'bright daytime light'
    if re.search(r'ноч|night', low):
        return 'late night'
    if re.search(r'вечер|evening|закат|sunset', low):
        return 'warm golden-hour evening light'
    return ''


def _outdoor_light(light: str, scene: str) -> str:
    """Night lamp light «outside the window» made a park shot look like a
    murky evening — outdoors the dark hours get street lamps instead."""
    if scene not in OUTDOOR_LIGHT_SCENES:
        return light
    if light.startswith('evening'):
        return 'evening outdoors: deep blue-hour sky, warm street lamps lighting her face'
    if light.startswith('late night'):
        return 'night outdoors: dark night sky, city lights and warm street lamps lighting her face, no daylight'
    return light


# V3.60.5: «я рядом с мужем, он уже сопит» and then a balcony selfie at sunset —
# a plain selfie now follows where she just said she is.
DIALOG_PLACES = (
    (r'(муж|парень|он)[^.!?]{0,40}(спит|сопит|храпит|уснул)|рядом с муж|рядом с парн',
     'in bed under the blanket in the dark, secretly taking a quiet selfie so she won\'t wake the man asleep beside her — '
     'his sleeping shoulder blurred in the dark behind her, a guilty-playful look',
     'late night: only the phone-screen glow on her face, dark room, no daylight'),
    (r'кроват|постел|одеял|подушк|сплю|засыпа|уснул|сопит|лежу|в спальн',
     'in bed under a soft blanket in her dim bedroom, head on the pillow, phone held above her face',
     'late night: dim warm bedside lamp or phone-screen glow, dark room, no daylight'),
    (r'ванн|в душе|душ\b|пена', 'in her bathroom, warm steam and soft light', ''),
    (r'кухн|готовлю|варю', 'in her home kitchen', ''),
    (r'офис|на работе|в работе|за ноутбук', 'at her desk in the office', ''),
    (r'за рул|в машин', 'in the driver seat of her parked car', ''),
    (r'балкон', 'on her balcony', ''),
    (r'диван|сериал', 'curled up on the sofa at home', ''),
)


def place_from_dialog(texts) -> tuple[str, str]:
    """Location and light from her latest messages (newest first), or ('', '')."""
    for text in texts:
        low = (text or '').lower()
        for pattern, place, light in DIALOG_PLACES:
            if re.search(pattern, low):
                return place, light
    return '', ''


def _local_time_light(telegram_id: int) -> str:
    """V3.59.8: the light of the user's own clock — a midnight request used to
    come back as a sunny morning shot."""
    try:
        from zoneinfo import ZoneInfo
        from services.user_service import get_user
        user = get_user(telegram_id)
        if not user or not user.timezone:
            return ''
        hour = datetime.now(ZoneInfo(user.timezone)).hour
    except Exception:
        return ''
    if 5 <= hour < 11:
        return 'soft morning light'
    if 11 <= hour < 17:
        return 'bright daytime light'
    if 17 <= hour < 20:
        return 'warm golden-hour evening light'
    if 20 <= hour < 23:
        return 'evening: cozy warm indoor lamp light, already dark outside the window'
    return 'late night: dim warm bedside or lamp light, deep dark night outside the window, no daylight anywhere'


def marital_status_for(telegram_id: int, character_id: str) -> str:
    """V3.59.7: the user's pick for this girl, else a custom girl's constructor
    choice, else '' (single / no detail)."""
    try:
        from models.relationship_models import UserCharacterRelationship
        with SessionLocal() as session:
            user = session.scalar(select(User).where(User.telegram_id == str(telegram_id)))
            if user:
                ms = session.scalar(select(UserCharacterRelationship.marital_status).where(
                    UserCharacterRelationship.user_id == user.id,
                    UserCharacterRelationship.character_id == character_id,
                ))
                if ms:
                    return ms
        from services.custom_character_service import is_custom_character, custom_character_params
        if is_custom_character(character_id):
            return str(custom_character_params(character_id)[0].get('marital', '') or '')
    except Exception:
        logger.exception('marital status read failed user=%s character=%s', telegram_id, character_id)
    return ''


def marital_photo_detail(telegram_id: int, character_id: str, *, allow_sometimes: bool = True) -> str:
    spec = MARITAL_PHOTO_DETAIL.get(marital_status_for(telegram_id, character_id))
    if not spec:
        return ''
    bits = [spec['always']] if spec['always'] else []
    if allow_sometimes and spec['sometimes'] and random.random() < 0.35:
        bits.append(spec['sometimes'])
    return '; '.join(bits)


def _resolve_request(telegram_id: int, request: PhotoRequest, *, character_id: str = CHARACTER_ID) -> PhotoRequest:
    state = ensure_life_state(telegram_id, character_id=character_id)
    season = request.season or _default_season()
    # V3.114.0: «👗 Гардероб» — what he gave her: today's garment, jewellery, room things.
    wd, gf = {}, {}
    if not request.with_guest:
        try:
            from services.wardrobe_service import photo_overrides
            wd = photo_overrides(telegram_id, character_id, request.scene, SCENE_GROUP.get(request.scene, 'day_casual'))
        except Exception:
            wd = {}
    if wd.get('clothing') and not request.clothing and not request.pack_outfits:
        request = replace(request, clothing=wd['clothing'], gift_outfit=True)
    if wd.get('accessory') and not request.accessory:
        request = replace(request, accessory=wd['accessory'])
    if not request.with_guest and not request.pack_outfits:
        try:
            from services.gift_shop_service import photo_overrides as gift_photo_overrides
            gf = gift_photo_overrides(telegram_id, character_id, request.scene,
                                      SCENE_GROUP.get(request.scene, 'day_casual'))
        except Exception:
            gf = {}
    # V3.153.0: owner ТЗ (Фогель, Модуль 4) — «платный подарок меняет картинку»:
    # the gift he bought once stays on her, so its clause has to reach the
    # prompt on every later photo. The wardrobe keeps the slot it was put on
    # for today («Надеть сегодня» is a deliberate action, a gift is a state),
    # the gift fills what is left and always says what she wears underneath —
    # that is how a lingerie gift shows up in bed and what she took off in a
    # nude frame.
    if gf.get('clothing') and not request.clothing:
        request = replace(request, clothing=gf['clothing'], gift_outfit=True)
    if gf.get('accessory'):
        request = replace(request, accessory=f'{request.accessory}; {gf["accessory"]}'
                          if request.accessory else gf['accessory'])
    if gf.get('underwear') and not wd.get('underwear'):
        wd = dict(wd, underwear=gf['underwear'])
    PRIVATE_SCENES = SEEDREAM_ADULT_SCENES | {'selfie'}
    spicy_level = 0 if request.scene in PRIVATE_SCENES else spicy_confidence.current_level(telegram_id, character_id)
    ordinary_style = _ordinary_style_request(request, get_relationship_level(telegram_id, character_id))
    pinned_outfit = bool(ordinary_style and (request.clothing or request.pack_outfits))
    ordinary_style = ordinary_style and (spicy_level == 0 or pinned_outfit)
    pack_outfits = tuple(request.pack_outfits) if request.pack_outfits else _choose_progression_outfits(
        telegram_id, request, season, character_id=character_id, ordinary_style=ordinary_style)
    clothing = pack_outfits[-1] if pack_outfits else request.clothing
    # V3.43.8: character-specific styling. Each built-in heroine has her own
    # hair colors, hairstyles and wardrobe in visual_identity.photo_style;
    # explicit request fields and learned preferences still win.
    style = _photo_style(character_id)
    if request.hairstyle:
        hairstyle = request.hairstyle
    elif ordinary_style:
        hairstyle = _ordinary_hairstyle(character_id, style)
    else:
        recent_hair = {x.strip().lower() for x in _json_list(getattr(state, 'recent_hairstyles_json', '[]'))}
        if state.hairstyle:
            recent_hair.add(state.hairstyle.strip().lower())
        char_hairstyles = style.get('hairstyles', [])
        base_hair_pool = char_hairstyles if char_hairstyles else HAIRSTYLE_POOL
        hair_pool = [x for x in base_hair_pool if x.strip().lower() not in recent_hair] or list(base_hair_pool)
        # V3.167.14: причёска привязана к дате — меняется раз в 3 дня для каждой модели.
        # Это создаёт ощущение "жизни": сегодня 18 ноября — одна причёска, 22 ноября — другая.
        today = _today()
        days_since_epoch = (today - datetime(2026, 1, 1, tzinfo=timezone.utc).date()).days
        three_day_period = days_since_epoch // 3
        hair_seed = hashlib.md5(f"{character_id}_{three_day_period}".encode()).hexdigest()
        hair_index = int(hair_seed, 16) % len(hair_pool)
        hairstyle = hair_pool[hair_index]
        uid = ensure_user(telegram_id)
        visual_prefs = get_visual_preferences(uid, character_id)
        hair_counts = visual_prefs.get('hairstyles', {}) if isinstance(visual_prefs, dict) else {}
        preferred_hair = max(hair_counts, key=hair_counts.get) if hair_counts and max(hair_counts.values()) >= 2 else ''
        if preferred_hair and preferred_hair.strip().lower() not in recent_hair and random.random() < 0.50:
            hairstyle = preferred_hair
    # V3.166.7 (владелец, «локация исключительно из того, что скажет LLM»):
    # живая анкета кадра сильнее и состояния дня, и банка случайных идей, и
    # дефолтной сцены. Своё место остаётся только за тем, что он назвал сам в
    # этой просьбе о фото («customized»). Маркер «PLACE FROM HER MESSAGE» — не
    # для генератора красоты: по нему enforce_private_location понимает, что
    # комнату выдумывать не надо, она уже названа словами.
    from services import scene_card_service
    card_scene = scene_card_service.scene_for(telegram_id, character_id)
    if request.customized and request.location:
        location = request.location
    elif card_scene:
        location = f'PLACE FROM HER MESSAGE: {card_scene}'
    elif request.location:
        location = request.location
    elif request.scene == 'selfie' and getattr(state, 'location', None):
        activity = getattr(state, 'activity', None) or 'having a normal day'
        location = f"{SCENES['selfie']}; keep it consistent with the character's current fictional day context: location={state.location}, activity={activity}"
    else:
        location = SCENES.get(request.scene, SCENES['selfie'])
    # V3.43.8: each character draws from her own hair-color palette instead
    # of sharing one global monthly cycle. Anna and custom personas without
    # a palette fall back to the original cycle.
    if request.hair_color:
        hair_color = request.hair_color
    elif ordinary_style:
        # No HAIR COLOR override: the canonical identity/reference keeps its
        # original color (including constructor personas), not a random dye.
        hair_color = ''
    else:
        char_colors = style.get('hair_colors', [])
        if char_colors:
            recent_hc = {x.strip().lower() for x in _json_list(getattr(state, 'recent_hair_colors_json', '[]'))}
            available = [c for c in char_colors if c.strip().lower() not in recent_hc] or list(char_colors)
            hair_color = random.choice(available)
        else:
            hair_color = current_hair_color()
    # V3.167.14: используем предпочтения персонажей для разнообразия
    char_prefs = get_character_preferences(character_id)
    makeup = request.makeup or char_prefs.get('preferred_makeup') or random.choice(MAKEUP_POOL_EXTENDED)
    accessory = request.accessory or char_prefs.get('preferred_accessories') or random.choice(ACCESSORY_POOL_EXTENDED)
    time_of_day = _outdoor_light(request.time_of_day or _local_time_light(telegram_id) or random.choice(DAYLIGHT_POOL), request.scene)
    # V3.167.14 этап 7: уровень раскрепощённости меняет одежду только на ПУБЛИЧНЫХ сценах.
    # Домашние (van, спальня, ванная, «Раздеть», «Наедине», селфи) остаются всегда в белье/голые.
    if spicy_level > 0 and spicy_level <= 10 and not pinned_outfit:
        # Используем одежду по уровню раскрепощённости (уже включает обувь и чулки)
        clothing = SPICY_OUTFIT_LEVELS[spicy_level]
        underwear_color = ''
        underwear_style = ''
    else:
        # Обычная логика выбора белья
        underwear_color = random.choice(UNDERWEAR_COLOR_POOL)
        underwear_style = random.choice(UNDERWEAR_STYLE_POOL)
        # V3.167.14: добавляем обувь и чулки из предпочтений персонажей
        shoes = char_prefs.get('preferred_shoes') or random.choice(SHOES_POOL)
        stockings = char_prefs.get('preferred_stockings') or random.choice(STOCKINGS_POOL)
        if not pinned_outfit:
            if clothing:
                clothing = f'{clothing}, {shoes}, {stockings}'
            else:
                clothing = f'{shoes}, {stockings}'
    if wd.get('underwear'):
        # his 18+ gift is the set she wears when the home-lingerie rule applies
        underwear_color, underwear_style = 'his gift', wd['underwear']
    # V3.31.7: variety rotations. A chat-mood expression still wins over the
    # rotation; otherwise every frame of the pack walks its own shuffled
    # expression and pose note instead of repeating one fixed look.
    from services.photo_expression_service import shuffled_sensual_variety_keys, shuffled_variety_keys, shuffled_private_sensual_keys
    # V3.51.4: the owner wants sensual facial emotion walked on EVERY photo, public
    # scenes included, so the default per-frame rotation is the sensual pool for all
    # scenes. An explicit chat-mood expression_key still overrides the rotation.
    # V3.55.6: the chosen «tender» manner swaps the sensual pool for the soft
    # everyday one (smile/laughing/thoughtful/shy/...); unset or «passionate»
    # keeps the V3.51.4 default.
    # V3.59.3: a user on the «passion» path (story choices pushed the axis to
    # the bold side) gets the hot faces — and flirtier poses — in EVERY scene.
    passion = _path_is_passion(telegram_id, character_id)
    # V3.61.4: the tenderness path (axis −20 and below) gets soft faces and
    # cozy romantic poses in every public scene — the mirror of passion.
    tender = not passion and _path_is_tender(telegram_id, character_id)
    expression_rotation = tuple(request.expression_rotation) or (
        () if request.expression_key else (
            shuffled_variety_keys() if _persona_style_is_tender(telegram_id, character_id) or tender
            else shuffled_private_sensual_keys() if (request.scene in {'personal', 'lingerie', 'private_fashion', 'tease'} or passion)
            else shuffled_sensual_variety_keys()
        )
    )
    # V3.43.4: private/boudoir scenes draw their pose notes from the sultrier pool.
    poses = list(PRIVATE_POSE_POOL if request.scene in {'personal', 'lingerie', 'private_fashion', 'tease'} else POSE_POOL)
    if passion and request.scene not in {'personal', 'lingerie', 'private_fashion', 'tease'}:
        poses = list(PASSION_PUBLIC_POSE_POOL)
    elif tender and request.scene not in {'personal', 'lingerie', 'private_fashion', 'tease'}:
        poses = list(TENDER_POSE_POOL)
    random.shuffle(poses)
    pose_rotation = tuple(request.pose_rotation) or (
        _ordinary_pose_rotation(telegram_id, character_id)
        if ordinary_style and not passion and not tender and not request.angle else tuple(poses)
    )
    # V3.167.14: логирование выбранных тегов для отладки разнообразия генерации.
    logging.info(
        f"[photo_service] character={character_id} scene={request.scene} "
        f"hairstyle='{hairstyle}' hair_color='{hair_color}' makeup='{makeup}' "
        f"accessory='{accessory}' underwear_color='{underwear_color}' "
        f"underwear_style='{underwear_style}' clothing='{clothing[:100]}' "
        f"spicy_level={spicy_level} poses_count={len(pose_rotation)}"
    )
    return replace(request, clothing=clothing, hairstyle=hairstyle, location=location, season=season,
                   pack_outfits=pack_outfits, hair_color=hair_color, makeup=makeup,
                   accessory=accessory, time_of_day=time_of_day,
                   underwear_color=underwear_color, underwear_style=underwear_style,
                   expression_rotation=expression_rotation, pose_rotation=pose_rotation,
                   story_detail='; '.join(x for x in (request.story_detail or marital_photo_detail(telegram_id, character_id), wd.get('room', '')) if x))


def _shot_variant(scene: str, index: int, requested_angle: str = '') -> str:
    if requested_angle:
        return requested_angle
    variants = SHOT_VARIANTS.get(scene, SHOT_VARIANTS['selfie'])
    return variants[index % len(variants)]


def _build_prompt(request: PhotoRequest, shot_index: int, seedream: bool = False, relationship_level: int = 1, character_id: str = CHARACTER_ID, *, force_safe: bool = False, duo_block: str = '') -> str:
    scene = SCENES.get(request.scene, SCENES['selfie'])
    # V3.166.5: a starter frame is described by the scenario itself — her first
    # line is the place, the garment and the pose, so the generic boudoir scene
    # text, her day context and the messy-bedroom amateur clause all step out.
    starter = bool(request.starter_note)
    angle = _shot_variant(request.scene, shot_index, request.angle)
    outfits = tuple(request.pack_outfits) if request.pack_outfits else (request.clothing,)
    wardrobe = outfits[min(shot_index, len(outfits) - 1)] if outfits else request.clothing
    if not seedream:
        # Normal OpenAI lifestyle route stays clearly general-audience while still looking styled.
        wardrobe = (wardrobe
                    .replace('body-skimming', 'well-fitted')
                    .replace('figure-flattering', 'polished')
                    .replace('strong waist-defined silhouette', 'clean tailored silhouette')
                    .replace('glamorous', 'stylish'))
    tier_rule = PACK_TIER_RULES[min(shot_index, len(PACK_TIER_RULES) - 1)]
    level_key = max(1, min(6, relationship_level))
    visual_rule = (LEVEL_VISUAL_RULES if seedream else OPENAI_LEVEL_VISUAL_RULES).get(level_key, LEVEL_VISUAL_RULES[1])
    underlay_rule = LEVEL_UNDERLAY_RULES.get(level_key, LEVEL_UNDERLAY_RULES[1])
    # At relationship level 5+ her at-home scenes (selfie/home/mirror) are
    # shot in only her lingerie — the lingerie IS the outfit there. Seedream
    # only: the general-audience OpenAI fallback route keeps ordinary
    # wardrobes to stay within its moderation envelope.
    adult_scene = seedream and request.scene in ADULT_SCENES and not force_safe
    home_lingerie = seedream and level_key >= 5 and request.scene in HOME_LINGERIE_SCENES and not force_safe
    if request.gift_outfit:  # V3.116.0: today's gift garment wins over the level-5+ lingerie rule
        home_lingerie = False
    if adult_scene:
        wardrobe = 'nothing at all — an elegant fine-art nude composition, tasteful and intimate, styled like classic boudoir photography'
        underlay_rule = ''
    elif home_lingerie:
        style_note = f' ({request.underwear_style})' if request.underwear_style else ''
        set_desc = f'{request.underwear_color} lingerie{style_note} set' if request.underwear_color else 'elegant lingerie set'
        if request.underwear_color == 'his gift':  # V3.114.0: his 18+ wardrobe gift
            set_desc = request.underwear_style
        wardrobe = f'only her {set_desc} — a matching bra and panties worn as the entire outfit in the privacy of her home, no outerwear at all'
        underlay_rule = 'Her lingerie is the outfit itself in this private at-home moment: nothing is worn over it and no other clothing appears in the frame.'
    # Inject specific underwear color and style only in the dedicated private
    # scenes where lingerie is the subject of the photo. V3.19.2: naming the
    # bra and panties in ordinary/public shots (even at level 5-6) made the
    # model draw visible lingerie in restaurants, cars and bars — public
    # venues now stay fully clothed, so the color stays unspoken there.
    elif request.underwear_color and request.scene in {'personal', 'lingerie', 'private_fashion'}:
        style_note = f' ({request.underwear_style})' if request.underwear_style else ''
        underlay_rule = (
            f'The lingerie she wears beneath her outfit is {request.underwear_color}{style_note} — always the under-layer, never outerwear. '
        ) + underlay_rule
    # Private scenes escalate with the relationship level (standard/suggestive/revealing).
    if starter:
        # Her promised frame carries its own garment; the level-based boudoir
        # set and the under-clothing line would only re-draw lace over a bath
        # or a blanket.
        wardrobe = STARTER_WARDROBE
        underlay_rule = ''
    tier_framing = ''
    scene_tiers = PRIVATE_SCENE_TIERS.get(request.scene)
    if scene_tiers and not force_safe and not starter:
        tier_key = 'revealing' if level_key >= 6 else ('suggestive' if level_key >= 5 else 'standard')
        tier_framing = f'PRIVATE SCENE FRAMING: {scene_tiers[tier_key]}.\n'
    if home_lingerie:
        tier_framing = (
            'HOME LINGERIE LOOK: at this level of trust she shoots her at-home sets relaxed and confident in only her lingerie — '
            'a private, tasteful, non-explicit at-home look made specifically for the person she is chatting with.\n'
        )
    # V3.19.2: at level 5-6 ordinary/public scenes no longer escalate toward
    # revealing cuts — she stays fully clothed there; the intimate looks live
    # in the at-home lingerie sets and the private scenes instead.
    season = request.season or _default_season()
    season_rule = SEASON_RULES.get(season, SEASON_RULES['summer'])
    identity, personal, safety, expression_identity = _character_identity_lock(character_id, seedream=seedream, expression_key=request.expression_key or (request.expression_rotation[shot_index % len(request.expression_rotation)] if request.expression_rotation else None))
    if adult_scene or starter:
        # V3.166.5 (владелец: «полная нагота всегда, и стартовые кадры тоже»):
        # the teaser frame is shown only in the «Без цензуры 18+» mode, so the
        # censorship envelope of the romantic route must not sit under it — the
        # bath and the bedroom prompts read as ordinary lingerie and got dressed
        # back up. What she actually shows stays written in her own scene line.
        safety = ADULT_SAFETY
    # V3.43.8: inject the character's actual age into the subject lock so
    # the provider sees the real age instead of a universal "twenties" label.
    adult_lock = ADULT_ONLY_LOCK
    if character_id != 'anna_01':
        try:
            _char = resolve_character(character_id)
            _card = None
            try:
                from services.character_card_service import get_card as _gc
                _card = _gc(character_id)
            except Exception:
                pass
            _age = _card.age if _card and _card.age else int(_char.get('age') or 25)
        except Exception:
            _age = 25
        adult_lock = ADULT_ONLY_LOCK.replace('adult woman', f'adult woman, {_age} years old', 1)
    body_reinforcement = BODY_REINFORCEMENT if (character_id == 'anna_01' and not seedream and request.scene in BODY_REINFORCEMENT_SCENES) else ''
    figure_note = (
        'Use tasteful fashion fit and waist definition while preserving the underlying slim body proportions. ' if seedream else
        'Use a well-fitted outfit that preserves the person\u2019s physique and proportions. Use a natural everyday pose with the visual focus on the person, outfit and environment. '
    )
    # V3.44.9: public scenes get the hard no-lingerie lock; private boudoir
    # scenes, adult scenes and the at-home lingerie look are exempt. Under
    # force_safe even a private scene stays general-audience, so the lock
    # applies there too.
    private_look = (
        adult_scene or home_lingerie
        or (not force_safe and request.scene in (SEEDREAM_ADULT_SCENES | ADULT_SCENES))
    )
    public_dress_rule = '' if private_look else PUBLIC_DRESS_RULE + '\n'
    bust_lock = bust_lock_line(character_id)
    bust_lock_tail = f'\n{bust_lock}' if bust_lock else ''
    if not private_look and level_key >= 3:
        public_dress_rule += LEVEL_HEMLINE_RULE + '\n'
    # V3.152.1 (Задача 4): hot frames stop looking like a studio shoot. The
    # amateur lock rides just under the identity, where the trimming of
    # SpicyAPI cannot reach it; the general-audience OpenAI route never gets
    # it, because there the safe wording is what keeps the generation alive.
    amateur_lock = ''
    if private_look and seedream and not force_safe:
        amateur_lock = f'{STARTER_AMATEUR_LOCK if starter else AMATEUR_HOT_FRAME_LOCK}\n'
    duo_head = f'{duo_head_lock(character_id, request.with_guest)}\n' if request.with_guest else ''
    # V3.165.0: the limb lock belongs at the head. It used to ride above the
    # quality block, where _fit_spicy_prompt cuts it first, so a long lingerie
    # prompt reached SpicyAPI with «exactly two arms» already trimmed off —
    # that is the third arm in the owner's screenshot.
    hands_lock = f'{HANDS_RULE}\n'
    body = apply_art_style(
        f'{identity}\n'
        + (f'{duo_block}\n' if duo_block else '')
        + f'{amateur_lock}'
        + f'{hands_lock}'
        + f'{adult_lock}\n'
        + (f'SCENE: {request.starter_note}.\n{STARTER_FRAME_LOCK}\n' if starter
           else f'SCENE: {scene}. {request.location}.\n')
        + f'SEASON/WEATHER: {season}. {season_rule}\n'
        f'RELATIONSHIP VISUAL PROGRESSION: {visual_rule}\n'
        f'PROGRESSION PACK FRAME {shot_index + 1}/{PHOTO_SET_SIZE}: {tier_rule}\n'
        f'WARDROBE: {wardrobe}. {figure_note}'
        'The outfit must be believable for this exact venue, weather and time of day. Do not reuse a heavy sweater or hoodie in a visibly warm summer scene.\n'
        f'{public_dress_rule}'
        f'UNDER-CLOTHING REALISM: {underlay_rule}{"" if (adult_scene or home_lingerie or starter) else LINGERIE_LAYERING_LOCK}\n'
        f'{tier_framing}'
        f'{BUST_CONSISTENCY_RULE}\n'
        f'HAIRSTYLE: {request.hairstyle}. This is her one and only hairstyle in the frame — '
        'never combine it with a second hairdo, extra braid, bun, wig or hairpiece.\n'
        f'MAKEUP: {request.makeup}.\n'
        f'STYLING DETAILS: {request.accessory}.\n'
        + (f'STORY DETAIL: {request.story_detail}. Keep it small and natural; it never changes her face, body or outfit choice.\n'
           if request.story_detail else '')
        + 
        f'TIME OF DAY: {request.time_of_day}. The light must match this time of day.\n'
        f'CAMERA/POSE: {angle}.\n'
        + (f'POSE NOTE: {_pose_note(request, shot_index)}. '
           'Use exactly this posture for this frame and keep it clearly different from the other frames of the set.\n'
           if request.pose_rotation else '')
        + (f'HAIR COLOR: {request.hair_color}. This is the character\'s current hair color; it overrides the hair color in the reference photos and in the identity description above; her face, features and everything else stay exactly the same.\n' if request.hair_color else '')
        + f'{body_reinforcement}\n'
        f'MOOD: {request.mood}.\n'
        f'{expression_identity}\n'
        f'{personal}\n'
        'LIGHTING: use lighting that naturally belongs to the location and time of day; realistic shadows, cinematic but believable contrast.\n'
        f'{safety}\n'
        f'{QUALITY_BLOCK}\n'
        f'{NEGATIVE_BLOCK}'
        + bust_lock_tail,
        character_id,
    )
    # V3.152.1 (Задача 5): lingerie/nude and a public venue never share a
    # photo. His own request is the only thing that keeps a public place, and
    # the words he typed are what we check — not the venue she ended up in.
    # Only the Seedream-flavoured legs (SpicyAPI and fal) ever render an
    # intimate look; the general-audience OpenAI/Gemini routes stay clothed, so
    # they must never be told she is in lingerie.
    return no_phone_frame(duo_head + enforce_private_location(
        body,
        f'{request.story_detail} {request.clothing} {request.location} {request.angle}',
        intimate=private_look and seedream,
        starter=starter,
    ))


def _pose_note(request: 'PhotoRequest', shot_index: int) -> str:
    """One pose sentence. V3.166.12: it used to append «(her other hand holds
    the phone)» — the phone is no longer in the frame, so the pose is the pose."""
    return request.pose_rotation[shot_index % len(request.pose_rotation)]


def _extract_openai_many(result) -> list[GeneratedPhoto]:
    out=[]
    for item in result.data:
        url=getattr(item,'url',None)
        raw=getattr(item,'b64_json',None)
        if url:
            out.append(GeneratedPhoto(url=url, provider='openai'))
        elif raw:
            out.append(GeneratedPhoto(data=base64.b64decode(raw), provider='openai'))
    if not out:
        raise RuntimeError('Image API returned no image')
    return out


async def _download_result_bytes(result: GeneratedPhoto) -> bytes | None:
    """Fetch the raw image bytes when a provider returned only a URL.

    Returns None on any failure so the gallery simply shows a view-only frame
    instead of crashing the whole delivery.
    """
    if result.data:
        return result.data
    if not result.url:
        return None
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.get(result.url)
        if response.status_code >= 400 or not response.content:
            logger.warning('gallery capture: URL download failed provider=%s url=%s status=%s',
                           result.provider, result.url[:120], response.status_code)
            return None
        return response.content
    except Exception as exc:
        logger.warning('gallery capture: URL download error provider=%s error=%s',
                       result.provider, type(exc).__name__)
        return None


async def photo_frame_bytes(photo: GeneratedPhoto) -> bytes | None:
    """V3.43.7: raw image bytes for one generated frame. The app paths
    (in-chat photos, date reward shots) save the file into their own media
    folder, so URL-only providers (openai/seedream) get downloaded once —
    the same capture the bot's gallery performs in _send_frame."""
    return photo.data or (await _download_result_bytes(photo))


_DATA_URI_CACHE: dict[str, tuple[str, str]] = {}


def _image_b64(path: Path, max_bytes: int = 900_000, max_side: int = 1280) -> tuple[str, str]:
    """Return (base64, mime) for a reference image, downscaled when oversized.

    V3.25.0: the canonical PNGs are ~5 MB each; embedding them as base64 made
    every Seedream/Gemini edit request multi-megabyte and fal rejected the
    payload with HTTP 422.  Re-encode to a compact JPEG (Pillow) when needed;
    results are cached per path+size+mtime.
    """
    stat = path.stat()
    key = f'{path}:{stat.st_size}:{stat.st_mtime_ns}'
    cached = _DATA_URI_CACHE.get(key)
    if cached:
        return cached
    raw = path.read_bytes()
    mime = mimetypes.guess_type(path.name)[0] or 'image/png'
    if len(raw) > max_bytes:
        try:
            import io as _io
            from PIL import Image
            img = Image.open(_io.BytesIO(raw)).convert('RGB')
            width, height = img.size
            scale = min(1.0, max_side / max(width, height))
            if scale < 1.0:
                img = img.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.LANCZOS)
            buf = _io.BytesIO()
            img.save(buf, format='JPEG', quality=88, optimize=True)
            raw = buf.getvalue()
            mime = 'image/jpeg'
        except Exception:
            logger.warning('reference downscale failed for %s; sending original bytes', path.name)
    encoded = (base64.b64encode(raw).decode('ascii'), mime)
    _DATA_URI_CACHE[key] = encoded
    return encoded


def _file_data_uri(path: Path) -> str:
    encoded, mime = _image_b64(path)
    return f'data:{mime};base64,{encoded}'



async def _gemini_image_one_frame(character: dict, telegram_id: int, request: PhotoRequest, i: int, *, character_id: str = CHARACTER_ID) -> GeneratedPhoto:
    if not GEMINI_API_KEY or not GEMINI_IMAGE_ENABLED:
        raise PhotoGenerationError('gemini_image', 'not_configured')

    # Interactions accepts UTF-8 prompts and base64 image blocks. We call the
    # documented REST endpoint directly instead of relying on the experimental
    # SDK wrapper; this avoids the UnicodeEncodeError observed in production and
    # gives us a deterministic response parser and clearer HTTP diagnostics.
    api_key = GEMINI_API_KEY.strip().strip('"').strip("'")
    try:
        api_key.encode('ascii')
    except UnicodeEncodeError as exc:
        raise PhotoGenerationError('gemini_image', 'invalid_api_key_non_ascii') from exc
    if not api_key or any(ch.isspace() for ch in api_key):
        raise PhotoGenerationError('gemini_image', 'invalid_api_key_whitespace')

    level = get_relationship_level(telegram_id, character_id)
    prompt = _build_prompt(request, i, seedream=False, relationship_level=level, character_id=character_id) + (
        "\nNANO BANANA ORDINARY-PHOTO RULE: Use the supplied canonical references as FACE and HAIR identity anchors only. "
        "Keep the same fictional adult person and the same exact face. The character's body and figure follow the BODY IDENTITY declaration in this prompt — including the declared bust size — even when a reference photo shows a smaller or different build. "
        "Hair color, hairstyle, facial expression and outfit follow the requested HAIR COLOR, HAIRSTYLE, EXPRESSION and WARDROBE lines, not the reference photos. "
        "This prompt is independent from chat personality, flirting, sensuality or relationship erotics; none of those should affect ordinary-photo styling. "
        "Change only the requested scene, fully clothed outfit, pose, camera and lighting. Keep the result mainstream, natural and general-audience. "
        "Photorealistic personal smartphone-photo aesthetic."
    )
    refs = _openai_reference_paths(character, request.scene)[:2]
    inputs: list[dict] = [{"type": "text", "text": prompt}]
    for ref in refs:
        data, mime = _image_b64(ref)
        inputs.append({"type": "image", "data": data, "mime_type": mime})

    payload = {
        'model': GEMINI_IMAGE_MODEL,
        'input': inputs,
        'response_format': {
            'type': 'image',
            'mime_type': 'image/png',
            'aspect_ratio': GEMINI_IMAGE_ASPECT_RATIO,
            'image_size': GEMINI_IMAGE_SIZE,
        },
    }
    headers = {'x-goog-api-key': api_key, 'Content-Type': 'application/json'}
    timeout = httpx.Timeout(float(GEMINI_IMAGE_TIMEOUT_SECONDS), connect=20.0)
    # V3.19.5: one automatic retry on transient failures (timeouts, 408/429/5xx).
    # Google's image API hiccups under load; a single retry turns many
    # "фото сейчас не получилось" moments into delivered photos.
    # V3.43.1: two retries with growing backoff — a 429 quota burst no
    # longer kills the studio picture after one unlucky attempt.
    retryable_statuses = {408, 429, 500, 502, 503, 504}
    response = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.post(
                    'https://generativelanguage.googleapis.com/v1beta/interactions',
                    headers=headers,
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            if attempt < 2:
                logger.warning('Nano Banana timeout user=%s scene=%s frame=%s/%s - retrying', telegram_id, request.scene, i + 1, PHOTO_SET_SIZE)
                await asyncio.sleep(2.0 * (attempt + 1))
                continue
            raise PhotoGenerationError('gemini_image', 'timeout') from exc
        except UnicodeEncodeError as exc:
            # Header encoding should now only fail for a malformed API key; keep the
            # error explicit instead of silently masking it behind GPT fallback logs.
            raise PhotoGenerationError('gemini_image', 'header_unicode_error') from exc
        except httpx.HTTPError as exc:
            if attempt < 2:
                logger.warning('Nano Banana transport failed user=%s scene=%s frame=%s/%s error=%s - retrying', telegram_id, request.scene, i + 1, PHOTO_SET_SIZE, type(exc).__name__)
                await asyncio.sleep(2.0 * (attempt + 1))
                continue
            logger.warning('Nano Banana transport failed user=%s scene=%s frame=%s/%s error=%s', telegram_id, request.scene, i + 1, PHOTO_SET_SIZE, type(exc).__name__)
            raise PhotoGenerationError('gemini_image', type(exc).__name__) from exc

        if response.status_code in retryable_statuses and attempt < 2:
            logger.warning('Nano Banana transient HTTP %s user=%s scene=%s frame=%s/%s - retrying', response.status_code, telegram_id, request.scene, i + 1, PHOTO_SET_SIZE)
            await asyncio.sleep(2.0 * (attempt + 1))
            continue
        break

    if response.status_code >= 400:
        reason = f'http_{response.status_code}'
        try:
            error_obj = response.json().get('error') or {}
            status = str(error_obj.get('status') or '').lower()
            if status:
                reason += f'_{status}'
        except Exception:
            pass
        logger.warning('Nano Banana HTTP failure user=%s scene=%s frame=%s/%s status=%s', telegram_id, request.scene, i + 1, PHOTO_SET_SIZE, response.status_code)
        raise PhotoGenerationError('gemini_image', reason)

    # V3.44.18: a 2xx Gemini call is billed even when the frame later fails to
    # parse or is discarded. This is the main photo engine and its cost used to
    # default to $0, so «себестоимость фото» could never show the money it ate.
    spend_service.record_image_spend('gemini_image', request.scene, GEMINI_IMAGE_ESTIMATED_COST_USD)

    try:
        body = response.json()
    except Exception as exc:
        raise PhotoGenerationError('gemini_image', 'invalid_json') from exc

    raw = None
    mime_type = 'image/png'
    # REST interactions response: steps[] -> model_output -> content[] -> image.
    for step in reversed(body.get('steps') or []):
        for content in reversed(step.get('content') or []):
            if content.get('type') == 'image' and content.get('data'):
                raw = content.get('data')
                mime_type = content.get('mime_type') or mime_type
                break
        if raw:
            break
    if not raw:
        step_types = [str(step.get('type') or '-') for step in (body.get('steps') or []) if isinstance(step, dict)]
        logger.warning(
            'Nano Banana response contained no image user=%s scene=%s frame=%s/%s keys=%s step_types=%s interaction_id=%s',
            telegram_id, request.scene, i + 1, PHOTO_SET_SIZE, ','.join(sorted(body.keys())), ','.join(step_types) or '-', body.get('id') or body.get('interaction_id'),
        )
        raise PhotoGenerationError('gemini_image', 'no_image')
    try:
        data = base64.b64decode(raw)
    except Exception as exc:
        raise PhotoGenerationError('gemini_image', 'invalid_base64') from exc
    if not data:
        raise PhotoGenerationError('gemini_image', 'empty_image')
    logger.info(
        'Nano Banana frame success user=%s scene=%s frame=%s/%s model=%s bytes=%s',
        telegram_id, request.scene, i + 1, PHOTO_SET_SIZE, GEMINI_IMAGE_MODEL, len(data),
    )
    return GeneratedPhoto(data=data, provider='gemini_image', estimated_cost_usd=GEMINI_IMAGE_ESTIMATED_COST_USD)


async def _run_gemini_set(
    character: dict,
    telegram_id: int,
    request: PhotoRequest,
    on_frame: Callable[[GeneratedPhoto, int], Awaitable[None]] | None = None,
    *,
    character_id: str = CHARACTER_ID,
    frames: int = PHOTO_SET_SIZE,
) -> list[GeneratedPhoto]:
    out: list[GeneratedPhoto] = []
    logger.info('Nano Banana set request user=%s scene=%s model=%s count=%s refs=2', telegram_id, request.scene, GEMINI_IMAGE_MODEL, frames)
    for i in range(frames):
        started = time.monotonic()
        try:
            photo = await _gemini_image_one_frame(character, telegram_id, request, i, character_id=character_id)
        except PhotoGenerationError as exc:
            track_event(ensure_user(telegram_id), 'photo_frame_failed', metadata={'scene': request.scene, 'frame': i + 1, 'provider': 'gemini_image', 'reason': exc.reason})
            if out:
                logger.warning('Nano Banana partial set user=%s scene=%s count=%s/%s reason=%s', telegram_id, request.scene, len(out), PHOTO_SET_SIZE, exc.reason)
                break
            raise
        out.append(photo)
        frame_elapsed = time.monotonic() - started
        track_event(ensure_user(telegram_id), 'photo_frame_ready', value=frame_elapsed, metadata={'scene': request.scene, 'frame': i + 1, 'provider': 'gemini_image'})
        if i == 0:
            track_event(ensure_user(telegram_id), 'photo_first_frame_ready', value=frame_elapsed, metadata={'scene': request.scene, 'provider': 'gemini_image'})
        if on_frame:
            await on_frame(photo, i)
    if not out:
        raise PhotoGenerationError('gemini_image', 'no_image')
    return out


# V3.64.4: since 15.10 every fal.run call dies with ReadError ~1s after it is
# sent, on every route. Walking 3 routes x 3 attempts cost each failed photo
# ~28s on top of the main engine, and every next photo paid it again. One
# exhausted route now marks fal down for the cooldown, and calls skip it.
FAL_DOWN_COOLDOWN_SECONDS = 600
_fal_down_until = 0.0


async def _seedream_request(
    prompt: str,
    image_urls: list[str],
    num_images: int = 1,
    request_label: str = '',
    *,
    allow_adult: bool = False,
    model: str | None = None,
) -> dict:
    """Call fal/Seedream with explicit phase timeouts and bounded retry.

    Seedream can legitimately take longer than a normal HTTP request.  We retry
    only transport timeouts and transient HTTP errors.  Policy/validation 4xx
    responses are returned immediately so we never try to bypass provider safety.
    """
    global _fal_down_until
    if not FAL_KEY:
        raise PhotoGenerationError('seedream45', 'FAL_KEY is not configured')
    if time.monotonic() < _fal_down_until:
        logger.info('Seedream skipped (fal down) label=%s', request_label or '-')
        raise PhotoGenerationError('seedream45', 'fal_down')
    
    # V3.44.3: fal retires/renames routes (v4.5 → v5 lite/pro). When the
    # configured model answers 404, walk a bounded fallback list of known
    # routes so a renamed endpoint never kills the whole leg. Policy 4xx
    # (400/403/422/451) are NOT bypassed — only «path not found».
    primary = (model or FAL_MODEL).strip('/')
    # V3.44.19: the primary is the owner's fal sandbox model; the proven
    # Seedream partner route rides right behind it, so a retired or renamed
    # registry id can never kill the edit leg — a 404 walks to the next
    # candidate instantly (policy 4xx are still never bypassed).
    if image_urls:
        candidates = [primary, 'bytedance/seedream/v5/pro/edit', 'fal-ai/bytedance/seedream/v5/lite/edit', 'fal-ai/bytedance/seedream/v4.5/edit']
    else:
        candidates = [primary, 'fal-ai/bytedance/seedream/v5/lite/text-to-image', 'fal-ai/bytedance/seedream/v4.5/text-to-image']
    seen: set[str] = set()
    candidates = [c for c in candidates if not (c in seen or seen.add(c))]
    
    payload = {
        'prompt': prompt,
        'image_size': FAL_IMAGE_SIZE,
        'num_images': num_images,
        'max_images': num_images,
        'enable_safety_checker': not allow_adult,
    }
    if image_urls:
        # V3.43.1: the edit endpoint rejects an empty image_urls sequence
        # with HTTP 422, so reference-free calls omit the field entirely.
        payload['image_urls'] = image_urls
    headers = {'Authorization': f'Key {FAL_KEY}', 'Content-Type': 'application/json'}
    timeout = httpx.Timeout(
        connect=float(FAL_CONNECT_TIMEOUT_SECONDS),
        read=float(FAL_TIMEOUT_SECONDS),
        write=float(FAL_WRITE_TIMEOUT_SECONDS),
        pool=float(FAL_POOL_TIMEOUT_SECONDS),
    )
    max_attempts = FAL_RETRIES + 1
    transient_statuses = {408, 425, 429, 500, 502, 503, 504}
    # V3.44.18: the media brake sits in front of every fal call (chat photos,
    # studio renders and constructor avatars alike), so nothing is billed after
    # the daily cap — and the caller's refund path still returns the money.
    if not spend_service.image_generation_allowed():
        logger.warning('SEEDREAM blocked by daily image budget label=%s', request_label or '-')
        raise PhotoGenerationError('budget', 'daily_image_budget_exhausted')
    
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        last_error: PhotoGenerationError | None = None
        for candidate in candidates:
            endpoint = f"https://fal.run/{candidate}"
            for attempt in range(1, max_attempts + 1):
                started = time.monotonic()
                try:
                    response = await client.post(endpoint, headers=headers, json=payload)
                except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.WriteTimeout, httpx.PoolTimeout, httpx.ReadError, httpx.RemoteProtocolError) as exc:
                    # V3.44.20: ReadError/RemoteProtocolError (connection reset
                    # mid-request) used to escape this loop entirely — the photo
                    # died as «seedream45: ReadError» with ZERO retries and no
                    # candidate walk. They are transient transport faults like
                    # timeouts: retry with backoff, then walk to the next route.
                    elapsed = time.monotonic() - started
                    logger.warning(
                        'Seedream transport failed label=%s model=%s attempt=%s/%s elapsed=%.1fs type=%s',
                        request_label or '-', candidate, attempt, max_attempts, elapsed, type(exc).__name__,
                    )
                    if attempt >= max_attempts:
                        # every route lives on fal.run: a dead transport here is
                        # dead for the rest of the list too.
                        _fal_down_until = time.monotonic() + FAL_DOWN_COOLDOWN_SECONDS
                        logger.error('fal marked down for %ss after %s', FAL_DOWN_COOLDOWN_SECONDS, type(exc).__name__)
                        raise PhotoGenerationError('seedream45', f'transport_{type(exc).__name__}')
                    await asyncio.sleep(FAL_RETRY_BACKOFF_SECONDS * attempt)
                    continue
    
                elapsed = time.monotonic() - started
                logger.info(
                    'Seedream response label=%s model=%s attempt=%s/%s status=%s elapsed=%.1fs',
                    request_label or '-', candidate, attempt, max_attempts, response.status_code, elapsed,
                )
                if response.status_code < 400:
                    # V3.44.18: a 2xx fal call is billed even when we throw the
                    # frame away afterwards (bad size / validation / quality).
                    # This money used to be structurally invisible in the stats.
                    spend_service.record_image_spend(
                        f'fal/{candidate}', request_label or '-', FAL_ESTIMATED_COST_USD,
                    )
    
                if response.status_code >= 400:
                    body = response.text[:1600]
                    # V3.44.3: retired/renamed route — try the next candidate.
                    if response.status_code == 404 and candidate != candidates[-1]:
                        logger.warning(
                            'Seedream 404 model=%s label=%s — falling back to next route body=%s',
                            candidate, request_label or '-', body[:200],
                        )
                        last_error = PhotoGenerationError('seedream45', f'HTTP 404 {candidate}')
                        break
                    if response.status_code in transient_statuses and attempt < max_attempts:
                        logger.warning(
                            'Seedream transient HTTP status=%s label=%s attempt=%s/%s body=%s',
                            response.status_code, request_label or '-', attempt, max_attempts, body[:500],
                        )
                        await asyncio.sleep(FAL_RETRY_BACKOFF_SECONDS * attempt)
                        continue
                    logger.error('Seedream HTTP error status=%s body=%s', response.status_code, body)
                    # V3.25.0: carry a short body excerpt in the reason so the chat
                    # error chain shows WHY fal rejected the request, not just 422.
                    detail = ' '.join(body.split())[:140]
                    last_error = PhotoGenerationError('seedream45', f'HTTP {response.status_code} {detail}'.strip())
                    break
    
                try:
                    return response.json()
                except Exception as exc:
                    logger.error('Seedream returned non-JSON response: %s', response.text[:1200])
                    raise PhotoGenerationError('seedream45', 'invalid_json') from exc
    
    if last_error is not None:
        raise last_error
    raise PhotoGenerationError('seedream45', 'request_failed')


async def _openai_one_frame(character: dict, telegram_id: int, request: PhotoRequest, i: int, *, safe_retry: bool = False, single_reference: bool = False, character_id: str = CHARACTER_ID) -> GeneratedPhoto:
    refs = _openai_reference_paths(character, request.scene, safe=safe_retry)
    if single_reference and len(refs) > 1:
        # Last ref is the fully-clothed full-body anchor and carries enough face +
        # silhouette information for providers/proxies that only accept one edit image.
        refs = (refs[-1],)
    level = get_relationship_level(telegram_id, character_id)
    if safe_retry:
        fallback_outfit = (
            'a simple lightweight summer midi dress with normal coverage and clean everyday styling'
            if (request.season or _default_season()) == 'summer' else
            'a simple season-appropriate midi dress with normal coverage and clean everyday styling'
        )
        safe_request = replace(request, clothing=fallback_outfit, pack_outfits=tuple(fallback_outfit for _ in range(PHOTO_SET_SIZE)), mood='natural, relaxed')
        prompt = _build_prompt(safe_request, i, seedream=False, relationship_level=min(level, 3), character_id=character_id) + (
            '\nSAFE RETRY: Strictly general-audience, fully clothed everyday lifestyle fashion. Neutral pose and scene-appropriate coverage. Preserve the exact face from the references; the body follows the BODY IDENTITY declaration, never the references; safety changes styling, not identity.'
        )
    else:
        prompt = _build_prompt(request, i, seedream=False, relationship_level=level, character_id=character_id)
    if single_reference:
        prompt += '\nCOMPATIBILITY RETRY: the single supplied fully-clothed reference controls the character\u2019s recognizable face and hair identity; her body follows the BODY IDENTITY declaration, never the reference silhouette.'
    started = time.monotonic()
    with ExitStack() as stack:
        image_files = [stack.enter_context(path.open('rb')) for path in refs]
        result = await openai_client.images.edit(
            model=IMAGE_MODEL,
            image=image_files,
            prompt=prompt,
            size=IMAGE_SIZE,
            quality=IMAGE_QUALITY,
            n=1,
        )
    elapsed = time.monotonic() - started
    photo = replace(_extract_openai_many(result)[0], estimated_cost_usd=OPENAI_IMAGE_ESTIMATED_COST_USD)
    # V3.44.18: mirror the fal/Gemini legs — an accepted OpenAI edit is billed,
    # so it lands in the ledger even though this provider is off by default.
    spend_service.record_image_spend('openai_image', request.scene, OPENAI_IMAGE_ESTIMATED_COST_USD)
    logger.info('OpenAI frame success user=%s scene=%s frame=%s/%s safe_retry=%s single_reference=%s refs=%s elapsed=%.1fs', telegram_id, request.scene, i + 1, PHOTO_SET_SIZE, safe_retry, single_reference, len(refs), elapsed)
    return photo


def _openai_error_debug(exc: BadRequestError) -> tuple[str | None, str | None, tuple[str, ...], str]:
    """Extract stable code plus optional moderation stage/categories for logs."""
    body = getattr(exc, 'body', None) or {}
    err = body.get('error', body) if isinstance(body, dict) else {}
    code = err.get('code') if isinstance(err, dict) else None
    message = str(err.get('message', '')) if isinstance(err, dict) else str(exc)
    details = err.get('moderation_details') if isinstance(err, dict) else None
    if not details and isinstance(body, dict):
        details = body.get('moderation_details')
    details = details if isinstance(details, dict) else {}
    stage = details.get('moderation_stage')
    categories = details.get('categories') or ()
    if isinstance(categories, str):
        categories = (categories,)
    else:
        categories = tuple(str(x) for x in categories)
    return code, stage, categories, message


async def _run_openai_set(
    character: dict,
    telegram_id: int,
    request: PhotoRequest,
    on_frame: Callable[[GeneratedPhoto, int], Awaitable[None]] | None = None,
    *,
    character_id: str = CHARACTER_ID,
    frames: int = PHOTO_SET_SIZE,
) -> list[GeneratedPhoto]:
    refs = _openai_reference_paths(character, request.scene)
    logger.info('OpenAI normal-photo set request user=%s scene=%s references=%s count=%s identity_engine=v3', telegram_id, request.scene, ','.join(p.name for p in refs), frames)
    outputs: list[GeneratedPhoto] = []
    for i in range(frames):
        frame_started = time.monotonic()
        try:
            photo = await _openai_one_frame(character, telegram_id, request, i, character_id=character_id)
        except BadRequestError as exc:
            code, moderation_stage, moderation_categories, msg = _openai_error_debug(exc)
            logger.warning(
                'OpenAI frame failed user=%s scene=%s frame=%s/%s code=%s moderation_stage=%s categories=%s request_id=%s message=%s',
                telegram_id, request.scene, i + 1, PHOTO_SET_SIZE, code, moderation_stage, ','.join(moderation_categories) or '-',
                getattr(exc, 'request_id', None), msg[:700],
            )
            track_event(ensure_user(telegram_id), 'photo_frame_blocked' if code == 'moderation_blocked' else 'photo_frame_failed', metadata={'scene': request.scene, 'frame': i + 1, 'provider': 'openai', 'reason': code or 'bad_request'})
            if code == 'moderation_blocked':
                try:
                    logger.info('OpenAI safe retry user=%s scene=%s frame=%s/%s', telegram_id, request.scene, i + 1, PHOTO_SET_SIZE)
                    photo = await _openai_one_frame(character, telegram_id, request, i, safe_retry=True, character_id=character_id)
                    track_event(ensure_user(telegram_id), 'photo_safe_retry_success', metadata={'scene': request.scene, 'frame': i + 1, 'provider': 'openai'})
                except BadRequestError as retry_exc:
                    retry_code, retry_stage, retry_categories, retry_msg = _openai_error_debug(retry_exc)
                    logger.warning(
                        'OpenAI safe retry failed user=%s scene=%s frame=%s/%s code=%s moderation_stage=%s categories=%s request_id=%s message=%s',
                        telegram_id, request.scene, i + 1, PHOTO_SET_SIZE, retry_code, retry_stage, ','.join(retry_categories) or '-',
                        getattr(retry_exc, 'request_id', None), retry_msg[:700],
                    )
                    if outputs:
                        break
                    try:
                        logger.info('OpenAI final safe single-reference retry user=%s scene=%s frame=%s/%s', telegram_id, request.scene, i + 1, PHOTO_SET_SIZE)
                        photo = await _openai_one_frame(character, telegram_id, request, i, safe_retry=True, single_reference=True, character_id=character_id)
                        track_event(ensure_user(telegram_id), 'photo_single_reference_retry_success', metadata={'scene': request.scene, 'frame': i + 1, 'provider': 'openai', 'original_reason': retry_code or code or 'bad_request'})
                    except Exception as final_exc:
                        raise PhotoGenerationError('openai', retry_code or code or 'bad_request') from final_exc
                except Exception as retry_exc:
                    logger.warning('OpenAI safe retry transport failure user=%s scene=%s frame=%s/%s type=%s', telegram_id, request.scene, i + 1, PHOTO_SET_SIZE, type(retry_exc).__name__)
                    if outputs:
                        break
                    raise PhotoGenerationError('openai', type(retry_exc).__name__) from retry_exc
            elif outputs:
                break
            else:
                # Some OpenAI-compatible gateways lag behind the official API and
                # may reject an image array even though gpt-image-2 itself supports
                # multiple inputs. One fully-clothed single-reference retry keeps
                # the bot usable without weakening provider safety.
                try:
                    logger.info('OpenAI compatibility retry single-reference user=%s scene=%s frame=%s/%s original_code=%s', telegram_id, request.scene, i + 1, PHOTO_SET_SIZE, code)
                    photo = await _openai_one_frame(character, telegram_id, request, i, safe_retry=True, single_reference=True, character_id=character_id)
                    track_event(ensure_user(telegram_id), 'photo_single_reference_retry_success', metadata={'scene': request.scene, 'frame': i + 1, 'provider': 'openai', 'original_reason': code or 'bad_request'})
                except Exception as retry_exc:
                    logger.warning('OpenAI compatibility retry failed user=%s scene=%s frame=%s/%s type=%s', telegram_id, request.scene, i + 1, PHOTO_SET_SIZE, type(retry_exc).__name__)
                    raise PhotoGenerationError('openai', code or 'bad_request') from retry_exc
        except Exception as exc:
            if outputs:
                logger.warning('OpenAI partial set user=%s scene=%s delivered=%s/%s stopped_reason=%s', telegram_id, request.scene, len(outputs), PHOTO_SET_SIZE, type(exc).__name__)
                break
            raise

        outputs.append(photo)
        frame_elapsed = time.monotonic() - frame_started
        track_event(ensure_user(telegram_id), 'photo_frame_ready', value=frame_elapsed, metadata={'scene': request.scene, 'frame': i + 1, 'provider': 'openai'})
        if i == 0:
            track_event(ensure_user(telegram_id), 'photo_first_frame_ready', value=frame_elapsed, metadata={'scene': request.scene, 'provider': 'openai'})
        if on_frame:
            await on_frame(photo, i)
    if not outputs:
        raise PhotoGenerationError('openai', 'no_image')
    return outputs


def _seedream_safe_retry_request(request: PhotoRequest) -> PhotoRequest:
    """Make one moderation-safe retry without disabling or bypassing provider safety.

    The retry removes high-intensity glamour wording and uses opaque, fully covered fashion.
    """
    season = request.season or _default_season()
    if request.scene in {'personal', 'lingerie', 'nude', 'tease'}:
        outfit = 'an elegant opaque lingerie fashion set with full garment coverage, no sheer fabric, tasteful catalog styling'
    else:
        outfit = (
            'an elegant opaque fitted midi dress with tasteful mainstream fashion styling'
            if season != 'summer' else
            'an elegant lightweight opaque summer midi dress with tasteful mainstream fashion styling'
        )
    return replace(
        request,
        clothing=outfit,
        pack_outfits=tuple(outfit for _ in range(PHOTO_SET_SIZE)),
        mood='natural, confident, tasteful',
        angle='neutral three-quarter or full-body fashion framing',
    )


async def _run_seedream_set(
    character: dict,
    telegram_id: int,
    request: PhotoRequest,
    on_frame: Callable[[GeneratedPhoto, int], Awaitable[None]] | None = None,
    *,
    character_id: str = CHARACTER_ID,
    frames: int = PHOTO_SET_SIZE,
) -> list[GeneratedPhoto]:
    ref = _seedream_reference_path(character)
    reference_uri = _file_data_uri(ref)
    out: list[GeneratedPhoto] = []
    logger.info(
        'Seedream set request user=%s scene=%s reference=%s target_count=%s per_request=1 timeout=%ss retries=%s',
        telegram_id, request.scene, ref.name, frames, FAL_TIMEOUT_SECONDS, FAL_RETRIES,
    )
    allow_adult = request.scene in SEEDREAM_ADULT_SCENES
    for i in range(frames):
        prompt = _build_prompt(request, i, seedream=True, relationship_level=get_relationship_level(telegram_id, character_id), character_id=character_id) + (
            '\nCreate exactly ONE photo for this shot. Keep the same hairstyle, location and face identity '
            'as the other photos in this set; her body always follows the declared BODY IDENTITY — never the reference silhouette. '
            'Make this framing clearly different from the previous shot while staying in the same photo session.'
        )
        frame_started = time.monotonic()
        try:
            result = await _seedream_request(prompt, [reference_uri], 1, request_label=f'{request.scene}:{i + 1}/{PHOTO_SET_SIZE}', allow_adult=allow_adult)
        except PhotoGenerationError as exc:
            # One safe retry on provider content validation. fal rejects adult
            # wording with its own API-level moderation (400/403/422/451) even
            # when the model safety checker is disabled — the retry simplifies
            # the prompt; it does not disable safety.
            if exc.reason.startswith(('HTTP 400', 'HTTP 403', 'HTTP 422', 'HTTP 451')):
                retry_request = _seedream_safe_retry_request(request)
                retry_prompt = _build_prompt(retry_request, i, seedream=True, relationship_level=min(get_relationship_level(telegram_id, character_id), 4), character_id=character_id, force_safe=True) + (
                    '\nSAFE RETRY: tasteful fully covered fashion, opaque garment, neutral pose, no nudity, no body-part emphasis. Even for private scenes the outfit stays fully opaque and covered. Create exactly ONE photo.'
                )
                try:
                    logger.info('Seedream safe retry user=%s scene=%s frame=%s/%s', telegram_id, request.scene, i + 1, PHOTO_SET_SIZE)
                    result = await _seedream_request(retry_prompt, [reference_uri], 1, request_label=f'{request.scene}:{i + 1}/{PHOTO_SET_SIZE}:safe')
                    track_event(ensure_user(telegram_id), 'photo_safe_retry_success', metadata={'scene': request.scene, 'frame': i + 1, 'provider': 'seedream45'})
                except PhotoGenerationError as retry_exc:
                    track_event(ensure_user(telegram_id), 'photo_frame_failed', metadata={'scene': request.scene, 'frame': i + 1, 'provider': 'seedream45', 'reason': retry_exc.reason})
                    if out:
                        logger.warning('Seedream partial set user=%s scene=%s delivered=%s/%s stopped_reason=%s', telegram_id, request.scene, len(out), PHOTO_SET_SIZE, retry_exc.reason)
                        break
                    raise
            else:
                track_event(ensure_user(telegram_id), 'photo_frame_failed', metadata={'scene': request.scene, 'frame': i + 1, 'provider': 'seedream45', 'reason': exc.reason})
                if out:
                    logger.warning('Seedream partial set user=%s scene=%s delivered=%s/%s stopped_reason=%s', telegram_id, request.scene, len(out), PHOTO_SET_SIZE, exc.reason)
                    break
                raise
        images = result.get('images') if isinstance(result, dict) else None
        if not images:
            if out:
                break
            raise PhotoGenerationError('seedream45', 'no_image_url')
        item = images[0]
        if not (isinstance(item, dict) and item.get('url')):
            if out:
                break
            raise PhotoGenerationError('seedream45', 'no_image_url')
        photo = GeneratedPhoto(url=item['url'], provider='seedream45', estimated_cost_usd=FAL_ESTIMATED_COST_USD)
        out.append(photo)
        frame_elapsed = time.monotonic() - frame_started
        track_event(ensure_user(telegram_id), 'photo_frame_ready', value=frame_elapsed, metadata={'scene': request.scene, 'frame': i + 1, 'provider': 'seedream45'})
        if i == 0:
            track_event(ensure_user(telegram_id), 'photo_first_frame_ready', value=frame_elapsed, metadata={'scene': request.scene, 'provider': 'seedream45'})
        if on_frame:
            await on_frame(photo, i)
    if not out:
        raise PhotoGenerationError('seedream45', 'no_image_url')
    return out


def _guest_photo_block(host_id: str, guest_id: str, location_en: str = '') -> str:
    """V3.61.2: the second woman of a joint photo, kept apart from the host.

    V3.139.0: owner ТЗ (Задача 6) — the joint frame is always described in
    English, whatever language he chats in, and the two women are placed in
    fixed halves of the picture: «Photo of two distinct women. Left side: …
    Right side: … Location: … High detail, realistic.»"""
    host_name = _character_display_name_safe(host_id)
    guest_name = _character_display_name_safe(guest_id)
    try:
        guest_identity = _character_identity_lock(guest_id, seedream=True)[0]
    except Exception:
        guest_identity = ''
    return (
        'JOINT PHOTO OF TWO ADULT WOMEN — Photo of two distinct women, one real photo of two friends. '
        f'Left side: {host_name}, exactly the woman described above. '
        f'Right side: {guest_name}. {guest_identity}'
        f'Location: {location_en.strip() or "the same place as described above"}. High detail, realistic. '
        f'They stand side by side or close, like a real selfie or mirror photo of two friends. '
        f'{host_name}\'s face and hair come ONLY from reference images 1–2; {guest_name}\'s face and hair come ONLY from '
        f'reference images 3–4. They are two clearly different women: never merge their faces, never swap hair or skin tone, '
        f'never draw a third person. Both are adults. '
    )


def _character_display_name_safe(character_id: str) -> str:
    try:
        from services.chat_guest_service import character_name
        return character_name(character_id) or 'She'
    except Exception:
        return 'She'


async def _run_spicy_set(
    character: dict,
    telegram_id: int,
    request: PhotoRequest,
    on_frame: Callable[[GeneratedPhoto, int], Awaitable[None]] | None = None,
    *,
    character_id: str = CHARACTER_ID,
    frames: int = PHOTO_SET_SIZE,
) -> list[GeneratedPhoto]:
    """V3.56.1: the owner's primary scene engine — SpicyAPI Seedream 5.0 edit.

    Same seedream-flavoured prompt the fal leg builds (identity lock, per-frame
    rotation), the same two canonical reference URLs the «Наедине» pipeline uses
    (i=0 face, i=1 look — both portrait crops, so the body rides on the BODY
    IDENTITY text plus V3.56.3 frame chaining), but every scene — public ones
    included — renders here because the owner judged its quality above fal's.
    `_spicyapi_render` never
    raises: None means «this engine produced nothing» and the caller walks to
    fal. The spend is ledgered inside `_spicyapi_render` on the createTask event.
    """
    from services.private_photo_service import _spicyapi_render, spicyapi_breaker_open, spicyapi_last_error
    refs = [f'{PUBLIC_BASE_URL}/webapp/photo/{character_id}?i=0',
            f'{PUBLIC_BASE_URL}/webapp/photo/{character_id}?i=1']
    out: list[GeneratedPhoto] = []
    guest_block = ''
    if request.with_guest:
        # V3.61.2: both girls in one frame — the guest's own canonical
        # references ride as images 3–4 and her identity text is declared apart.
        refs += [f'{PUBLIC_BASE_URL}/webapp/photo/{request.with_guest}?i=0',
                 f'{PUBLIC_BASE_URL}/webapp/photo/{request.with_guest}?i=1']
        guest_block = _guest_photo_block(
            character_id, request.with_guest,
            request.location or SCENES.get(request.scene, SCENES['selfie']))
    # V3.56.3: figure chaining. The canonical references are face crops, so the
    # BODY IDENTITY text is the only body anchor — and Seedream re-improvises the
    # figure every frame (the owner watched bust and hips «jump» inside one set).
    # Frames 2..N therefore also receive the previous shot as a third reference
    # (the provider's signed asset URL, alive ~20 min — a frame takes ~1) and are
    # ordered to copy that body exactly.
    prev_url: str | None = None
    logger.info('SpicyAPI set request user=%s scene=%s target_count=%s', telegram_id, request.scene, frames)
    for i in range(frames):
        frame_refs = refs + ([prev_url] if prev_url else [])
        prompt = _build_prompt(request, i, seedream=True, relationship_level=get_relationship_level(telegram_id, character_id),
                               character_id=character_id, duo_block=guest_block) + (
            '\nCreate exactly ONE photo for this shot. Keep the same hairstyle, location and face identity '
            'as the other photos in this set; her body always follows the declared BODY IDENTITY — never the reference silhouette. '
            'Her figure is locked for this entire shoot: exactly the silhouette, bust size, waist and hips '
            'declared in her BODY IDENTITY, soft feminine torso with no visible abs — '
            'never draw her bigger, slimmer, flatter or smaller-chested than declared. '
            'Make this framing clearly different from the previous shot while staying in the same photo session.'
        )
        if prev_url:
            prompt += (
                '\nREFERENCE IMAGE 3 is the PREVIOUS photo of this same shoot: reproduce her exact body from image 3 — '
                'same bust size and shape, same waist width, same hip and rear proportions — so both photos show one identical body. '
                'Take face and hair identity from images 1–2 only.'
            )
        if spicyapi_breaker_open(SPICYAPI_IMAGE_MODEL, frame_refs):
            # V3.58.1: engine known-dead right now — hand over to fal without
            # waiting and without logging another ❌ for the same outage.
            if out:
                break
            raise PhotoGenerationError('spicyapi', _spicy_reason('breaker_open', spicyapi_last_error()))
        frame_started = time.monotonic()
        data, frame_url = await _spicyapi_render(SPICYAPI_IMAGE_MODEL, prompt, frame_refs, scene=f'scene:{request.scene}', return_url=True)
        record_provider('spicyapi', bool(data), None if data else spicyapi_last_error())
        if not data:
            track_event(ensure_user(telegram_id), 'photo_frame_failed', metadata={'scene': request.scene, 'frame': i + 1, 'provider': 'spicyapi', 'reason': 'empty_result'})
            if out:
                logger.warning('SpicyAPI partial set user=%s scene=%s delivered=%s/%s', telegram_id, request.scene, len(out), frames)
                break
            raise PhotoGenerationError('spicyapi', _spicy_reason('empty_result', spicyapi_last_error()))
        prev_url = frame_url
        if guest_block:
            # a joint photo keeps images 3–4 for the guest, so no frame chaining.
            prev_url = None
        photo = GeneratedPhoto(data=data, provider='spicyapi', estimated_cost_usd=SPICYAPI_ESTIMATED_COST_USD)
        out.append(photo)
        frame_elapsed = time.monotonic() - frame_started
        track_event(ensure_user(telegram_id), 'photo_frame_ready', value=frame_elapsed, metadata={'scene': request.scene, 'frame': i + 1, 'provider': 'spicyapi'})
        if i == 0:
            track_event(ensure_user(telegram_id), 'photo_first_frame_ready', value=frame_elapsed, metadata={'scene': request.scene, 'provider': 'spicyapi'})
        if on_frame:
            await on_frame(photo, i)
    if not out:
        raise PhotoGenerationError('spicyapi', 'no_image')
    return out


def _spicy_reason(code: str, last: str | None) -> str:
    last = (last or '').strip()
    return f'{code}:{last[:160]}' if last else code


def choose_photo_provider(telegram_id: int, request: PhotoRequest) -> str:
    # V3.56.1: owner's call — SpicyAPI renders every scene (better identity and
    # quality than fal, and cheaper per job). It rides first whenever the key is
    # present; _run_routed_photo_set walks to fal when SpicyAPI produces nothing.
    if PHOTO_SPICY_FIRST and SPICYAPI_KEY:
        return 'spicyapi'
    mode = PHOTO_ROUTER_MODE
    if mode in {'openai', 'gpt', 'gpt-image-2'}:
        return 'openai' if OPENAI_IMAGE_AVAILABLE else ('gemini_image' if GEMINI_IMAGE_ENABLED else 'seedream45')
    if mode in {'fal', 'seedream', 'seedream45'}:
        return 'seedream45'
    if mode in {'gemini', 'nano', 'nanobanana', 'nano-banana'}:
        return 'gemini_image' if GEMINI_IMAGE_ENABLED else ('openai' if OPENAI_IMAGE_AVAILABLE else 'seedream45')

    # HYBRID routing (opt-in since V3.44.19 — the default is the strict 'fal'
    # branch above, the owner's decision «фото через fal.ai, OpenRouter —
    # только общение»):
    # - intimate/private/bold scenes -> Seedream
    # - ordinary fully-clothed scenes -> Gemini Image (primary) -> OpenAI (fallback)
    combined = ' '.join([request.scene, request.clothing, request.location, request.angle]).lower()
    if request.scene in SEEDREAM_ADULT_SCENES or INTIMATE_STYLE.search(combined):
        logger.info('Hybrid photo route scene=%s -> seedream45', request.scene)
        return 'seedream45'
    if GEMINI_IMAGE_ENABLED and GEMINI_API_KEY:
        logger.info('Hybrid photo route scene=%s -> gemini_image (%s)', request.scene, GEMINI_IMAGE_MODEL)
        return 'gemini_image'
    if OPENAI_IMAGE_AVAILABLE:
        logger.info('Hybrid photo route scene=%s -> openai', request.scene)
        return 'openai'
    # Ultimate fallback to Seedream
    logger.info('Hybrid photo route scene=%s -> seedream45 (no Gemini/OpenAI)', request.scene)
    return 'seedream45'


async def _run_routed_photo_set(
    character: dict,
    telegram_id: int,
    resolved: PhotoRequest,
    provider: str,
    on_frame: Callable[[GeneratedPhoto, int], Awaitable[None]] | None = None,
    *,
    character_id: str = CHARACTER_ID,
    frames: int = PHOTO_SET_SIZE,
) -> list[GeneratedPhoto]:
    # V3.44.18: refuse BEFORE touching any provider once the daily media budget
    # is gone. Raising here (instead of inside the engines) means the caller's
    # existing failure branch still refunds the peaches/Stars it charged.
    if not spend_service.image_generation_allowed():
        logger.warning('PHOTO ROUTE blocked by daily image budget user=%s scene=%s', telegram_id, resolved.scene)
        track_event(ensure_user(telegram_id), 'photo_budget_blocked', metadata={'scene': resolved.scene})
        raise PhotoGenerationError('budget', 'daily_image_budget_exhausted')
    try:
        if provider == 'spicyapi':
            # V3.64.5: owner's call «фал вообще убери, всё идёт в Спайси». fal has
            # been dead since 15.10 (ReadError on every route), so the fallback
            # only added ~28s of waiting before the same failure. A SpicyAPI
            # miss now surfaces straight away and the caller refunds.
            return await _run_spicy_set(character, telegram_id, resolved, on_frame=on_frame, character_id=character_id, frames=frames)
        if provider == 'seedream45':
            try:
                return await _run_seedream_set(character, telegram_id, resolved, on_frame=on_frame, character_id=character_id, frames=frames)
            except PhotoGenerationError as exc:
                # V3.19.2/3: a Seedream failure (HTTP 422 policy/validation etc.)
                # must not kill the photo — walk the remaining engines, and only
                # surface an error when every one of them failed. Each fallback
                # is wrapped: one broken engine must not stop the chain.
                # V3.24.0: the final error carries the whole engine chain
                # (seedream45/... → gemini_image/...) so the owner sees which
                # engine failed FIRST and why, not just the last fallback.
                chain = [f'seedream45/{exc.reason}']
                last_error = exc
                # V3.44.19: strict fal mode — a fal failure must not quietly
                # re-route photo money onto other providers' accounts (the
                # owner's rule: photos on fal.ai only, OpenRouter is chat-only);
                # the user gets the refund instead. The full engine chain stays
                # available in 'hybrid' mode via PHOTO_ROUTER_MODE.
                if PHOTO_ROUTER_MODE == 'hybrid' and GEMINI_IMAGE_ENABLED and GEMINI_API_KEY:
                    try:
                        logger.warning('PHOTO ROUTE FALLBACK user=%s scene=%s from=seedream45 to=gemini_image reason=%s', telegram_id, resolved.scene, exc.reason)
                        track_event(ensure_user(telegram_id), 'photo_provider_fallback', metadata={'scene': resolved.scene, 'from': 'seedream45', 'to': 'gemini_image', 'reason': exc.reason})
                        return await _run_gemini_set(character, telegram_id, resolved, on_frame=on_frame, character_id=character_id, frames=frames)
                    except PhotoGenerationError as gemini_exc:
                        logger.warning('PHOTO ROUTE FALLBACK FAILED user=%s scene=%s engine=gemini_image reason=%s', telegram_id, resolved.scene, gemini_exc.reason)
                        chain.append(f'gemini_image/{gemini_exc.reason}')
                        last_error = gemini_exc
                if PHOTO_ROUTER_MODE == 'hybrid' and OPENAI_IMAGE_AVAILABLE:
                    try:
                        logger.warning('PHOTO ROUTE FALLBACK user=%s scene=%s from=seedream45 to=openai reason=%s', telegram_id, resolved.scene, exc.reason)
                        track_event(ensure_user(telegram_id), 'photo_provider_fallback', metadata={'scene': resolved.scene, 'from': 'seedream45', 'to': 'openai', 'reason': exc.reason})
                        return await _run_openai_set(character, telegram_id, resolved, on_frame=on_frame, character_id=character_id, frames=frames)
                    except PhotoGenerationError as openai_exc:
                        logger.warning('PHOTO ROUTE FALLBACK FAILED user=%s scene=%s engine=openai reason=%s', telegram_id, resolved.scene, openai_exc.reason)
                        chain.append(f'openai/{openai_exc.reason}')
                        last_error = openai_exc
                if len(chain) > 1:
                    raise PhotoGenerationError('seedream45', ' → '.join(chain)) from last_error
                raise last_error
        if provider == 'gemini_image':
            try:
                return await _run_gemini_set(character, telegram_id, resolved, on_frame=on_frame, character_id=character_id, frames=frames)
            except PhotoGenerationError as exc:
                # Gemini failed: try OpenAI if available, otherwise fall back to Seedream.
                if OPENAI_IMAGE_AVAILABLE:
                    try:
                        logger.warning('PHOTO ROUTE FALLBACK user=%s scene=%s from=gemini_image to=openai reason=%s', telegram_id, resolved.scene, exc.reason)
                        track_event(ensure_user(telegram_id), 'photo_provider_fallback', metadata={'scene': resolved.scene, 'from': 'gemini_image', 'to': 'openai', 'reason': exc.reason})
                        return await _run_openai_set(character, telegram_id, resolved, on_frame=on_frame, character_id=character_id, frames=frames)
                    except PhotoGenerationError as openai_exc:
                        logger.warning('PHOTO ROUTE FALLBACK FAILED user=%s scene=%s engine=openai reason=%s', telegram_id, resolved.scene, openai_exc.reason)
                logger.warning('PHOTO ROUTE FALLBACK user=%s scene=%s from=gemini_image to=seedream45 reason=%s', telegram_id, resolved.scene, exc.reason)
                track_event(ensure_user(telegram_id), 'photo_provider_fallback', metadata={'scene': resolved.scene, 'from': 'gemini_image', 'to': 'seedream45', 'reason': exc.reason})
                return await _run_seedream_set(character, telegram_id, resolved, on_frame=on_frame, character_id=character_id, frames=frames)
        # provider == 'openai'
        if OPENAI_IMAGE_AVAILABLE:
            return await _run_openai_set(character, telegram_id, resolved, on_frame=on_frame, character_id=character_id, frames=frames)
        # OpenAI requested but not available: use Gemini or Seedream
        if GEMINI_IMAGE_ENABLED and GEMINI_API_KEY:
            return await _run_gemini_set(character, telegram_id, resolved, on_frame=on_frame, character_id=character_id, frames=frames)
        return await _run_seedream_set(character, telegram_id, resolved, on_frame=on_frame, character_id=character_id, frames=frames)
    except BadRequestError as exc:
        body = getattr(exc, 'body', None) or {}
        err = body.get('error', body) if isinstance(body, dict) else {}
        code = err.get('code') if isinstance(err, dict) else None
        msg = str(err.get('message', '')) if isinstance(err, dict) else str(exc)
        logger.warning('OpenAI image failed user=%s scene=%s code=%s message=%s', telegram_id, resolved.scene, code, msg[:700])
        raise PhotoGenerationError('openai', code or 'bad_request') from exc


async def generate_photo_set(telegram_id: int, request: PhotoRequest, on_frame: Callable[[GeneratedPhoto, int], Awaitable[None]] | None = None, *, character_id: str = CHARACTER_ID, frames: int = PHOTO_SET_SIZE) -> tuple[list[GeneratedPhoto], PhotoRequest]:
    from services import spend_service
    spend_service.set_spend_user(telegram_id)
    character = resolve_character(character_id)
    # Pinterest-style variety: underspecified ordinary requests get a fresh
    # curated/LLM idea (location + camera). Explicit and private requests pass through.
    request, idea_source = await enrich_request_with_idea(telegram_id, request, character_id=character_id)
    if idea_source:
        track_event(ensure_user(telegram_id), 'photo_idea_applied', metadata={'scene': request.scene, 'source': idea_source})
    resolved = _resolve_request(telegram_id, request, character_id=character_id)
    provider = choose_photo_provider(telegram_id, resolved)
    logger.info(
        'PHOTO ROUTE selected user=%s scene=%s provider=%s gemini_enabled=%s gemini_key_present=%s model=%s',
        telegram_id, resolved.scene, provider, bool(GEMINI_IMAGE_ENABLED), bool(GEMINI_API_KEY), GEMINI_IMAGE_MODEL if provider == 'gemini_image' else '-',
    )
    try:
        return await _run_routed_photo_set(character, telegram_id, resolved, provider, on_frame=on_frame, character_id=character_id, frames=frames), resolved
    except PhotoAppDeliveryError:
        raise
    except PhotoGenerationError:
        # V3.22.0: keep the original provider/reason — the old wrapper replaced
        # the real reason with the exception class name ("PhotoGenerationError"),
        # hiding whether fal refused the prompt, timed out or ran out of credits.
        logger.exception('photo provider failed provider=%s user=%s scene=%s', provider, telegram_id, request.scene)
        raise
    except Exception as exc:
        logger.exception('photo provider failed provider=%s user=%s scene=%s', provider, telegram_id, request.scene)
        raise PhotoGenerationError(provider, type(exc).__name__) from exc


async def generate_photo(telegram_id: int, request: PhotoRequest) -> GeneratedPhoto:
    """Compatibility wrapper for callers/tests that expect one result."""
    photos, _ = await generate_photo_set(telegram_id, request)
    return photos[0]


def _bump_photo_usage(telegram_id: int, delivery_type: str, character_id: str = CHARACTER_ID):
    """Count one set-level request against the daily quota (no delivery row)."""
    uid = ensure_user(telegram_id)
    with SessionLocal() as session:
        usage = session.scalar(select(PhotoDailyUsage).where(
            PhotoDailyUsage.user_id == uid,
            PhotoDailyUsage.character_id == character_id,
            PhotoDailyUsage.usage_date == _today(),
        ))
        if not usage:
            usage = PhotoDailyUsage(user_id=uid, character_id=character_id, usage_date=_today())
            session.add(usage)
            session.flush()
        # One generated SET counts as one free/paid request, regardless of set size.
        if delivery_type == 'free':
            usage.free_used += 1
        elif delivery_type in {'credit', 'paid'}:
            usage.paid_used += 1
        session.commit()
    # V3.167.14 этап 6: +3 очка раскрепощённости за успешно доставленный кадр.
    try:
        from services import spicy_confidence
        spicy_confidence.apply_progress(telegram_id, character_id, kind='photo')
    except Exception:
        logger.warning('spicy photo progress failed user=%s character=%s', telegram_id, character_id, exc_info=True)


def _insert_delivery_row(
    telegram_id: int,
    scene: str,
    delivery_type: str,
    *,
    file_id=None,
    url=None,
    provider: str = 'unknown',
    estimated_cost_usd: float = 0.0,
    character_id: str = CHARACTER_ID,
    full_bytes: bytes | None = None,
    community_shared: bool = False,
    source_delivery_id: int | None = None,
) -> int:
    """Create a PhotoDelivery row and return its id (button/per-frame anchor).

    Pass ``full_bytes`` (the raw image bytes from the generation result) to let
    paid gallery downloads re-send the uncompressed file as a Telegram document.
    Set ``community_shared=True`` on AI-generated frames so other users can
    reuse them via the community pool. ``source_delivery_id`` links a
    re-delivered community photo back to the original generation row.
    """
    uid = ensure_user(telegram_id)
    with SessionLocal() as session:
        row = PhotoDelivery(
            user_id=uid,
            character_id=character_id,
            scene=scene,
            delivery_type=delivery_type,
            telegram_file_id=file_id,
            image_url=url,
            provider=provider,
            estimated_cost_usd=estimated_cost_usd,
            full_resolution_bytes=full_bytes,
            community_shared=community_shared,
            source_delivery_id=source_delivery_id,
        )
        session.add(row)
        session.commit()
        return int(row.id)


def _photo_mime_type(data: bytes) -> str:
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return 'image/webp'
    if data.startswith((b'GIF87a', b'GIF89a')):
        return 'image/gif'
    return 'image/jpeg'


async def _deliver_app_photo(
    bot: Bot,
    telegram_id: int,
    scene: str,
    delivery_type: str,
    app_delivery: AppPhotoDelivery,
    *,
    data: bytes | None = None,
    file_id: str | None = None,
    url: str | None = None,
    caption: str = '',
    provider: str = 'unknown',
    estimated_cost_usd: float = 0.0,
    character_id: str = CHARACTER_ID,
    community_shared: bool = False,
    source_delivery_id: int | None = None,
) -> int:
    try:
        if not data and file_id:
            downloaded = await bot.download(file_id)
            data = downloaded.getvalue() if downloaded is not None else None
        if not data and url:
            data = await _download_result_bytes(GeneratedPhoto(url=url, provider=provider))
        if not data:
            raise ValueError('empty_photo_bytes')
        mime = _photo_mime_type(data)
        row_id = _insert_delivery_row(
            telegram_id, scene, delivery_type, url=url, provider=provider,
            estimated_cost_usd=estimated_cost_usd, character_id=character_id,
            full_bytes=data, community_shared=community_shared,
            source_delivery_id=source_delivery_id,
        )
        await app_delivery(data, mime, row_id, caption)
        # Best-effort marker after successful persistence, never before it.
        # This changes only ordinary pose rotation, not prices or daily usage.
        try:
            track_event(ensure_user(telegram_id), 'photo_app_delivered',
                        character_id=character_id, value=row_id)
        except Exception:
            pass  # Analytics failure cannot turn a delivered frame into a refund.
        return row_id
    except Exception as exc:
        raise PhotoAppDeliveryError('app_delivery_failed') from exc


def _attach_delivery_file(delivery_id: int, file_id: str | None):
    """Store the sent Telegram file_id so the animate button works later."""
    if not file_id:
        return
    with SessionLocal() as session:
        row = session.get(PhotoDelivery, int(delivery_id))
        if row is not None:
            row.telegram_file_id = file_id
            session.commit()


def _record(telegram_id: int, scene: str, delivery_type: str, file_id=None, url=None, provider='unknown', estimated_cost_usd=0.0, *, character_id: str = CHARACTER_ID, full_bytes: bytes | None = None):
    _bump_photo_usage(telegram_id, delivery_type, character_id)
    return _insert_delivery_row(
        telegram_id, scene, delivery_type,
        file_id=file_id, url=url, provider=provider,
        estimated_cost_usd=estimated_cost_usd, character_id=character_id,
        full_bytes=full_bytes,
    )


# ── Community photo pool ────────────────────────────────────────────────────
# AI-generated photos are shared between users: when User B requests the same
# character+scene that User A already generated, User B receives User A's photo
# instead of paying for a new generation. Only generate new photos when the
# pool has nothing unseen for this user.

def _delivery_media_filter(include_app: bool):
    sendable = PhotoDelivery.telegram_file_id.isnot(None)
    if include_app:
        sendable = sendable | PhotoDelivery.full_resolution_bytes.isnot(None)
    return sendable


def _delivery_app_media(row: PhotoDelivery) -> dict:
    data = row.full_resolution_bytes
    return {'media_bytes': data, 'mime_type': _photo_mime_type(data) if data else None}


def query_community_photos(
    telegram_id: int,
    character_id: str,
    scene: str,
    relationship_level: int,
    count: int = 1,
    *,
    include_app: bool = False,
) -> list[dict]:
    """Return up to ``count`` random unseen community-shared photos.

    A community photo is any AI-generated delivery (community_shared=True) for
    the given character+scene that the current user has not yet received.
    Results are randomly ordered so different users see different photos first.
    """
    if not COMMUNITY_POOL_ENABLED:
        return []
    uid = ensure_user(telegram_id)
    with SessionLocal() as session:
        # All delivery IDs this user already received (own generations +
        # community re-deliveries). Used to exclude photos they have seen.
        seen_ids = set(session.scalars(
            select(PhotoDelivery.id).where(PhotoDelivery.user_id == uid)
        ).all())
        # Source delivery IDs from community re-deliveries — the original
        # AI generation that this user already received indirectly.
        source_ids = set(session.scalars(
            select(PhotoDelivery.source_delivery_id).where(
                PhotoDelivery.user_id == uid,
                PhotoDelivery.source_delivery_id.isnot(None),
            )
        ).all())
        exclude = seen_ids | source_ids

        query = select(PhotoDelivery).where(
            PhotoDelivery.community_shared.is_(True),
            PhotoDelivery.character_id == character_id,
            PhotoDelivery.scene == scene,
            _delivery_media_filter(include_app),
        )
        if exclude:
            query = query.where(PhotoDelivery.id.notin_(exclude))
        # Random order so the pool is spread evenly across users.
        query = query.order_by(func.random()).limit(count)
        rows = session.scalars(query).all()
        return [
            {
                'id': int(r.id),
                'telegram_file_id': r.telegram_file_id,
                'scene': r.scene,
                'provider': r.provider,
                **(_delivery_app_media(r) if include_app else {}),
            }
            for r in rows
        ]


# V3.19.14: owner moderation for the community pool. Every AI-generated public
# frame enters the shared pool (community_shared=True); these helpers let the
# owner browse the pool newest-first and exclude bad frames so other users
# never receive them. Removal only flips the flag — the original owner keeps
# the photo in their own history.
def admin_pool_count() -> int:
    """How many deliveries are currently shared into the community pool."""
    with SessionLocal() as session:
        return int(session.scalar(
            select(func.count(PhotoDelivery.id)).where(PhotoDelivery.community_shared.is_(True))
        ) or 0)


def admin_pool_get(delivery_id: int) -> dict | None:
    with SessionLocal() as session:
        r = session.get(PhotoDelivery, delivery_id)
        if not r or not r.telegram_file_id:
            return None
        return {
            'id': int(r.id),
            'scene': r.scene,
            'provider': r.provider,
            'character_id': r.character_id,
            'telegram_file_id': r.telegram_file_id,
            'community_shared': bool(r.community_shared),
            'created_at': r.created_at,
        }


def admin_pool_latest_id() -> int | None:
    """Newest delivery id currently in the pool (with a sendable file)."""
    with SessionLocal() as session:
        return session.scalar(
            select(PhotoDelivery.id).where(
                PhotoDelivery.community_shared.is_(True),
                PhotoDelivery.telegram_file_id.isnot(None),
            ).order_by(PhotoDelivery.id.desc()).limit(1)
        )


def admin_pool_neighbor(delivery_id: int, direction: str) -> int | None:
    """Adjacent pool id in newest-first order: 'next' = older, 'prev' = newer."""
    with SessionLocal() as session:
        cond = PhotoDelivery.id < delivery_id if direction == 'next' else PhotoDelivery.id > delivery_id
        q = select(PhotoDelivery.id).where(
            PhotoDelivery.community_shared.is_(True),
            PhotoDelivery.telegram_file_id.isnot(None),
            cond,
        ).order_by(PhotoDelivery.id.desc() if direction == 'next' else PhotoDelivery.id.asc()).limit(1)
        return session.scalar(q)


def admin_pool_set_shared(delivery_id: int, shared: bool) -> bool:
    """Include/exclude a delivery from the community pool (moderation)."""
    with SessionLocal() as session:
        r = session.get(PhotoDelivery, delivery_id)
        if not r:
            return False
        r.community_shared = bool(shared)
        session.commit()
        return True


_PRIVATE_LIBRARY_SCENES = {'personal', 'lingerie', 'private_fashion', 'peek', 'dressing', 'nude', 'tease'}

# At-home scenes that switch to lingerie-only looks at high relationship
# levels (5-6): once she trusts the user this much, her at-home selfie/home/
# mirror sets are shot in only her lingerie. These generations must never
# enter the community pool (they would leak to low-level users requesting the
# same scenes), and the pool must never serve low-level clothed photos back
# into a high-level home set.
HOME_LINGERIE_SCENES = {'selfie', 'home', 'mirror'}

def _library_fallback_scene_order(requested_scene: str, relationship_level: int) -> tuple[str, ...]:
    """Return compatible ordinary-library scenes in graceful-fallback order."""
    requested_group = SCENE_GROUP.get(requested_scene)
    ordinary = [
        scene for scene, min_level in SCENE_LEVELS.items()
        if min_level <= relationship_level and scene not in _PRIVATE_LIBRARY_SCENES
    ]
    same_group = [scene for scene in ordinary if scene != requested_scene and SCENE_GROUP.get(scene) == requested_group]
    other = [scene for scene in ordinary if scene != requested_scene and scene not in same_group]
    return tuple([requested_scene] + same_group + other)


async def _deliver_library_failure_fallback(
    bot: Bot,
    chat_id: int,
    telegram_id: int,
    request: PhotoRequest,
    caption: str | None = None,
    *,
    character_id: str = CHARACTER_ID,
    app_delivery: AppPhotoDelivery | None = None,
):
    """Serve a ready library photo when ordinary free AI generation fails."""
    if request.scene in _PRIVATE_LIBRARY_SCENES:
        return []
    level = get_relationship_level(telegram_id, character_id)
    scene_order = _library_fallback_scene_order(request.scene, level)
    pack = choose_fallback_pack(telegram_id, character_id, level, scene_order)
    if not pack or not pack.photos:
        logger.warning('library failure fallback empty user=%s requested_scene=%s level=%s character=%s', telegram_id, request.scene, level, character_id)
        return []

    actual_caption = caption or random.choice(AUTO_CAPTIONS.get(pack.scene, ('вот 😌',)))
    fallback_caption = f'генерация сейчас капризничает, поэтому держи один из моих готовых кадров 😌\n\n{actual_caption}'
    sent_messages = []
    try:
        for idx, item in enumerate(pack.photos):
            if app_delivery is not None:
                row_id = await _deliver_app_photo(
                    bot, telegram_id, pack.scene, 'free', app_delivery,
                    file_id=item.file_id,
                    caption=_her(fallback_caption, character_id) if idx == 0 else '',
                    provider='telegram_library_fallback', character_id=character_id,
                )
                sent_messages.append(row_id)
                continue
            row_id = _insert_delivery_row(telegram_id, pack.scene, 'free', provider='telegram_library_fallback', estimated_cost_usd=0.0, character_id=character_id)
            sent = await bot.send_photo(
                chat_id, item.file_id, caption=_her(fallback_caption, character_id) if idx == 0 else None,
                reply_markup=_photo_action_markup(row_id, item),
            )
            _attach_delivery_file(row_id, sent.photo[-1].file_id if sent.photo else item.file_id)
            sent_messages.append(sent)
    except PhotoAppDeliveryError:
        raise
    except Exception:
        logger.exception('library failure fallback send failed user=%s requested_scene=%s pack=%s', telegram_id, request.scene, pack.pack_key)
        return []

    mark_pack_seen(telegram_id, pack.id)
    _bump_photo_usage(telegram_id, 'free', character_id=character_id)
    uid = ensure_user(telegram_id)
    track_event(uid, 'photo_library_fallback_served', metadata={
        'requested_scene': request.scene,
        'served_scene': pack.scene,
        'pack_key': pack.pack_key,
        'level': pack.relationship_level,
    })
    logger.info(
        'library failure fallback delivered user=%s requested_scene=%s served_scene=%s pack=%s count=%s',
        telegram_id, request.scene, pack.scene, pack.pack_key, len(sent_messages),
    )
    return sent_messages


async def _deliver_library_partial_topup(
    bot: Bot,
    chat_id: int,
    telegram_id: int,
    request: PhotoRequest,
    needed: int,
    *,
    character_id: str = CHARACTER_ID,
    app_delivery: AppPhotoDelivery | None = None,
):
    """Fill missing ordinary free/story frames from ready library content.

    This is deliberately a delivery-reliability layer, not a second AI retry.
    It never targets private/lingerie scenes and never unlocks content above the
    user's relationship level. Only actually sent item ids are marked seen.
    """
    if needed <= 0 or request.scene in _PRIVATE_LIBRARY_SCENES:
        return []
    level = get_relationship_level(telegram_id, character_id)
    scene_order = _library_fallback_scene_order(request.scene, level)
    sent_messages = []
    used_pack_ids: set[int] = set()

    while len(sent_messages) < needed:
        pack = choose_fallback_pack(telegram_id, character_id, level, scene_order)
        if not pack or not pack.photos or pack.id in used_pack_ids:
            break
        used_pack_ids.add(pack.id)
        remaining = needed - len(sent_messages)
        chosen_items = list(pack.photos[:remaining])
        sent_item_ids: list[int] = []
        try:
            for item in chosen_items:
                if app_delivery is not None:
                    row_id = await _deliver_app_photo(
                        bot, telegram_id, request.scene, 'free', app_delivery,
                        file_id=item.file_id, provider='telegram_library_topup',
                        character_id=character_id,
                    )
                    sent_messages.append(row_id)
                    sent_item_ids.append(int(item.item_id))
                    continue
                row_id = _insert_delivery_row(telegram_id, request.scene, 'free', provider='telegram_library_topup', estimated_cost_usd=0.0, character_id=character_id)
                sent = await bot.send_photo(
                    chat_id, item.file_id, reply_markup=_photo_action_markup(row_id, item),
                )
                _attach_delivery_file(row_id, sent.photo[-1].file_id if sent.photo else item.file_id)
                sent_messages.append(sent)
                sent_item_ids.append(int(item.item_id))
        except PhotoAppDeliveryError:
            raise
        except Exception:
            logger.exception(
                'library partial topup send failed user=%s requested_scene=%s pack=%s sent=%s/%s',
                telegram_id, request.scene, pack.pack_key, len(sent_messages), needed,
            )
            break

        # Keep collection progress truthful: only frames actually delivered are
        # item-seen. Mark the whole pack only when every item in it was delivered.
        if len(chosen_items) >= len(pack.photos):
            mark_pack_seen(telegram_id, pack.id)
        elif sent_item_ids:
            mark_items_seen(telegram_id, sent_item_ids)

        if len(sent_messages) >= needed:
            break

    if sent_messages:
        uid = ensure_user(telegram_id)
        track_event(uid, 'photo_library_partial_topup', metadata={
            'requested_scene': request.scene,
            'count': len(sent_messages),
            'target_missing': needed,
            'level': level,
        })
        logger.info(
            'PHOTO SET TOPUP user=%s scene=%s source=telegram_library added=%s requested_missing=%s final_gap=%s',
            telegram_id, request.scene, len(sent_messages), needed, max(0, needed - len(sent_messages)),
        )
    else:
        logger.warning('PHOTO SET TOPUP empty user=%s scene=%s requested_missing=%s level=%s', telegram_id, request.scene, needed, level)
    return sent_messages


async def deliver_photo(
    bot: Bot,
    chat_id: int,
    telegram_id: int,
    request: PhotoRequest,
    delivery_type: str = 'free',
    caption: str | None = None,
    *,
    character_id: str = CHARACTER_ID,
    skip_stage: bool = False,
    app_delivery: AppPhotoDelivery | None = None,
):
    """Return Telegram messages, or delivery IDs when using app_delivery."""
    stage = get_relationship_stage(telegram_id, character_id)
    if not skip_stage and not scene_allowed_for_stage(request.scene, stage, telegram_id):
        raise PermissionError('scene_locked')
    if requires_adult_confirmation(request) and not is_adult_confirmed(telegram_id):
        raise PermissionError('age_gate')
    if delivery_type == 'free' and not has_free_photo(telegram_id, character_id):
        raise PermissionError('quota')
    # V3.65.0: one credit = PEACH_SCALE peaches.
    if delivery_type == 'credit' and get_photo_credits(telegram_id) < PEACH_SCALE:
        raise PermissionError('no_credit')

    caption = _her(caption or random.choice(AUTO_CAPTIONS.get(request.scene, ('вот 😌',))), character_id)
    sent_messages = []

    async def _send_community_frame(cp: dict, idx: int, provider: str, record_type: str):
        if app_delivery is not None:
            sent = await _deliver_app_photo(
                bot, telegram_id, request.scene, record_type, app_delivery,
                data=cp.get('media_bytes'), file_id=cp['telegram_file_id'],
                caption=caption if idx == 0 else '', provider=provider,
                character_id=character_id, source_delivery_id=cp['id'],
            )
        else:
            row_id = _insert_delivery_row(
                telegram_id, request.scene, record_type, provider=provider,
                estimated_cost_usd=0.0, character_id=character_id, source_delivery_id=cp['id'],
            )
            sent = await bot.send_photo(
                chat_id, cp['telegram_file_id'], caption=caption if idx == 0 else None,
                reply_markup=_photo_action_markup(row_id),
            )
            _attach_delivery_file(row_id, sent.photo[-1].file_id if sent.photo else cp['telegram_file_id'])
        sent_messages.append(sent)

    # High-level at-home sets are lingerie-only (see _build_prompt): they must
    # neither be served from the community pool (which holds low-level clothed
    # photos of these scenes) nor feed their frames back into it.
    home_lingerie_mode = (
        request.scene in HOME_LINGERIE_SCENES
        and get_relationship_level(telegram_id, character_id) >= 5
    )
    # V3.116.0: a garment he gave her for today is in no shared photo — render fresh.
    try:
        from services.wardrobe_service import worn_today as _worn_today
        _gift_worn = _worn_today(telegram_id, character_id) is not None
    except Exception:
        _gift_worn = False
    # same pool rules as the at-home lingerie sets: not served from, not fed into the pool
    home_lingerie_mode = home_lingerie_mode or _gift_worn
    # V3.153.0: «🎁 Подарки» stays on her for good, so the pool is skipped only in
    # the scenes where his gift actually shows — on top of her clothes or on her
    # neck. On the street it is under them, and a shared frame costs nothing.
    try:
        from services import gift_shop_service
        _gs = gift_shop_service.photo_overrides(
            telegram_id, character_id, request.scene, SCENE_GROUP.get(request.scene, 'day_casual'))
    except Exception:
        _gs = {}
    home_lingerie_mode = home_lingerie_mode or bool(_gs.get('clothing') or _gs.get('accessory'))

    # Community pool first for free/story sets: when other users' AI
    # generations already cover this character+scene, serve the shared photos
    # instead of paying for a duplicate AI run. Paid credit sets always
    # generate fresh AI photos, and AI still runs whenever the pool has no
    # full unseen set for this user. Fresh AI frames keep feeding the pool
    # (community_shared in _send_frame).
    if (
        delivery_type in {'free', 'story'}
        and request.scene not in _PRIVATE_LIBRARY_SCENES
        and not home_lingerie_mode
        and COMMUNITY_POOL_ENABLED and COMMUNITY_POOL_FIRST
    ):
        level = get_relationship_level(telegram_id, character_id)
        community_photos = query_community_photos(telegram_id, character_id, request.scene, level, count=PHOTO_SET_SIZE, include_app=app_delivery is not None)
        if len(community_photos) >= PHOTO_SET_SIZE:
            for idx, cp in enumerate(community_photos[:PHOTO_SET_SIZE]):
                await _send_community_frame(cp, idx, provider='community_pool', record_type=delivery_type)
            _bump_photo_usage(telegram_id, delivery_type, character_id=character_id)
            uid = ensure_user(telegram_id)
            track_event(uid, 'photo_community_pool_served', metadata={'scene': request.scene, 'count': len(sent_messages)})
            logger.info('community pool served user=%s scene=%s count=%s', telegram_id, request.scene, len(sent_messages))
            return sent_messages

    # Paid sets and scenes the pool cannot cover generate fresh AI photos. The
    # community pool and curated library remain safety nets if AI fails.

    async def _send_frame(result: GeneratedPhoto, idx: int):
        if app_delivery is not None:
            row_id = await _deliver_app_photo(
                bot, telegram_id, request.scene, delivery_type, app_delivery,
                data=result.data, url=result.url, caption=caption if idx == 0 else '',
                provider=result.provider, estimated_cost_usd=result.estimated_cost_usd,
                character_id=character_id,
                community_shared=not home_lingerie_mode and request.scene not in ADULT_SCENES,
            )
            sent_messages.append(row_id)
            return
        item_caption = caption if idx == 0 else None
        # Capture the raw bytes so the paid gallery download can re-send this
        # frame uncompressed as a Telegram document. URL-only providers may
        # leave this empty — their frames just become view-only in the gallery.
        full_bytes = result.data or (await _download_result_bytes(result))
        row_id = _insert_delivery_row(
            telegram_id, request.scene, delivery_type,
            url=result.url, provider=result.provider,
            estimated_cost_usd=result.estimated_cost_usd, character_id=character_id,
            full_bytes=full_bytes,
            # AI-generated photos enter the community pool so other users can
            # reuse them instead of paying for a duplicate generation. High-
            # level at-home lingerie sets stay private to their user.
            community_shared=not home_lingerie_mode and request.scene not in ADULT_SCENES,
        )
        if result.url:
            sent = await bot.send_photo(chat_id, result.url, caption=item_caption, reply_markup=_photo_action_markup(row_id))
        else:
            sent = await bot.send_photo(
                chat_id,
                BufferedInputFile(result.data, filename=f'anna_{request.scene}_{idx+1}.png'),
                caption=item_caption,
                reply_markup=_photo_action_markup(row_id),
            )
        _attach_delivery_file(row_id, sent.photo[-1].file_id if sent.photo else None)
        sent_messages.append(sent)
        logger.info('photo frame delivered user=%s scene=%s frame=%s/%s provider=%s', telegram_id, request.scene, idx + 1, PHOTO_SET_SIZE, result.provider)

    try:
        results, resolved = await generate_photo_set(telegram_id, request, on_frame=_send_frame, character_id=character_id)
    except PhotoGenerationError as exc:
        # AI failed: try community pool first (other users' fresh generations),
        # then curated library as last resort. This keeps photos unique while
        # still recovering gracefully when providers are down.
        if delivery_type in {'free', 'story'} and request.scene not in _PRIVATE_LIBRARY_SCENES:
            if COMMUNITY_POOL_ENABLED:
                level = get_relationship_level(telegram_id, character_id)
                community_photos = query_community_photos(telegram_id, character_id, request.scene, level, count=PHOTO_SET_SIZE, include_app=app_delivery is not None)
                if community_photos:
                    for idx, cp in enumerate(community_photos):
                        await _send_community_frame(cp, idx, provider='community_pool_fallback', record_type='free')
                    _bump_photo_usage(telegram_id, 'free', character_id=character_id)
                    uid = ensure_user(telegram_id)
                    track_event(uid, 'photo_community_fallback_served', metadata={
                        'scene': request.scene, 'count': len(sent_messages),
                        'ai_reason': exc.reason,
                    })
                    logger.warning('AI failed but community pool recovered user=%s scene=%s provider=%s reason=%s count=%s',
                                   telegram_id, request.scene, exc.provider, exc.reason, len(sent_messages))
                    return sent_messages
            fallback_sent = await _deliver_library_failure_fallback(bot, chat_id, telegram_id, request, character_id=character_id, app_delivery=app_delivery)
            if fallback_sent:
                logger.warning('AI failed but library fallback recovered user=%s scene=%s provider=%s reason=%s', telegram_id, request.scene, exc.provider, exc.reason)
                return fallback_sent
        raise
    # V3.14.1 reliability: if an ordinary free/story AI set is partial, fill the
    # missing slots from the curated library so the user receives the promised set
    # size instead of seeing 1/3 after a provider moderation or transport failure.
    library_topup_count = 0
    if delivery_type in {'free', 'story'} and request.scene not in _PRIVATE_LIBRARY_SCENES and len(sent_messages) < PHOTO_SET_SIZE:
        topup = await _deliver_library_partial_topup(
            bot, chat_id, telegram_id, request, PHOTO_SET_SIZE - len(sent_messages),
            character_id=character_id, app_delivery=app_delivery,
        )
        sent_messages.extend(topup)
        library_topup_count = len(topup)

    if not sent_messages:
        raise PhotoGenerationError(results[0].provider if results else 'unknown', 'send_failed')

    # Commercial fairness: a paid photo credit is consumed only for a complete AI pack.
    # For free/story, library top-up counts toward the user-visible completed set.
    # Paid credits remain AI-only for charging: a mixed/partial AI result never consumes a credit.
    ai_complete = len(results) >= PHOTO_SET_SIZE
    delivered_count = len(sent_messages)
    user_visible_complete = delivered_count >= PHOTO_SET_SIZE
    charge_free_partial = delivery_type == 'free' and delivered_count >= 2
    if delivery_type == 'credit' and ai_complete:
        consume_photo_credit(telegram_id)
    record_delivery_type = delivery_type if user_visible_complete or charge_free_partial or delivery_type == 'admin' else f'partial_{delivery_type}'
    first_result = results[0]
    total_cost = sum(x.estimated_cost_usd for x in results)
    # Per-frame delivery rows were already created inside _send_frame; only the
    # set-level daily-quota accounting happens here.
    _bump_photo_usage(telegram_id, record_delivery_type, character_id=character_id)
    current_state = get_state(telegram_id, character_id=character_id)
    recent_outfits = (_json_list(getattr(current_state, 'recent_outfits_json', '[]')) + list(resolved.pack_outfits))[-6:]
    recent_hair = (_json_list(getattr(current_state, 'recent_hairstyles_json', '[]')) + [resolved.hairstyle])[-4:]
    update_state(
        telegram_id, character_id=character_id,
        outfit=resolved.clothing,
        hairstyle=resolved.hairstyle,
        recent_outfits_json=json.dumps(recent_outfits, ensure_ascii=False),
        recent_hairstyles_json=json.dumps(recent_hair, ensure_ascii=False),
    )
    uid = ensure_user(telegram_id)
    if delivered_count < PHOTO_SET_SIZE:
        track_event(uid, 'photo_partial', value=total_cost, metadata={
            'scene': request.scene, 'provider': first_result.provider, 'ai_count': len(results),
            'library_topup': library_topup_count, 'delivered_count': delivered_count, 'target': PHOTO_SET_SIZE,
        })
        try:
            extra = ''
            if delivery_type == 'credit':
                extra = ' photo credit сохранила — спишу только за полный AI-сет.'
            elif delivery_type == 'free' and delivered_count < 2:
                extra = ' бесплатный запрос тоже не списала.'
            if app_delivery is None:
                await bot.send_message(chat_id, f'часть сета уже есть 🙂 получилось {delivered_count} из {PHOTO_SET_SIZE}.{extra}')
        except Exception:
            pass
    else:
        track_event(uid, 'photo_delivered', value=total_cost, metadata={
            'scene': request.scene, 'provider': first_result.provider, 'ai_count': len(results),
            'library_topup': library_topup_count, 'count': delivered_count,
        })
    logger.info(
        'photo set delivered user=%s scene=%s provider=%s ai_count=%s library_topup=%s delivered_count=%s outfit=%s hair=%s',
        telegram_id, request.scene, first_result.provider, len(results), library_topup_count, delivered_count,
        ' | '.join(resolved.pack_outfits) if resolved.pack_outfits else resolved.clothing, resolved.hairstyle,
    )
    return sent_messages



def get_photo_delivery_for_user(telegram_id: int, delivery_id: int):
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            return None
        row = s.scalar(select(PhotoDelivery).where(PhotoDelivery.id == int(delivery_id), PhotoDelivery.user_id == user.id))
        if not row:
            return None
        return {
            'id': row.id, 'scene': row.scene, 'telegram_file_id': row.telegram_file_id,
            'character_id': row.character_id,
            'provider': row.provider, 'created_at': row.created_at,
            **_delivery_app_media(row),
        }


def get_latest_photo_delivery(telegram_id: int, *, include_app: bool = False):
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            return None
        row = s.scalar(
            select(PhotoDelivery)
            .where(PhotoDelivery.user_id == user.id, _delivery_media_filter(include_app))
            .order_by(PhotoDelivery.created_at.desc(), PhotoDelivery.id.desc())
        )
        if not row:
            return None
        return {
            'id': row.id, 'scene': row.scene, 'telegram_file_id': row.telegram_file_id,
            'character_id': row.character_id,
            'provider': row.provider, 'created_at': row.created_at,
            **_delivery_app_media(row),
        }


GALLERY_PAGE_SIZE = 6


def get_gallery_page(telegram_id: int, page: int = 0, *, include_app: bool = False) -> dict:
    """Return a slice of the user's deliveries with metadata for pagination.

    Each item carries everything the gallery UI needs: telegram_file_id for
    thumbnails, full_resolution_bytes availability (not the bytes themselves —
    they are only loaded on a paid download), and a short caption.
    """
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            return {'items': [], 'total': 0, 'page': 0, 'pages': 0}
        q = (
            select(PhotoDelivery)
            .where(PhotoDelivery.user_id == user.id, _delivery_media_filter(include_app))
            .order_by(PhotoDelivery.created_at.desc(), PhotoDelivery.id.desc())
        )
        rows = s.scalars(q).all()
        total = len(rows)
        if total == 0:
            return {'items': [], 'total': 0, 'page': 0, 'pages': 0}
        pages = (total + GALLERY_PAGE_SIZE - 1) // GALLERY_PAGE_SIZE
        page = max(0, min(int(page), pages - 1))
        offset = page * GALLERY_PAGE_SIZE
        slice_rows = rows[offset:offset + GALLERY_PAGE_SIZE]
        items = [
            {
                'id': r.id,
                'scene': r.scene,
                'telegram_file_id': r.telegram_file_id,
                'created_at': r.created_at,
                'downloadable': bool(r.full_resolution_bytes),
                'character_id': r.character_id,
            }
            for r in slice_rows
        ]
        return {'items': items, 'total': total, 'page': page, 'pages': pages}


def get_gallery_item_bytes(telegram_id: int, delivery_id: int) -> dict | None:
    """Fetch the raw image bytes for a single gallery item (paid download).

    Returns a small dict with bytes + filename hint, or None when the item
    belongs to another user or was delivered before bytes were stored.
    """
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            return None
        row = s.scalar(
            select(PhotoDelivery).where(
                PhotoDelivery.id == int(delivery_id),
                PhotoDelivery.user_id == user.id,
            )
        )
        if not row or not row.full_resolution_bytes:
            return None
        filename = f'anna_{row.scene}_{row.id}.jpg'
        return {'bytes': row.full_resolution_bytes, 'filename': filename, 'scene': row.scene}
