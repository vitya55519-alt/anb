from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import os
import random
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from aiogram import Bot
from aiogram.types import BufferedInputFile
from openai import AsyncOpenAI, BadRequestError
from sqlalchemy import select

from config import (
    CHARACTER_ID,
    IMAGE_API_KEY, IMAGE_BASE_URL, IMAGE_MODEL, IMAGE_SIZE, IMAGE_QUALITY,
    FREE_PHOTOS_PER_DAY, PREMIUM_PHOTOS_PER_DAY, PHOTO_COST_STARS,
    FAL_KEY, FAL_MODEL, FAL_IMAGE_SIZE, FAL_TIMEOUT_SECONDS, FAL_ESTIMATED_COST_USD,
    PHOTO_ROUTER_MODE, SEEDREAM_RELATIONSHIP_LEVEL,
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
    'selfie': 'natural smartphone selfie in an ordinary everyday setting',
    'home': 'relaxed realistic smartphone photo at home',
    'park': 'natural photo during a walk in a green city park',
    'cafe': 'natural smartphone photo in a cozy cafe',
    'mirror': 'realistic full-body mirror photo in a tidy apartment',
    'outfit': 'full-body smartphone photo focused on the outfit',
    'evening': 'stylish evening portrait in a tasteful outfit',
    'fashion': 'mainstream fashion-catalog portrait in tasteful everyday or evening clothing',
    'lingerie': 'tasteful private fashion-editorial photo in a refined indoor setting',
}

# Relationship progression controls access. Stars never buy a higher relationship level.
SCENE_LEVELS = {
    'selfie': 1, 'home': 1, 'park': 1, 'cafe': 1, 'outfit': 1,
    'mirror': 2, 'evening': 2, 'fashion': 3, 'lingerie': 5,
}
STAGE_INDEX = {
    'stranger': 0,
    'acquaintance': 1,
    'close': 2,
    'intimate': 3,
    'deeply_connected': 4,
    'committed': 5,
}

AUTO_CAPTIONS = {
    'selfie': ('ладно, держи 😌', 'вот такая я сейчас', 'ну всё, поймала нормальный свет 😂'),
    'home': ('я сегодня максимально домашняя 😌', 'вот мой режим на сегодня', 'никуда сегодня не тороплюсь'),
    'park': ('вышла немного пройтись 🌿', 'смотри какой свет поймала', 'вот, пока гуляю'),
    'cafe': ('кофе спасает ☕', 'я тут зависла с кофе', 'моё место на ближайшие полчаса'),
    'mirror': ('зеркало сегодня не подвело 😏', 'ну вот, целиком', 'поймала себя в зеркале'),
    'outfit': ('ты же хотел посмотреть образ 😌', 'вот что выбрала', 'сегодня вот так'),
    'evening': ('сегодня решила выглядеть вот так ✨', 'вечерний вариант', 'мне самой этот образ нравится'),
    'fashion': ('сегодня настроение на красивый кадр', 'немного журнального вайба 😌'),
    'lingerie': ('ладно… этот образ покажу 😏', 'сегодня чуть смелее обычного', 'вот такой приватный fashion-настрой'),
}

SAFE_EXPLICIT = re.compile(
    r'\b(голая|голый|обнаж|без трус|без бель|соски|генитал|вагин|пенис|nude|naked|topless|explicit)\b', re.I
)
INTIMATE_STYLE = re.compile(r'\b(бель|lingerie|будуар|чулк|stocking|garter|bra\b|bralette)\b', re.I)


@dataclass(frozen=True)
class GeneratedPhoto:
    url: Optional[str] = None
    data: Optional[bytes] = None
    used_static_fallback: bool = False
    provider: str = 'openai'
    estimated_cost_usd: float = 0.0
    failure_reason: str = ''


