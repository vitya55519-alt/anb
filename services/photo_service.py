from __future__ import annotations

import asyncio
import base64
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
from urllib.parse import quote

import httpx
from aiogram import Bot
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from openai import AsyncOpenAI, BadRequestError
from sqlalchemy import select, func

from config import (
    CHARACTER_ID,
    IMAGE_API_KEY, IMAGE_BASE_URL, IMAGE_MODEL, IMAGE_SIZE, IMAGE_QUALITY, OPENAI_IMAGE_ESTIMATED_COST_USD,
    OPENAI_IMAGE_AVAILABLE,
    FREE_PHOTOS_LEVEL_1_2, FREE_PHOTOS_LEVEL_3_6, PHOTO_COST_STARS,
    FAL_KEY, FAL_MODEL, FAL_IMAGE_SIZE, FAL_TIMEOUT_SECONDS,
    FAL_CONNECT_TIMEOUT_SECONDS, FAL_WRITE_TIMEOUT_SECONDS, FAL_POOL_TIMEOUT_SECONDS,
    FAL_RETRIES, FAL_RETRY_BACKOFF_SECONDS, FAL_ESTIMATED_COST_USD,
    PHOTO_ROUTER_MODE, PHOTO_SET_SIZE,
    GEMINI_API_KEY, GEMINI_IMAGE_ENABLED, GEMINI_IMAGE_MODEL, GEMINI_IMAGE_TIMEOUT_SECONDS, GEMINI_IMAGE_ESTIMATED_COST_USD, GEMINI_IMAGE_ASPECT_RATIO, GEMINI_IMAGE_SIZE,
    POLLINATIONS_ENABLED, POLLINATIONS_MODEL, POLLINATIONS_TIMEOUT_SECONDS, POLLINATIONS_WIDTH, POLLINATIONS_HEIGHT,
    COMMUNITY_POOL_ENABLED,
)
from models.app_models import User
from models.relationship_models import UserCharacterRelationship
from models.photo_models import PhotoDailyUsage, PhotoDelivery, PhotoOffer
from services.db import SessionLocal
from services.photo_idea_service import enrich_request_with_idea
from services.character_service import get_anna
from services.character_registry import get_character
from services.test_mode import get_stage as get_test_stage
from services.access_service import is_premium
from services.user_service import ensure_user, get_state, update_state, is_adult_confirmed
from services.payments import consume_photo_credit, get_photo_credits
from services.adaptation_service import get_visual_preferences
from services.analytics_service import track_event
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
    'PHOTO PROVIDERS: Gemini=%s (model=%s) | OpenAI=%s | fal.ai/Seedream=%s | Pollinations(free)=%s | mode=%s',
    'READY' if GEMINI_IMAGE_ENABLED else 'NO KEY/DISABLED',
    GEMINI_IMAGE_MODEL if GEMINI_IMAGE_ENABLED else '-',
    'READY' if OPENAI_IMAGE_AVAILABLE else 'NO KEY',
    'READY' if FAL_KEY else 'NO KEY',
    'READY' if POLLINATIONS_ENABLED else 'DISABLED',
    PHOTO_ROUTER_MODE,
)

SCENES = {
    'selfie': 'a believable personal smartphone selfie made specifically to send to the person she is chatting with',
    'home': 'a relaxed personal smartphone photo at home, spontaneous rather than a catalogue shoot',
    'park': 'a natural personal smartphone photo during a walk in a green city park',
    'cafe': 'a personal smartphone photo in a cozy modern cafe',
    'street': 'a natural smartphone street-style photo while walking through a lively city neighborhood',
    'shop': 'a personal shopping-day smartphone photo in a stylish boutique or modern shopping mall',
    'car': 'a believable personal smartphone photo inside a clean modern car while parked',
    'gym': 'a realistic personal smartphone photo in a clean modern fitness gym during a workout break',
    'mirror': 'a realistic full-body mirror selfie in a tidy apartment, smartphone visible naturally',
    'outfit': 'a personal full-body smartphone photo showing today’s outfit',
    'restaurant': 'a polished personal photo in a stylish modern restaurant',
    'cinema': 'a casual personal photo in a modern cinema lobby before or after a movie',
    'embankment': 'a city-river embankment walk with attractive urban scenery and natural light',
    'evening': 'a tasteful evening portrait in an elegant fully clothed outfit',
    'fashion': 'a mainstream fashion-editorial portrait in tasteful fully clothed styling',
    'bar': 'a stylish personal evening photo in a warm modern cocktail bar',
    'karaoke': 'a lively personal photo in a modern karaoke lounge with atmospheric lights',
    'rooftop': 'a stylish rooftop photo with city skyline lights in the background',
    'club': 'a glamorous but fully clothed nightlife photo in a modern club',
    'personal': 'a tasteful private adult lingerie portrait made especially for someone she trusts, non-explicit, with opaque lingerie coverage',
    'lingerie': 'tasteful adult glamour/boudoir fashion in lingerie, non-explicit and fully covered by the garment',
    'private_fashion': 'premium private adult fashion portrait, non-explicit, polished and highly personalized',
}

SCENE_LEVELS = {
    'selfie': 1, 'home': 1, 'park': 1, 'cafe': 1, 'street': 1,
    'mirror': 2, 'outfit': 2, 'shop': 2, 'car': 2, 'gym': 2,
    'restaurant': 3, 'cinema': 3, 'embankment': 3, 'fashion': 3,
    'evening': 4, 'bar': 4, 'karaoke': 4, 'rooftop': 4,
    'club': 5, 'personal': 5, 'lingerie': 5,
    'private_fashion': 6,
}
STAGE_INDEX = {
    'stranger': 0, 'acquaintance': 1, 'close': 2, 'intimate': 3,
    'deeply_connected': 4, 'committed': 5,
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
    'personal': ('это уже чуть более личный сет 😌', 'ладно, эти кадры именно тебе'),
    'lingerie': ('сегодня чуть смелее обычного 😏', 'вот такой приватный fashion-настрой'),
    'private_fashion': ('это уже мой самый личный fashion-сет 😌', 'этот сет оставлю только здесь'),
}

SAFE_EXPLICIT = re.compile(
    r'\b(голая|голый|голое|голую|голые|обнаж\w*|без трус\w*|без бель\w*|соск\w*|генитал\w*|вагин\w*|пенис\w*|nude|naked|topless|explicit)\b', re.I
)
INTIMATE_STYLE = re.compile(
    r'\b(бель\w*|lingerie|будуар\w*|boudoir|чулк\w*|stocking\w*|garter\w*|bra\b|bralette|смел\w*|daring|spicy|seductive)\b', re.I
)
REAR_VIEW_STYLE = re.compile(r'\b(попк\w*|ягодиц\w*|со спины|сзади|back view|from behind|butt\w*)\b', re.I)

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
_recent_outfit_colors: dict[int, list[str]] = {}

