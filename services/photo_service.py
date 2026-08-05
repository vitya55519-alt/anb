from __future__ import annotations

import base64
import json
import logging
import mimetypes
import random
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import httpx
from aiogram import Bot
from aiogram.types import BufferedInputFile
from openai import AsyncOpenAI, BadRequestError
from sqlalchemy import select

from config import (
    CHARACTER_ID,
    IMAGE_API_KEY, IMAGE_BASE_URL, IMAGE_MODEL, IMAGE_SIZE, IMAGE_QUALITY,
    FREE_PHOTOS_LEVEL_1_2, FREE_PHOTOS_LEVEL_3_6, PHOTO_COST_STARS,
    FAL_KEY, FAL_MODEL, FAL_IMAGE_SIZE, FAL_TIMEOUT_SECONDS, FAL_ESTIMATED_COST_USD,
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

logger = logging.getLogger(__name__)
openai_client = AsyncOpenAI(api_key=IMAGE_API_KEY, base_url=IMAGE_BASE_URL)

SCENES = {
    'selfie': 'a believable personal smartphone selfie made specifically to send to the person she is chatting with',
    'home': 'a relaxed personal smartphone photo at home, spontaneous rather than a catalogue shoot',
    'park': 'a natural personal smartphone photo during a walk in a green city park',
    'cafe': 'a personal smartphone photo in a cozy modern cafe',
    'mirror': 'a realistic full-body mirror selfie in a tidy apartment, smartphone visible naturally',
    'outfit': 'a personal full-body smartphone photo showing today’s outfit',
    'evening': 'a tasteful evening portrait in an elegant fully clothed outfit',
    'fashion': 'a mainstream fashion-editorial portrait in tasteful fully clothed styling',
    'personal': 'a warm personal lifestyle portrait made especially for someone she trusts',
    'lingerie': 'tasteful adult glamour/boudoir fashion in lingerie, non-explicit and fully covered by the garment',
}

SCENE_LEVELS = {
    'selfie': 1, 'home': 1, 'park': 1, 'cafe': 1, 'outfit': 1,
    'mirror': 2, 'evening': 2, 'fashion': 3, 'personal': 4, 'lingerie': 5,
}
STAGE_INDEX = {
    'stranger': 0, 'acquaintance': 1, 'close': 2, 'intimate': 3,
    'deeply_connected': 4, 'committed': 5,
}

AUTO_CAPTIONS = {
    'selfie': ('сфоткалась для тебя 😌', 'вот такая я сейчас', 'поймала свет и решила отправить тебе'),
    'home': ('лови домашний кадр 😌', 'сегодня я дома и никуда не спешу', 'вот мой домашний режим'),
    'park': ('вышла немного пройтись 🌿', 'поймала хороший свет на прогулке', 'гуляю и решила тебе показать'),
    'cafe': ('заскочила за кофе ☕', 'сижу с кофе и вспомнила про тебя', 'кофе + хороший свет = фото тебе'),
    'mirror': ('зеркало сегодня не подвело 😏', 'ну вот, целиком', 'поймала себя в зеркале'),
    'outfit': ('вот что выбрала сегодня 😌', 'показываю образ целиком', 'как тебе сегодняшний вариант?'),
    'evening': ('вечером решила выглядеть вот так ✨', 'вечерний вариант', 'мне самой этот образ нравится'),
    'fashion': ('сегодня настроение на красивый кадр', 'немного fashion-вйба 😌'),
    'personal': ('это уже чуть более личный кадр 😌', 'ладно, этот кадр именно тебе'),
    'lingerie': ('сегодня чуть смелее обычного 😏', 'вот такой приватный fashion-настрой'),
}

SAFE_EXPLICIT = re.compile(
    r'\b(голая|голый|обнаж|без трус|без бель|соски|генитал|вагин|пенис|nude|naked|topless|explicit)\b', re.I
)
INTIMATE_STYLE = re.compile(
    r'\b(бель|lingerie|будуар|boudoir|чулк|stocking|garter|bra\b|bralette|смел\w*|daring|spicy|seductive)\b', re.I
)

# Stable wardrobe/hair pools. The resolver avoids the immediately previous state,
# so the model does not keep returning the same beige outfit and hairstyle.
OUTFIT_POOLS = {
    'selfie': [
        'a fitted black long-sleeve top with dark blue jeans',
        'a burgundy fitted turtleneck with black trousers',
        'a soft gray fitted knit top with blue jeans',
        'a dark green fitted sweater with black jeans',
        'a navy fitted top with a midi skirt',
    ],
    'home': [
        'an oversized soft gray hoodie with black leggings',
        'a fitted black long-sleeve top with comfortable gray lounge trousers',
        'a soft knit lounge set in muted blue',
        'a casual burgundy sweatshirt with dark leggings',
        'a cream cardigan over a dark fitted top with jeans',
    ],
    'park': [
        'a fitted white t-shirt with blue jeans and a light denim jacket',
        'a black athletic top with dark leggings and casual sneakers',
        'a burgundy fitted top with blue jeans',
        'a light casual summer dress with a denim jacket',
        'a gray hoodie with black leggings and white sneakers',
    ],
    'cafe': [
        'a fitted dark burgundy turtleneck with tailored dark trousers',
        'a black fitted long-sleeve top with blue high-waisted jeans',
        'a cream cardigan over a fitted black top with a midi skirt',
        'a deep green knit top with dark jeans',
        'a navy fitted sweater with a beige midi skirt',
    ],
    'mirror': [
        'a fitted black midi dress',
        'a white fitted long-sleeve top with black high-waisted trousers',
        'a burgundy fitted dress',
        'a dark green fitted top with tailored black trousers',
    ],
    'outfit': [
        'a fitted elegant black dress',
        'a burgundy fitted dress',
        'a white fitted long-sleeve top with black high-waisted trousers',
        'a dark green top with a black midi skirt',
        'a tailored monochrome navy outfit',
    ],
    'evening': [
        'an elegant fitted black evening dress',
        'a deep burgundy evening dress',
        'a dark emerald fitted evening dress',
        'a navy elegant long-sleeve dress',
    ],
    'fashion': [
        'a fitted black fashion dress with opaque fabric',
        'a tailored burgundy fashion look with opaque fabric',
        'a white fitted top with black tailored trousers',
        'a deep green fitted fashion outfit with opaque fabric',
    ],
    'personal': [
        'a soft fitted dark long-sleeve top with comfortable high-waisted trousers',
        'a fitted burgundy knit top with dark trousers',
        'a black fitted dress with long sleeves',
    ],
    'lingerie': [
        'an elegant black lingerie fashion set with opaque coverage and polished catalog styling',
        'an elegant white lingerie fashion set with opaque coverage and polished catalog styling',
        'an elegant burgundy lingerie fashion set with opaque coverage and polished catalog styling',
    ],
}
HAIRSTYLE_POOL = [
    'long straight dark brunette hair worn loose',
    'soft loose waves with a side part',
    'a sleek high ponytail',
    'a low ponytail with a few natural face-framing strands',
    'a neat high bun',
    'a half-up hairstyle with long hair down',
]

SHOT_VARIANTS = {
    'selfie': [
        'front-camera selfie at arm’s length, phone just outside the frame, natural eye contact',
        'slightly high-angle front-camera selfie, spontaneous smartphone perspective',
        'seated casual selfie with natural handheld framing and direct eye contact',
    ],
    'home': [
        'handheld smartphone selfie in the living room, natural imperfect framing',
        'mirror selfie at home with the phone visible naturally',
        'smartphone on a nearby shelf using a short self-timer, candid full-body home photo',
    ],
    'park': [
        'handheld walking selfie, slight smartphone wide-angle perspective',
        'bench selfie with greenery behind her and relaxed eye contact',
        'smartphone on a short self-timer capturing a natural walking full-body frame',
    ],
    'cafe': [
        'front-camera selfie while seated at a cafe table, slightly above eye level',
        'handheld medium close-up selfie with a coffee cup in the foreground',
        'smartphone set on the table with a short self-timer, natural seated portrait',
    ],
    'mirror': [
        'full-body mirror selfie with the smartphone visible and realistic reflection geometry',
        'three-quarter mirror selfie with phone visible and natural posture',
        'slightly closer mirror selfie showing outfit details and realistic room reflection',
    ],
    'outfit': [
        'full-body smartphone self-timer portrait, straight-on view',
        'three-quarter smartphone self-timer portrait showing the outfit silhouette',
        'mirror-style full-body personal outfit photo with natural phone-camera perspective',
    ],
    'evening': [
        'full-body personal smartphone portrait before going out',
        'three-quarter personal portrait with warm evening light',
        'mirror-style evening look photo with realistic smartphone perspective',
    ],
    'fashion': [
        'full-body editorial portrait with realistic phone-camera styling',
        'three-quarter fashion portrait with direct eye contact',
        'medium portrait emphasizing the outfit while preserving identity',
    ],
    'personal': [
        'warm handheld personal portrait made specifically to send to someone',
        'slightly high-angle personal selfie with direct eye contact',
        'relaxed indoor self-timer portrait with intimate but non-explicit personal mood',
    ],
    'lingerie': [
        'tasteful adult glamour portrait, three-quarter framing, non-explicit',
        'tasteful mirror-style glamour portrait, non-explicit and fully covered by the garment',
        'tasteful seated boudoir-fashion portrait with elegant posture, non-explicit',
    ],
}

IDENTITY_LOCK = (
    'The supplied reference defines Anna’s permanent NEW identity. '
    'Create the SAME fictional adult woman, Anna, age 26. Identity preservation has absolute priority. '
    'Preserve her oval face, defined cheekbones, almond-shaped brown eyes and spacing, dark shaped eyebrows, '
    'straight refined nose, full lips, jawline, warm light-to-medium skin tone, dark brunette hair color, '
    'and stable curvy body proportions. Do not drift back to the previous Anna face, do not substitute another woman, '
    'do not change age or ethnicity, and do not redesign her facial proportions.'
)
QUALITY_BLOCK = (
    'Photorealistic smartphone/lifestyle photography, realistic skin pores and texture, realistic hands and anatomy, '
    'natural hair strands, coherent perspective, premium photographic detail, soft cinematic realism, shallow depth of field where appropriate.'
)
NEGATIVE_BLOCK = (
    'Avoid identity drift, generic doll-like face, plastic skin, asymmetrical eyes, warped hands, extra fingers, '
    'duplicate limbs, distorted anatomy, inconsistent body proportions, text, watermark, random accessories, and overprocessed beauty filters.'
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
    return request.scene == 'lingerie' or bool(request.clothing or request.hairstyle or request.location or request.angle)


def requires_adult_confirmation(request: PhotoRequest) -> bool:
    return request.scene == 'lingerie' or bool(INTIMATE_STYLE.search(' '.join([request.clothing, request.location, request.angle])))


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
    if 'бел' in low or 'white' in low:
        color = 'white'
    elif 'красн' in low or 'red' in low:
        color = 'burgundy red'
    elif 'розов' in low or 'pink' in low:
        color = 'soft pink'
    base = f'{color} elegant lingerie fashion set with opaque coverage and polished catalog styling'
    if 'чулк' in low or 'stocking' in low:
        base += ', with matching thigh-high stockings'
    return base


def parse_photo_request(text: str) -> Optional[PhotoRequest]:
    t = (text or '').strip()
    low = t.lower()
    direct = any(x in low for x in (
        'фото', 'фотку', 'селфи', 'покажись', 'покажи себя', 'сфоткай', 'фотограф', 'photo', 'selfie'
    ))
    if not direct:
        return None

    if SAFE_EXPLICIT.search(low):
        return PhotoRequest(scene='fashion', clothing='tasteful fitted evening fashion outfit with opaque fabric')

    scene = 'selfie'
    clothing = ''
    if INTIMATE_STYLE.search(low):
        scene = 'lingerie'
        clothing = _lingerie_clothing(low)
    elif any(x in low for x in ('парк', 'гуля', 'улиц')):
        scene = 'park'
    elif any(x in low for x in ('кафе', 'кофе', 'ресторан')):
        scene = 'cafe'
    elif any(x in low for x in ('зеркал', 'mirror')):
        scene = 'mirror'
    elif any(x in low for x in ('дома', 'домаш', 'кровать', 'диван', 'спальн')):
        scene = 'home'
    elif any(x in low for x in ('вечер', 'клуб')):
        scene = 'evening'
    elif any(x in low for x in ('личное фото', 'личный кадр', 'только для меня', 'специально для меня')):
        scene = 'personal'
    elif any(x in low for x in ('образ', 'наряд', 'одета', 'одежд', 'плать', 'джинс', 'леггинс')):
        scene = 'outfit'

    if not clothing:
        clothing_map = [
            ('черн', 'black outfit'), ('бел', 'white outfit'), ('красн', 'burgundy red outfit'),
            ('плать', 'fitted elegant dress'), ('джинс', 'jeans with a casual fitted top'),
            ('леггинс', 'leggings with a fitted casual top'), ('водолаз', 'fitted turtleneck sweater'),
            ('майк', 'fitted tank top'), ('топ', 'fitted fashion top'),
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
    elif any(x in low for x in ('распущ', 'волнист')):
        hairstyle = 'long loose softly wavy dark brunette hair'

    angle = ''
    if any(x in low for x in ('со спины', 'сзади', 'back view')):
        angle = 'back three-quarter view while keeping her recognizable profile when visible'
    elif any(x in low for x in ('сбоку', 'профиль', 'side')):
        angle = 'side three-quarter view'
    elif any(x in low for x in ('сверху', 'верхний ракурс')):
        angle = 'slightly high-angle smartphone selfie'
    elif 'полный рост' in low:
        angle = 'full-body framing'

    location = ''
    if 'диван' in low:
        location = 'a tidy modern living room with a sofa'
    elif 'спальн' in low:
        location = 'a tasteful modern bedroom with soft daylight'
    elif 'отел' in low:
        location = 'a tasteful modern hotel room'

    return PhotoRequest(scene=scene, clothing=clothing, hairstyle=hairstyle, location=location, angle=angle)


def _reference_folder(character: dict) -> Path:
    identity = character.get('visual_identity', {})
    return Path(__file__).resolve().parents[1] / identity.get('reference_folder', 'data/references/anna')


def _reference_path(character: dict, scene: str) -> Path:
    folder = _reference_folder(character)
    # Face-led scenes use the new face anchor; full-body scenes use the new fully-clothed body anchor.
    filename = '01_face_front_white_top.png' if scene in {'selfie', 'cafe', 'personal'} else '02_full_body_white_top.png'
    path = folder / filename
    if path.exists():
        return path
    for candidate in ('00_identity_face_new.png', '00_seedream_face_safe.png'):
        cp = folder / candidate
        if cp.exists():
            return cp
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


def _resolve_request(telegram_id: int, request: PhotoRequest) -> PhotoRequest:
    state = get_state(telegram_id)
    pool = OUTFIT_POOLS.get(request.scene, OUTFIT_POOLS['selfie'])
    clothing = request.clothing or _pick_nonrepeat(pool, state.outfit)
    hairstyle = request.hairstyle or _pick_nonrepeat(HAIRSTYLE_POOL, state.hairstyle)
    location = request.location or SCENES.get(request.scene, SCENES['selfie'])
    return replace(request, clothing=clothing, hairstyle=hairstyle, location=location)


def _shot_variant(scene: str, index: int, requested_angle: str = '') -> str:
    if requested_angle:
        return requested_angle
    variants = SHOT_VARIANTS.get(scene, SHOT_VARIANTS['selfie'])
    return variants[index % len(variants)]


def _build_prompt(request: PhotoRequest, shot_index: int, seedream: bool = False) -> str:
    scene = SCENES.get(request.scene, SCENES['selfie'])
    angle = _shot_variant(request.scene, shot_index, request.angle)
    personal = (
        'This should feel like a personal photo Anna has just taken herself specifically to send to someone she is chatting with. '
        'It must feel spontaneous and believable, not like a professional photographer is standing in front of her. '
        'Use a realistic smartphone-camera perspective and slightly imperfect real-life framing.'
    )
    bold = ''
    if seedream:
        bold = (
            'Use tasteful adult glamour/editorial styling. Keep it non-explicit: no nudity, no exposed nipples or genitals, '
            'and the lingerie garment must provide opaque coverage. Preserve identity above styling.'
        )
    return (
        f'{IDENTITY_LOCK}\n'
        f'SCENE: {scene}. {request.location}.\n'
        f'WARDROBE: {request.clothing}. Do not reuse the previous outfit if a different one is specified.\n'
        f'HAIRSTYLE: {request.hairstyle}.\n'
        f'SHOT {shot_index + 1}/{PHOTO_SET_SIZE}: {angle}.\n'
        f'MOOD: {request.mood}.\n'
        f'{personal}\n'
        'LIGHTING: soft natural window light where appropriate, realistic shadows, cinematic but believable contrast.\n'
        f'{bold}\n'
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


async def _seedream_request(prompt: str, image_urls: list[str], num_images: int = 1) -> dict:
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
    timeout = httpx.Timeout(float(FAL_TIMEOUT_SECONDS), connect=20.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.post(endpoint, headers=headers, json=payload)
    if response.status_code >= 400:
        body = response.text[:1600]
        logger.error('Seedream HTTP error status=%s body=%s', response.status_code, body)
        raise PhotoGenerationError('seedream45', f'HTTP {response.status_code}')
    try:
        return response.json()
    except Exception as exc:
        logger.error('Seedream returned non-JSON response: %s', response.text[:1200])
        raise PhotoGenerationError('seedream45', 'invalid_json') from exc


async def _run_openai_set(character: dict, telegram_id: int, request: PhotoRequest) -> list[GeneratedPhoto]:
    ref = _reference_path(character, request.scene)
    outputs=[]
    # Three independent edits give us controlled angle variation while preserving the same resolved outfit/hair.
    for i in range(PHOTO_SET_SIZE):
        prompt = _build_prompt(request, i, seedream=False)
        with ref.open('rb') as image_file:
            result = await openai_client.images.edit(
                model=IMAGE_MODEL,
                image=image_file,
                prompt=prompt,
                size=IMAGE_SIZE,
                quality=IMAGE_QUALITY,
                n=1,
            )
        outputs.extend(_extract_openai_many(result))
    return outputs[:PHOTO_SET_SIZE]


async def _run_seedream_set(character: dict, telegram_id: int, request: PhotoRequest) -> list[GeneratedPhoto]:
    ref = _seedream_reference_path(character)
    # One prompt requests a coherent 3-image mini-set. Fal returns multiple images in one response when available.
    prompt = _build_prompt(request, 0, seedream=True) + (
        f'\nGenerate {PHOTO_SET_SIZE} coherent but clearly different photos of the SAME moment: '
        'vary camera angle/framing between handheld selfie, mirror/self-timer style, and a wider personal portrait; '
        'keep the exact same outfit, hairstyle, location, face identity, and body proportions across the set.'
    )
    logger.info('Seedream set request user=%s scene=%s reference=%s count=%s', telegram_id, request.scene, ref.name, PHOTO_SET_SIZE)
    result = await _seedream_request(prompt, [_file_data_uri(ref)], PHOTO_SET_SIZE)
    images = result.get('images') if isinstance(result, dict) else None
    if not images:
        logger.error('Seedream response missing image URLs: %r', result)
        raise PhotoGenerationError('seedream45', 'no_image_url')
    out=[]
    for item in images[:PHOTO_SET_SIZE]:
        if isinstance(item, dict) and item.get('url'):
            out.append(GeneratedPhoto(url=item['url'], provider='seedream45', estimated_cost_usd=FAL_ESTIMATED_COST_USD))
    if not out:
        raise PhotoGenerationError('seedream45', 'no_image_url')
    # If provider returns fewer than requested, treat it as a valid partial set; quota still counts one request.
    return out


def choose_photo_provider(telegram_id: int, request: PhotoRequest) -> str:
    mode = PHOTO_ROUTER_MODE
    if mode in {'openai', 'gpt', 'gpt-image-2'}:
        return 'openai'
    if mode in {'fal', 'seedream', 'seedream45'}:
        return 'seedream45'

    # HYBRID: ordinary fully-clothed photos -> GPT Image 2; bold lingerie/boudoir -> Seedream.
    # This is content-based routing, not relationship-level routing.
    combined = ' '.join([request.scene, request.clothing, request.location, request.angle]).lower()
    if request.scene == 'lingerie' or INTIMATE_STYLE.search(combined):
        return 'seedream45'
    return 'openai'


async def generate_photo_set(telegram_id: int, request: PhotoRequest) -> tuple[list[GeneratedPhoto], PhotoRequest]:
    character = get_anna()
    resolved = _resolve_request(telegram_id, request)
    provider = choose_photo_provider(telegram_id, resolved)
    try:
        if provider == 'seedream45':
            return await _run_seedream_set(character, telegram_id, resolved), resolved
        return await _run_openai_set(character, telegram_id, resolved), resolved
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

    results, resolved = await generate_photo_set(telegram_id, request)
    caption = caption or random.choice(AUTO_CAPTIONS.get(request.scene, ('вот 😌',)))
    sent_messages=[]
    for idx, result in enumerate(results):
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

    # Quota/credit changes only after generated photos were actually sent.
    if delivery_type == 'credit':
        consume_photo_credit(telegram_id)
    first = sent_messages[0]
    first_result = results[0]
    file_id = first.photo[-1].file_id if first.photo else None
    total_cost = sum(x.estimated_cost_usd for x in results)
    _record(
        telegram_id, request.scene, delivery_type,
        file_id=file_id, url=first_result.url,
        provider=first_result.provider, estimated_cost_usd=total_cost,
    )
    update_state(
        telegram_id,
        location=resolved.location,
        outfit=resolved.clothing,
        hairstyle=resolved.hairstyle,
    )
    logger.info('photo set delivered user=%s scene=%s provider=%s count=%s outfit=%s hair=%s',
                telegram_id, request.scene, first_result.provider, len(results), resolved.clothing, resolved.hairstyle)
    return sent_messages
