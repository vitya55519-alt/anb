"""V3.33.0: Telegram Mini App (WebApp) backend.

The storefront the owner benchmarked (@come_closer_bot) is a Telegram Mini
App — a web page opened from the bot's profile («Открыть приложение»).
This service powers ours on the SAME aiohttp app Railway already serves
(FreeKassa webhooks / healthz):

- ``validate_init_data`` — the official Telegram initData HMAC check
  (secret = HMAC("WebAppData", bot_token); hash = HMAC(secret, data_check_string));
- ``api_me`` — profile payload (premium, selected girl, relationship level, streak);
- ``api_characters`` — character cards for the storefront grid;
- ``api_shop`` — structured prices for the shop tab;
- ``api_legal`` — privacy policy / user agreement / tariffs / support texts,
  so the Platega-required documents are visible in the Mini App too;
- ``character_photo`` — canonical face PNGs (built-ins) / cached constructor
  avatars (custom personas), served as bytes without any Telegram API call.

The module deliberately does NOT import main.py (the handlers live there and
import this service — no circular imports).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path
from urllib.parse import parse_qsl

from sqlalchemy import select

from config import (
    CHARACTER_ID,
    CHAT_PHOTO_OFFER_STARS,
    CONSTRUCTOR_COST_RUB,
    CONSTRUCTOR_COST_STARS,
    CONSTRUCTOR_PRICE_USD,
    CUSTOM_PHOTO_COST_STARS,
    FREEKASSA_ENABLED,
    FREEKASSA_PREMIUM_PRICE_RUB,
    FREEKASSA_PREMIUM_PRICE_USD,
    FREEKASSA_PREMIUM_WEEKLY_PRICE_RUB,
    FREE_MESSAGES_PER_DAY,
    FREE_PHOTOS_LEVEL_1_2,
    FREE_PHOTOS_LEVEL_3_6,
    GALLERY_DOWNLOAD_STARS,
    PHOTO_COST_STARS,
    PREMIUM_MONTHLY_PHOTO_CREDITS,
    PREMIUM_MONTHLY_STARS,
    PREMIUM_WEEKLY_PHOTO_CREDITS,
    PREMIUM_WEEKLY_PRICE_USD,
    PREMIUM_WEEKLY_STARS,
    QUEST_REPLAY_STARS,
    TELEGRAM_TOKEN,
    VIDEO_COST_STARS,
    VIDEO_PREMIUM_FREE_DAILY,
    fiat_values,
)
from models.app_models import User
from services import legal_service
from services.access_service import is_premium
from services.character_card_service import get_card, list_cards
from services.custom_character_service import (
    CONSTRUCTOR_STEPS, OPTION_LABELS_EN, STEP_TITLES_EN,
    custom_character_id, is_custom_character,
)
from services.db import SessionLocal
from services.ui_lang import EN, user_lang

ROOT = Path(__file__).resolve().parents[1]
WEBAPP_INDEX = ROOT / 'webapp' / 'index.html'

# Canonical face references used for storefront photos (no network needed).
_FACE_REFERENCES = {
    CHARACTER_ID: ('references', 'anna', '00_anna_canonical_face_v3.png'),
    'alena_01': ('references', 'emily', '00_emily_canonical_face.png'),
    'maria_01': ('references', 'maria', '00_maria_canonical_face.png'),
}


def validate_init_data(init_data: str, bot_token: str | None = None, max_age_seconds: int = 86400) -> dict | None:
    """Verify Telegram WebApp initData; return its fields, or None if invalid.

    Per the official spec: data_check_string is every field except ``hash``,
    sorted alphabetically, joined with newlines; secret key is
    HMAC-SHA256(key="WebAppData", msg=bot_token).
    """
    token = bot_token or TELEGRAM_TOKEN
    if not init_data or not token:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None
    received_hash = pairs.pop('hash', '')
    if not received_hash:
        return None
    check_string = '\n'.join(f'{k}={v}' for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    calculated = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received_hash):
        return None
    try:
        auth_age = time.time() - int(pairs.get('auth_date', '0') or 0)
    except ValueError:
        return None
    if max_age_seconds and auth_age > max_age_seconds:
        return None
    return pairs


def init_data_user(pairs: dict) -> dict:
    """The ``user`` JSON object from validated initData ({} if absent)."""
    try:
        return json.loads(pairs.get('user', '{}')) or {}
    except (TypeError, ValueError):
        return {}


def _user_row(telegram_id: int) -> User | None:
    with SessionLocal() as session:
        return session.scalar(select(User).where(User.telegram_id == str(telegram_id)))


def api_me(telegram_id: int) -> dict:
    """Profile tab payload — mirrors what the bot already knows about the user."""
    lang = user_lang(telegram_id)
    user = _user_row(telegram_id)
    selected_character = (user.selected_character or CHARACTER_ID) if user else CHARACTER_ID
    level = 1
    try:
        from services.photo_service import get_relationship_level
        level = get_relationship_level(telegram_id, selected_character)
    except Exception:
        pass
    card = get_card(selected_character)
    return {
        'id': telegram_id,
        'name': (user.name or '') if user else '',
        'lang': lang,
        'premium': is_premium(telegram_id),
        'streak': (user.streak_count or 0) if user else 0,
        'photo_credits': (user.photo_credits or 0) if user else 0,
        'selected_character': {
            'id': selected_character,
            'name': (card.display_name if card else selected_character),
            'level': level,
        },
    }


def api_characters(telegram_id: int | None = None) -> list[dict]:
    """Storefront grid: every visible card plus its storefront photo URL.

    V3.35.0: constructor personas are public — they were always registered as
    visible ``active`` cards, and now the grid also marks which cards are
    user-made (``custom``) and which one is the caller's own creation
    (``mine``), so the app can offer «create your own» and chat entry.
    """
    selected = None
    if telegram_id:
        user = _user_row(telegram_id)
        selected = (user.selected_character or CHARACTER_ID) if user else None
    out = []
    for card in list_cards(visible_only=True):
        custom = is_custom_character(card.character_id)
        out.append({
            'id': card.character_id,
            'name': card.display_name,
            'age': card.age,
            'bio': card.short_bio or '',
            'status': card.status,
            'emoji': card.button_emoji or '👩',
            'photo': f"/webapp/photo/{card.character_id}",
            'selected': card.character_id == selected,
            'custom': custom,
            'mine': custom and bool(telegram_id) and card.character_id == custom_character_id(telegram_id),
        })
    return out


def api_invoice_products(lang: str = 'ru') -> list[dict]:
    """Products the Mini App sells directly with Stars (V3.34.0).

    ``payload`` is the exact string the bot's ``pre_checkout_query`` /
    ``successful_payment`` handlers already validate, so a payment started
    from the app lands in the very same granting code path as a chat payment:

    - ``premium_month`` — handled since forever: +30 days Premium, +12 credits;
    - ``premium_week`` — V3.34.1 addition: +7 days Premium, +3 credits;
    - ``photo_pack`` — V3.34.0 addition: a standalone +1 photo credit.
    """
    en = lang == EN
    # V3.36.0: every Stars price carries its rub + dollar equivalent so the
    # storefront can show all three tiers next to each other.
    photo_rub, photo_usd = fiat_values(PHOTO_COST_STARS)
    return [
        {
            'id': 'premium',
            'emoji': '⭐',
            'title': 'Premium · 30 дней' if not en else 'Premium · 30 days',
            'description': (
                '30 дней Premium: 12 фото-кредитов, 2 видео-оживления в день, все персонажи и кружочки'
                if not en else
                '30 days of Premium: 12 photo credits, 2 photo animations daily, all characters and video circles'
            ),
            'stars': PREMIUM_MONTHLY_STARS,
            'payload': 'premium_month',
            'rub': FREEKASSA_PREMIUM_PRICE_RUB if FREEKASSA_ENABLED else None,
            'usd': FREEKASSA_PREMIUM_PRICE_USD,
        },
        {
            'id': 'premium_week',
            'emoji': '⭐',
            'title': 'Premium · 7 дней' if not en else 'Premium · 7 days',
            'description': (
                f'7 дней Premium: {PREMIUM_WEEKLY_PHOTO_CREDITS} фото-кредита, 2 видео-оживления в день, все персонажи и кружочки'
                if not en else
                f'7 days of Premium: {PREMIUM_WEEKLY_PHOTO_CREDITS} photo credits, 2 photo animations daily, all characters and video circles'
            ),
            'stars': PREMIUM_WEEKLY_STARS,
            'payload': 'premium_week',
            'rub': FREEKASSA_PREMIUM_WEEKLY_PRICE_RUB if FREEKASSA_ENABLED else None,
            'usd': PREMIUM_WEEKLY_PRICE_USD,
        },
        {
            'id': 'photo_credit',
            'emoji': '📸',
            'title': '+1 фото-кредит' if not en else '+1 photo credit',
            'description': (
                'Один сет фото на заказ — кредит списывается, когда попросишь фото в чате'
                if not en else
                'One photo set on demand — the credit is used when you ask for a photo in chat'
            ),
            'stars': PHOTO_COST_STARS,
            'payload': 'photo_pack',
            'rub': photo_rub,
            'usd': photo_usd,
        },
    ]


def api_shop(lang: str = 'ru') -> dict:
    """Structured prices for the shop tab (same constants the bot charges)."""
    en = lang == EN
    features = [
        ('📸', '12 фото-кредитов каждый месяц', '12 photo credits every month'),
        ('🎬', '2 бесплатных видео-оживления в день', '2 free photo animations per day'),
        ('🎯', 'перезапуски историй и все персонажи', 'story replays and all characters'),
        ('💌', 'расширенные лимиты общения и память', 'wider chat limits and memory'),
        ('🎙', 'голосовые ответы и кружочки', 'voice replies and video circles'),
    ]
    items = [
        ('📸', 'Сет фото' if not en else 'Photo set', PHOTO_COST_STARS, None, None),
        ('✨', 'Фото по сценарию из чата' if not en else 'Chat-scenario photo', CHAT_PHOTO_OFFER_STARS, None, None),
        ('🎨', 'Кастомное фото' if not en else 'Custom photo', CUSTOM_PHOTO_COST_STARS, None, None),
        ('🎬', 'Оживление фото' if not en else 'Photo animation', VIDEO_COST_STARS, None, None),
        ('🖼', 'Скачивание из галереи' if not en else 'Gallery download', GALLERY_DOWNLOAD_STARS, None, None),
        ('🎯', 'Другая ветка истории' if not en else 'Story branch replay', QUEST_REPLAY_STARS, None, None),
        # the constructor has REAL card prices — the ladder would lie about them
        ('👩', 'Создание персонажа' if not en else 'Character creation', CONSTRUCTOR_COST_STARS,
         CONSTRUCTOR_COST_RUB if FREEKASSA_ENABLED else None, CONSTRUCTOR_PRICE_USD),
    ]
    return {
        'premium': {
            'stars': PREMIUM_MONTHLY_STARS,
            'rub': FREEKASSA_PREMIUM_PRICE_RUB if FREEKASSA_ENABLED else None,
            'usd': FREEKASSA_PREMIUM_PRICE_USD,
            'photo_credits': PREMIUM_MONTHLY_PHOTO_CREDITS,
            'free_videos_daily': VIDEO_PREMIUM_FREE_DAILY,
            'features': [
                {'emoji': e, 'ru': ru, 'en': en_text} for e, ru, en_text in features
            ],
        },
        'free_tier': {
            'messages_per_day': FREE_MESSAGES_PER_DAY,
            'photos_level_1_2': FREE_PHOTOS_LEVEL_1_2,
            'photos_level_3_6': FREE_PHOTOS_LEVEL_3_6,
        },
        # V3.36.0: each item carries the rub + dollar equivalent of its Stars
        # price (the same ladder the bot shows next to its buttons); explicit
        # per-item fiat (the constructor) wins over the ladder.
        'items': [
            {'emoji': e, 'name': n, 'stars': s,
             'rub': rub if rub is not None else fiat_values(s)[0],
             'usd': usd if usd is not None else fiat_values(s)[1]}
            for e, n, s, rub, usd in items
        ],
        'constructor_rub': CONSTRUCTOR_COST_RUB if FREEKASSA_ENABLED else None,
        'constructor_usd': CONSTRUCTOR_PRICE_USD,
        # V3.34.0: what the Mini App can sell right now (Stars invoices via
        # tg.openInvoice) — the rest of the price list stays informational.
        'purchases': api_invoice_products(lang),
    }


def api_constructor_steps(lang: str = 'ru') -> list[dict]:
    """V3.35.0: the app wizard's steps — the same CONSTRUCTOR_STEPS the bot's
    inline constructor walks, labeled per language."""
    en = lang == EN
    out = []
    for step in CONSTRUCTOR_STEPS:
        title = STEP_TITLES_EN.get(step['key'], step['title']) if en else step['title']
        options = [
            {'value': value, 'label': (OPTION_LABELS_EN.get(value, label) if en else label)}
            for value, label, _ in step['options']
        ]
        out.append({'key': step['key'], 'title': title, 'options': options})
    return out


def api_chat_history(db_user_id: int, character_id: str, limit: int = 30) -> list[dict]:
    """V3.35.0: recent dialog rows for the Mini App chat view (oldest first).

    Same ``messages`` table the bot chat writes to — the app and the bot share
    one continuous dialog per (user, character).
    """
    limit = max(1, min(60, int(limit or 30)))
    try:
        from services.memory_service import get_recent_messages
        rows = get_recent_messages(db_user_id, character_id, limit)
    except Exception:
        return []
    out = []
    for m in rows:
        try:
            ts = m.created_at.isoformat() if m.created_at else None
        except Exception:
            ts = None
        out.append({'role': m.role, 'content': m.content, 'ts': ts})
    return out


def api_legal(lang: str = 'ru') -> dict:
    """Documents tab payload — the Platega-required docs, visible in the app too."""
    return {
        'date': legal_service.LEGAL_DATE_SHORT,
        'check_word': legal_service.LEGAL_CHECK_WORD,
        'privacy': legal_service.PRIVACY_POLICY,
        'agreement': legal_service.USER_AGREEMENT,
        'tariffs': legal_service.tariffs_text(lang),
        'support': legal_service.support_text(lang),
    }


def character_photo(character_id: str) -> tuple[bytes, str] | None:
    """(bytes, content_type) of a storefront photo, or None if unavailable.

    Built-ins read their canonical face reference; constructor personas read
    the cached avatar (v3.31.8 ``ensure_custom_avatar_cached``).
    """
    base = ROOT / 'data'
    path: Path | None = None
    if is_custom_character(character_id):
        path = base / 'custom_references' / character_id / 'avatar.jpg'
    else:
        rel = _FACE_REFERENCES.get(character_id)
        if rel:
            path = base.joinpath(*rel)
    if path and path.exists():
        content_type = 'image/jpeg' if path.suffix.lower() in ('.jpg', '.jpeg') else 'image/png'
        try:
            return path.read_bytes(), content_type
        except OSError:
            return None
    return None
