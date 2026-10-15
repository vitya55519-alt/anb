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
import os
import hashlib
import json
import random
import re
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
    SPICYAPI_T2I_MODEL,
    SPICYAPI_RESOLUTION,
    SPICYAPI_ENABLE_THINKING,
    SPICYAPI_IMAGE_TIMEOUT,
    SPICYAPI_ESTIMATED_COST_USD,
    CHARACTER_ID,
    PUBLIC_BASE_URL,
)
from services import spend_service  # V3.56.0: ledger every billed SpicyAPI job

logger = logging.getLogger(__name__)


# ─── Категории и типы фото ─────────────────────────────────────────────────────

# Фото «наедине» — 4 категории
PRIVATE_PHOTO_CATEGORIES = {
    "lingerie": {
        "name_ru": "👙 В белье",
        "name_en": "🩲 Lingerie",
        "types": [
            {"id": "lace", "name_ru": "🖤 Кружевной комплект", "name_en": "Lace set"},
            {"id": "silk", "name_ru": "🤍 Шёлковый комплект", "name_en": "🤍 Silk set"},
            {"id": "corset", "name_ru": "❤️ Корсет и чулки", "name_en": "❤️ Corset + stockings"},
            {"id": "bodysuit", "name_ru": "🩱 Боди", "name_en": "🩱 Bodysuit"},
            {"id": "stockings", "name_ru": "🧦 Чулки с подвязками", "name_en": "🧦 Stockings + garters"},
            {"id": "braziliana", "name_ru": "🍑 Бразильские трусики", "name_en": "🩳 Brazilian"},
            {"id": "bows", "name_ru": "🎀 Бельё с бантиками", "name_en": "Lingerie with bows"},
            {"id": "fishnet", "name_ru": "🕸️ Бельё в сетку", "name_en": "🕸️ Fishnet lingerie"},
        ]
    },
    "nude_art": {
        "name_ru": "🎨 Красивое ню",
        "name_en": "🎨 Art nude",
        "types": [
            {"id": "sunset", "name_ru": "🌅 Силуэт на закате", "name_en": "🌅 Sunset silhouette"},
            {"id": "shower", "name_ru": "🚿 Под душем", "name_en": "🚿 In shower"},
            {"id": "bath", "name_ru": "🛁 В ванной", "name_en": "🛁 In bath"},
            {"id": "mirror", "name_ru": "🪞 Отражение в зеркале", "name_en": "🪞 Mirror reflection"},
            {"id": "moonlight", "name_ru": "🌙 При луне", "name_en": "🌙 Moonlight"},
            {"id": "underwater", "name_ru": "🌊 Под водой", "name_en": "Underwater"},
            {"id": "artistic", "name_ru": "🖌️ Как на картине", "name_en": "🎨 Artistic nude"},
            {"id": "garden", "name_ru": "🌿 В саду", "name_en": "🌿 In garden"},
            {"id": "cave", "name_ru": "🪨 В гроте", "name_en": "🌋 In cave"},
            {"id": "marble", "name_ru": "🏛️ Как античная статуя", "name_en": "🏛️ Marble statue"},
            {"id": "studio", "name_ru": "🖼️ В мастерской художника", "name_en": "🎨 In studio"},
            {"id": "field", "name_ru": "🌾 В поле", "name_en": "🌾 In field"},
            {"id": "snow", "name_ru": "❄️ На снегу", "name_en": "❄️ In snow"},
            {"id": "petals", "name_ru": "🌹 Ванна с лепестками", "name_en": "🪷 Bath with petals"},
            {"id": "space", "name_ru": "🌌 Среди звёзд", "name_en": "🌌 Space"},
            {"id": "cliff", "name_ru": "🏔️ На скале", "name_en": "🏔️ On cliff"},
            {"id": "backstage", "name_ru": "🎪 За кулисами", "name_en": "🎪 Backstage"},
            {"id": "fabric", "name_ru": "🤍 На белом фоне", "name_en": "🤍 On white"},
        ]
    },
    "roleplay": {
        "name_ru": "🎭 Сюжетная сцена",
        "name_en": "🎭 Roleplay scene",
        "types": [
            {"id": "bath_candles", "name_ru": "🕯️ Ванна при свечах", "name_en": "🛁 Bath with candles"},
            {"id": "morning_kitchen", "name_ru": "☕ Утро на кухне", "name_en": "Morning in kitchen"},
            {"id": "massage", "name_ru": "💆 Массаж", "name_en": "💆 Massage"},
            {"id": "library", "name_ru": "📚 В библиотеке", "name_en": "Library"},
            {"id": "after_workout", "name_ru": "💪 После тренировки", "name_en": "️ After workout"},
            {"id": "backstage", "name_ru": "🎭 За кулисами", "name_en": "🎭 Backstage"},
            {"id": "elevator", "name_ru": "🛗 Застряли в лифте", "name_en": "🛗 Elevator stuck"},
            {"id": "hotel", "name_ru": "🏨 Номер в отеле", "name_en": "🏨 Hotel room"},
            {"id": "shower_silhouette", "name_ru": "🚿 Душ вдвоём", "name_en": "🚿 Shared shower"},
            {"id": "private_dance", "name_ru": "💃 Приватный танец", "name_en": "🎭 Private dance"},
            {"id": "photoshoot", "name_ru": "📸 Фотосессия", "name_en": "📸 Photoshoot"},
            {"id": "rain", "name_ru": "🌧️ Промокла под дождём", "name_en": "🌧️ Got wet"},
            {"id": "lazy_sunday", "name_ru": "🛏️ Ленивое воскресенье", "name_en": "🛏️ Lazy Sunday"},
            {"id": "movie", "name_ru": "🎬 Кино вдвоём", "name_en": "🎬 Movie together"},
            {"id": "wine", "name_ru": "🍷 Вечер с вином", "name_en": "Wine tasting"},
            {"id": "beach", "name_ru": "🏖️ Пляж после заката", "name_en": "🏖️ Beach after sunset"},
            {"id": "costume_help", "name_ru": "👗 Помоги с костюмом", "name_en": "🎭 Costume help"},
            {"id": "rooftop", "name_ru": "🌃 Ночь на крыше", "name_en": "Rooftop at night"},
        ]
    },
    "suggestive": {
        "name_ru": "😏 Пикантно в одежде",
        "name_en": "Suggestive clothed",
        "types": [
            {"id": "shirt", "name_ru": "👔 В твоей рубашке", "name_en": "Men's shirt"},
            {"id": "coat", "name_ru": "🧥 Пальто на голое тело", "name_en": "Coat on bare body"},
            {"id": "dress", "name_ru": "👗 Вечернее платье", "name_en": "Evening dress"},
            {"id": "shorts", "name_ru": "🩳 Шортики и топ", "name_en": "Short shorts + top"},
            {"id": "wet", "name_ru": "💦 Мокрая футболка", "name_en": "Wet t-shirt"},
            # V3.60.1: owner's «подняла топ / спустила топ — видно бюстгальтер».
            {"id": "top_up", "name_ru": "👚 Подняла топ", "name_en": "Lifted top",
             "prompt": "she pulls her tight thin top up with one hand to just above her bra, her bra fully visible underneath, flat stomach, playful look into the camera; jeans or a fitted skirt below"},
            {"id": "top_down", "name_ru": "😈 Спустила топ", "name_en": "Top pulled down",
             "prompt": "the strap of her top has slipped off one shoulder and she tugs the neckline down so one cup of her bra and its strap show, teasing half-smile"},
            {"id": "open_shirt", "name_ru": "🔓 Расстёгнутая рубашка", "name_en": "Unbuttoned shirt",
             "prompt": "a fitted shirt unbuttoned halfway, the bra clearly visible between the open sides, one hand on the collar"},
            {"id": "tank_strap", "name_ru": "🎽 Майка и лямка", "name_en": "Tank top and strap",
             "prompt": "a tight thin tank top, the outline of her bra showing through the fabric and a thin bra strap slipping out at the shoulder"},
        ]
    },
    "fully_nude": {
        "name_ru": "🔥 Полностью обнажённая",
        "name_en": "Fully nude",
        "peach_cost": 4,
        "types": [
            {"id": "bed", "name_ru": "🛏️ На кровати", "name_en": "On bed"},
            {"id": "shower", "name_ru": "🚿 В душе", "name_en": "In shower"},
            {"id": "mirror", "name_ru": "🪞 У зеркала", "name_en": "By mirror"},
            {"id": "window", "name_ru": "🪟 У окна", "name_en": "By window"},
            {"id": "bathtub", "name_ru": "🛁 В ванной", "name_en": "In bathtub"},
            {"id": "outdoor", "name_ru": "🌲 На природе", "name_en": "Outdoor"},
            {"id": "candles", "name_ru": "🕯️ При свечах", "name_en": "By candlelight"},
            {"id": "silk_sheets", "name_ru": "🤍 На шёлковых простынях", "name_en": "On silk sheets"},
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

_REAL_PLACES = (
    "a cozy bedroom with warm lamps and soft sheets", "a sunlit modern apartment living room",
    "a stylish hotel room with a city view", "a sunset balcony with city lights",
    "a candlelit bathroom with marble and steam", "a walk-in closet with a full-length mirror",
)

# Обстановки (10 вариантов)
LOCATIONS = [
    {"id": "bedroom", "name_ru": "🛏️ Спальня", "name_en": "🛏️ Bedroom"},
    {"id": "bathroom", "name_ru": "🚿 Ванная", "name_en": "🚿 Bathroom"},
    {"id": "balcony", "name_ru": "🌅 Балкон (закат)", "name_en": "🌅 Balcony (sunset)"},
    {"id": "closet", "name_ru": "🪞 Гардеробная", "name_en": "🪞 Walk-in closet"},
    {"id": "candles", "name_ru": "🕯️ При свечах", "name_en": "🕯️ Candles (dark room)"},
    {"id": "hotel", "name_ru": "🏨 Отель", "name_en": "🏨 Hotel"},
    {"id": "beach", "name_ru": "🏖️ Пляж", "name_en": "🏖️ Beach"},
    {"id": "nature", "name_ru": "🌲 Природа", "name_en": "🌲 Nature"},
    {"id": "studio", "name_ru": "📸 Фотостудия", "name_en": "a styled photo studio set: warm textured backdrop in blush, beige or terracotta, a velvet armchair or draped fabric, plants and soft directional light — never a plain black void"},
    {"id": "random", "name_ru": "🎲 Наугад", "name_en": "🎲 Random"},
]

# Настроения (8 вариантов)
MOODS = [
    {"id": "playful", "name_ru": "😏 Игривое", "name_en": "😏 Playful"},
    {"id": "morning", "name_ru": "🥱 Утреннее", "name_en": "🥱 Morning"},
    {"id": "bold", "name_ru": "💃 Дерзкое", "name_en": "💃 Bold"},
    {"id": "tender", "name_ru": "🌸 Нежное", "name_en": "Tender"},
    {"id": "passionate", "name_ru": "🔥 Страстное", "name_en": "🔥 Passionate"},
    {"id": "shy", "name_ru": "🦋 Застенчивое", "name_en": "🦋 Shy"},
    {"id": "confident", "name_ru": "👑 Уверенное", "name_en": "👑 Confident"},
    {"id": "random", "name_ru": "🎲 Наугад", "name_en": "🎲 Random"},
]

# V3.45.26: цвета белья/одежды — выбор игрока в мастере «Наедине».
# `word` — английское описание цвета для промпта.
BRA_CUT_POOL = (
    "a lace balconette bra", "a smooth t-shirt bra", "a satin plunge bra", "a sheer mesh bra",
    "a cotton bralette", "a triangle lace bralette", "a sporty bra", "a strappy cage bra",
    "a bra with small bows", "a velvet bra", "a floral-embroidered bra",
)
BRA_COLOR_POOL = (
    "black", "white", "red", "wine red", "nude beige", "dusty pink", "emerald green",
    "navy blue", "lavender", "leopard print", "cream", "baby blue",
)

LINGERIE_COLORS = [
    {"id": "black",   "name_ru": "🖤 Чёрное",    "name_en": "Black",   "word": "black"},
    {"id": "white",   "name_ru": "🤍 Белое",     "name_en": "White",   "word": "white"},
    {"id": "red",     "name_ru": "❤️ Красное",    "name_en": "Red",     "word": "red"},
    {"id": "burgundy","name_ru": "🍷 Бордовое",   "name_en": "Burgundy","word": "deep burgundy / wine red"},
    {"id": "nude",    "name_ru": "🤎 Бежевое",    "name_en": "Nude",    "word": "nude beige"},
    {"id": "emerald", "name_ru": "💚 Изумрудное",  "name_en": "Emerald", "word": "emerald green"},
    {"id": "royal",   "name_ru": "💙 Синее",      "name_en": "Royal blue", "word": "royal blue"},
    {"id": "purple",  "name_ru": "💜 Фиолетовое", "name_en": "Purple",  "word": "purple / violet"},
    {"id": "pink",    "name_ru": "🌸 Розовое",    "name_en": "Pink",    "word": "soft pink"},
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
    # V3.45.26: бельё/одежда — выбранный игроком цвет
    color: Optional[str] = None
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


# V3.46.0: achievement rewards of kind 'scene' permanently unlock one sealed
# private-photo category (no new generation — reuses existing content). The
# reward payload key is written into user.achievements (same CSV the unified
# board reads); when present, the mapped category is free forever. Fully_nude
# is reserved for the rarest achievement (90-day anniversary).
ACHIEVEMENT_SCENE_UNLOCKS: Dict[str, str] = {
    "ach_seven": "suggestive",
    "ach_hundred": "lingerie",
    "ach_photo_collector": "roleplay",
    "ach_date_collector": "cosplay",
    "ach_anniv7": "lingerie",
    "ach_anniv30": "nude_art",
    "ach_anniv90": "fully_nude",
    "ach_views100": "roleplay",
}


def unlocked_scene_categories(telegram_id: int) -> set:
    """V3.46.0: sealed categories this user unlocked via achievement scenes."""
    uid = ensure_user(telegram_id)
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.id == uid))
        if not user:
            return set()
        keys = set((user.achievements or "").split(",")) - {""}
    return {cat for key, cat in ACHIEVEMENT_SCENE_UNLOCKS.items() if key in keys}


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
        
        # V3.46.0: a sealed category unlocked by an achievement is free forever
        # and never burns the daily limit.
        keys = set((user.achievements or "").split(",")) - {""}
        if any(ACHIEVEMENT_SCENE_UNLOCKS.get(k) == category for k in keys):
            return True
        
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


# V3.60.8: the picked mood now drives the face too (it used to be a bare label).
_MOOD_EXPRESSIONS = {
    "playful": ("teasing", "wink", "tongue_out_playful", "laughing"),
    "morning": ("sleepy_soft", "smile"),
    "bold": ("confident", "biting_lip", "bedroom_eyes"),
    "tender": ("smile", "shy", "blow_kiss"),
    "passionate": ("desire", "bedroom_eyes", "pleasure", "breathless", "biting_lip"),
    "shy": ("shy", "biting_lip"),
    "confident": ("confident", "bedroom_eyes", "pouty_seductive"),
}


def _build_visual_identity_lock(character_id: str) -> str:
    """V3.45.26: delegate to the CANONICAL identity builder used by the regular
    photo pipeline, so «Наедине» renders the exact same figure as an ordinary
    photo. The old private copy drifted: it forced an exaggerated E-cup /
    round-hips body onto constructor characters whose chosen bust is small.
    """
    from services.photo_service import _character_identity_lock
    try:
        identity, _personal, _safety, _expression = _character_identity_lock(character_id)
    except Exception as exc:  # pragma: no cover — defensive, keep generation alive
        logger.warning('identity lock delegate failed for %s: %s', character_id, exc)
        return ''
    return identity

# V3.45.23: pose & camera variety — without it every generation lands on the
# same default standing/sitting pose (players noticed «одна и та же поза»).
PRIVATE_POSE_POOL = [
    'lying on her side, propped on one elbow, looking at the camera',
    'sitting on the edge of the bed, legs crossed, slight head tilt',
    'standing by the window, over-the-shoulder glance back at camera',
    'reclining against pillows, arms stretched above head',
    'sitting on the floor leaning against the wall, knees up',
    'standing in front of a mirror, phone POV selfie angle',
    'kneeling on the bed facing the camera, leaning slightly forward',
    'sitting in a chair, legs draped over one armrest',
    'lying on her back, shot from above at a slight angle',
    'standing arching her back, hands in hair, eyes on the camera',
    'perched on a windowsill, ankles crossed',
    'kneeling on the bed, turning to face the camera',
    # V3.59.3: self-touch poses (owner request) — hands on her own body.
    'gently cupping her breasts with both hands without pressing them, lips parted, eyes on the camera — natural slender female hands with five correct fingers each, both hands free (no phone in hand — tripod or mirror framing); her face stays clearly visible and turned to the camera, exactly the same face as reference image 1',
    'body turned three-quarters away, face turned back to the camera over her shoulder, one hand gripping her own bottom — natural slender female hands with five correct fingers each, both hands free (no phone in hand — tripod or mirror framing); her face stays clearly visible and turned to the camera, exactly the same face as reference image 1',
    'reclining propped on one elbow facing the camera, one hand on her breast, the other sliding down her stomach — natural slender female hands with five correct fingers each, both hands free (no phone in hand — tripod or mirror framing); her face stays clearly visible and turned to the camera, exactly the same face as reference image 1',
    'kneeling with her arms pushing her breasts together, leaning toward the camera — natural slender female hands with five correct fingers each, both hands free (no phone in hand — tripod or mirror framing); her face stays clearly visible and turned to the camera, exactly the same face as reference image 1',
    'standing side-on to a mirror, face to the camera, one hand resting on her own bottom — natural slender female hands with five correct fingers each, both hands free (no phone in hand — tripod or mirror framing); her face stays clearly visible and turned to the camera, exactly the same face as reference image 1',
    'sitting with legs apart on the bed, hands running up her inner thighs — natural slender female hands with five correct fingers each, both hands free (no phone in hand — tripod or mirror framing); her face stays clearly visible and turned to the camera, exactly the same face as reference image 1',
]

# V3.60.1: full-body and whole-room shots left her face a few dozen pixels
# wide at 1k — the model then invents a stranger's face. Every framing keeps
# the face large enough to carry her identity.
PRIVATE_CAMERA_POOL = [
    'three-quarter framing from the knees up, eye level, her face large and sharp',
    'waist-up framing at eye level, her face sharp and well lit',
    'slightly high angle from the thighs up, face turned to the camera',
    'mirror selfie framing from the thighs up, her face clearly visible in the mirror',
    'close medium shot from the hips up, soft light on her face',
]


def build_private_photo_prompt(
    request: PrivatePhotoRequest,
    character_description: str,
    use_reference: bool = True,
) -> str:
    """
    Строит промпт для SpicyAPI.
    
    Структура:
    [визуальная идентичность] + [категория] + [тип] + [обстановка] + [настроение]
    + [правило волос для косплея]

    V3.45.23: ``use_reference`` toggles the image-to-image REFERENCE PROTOCOL.
    Nude categories render via text-to-image, so they must not mention
    «Image 1 / Image 2»; the text visual-lock carries identity instead.
    """
    parts = []
    
    # V3.45.26: identity/body comes from the CANONICAL builder (same as the
    # regular photo pipeline). It already embeds the face-scoped REFERENCE
    # PROTOCOL and the BODY IDENTITY override, so no duplicate protocol here.
    visual_lock = _build_visual_identity_lock(request.character_id)
    if visual_lock:
        parts.append(visual_lock)
    else:
        parts.append(f"Subject: {character_description}")
    
    # Обстановка
    location = next((loc for loc in LOCATIONS if loc["id"] == request.location_id), None)
    if location and request.location_id != "random":
        parts.append(f"Location: {location['name_en']}")
    else:
        # V3.60.1: no location (the «Картинки» studio) or «random» used to leave
        # the model alone with a black backdrop — give her a real place.
        parts.append(f"Location: {random.choice(_REAL_PLACES)}, a lived-in real setting with depth and detail, never a plain black or empty backdrop")
    
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
            if type_data.get("prompt"):
                parts.append(f"SCENE: {type_data['prompt']}.")
        # V3.60.1: not always the same black lace — every lingerie/bra shot
        # draws its own cut (and colour, unless the player picked one).
        if request.category in ("lingerie", "suggestive") and request.type_id not in ("corset", "bodysuit", "fishnet", "coat", "shirt"):
            parts.append(f"BRA: {random.choice(BRA_CUT_POOL)}"
                         + ("" if request.color else f", in {random.choice(BRA_COLOR_POOL)}") + ".")
        # V3.45.23: explicit nudity directive — without it the model leaves her
        # clothed: the type names are only locations («On bed», «In shower»).
        if request.category == "fully_nude":
            parts.append(
                'OUTFIT: completely nude, naked, no clothing at all, bare breasts, '
                'nipples and genitals visible, no censorship, no blur.'
            )
        elif request.category == "nude_art":
            parts.append('OUTFIT: artistic nude, bare skin, elegant and tasteful composition.')
        # V3.45.26: player-picked colour for lingerie / apparel categories.
        if request.color and request.category in ("lingerie", "suggestive", "roleplay"):
            color_data = next((c for c in LINGERIE_COLORS if c["id"] == request.color), None)
            if color_data:
                parts.append(f"COLOR: her lingerie/outfit is {color_data['word']} — the whole set is this color.")
    
    # V3.45.23: random pose + camera so consecutive photos never repeat.
    parts.append(f"POSE: {random.choice(PRIVATE_POSE_POOL)}.")
    parts.append(f"CAMERA: {random.choice(PRIVATE_CAMERA_POOL)}.")
    
    # V3.60.8: «Наедине» never had an EXPRESSION line — only a weak «Mood: …»
    # (none at all for a random mood), so the girl came out stone-faced.
    from services.photo_expression_service import expression_description, shuffled_private_sensual_keys
    mood_faces = _MOOD_EXPRESSIONS.get(request.mood_id)
    face_key = random.choice(mood_faces) if mood_faces else shuffled_private_sensual_keys()[0]
    parts.append(expression_description(face_key, "she"))
    
    # V3.60.7: the bust size goes right before the face lock (the face keeps the very last line) — it used to jump between photos.
    from services.photo_service import bust_lock_line
    bust_lock = bust_lock_line(request.character_id)
    if bust_lock:
        parts.append(bust_lock)
    
    # Общие правила
    parts.append("High quality realistic smartphone-style photo, natural skin, detailed")
    if use_reference:
        # V3.60.1: last line wins the most attention — her face goes here, after
        # the outfit/pose/location text that used to drown it out.
        parts.append(
            "FACE LOCK: her face is clearly visible, sharp, well lit and turned toward the camera — "
            "exactly the same face as reference image 1 (same eyes, nose, lips, jaw, brows and skin tone); "
            "never closed eyes, never hidden by hair or hands, never a different woman."
        )
    # V3.45.24: only nude categories carry the uncensored-NSFW trailer. On a
    # clothed/suggestive shot that phrase trips fal.ai's safety checker when the
    # SpicyAPI i2i leg fails and we fall back with allow_adult=False — the whole
    # generation came back empty («одетая полностью не генерируется»).
    if request.category in ("fully_nude", "nude_art"):
        parts.append("NSFW content allowed, uncensored generation")
    elif request.category == "suggestive":
        parts.append("Clothed and non-explicit: her bra may show as described, no nudity")
    
    return "\n".join(parts)


# ─── SpicyAPI интеграция ───────────────────────────────────────────────────────
# NOTE: the real generation pipeline lives in ``generate_private_photo_real``
# below (task create → poll → download) — the old ``generate_private_photo``
# stub that only returned None has been removed (V3.45.27).

# V3.46.1: honour the configurable base (config.SPICYAPI_BASE_URL) instead of a
# hardcoded literal, so the endpoint can be corrected from Railway/env vars
# without a redeploy. Default keeps the previously-working …/api/v1 path.
SPICYAPI_TASK_BASE = SPICYAPI_BASE_URL


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
            # createTask answers 202 (accepted); recordInfo answers 200.
            if body.get("code") not in (200, 201, 202):
                raise RuntimeError(f'SpicyAPI error: {body.get("code")} {body.get("msg")} — full: {body}')
            return body.get("data", {})


# V3.58.1: circuit breaker. The owner's «Отказы» screen showed spicyapi
# 0 ✅ / 39 ❌ — every chat photo, date photo and studio render first waited up
# to SPICYAPI_IMAGE_TIMEOUT on a dead engine before falling back to fal. After
# SPICYAPI_BREAKER_FAILURES misses in a row the engine is skipped for
# SPICYAPI_BREAKER_COOLDOWN_SECONDS; one success closes the breaker again.
SPICYAPI_BREAKER_FAILURES = 3
SPICYAPI_BREAKER_COOLDOWN_SECONDS = 900
# Keyed per engine leg (model + edit/t2i): a broken reference-edit leg must not
# take the reference-free «Наедине» t2i leg down with it.
_spicy_fail_streak: Dict[str, int] = {}
# V3.58.2: the real reason of the last miss («Отказы» used to say only
# «empty_result», hiding a refused model id for weeks).
_spicy_last_error: str = ''
# V3.61.11: per-model enable_thinking value the provider currently accepts.
_spicy_thinking_override: Dict[str, bool] = {}


# V3.62.4: SpicyAPI started rejecting prompts over 5000 characters (HTTP 400
# «prompt: must be at most 5000 characters»), and every scene prompt runs
# ~8–10k, so all photos died. _fit_spicy_prompt shrinks a prompt to the cap:
# first it drops the least important lines, then cuts trailing sentences off
# the longest lines (identity and the adult lock last), then hard-truncates.
SPICYAPI_PROMPT_MAX = 4900
_SPICY_DROP_ORDER = (
    'Photorealistic smartphone', 'This should feel like', 'LIGHTING:',
    'SEASON/WEATHER:', 'PROGRESSION PACK', 'BUST CONSISTENCY:', 'OUTFIT FIT:',
    'STYLING DETAILS:', 'MOOD:', 'UNDER-CLOTHING REALISM:',
    'RELATIONSHIP VISUAL PROGRESSION:', 'TIME OF DAY:', 'MAKEUP:',
)
# Trim tiers: 0 = everything else, 1 = what the shot is, 2 = who she is.
_SPICY_TIERS = (
    ('SCENE:', 'WARDROBE:', 'CAMERA/POSE:', 'Create exactly ONE', 'Mainstream general-audience'),
    ('PHOTO IDENTITY:', 'HARD SUBJECT LOCK:'),
)


def _spicy_tier(line: str) -> int:
    for n, prefixes in enumerate(_SPICY_TIERS, 1):
        if line.startswith(prefixes):
            return n
    return 0
_SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+')


def _dedupe_sentences(line: str) -> str:
    seen: set = set()
    out = []
    for part in _SENTENCE_SPLIT.split(line):
        key = part.strip().rstrip('.;').lower()
        if key and key in seen:
            continue
        seen.add(key)
        out.append(part)
    return ' '.join(out)


def _fit_spicy_prompt(prompt: str, limit: int = SPICYAPI_PROMPT_MAX) -> str:
    if len(prompt) <= limit:
        return prompt
    lines = [_dedupe_sentences(l.strip()) for l in prompt.split('\n') if l.strip()]
    size = lambda: len('\n'.join(lines))
    for prefix in _SPICY_DROP_ORDER:
        if size() <= limit:
            break
        lines = [l for l in lines if not l.startswith(prefix)]
    for tier in range(len(_SPICY_TIERS) + 1):
        while size() > limit:
            pool = [i for i, l in enumerate(lines)
                    if _spicy_tier(l) == tier and len(_SENTENCE_SPLIT.split(l)) > 1]
            if not pool:
                break
            i = max(pool, key=lambda k: len(lines[k]))
            lines[i] = ' '.join(_SENTENCE_SPLIT.split(lines[i])[:-1])
    return '\n'.join(lines)[:limit]


def spicyapi_last_error() -> str:
    return _spicy_last_error or 'empty_result'


def _spicy_note_error(reason: str) -> None:
    global _spicy_last_error
    _spicy_last_error = str(reason)[:120]
_spicy_skip_until: Dict[str, float] = {}


def _spicy_leg(model: str, image_urls: Optional[List[str]]) -> str:
    return f"{model}:{'edit' if image_urls else 't2i'}"


def spicyapi_breaker_open(model: str, image_urls: Optional[List[str]]) -> bool:
    return asyncio.get_event_loop().time() < _spicy_skip_until.get(_spicy_leg(model, image_urls), 0.0)


def _spicyapi_note_result(leg: str, ok: bool) -> None:
    if ok:
        _spicy_fail_streak[leg] = 0
        return
    _spicy_fail_streak[leg] = _spicy_fail_streak.get(leg, 0) + 1
    if _spicy_fail_streak[leg] >= SPICYAPI_BREAKER_FAILURES:
        _spicy_skip_until[leg] = asyncio.get_event_loop().time() + SPICYAPI_BREAKER_COOLDOWN_SECONDS
        _spicy_fail_streak[leg] = 0
        logger.error('SpicyAPI breaker open for %s: %s misses in a row, skipping for %ss',
                     leg, SPICYAPI_BREAKER_FAILURES, SPICYAPI_BREAKER_COOLDOWN_SECONDS)


async def _spicyapi_render(model: str, prompt: str, image_urls: Optional[List[str]], scene: str = 'private', *,
                           return_url: bool = False, breaker: bool = True):
    """Breaker-guarded entry point; see ``_spicyapi_render_once`` for the flow.

    V3.61.12: ``breaker=False`` (a button the user pressed and waits on, like
    «Раздеть») neither skips on an open breaker nor counts toward it — one
    girl's refused edit must not block every other girl for 15 minutes."""
    if not breaker:
        return await _spicyapi_render_once(model, prompt, image_urls, scene, return_url=return_url)
    if spicyapi_breaker_open(model, image_urls):
        logger.info('SpicyAPI skipped (breaker open) scene=%s', scene)
        return (None, None) if return_url else None
    result = await _spicyapi_render_once(model, prompt, image_urls, scene, return_url=return_url)
    data = result[0] if return_url else result
    _spicyapi_note_result(_spicy_leg(model, image_urls), bool(data))
    return result


async def _spicyapi_render_once(model: str, prompt: str, image_urls: Optional[List[str]], scene: str = 'private', *, return_url: bool = False):
    """Shared SpicyAPI task flow: createTask → poll → download.

    ``image_urls`` empty/None → text-to-image; otherwise image-to-image edit.
    Returns image bytes or None on any failure (missing key, no taskId, task
    failed/expired, timeout, download error). Never raises — callers treat None
    as «this engine produced nothing».

    V3.56.0: once createTask returns a taskId the provider bills the job whether
    or not the image ever comes back, so the cost is ledgered on that event with
    the true success flag — the fix for intimate renders being invisible in
    /stats (the «картинки $0.080» blind spot).

    V3.56.3: ``return_url=True`` switches the result to a ``(bytes, url)`` pair —
    the provider's signed asset URL (valid ~20 min) lets the scene router chain
    frames so every next shot copies the figure of the previous one. Callers
    without the flag keep the old bytes-or-None contract untouched.
    """
    if not SPICYAPI_KEY:
        logger.error("SPICYAPI_KEY not configured")
        return (None, None) if return_url else None
    result: Optional[bytes] = None
    result_url: Optional[str] = None
    _spicy_note_error('')
    try:
        input_block: Dict[str, Any] = {
            "prompt": _fit_spicy_prompt(prompt),
            # V3.58.2: Seedream 5.0 Pro schema — an unknown field (the old
            # "size") is a 400, so only documented fields are sent.
            "aspect_ratio": "3:4",  # portrait
            "resolution": SPICYAPI_RESOLUTION,
            "output_format": "jpeg",
            "enable_thinking": SPICYAPI_ENABLE_THINKING,
        }
        if image_urls:
            input_block["image_urls"] = image_urls
        if _spicy_thinking_override.get(model) is not None:
            input_block["enable_thinking"] = _spicy_thinking_override[model]
        logger.info(f"SpicyAPI: creating task, model={model}, refs={len(image_urls) if image_urls else 0}")
        try:
            task_data = await _spicyapi_call(
                "POST", "/jobs/createTask",
                headers={"Idempotency-Key": str(uuid.uuid4())},
                json={"model": model, "input": input_block},
            )
        except RuntimeError as exc:
            # V3.61.11: the provider started refusing enable_thinking=false
            # («40004 cannot serve this parameter combination»). Flip the flag
            # once, remember the working value per model and go on.
            if 'enable_thinking' not in str(exc):
                raise
            flipped = not bool(input_block.get("enable_thinking"))
            logger.warning('SpicyAPI refused enable_thinking=%s for %s, retrying with %s',
                           input_block.get("enable_thinking"), model, flipped)
            input_block["enable_thinking"] = flipped
            task_data = await _spicyapi_call(
                "POST", "/jobs/createTask",
                headers={"Idempotency-Key": str(uuid.uuid4())},
                json={"model": model, "input": input_block},
            )
            _spicy_thinking_override[model] = flipped
        task_id = task_data.get("taskId")
        if not task_id:
            logger.error(f"No taskId in SpicyAPI response: {task_data}")
            _spicy_note_error('no_task_id')
            return (None, None) if return_url else None
        logger.info(f"SpicyAPI task: {task_id}")
        # Money is committed the moment the task is accepted — ledger it before
        # polling so a later timeout/failure still counts against the budget.
        deadline = asyncio.get_event_loop().time() + SPICYAPI_IMAGE_TIMEOUT
        # V3.56.5: the old backoff (2s start, ×1.5, 15s cap) slept up to 15s
        # AFTER the job was done — the owner's log lost ~13s to it. recordInfo
        # is free, so poll tight: detection latency ≤ 3s.
        wait = 1.0
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(wait)
            wait = min(wait * 1.25, 3.0)
            task_info = await _spicyapi_call("GET", f"/jobs/recordInfo?taskId={task_id}")
            state = task_info.get("state")
            if state == "succeeded":
                assets = task_info.get("output", {}).get("assets", [])
                asset_url = next((a["url"] for a in assets if a.get("url")), None)
                if asset_url:
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                        async with session.get(asset_url) as resp:
                            if resp.status == 200:
                                result = await resp.read()
                                if result is not None:
                                    result_url = asset_url
                break
            elif state in ("failed", "expired", "canceled"):
                logger.error(f"SpicyAPI task {state}: {task_info.get('errorMessage')}")
                _spicy_note_error(f"{state}: {task_info.get('errorCode') or task_info.get('errorMessage')}")
                break
        if result is None:
            logger.error(f"SpicyAPI no image (timeout or empty): {task_id}")
            if not _spicy_last_error.startswith(('failed', 'expired', 'canceled')):
                _spicy_note_error('timeout_or_empty')
    except Exception as e:
        logger.exception(f"SpicyAPI failed: {e}")
        _spicy_note_error(e)
    # A task that reached createTask is billed regardless of the outcome.
    spend_service.record_image_spend(
        'spicyapi', scene, SPICYAPI_ESTIMATED_COST_USD,
        billed=True, success=bool(result),
    )
    if return_url:
        return (result, result_url if result else None)
    return result


async def generate_private_photo_real(
    request: PrivatePhotoRequest,
    character_description: str,
    prompt: Optional[str] = None,
) -> Optional[bytes]:
    """
    Генерирует приватное фото через SpicyAPI Seedream 5.0 Lite edit (image-to-image).
    Возвращает bytes изображения или None при ошибке.

    V3.45.23: accepts a prebuilt ``prompt`` so the caller's random pose/camera
    matches the cache key (build_private_photo_prompt is non-deterministic).
    """
    if not SPICYAPI_KEY:
        logger.error("SPICYAPI_KEY not configured")
        return None

    if prompt is None:
        prompt = build_private_photo_prompt(request, character_description)
    logger.info(f"Private photo: category={request.category}, type={request.type_id}")

    # Build reference image URLs (public endpoint, no auth)
    # i=0 = face identity, i=1 = body/look silhouette
    ref_face_url = f"{PUBLIC_BASE_URL}/webapp/photo/{request.character_id}?i=0"
    ref_body_url = f"{PUBLIC_BASE_URL}/webapp/photo/{request.character_id}?i=1"
    return await _spicyapi_render(SPICYAPI_IMAGE_MODEL, prompt, [ref_face_url, ref_body_url], scene=str(request.category or 'private'))


async def generate_private_photo_t2i(prompt: str) -> Optional[bytes]:
    """V3.46.1: uncensored text-to-image for the nude «Наедине» categories.

    The fal Seedream t2i route is censored and will not return full nudity, and
    SpicyAPI image-to-image keeps a clothed reference clothed — so nude shots
    go through the UNCENSORED SpicyAPI engine with no reference (identity is
    carried by the text visual-lock). ``SPICYAPI_T2I_MODEL`` is env-overridable
    because the exact provider model id is account-specific.
    """
    return await _spicyapi_render(SPICYAPI_T2I_MODEL, prompt, None, scene='nude_t2i')


# ─── Вспомогательные функции ───────────────────────────────────────────────────

def get_category_cost(category: str) -> int:
    """V3.45.22: per-category peach cost (fully_nude = 4, others = 2)."""
    cat = PRIVATE_PHOTO_CATEGORIES.get(category, {})
    return cat.get('peach_cost', PRIVATE_PHOTO_PEACH_COST)


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


# V3.51.3: stockpile reuse threshold. Once a character has at least this many
# ready shots for the same scene (category + type), send a random one instead of
# paying the provider again — the owner's «зачем генерировать новые, если можно
# отправить готовое». Raise it (or set very high) to effectively disable reuse.
PRIVATE_POOL_MIN = 10


# V3.60.1: the stockpile still held renders from the 2k days (faces drifted)
# and served them at random, ignoring colour/location — only renders made
# after the 1k fix are reused. Railway PRIVATE_POOL_SINCE moves the cutoff.
PRIVATE_POOL_SINCE = os.getenv('PRIVATE_POOL_SINCE', '2026-10-14T00:00:00')


def pool_get(character_id: str, category: str, type_id: str,
             min_count: int = PRIVATE_POOL_MIN) -> Optional[bytes]:
    """Return a random already-generated photo for this character + scene when the
    shared cache stockpile (user_id=0 rows) holds at least ``min_count`` shots for
    it, so the caller can skip a fresh provider render. ``None`` -> generate.

    Matched on the stable category + type_id (pose) columns only; the volatile
    full-prompt hash (which carries the per-frame expression/pose rotation) almost
    never repeats, so the exact cache_get rarely hits — this reuses the stockpile
    that actually accumulates. Location/mood/colour nuance is not matched."""
    with SessionLocal() as session:
        stmt = select(PrivateGallery).where(
            PrivateGallery.user_id == 0,
            PrivateGallery.character_id == character_id,
            PrivateGallery.category == category,
            PrivateGallery.image_bytes.isnot(None),
        )
        try:
            stmt = stmt.where(PrivateGallery.created_at >= datetime.fromisoformat(PRIVATE_POOL_SINCE))
        except ValueError:
            pass
        if type_id:
            stmt = stmt.where(PrivateGallery.type_id == type_id)
        rows = session.execute(stmt).scalars().all()
    shots = [r.image_bytes for r in rows if r.image_bytes]
    if len(shots) < max(1, min_count):
        return None
    return random.choice(shots)


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
    """V3.56.0: the daily «Подарок от неё» photo is served ONLY from the owner's
    free media pool now. It used to render a fresh paid SpicyAPI image per
    recipient — up to 50/day fired at 12:00 UTC, ~$1.70 burned every single day
    and invisible in /stats because the gift path never ledgered or audited.
    An empty pool simply means no photo gift today; a proactive push never
    spends money. The gift date is only stamped once the photo actually lands."""
    uid = ensure_user(telegram_id)
    today = date.today()
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.id == uid))
        if not user:
            return False
        if user.last_daily_gift_date == today:
            return False
        # V3.56.7: the gift photo must be THE GIRL HE CHATS with — the pool is
        # per-character now, picked by the user's selected character.
        gift_char = user.selected_character or CHARACTER_ID
    from services import retention_features_service
    shot = retention_features_service.random_proactive_photo(gift_char)
    if not shot:
        return False  # no free pool image — skip, never pay for a push
    data, _ctype, _kind = shot
    from aiogram.types import BufferedInputFile
    await bot.send_photo(
        chat_id=telegram_id,
        photo=BufferedInputFile(data, filename='daily_gift.jpg'),
        caption='🎁 Я скучала... вот, держи 💋',
    )
    # V3.61.8: the gift also shows up in her chat inside the Mini App.
    try:
        from services.scheduler_service import _to_app_chat
        _to_app_chat(uid, telegram_id, gift_char, '🎁 Я скучала... вот, держи 💋', shot)
    except Exception:
        logger.exception('daily gift app-chat persist failed user=%s', telegram_id)
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.id == uid))
        if user:
            user.last_daily_gift_date = today
            session.commit()
    # V3.56.0: audit the gift into the admin feed (free pool, $0) so the owner
    # finally sees proactive sends next to the paid renders.
    try:
        from services import webapp_service
        webapp_service.record_generation(
            telegram_id, 'gift', gift_char, 'daily_gift', None,
            engine='pool', cost_usd=0.0,
        )
    except Exception:
        pass
    return True


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
