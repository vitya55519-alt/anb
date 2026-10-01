"""
V3.45.0 — Фото «наедине» и «Косплей» — монетизация через персики.

Отдельная категория фото, доступная на ЛЮБОМ уровне отношений за персики.
Не заменяет бесплатную прогрессию по уровням — дополняет её.

Категории:
- 💋 Фото наедине: бельё, арт-нюдо, ролевые сцены, пикантная одежда
- 🎭 Косплей: 25 образов из игр/аниме/поп-культуры

Цены:
- 2 бесплатных фото/день (1 наедине + 1 косплей)
- После лимита: 2 персика за фото
- Hot Pass: 5/25/80 персиков (день/неделя/месяц) — безлимит
"""

import logging
import hashlib
import json
import uuid
import asyncio
import aiohttp
from datetime import datetime, timedelta, date
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, asdict
from sqlalchemy import select, func
from services.db import SessionLocal
from models.app_models import User, PrivateGallery
from services.user_service import ensure_user
from config import (
    PRIVATE_PHOTO_FREE_DAILY,
    COSPLAY_PHOTO_FREE_DAILY,
    PRIVATE_PHOTO_PEACH_COST,
    COSPLAY_PHOTO_PEACH_COST,
    HOT_PASS_DAY_PEACHES,
    HOT_PASS_WEEK_PEACHES,
    HOT_PASS_MONTH_PEACHES,
    SPICYAPI_KEY,
    SPICYAPI_BASE_URL,
    SPICYAPI_IMAGE_MODEL,
    SPICYAPI_IMAGE_TIMEOUT,
    CHARACTER_ID,
)

logger = logging.getLogger(__name__)


# ─── Категории и типы фото ─────────────────────────────────────────────────────