@dataclass(frozen=True)
class PhotoRequest:
    scene: str = 'selfie'
    clothing: str = ''
    hairstyle: str = ''
    location: str = ''
    angle: str = ''
    mood: str = 'warm, natural'


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
    return PREMIUM_PHOTOS_PER_DAY if is_premium(telegram_id) else FREE_PHOTOS_PER_DAY


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
    return request.scene == 'lingerie' or bool(INTIMATE_STYLE.search(request.clothing or ''))


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
        color = 'red'
    elif 'розов' in low or 'pink' in low:
        color = 'soft pink'
    base = f'{color} elegant lingerie fashion set with opaque fabric and polished catalog styling'
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

    # Explicit requests are normalized to a safe mainstream fashion request.
    if SAFE_EXPLICIT.search(low):
        return PhotoRequest(scene='fashion', clothing='tasteful fitted evening fashion outfit with opaque fabric')

    scene = 'selfie'
    clothing = ''
    if any(x in low for x in ('парк', 'гуля', 'улиц')):
        scene = 'park'
    elif any(x in low for x in ('кафе', 'кофе', 'ресторан')):
        scene = 'cafe'
    elif any(x in low for x in ('зеркал', 'mirror')):
        scene = 'mirror'
    elif any(x in low for x in ('дома', 'домаш', 'кровать', 'диван', 'спальн')):
        scene = 'home'
    elif any(x in low for x in ('вечер', 'клуб')):
        scene = 'evening'
    elif INTIMATE_STYLE.search(low):
        scene = 'lingerie'
        clothing = _lingerie_clothing(low)
    elif any(x in low for x in ('образ', 'наряд', 'одета', 'одежд', 'плать', 'джинс', 'леггинс')):
        scene = 'outfit'

    if not clothing:
        clothing_map = [
            ('черн', 'black outfit'), ('бел', 'white outfit'), ('красн', 'red outfit'),
            ('плать', 'fitted elegant dress'), ('джинс', 'jeans with a casual top'),
            ('леггинс', 'leggings with a fitted casual top'), ('майк', 'fitted tank top'),
            ('топ', 'fitted fashion top'),
        ]
        for key, value in clothing_map:
            if key in low:
                clothing = value

    hairstyle = ''
    if any(x in low for x in ('хвост', 'ponytail')):
        hairstyle = 'high ponytail'
    elif any(x in low for x in ('пучок', 'bun')):
        hairstyle = 'neat bun'
    elif any(x in low for x in ('распущ', 'волнист')):
        hairstyle = 'long loose softly wavy hair'

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
        location = 'sitting naturally on a modern sofa in a tidy apartment'
    elif 'спальн' in low:
        location = 'tasteful modern bedroom with soft daylight'
    elif 'отел' in low:
        location = 'tasteful modern hotel room'

    return PhotoRequest(scene=scene, clothing=clothing, hairstyle=hairstyle, location=location, angle=angle)


def _reference_folder(character: dict) -> Path:
    identity = character.get('visual_identity', {})
    return Path(__file__).resolve().parents[1] / identity.get('reference_folder', 'data/references/anna')


def _reference_path(character: dict, scene: str) -> Path:
    identity = character.get('visual_identity', {})
    folder = _reference_folder(character)
    pref = {
        'selfie': '01_face_front_white_top.png',
        'cafe': '01_face_front_white_top.png',
        'park': '02_full_body_white_top.png',
        'home': '04_lying_hair_down.png',
        'evening': '02_full_body_white_top.png',
        'mirror': '02_full_body_white_top.png',
        'outfit': '02_full_body_white_top.png',
        'fashion': '02_full_body_white_top.png',
        # Seedream edits a fully clothed anchor; the requested outfit is described in text.
        'lingerie': '02_full_body_white_top.png',
    }
    path = folder / pref.get(scene, '01_face_front_white_top.png')
    if not path.exists():
        refs = [folder / x for x in identity.get('reference_assets', []) if (folder / x).exists()]
        if not refs:
            raise FileNotFoundError('У Анны нет доступных reference-фото')
        path = refs[0]
    return path


def _prompt(character: dict, request: PhotoRequest, telegram_id: int) -> str:
    state = get_state(telegram_id)
    scene = SCENES.get(request.scene, SCENES['selfie'])
    state_outfit = state.outfit or ''
    if SAFE_EXPLICIT.search(state_outfit) or INTIMATE_STYLE.search(state_outfit):
        state_outfit = ''
    clothing = request.clothing or state_outfit or 'natural stylish everyday outfit'
    hairstyle = request.hairstyle or state.hairstyle or 'keep the hairstyle from the reference unless the request changes it'
    location = request.location or state.location or scene
    angle = request.angle or 'natural flattering camera angle appropriate for the scene'
    return f'''Edit the supplied reference into a NEW photorealistic photo of the SAME fictional adult woman, {character['name']}, age {character['age']}.
Identity consistency is the top priority. Preserve her recognizable face, eye shape and spacing, nose, lips, jawline, skin tone, hair color and stable body proportions. Do not substitute a different person or change her age.
Requested hairstyle: {hairstyle}.
Requested clothing: {clothing}.
Requested location/scene: {location}.
Camera/framing: {angle}.
Mood: {request.mood}.
The result should look like a high-quality natural smartphone or fashion-catalog photograph with realistic skin texture, hands and anatomy. Clothing, hairstyle, location, pose and camera angle may change; identity and body proportions remain consistent.'''


def _seedream_prompt(character: dict, request: PhotoRequest, telegram_id: int) -> str:
    base = _prompt(character, request, telegram_id)
    return base + (
        "\nThis is a tasteful adult fashion editorial. Keep the clothing opaque and complete, with polished mainstream catalog styling. "
        "Keep the composition elegant and non-explicit."
    )


def _extract_openai(result) -> GeneratedPhoto:
    item = result.data[0]
    url = getattr(item, 'url', None)
    raw = getattr(item, 'b64_json', None)
    if url:
        return GeneratedPhoto(url=url, provider='openai')
    if raw:
        return GeneratedPhoto(data=base64.b64decode(raw), provider='openai')
    raise RuntimeError('Image API returned no image')


def _safe_reference_result(character: dict, reason: str = '') -> GeneratedPhoto:
    ref = _reference_path(character, 'outfit')
    return GeneratedPhoto(data=ref.read_bytes(), used_static_fallback=True, provider='static', failure_reason=reason)


