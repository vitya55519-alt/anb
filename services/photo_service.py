from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, date
import random
from pathlib import Path
from typing import Optional

from aiogram import Bot
from aiogram.types import BufferedInputFile
from openai import AsyncOpenAI
from sqlalchemy import select

from config import (
    CHARACTER_ID,
    IMAGE_API_KEY,
    IMAGE_BASE_URL,
    IMAGE_MODEL,
    IMAGE_REFERENCE_MODE,
    PHOTO_COST_STARS,
    PHOTO_DAILY_LIMITS,
)
from models.app_models import User
from models.relationship_models import UserCharacterRelationship
from models.photo_models import PhotoDailyUsage, PhotoDelivery, PhotoOffer
from services.db import SessionLocal
from services.character_service import get_anna
from services.test_mode import get_stage as get_test_stage

logger = logging.getLogger(__name__)
client = AsyncOpenAI(api_key=IMAGE_API_KEY, base_url=IMAGE_BASE_URL)

SCENES = {
    "selfie": "natural smartphone selfie in an ordinary everyday setting",
    "cafe": "natural smartphone photo in a cozy cafe with coffee",
    "park": "natural smartphone photo during a walk in a green city park",
    "home": "casual smartphone photo at home during a relaxed evening",
    "evening": "stylish evening smartphone photo in a tasteful adult outfit",
    "mirror": "natural full-body mirror photo in a tidy apartment",
    "outfit": "natural smartphone photo showing a casual everyday outfit",
    "personal": "warm personal smartphone photo with a close, affectionate atmosphere, fully clothed",
    "lingerie": "tasteful adult lingerie fashion portrait, fully non-explicit and with no nudity",
    "lingerie_bed": "tasteful adult lingerie photo sitting on a bed, fully non-explicit and no nudity",
    "lingerie_mirror": "tasteful adult lingerie mirror photo, fully non-explicit and no nudity",
    "lingerie_red": "tasteful adult red lingerie portrait at home, fully non-explicit and no nudity",
}

SCENE_LEVELS = {
    "selfie": 1,
    "cafe": 1,
    "park": 1,
    "home": 1,
    "outfit": 1,
    "evening": 2,
    "mirror": 2,
    "personal": 3,
    "lingerie": 4,
    "lingerie_bed": 5,
    "lingerie_mirror": 5,
    "lingerie_red": 6,
}

STAGE_INDEX = {
    "stranger": 0,
    "acquaintance": 1,
    "close": 2,
    "intimate": 3,
    "deeply_connected": 4,
    "committed": 5,
}

TRIGGERS = {
    "cafe": ("кафе", "кофе", "ресторан", "кофей", "сижу пью"),
    "park": ("парк", "прогул", "гуля", "на улице"),
    "outfit": ("что на тебе", "как одета", "во что одета", "наряд", "во что ты одета"),
    "selfie": ("покажись", "фото", "селфи", "покажи себя", "пришли фотку", "скинь фотку"),
    "home": ("дома", "дома сейчас", "отдыхаешь", "лежишь", "что делаешь"),
    "evening": ("вечер", "вечером", "собираешься", "куда-нибудь вечером"),
}

AUTO_CAPTIONS = {
    "selfie": ("Вот, поймала себя на камеру 🙈", "Ну ладно, держи мою фотку 😊", "Вот такая я сегодня."),
    "cafe": ("Я как раз сижу с кофе ☕", "Вот где я сегодня зависла немного ☕", "Кофе был слишком хорош, чтобы не показать тебе."),
    "park": ("Я сейчас немного гуляю 🌿", "Вот где я сегодня хожу.", "Вышла пройтись и поймала нормальный свет 🌿"),
    "home": ("Я сейчас дома, валяюсь немного 😌", "Вот мой сегодняшний домашний вид.", "Ничего особенного, просто я дома."),
    "outfit": ("Ты же спрашивал, как я одета 🙂", "Вот сегодняшний наряд.", "Ладно, покажусь целиком 😌"),
    "evening": ("Собираюсь на вечер, вот так сегодня выгляжу.", "Покажу тебе сегодняшний вечерний образ ✨", "Вот такая я сегодня вечером."),
    "mirror": ("Поймала себя в зеркале.", "Вот нормальный кадр в полный рост 😌", "Зеркало сегодня было на моей стороне."),
    "personal": ("Эту оставлю тебе одну 💗", "Ладно… эту фотку только тебе.", "Вот, немного более личная версия меня."),
    "lingerie": ("Ладно, сегодня я немного смелее 😏", "Вот так я сегодня решила себя показать.", "Ну всё, уговорил 🙈"),
    "lingerie_bed": ("Я тут немного расслабилась…", "Кажется, я сегодня слишком довольна собой 😏"),
    "lingerie_mirror": ("Поймала себя в зеркале.", "Вот такой сегодня домашний образ."),
    "lingerie_red": ("Сегодня почему-то выбрала красное ❤️", "Ладно, этот образ мне самой нравится."),
}