# Small tasteful details so every set feels like a fresh photo session.
ACCESSORY_POOL = [
    'a delicate gold necklace',
    'small hoop earrings',
    'a thin bracelet',
    'an elegant wristwatch',
    'a light silk scarf',
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
    'selfie': ['front-camera selfie at arm’s length, natural eye contact', 'slightly high-angle front-camera selfie, spontaneous smartphone perspective', 'best polished personal selfie with flattering natural phone-camera framing'],
    'home': ['natural handheld home photo, relaxed posture', 'more styled mirror or self-timer home photo, confident posture', 'premium full-body home photo with the strongest composition and direct eye contact'],
    'park': ['natural walking photo in the park', 'more stylish three-quarter photo near greenery or flowers', 'premium full-body golden-hour park photo with a strong fashion-lifestyle composition'],
    'cafe': ['front-camera cafe selfie while seated', 'stylish three-quarter cafe portrait with coffee in frame', 'premium cafe portrait with beautiful window light and the strongest composition'],
    'street': ['natural walking street photo', 'stylish city street portrait with a confident pose', 'premium street-style full-body photo with strong urban composition'],
    'shop': ['natural shopping-day mirror or aisle photo', 'stylish boutique mirror photo with shopping details', 'premium fashion-shopping portrait with polished composition'],
    'car': ['natural parked-car selfie', 'stylish three-quarter car interior portrait', 'premium personal car photo with flattering daylight and polished framing'],
    'gym': ['natural gym mirror or self-timer photo during a workout break', 'stylish three-quarter fitness portrait near training equipment', 'premium full-body gym lifestyle photo with polished athletic styling'],
    'mirror': ['full-body mirror selfie', 'more styled three-quarter mirror selfie', 'premium mirror fashion photo with strongest outfit presentation'],
    'outfit': ['base full-body outfit photo', 'more stylish three-quarter outfit photo', 'premium outfit photo with best fashion composition'],
    'restaurant': ['natural table-side personal photo', 'stylish restaurant portrait', 'premium dinner portrait with elegant lighting'],
    'cinema': ['natural cinema-lobby personal photo', 'stylish photo near posters or lounge area', 'premium cinematic portrait with atmospheric lobby light'],
    'embankment': ['natural walking photo by the water', 'stylish city-river portrait', 'premium golden-hour or blue-hour full-body portrait'],
    'evening': ['base evening look portrait', 'more stylish evening three-quarter portrait', 'premium evening fashion portrait with best lighting'],
    'fashion': ['base full-body fashion portrait', 'more styled three-quarter fashion portrait', 'premium editorial-fashion portrait with strongest composition'],
    'bar': ['natural personal photo near a bar table', 'stylish bar portrait with warm ambient light', 'premium cocktail-bar fashion portrait with cinematic composition'],
    'karaoke': ['natural karaoke photo with microphone nearby', 'more energetic stylish karaoke portrait', 'premium nightlife karaoke portrait with atmospheric light'],
    'rooftop': ['natural rooftop city portrait', 'stylish skyline three-quarter portrait', 'premium rooftop evening portrait with city lights and strongest composition'],
    'club': ['natural nightlife arrival photo', 'stylish club portrait with atmospheric lights', 'premium glamorous fully clothed nightlife portrait'],
    'personal': ['tasteful seated lingerie portrait with natural eye contact, non-explicit', 'polished mirror or self-timer lingerie fashion portrait, non-explicit', 'premium private lingerie-fashion portrait with elegant opaque coverage, non-explicit'],
    'lingerie': ['tasteful adult glamour portrait, non-explicit', 'more polished mirror-style lingerie fashion portrait, non-explicit', 'premium tasteful boudoir-fashion portrait with opaque garment coverage'],
    'private_fashion': ['tasteful private fashion portrait with opaque coverage', 'more polished private fashion portrait with confident styling', 'premium personalized private fashion portrait, non-explicit and opaque'],
}

PACK_TIER_RULES = (
    'BASE: believable, natural, relaxed and attractive; this is the first frame of the set.',
    'STYLISH: visibly more polished styling and a more confident pose than frame one.',
    'PREMIUM: strongest outfit styling, best light, best composition and the biggest wow-effect allowed at this relationship level.',
)
LEVEL_VISUAL_RULES = {
    1: 'Relationship visual level 1/6: friendly, approachable, casual and fully clothed. Attractive but not deliberately intimate. Fitted clothing may very subtly hint at everyday lingerie underneath, like a soft bra outline under a thin blouse — believable and tasteful, never exposed.',
    2: 'Relationship visual level 2/6: more feminine and fitted styling, clearer waist definition, still fully clothed. A discreet lingerie outline under fitted fabric is allowed; necklines slightly more feminine.',
    3: 'Relationship visual level 3/6: noticeably more stylish, confident and figure-flattering fashion, deeper feminine necklines and fitted silhouettes while remaining mainstream; tasteful hints of lace or lingerie under clothing, fully clothed.',
    4: 'Relationship visual level 4/6: polished personal fashion, more confident poses and stronger fitted silhouettes; more revealing cuts such as open back or off-shoulder are allowed, still no exposure and non-explicit.',
    5: 'Relationship visual level 5/6: glamorous personalized styling and more private-feeling fashion; elegant daring cuts and visible lace details are allowed, keep it classy and non-explicit.',
    6: 'Relationship visual level 6/6: premium personalized styling, strongest confident fashion presentation and clear exclusivity; boldest tasteful fashion allowed, remain fully non-explicit.',
}
OPENAI_LEVEL_VISUAL_RULES = {
    1: 'Relationship visual level 1/6: simple casual styling, natural pose, everyday social-media feel, fully clothed. A very subtle hint of everyday lingerie under fitted clothing (soft bra outline under a thin blouse) is allowed if natural; never exposed.',
    2: 'Relationship visual level 2/6: more coordinated clothing, cleaner styling and a little more confidence, fully clothed; a discreet lingerie outline under fitted fabric is allowed.',
    3: 'Relationship visual level 3/6: noticeably more fashionable outfit, better accessories and stronger composition, fully clothed; deeper feminine necklines and tasteful hints of lace under clothing are allowed.',
    4: 'Relationship visual level 4/6: polished personal fashion, confident lifestyle pose and more intentional styling, fully clothed; more revealing cuts such as open back or off-shoulder are allowed, no exposure.',
    5: 'Relationship visual level 5/6: premium personalized styling, richer venue details and more exclusive-feeling composition, fully clothed; elegant daring cuts and visible lace details are allowed.',
    6: 'Relationship visual level 6/6: strongest premium styling, best accessories, lighting and composition; sophisticated and exclusive, boldest tasteful fashion while fully clothed and general-audience.',
}

# How the underwear under her clothes reads on camera, by relationship level.
# Like real life: she always wears lingerie — and it is there to underline her
# own femininity, confidence and natural sexuality, never to objectify her.
# At low levels it only shows through the fabric; at higher levels lace edges
# become a tasteful part of the look.
LEVEL_UNDERLAY_RULES = {
    1: 'Her everyday bra is clearly but subtly visible under the thin fitted fabric of her top — like a real woman wearing beautiful lingerie under a blouse. The lingerie is not on display: it simply makes her posture and silhouette more feminine and attractive. No exposure.',
    2: 'The outline of her bra and a hint of lingerie straps show gently through her fitted clothing — her underwear quietly emphasizes her natural sexuality and self-confidence.',
    3: 'Her lingerie is clearly hinted: the bra outline and a glimpse of a lace edge under the fitted garment. The lace adds femininity and allure, never vulgarity.',
    4: 'Lace lingerie edges are intentionally visible under the more revealing outfit — elegant sensuality that flatters her figure, still no exposure.',
    5: 'Elegant visible lace details under the private-feeling outfit: the lingerie flatters her curves and radiates confident, tasteful sexuality.',
    6: 'Sophisticated visible lace and lingerie-inspired fashion details — her most sensual look, refined, feminine and non-explicit.',
}