# Фото «наедине» — 4 категории
PRIVATE_PHOTO_CATEGORIES = {
    "lingerie": {
        "name_ru": "🩲 В белье",
        "name_en": "🩲 Lingerie",
        "types": [
            {"id": "lace", "name_ru": "Кружевной комплект", "name_en": "Lace set"},
            {"id": "silk", "name_ru": "🤍 Шёлковый комплект", "name_en": "🤍 Silk set"},
            {"id": "corset", "name_ru": "❤️ Корсет + чулки", "name_en": "❤️ Corset + stockings"},
            {"id": "bodysuit", "name_ru": "🩱 Боди", "name_en": "🩱 Bodysuit"},
            {"id": "stockings", "name_ru": "🧦 Чулки + подвязки", "name_en": "🧦 Stockings + garters"},
            {"id": "braziliana", "name_ru": "🩳 Бразилиана", "name_en": "🩳 Brazilian"},
            {"id": "bows", "name_ru": "Бельё с бантиками", "name_en": "Lingerie with bows"},
            {"id": "fishnet", "name_ru": "🕸️ Бельё-сетка", "name_en": "🕸️ Fishnet lingerie"},
        ]
    },
    "nude_art": {
        "name_ru": "🎨 Арт-нюдо",
        "name_en": "🎨 Art nude",
        "types": [
            {"id": "sunset", "name_ru": "🌅 Силуэт на закате", "name_en": "🌅 Sunset silhouette"},
            {"id": "shower", "name_ru": "🚿 Под душем", "name_en": "🚿 In shower"},
            {"id": "bath", "name_ru": "🛁 В ванной", "name_en": "🛁 In bath"},
            {"id": "mirror", "name_ru": "🪞 Отражение в зеркале", "name_en": "🪞 Mirror reflection"},
            {"id": "moonlight", "name_ru": "🌙 Лунный свет", "name_en": "🌙 Moonlight"},
            {"id": "underwater", "name_ru": "Под водой", "name_en": "Underwater"},
            {"id": "artistic", "name_ru": "🎨 Художественное нюдо", "name_en": "🎨 Artistic nude"},
            {"id": "garden", "name_ru": "🌿 В саду", "name_en": "🌿 In garden"},
            {"id": "cave", "name_ru": "🌋 В пещере", "name_en": "🌋 In cave"},
            {"id": "marble", "name_ru": "🏛️ Античная статуя", "name_en": "🏛️ Marble statue"},
            {"id": "studio", "name_ru": "🎨 Среди картин", "name_en": "🎨 In studio"},
            {"id": "field", "name_ru": "🌾 В поле", "name_en": "🌾 In field"},
            {"id": "snow", "name_ru": "❄️ В снегу", "name_en": "❄️ In snow"},
            {"id": "petals", "name_ru": "🪷 Ванна с лепестками", "name_en": "🪷 Bath with petals"},
            {"id": "space", "name_ru": "🌌 Космос", "name_en": "🌌 Space"},
            {"id": "cliff", "name_ru": "🏔️ На скале", "name_en": "🏔️ On cliff"},
            {"id": "backstage", "name_ru": "🎪 За кулисами", "name_en": "🎪 Backstage"},
            {"id": "fabric", "name_ru": "🤍 На белом", "name_en": "🤍 On white"},
        ]
    },
    "roleplay": {
        "name_ru": "🎭 Ролевая сцена",
        "name_en": "🎭 Roleplay scene",
        "types": [
            {"id": "bath_candles", "name_ru": "🛁 Ванна при свечах", "name_en": "🛁 Bath with candles"},
            {"id": "morning_kitchen", "name_ru": "Утро на кухне", "name_en": "Morning in kitchen"},
            {"id": "massage", "name_ru": "💆 Массаж", "name_en": "💆 Massage"},
            {"id": "library", "name_ru": "Библиотека", "name_en": "Library"},
            {"id": "after_workout", "name_ru": "️ После тренировки", "name_en": "️ After workout"},
            {"id": "backstage", "name_ru": "🎭 За кулисами", "name_en": "🎭 Backstage"},
            {"id": "elevator", "name_ru": "🛗 Лифт застрял", "name_en": "🛗 Elevator stuck"},
            {"id": "hotel", "name_ru": "🏨 Номер отеля", "name_en": "🏨 Hotel room"},
            {"id": "shower_silhouette", "name_ru": "🚿 Совместный душ", "name_en": "🚿 Shared shower"},
            {"id": "private_dance", "name_ru": "🎭 Приватный танец", "name_en": "🎭 Private dance"},
            {"id": "photoshoot", "name_ru": "📸 Фотосессия", "name_en": "📸 Photoshoot"},
            {"id": "rain", "name_ru": "🌧️ Промокла", "name_en": "🌧️ Got wet"},
            {"id": "lazy_sunday", "name_ru": "🛏️ Ленивое воскресенье", "name_en": "🛏️ Lazy Sunday"},
            {"id": "movie", "name_ru": "🎬 Кино вдвоём", "name_en": "🎬 Movie together"},
            {"id": "wine", "name_ru": "Дегустация вина", "name_en": "Wine tasting"},
            {"id": "beach", "name_ru": "🏖️ Пляж после заката", "name_en": "🏖️ Beach after sunset"},
            {"id": "costume_help", "name_ru": "🎭 Помощь с костюмом", "name_en": "🎭 Costume help"},
            {"id": "rooftop", "name_ru": "Крыша ночью", "name_en": "Rooftop at night"},
        ]
    },
    "suggestive": {
        "name_ru": "В одежде пикантно",
        "name_en": "Suggestive clothed",
        "types": [
            {"id": "shirt", "name_ru": "👔 Мужская рубашка", "name_en": "👔 Men's shirt"},
            {"id": "coat", "name_ru": "Пальто на голое тело", "name_en": "Coat on bare body"},
            {"id": "dress", "name_ru": "Вечернее платье", "name_en": "Evening dress"},
            {"id": "shorts", "name_ru": "🩳 Короткие шорты + топ", "name_en": "🩳 Short shorts + top"},
            {"id": "wet", "name_ru": "🌧️ Мокрая футболка", "name_en": "🌧️ Wet t-shirt"},
        ]
    },
}