@dataclass(frozen=True)
class GeneratedPhoto:
    url: Optional[str] = None
    data: Optional[bytes] = None


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _user_and_relationship(session, telegram_id: int):
    user = session.scalar(select(User).where(User.telegram_id == str(telegram_id)))
    if not user:
        return None, None
    rel = session.scalar(select(UserCharacterRelationship).where(
        UserCharacterRelationship.user_id == user.id,
        UserCharacterRelationship.character_id == CHARACTER_ID,
    ))
    return user, rel


def ensure_user(telegram_id: int, name: str | None = None) -> int:
    with SessionLocal() as s:
        user, _ = _user_and_relationship(s, telegram_id)
        if not user:
            user = User(telegram_id=str(telegram_id), name=name)
            s.add(user)
            s.flush()
        elif name:
            user.name = name
        s.commit()
        return user.id


def get_relationship_stage(telegram_id: int) -> str:
    override = get_test_stage(telegram_id)
    if override:
        return override
    with SessionLocal() as s:
        _, rel = _user_and_relationship(s, telegram_id)
        return rel.stage if rel else "stranger"


def get_daily_limit(telegram_id: int) -> int:
    stage = get_relationship_stage(telegram_id)
    idx = STAGE_INDEX.get(stage, 0)
    return PHOTO_DAILY_LIMITS[min(idx, len(PHOTO_DAILY_LIMITS) - 1)]


def get_usage(telegram_id: int) -> tuple[int, int, int]:
    ensure_user(telegram_id)
    with SessionLocal() as s:
        user, _ = _user_and_relationship(s, telegram_id)
        row = s.scalar(select(PhotoDailyUsage).where(
            PhotoDailyUsage.user_id == user.id,
            PhotoDailyUsage.character_id == CHARACTER_ID,
            PhotoDailyUsage.usage_date == _today(),
        ))
        limit = get_daily_limit(telegram_id)
        if not row:
            return 0, 0, limit
        return row.free_used, row.paid_used, limit


def has_free_photo(telegram_id: int) -> bool:
    free_used, _, limit = get_usage(telegram_id)
    return free_used < limit


def free_photos_left(telegram_id: int) -> int:
    used, _, limit = get_usage(telegram_id)
    return max(0, limit - used)


def scene_allowed_for_stage(scene: str, stage: str) -> bool:
    required = SCENE_LEVELS.get(scene)
    if required is None:
        return False
    return STAGE_INDEX.get(stage, 0) + 1 >= required


def build_photo_menu(telegram_id: int) -> dict:
    stage = get_relationship_stage(telegram_id)
    free_used, paid_used, limit = get_usage(telegram_id)
    return {
        "stage": stage,
        "free_used": free_used,
        "paid_used": paid_used,
        "limit": limit,
        "free_left": max(0, limit - free_used),
        "cost": PHOTO_COST_STARS,
    }


def suggest_scene_from_text(text: str) -> Optional[str]:
    lowered = (text or "").lower()
    for scene, words in TRIGGERS.items():
        if any(word in lowered for word in words):
            return scene
    return None


def create_offer(telegram_id: int, scene: str, ttl_minutes: int = 30) -> Optional[int]:
    if scene not in SCENE_LEVELS:
        return None
    ensure_user(telegram_id)
    with SessionLocal() as s:
        user, _ = _user_and_relationship(s, telegram_id)
        offer = PhotoOffer(
            user_id=user.id,
            character_id=CHARACTER_ID,
            scene=scene,
            created_at=_now(),
            expires_at=_now() + timedelta(minutes=ttl_minutes),
        )
        s.add(offer)
        s.commit()
        return offer.id


def consume_offer(telegram_id: int, offer_id: int) -> Optional[str]:
    ensure_user(telegram_id)
    with SessionLocal() as s:
        user, _ = _user_and_relationship(s, telegram_id)
        offer = s.scalar(select(PhotoOffer).where(
            PhotoOffer.id == offer_id,
            PhotoOffer.user_id == user.id,
            PhotoOffer.character_id == CHARACTER_ID,
        ))
        if not offer or offer.consumed or offer.expires_at < _now():
            return None
        offer.consumed = True
        s.commit()
        return offer.scene