# Bust size must never drift between frames or between sets.
BUST_CONSISTENCY_RULE = (
    'BUST CONSISTENCY: her bust must look exactly the same size in this frame as in every other photo — '
    'a full feminine bust with silicone implants (Russian size 4, D cup), neither larger nor smaller, '
    'with the same shape and the same natural fit inside the clothing.'
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
    'Anna has a full feminine bust with silicone implants (Russian size 4, D cup) — this bust size is a permanent part of her identity even if the reference shows a smaller one. '
    'Anna has a naturally slim and fit build — this is a core part of her identity. '
    'These proportions are part of Anna\u2019s identity, not a wardrobe effect. Clothing may change, but it must fit the same underlying physique. '
    'Do not add weight, make her thicker, or change her body type. Keep the same slim proportions visible in the canonical reference. '
    'Wardrobe, cafe background, pose and accessories from the reference are not permanent traits unless the requested scene calls for them.'
)
OPENAI_REFERENCE_PROTOCOL = (
    'REFERENCE PROTOCOL: image 1 controls Anna\u2019s exact face and hair identity; image 2 reinforces the same appearance and stable slender silhouette. '
    'The two images depict the same canonical Anna. Anna\u2019s bust is always full (silicone implants, Russian size 4, D cup) regardless of how the reference shows it. '
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
    'Include Anna\u2019s full bust (silicone implants, Russian size 4, D cup) as a permanent body trait even if the reference shows it smaller; keep the waist slim. '
    'Do not add weight, make her thicker, or change her body type — keep the same slender proportions from the reference. '
    'Clothing changes coverage and styling only; the underlying body identity stays fixed and slim.'
)
ORDINARY_REFERENCE_PROTOCOL = (
    'ORDINARY REFERENCE PROTOCOL: image 1 controls Anna\u2019s exact recognizable face and hair identity; image 2 controls the same overall physique and slim proportions. '
    'Use the requested scene, outfit, hairstyle, pose, camera and lighting for everything else. '
    'Keep the result natural and general-audience but always preserve Anna\u2019s naturally slim and fit figure.'
)
ORDINARY_IDENTITY_LOCK = ANNA_FACE_IDENTITY + ' ' + ORDINARY_BODY_IDENTITY + ' ' + ORDINARY_REFERENCE_PROTOCOL
BODY_REINFORCEMENT = (
    'BODY CONSISTENCY CHECK: keep Anna\u2019s overall physique and proportions visually consistent with reference image 2. '
    'She is naturally slim and fit — do NOT add weight, make her thicker, or change her body type in any pose, angle, clothing or scene. '
    'Her bust stays full and consistent in every scene (silicone implants, Russian size 4, D cup). '
    'Including mirror, seated, athletic, full-body and loose-clothing scenes: preserve the same slender proportions. '
    'Keep anatomy realistic, clothing scene-appropriate and the pose natural.'
)
EXPRESSION_IDENTITY = (
    'EXPRESSION: Anna has a natural warm feminine smile in generated photos. Keep it subtle, relaxed and believable, similar to her canonical references; '
    'avoid a blank stern expression and avoid an exaggerated forced grin or unnaturally wide toothy smile.'
)
OPENAI_IDENTITY_LOCK = ORDINARY_IDENTITY_LOCK


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
                'The photo must plausibly be made by Anna herself using a front camera, a mirror, or a smartphone self-timer; no invisible photographer. '
                'Keep the styling polished and personal while remaining non-explicit.',
                'Tasteful adult fashion/editorial styling only. No nudity, no exposed nipples or genitals. '
                'For personal or lingerie scenes, use elegant adult lingerie with opaque garment coverage; preserve identity above styling.',
                expression_description(expression_key, 'Anna') if expression_key else EXPRESSION_IDENTITY,
            )
        return (
            OPENAI_IDENTITY_LOCK,
            'This should feel like a normal personal photo Anna has just taken herself to send to someone she is chatting with. '
            'Every frame must plausibly be made by Anna herself using a front camera, a mirror, or a smartphone self-timer; no invisible photographer. '
            'Use believable smartphone framing and a natural expression. The result should feel Pinterest-like and intentionally styled, '
            'but still like a real personal lifestyle photo rather than a studio glamour shoot.',
            OPENAI_GENERAL_AUDIENCE_BLOCK,
            expression_description(expression_key, 'Anna') if expression_key else EXPRESSION_IDENTITY,
        )

    from services.character_card_service import get_card
    card = get_card(character_id)
    character = get_character(character_id)
    name = card.display_name if card else character_id
    age = card.age if card else 25
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
    identity = (
        f'PHOTO IDENTITY: Create the SAME fictional adult {gender} character, {name}, age {age}. '
        f'Identity preservation is the highest priority. Preserve these exact traits from the canonical references: {preserve_text}. '
        f'{pronoun_cap} is the same person across all photos. Preserve {figure}. '
        f'Do not substitute another person, do not change age or ethnicity. '
        f'Use the requested scene, outfit, pose, camera and lighting for everything else.'
    )
    personal = (
        f'This should feel like a normal personal photo {name} has just taken to send to someone {pronoun} is chatting with. '
        f'Every frame must plausibly be made by {pronoun} using a front camera, a mirror, or a smartphone self-timer; no invisible photographer. '
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
    'Anna has a full bust with silicone implants (Russian size 4, D cup) as a permanent trait even if the reference shows it smaller. '
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
NEGATIVE_BLOCK = (
    'Avoid identity drift, generic doll-like face, plastic skin, asymmetrical eyes, warped hands, extra fingers, '
    'duplicate limbs, distorted anatomy, text, watermark, random accessories, and overprocessed beauty filters.'
)


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
    season: str = ''
    accessory: str = ''
    time_of_day: str = ''
    pack_outfits: tuple[str, ...] = ()
    customized: bool = False


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
    override = get_test_stage(telegram_id)
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


def scene_allowed_for_stage(scene: str, stage: str) -> bool:
    return STAGE_INDEX.get(stage, 0) + 1 >= SCENE_LEVELS.get(scene, 99)


def is_custom_request(request: PhotoRequest) -> bool:
    return request.scene in {'lingerie', 'private_fashion'} or bool(request.customized)


def requires_adult_confirmation(request: PhotoRequest) -> bool:
    return request.scene in {'lingerie', 'private_fashion'} or bool(INTIMATE_STYLE.search(' '.join([request.clothing, request.location, request.angle])))


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


def parse_photo_request(text: str) -> Optional[PhotoRequest]:
    t = (text or '').strip()
    low = t.lower()
    request_verbs = (
        'сфоткай', 'сфотай', 'сфотограф', 'фоткни', 'сделай фото', 'пришли фото', 'пришли фотку', 'покажи себя', 'покажись',
        'сними себя', 'селфи', 'take a photo', 'take a pic', 'send me a photo', 'send a pic', 'show me a photo', 'show yourself', 'show me yourself', 'selfie',
        '拍照', '自拍', '发张照片', '给我看看你',
    )
    direct = (
        any(x in low for x in request_verbs)
        or bool(re.match(r'^\s*(?:фото|фотку|photo|pic)\b', low))
        or bool(re.search(r'\b(?:сделай|пришли|дай|хочу|покажи)\b.{0,45}\b(?:фото|фотку|фотографию|селфи)\b', low))
        or bool(re.search(r'\b(?:make|send|take|want|show)\b.{0,45}\b(?:photo|pic|selfie|picture)\b', low))
    )
    if not direct:
        return None

    season = _season_from_text(low)
    if SAFE_EXPLICIT.search(low):
        return PhotoRequest(scene='fashion', clothing='tasteful fitted evening fashion outfit with opaque fabric', season=season)

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
    return PhotoRequest(scene=scene, clothing=clothing, hairstyle=hairstyle, location=location, angle=angle, season=season, customized=customized)


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
        raise FileNotFoundError('У Анны нет доступных reference-фото')
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
    raise FileNotFoundError('У Анны нет нового canonical reference для Seedream')


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


def _wardrobe_pool(scene: str, level: int, season: str) -> list[str]:
    group = SCENE_GROUP.get(scene, 'day_casual')
    level = max(1, min(6, int(level)))
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


def _choose_progression_outfits(telegram_id: int, request: PhotoRequest, season: str, *, character_id: str = CHARACTER_ID) -> tuple[str, ...]:
    if request.clothing:
        return tuple(request.clothing for _ in range(PHOTO_SET_SIZE))
    state = get_state(telegram_id)
    level = get_relationship_level(telegram_id, character_id)
    pool = _wardrobe_pool(request.scene, level, season)
    uid = ensure_user(telegram_id)
    visual_prefs = get_visual_preferences(uid, character_id)
    color_counts = visual_prefs.get('colors', {}) if isinstance(visual_prefs, dict) else {}
    favorite_color = max(color_counts, key=color_counts.get) if color_counts and max(color_counts.values()) >= 2 else ''
    picks: list[str] = []
    recent = {x.strip().lower() for x in _json_list(getattr(state, 'recent_outfits_json', '[]'))}
    if state.outfit:
        recent.add(state.outfit.strip().lower())
    for i in range(PHOTO_SET_SIZE):
        usable = [x for x in pool if x not in picks and x.strip().lower() not in recent]
        if not usable:
            usable = [x for x in pool if x not in picks] or pool
        chosen = random.choice(usable)
        # Color diversity: every frame gets its own garment color and the
        # favorite color shows up at most once per set (and never orange), so
        # the wardrobe never collapses into one repeated tone.
        if favorite_color and 'orange' not in favorite_color.lower() and i == 0 \
                and SCENE_GROUP.get(request.scene) != 'adult' and random.random() < 0.35:
            chosen = f'{chosen} in a {favorite_color} tone'
        else:
            recent_colors = _recent_outfit_colors.setdefault(telegram_id, [])
            color_pool = [c for c in OUTFIT_COLOR_POOL if c not in recent_colors] or list(OUTFIT_COLOR_POOL)
            color = random.choice(color_pool)
            recent_colors.append(color)
            del recent_colors[:-3]
            chosen = f'{chosen} in a {color} color'
        picks.append(chosen)
    return tuple(picks)


def _resolve_request(telegram_id: int, request: PhotoRequest, *, character_id: str = CHARACTER_ID) -> PhotoRequest:
    state = ensure_life_state(telegram_id)
    season = request.season or _default_season()
    pack_outfits = tuple(request.pack_outfits) if request.pack_outfits else _choose_progression_outfits(telegram_id, request, season, character_id=character_id)
    clothing = pack_outfits[-1] if pack_outfits else request.clothing
    if request.hairstyle:
        hairstyle = request.hairstyle
    else:
        recent_hair = {x.strip().lower() for x in _json_list(getattr(state, 'recent_hairstyles_json', '[]'))}
        if state.hairstyle:
            recent_hair.add(state.hairstyle.strip().lower())
        hair_pool = [x for x in HAIRSTYLE_POOL if x.strip().lower() not in recent_hair] or HAIRSTYLE_POOL
        uid = ensure_user(telegram_id)
        visual_prefs = get_visual_preferences(uid, character_id)
        hair_counts = visual_prefs.get('hairstyles', {}) if isinstance(visual_prefs, dict) else {}
        preferred_hair = max(hair_counts, key=hair_counts.get) if hair_counts and max(hair_counts.values()) >= 2 else ''
        if preferred_hair and preferred_hair.strip().lower() not in recent_hair and random.random() < 0.50:
            hairstyle = preferred_hair
        else:
            hairstyle = random.choice(hair_pool)
    if request.location:
        location = request.location
    elif request.scene == 'selfie' and getattr(state, 'location', None):
        activity = getattr(state, 'activity', None) or 'having a normal day'
        location = f"{SCENES['selfie']}; keep it consistent with the character's current fictional day context: location={state.location}, activity={activity}"
    else:
        location = SCENES.get(request.scene, SCENES['selfie'])
    # Anna re-dyes monthly; other characters keep their identity's natural hair
    # color (e.g. Emily is always blonde). The cycle was designed for Anna only.
    if request.hair_color:
        hair_color = request.hair_color
    elif character_id == 'anna_01':
        hair_color = current_hair_color()
    else:
        hair_color = ''
    makeup = request.makeup or random.choice(MAKEUP_POOL)
    accessory = request.accessory or random.choice(ACCESSORY_POOL)
    time_of_day = request.time_of_day or random.choice(DAYLIGHT_POOL)
    return replace(request, clothing=clothing, hairstyle=hairstyle, location=location, season=season,
                   pack_outfits=pack_outfits, hair_color=hair_color, makeup=makeup,
                   accessory=accessory, time_of_day=time_of_day)


def _shot_variant(scene: str, index: int, requested_angle: str = '') -> str:
    if requested_angle:
        return requested_angle
    variants = SHOT_VARIANTS.get(scene, SHOT_VARIANTS['selfie'])
    return variants[index % len(variants)]


def _build_prompt(request: PhotoRequest, shot_index: int, seedream: bool = False, relationship_level: int = 1, character_id: str = CHARACTER_ID) -> str:
    scene = SCENES.get(request.scene, SCENES['selfie'])
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
    season = request.season or _default_season()
    season_rule = SEASON_RULES.get(season, SEASON_RULES['summer'])
    identity, personal, safety, expression_identity = _character_identity_lock(character_id, seedream=seedream, expression_key=request.expression_key)
    body_reinforcement = BODY_REINFORCEMENT if (character_id == 'anna_01' and not seedream and request.scene in BODY_REINFORCEMENT_SCENES) else ''
    figure_note = (
        'Use tasteful fashion fit and waist definition while preserving the underlying slim body proportions. ' if seedream else
        'Use a well-fitted outfit that preserves the person\u2019s physique and proportions. Use a natural everyday pose with the visual focus on the person, outfit and environment. '
    )
    return (
        f'{identity}\n'
        f'SCENE: {scene}. {request.location}.\n'
        f'SEASON/WEATHER: {season}. {season_rule}\n'
        f'RELATIONSHIP VISUAL PROGRESSION: {visual_rule}\n'
        f'PROGRESSION PACK FRAME {shot_index + 1}/{PHOTO_SET_SIZE}: {tier_rule}\n'
        f'WARDROBE: {wardrobe}. {figure_note}'
        'The outfit must be believable for this exact venue, weather and time of day. Do not reuse a heavy sweater or hoodie in a visibly warm summer scene.\n'
        f'UNDER-CLOTHING REALISM: {underlay_rule}\n'
        f'{BUST_CONSISTENCY_RULE}\n'
        f'HAIRSTYLE: {request.hairstyle}.\n'
        f'MAKEUP: {request.makeup}.\n'
        f'STYLING DETAILS: {request.accessory}.\n'
        f'TIME OF DAY: {request.time_of_day}. The light must match this time of day.\n'
        f'CAMERA/POSE: {angle}.\n'
        f'HAIR COLOR THIS MONTH: {request.hair_color}. This temporary hair color overrides the hair color in the reference photos and in the identity description above; her face, features and everything else stay exactly the same.\n' if request.hair_color else ''
        f'{body_reinforcement}\n'
        f'MOOD: {request.mood}.\n'
        f'{expression_identity}\n'
        f'{personal}\n'
        'LIGHTING: use lighting that naturally belongs to the location and time of day; realistic shadows, cinematic but believable contrast.\n'
        f'{safety}\n'
        f'{QUALITY_BLOCK}\n'
        f'{NEGATIVE_BLOCK}'
    )


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


def _file_data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or 'image/png'
    encoded = base64.b64encode(path.read_bytes()).decode('ascii')
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
        "\nNANO BANANA ORDINARY-PHOTO RULE: Use the supplied canonical references as identity anchors. "
        "Keep the same fictional adult person, same exact face, hair color and style, overall physique and subtle warm smile. "
        "This prompt is independent from chat personality, flirting, sensuality or relationship erotics; none of those should affect ordinary-photo styling. "
        "Change only the requested scene, fully clothed outfit, pose, camera and lighting. Keep the result mainstream, natural and general-audience. "
        "Photorealistic personal smartphone-photo aesthetic."
    )
    refs = _openai_reference_paths(character, request.scene)[:2]
    inputs: list[dict] = [{"type": "text", "text": prompt}]
    for ref in refs:
        mime = mimetypes.guess_type(str(ref))[0] or 'image/png'
        inputs.append({
            "type": "image",
            "data": base64.b64encode(ref.read_bytes()).decode('ascii'),
            "mime_type": mime,
        })

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
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.post(
                'https://generativelanguage.googleapis.com/v1beta/interactions',
                headers=headers,
                json=payload,
            )
    except httpx.TimeoutException as exc:
        raise PhotoGenerationError('gemini_image', 'timeout') from exc
    except UnicodeEncodeError as exc:
        # Header encoding should now only fail for a malformed API key; keep the
        # error explicit instead of silently masking it behind GPT fallback logs.
        raise PhotoGenerationError('gemini_image', 'header_unicode_error') from exc
    except httpx.HTTPError as exc:
        logger.warning('Nano Banana transport failed user=%s scene=%s frame=%s/%s error=%s', telegram_id, request.scene, i + 1, PHOTO_SET_SIZE, type(exc).__name__)
        raise PhotoGenerationError('gemini_image', type(exc).__name__) from exc

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
) -> list[GeneratedPhoto]:
    out: list[GeneratedPhoto] = []
    logger.info('Nano Banana set request user=%s scene=%s model=%s count=%s refs=2', telegram_id, request.scene, GEMINI_IMAGE_MODEL, PHOTO_SET_SIZE)
    for i in range(PHOTO_SET_SIZE):
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