# Косплей — 25 образов из игр/аниме/поп-культуры
COSPLAY_CHARACTERS = [
    {"id": "2b", "name": "🐱 2B (NieR: Automata)", "hair": "silver-white short bob", "outfit": "black gothic lolita dress with thigh-high slit, black thigh-high boots, black gloves", "accessories": "black blindfold over eyes"},
    {"id": "mikasa", "name": "🔴 Микаса (Attack on Titan)", "hair": "long straight black hair", "outfit": "white shirt unbuttoned at top, brown corset belt, short brown skirt, brown knee-high boots", "accessories": "brown harness straps on thighs"},
    {"id": "rei", "name": "💜 Рей Аянами (Evangelion)", "hair": "short blue bob", "outfit": "blue plugsuit (tight bodysuit) with deep V-neckline, blue and white color scheme", "accessories": "none"},
    {"id": "yor", "name": "🗡️ Йор Форджер (Spy x Family)", "hair": "long black hair in loose waves", "outfit": "black backless dress with deep side cutouts, black thigh-high heels", "accessories": "two long golden hair pins crossing at the back of head, red hair ribbon"},
    {"id": "tifa", "name": "🐉 Тифа (Final Fantasy VII)", "hair": "very long straight black hair past waist", "outfit": "white cropped tank top, black mini skirt, black suspenders", "accessories": "black leather gloves, red materia bracelet"},
    {"id": "zero_two", "name": "💋 Зеро Ту (Darling in the Franxx)", "hair": "long pink hair", "outfit": "red skin-tight bodysuit with deep cutouts at hips", "accessories": "two small red horns on top of head, white hair clip"},
    {"id": "lightning", "name": "⚡ Молния (Final Fantasy XIII)", "hair": "pink spiky short hair", "outfit": "pink and black armored corset top, short skirt, thigh-high boots", "accessories": "metal arm guard on left arm, sword on back"},
    {"id": "ahri", "name": "🦊 Ахри (League of Legends)", "hair": "long brown hair", "outfit": "white and red hanbok-inspired mini dress with deep neckline", "accessories": "brown fox ears on top of head, nine fluffy brown fox tails behind body"},
    {"id": "neko", "name": "🐱 Нэко (кошачий образ)", "hair": "natural hair", "outfit": "black latex bodysuit with front zipper pulled down to navel, black thigh-high stockings", "accessories": "black cat ears on headband, black cat tail at lower back, small bell on choker collar"},
    {"id": "sailor_moon", "name": "🌙 Сейлор Мун", "hair": "very long blonde hair in two high odango buns with long flowing tails", "outfit": "white and blue sailor mini dress with red bow, white gloves, blue knee-high boots with red trim", "accessories": "red bow on chest, golden tiara with red gem on forehead"},
    {"id": "esdeath", "name": "🔥 Эсдес (Akame ga Kill)", "hair": "long straight blue hair", "outfit": "white military-style uniform with deep V-neck, short white skirt, white thigh-high boots", "accessories": "white military cap, blue ice crystal earrings"},
    {"id": "lara", "name": "🏹 Лара Крофт (Tomb Raider)", "hair": "long brown hair in thick braid over shoulder", "outfit": "teal tight tank top, brown hot-pants, brown boots", "accessories": "two pistols in holsters on thighs, backpack"},
    {"id": "kasumi", "name": "🧊 Касуми (Dead or Alive)", "hair": "long brown hair", "outfit": "purple and silver armor-bikini with minimal coverage, purple arm guards", "accessories": "purple headband, arm guards"},
    {"id": "mai", "name": "👘 Май ШираНуи (KOF)", "hair": "long black hair in high ponytail", "outfit": "red and white sleeveless kunoichi outfit with deep cleavage opening, short skirt", "accessories": "large white fan, red hair ornaments"},
    {"id": "harley", "name": "🃏 Харли Квинн (DC)", "hair": "twin pigtails — one pink, one blue", "outfit": "red and black diamond-pattern corset, red and black hot-pants, mismatched thigh-high stockings", "accessories": "black choker with PUDDIN text, baseball bat"},
    {"id": "black_widow", "name": "🖤 Чёрная Вдова (Marvel)", "hair": "short red hair", "outfit": "black skin-tight catsuit with deep V-neckline and zipper front", "accessories": "black wrist gauntlets, utility belt"},
    {"id": "wonder_woman", "name": "⚡ Чудо-женщина (DC)", "hair": "long black wavy hair", "outfit": "red corset with golden eagle emblem, blue mini skirt with white stars, red and gold boots", "accessories": "golden tiara with red star, silver bracelets, golden lasso on hip"},
    {"id": "triss", "name": "💋 Трисс (The Witcher)", "hair": "long wavy auburn/red hair", "outfit": "deep blue velvet dress with extremely low neckline and thigh-high slit", "accessories": "none"},
    {"id": "yennefer", "name": "🖤 Йеннифэр (The Witcher)", "hair": "long black curly hair", "outfit": "black and white dress with tight corset, long sleeves, thigh-high slit", "accessories": "black choker with small pendant"},
    {"id": "aloy", "name": "🏹 Элой (Horizon)", "hair": "red hair in thick braid with small braids around", "outfit": "blue and tan tribal outfit with leather corset, short skirt, leg wraps", "accessories": "blue focus device on temple, bow on back, face paint stripes"},
    {"id": "sakura", "name": "🌸 Сакура (Naruto)", "hair": "short pink bob", "outfit": "red qipao-style mini dress with white circle on back, black shorts underneath", "accessories": "red headband with metal plate, black gloves"},
    {"id": "asuka", "name": "🔥 Аска (Evangelion)", "hair": "long red hair in twin tails", "outfit": "red plugsuit (tight bodysuit) with shoulder armor pieces, orange and red color scheme", "accessories": "orange interface headset clips on hair, red shoulder armor"},
    {"id": "rem", "name": "🎀 Рем (Re:Zero)", "hair": "short blue hair covering one eye", "outfit": "black and white maid dress with short skirt, white apron, white frilled headband", "accessories": "blue morning star weapon"},
    {"id": "ram", "name": "🌸 Рам (Re:Zero)", "hair": "short pink hair covering one eye", "outfit": "black and white maid dress with short skirt, white apron, white frilled headband", "accessories": "none"},
    {"id": "kitsune", "name": "🦊 Кицунэ (лисий образ)", "hair": "natural hair", "outfit": "short red and white kimono robe worn loosely off one shoulder, red obi sash", "accessories": "two fluffy fox ears on head, nine golden fox tails behind body, small bell on red string around neck"},
]

