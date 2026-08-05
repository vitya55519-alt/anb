from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import random
import re
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Awaitable, Callable

import httpx
from aiogram import Bot
from aiogram.types import BufferedInputFile
from openai import AsyncOpenAI, BadRequestError
from sqlalchemy import select

from config import (
    CHARACTER_ID,
    IMAGE_API_KEY, IMAGE_BASE_URL, IMAGE_MODEL, IMAGE_SIZE, IMAGE_QUALITY, OPENAI_IMAGE_ESTIMATED_COST_USD,
    FREE_PHOTOS_LEVEL_1_2, FREE_PHOTOS_LEVEL_3_6, PHOTO_COST_STARS,
    FAL_KEY, FAL_MODEL, FAL_IMAGE_SIZE, FAL_TIMEOUT_SECONDS,
    FAL_CONNECT_TIMEOUT_SECONDS, FAL_WRITE_TIMEOUT_SECONDS, FAL_POOL_TIMEOUT_SECONDS,
    FAL_RETRIES, FAL_RETRY_BACKOFF_SECONDS, FAL_ESTIMATED_COST_USD,
    PHOTO_ROUTER_MODE, PHOTO_SET_SIZE,
)
from models.app_models import User
from models.relationship_models import UserCharacterRelationship
from models.photo_models import PhotoDailyUsage, PhotoDelivery, PhotoOffer
from services.db import SessionLocal
from services.character_service import get_anna
from services.test_mode import get_stage as get_test_stage
from services.access_service import is_premium
from services.user_service import ensure_user, get_state, update_state, is_adult_confirmed
from services.payments import consume_photo_credit, get_photo_credits
from services.adaptation_service import get_visual_preferences
from services.analytics_service import track_event
from services.state_service import ensure_life_state

logger = logging.getLogger(__name__)
openai_client = AsyncOpenAI(api_key=IMAGE_API_KEY, base_url=IMAGE_BASE_URL)

SCENES = {
    'selfie': 'a believable personal smartphone selfie made specifically to send to the person she is chatting with',
    'home': 'a relaxed personal smartphone photo at home, spontaneous rather than a catalogue shoot',
    'park': 'a natural personal smartphone photo during a walk in a green city park',
    'cafe': 'a personal smartphone photo in a cozy modern cafe',
    'street': 'a natural smartphone street-style photo while walking through a lively city neighborhood',
    'shop': 'a personal shopping-day smartphone photo in a stylish boutique or modern shopping mall',
    'car': 'a believable personal smartphone photo inside a clean modern car while parked',
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
    'personal': 'a warm personal lifestyle portrait made especially for someone she trusts',
    'lingerie': 'tasteful adult glamour/boudoir fashion in lingerie, non-explicit and fully covered by the garment',
    'private_fashion': 'premium private adult fashion portrait, non-explicit, polished and highly personalized',
}

SCENE_LEVELS = {
    'selfie': 1, 'home': 1, 'park': 1, 'cafe': 1, 'street': 1,
    'mirror': 2, 'outfit': 2, 'shop': 2, 'car': 2,
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
    'home':'home',
    'park':'warm_outdoor', 'street':'warm_outdoor', 'embankment':'warm_outdoor',
    'mirror':'fashion', 'outfit':'fashion', 'fashion':'fashion',
    'restaurant':'evening', 'evening':'evening', 'bar':'evening', 'karaoke':'evening', 'rooftop':'evening', 'club':'evening',
    'personal':'personal', 'private_fashion':'personal',
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
    'long straight dark brunette hair worn loose',
    'soft loose waves with a side part',
    'a sleek high ponytail',
    'a low ponytail with a few natural face-framing strands',
    'a neat high bun',
    'a half-up hairstyle with long hair down',
    'a loose dark brunette braid falling down her back',
]