async def _pollinations_one_frame(character: dict, telegram_id: int, request: PhotoRequest, i: int, *, character_id: str = CHARACTER_ID) -> GeneratedPhoto:
    """Free text-to-image fallback via Pollinations.ai (no API key required).

    Used as the last-resort route for ordinary fully-clothed photos when the
    primary providers fail or are not configured. The endpoint cannot accept
    reference image uploads, so identity is reinforced purely by the text lock.
    """
    if not POLLINATIONS_ENABLED:
        raise PhotoGenerationError('pollinations', 'not_configured')

    level = get_relationship_level(telegram_id, character_id)
    prompt = _build_prompt(request, i, seedream=False, relationship_level=level, character_id=character_id) + (
        " FREE PROVIDER ORDINARY-PHOTO RULE: Keep the same fictional adult person described in PHOTO IDENTITY "
        "across every photo: same face features, hair color and style, overall physique and subtle warm smile. "
        "Change only the requested scene, fully clothed outfit, pose, camera and lighting. "
        "Keep the result mainstream, natural and general-audience. Photorealistic personal smartphone-photo aesthetic."
    )
    # Pollinations rejects prompts containing newline characters (404), so the
    # multi-line structured prompt must be flattened into a single line.
    prompt = ' '.join(line.strip() for line in prompt.split('\n') if line.strip())
    params = {
        'width': str(POLLINATIONS_WIDTH),
        'height': str(POLLINATIONS_HEIGHT),
        'model': POLLINATIONS_MODEL,
        'seed': str(random.randint(0, 2**31 - 1)),
        'nologo': 'true',
        'safe': 'true',
    }
    url = f'https://image.pollinations.ai/prompt/{quote(prompt)}'
    timeout = httpx.Timeout(float(POLLINATIONS_TIMEOUT_SECONDS), connect=20.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url, params=params)
    except httpx.TimeoutException as exc:
        raise PhotoGenerationError('pollinations', 'timeout') from exc
    except httpx.HTTPError as exc:
        logger.warning('Pollinations transport failed user=%s scene=%s frame=%s/%s error=%s', telegram_id, request.scene, i + 1, PHOTO_SET_SIZE, type(exc).__name__)
        raise PhotoGenerationError('pollinations', type(exc).__name__) from exc

    if response.status_code >= 400:
        logger.warning('Pollinations HTTP failure user=%s scene=%s frame=%s/%s status=%s', telegram_id, request.scene, i + 1, PHOTO_SET_SIZE, response.status_code)
        raise PhotoGenerationError('pollinations', f'http_{response.status_code}')

    data = response.content
    # The endpoint returns image bytes directly; guard against error pages.
    if not data or not (data.startswith(b'\xff\xd8') or data.startswith(b'\x89PNG')):
        raise PhotoGenerationError('pollinations', 'no_image')
    logger.info(
        'Pollinations frame success user=%s scene=%s frame=%s/%s model=%s bytes=%s',
        telegram_id, request.scene, i + 1, PHOTO_SET_SIZE, POLLINATIONS_MODEL, len(data),
    )
    return GeneratedPhoto(data=data, provider='pollinations', estimated_cost_usd=0.0)