# Обстановки (10 вариантов)
LOCATIONS = [
    {"id": "bedroom", "name_ru": "🛏️ Спальня", "name_en": "🛏️ Bedroom"},
    {"id": "bathroom", "name_ru": "🚿 Ванная", "name_en": "🚿 Bathroom"},
    {"id": "balcony", "name_ru": "🌅 Балкон (закат)", "name_en": "🌅 Balcony (sunset)"},
    {"id": "closet", "name_ru": "🪞 Гардеробная", "name_en": "🪞 Walk-in closet"},
    {"id": "candles", "name_ru": "🕯️ Свечи", "name_en": "🕯️ Candles (dark room)"},
    {"id": "hotel", "name_ru": "🏨 Отель", "name_en": "🏨 Hotel"},
    {"id": "beach", "name_ru": "🏖️ Пляж", "name_en": "🏖️ Beach"},
    {"id": "nature", "name_ru": "🌲 Природа", "name_en": "🌲 Nature"},
    {"id": "studio", "name_ru": "🎭 Студия", "name_en": "🎭 Studio (black background)"},
    {"id": "random", "name_ru": "🎲 Случайная", "name_en": "🎲 Random"},
]

# Настроения (8 вариантов)
MOODS = [
    {"id": "playful", "name_ru": "😏 Игривое", "name_en": "😏 Playful"},
    {"id": "morning", "name_ru": "🥱 Утреннее", "name_en": "🥱 Morning"},
    {"id": "bold", "name_ru": "💃 Дерзкое", "name_en": "💃 Bold"},
    {"id": "tender", "name_ru": "Нежное", "name_en": "Tender"},
    {"id": "passionate", "name_ru": "🔥 Страстное", "name_en": "🔥 Passionate"},
    {"id": "shy", "name_ru": "🦋 Застенчивое", "name_en": "🦋 Shy"},
    {"id": "confident", "name_ru": "👑 Уверенное", "name_en": "👑 Confident"},
    {"id": "random", "name_ru": "🎲 Случайное", "name_en": "🎲 Random"},
]


# ─── Модели для хранения состояния ─────────────────────────────────────────────

@dataclass
class PrivatePhotoRequest:
    """Запрос на приватное фото."""
    category: str  # lingerie, nude_art, roleplay, suggestive, cosplay
    type_id: str  # ID типа внутри категории
    location_id: str  # ID обстановки
    mood_id: str  # ID настроения
    character_id: str = CHARACTER_ID
    # Для косплея
    cosplay_id: Optional[str] = None


@dataclass
class PrivatePhotoUsage:
    """Использование бесплатных лимитов."""
    user_id: int
    date: date
    private_used: int = 0
    cosplay_used: int = 0
    hot_pass_expires: Optional[datetime] = None


# ─── Функции работы с БД ───────────────────────────────────────────────────────

def get_private_photo_usage(telegram_id: int) -> Dict[str, Any]:
    """Получить использование бесплатных лимитов и статус Hot Pass."""
    uid = ensure_user(telegram_id)
    today = date.today()
    
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.id == uid))
        if not user:
            return {
                "private_used": 0,
                "cosplay_used": 0,
                "private_left": PRIVATE_PHOTO_FREE_DAILY,
                "cosplay_left": COSPLAY_PHOTO_FREE_DAILY,
                "hot_pass_active": False,
                "hot_pass_expires": None,
            }
        
        # Проверяем Hot Pass
        hot_pass_active = False
        hot_pass_expires = None
        if hasattr(user, 'hot_pass_expires') and user.hot_pass_expires:
            if user.hot_pass_expires > datetime.utcnow():
                hot_pass_active = True
                hot_pass_expires = user.hot_pass_expires
        
        # Сбрасываем счётчики если новый день
        private_used = 0
        cosplay_used = 0
        if hasattr(user, 'private_photo_date') and user.private_photo_date:
            if user.private_photo_date == today:
                private_used = getattr(user, 'private_photo_used', 0) or 0
                cosplay_used = getattr(user, 'cosplay_photo_used', 0) or 0
        
        return {
            "private_used": private_used,
            "cosplay_used": cosplay_used,
            "private_left": max(0, PRIVATE_PHOTO_FREE_DAILY - private_used),
            "cosplay_left": max(0, COSPLAY_PHOTO_FREE_DAILY - cosplay_used),
            "hot_pass_active": hot_pass_active,
            "hot_pass_expires": hot_pass_expires,
        }