def _file_data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or 'image/png'
    encoded = base64.b64encode(path.read_bytes()).decode('ascii')
    return f'data:{mime};base64,{encoded}'


def _seedream_sync(prompt: str, image_urls: list[str]):
    if not FAL_KEY:
        raise RuntimeError('FAL_KEY is not configured')
    os.environ['FAL_KEY'] = FAL_KEY
    import fal_client  # lazy import so local smoke tests do not require the package
    return fal_client.subscribe(
        FAL_MODEL,
        arguments={
            'prompt': prompt,
            'image_urls': image_urls,
            'image_size': FAL_IMAGE_SIZE,
            'num_images': 1,
            'max_images': 1,
            'enable_safety_checker': True,
        },
    )


async def _run_openai(character: dict, telegram_id: int, request: PhotoRequest) -> GeneratedPhoto:
    ref = _reference_path(character, request.scene)
    prompt = _prompt(character, request, telegram_id)
    with ref.open('rb') as image_file:
        result = await openai_client.images.edit(
            model=IMAGE_MODEL,
            image=image_file,
            prompt=prompt,
            size=IMAGE_SIZE,
            quality=IMAGE_QUALITY,
            n=1,
        )
    out = _extract_openai(result)
    return GeneratedPhoto(url=out.url, data=out.data, provider='openai', estimated_cost_usd=0.0)


async def _run_seedream(character: dict, telegram_id: int, request: PhotoRequest) -> GeneratedPhoto:
    ref = _reference_path(character, request.scene)
    prompt = _seedream_prompt(character, request, telegram_id)
    image_urls = [_file_data_uri(ref)]
    result = await asyncio.wait_for(
        asyncio.to_thread(_seedream_sync, prompt, image_urls),
        timeout=FAL_TIMEOUT_SECONDS,
    )
    images = result.get('images') if isinstance(result, dict) else None
    if not images or not images[0].get('url'):
        raise RuntimeError('Seedream returned no image URL')
    return GeneratedPhoto(
        url=images[0]['url'],
        provider='seedream45',
        estimated_cost_usd=FAL_ESTIMATED_COST_USD,
    )


def choose_photo_provider(telegram_id: int, request: PhotoRequest) -> str:
    mode = PHOTO_ROUTER_MODE
    if mode in {'openai', 'gpt', 'gpt-image-2'}:
        return 'openai'
    if mode in {'fal', 'seedream', 'seedream45'}:
        return 'seedream45'
    level = get_relationship_level(telegram_id)
    intimate_request = request.scene == 'lingerie' or bool(INTIMATE_STYLE.search(request.clothing or ''))
    if level >= SEEDREAM_RELATIONSHIP_LEVEL and intimate_request:
        return 'seedream45'
    return 'openai'


async def generate_photo(telegram_id: int, request: PhotoRequest) -> GeneratedPhoto:
    character = get_anna()
    provider = choose_photo_provider(telegram_id, request)
    try:
        if provider == 'seedream45':
            return await _run_seedream(character, telegram_id, request)
        return await _run_openai(character, telegram_id, request)
    except BadRequestError as exc:
        body = getattr(exc, 'body', None) or {}
        err = body.get('error', body) if isinstance(body, dict) else {}
        code = err.get('code') if isinstance(err, dict) else None
        msg = str(err.get('message', '')) if isinstance(err, dict) else str(exc)
        if code != 'moderation_blocked' and 'safety' not in msg.lower() and 'moderation' not in msg.lower():
            raise
        logger.warning('OpenAI image blocked by safety; static fallback user=%s scene=%s', telegram_id, request.scene)
        return _safe_reference_result(character, 'openai_safety')
    except Exception as exc:
        if provider != 'seedream45':
            raise
        # Do not loop across providers for a sensitive edit. Keep costs and behavior predictable.
        logger.exception('Seedream photo failed; static fallback user=%s scene=%s', telegram_id, request.scene)
        return _safe_reference_result(character, f'seedream_error:{type(exc).__name__}')


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

    result = await generate_photo(telegram_id, request)
    if result.used_static_fallback:
        caption = caption or 'этот кадр не прошёл генерацию, поэтому без экспериментов 😌'
    else:
        caption = caption or random.choice(AUTO_CAPTIONS.get(request.scene, ('вот 😌',)))

    if result.url:
        sent = await bot.send_photo(chat_id, result.url, caption=caption)
    else:
        sent = await bot.send_photo(
            chat_id,
            BufferedInputFile(result.data, filename=f'anna_{request.scene}.png'),
            caption=caption,
        )

    # A blocked/failed generation never consumes quota or paid credit and does not corrupt visual continuity.
    if not result.used_static_fallback:
        if delivery_type == 'credit':
            consume_photo_credit(telegram_id)
        file_id = sent.photo[-1].file_id if sent.photo else None
        _record(
            telegram_id, request.scene, delivery_type,
            file_id=file_id, url=result.url,
            provider=result.provider, estimated_cost_usd=result.estimated_cost_usd,
        )
        update_state(
            telegram_id,
            location=request.location or SCENES.get(request.scene),
            outfit=request.clothing or None,
            hairstyle=request.hairstyle or None,
        )
    return sent