async def _run_pollinations_set(
    character: dict,
    telegram_id: int,
    request: PhotoRequest,
    on_frame: Callable[[GeneratedPhoto, int], Awaitable[None]] | None = None,
    *,
    character_id: str = CHARACTER_ID,
) -> list[GeneratedPhoto]:
    out: list[GeneratedPhoto] = []
    logger.info('Pollinations set request user=%s scene=%s model=%s count=%s (free last resort)', telegram_id, request.scene, POLLINATIONS_MODEL, PHOTO_SET_SIZE)
    for i in range(PHOTO_SET_SIZE):
        started = time.monotonic()
        try:
            photo = await _pollinations_one_frame(character, telegram_id, request, i, character_id=character_id)
        except PhotoGenerationError as exc:
            track_event(ensure_user(telegram_id), 'photo_frame_failed', metadata={'scene': request.scene, 'frame': i + 1, 'provider': 'pollinations', 'reason': exc.reason})
            if out:
                logger.warning('Pollinations partial set user=%s scene=%s count=%s/%s reason=%s', telegram_id, request.scene, len(out), PHOTO_SET_SIZE, exc.reason)
                break
            raise
        out.append(photo)
        frame_elapsed = time.monotonic() - started
        track_event(ensure_user(telegram_id), 'photo_frame_ready', value=frame_elapsed, metadata={'scene': request.scene, 'frame': i + 1, 'provider': 'pollinations'})
        if i == 0:
            track_event(ensure_user(telegram_id), 'photo_first_frame_ready', value=frame_elapsed, metadata={'scene': request.scene, 'provider': 'pollinations'})
        if on_frame:
            await on_frame(photo, i)
    if not out:
        raise PhotoGenerationError('pollinations', 'no_image')
    return out