def consume_free_private_photo(telegram_id: int, category: str) -> bool:
    """
    Использовать бесплатный лимит.
    Возвращает True если использован бесплатный, False если нужно платить.
    """
    uid = ensure_user(telegram_id)
    today = date.today()
    
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.id == uid))
        if not user:
            return False
        
        # Проверяем Hot Pass
        if hasattr(user, 'hot_pass_expires') and user.hot_pass_expires:
            if user.hot_pass_expires > datetime.utcnow():
                return True  # Hot Pass активен, не считаем
        
        # Определяем какой лимит проверять
        if category == "cosplay":
            limit = COSPLAY_PHOTO_FREE_DAILY
            used_attr = 'cosplay_photo_used'
            date_attr = 'cosplay_photo_date'
        else:
            limit = PRIVATE_PHOTO_FREE_DAILY
            used_attr = 'private_photo_used'
            date_attr = 'private_photo_date'
        
        # Сбрасываем если новый день
        current_date = getattr(user, date_attr, None)
        if current_date != today:
            setattr(user, used_attr, 0)
            setattr(user, date_attr, today)
        
        used = getattr(user, used_attr, 0) or 0
        if used < limit:
            setattr(user, used_attr, used + 1)
            session.commit()
            return True
        
        return False


def activate_hot_pass(telegram_id: int, duration_days: int) -> datetime:
    """Активировать Hot Pass на N дней."""
    uid = ensure_user(telegram_id)
    expires = datetime.utcnow() + timedelta(days=duration_days)
    
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.id == uid))
        if user:
            user.hot_pass_expires = expires
            session.commit()
    
    return expires


# ─── Промпт-конструктор ────────────────────────────────────────────────────────


def _build_visual_identity_lock(character_id: str) -> str:
    """V3.45.19: build a visual identity description (face, hair, body) for
    private photo prompts. Uses the same character card / visual_identity data
    as the regular photo pipeline."""
    from services.character_card_service import get_card
    from services.photo_service import resolve_character, BODY_SPECS, DEFAULT_FEMALE_BODY_SPEC
    card = get_card(character_id)
    character = resolve_character(character_id)
    name = card.display_name if card else (character.get('name') or character_id)
    try:
        age = int(character.get('age') or 25)
    except (TypeError, ValueError):
        age = 25
    visual_identity = character.get('visual_identity', {})
    preserve = visual_identity.get('preserve_identity', [])
    preserve_text = '; '.join(preserve) if preserve else 'consistent facial features, hair color and body proportions'
    body_spec = visual_identity.get('body_spec') or ''
    if not body_spec:
        body_spec = BODY_SPECS.get(character_id, '') or DEFAULT_FEMALE_BODY_SPEC
    lock = (
        f'PHOTO IDENTITY — HIGHEST PRIORITY. Create the SAME fictional adult woman, {name}, age {age}. '
        f'Preserve these exact traits: {preserve_text}. '
        f'BODY IDENTITY: {name} has {body_spec}. This figure is permanent and overrides any reference. '
        f'Do not substitute another person, do not change age, ethnicity, hair color or body type. '
        f'She is the same woman in every photo.'
    )
    return lock

def build_private_photo_prompt(
    request: PrivatePhotoRequest,
    character_description: str,
) -> str:
    """
    Строит промпт для SpicyAPI.
    
    Структура:
    [визуальная идентичность] + [категория] + [тип] + [обстановка] + [настроение]
    + [правило волос для косплея]
    """
    parts = []
    
    # V3.45.19: use VISUAL identity (face, body, hair) instead of personality DNA
    visual_lock = _build_visual_identity_lock(request.character_id)
    if visual_lock:
        parts.append(visual_lock)
    else:
        parts.append(f"Subject: {character_description}")
    
    # Обстановка
    location = next((loc for loc in LOCATIONS if loc["id"] == request.location_id), None)
    if location and request.location_id != "random":
        parts.append(f"Location: {location['name_en']}")
    
    # Настроение
    mood = next((m for m in MOODS if m["id"] == request.mood_id), None)
    if mood and request.mood_id != "random":
        parts.append(f"Mood: {mood['name_en']}")
    
    # Косплей — отдельная обработка с правилом волос
    if request.category == "cosplay" and request.cosplay_id:
        cosplay = next((c for c in COSPLAY_CHARACTERS if c["id"] == request.cosplay_id), None)
        if cosplay:
            parts.append(f"Cosplay character: {cosplay['name']}")
            parts.append(f"HAIRSTYLE: REPLACE the character's natural hair with: {cosplay['hair']}. The cosplay hair completely replaces natural hair — do NOT show both hairstyles at once.")
            parts.append(f"Outfit: {cosplay['outfit']}")
            if cosplay['accessories'] and cosplay['accessories'] != "none":
                parts.append(f"Accessories: {cosplay['accessories']}")
    else:
        # Обычная категория — ищем тип
        category_data = PRIVATE_PHOTO_CATEGORIES.get(request.category, {})
        type_data = next((t for t in category_data.get("types", []) if t["id"] == request.type_id), None)
        if type_data:
            parts.append(f"Style: {type_data['name_en']}")
    
    # Общие правила
    parts.append("High quality photo, professional photography, detailed, realistic")
    parts.append("NSFW content allowed, uncensored generation")
    
    return "\n".join(parts)