SHOT_VARIANTS = {
    'selfie': ['front-camera selfie at arm’s length, natural eye contact', 'slightly high-angle front-camera selfie, spontaneous smartphone perspective', 'best polished personal selfie with flattering natural phone-camera framing'],
    'home': ['natural handheld home photo, relaxed posture', 'more styled mirror or self-timer home photo, confident posture', 'premium full-body home photo with the strongest composition and direct eye contact'],
    'park': ['natural walking photo in the park', 'more stylish three-quarter photo near greenery or flowers', 'premium full-body golden-hour park photo with a strong fashion-lifestyle composition'],
    'cafe': ['front-camera cafe selfie while seated', 'stylish three-quarter cafe portrait with coffee in frame', 'premium cafe portrait with beautiful window light and the strongest composition'],
    'street': ['natural walking street photo', 'stylish city street portrait with a confident pose', 'premium street-style full-body photo with strong urban composition'],
    'shop': ['natural shopping-day mirror or aisle photo', 'stylish boutique mirror photo with shopping details', 'premium fashion-shopping portrait with polished composition'],
    'car': ['natural parked-car selfie', 'stylish three-quarter car interior portrait', 'premium personal car photo with flattering daylight and polished framing'],
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
    'personal': ['warm personal portrait', 'more styled personal photo with direct eye contact', 'premium personalized fashion-lifestyle portrait made especially for the recipient'],
    'lingerie': ['tasteful adult glamour portrait, non-explicit', 'more polished mirror-style lingerie fashion portrait, non-explicit', 'premium tasteful boudoir-fashion portrait with opaque garment coverage'],
    'private_fashion': ['tasteful private fashion portrait with opaque coverage', 'more polished private fashion portrait with confident styling', 'premium personalized private fashion portrait, non-explicit and opaque'],
}

PACK_TIER_RULES = (
    'BASE: believable, natural, relaxed and attractive; this is the first frame of the set.',
    'STYLISH: visibly more polished styling and a more confident pose than frame one.',
    'PREMIUM: strongest outfit styling, best light, best composition and the biggest wow-effect allowed at this relationship level.',
)
LEVEL_VISUAL_RULES = {
    1: 'Relationship visual level 1/6: friendly, approachable, casual and fully clothed. Attractive but not deliberately intimate.',
    2: 'Relationship visual level 2/6: more feminine and fitted styling, clearer waist definition, still casual and fully clothed.',
    3: 'Relationship visual level 3/6: noticeably more stylish, confident and figure-flattering fashion while remaining mainstream and fully clothed.',
    4: 'Relationship visual level 4/6: polished personal fashion, more confident poses and stronger fitted silhouettes, still non-explicit.',
    5: 'Relationship visual level 5/6: glamorous personalized styling and more private-feeling fashion; keep ordinary scenes fully clothed and tasteful.',
    6: 'Relationship visual level 6/6: premium personalized styling, strongest confident fashion presentation and clear exclusivity; remain non-explicit.',
}
OPENAI_LEVEL_VISUAL_RULES = {
    1: 'Relationship visual level 1/6: simple casual styling, natural pose, everyday social-media feel.',
    2: 'Relationship visual level 2/6: more coordinated clothing, cleaner styling and a little more confidence, fully clothed.',
    3: 'Relationship visual level 3/6: noticeably more fashionable outfit, better accessories and stronger composition, fully clothed.',
    4: 'Relationship visual level 4/6: polished personal fashion, confident lifestyle pose and more intentional styling, fully clothed.',
    5: 'Relationship visual level 5/6: premium personalized styling, richer venue details and more exclusive-feeling composition, fully clothed.',
    6: 'Relationship visual level 6/6: strongest premium styling, best accessories, lighting and composition; sophisticated and exclusive while fully clothed and general-audience.',
}

SEASON_RULES = {
    'summer': 'Warm summer weather. Use breathable summer clothing. No sweaters, hoodies, coats, thick knitwear or winter styling unless explicitly requested.',
    'spring': 'Mild spring weather. Use light layers and season-appropriate clothing; avoid heavy winter garments.',
    'autumn': 'Cool autumn weather. Light knitwear, fitted jackets and trousers are believable; avoid summer-only beachwear unless requested.',
    'winter': 'Cold winter weather outdoors. Use fitted season-appropriate layers, coats or knitwear outdoors; indoor venues may use normal fitted outfits.',
}