def _reference_path(character: dict, scene: str) -> Optional[Path]:
    """Pick the reference that best matches the requested framing.

    The face reference is used for close/ordinary shots; full-body references are
    used for mirror/outfit shots. This is more stable than always feeding the API
    the first image in the folder.
    """
    identity = character.get("visual_identity", {})
    refs = identity.get("reference_assets", [])
    folder = Path(__file__).resolve().parents[1] / identity.get("reference_folder", "")
    preferred_by_scene = {
        "selfie": "01_face_front_white_top.png",
        "cafe": "01_face_front_white_top.png",
        "park": "01_face_front_white_top.png",
        "home": "04_lying_hair_down.png",
        "evening": "01_face_front_white_top.png",
        "mirror": "02_full_body_white_top.png",
        "outfit": "02_full_body_white_top.png",
        "personal": "05_lying_hair_up.png",
        "lingerie": "06_front_black_lingerie.jpg",
        "lingerie_bed": "05_lying_hair_up.png",
        "lingerie_mirror": "06_front_black_lingerie.jpg",
        "lingerie_red": "06_front_black_lingerie.jpg",
    }
    preferred = preferred_by_scene.get(scene)
    if preferred in refs and (folder / preferred).exists():
        return folder / preferred
    preferred = next((x for x in refs if "face" in x.lower()), refs[0] if refs else None)
    if not preferred:
        return None
    path = folder / preferred
    return path if path.exists() else None


def _extract_result(result) -> GeneratedPhoto:
    item = result.data[0]
    url = getattr(item, "url", None)
    if url:
        return GeneratedPhoto(url=url)
    raw = getattr(item, "b64_json", None)
    if raw:
        return GeneratedPhoto(data=base64.b64decode(raw))
    raise RuntimeError("Image API returned neither url nor b64_json")


async def _generate_with_reference(character: dict, scene: str, clothing: str, mood: str) -> GeneratedPhoto:
    ref_path = _reference_path(character, scene)
    if not ref_path:
        raise FileNotFoundError("No character reference image configured")

    identity = character.get("visual_identity", {})
    preserve = ", ".join(identity.get("preserve_identity", []))
    prompt = (
        f"Create a new realistic smartphone photo of the SAME fictional adult woman "
        f"({character['name']}, age {character['age']}) shown in the reference. "
        "IDENTITY LOCK IS THE HIGHEST PRIORITY. Preserve the same recognizable adult face: "
        "same eye shape and spacing, brow shape, nose bridge and tip, lip shape, jawline, "
        "cheek structure, facial width, hair color, hairline and parting. Preserve the same "
        "body identity and proportions: shoulder width, torso-to-hip ratio, waist shape, leg "
        "length, bust/hip silhouette and overall build. Do not redesign, beautify, slim, enlarge, "
        "age or otherwise alter her. The character must look like the same woman photographed "
        "on another day. Change only scene, pose, clothing, lighting and camera framing. "
        f"Scene: {SCENES.get(scene, SCENES['selfie'])}. Clothing: {clothing}. Mood: {mood}. "
        "Natural phone-camera optics, realistic skin texture, subtle asymmetry, believable hands, "
        "no studio glamour retouching. No minors, no nudity, no explicit sexual activity."
    )
    with ref_path.open("rb") as image_file:
        result = await client.images.edit(
            model=IMAGE_MODEL,
            image=image_file,
            prompt=prompt,
            size="1024x1024",
        )
    return _extract_result(result)


async def _generate_from_prompt(character: dict, scene: str, clothing: str, mood: str) -> GeneratedPhoto:
    identity = character.get("visual_identity", {})
    preserve = ", ".join(identity.get("preserve_identity", []))
    prompt = (
        f"Create a fictional adult woman named {character['name']}, age {character['age']}. "
        f"Identity traits that must remain consistent: {preserve}. "
        "She has long brown hair and a stable recognizable adult face and body silhouette across every image. "
        "Do not invent a different woman. Keep facial proportions and body proportions stable. "
        f"Scene: {SCENES.get(scene, SCENES['selfie'])}. Clothing: {clothing}. Mood: {mood}. "
        "Realistic imperfect smartphone photography, natural anatomy, natural expression, "
        "same character every time. No minors, no nudity, no explicit sexual activity."
    )
    result = await client.images.generate(
        model=IMAGE_MODEL,
        prompt=prompt,
        size="1024x1024",
        n=1,
    )
    return _extract_result(result)