# ─── SpicyAPI интеграция ───────────────────────────────────────────────────────

async def generate_private_photo(
    request: PrivatePhotoRequest,
    character_description: str,
) -> Optional[bytes]:
    """
    Генерирует приватное фото через SpicyAPI.
    Возвращает bytes изображения или None при ошибке.
    """
    if not SPICYAPI_KEY:
        logger.error("SPICYAPI_KEY not configured")
        return None
    
    prompt = build_private_photo_prompt(request, character_description)
    
    # TODO: Реализовать HTTP запрос к SpicyAPI
    # Пример:
    # async with aiohttp.ClientSession() as session:
    #     async with session.post(
    #         f"{SPICYAPI_BASE_URL}/generate",
    #         headers={"Authorization": f"Bearer {SPICYAPI_KEY}"},
    #         json={
    #             "model": SPICYAPI_IMAGE_MODEL,
    #             "prompt": prompt,
    #             "timeout": SPICYAPI_IMAGE_TIMEOUT,
    #         }
    #     ) as resp:
    #         if resp.status == 200:
    #             data = await resp.json()
    #             return base64.b64decode(data["image"])
    
    logger.info(f"Private photo request: category={request.category}, type={request.type_id}")
    logger.debug(f"Prompt: {prompt}")
    
    # Заглушка — вернуть None, реализовать позже
    return None


SPICYAPI_TASK_BASE = "https://api.spicyapi.ai/api/v1"


async def _spicyapi_call(method: str, path: str, headers: dict = None, **kwargs) -> dict:
    """Вызов к SpicyAPI с обработкой ошибок."""
    url = f"{SPICYAPI_TASK_BASE}{path}"
    default_headers = {
        "Authorization": f"Bearer {SPICYAPI_KEY}",
        "Content-Type": "application/json",
    }
    if headers:
        default_headers.update(headers)
    
    async with aiohttp.ClientSession() as session:
        async with session.request(
            method, url, headers=default_headers, timeout=aiohttp.ClientTimeout(total=30), **kwargs
        ) as resp:
            body = await resp.json()
            logger.info(f"SpicyAPI {method} {path}: status={resp.status}, body={body}")
            if body.get("code") != 200:
                raise RuntimeError(f'SpicyAPI error: {body.get("code")} {body.get("msg")} — full: {body}')
            return body.get("data", {})


async def generate_private_photo_real(
    request: PrivatePhotoRequest,
    character_description: str,
) -> Optional[bytes]:
    """
    Генерирует приватное фото через SpicyAPI.
    Возвращает bytes изображения или None при ошибке.
    """
    if not SPICYAPI_KEY:
        logger.error("SPICYAPI_KEY not configured")
        return None
    
    prompt = build_private_photo_prompt(request, character_description)
    logger.info(f"Private photo: category={request.category}, type={request.type_id}")
    
    try:
        # 1. Создаём задачу
        idempotency_key = str(uuid.uuid4())
        logger.info(f"SpicyAPI: creating task, model={SPICYAPI_IMAGE_MODEL}")
        task_data = await _spicyapi_call(
            "POST", "/jobs/createTask",
            headers={"Idempotency-Key": idempotency_key},
            json={
                "model": SPICYAPI_IMAGE_MODEL,
                "input": {
                    "prompt": prompt,
                    "resolution": "1k",
                    "aspect_ratio": "3:4",
                    "output_format": "jpeg",
                }
            }
        )
        task_id = task_data.get("taskId")
        logger.info(f"SpicyAPI: task created, id={task_id}, data={task_data}")
        if not task_id:
            logger.error(f"No taskId in SpicyAPI response: {task_data}")
            return None
        
        logger.info(f"SpicyAPI task: {task_id}")
        
        # 2. Поллим статус
        deadline = asyncio.get_event_loop().time() + SPICYAPI_IMAGE_TIMEOUT
        wait = 2.0
        
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(wait)
            wait = min(wait * 1.5, 15.0)
            
            task_info = await _spicyapi_call("GET", f"/jobs/recordInfo?taskId={task_id}")
            state = task_info.get("state")
            
            if state == "succeeded":
                assets = task_info.get("output", {}).get("assets", [])
                asset_url = next((a["url"] for a in assets if a.get("url")), None)
                if not asset_url:
                    return None
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(asset_url) as resp:
                        if resp.status == 200:
                            return await resp.read()
                return None
            
            elif state in ("failed", "expired", "canceled"):
                logger.error(f"SpicyAPI task {state}: {task_info.get('errorMessage')}")
                return None
        
        logger.error(f"SpicyAPI timeout: {task_id}")
        return None
        
    except Exception as e:
        logger.exception(f"SpicyAPI failed: {e}")
        return None