async def _seedream_request(
    prompt: str,
    image_urls: list[str],
    num_images: int = 1,
    request_label: str = '',
) -> dict:
    """Call fal/Seedream with explicit phase timeouts and bounded retry.

    Seedream can legitimately take longer than a normal HTTP request.  We retry
    only transport timeouts and transient HTTP errors.  Policy/validation 4xx
    responses are returned immediately so we never try to bypass provider safety.
    """
    if not FAL_KEY:
        raise PhotoGenerationError('seedream45', 'FAL_KEY is not configured')

    endpoint = f"https://fal.run/{FAL_MODEL.strip('/')}"
    payload = {
        'prompt': prompt,
        'image_urls': image_urls,
        'image_size': FAL_IMAGE_SIZE,
        'num_images': num_images,
        'max_images': num_images,
        'enable_safety_checker': True,
    }
    headers = {'Authorization': f'Key {FAL_KEY}', 'Content-Type': 'application/json'}
    timeout = httpx.Timeout(
        connect=float(FAL_CONNECT_TIMEOUT_SECONDS),
        read=float(FAL_TIMEOUT_SECONDS),
        write=float(FAL_WRITE_TIMEOUT_SECONDS),
        pool=float(FAL_POOL_TIMEOUT_SECONDS),
    )
    max_attempts = FAL_RETRIES + 1
    transient_statuses = {408, 425, 429, 500, 502, 503, 504}

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for attempt in range(1, max_attempts + 1):
            started = time.monotonic()
            try:
                response = await client.post(endpoint, headers=headers, json=payload)
            except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as exc:
                elapsed = time.monotonic() - started
                logger.warning(
                    'Seedream timeout label=%s attempt=%s/%s elapsed=%.1fs type=%s',
                    request_label or '-', attempt, max_attempts, elapsed, type(exc).__name__,
                )
                if attempt >= max_attempts:
                    raise PhotoGenerationError('seedream45', 'timeout') from exc
                await asyncio.sleep(FAL_RETRY_BACKOFF_SECONDS * attempt)
                continue

            elapsed = time.monotonic() - started
            logger.info(
                'Seedream response label=%s attempt=%s/%s status=%s elapsed=%.1fs',
                request_label or '-', attempt, max_attempts, response.status_code, elapsed,
            )

            if response.status_code >= 400:
                body = response.text[:1600]
                if response.status_code in transient_statuses and attempt < max_attempts:
                    logger.warning(
                        'Seedream transient HTTP status=%s label=%s attempt=%s/%s body=%s',
                        response.status_code, request_label or '-', attempt, max_attempts, body[:500],
                    )
                    await asyncio.sleep(FAL_RETRY_BACKOFF_SECONDS * attempt)
                    continue
                logger.error('Seedream HTTP error status=%s body=%s', response.status_code, body)
                raise PhotoGenerationError('seedream45', f'HTTP {response.status_code}')

            try:
                return response.json()
            except Exception as exc:
                logger.error('Seedream returned non-JSON response: %s', response.text[:1200])
                raise PhotoGenerationError('seedream45', 'invalid_json') from exc

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
            '\nSAFE RETRY: Strictly general-audience, fully clothed everyday lifestyle fashion. Neutral pose and scene-appropriate coverage. Preserve the exact face and canonical body proportions from the references; safety changes styling, not identity.'
        )
    else:
        prompt = _build_prompt(request, i, seedream=False, relationship_level=level, character_id=character_id)
    if single_reference:
        prompt += '\nCOMPATIBILITY RETRY: the single supplied fully-clothed reference controls both the character\u2019s recognizable identity and stable overall silhouette.'
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
) -> list[GeneratedPhoto]:
    refs = _openai_reference_paths(character, request.scene)
    logger.info('OpenAI normal-photo set request user=%s scene=%s references=%s count=%s identity_engine=v3', telegram_id, request.scene, ','.join(p.name for p in refs), PHOTO_SET_SIZE)
    outputs: list[GeneratedPhoto] = []
    for i in range(PHOTO_SET_SIZE):
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
                    photo = await _openai_one_frame(character, telegram_id, request, i, safe_retry=True, single_reference=True)
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
    if request.scene in {'personal', 'lingerie'}:
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
) -> list[GeneratedPhoto]:
    ref = _seedream_reference_path(character)
    reference_uri = _file_data_uri(ref)
    out: list[GeneratedPhoto] = []
    logger.info(
        'Seedream set request user=%s scene=%s reference=%s target_count=%s per_request=1 timeout=%ss retries=%s',
        telegram_id, request.scene, ref.name, PHOTO_SET_SIZE, FAL_TIMEOUT_SECONDS, FAL_RETRIES,
    )
    for i in range(PHOTO_SET_SIZE):
        prompt = _build_prompt(request, i, seedream=True, relationship_level=get_relationship_level(telegram_id, character_id), character_id=character_id) + (
            '\nCreate exactly ONE photo for this shot. Keep the same hairstyle, location, '
            'face identity and body proportions as the other photos in this set. '
            'Make this framing clearly different from the previous shot while staying in the same photo session.'
        )
        frame_started = time.monotonic()
        try:
            result = await _seedream_request(prompt, [reference_uri], 1, request_label=f'{request.scene}:{i + 1}/{PHOTO_SET_SIZE}')
        except PhotoGenerationError as exc:
            # One safe retry on provider content validation. This simplifies the prompt; it does not disable safety.
            if exc.reason == 'HTTP 422':
                retry_request = _seedream_safe_retry_request(request)
                retry_prompt = _build_prompt(retry_request, i, seedream=True, relationship_level=min(get_relationship_level(telegram_id, character_id), 4), character_id=character_id) + (
                    '\nSAFE RETRY: tasteful fully covered fashion, opaque garment, neutral pose, no nudity, no body-part emphasis. For personal/lingerie scenes, keep the requested lingerie category with opaque coverage. Create exactly ONE photo.'
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


def choose_photo_provider(telegram_id: int, request: PhotoRequest) -> str:
    mode = PHOTO_ROUTER_MODE
    if mode in {'openai', 'gpt', 'gpt-image-2'}:
        return 'openai' if OPENAI_IMAGE_AVAILABLE else ('gemini_image' if GEMINI_IMAGE_ENABLED else 'seedream45')
    if mode in {'fal', 'seedream', 'seedream45'}:
        return 'seedream45'
    if mode in {'gemini', 'nano', 'nanobanana', 'nano-banana'}:
        return 'gemini_image' if GEMINI_IMAGE_ENABLED else ('openai' if OPENAI_IMAGE_AVAILABLE else 'seedream45')
    if mode == 'pollinations':
        return 'pollinations' if POLLINATIONS_ENABLED else ('gemini_image' if GEMINI_IMAGE_ENABLED else 'seedream45')

    # HYBRID routing (default):
    # - intimate/private/bold scenes → Seedream
    # - ordinary fully-clothed scenes → Gemini Image (primary) → OpenAI (fallback)
    combined = ' '.join([request.scene, request.clothing, request.location, request.angle]).lower()
    if request.scene in {'personal', 'lingerie', 'private_fashion'} or INTIMATE_STYLE.search(combined):
        logger.info('Hybrid photo route scene=%s -> seedream45', request.scene)
        return 'seedream45'
    if GEMINI_IMAGE_ENABLED and GEMINI_API_KEY:
        logger.info('Hybrid photo route scene=%s -> gemini_image (%s)', request.scene, GEMINI_IMAGE_MODEL)
        return 'gemini_image'
    if OPENAI_IMAGE_AVAILABLE:
        logger.info('Hybrid photo route scene=%s -> openai', request.scene)
        return 'openai'
    if POLLINATIONS_ENABLED:
        logger.info('Hybrid photo route scene=%s -> pollinations (free, no Gemini/OpenAI)', request.scene)
        return 'pollinations'
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
) -> list[GeneratedPhoto]:
    try:
        if provider == 'seedream45':
            return await _run_seedream_set(character, telegram_id, resolved, on_frame=on_frame, character_id=character_id)
        if provider == 'gemini_image':
            try:
                return await _run_gemini_set(character, telegram_id, resolved, on_frame=on_frame, character_id=character_id)
            except PhotoGenerationError as exc:
                # Gemini failed: try OpenAI if available, otherwise fall back to Seedream.
                if OPENAI_IMAGE_AVAILABLE:
                    logger.warning('PHOTO ROUTE FALLBACK user=%s scene=%s from=gemini_image to=openai reason=%s', telegram_id, resolved.scene, exc.reason)
                    track_event(ensure_user(telegram_id), 'photo_provider_fallback', metadata={'scene': resolved.scene, 'from': 'gemini_image', 'to': 'openai', 'reason': exc.reason})
                    return await _run_openai_set(character, telegram_id, resolved, on_frame=on_frame, character_id=character_id)
                logger.warning('PHOTO ROUTE FALLBACK user=%s scene=%s from=gemini_image to=seedream45 reason=%s', telegram_id, resolved.scene, exc.reason)
                track_event(ensure_user(telegram_id), 'photo_provider_fallback', metadata={'scene': resolved.scene, 'from': 'gemini_image', 'to': 'seedream45', 'reason': exc.reason})
                return await _run_seedream_set(character, telegram_id, resolved, on_frame=on_frame, character_id=character_id)
        if provider == 'pollinations':
            return await _run_pollinations_set(character, telegram_id, resolved, on_frame=on_frame, character_id=character_id)
        # provider == 'openai'
        if OPENAI_IMAGE_AVAILABLE:
            return await _run_openai_set(character, telegram_id, resolved, on_frame=on_frame, character_id=character_id)
        # OpenAI requested but not available: use Gemini or Seedream
        if GEMINI_IMAGE_ENABLED and GEMINI_API_KEY:
            return await _run_gemini_set(character, telegram_id, resolved, on_frame=on_frame, character_id=character_id)
        return await _run_seedream_set(character, telegram_id, resolved, on_frame=on_frame, character_id=character_id)
    except BadRequestError as exc:
        body = getattr(exc, 'body', None) or {}
        err = body.get('error', body) if isinstance(body, dict) else {}
        code = err.get('code') if isinstance(err, dict) else None
        msg = str(err.get('message', '')) if isinstance(err, dict) else str(exc)
        logger.warning('OpenAI image failed user=%s scene=%s code=%s message=%s', telegram_id, resolved.scene, code, msg[:700])
        raise PhotoGenerationError('openai', code or 'bad_request') from exc