async def generate_photo(scene: str = "selfie", clothing: str = "casual", mood: str = "warm") -> GeneratedPhoto:
    if scene not in SCENES:
        raise ValueError(f"Unknown photo scene: {scene}")
    if clothing == "casual" and scene.startswith("lingerie"):
        clothing = "elegant adult lingerie, fully non-explicit"
    character = get_anna()
    use_reference = IMAGE_REFERENCE_MODE in {"auto", "edit"} and IMAGE_MODEL.startswith("gpt-image")
    if use_reference:
        try:
            return await _generate_with_reference(character, scene, clothing, mood)
        except Exception:
            logger.exception("Reference image generation failed for scene=%s", scene)
            if IMAGE_REFERENCE_MODE == "edit":
                raise
    return await _generate_from_prompt(character, scene, clothing, mood)


def _record_delivery(telegram_id: int, scene: str, delivery_type: str, telegram_file_id: Optional[str], image_url: Optional[str]):
    ensure_user(telegram_id)
    with SessionLocal() as s:
        user, _ = _user_and_relationship(s, telegram_id)
        usage = s.scalar(select(PhotoDailyUsage).where(
            PhotoDailyUsage.user_id == user.id,
            PhotoDailyUsage.character_id == CHARACTER_ID,
            PhotoDailyUsage.usage_date == _today(),
        ))
        if not usage:
            usage = PhotoDailyUsage(
                user_id=user.id,
                character_id=CHARACTER_ID,
                usage_date=_today(),
            )
            s.add(usage)
            s.flush()
        if delivery_type == "free":
            usage.free_used += 1
        elif delivery_type == "paid":
            usage.paid_used += 1
        s.add(PhotoDelivery(
            user_id=user.id,
            character_id=CHARACTER_ID,
            scene=scene,
            delivery_type=delivery_type,
            telegram_file_id=telegram_file_id,
            image_url=image_url,
        ))
        s.commit()


async def deliver_photo(
    bot: Bot,
    chat_id: int,
    telegram_id: int,
    scene: str,
    delivery_type: str = "free",
    caption: str | None = None,
):
    """Generate, send and persist one photo. Free deliveries consume the daily quota."""
    stage = get_relationship_stage(telegram_id)
    if not scene_allowed_for_stage(scene, stage):
        raise PermissionError("Scene is locked for current relationship stage")
    if delivery_type == "free" and not has_free_photo(telegram_id):
        raise PermissionError("Daily free photo quota exhausted")

    result = await generate_photo(scene=scene)
    sent = None
    caption = caption or random.choice(AUTO_CAPTIONS.get(scene, ("Вот 😊",)))
    if result.url:
        sent = await bot.send_photo(chat_id, result.url, caption=caption)
    elif result.data:
        sent = await bot.send_photo(chat_id, BufferedInputFile(result.data, filename=f"anna_{scene}.png"), caption=caption)
    else:
        raise RuntimeError("Generated photo is empty")

    file_id = sent.photo[-1].file_id if sent.photo else None
    _record_delivery(telegram_id, scene, delivery_type, file_id, result.url)
    return sent


def auto_photo_scene(text: str) -> Optional[str]:
    """Return a scene only when the user's message naturally gives Anna a photo moment."""
    return suggest_scene_from_text(text)


def should_auto_send_photo(telegram_id: int, text: str) -> bool:
    """Small chance-based behavior prevents Anna from turning every message into a photo menu."""
    if not has_free_photo(telegram_id):
        return False
    scene = auto_photo_scene(text)
    if not scene:
        return False
    # Direct requests are always fulfilled; contextual mentions are occasional.
    lowered = (text or "").lower()
    direct = any(x in lowered for x in ("фото", "фотку", "селфи", "покажись", "покажи себя", "скинь"))
    return direct or random.random() < 0.30


async def maybe_send_contextual_photo(
    bot: Bot, chat_id: int, telegram_id: int, user_text: str, *, delivery_type: str = "free"
):
    scene = auto_photo_scene(user_text)
    if not scene or not scene_allowed_for_stage(scene, get_relationship_stage(telegram_id)):
        return False
    if not should_auto_send_photo(telegram_id, user_text):
        return False
    try:
        await bot.send_chat_action(chat_id, "upload_photo")
        await deliver_photo(
            bot, chat_id, telegram_id, scene, delivery_type,
            caption=random.choice(AUTO_CAPTIONS.get(scene, ("Вот 😊",))),
        )
        return True
    except Exception:
        logger.exception("contextual photo delivery failed for user=%s scene=%s", telegram_id, scene)
        return False