# ─── Вспомогательные функции ───────────────────────────────────────────────────

def get_category_name(category: str, lang: str = "ru") -> str:
    """Получить название категории на нужном языке."""
    cat = PRIVATE_PHOTO_CATEGORIES.get(category, {})
    return cat.get(f"name_{lang}", cat.get("name_ru", category))


def get_type_name(category: str, type_id: str, lang: str = "ru") -> str:
    """Получить название типа на нужном языке."""
    cat = PRIVATE_PHOTO_CATEGORIES.get(category, {})
    type_data = next((t for t in cat.get("types", []) if t["id"] == type_id), None)
    if type_data:
        return type_data.get(f"name_{lang}", type_data.get("name_ru", type_id))
    return type_id


def get_cosplay_name(cosplay_id: str) -> str:
    """Получить название косплей-персонажа."""
    cosplay = next((c for c in COSPLAY_CHARACTERS if c["id"] == cosplay_id), None)
    return cosplay["name"] if cosplay else cosplay_id


def get_location_name(location_id: str, lang: str = "ru") -> str:
    """Получить название обстановки."""
    loc = next((l for l in LOCATIONS if l["id"] == location_id), None)
    if loc:
        return loc.get(f"name_{lang}", loc.get("name_ru", location_id))
    return location_id


def get_mood_name(mood_id: str, lang: str = "ru") -> str:
    """Получить название настроения."""
    mood = next((m for m in MOODS if m["id"] == mood_id), None)
    if mood:
        return mood.get(f"name_{lang}", mood.get("name_ru", mood_id))
    return mood_id


# ─── Кэш фото (PrivateGallery) ─────────────────────────────────────────────

def _prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()


def cache_get(prompt: str, character_id: str) -> Optional[bytes]:
    """Получить фото из кэша по хэшу промпта."""
    ph = _prompt_hash(prompt)
    with SessionLocal() as session:
        row = session.scalar(select(PrivateGallery).where(
            PrivateGallery.prompt_hash == ph,
            PrivateGallery.character_id == character_id,
        ))
        if row and row.image_bytes:
            return row.image_bytes
    return None


def cache_save(prompt: str, character_id: str, category: str, type_id: str, image_bytes: bytes):
    """Сохранить фото в кэш."""
    from models.app_models import PrivateGallery
    ph = _prompt_hash(prompt)
    with SessionLocal() as session:
        existing = session.scalar(select(PrivateGallery).where(
            PrivateGallery.prompt_hash == ph,
            PrivateGallery.character_id == character_id,
        ))
        if existing:
            return
        row = PrivateGallery(
            user_id=0, character_id=character_id,
            category=category, type_id=type_id,
            prompt_hash=ph, image_bytes=image_bytes,
        )
        session.add(row)
        session.commit()


def gallery_save(telegram_id: int, character_id: str, category: str, type_id: str, image_bytes: bytes):
    """Сохранить фото в приватную галерею пользователя."""
    from models.app_models import PrivateGallery
    uid = ensure_user(telegram_id)
    ph = _prompt_hash(f"{uid}:{category}:{type_id}:{datetime.utcnow().isoformat()}")
    with SessionLocal() as session:
        row = PrivateGallery(
            user_id=uid, character_id=character_id,
            category=category, type_id=type_id,
            prompt_hash=ph, image_bytes=image_bytes,
        )
        session.add(row)
        session.commit()


def gallery_list(telegram_id: int, limit: int = 20) -> list:
    """Получить список фото из приватной галереи."""
    from models.app_models import PrivateGallery
    uid = ensure_user(telegram_id)
    with SessionLocal() as session:
        rows = session.execute(
            select(PrivateGallery)
            .where(PrivateGallery.user_id == uid)
            .order_by(PrivateGallery.created_at.desc())
            .limit(limit)
        ).scalars().all()
        return [{"id": r.id, "category": r.category, "type_id": r.type_id,
                 "image_bytes": r.image_bytes, "created_at": r.created_at} for r in rows]


def gallery_count(telegram_id: int) -> int:
    """Количество фото в приватной галерее."""
    from models.app_models import PrivateGallery
    uid = ensure_user(telegram_id)
    with SessionLocal() as session:
        return session.scalar(select(func.count()).select_from(PrivateGallery).where(PrivateGallery.user_id == uid)) or 0


# ─── Достижения ─────────────────────────────────────────────────────────────

ACHIEVEMENTS = {
    "first_private": {"name": "💋 Первый раз наедине", "condition": lambda total: total >= 1},
    "collector_10": {"name": "🎭 Коллекционер (10 фото)", "condition": lambda total: total >= 10},
    "collector_25": {"name": "🏆 Коллекционер (25 фото)", "condition": lambda total: total >= 25},
    "collector_50": {"name": "💎 Коллекционер (50 фото)", "condition": lambda total: total >= 50},
    "hot_pass": {"name": "🔥 Hot Pass", "condition": lambda total: False},
    "night_owl": {"name": "🌙 Ночная птица", "condition": lambda total: False},
}