async def generate_photo_set(telegram_id: int, request: PhotoRequest, on_frame: Callable[[GeneratedPhoto, int], Awaitable[None]] | None = None, *, character_id: str = CHARACTER_ID) -> tuple[list[GeneratedPhoto], PhotoRequest]:
    character = get_character(character_id)
    # Pinterest-style variety: underspecified ordinary requests get a fresh
    # curated/LLM idea (location + camera). Explicit and private requests pass through.
    request, idea_source = await enrich_request_with_idea(telegram_id, request)
    if idea_source:
        track_event(ensure_user(telegram_id), 'photo_idea_applied', metadata={'scene': request.scene, 'source': idea_source})
    resolved = _resolve_request(telegram_id, request, character_id=character_id)
    provider = choose_photo_provider(telegram_id, resolved)
    logger.info(
        'PHOTO ROUTE selected user=%s scene=%s provider=%s gemini_enabled=%s gemini_key_present=%s model=%s',
        telegram_id, resolved.scene, provider, bool(GEMINI_IMAGE_ENABLED), bool(GEMINI_API_KEY), GEMINI_IMAGE_MODEL if provider == 'gemini_image' else '-',
    )
    try:
        return await _run_routed_photo_set(character, telegram_id, resolved, provider, on_frame=on_frame, character_id=character_id), resolved
    except PhotoGenerationError as exc:
        # Free last-resort route: ordinary scenes get a zero-cost Pollinations
        # frame instead of failing outright. Private scenes never go here.
        if (
            POLLINATIONS_ENABLED
            and provider != 'pollinations'
            and resolved.scene not in {'personal', 'lingerie', 'private_fashion'}
        ):
            logger.warning('PHOTO ROUTE FALLBACK user=%s scene=%s from=%s to=pollinations reason=%s', telegram_id, resolved.scene, provider, exc.reason)
            track_event(ensure_user(telegram_id), 'photo_provider_fallback', metadata={'scene': resolved.scene, 'from': provider, 'to': 'pollinations', 'reason': exc.reason})
            return await _run_pollinations_set(character, telegram_id, resolved, on_frame=on_frame, character_id=character_id), resolved
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

def query_community_photos(
    telegram_id: int,
    character_id: str,
    scene: str,
    relationship_level: int,
    count: int = 1,
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
            PhotoDelivery.telegram_file_id.isnot(None),
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
            }
            for r in rows
        ]