OPENAI_IDENTITY_LOCK = (
    'The supplied fully clothed reference defines Anna’s current face identity. '
    'Create the same fictional adult woman, Anna, age 26. Preserve stable identity traits: '
    'recognizable oval face, defined cheekbones, almond-shaped brown eyes and spacing, dark shaped eyebrows, '
    'straight refined nose, full lips, jawline, warm light-to-medium skin tone, and dark brunette hair color. '
    'Keep her overall appearance recognizable and realistic. Do not change age or ethnicity and do not substitute another woman.'
)
SEEDREAM_IDENTITY_LOCK = (
    'The supplied reference defines Anna’s permanent NEW identity. '
    'Create the SAME fictional adult woman, Anna, age 26. Identity preservation has absolute priority. '
    'Preserve her oval face, defined cheekbones, almond-shaped brown eyes and spacing, dark shaped eyebrows, '
    'straight refined nose, full lips, jawline, warm light-to-medium skin tone, dark brunette hair color, '
    'and stable body proportions matching the supplied reference. Do not drift back to the previous Anna face, '
    'do not substitute another woman, do not change age or ethnicity, and do not redesign her facial proportions.'
)
QUALITY_BLOCK = (
    'Photorealistic smartphone/lifestyle photography, realistic skin texture, realistic hands and anatomy, '
    'natural hair strands, coherent perspective, premium photographic detail, soft cinematic realism, shallow depth of field where appropriate.'
)
OPENAI_GENERAL_AUDIENCE_BLOCK = (
    'Mainstream general-audience lifestyle photograph. The woman remains fully clothed in opaque everyday clothing. '
    'Use an ordinary neckline and a relaxed natural pose. Keep the composition focused on the scene, face, outfit, and environment rather than anatomy. '
    'The image should read as an everyday social-media or personal travel/lifestyle photo, not glamour or boudoir photography.'
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
    location: str = ''
    angle: str = ''
    mood: str = 'warm, natural'
    season: str = ''
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


def _user_rel(session, telegram_id: int):
    user = session.scalar(select(User).where(User.telegram_id == str(telegram_id)))
    if not user:
        return None, None
    rel = session.scalar(select(UserCharacterRelationship).where(
        UserCharacterRelationship.user_id == user.id,
        UserCharacterRelationship.character_id == CHARACTER_ID,
    ))
    return user, rel


def get_relationship_stage(telegram_id: int) -> str:
    override = get_test_stage(telegram_id)
    if override:
        return override
    ensure_user(telegram_id)
    with SessionLocal() as session:
        _, rel = _user_rel(session, telegram_id)
        return rel.stage if rel else 'stranger'


def get_relationship_level(telegram_id: int) -> int:
    return STAGE_INDEX.get(get_relationship_stage(telegram_id), 0) + 1


def get_daily_limit(telegram_id: int) -> int:
    level = get_relationship_level(telegram_id)
    return FREE_PHOTOS_LEVEL_3_6 if level >= 3 else FREE_PHOTOS_LEVEL_1_2


def get_usage(telegram_id: int):
    uid = ensure_user(telegram_id)
    with SessionLocal() as session:
        row = session.scalar(select(PhotoDailyUsage).where(
            PhotoDailyUsage.user_id == uid,
            PhotoDailyUsage.character_id == CHARACTER_ID,
            PhotoDailyUsage.usage_date == _today(),
        ))
        limit = get_daily_limit(telegram_id)
        return (row.free_used if row else 0, row.paid_used if row else 0, limit)


def has_free_photo(telegram_id: int) -> bool:
    used, _, limit = get_usage(telegram_id)
    return used < limit


def scene_allowed_for_stage(scene: str, stage: str) -> bool:
    return STAGE_INDEX.get(stage, 0) + 1 >= SCENE_LEVELS.get(scene, 99)


def is_custom_request(request: PhotoRequest) -> bool:
    return request.scene in {'lingerie', 'private_fashion'} or bool(request.customized)


def requires_adult_confirmation(request: PhotoRequest) -> bool:
    return request.scene in {'lingerie', 'private_fashion'} or bool(INTIMATE_STYLE.search(' '.join([request.clothing, request.location, request.angle])))


def build_photo_menu(telegram_id: int):
    used, paid, limit = get_usage(telegram_id)
    return {
        'stage': get_relationship_stage(telegram_id),
        'level': get_relationship_level(telegram_id),
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
        hairstyle = 'a long dark brunette braid falling down her back'
    elif any(x in low for x in ('хвост', 'ponytail')):
        hairstyle = 'a sleek high ponytail'
    elif any(x in low for x in ('пучок', 'bun')):
        hairstyle = 'a neat high bun'
    elif any(x in low for x in ('распущ', 'волнист', 'loose hair', 'waves')):
        hairstyle = 'long loose softly wavy dark brunette hair'

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
    folder = _reference_folder(character)
    # GPT Image 2 gets a neutral, fully clothed identity anchor for ordinary scenes.
    for candidate in ('00_openai_safe_fullbody.png', '00_identity_face_new.png', '01_face_front_white_top.png'):
        path = folder / candidate
        if path.exists():
            return path
    raise FileNotFoundError('У Анны нет доступных reference-фото')


def _seedream_reference_path(character: dict) -> Path:
    folder = _reference_folder(character)
    for candidate in ('00_seedream_face_safe.png', '00_identity_face_new.png'):
        p = folder / candidate
        if p.exists():
            return p
    return _reference_path(character, 'selfie')


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


def _choose_progression_outfits(telegram_id: int, request: PhotoRequest, season: str) -> tuple[str, ...]:
    if request.clothing:
        return tuple(request.clothing for _ in range(PHOTO_SET_SIZE))
    state = get_state(telegram_id)
    level = get_relationship_level(telegram_id)
    pool = _wardrobe_pool(request.scene, level, season)
    uid = ensure_user(telegram_id)
    visual_prefs = get_visual_preferences(uid, CHARACTER_ID)
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
        # Roughly half personalization, half diversity/surprise. Never override an explicit user outfit.
        if favorite_color and SCENE_GROUP.get(request.scene) != 'adult' and random.random() < 0.50:
            chosen = f'{chosen}, using a {favorite_color}-led color palette'
        picks.append(chosen)
    return tuple(picks)


def _resolve_request(telegram_id: int, request: PhotoRequest) -> PhotoRequest:
    state = ensure_life_state(telegram_id)
    season = request.season or _default_season()
    pack_outfits = tuple(request.pack_outfits) if request.pack_outfits else _choose_progression_outfits(telegram_id, request, season)
    clothing = pack_outfits[-1] if pack_outfits else request.clothing
    if request.hairstyle:
        hairstyle = request.hairstyle
    else:
        recent_hair = {x.strip().lower() for x in _json_list(getattr(state, 'recent_hairstyles_json', '[]'))}
        if state.hairstyle:
            recent_hair.add(state.hairstyle.strip().lower())
        hair_pool = [x for x in HAIRSTYLE_POOL if x.strip().lower() not in recent_hair] or HAIRSTYLE_POOL
        uid = ensure_user(telegram_id)
        visual_prefs = get_visual_preferences(uid, CHARACTER_ID)
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
        location = f"{SCENES['selfie']}; keep it consistent with Anna's current fictional day context: location={state.location}, activity={activity}"
    else:
        location = SCENES.get(request.scene, SCENES['selfie'])
    return replace(request, clothing=clothing, hairstyle=hairstyle, location=location, season=season, pack_outfits=pack_outfits)


def _shot_variant(scene: str, index: int, requested_angle: str = '') -> str:
    if requested_angle:
        return requested_angle
    variants = SHOT_VARIANTS.get(scene, SHOT_VARIANTS['selfie'])
    return variants[index % len(variants)]


def _build_prompt(request: PhotoRequest, shot_index: int, seedream: bool = False, relationship_level: int = 1) -> str:
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
    season = request.season or _default_season()
    season_rule = SEASON_RULES.get(season, SEASON_RULES['summer'])
    if seedream:
        identity = SEEDREAM_IDENTITY_LOCK
        personal = (
            'This is a tasteful adult fashion/glamour photo made specifically to send to someone she is chatting with. '
            'The photo must plausibly be made by Anna herself using a front camera, a mirror, or a smartphone self-timer; no invisible photographer. '
            'Keep the styling polished and personal while remaining non-explicit.'
        )
        safety = (
            'Tasteful adult fashion/editorial styling only. No nudity, no exposed nipples or genitals. '
            'Any lingerie garment must provide opaque coverage. Preserve identity above styling.'
        )
    else:
        identity = OPENAI_IDENTITY_LOCK
        personal = (
            'This should feel like a normal personal photo Anna has just taken herself to send to someone she is chatting with. '
            'Every frame must plausibly be made by Anna herself using a front camera, a mirror, or a smartphone self-timer; no invisible photographer. '
            'Use believable smartphone framing and a natural expression. The result should feel Pinterest-like and intentionally styled, '
            'but still like a real personal lifestyle photo rather than a studio glamour shoot.'
        )
        safety = OPENAI_GENERAL_AUDIENCE_BLOCK
    return (
        f'{identity}\n'
        f'SCENE: {scene}. {request.location}.\n'
        f'SEASON/WEATHER: {season}. {season_rule}\n'
        f'RELATIONSHIP VISUAL PROGRESSION: {visual_rule}\n'
        f'PROGRESSION PACK FRAME {shot_index + 1}/{PHOTO_SET_SIZE}: {tier_rule}\n'
        f'WARDROBE: {wardrobe}. ' + (
            'Use tasteful fashion fit and waist definition while preserving the underlying body proportions. ' if seedream else
            'Use a polished, well-fitted, general-audience outfit; preserve the underlying body proportions and do not emphasize chest, hips, buttocks or other body parts. '
        ) +
        'The outfit must be believable for this exact venue, weather and time of day. Do not reuse a heavy sweater or hoodie in a visibly warm summer scene.\n'
        f'HAIRSTYLE: {request.hairstyle}.\n'
        f'CAMERA/POSE: {angle}.\n'
        f'MOOD: {request.mood}.\n'
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


def _file_data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or 'image/png'
    encoded = base64.b64encode(path.read_bytes()).decode('ascii')
    return f'data:{mime};base64,{encoded}'


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


async def _openai_one_frame(character: dict, telegram_id: int, request: PhotoRequest, i: int, *, safe_retry: bool = False) -> GeneratedPhoto:
    ref = _reference_path(character, request.scene)
    level = get_relationship_level(telegram_id)
    if safe_retry:
        fallback_outfit = (
            'a simple lightweight summer midi dress with normal coverage and clean everyday styling'
            if (request.season or _default_season()) == 'summer' else
            'a simple season-appropriate midi dress with normal coverage and clean everyday styling'
        )
        safe_request = replace(request, clothing=fallback_outfit, pack_outfits=tuple(fallback_outfit for _ in range(PHOTO_SET_SIZE)), mood='natural, relaxed')
        prompt = _build_prompt(safe_request, i, seedream=False, relationship_level=min(level, 3)) + (
            '\nSAFE RETRY: Strictly general-audience, fully clothed everyday lifestyle fashion. Neutral pose, ordinary neckline, no body-part emphasis, no glamour cues.'
        )
    else:
        prompt = _build_prompt(request, i, seedream=False, relationship_level=level)
    started = time.monotonic()
    with ref.open('rb') as image_file:
        result = await openai_client.images.edit(
            model=IMAGE_MODEL,
            image=image_file,
            prompt=prompt,
            size=IMAGE_SIZE,
            quality=IMAGE_QUALITY,
            n=1,
        )
    elapsed = time.monotonic() - started
    photo = replace(_extract_openai_many(result)[0], estimated_cost_usd=OPENAI_IMAGE_ESTIMATED_COST_USD)
    logger.info('OpenAI frame success user=%s scene=%s frame=%s/%s safe_retry=%s elapsed=%.1fs', telegram_id, request.scene, i + 1, PHOTO_SET_SIZE, safe_retry, elapsed)
    return photo


async def _run_openai_set(
    character: dict,
    telegram_id: int,
    request: PhotoRequest,
    on_frame: Callable[[GeneratedPhoto, int], Awaitable[None]] | None = None,
) -> list[GeneratedPhoto]:
    ref = _reference_path(character, request.scene)
    logger.info('OpenAI normal-photo set request user=%s scene=%s reference=%s count=%s safe_prompt=true', telegram_id, request.scene, ref.name, PHOTO_SET_SIZE)
    outputs: list[GeneratedPhoto] = []
    for i in range(PHOTO_SET_SIZE):
        try:
            photo = await _openai_one_frame(character, telegram_id, request, i)
        except BadRequestError as exc:
            body = getattr(exc, 'body', None) or {}
            err = body.get('error', body) if isinstance(body, dict) else {}
            code = err.get('code') if isinstance(err, dict) else None
            msg = str(err.get('message', '')) if isinstance(err, dict) else str(exc)
            logger.warning('OpenAI frame failed user=%s scene=%s frame=%s/%s code=%s message=%s', telegram_id, request.scene, i + 1, PHOTO_SET_SIZE, code, msg[:700])
            track_event(ensure_user(telegram_id), 'photo_frame_blocked' if code == 'moderation_blocked' else 'photo_frame_failed', metadata={'scene': request.scene, 'frame': i + 1, 'provider': 'openai', 'reason': code or 'bad_request'})
            if code == 'moderation_blocked':
                try:
                    logger.info('OpenAI safe retry user=%s scene=%s frame=%s/%s', telegram_id, request.scene, i + 1, PHOTO_SET_SIZE)
                    photo = await _openai_one_frame(character, telegram_id, request, i, safe_retry=True)
                    track_event(ensure_user(telegram_id), 'photo_safe_retry_success', metadata={'scene': request.scene, 'frame': i + 1, 'provider': 'openai'})
                except BadRequestError as retry_exc:
                    retry_body = getattr(retry_exc, 'body', None) or {}
                    retry_err = retry_body.get('error', retry_body) if isinstance(retry_body, dict) else {}
                    retry_code = retry_err.get('code') if isinstance(retry_err, dict) else None
                    logger.warning('OpenAI safe retry failed user=%s scene=%s frame=%s/%s code=%s', telegram_id, request.scene, i + 1, PHOTO_SET_SIZE, retry_code)
                    if outputs:
                        break
                    raise PhotoGenerationError('openai', retry_code or code or 'bad_request') from retry_exc
                except Exception as retry_exc:
                    logger.warning('OpenAI safe retry transport failure user=%s scene=%s frame=%s/%s type=%s', telegram_id, request.scene, i + 1, PHOTO_SET_SIZE, type(retry_exc).__name__)
                    if outputs:
                        break
                    raise PhotoGenerationError('openai', type(retry_exc).__name__) from retry_exc
            elif outputs:
                break
            else:
                raise PhotoGenerationError('openai', code or 'bad_request') from exc
        except Exception as exc:
            if outputs:
                logger.warning('OpenAI partial set user=%s scene=%s delivered=%s/%s stopped_reason=%s', telegram_id, request.scene, len(outputs), PHOTO_SET_SIZE, type(exc).__name__)
                break
            raise

        outputs.append(photo)
        track_event(ensure_user(telegram_id), 'photo_frame_ready', value=elapsed, metadata={'scene': request.scene, 'frame': i + 1, 'provider': 'openai'})
        if i == 0:
            track_event(ensure_user(telegram_id), 'photo_first_frame_ready', value=elapsed, metadata={'scene': request.scene, 'provider': 'openai'})
        if on_frame:
            await on_frame(photo, i)
    if not outputs:
        raise PhotoGenerationError('openai', 'no_image')
    return outputs


async def _run_seedream_set(
    character: dict,
    telegram_id: int,
    request: PhotoRequest,
    on_frame: Callable[[GeneratedPhoto, int], Awaitable[None]] | None = None,
) -> list[GeneratedPhoto]:
    ref = _seedream_reference_path(character)
    reference_uri = _file_data_uri(ref)
    out: list[GeneratedPhoto] = []
    logger.info(
        'Seedream set request user=%s scene=%s reference=%s target_count=%s per_request=1 timeout=%ss retries=%s',
        telegram_id, request.scene, ref.name, PHOTO_SET_SIZE, FAL_TIMEOUT_SECONDS, FAL_RETRIES,
    )
    for i in range(PHOTO_SET_SIZE):
        prompt = _build_prompt(request, i, seedream=True, relationship_level=get_relationship_level(telegram_id)) + (
            '\nCreate exactly ONE photo for this shot. Keep the same hairstyle, location, '
            'face identity and body proportions as the other photos in this set. '
            'Make this framing clearly different from the previous shot while staying in the same photo session.'
        )
        frame_started = time.monotonic()
        try:
            result = await _seedream_request(prompt, [reference_uri], 1, request_label=f'{request.scene}:{i + 1}/{PHOTO_SET_SIZE}')
        except PhotoGenerationError as exc:
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
        return 'openai'
    if mode in {'fal', 'seedream', 'seedream45'}:
        return 'seedream45'

    # HYBRID routing:
    # - ordinary fully-clothed lifestyle/fashion scenes -> GPT Image 2
    # - intentionally more private/bold scenes -> Seedream
    # `personal` and private scenes are deliberately kept off the OpenAI image
    # path because even fully-clothed personal prompts can be classified as sexual
    # when combined with identity-preserving image edits.
    combined = ' '.join([request.scene, request.clothing, request.location, request.angle]).lower()
    if request.scene in {'personal', 'lingerie', 'private_fashion'} or INTIMATE_STYLE.search(combined):
        logger.info('Hybrid photo route scene=%s -> seedream45', request.scene)
        return 'seedream45'
    logger.info('Hybrid photo route scene=%s -> openai', request.scene)
    return 'openai'


async def generate_photo_set(telegram_id: int, request: PhotoRequest, on_frame: Callable[[GeneratedPhoto, int], Awaitable[None]] | None = None) -> tuple[list[GeneratedPhoto], PhotoRequest]:
    character = get_anna()
    resolved = _resolve_request(telegram_id, request)
    provider = choose_photo_provider(telegram_id, resolved)
    try:
        if provider == 'seedream45':
            return await _run_seedream_set(character, telegram_id, resolved, on_frame=on_frame), resolved
        return await _run_openai_set(character, telegram_id, resolved, on_frame=on_frame), resolved
    except BadRequestError as exc:
        body = getattr(exc, 'body', None) or {}
        err = body.get('error', body) if isinstance(body, dict) else {}
        code = err.get('code') if isinstance(err, dict) else None
        msg = str(err.get('message', '')) if isinstance(err, dict) else str(exc)
        logger.warning('OpenAI image failed user=%s scene=%s code=%s message=%s', telegram_id, request.scene, code, msg[:700])
        raise PhotoGenerationError('openai', code or 'bad_request') from exc
    except PhotoGenerationError:
        raise
    except Exception as exc:
        logger.exception('photo provider failed provider=%s user=%s scene=%s', provider, telegram_id, request.scene)
        raise PhotoGenerationError(provider, type(exc).__name__) from exc


async def generate_photo(telegram_id: int, request: PhotoRequest) -> GeneratedPhoto:
    """Compatibility wrapper for callers/tests that expect one result."""
    photos, _ = await generate_photo_set(telegram_id, request)
    return photos[0]


def _record(telegram_id: int, scene: str, delivery_type: str, file_id=None, url=None, provider='unknown', estimated_cost_usd=0.0):
    uid = ensure_user(telegram_id)
    with SessionLocal() as session:
        usage = session.scalar(select(PhotoDailyUsage).where(
            PhotoDailyUsage.user_id == uid,
            PhotoDailyUsage.character_id == CHARACTER_ID,
            PhotoDailyUsage.usage_date == _today(),
        ))
        if not usage:
            usage = PhotoDailyUsage(user_id=uid, character_id=CHARACTER_ID, usage_date=_today())
            session.add(usage)
            session.flush()
        # One generated SET counts as one free/paid request, regardless of set size.
        if delivery_type == 'free':
            usage.free_used += 1
        elif delivery_type in {'credit', 'paid'}:
            usage.paid_used += 1
        session.add(PhotoDelivery(
            user_id=uid,
            character_id=CHARACTER_ID,
            scene=scene,
            delivery_type=delivery_type,
            telegram_file_id=file_id,
            image_url=url,
            provider=provider,
            estimated_cost_usd=estimated_cost_usd,
        ))
        session.commit()


async def deliver_photo(
    bot: Bot,
    chat_id: int,
    telegram_id: int,
    request: PhotoRequest,
    delivery_type: str = 'free',
    caption: str | None = None,
):
    stage = get_relationship_stage(telegram_id)
    if not scene_allowed_for_stage(request.scene, stage):
        raise PermissionError('scene_locked')
    if requires_adult_confirmation(request) and not is_adult_confirmed(telegram_id):
        raise PermissionError('age_gate')
    if delivery_type == 'free' and not has_free_photo(telegram_id):
        raise PermissionError('quota')
    if delivery_type == 'credit' and get_photo_credits(telegram_id) <= 0:
        raise PermissionError('no_credit')

    caption = caption or random.choice(AUTO_CAPTIONS.get(request.scene, ('вот 😌',)))
    sent_messages = []

    async def _send_frame(result: GeneratedPhoto, idx: int):
        item_caption = caption if idx == 0 else None
        if result.url:
            sent = await bot.send_photo(chat_id, result.url, caption=item_caption)
        else:
            sent = await bot.send_photo(
                chat_id,
                BufferedInputFile(result.data, filename=f'anna_{request.scene}_{idx+1}.png'),
                caption=item_caption,
            )
        sent_messages.append(sent)
        logger.info('photo frame delivered user=%s scene=%s frame=%s/%s provider=%s', telegram_id, request.scene, idx + 1, PHOTO_SET_SIZE, result.provider)

    results, resolved = await generate_photo_set(telegram_id, request, on_frame=_send_frame)
    if not sent_messages:
        raise PhotoGenerationError(results[0].provider if results else 'unknown', 'send_failed')

    # Commercial fairness: a paid photo credit is consumed only for a complete pack.
    # A one-frame free partial also does not burn the daily request; 2/3 is considered a usable free set.
    complete = len(results) >= PHOTO_SET_SIZE
    charge_free_partial = delivery_type == 'free' and len(results) >= 2
    if delivery_type == 'credit' and complete:
        consume_photo_credit(telegram_id)
    record_delivery_type = delivery_type if complete or charge_free_partial or delivery_type == 'admin' else f'partial_{delivery_type}'
    first = sent_messages[0]
    first_result = results[0]
    file_id = first.photo[-1].file_id if first.photo else None
    total_cost = sum(x.estimated_cost_usd for x in results)
    _record(
        telegram_id, request.scene, record_delivery_type,
        file_id=file_id, url=first_result.url,
        provider=first_result.provider, estimated_cost_usd=total_cost,
    )
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
    if len(results) < PHOTO_SET_SIZE:
        track_event(uid, 'photo_partial', value=total_cost, metadata={'scene': request.scene, 'provider': first_result.provider, 'count': len(results), 'target': PHOTO_SET_SIZE})
        try:
            extra = ''
            if delivery_type == 'credit':
                extra = ' photo credit сохранила — спишу только за полный сет.'
            elif delivery_type == 'free' and len(results) < 2:
                extra = ' бесплатный запрос тоже не списала.'
            await bot.send_message(chat_id, f'часть сета уже есть 🙂 получилось {len(results)} из {PHOTO_SET_SIZE}.{extra}')
        except Exception:
            pass
    else:
        track_event(uid, 'photo_delivered', value=total_cost, metadata={'scene': request.scene, 'provider': first_result.provider, 'count': len(results)})
    logger.info('photo set delivered user=%s scene=%s provider=%s count=%s outfit=%s hair=%s',
                telegram_id, request.scene, first_result.provider, len(results), ' | '.join(resolved.pack_outfits) if resolved.pack_outfits else resolved.clothing, resolved.hairstyle)
    return sent_messages