def check_achievements(telegram_id: int) -> list:
    """Проверить и выдать новые достижения."""
    uid = ensure_user(telegram_id)
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.id == uid))
        if not user:
            return []
        current = set((user.achievements or "").split(",")) - {""}
        total = user.total_private_photos or 0
        new_achievements = []
        for ach_id, ach_data in ACHIEVEMENTS.items():
            if ach_id in current:
                continue
            if ach_data["condition"](total):
                current.add(ach_id)
                new_achievements.append(ach_id)
        if new_achievements:
            user.achievements = ",".join(sorted(current))
            session.commit()
        return new_achievements


def grant_achievement(telegram_id: int, achievement_id: str):
    """Выдать достижение вручную (для hot_pass, night_owl)."""
    uid = ensure_user(telegram_id)
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.id == uid))
        if not user:
            return
        current = set((user.achievements or "").split(",")) - {""}
        current.add(achievement_id)
        user.achievements = ",".join(sorted(current))
        session.commit()


def get_achievements(telegram_id: int) -> list:
    """Получить список достижений пользователя."""
    uid = ensure_user(telegram_id)
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.id == uid))
        if not user:
            return []
        current = set((user.achievements or "").split(",")) - {""}
        return [ACHIEVEMENTS[a]["name"] for a in current if a in ACHIEVEMENTS]


# ─── Ежедневный подарок «Подарок от неё» ────────────────────────────────────

async def send_daily_gift(telegram_id: int, bot) -> bool:
    """Отправить ежедневный бесплатный подарок. Возвращает True если отправлен."""
    uid = ensure_user(telegram_id)
    today = date.today()
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.id == uid))
        if not user:
            return False
        if user.last_daily_gift_date == today:
            return False
        user.last_daily_gift_date = today
        session.commit()
    # Генерируем случайное фото «наедине»
    import random
    cat = random.choice(list(PRIVATE_PHOTO_CATEGORIES.keys()))
    types = PRIVATE_PHOTO_CATEGORIES[cat]["types"]
    type_id = random.choice(types)["id"]
    loc = random.choice(LOCATIONS)["id"]
    mood = random.choice(MOODS)["id"]
    request = PrivatePhotoRequest(
        category=cat, type_id=type_id, location_id=loc, mood_id=mood,
        character_id=CHARACTER_ID,
    )
    from services.character_dna_service import character_dna_context
    char_desc = character_dna_context(CHARACTER_ID)
    image_bytes = await generate_private_photo_real(request, char_desc)
    if image_bytes:
        import io
        from aiogram.types import BufferedInputFile
        type_name = get_type_name(cat, type_id)
        await bot.send_photo(
            chat_id=telegram_id,
            photo=BufferedInputFile(image_bytes, filename='daily_gift.jpg'),
            caption=f'🎁 Я скучала... вот, держи 💋\n\n{type_name}',
        )
        # Сохраняем в галерею
        gallery_save(telegram_id, CHARACTER_ID, cat, type_id, image_bytes)
        return True
    return False


# ─── Голос + фото комбо ─────────────────────────────────────────────────────

async def generate_voice_photo_combo(
    telegram_id: int,
    request: PrivatePhotoRequest,
    character_description: str,
    bot,
) -> bool:
    """Генерирует фото + голосовое сообщение."""
    image_bytes = await generate_private_photo_real(request, character_description)
    if not image_bytes:
        return False
    
    import io
    from aiogram.types import BufferedInputFile
    type_name = get_type_name(request.category, request.type_id)
    
    # Отправляем фото
    await bot.send_photo(
        chat_id=telegram_id,
        photo=BufferedInputFile(image_bytes, filename='voice_photo.jpg'),
        caption=f'💋 {type_name}',
    )
    
    # Генерируем голосовое сообщение через MiniMax TTS
    voice_phrases = [
        "Это только для тебя... ",
        "Я скучала по тебе... ",
        "Хочешь ещё?.. ",
        "Тебе нравится?.. ",
        "Я рада тебя видеть... ",
    ]
    import random
    phrase = random.choice(voice_phrases)
    
    try:
        from services.voice_service import generate_voice
        voice_bytes = await generate_voice(phrase)
        if voice_bytes:
            await bot.send_voice(
                chat_id=telegram_id,
                voice=BufferedInputFile(voice_bytes, filename='voice.ogg'),
            )
    except Exception as e:
        logger.warning(f"Voice generation failed: {e}")
    
    # Сохраняем в галерею
    gallery_save(telegram_id, request.character_id, request.category, request.type_id, image_bytes)
    return True