_PRIVATE_LIBRARY_SCENES = {'personal', 'lingerie', 'private_fashion'}

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
):
    """Serve a ready Telegram photo when ordinary free AI generation fails."""
    if request.scene in _PRIVATE_LIBRARY_SCENES:
        return []
    level = get_relationship_level(telegram_id, character_id)
    scene_order = _library_fallback_scene_order(request.scene, level)
    pack = choose_fallback_pack(telegram_id, CHARACTER_ID, level, scene_order)
    if not pack or not pack.photos:
        logger.warning('library failure fallback empty user=%s requested_scene=%s level=%s', telegram_id, request.scene, level)
        return []

    actual_caption = caption or random.choice(AUTO_CAPTIONS.get(pack.scene, ('вот 😌',)))
    fallback_caption = f'генерация сейчас капризничает, поэтому держи один из моих готовых кадров 😌\n\n{actual_caption}'
    sent_messages = []
    try:
        for idx, item in enumerate(pack.photos):
            row_id = _insert_delivery_row(telegram_id, pack.scene, 'free', provider='telegram_library_fallback', estimated_cost_usd=0.0, character_id=character_id)
            sent = await bot.send_photo(
                chat_id, item.file_id, caption=fallback_caption if idx == 0 else None,
                reply_markup=_photo_action_markup(row_id, item),
            )
            _attach_delivery_file(row_id, sent.photo[-1].file_id if sent.photo else item.file_id)
            sent_messages.append(sent)
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
        pack = choose_fallback_pack(telegram_id, CHARACTER_ID, level, scene_order)
        if not pack or not pack.photos or pack.id in used_pack_ids:
            break
        used_pack_ids.add(pack.id)
        remaining = needed - len(sent_messages)
        chosen_items = list(pack.photos[:remaining])
        sent_item_ids: list[int] = []
        try:
            for item in chosen_items:
                row_id = _insert_delivery_row(telegram_id, request.scene, 'free', provider='telegram_library_topup', estimated_cost_usd=0.0)
                sent = await bot.send_photo(
                    chat_id, item.file_id, reply_markup=_photo_action_markup(row_id, item),
                )
                _attach_delivery_file(row_id, sent.photo[-1].file_id if sent.photo else item.file_id)
                sent_messages.append(sent)
                sent_item_ids.append(int(item.item_id))
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
):
    stage = get_relationship_stage(telegram_id, character_id)
    if not scene_allowed_for_stage(request.scene, stage):
        raise PermissionError('scene_locked')
    if requires_adult_confirmation(request) and not is_adult_confirmed(telegram_id):
        raise PermissionError('age_gate')
    if delivery_type == 'free' and not has_free_photo(telegram_id, character_id):
        raise PermissionError('quota')
    if delivery_type == 'credit' and get_photo_credits(telegram_id) <= 0:
        raise PermissionError('no_credit')

    caption = caption or random.choice(AUTO_CAPTIONS.get(request.scene, ('вот 😌',)))
    sent_messages = []

    # Community pool first: re-use AI-generated photos from other users
    # requesting the same character+scene, saving API cost. When the pool
    # has unseen content the user gets fresh-to-them photos instantly.
    if delivery_type in {'free', 'story'} and COMMUNITY_POOL_ENABLED and request.scene not in _PRIVATE_LIBRARY_SCENES:
        level = get_relationship_level(telegram_id, character_id)
        community_photos = query_community_photos(telegram_id, character_id, request.scene, level, count=PHOTO_SET_SIZE)
        if community_photos:
            for idx, cp in enumerate(community_photos):
                row_id = _insert_delivery_row(
                    telegram_id, request.scene, 'free',
                    provider='community_pool', estimated_cost_usd=0.0,
                    character_id=character_id,
                    source_delivery_id=cp['id'],
                )
                sent = await bot.send_photo(
                    chat_id, cp['telegram_file_id'],
                    caption=caption if idx == 0 else None,
                    reply_markup=_photo_action_markup(row_id),
                )
                _attach_delivery_file(row_id, sent.photo[-1].file_id if sent.photo else cp['telegram_file_id'])
                sent_messages.append(sent)
                logger.info('community photo delivered user=%s scene=%s source=%s frame=%s/%s',
                            telegram_id, request.scene, cp['id'], idx + 1, len(community_photos))
            _bump_photo_usage(telegram_id, 'free', character_id=character_id)
            uid = ensure_user(telegram_id)
            track_event(uid, 'photo_delivered', value=0.0, metadata={
                'scene': request.scene, 'provider': 'community_pool',
                'count': len(sent_messages),
            })
            logger.info('community pool set delivered user=%s scene=%s count=%s',
                        telegram_id, request.scene, len(sent_messages))
            return sent_messages

    # Cost-first routing for beta: ordinary free requests use a curated Telegram file_id library first.
    # Custom/paid-credit/admin requests still exercise AI generation so the user gets bespoke output.
    if delivery_type in {'free', 'story'}:
        library_pack = choose_unseen_pack(telegram_id, character_id, request.scene, get_relationship_level(telegram_id, character_id))
        if library_pack and library_pack.photos:
            for idx, item in enumerate(library_pack.photos):
                row_id = _insert_delivery_row(telegram_id, request.scene, 'free', provider='telegram_library', estimated_cost_usd=0.0, character_id=character_id)
                sent = await bot.send_photo(
                    chat_id, item.file_id, caption=caption if idx == 0 else None,
                    reply_markup=_photo_action_markup(row_id, item),
                )
                _attach_delivery_file(row_id, sent.photo[-1].file_id if sent.photo else item.file_id)
                sent_messages.append(sent)
                logger.info('library photo frame delivered user=%s scene=%s pack=%s frame=%s/%s', telegram_id, request.scene, library_pack.pack_key, idx + 1, len(library_pack.photos))
            mark_pack_seen(telegram_id, library_pack.id)
            _bump_photo_usage(telegram_id, 'free', character_id=character_id)
            uid = ensure_user(telegram_id)
            track_event(uid, 'photo_delivered', value=0.0, metadata={'scene': request.scene, 'provider': 'telegram_library', 'count': len(sent_messages), 'pack_key': library_pack.pack_key})
            track_event(uid, 'photo_library_served', metadata={'scene': request.scene, 'pack_key': library_pack.pack_key, 'level': library_pack.relationship_level})
            logger.info('library photo set delivered user=%s scene=%s pack=%s count=%s', telegram_id, request.scene, library_pack.pack_key, len(sent_messages))
            return sent_messages

    async def _send_frame(result: GeneratedPhoto, idx: int):
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
            # reuse them instead of paying for a duplicate generation.
            community_shared=True,
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
        # The product promise for ordinary free photos is: if AI cannot make a
        # fresh image, use the curated library instead of returning an empty
        # failure. Exact-scene library was already checked above; this second
        # pass may choose another unlocked ordinary scene as a graceful fallback.
        if delivery_type in {'free', 'story'}:
            fallback_sent = await _deliver_library_failure_fallback(bot, chat_id, telegram_id, request, character_id=character_id)
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
    current_state = get_state(telegram_id)
    recent_outfits = (_json_list(getattr(current_state, 'recent_outfits_json', '[]')) + list(resolved.pack_outfits))[-6:]
    recent_hair = (_json_list(getattr(current_state, 'recent_hairstyles_json', '[]')) + [resolved.hairstyle])[-4:]
    update_state(
        telegram_id,
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
            'provider': row.provider, 'created_at': row.created_at,
        }


def get_latest_photo_delivery(telegram_id: int):
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            return None
        row = s.scalar(
            select(PhotoDelivery)
            .where(PhotoDelivery.user_id == user.id, PhotoDelivery.telegram_file_id.is_not(None))
            .order_by(PhotoDelivery.created_at.desc(), PhotoDelivery.id.desc())
        )
        if not row:
            return None
        return {
            'id': row.id, 'scene': row.scene, 'telegram_file_id': row.telegram_file_id,
            'provider': row.provider, 'created_at': row.created_at,
        }


GALLERY_PAGE_SIZE = 6


def get_gallery_page(telegram_id: int, page: int = 0) -> dict:
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
            .where(PhotoDelivery.user_id == user.id, PhotoDelivery.telegram_file_id.is_not(None))
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
