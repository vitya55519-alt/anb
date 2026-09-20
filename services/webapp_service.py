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
import logging
import re
import secrets
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
    PEACH_PACK_10_STARS,
    PEACH_PACK_30_STARS,
    PEACH_PACK_100_STARS,
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
    WALLET_PAY_ENABLED,
    WEBAPP_INIT_DATA_MAX_AGE,
    fiat_values,
)
from models.app_models import CharacterComment, CharacterLike, CharacterStat, DailyBonus, Message, NotificationPref, SimulatedMessage, User
from services import legal_service
from services.access_service import is_premium
from services.character_card_service import get_card, get_scenario_hook, list_cards
from services.custom_character_service import (
    CONSTRUCTOR_STEPS, OPTION_LABELS_EN, STEP_TITLES_EN,
    custom_character_id, is_custom_character,
)
from services.db import SessionLocal
from services.ui_lang import EN, user_lang

ROOT = Path(__file__).resolve().parents[1]
WEBAPP_INDEX = ROOT / 'webapp' / 'index.html'

logger = logging.getLogger(__name__)

# V3.38.0: user-generated pictures from the «Картинки» studio tab live
# outside the character system — one folder per user, meta.json index.
APP_PICTURES_DIR = ROOT / 'data' / 'app_pictures'

# One freeform picture costs one photo credit (🍑) — the same balance the bot
# charges for a photo set, so shop purchases feed both chat photos and the
# studio.
WEBAPP_PICTURE_COST_CREDITS = 150

# The studio is a public, fully-clothed surface. Prompts that point at minors
# or coercion are rejected before any engine call; every prompt additionally
# gets the SFW constraint appended so the output stays within the same
# boundaries as the rest of the product.
_PICTURE_BLOCKED_RE = re.compile(
    r'(child|children|kid|kids|teen|teenager|minor|underage|loli|shota|'
    r'школьниц|школьник|школяр|реб[её]н|детск|девочк|мальчик|несовершеннолетн|подрост|'
    r'rape|raped|изнасил|насили|принуд|non.?consensual)',
    re.IGNORECASE,
)
PICTURE_PROMPT_SUFFIX = (
    ', fully clothed, elegant outfit, safe for work, no nudity, '
    'high quality, detailed, cinematic lighting'
)
PICTURE_PROMPT_MAX_LEN = 800
PICTURE_PROMPT_MIN_LEN = 4

# Studio selectors — the user-facing «Стиль»/«Формат» dropdowns only prepend /
# append neutral composition words; the SFW constraint is mandatory.
PICTURE_STYLE_PREFIXES = {
    'anime': 'anime style illustration, vibrant colors, ',
    'realistic': 'photorealistic photo, natural lighting, ',
    'fantasy': 'fantasy digital art, ',
}
PICTURE_FORMAT_SUFFIXES = {
    'square': ', square 1:1 composition',
    'portrait': ', vertical portrait 2:3 composition',
}


def picture_prompt_allowed(prompt: str) -> bool:
    """V3.38.0: hard reject for the studio — minors/coercion never reach an engine."""
    return not _PICTURE_BLOCKED_RE.search(prompt or '')


def picture_final_prompt(prompt: str, style: str = 'anime', fmt: str = 'square') -> str:
    """User text + the chosen style/format + the standing SFW constraint."""
    base = (prompt or '').strip()[:PICTURE_PROMPT_MAX_LEN]
    prefix = PICTURE_STYLE_PREFIXES.get(style, PICTURE_STYLE_PREFIXES['anime'])
    suffix = PICTURE_FORMAT_SUFFIXES.get(fmt, PICTURE_FORMAT_SUFFIXES['square'])
    return prefix + base + suffix + PICTURE_PROMPT_SUFFIX

# Canonical face references used for storefront photos (no network needed).
_FACE_REFERENCES = {
    CHARACTER_ID: ('references', 'anna', '00_anna_canonical_face_v3.png'),
    'alena_01': ('references', 'emily', '00_emily_canonical_face.png'),
    'maria_01': ('references', 'maria', '00_maria_canonical_face.png'),
    # V3.38.0: the Come Closer character pack storefront portraits.
    'erika_01': ('references', 'erika', '00_erika_canonical_face.png'),
    'sonya_01': ('references', 'sonya', '00_sonya_canonical_face.png'),
    'vika_01': ('references', 'vika', '00_vika_canonical_face.png'),
    'alisa_01': ('references', 'alisa', '00_alisa_canonical_face.png'),
    'mila_01': ('references', 'mila', '00_mila_canonical_face.png'),
    # V3.44.0: new archetypes — fitness, artistic, and power.
    'kate_01': ('references', 'kate', '00_kate_canonical_face.png'),
    'luna_01': ('references', 'luna', '00_luna_canonical_face.png'),
    'rex_01': ('references', 'rex', '00_rex_canonical_face.png'),
}


def validate_init_data(init_data: str, bot_token: str | None = None, max_age_seconds: int | None = None) -> dict | None:
    """Verify Telegram WebApp initData; return its fields, or None if invalid.

    Per the official spec: data_check_string is every field except ``hash``,
    sorted alphabetically, joined with newlines; secret key is
    HMAC-SHA256(key="WebAppData", msg=bot_token).
    V3.43.0: the age window comes from config (7 days) — the strict 24h
    default locked users out when the client reopened the Mini App from its
    recents list with the previous initData.
    """
    token = bot_token or TELEGRAM_TOKEN
    if max_age_seconds is None:
        max_age_seconds = WEBAPP_INIT_DATA_MAX_AGE
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
        # V3.43.5: the in-app Settings toggle shows the live flag (Premium is
        # already in this payload — enabling re-checks it server-side).
        'spicy_mode': bool(getattr(user, 'spicy_mode', False)) if user else False,
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
    V3.43.9: includes relationship level per character for the progress bar.
    """
    selected = None
    if telegram_id:
        user = _user_row(telegram_id)
        selected = (user.selected_character or CHARACTER_ID) if user else None
    views = character_views_map()
    # V3.43.9: pre-load relationship levels for all characters at once.
    rel_levels: dict[str, int] = {}
    if telegram_id:
        try:
            from services.photo_service import get_relationship_level
            for card in list_cards(visible_only=True):
                rel_levels[card.character_id] = get_relationship_level(telegram_id, card.character_id)
        except Exception:
            pass
    out = []
    for card in list_cards(visible_only=True):
        custom = is_custom_character(card.character_id)
        # V3.43.2: cache-buster so a re-rendered tile reaches the grid at
        # once instead of sitting in the WebView cache for an hour.
        ver = asset_version(card.character_id)
        # V3.43.3: the admin-uploaded storefront media (photo/gif/mp4).
        ov = character_card_override(card.character_id)
        ov_ext = ov.suffix.lower() if ov else ''
        out.append({
            'id': card.character_id,
            'name': card.display_name,
            'age': card.age,
            'bio': card.short_bio or '',
            # V3.38.0: the Come Closer story-hook line under the name ("мать
            # твоего друга", "подруга детства приехала в твой город").
            'hook': get_scenario_hook(card.character_id) or '',
            'status': card.status,
            'emoji': card.button_emoji or '',
            'photo': f"/webapp/photo/{card.character_id}?v={ver}",
            # V3.43.3: the grid card is a PLAIN static photo (owner: «сделай
            # просто фото») — the look shot, not the Ken-Burns webp anymore.
            # An admin-uploaded override wins: jpg/png/webp/gif ride <img>
            # (animated formats loop by themselves), mp4 rides <video>.
            'card': (f'/webapp/card/{card.character_id}?v={ver}'
                     if ov_ext in ('.jpg', '.png', '.webp', '.gif')
                     else f"/webapp/photo/{card.character_id}?i=1&v={ver}"),
            'live': (f'/webapp/card/{card.character_id}?v={ver}'
                     if ov_ext == '.mp4' else None),
            # V3.40.0: the « 427k» view badge on the card corner.
            'views': views.get(card.character_id, 0),
            # V3.39.0: the Come Closer character page opens with a photo strip
            # (face + look references), so the card page needs every shot.
            'gallery': [
                f'/webapp/photo/{card.character_id}?i={idx}&v={ver}'
                for idx in range(min(4, len(character_gallery(card.character_id))))
            ],
            'selected': card.character_id == selected,
            'custom': custom,
            'mine': custom and bool(telegram_id) and card.character_id == custom_character_id(telegram_id),
            # V3.43.9: relationship level (0-8) for the progress bar.
            'level': rel_levels.get(card.character_id, 0),
        })
    return out


def api_invoice_products(lang: str = 'ru') -> list[dict]:
    """Products the Mini App sells directly with Stars (V3.34.0).

    ``payload`` is the exact string the bot's ``pre_checkout_query`` /
    ``successful_payment`` handlers already validate, so a payment started
    from the app lands in the very same granting code path as a chat payment:

    - ``premium_month`` — handled since forever: +30 days Premium, +12 credits;
    - ``premium_week`` — V3.34.1 addition: +7 days Premium, +3 credits;
    - ``peach_pack_*`` — V3.43.1: the peach pack ladder (10/30/100 credits)
      that replaced the standalone +1 photo credit square.
    """
    en = lang == EN
    # V3.36.0: every Stars price carries its rub + dollar equivalent so the
    # storefront can show all three tiers next to each other.
    p10_rub, p10_usd = fiat_values(PEACH_PACK_10_STARS)
    p30_rub, p30_usd = fiat_values(PEACH_PACK_30_STARS)
    p100_rub, p100_usd = fiat_values(PEACH_PACK_100_STARS)
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
            'id': 'peach_pack_10',
            'emoji': '🍑',
            'title': '10 персиков' if not en else '10 peaches',
            'description': (
                '10 фото-кредитов разом — хватит на 10 сетов фото по запросу'
                if not en else
                '10 photo credits at once — enough for 10 on-demand photo sets'
            ),
            'stars': PEACH_PACK_10_STARS,
            'payload': 'peach_pack_10',
            'rub': p10_rub,
            'usd': p10_usd,
        },
        {
            'id': 'peach_pack_30',
            'emoji': '🍑',
            'title': '30 персиков' if not en else '30 peaches',
            'description': (
                '30 фото-кредитов со скидкой 10% — кредит дешевле одиночного'
                if not en else
                '30 photo credits with a 10% discount — each credit costs less'
            ),
            'stars': PEACH_PACK_30_STARS,
            'payload': 'peach_pack_30',
            'rub': p30_rub,
            'usd': p30_usd,
            'badge': '−10%',
        },
        {
            'id': 'peach_pack_100',
            'emoji': '🍑',
            'title': '100 персиков' if not en else '100 peaches',
            'description': (
                '100 фото-кредитов со скидкой 25% — самый выгодный пак'
                if not en else
                '100 photo credits with a 25% discount — the best value pack'
            ),
            'stars': PEACH_PACK_100_STARS,
            'payload': 'peach_pack_100',
            'rub': p100_rub,
            'usd': p100_usd,
            'badge': '−25%',
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
        # V3.43.0: the pay-method modal only offers rows the backend can sell —
        # FreeKassa (card/SBP) and Wallet Pay (crypto) are env-gated.
        'freekassa': FREEKASSA_ENABLED,
        'wallet_pay': WALLET_PAY_ENABLED,
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
        out.append({'role': m.role, 'content': m.content, 'ts': ts,
                    # V3.39.0: media messages (photo / circle / voice) travel
                    # with the history so the app renders them like the bot.
                    'media_kind': getattr(m, 'media_kind', None),
                    'media_url': getattr(m, 'media_url', None)})
    return out


def api_chat_list(db_user_id: int, telegram_id: int | None = None) -> list[dict]:
    """V3.38.0: the «Чаты» tab — one row per character the user has any
    messages with, newest activity first, carrying the storefront card data
    (photo, status) so a tap can open the shared in-app chat view."""
    try:
        with SessionLocal() as session:
            rows = session.scalars(
                select(Message)
                .where(Message.user_id == int(db_user_id))
                .order_by(Message.created_at.desc())
                .limit(400)
            ).all()
    except Exception:
        return []
    seen: dict[str, Message] = {}
    for m in rows:
        if m.character_id not in seen:
            seen[m.character_id] = m
    out = []
    for character_id, last in seen.items():
        card = get_card(character_id)
        custom = is_custom_character(character_id)
        try:
            ts = last.created_at.isoformat() if last.created_at else None
        except Exception:
            ts = None
        out.append({
            'id': character_id,
            'name': card.display_name if card else (character_id if not custom else '—'),
            'photo': f"/webapp/photo/{character_id}?v={asset_version(character_id)}",
            'emoji': (card.button_emoji if card else None) or '👩',
            'status': card.status if card else ('active' if custom else 'soon'),
            'custom': custom,
            'mine': custom and bool(telegram_id) and character_id == custom_character_id(telegram_id),
            'selected': False,
            'last_message': (last.content or '')[:140],
            'last_role': last.role,
            'last_ts': ts,
        })
    return out[:50]


# ── V3.38.0: «Картинки» studio persistence ────────────────────────────────

def _picture_folder(telegram_id: int) -> Path:
    return APP_PICTURES_DIR / str(int(telegram_id))


def save_picture(telegram_id: int, filename: str, prompt: str) -> None:
    """Append the new picture to the user's meta.json index (newest last)."""
    folder = _picture_folder(telegram_id)
    folder.mkdir(parents=True, exist_ok=True)
    meta = folder / 'meta.json'
    try:
        items = json.loads(meta.read_text(encoding='utf-8')) if meta.exists() else []
        if not isinstance(items, list):
            items = []
    except Exception:
        items = []
    items.append({'file': filename, 'prompt': (prompt or '')[:300], 'ts': time.time()})
    items = items[-100:]
    meta.write_text(json.dumps(items, ensure_ascii=False), encoding='utf-8')


def api_picture_list(telegram_id: int) -> list[dict]:
    """Newest-first gallery of the user's studio pictures."""
    meta = _picture_folder(telegram_id) / 'meta.json'
    if not meta.exists():
        return []
    try:
        items = json.loads(meta.read_text(encoding='utf-8'))
        if not isinstance(items, list):
            return []
    except Exception:
        return []
    out = []
    for item in reversed(items[-30:]):
        if not isinstance(item, dict) or not item.get('file'):
            continue
        out.append({
            'file': f"/webapp/picture/{item['file']}",
            'prompt': item.get('prompt', ''),
            'ts': item.get('ts'),
        })
    return out


def picture_file_path(telegram_id: int, filename: str) -> Path | None:
    """Resolve a gallery image for serving; None unless it belongs to the user.

    Filenames are server-generated (<unix_ms>_<hex>.jpg), so a caller can
    only ever reference pictures they already received from the API.
    """
    safe_name = Path(str(filename)).name
    if not re.fullmatch(r'\d+_[0-9a-f]{8,}\.(jpg|jpeg|png|webp)', safe_name):
        return None
    path = _picture_folder(telegram_id) / safe_name
    return path if path.exists() else None


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


def api_partner(user_id: int, telegram_id: int) -> dict:
    """V3.37.0: the «Партнёрка» tab payload — live stats, the personal link
    and the FAQ copy, all in the caller's interface language."""
    from services import partner_service
    from config import PARTNER_MIN_PAYOUT_RUB, PARTNER_PAYOUT_METHODS, REFERRAL_COMMISSION_PCT
    lang = user_lang(telegram_id)
    en = lang == EN
    stats = partner_service.partner_stats(user_id)
    pct = int(REFERRAL_COMMISSION_PCT) if float(REFERRAL_COMMISSION_PCT).is_integer() else REFERRAL_COMMISSION_PCT
    faq = [
        {
            'q': 'What is it?' if en else 'Что это такое?',
            'a': (f'The affiliate program: you earn {pct}% of every purchase your invited friends make. '
                  'It runs forever — commission lands with each of their purchases, permanently.') if en else
                 (f'Партнёрская программа: ты получаешь {pct}% от всех покупок приглашённых тобой друзей. '
                  'Это бессрочная программа — комиссия капает с каждой их покупки навсегда.'),
        },
        {
            'q': 'How does it work?' if en else 'Как это работает?',
            'a': ('1. Share your link below. 2. Your friend opens it, starts the bot and buys something. '
                  f'3. You automatically get {pct}% of every purchase they make — premium, photos, video, everything.') if en else
                 ('1. Поделись своей ссылкой ниже. 2. Друг переходит, запускает бота и что-то покупает. '
                  f'3. Тебе автоматически капает {pct}% от каждой его покупки — с премиума, фото, видео, всего.'),
        },
        {
            'q': 'How do I get paid?' if en else 'Как мне вывести деньги?',
            'a': (f'Reach {PARTNER_MIN_PAYOUT_RUB} ₽ and tap «Withdraw». Payouts go to {PARTNER_PAYOUT_METHODS}. '
                  'The owner confirms manually, usually within a day.') if en else
                 (f'Набери {PARTNER_MIN_PAYOUT_RUB} ₽ и нажми «Вывести деньги». Выплата — на {PARTNER_PAYOUT_METHODS}. '
                  'Владелец подтверждает вручную, обычно в течение суток.'),
        },
        {
            'q': 'Is the payout one-time?' if en else 'Выплата разовая?',
            'a': (f'No! This is not a one-time reward — it is a permanent passive income: {pct}% of every '
                  'purchase your referrals make, forever.') if en else
                 (f'Нет! Это не разовая выплата, а постоянный пассивный доход: {pct}% с каждой покупки '
                  'твоих рефералов капают всегда.'),
        },
        {
            'q': 'More questions' if en else 'У меня остались вопросы',
            'a': ('Write /support right in the bot — the message reaches the owner and he replies '
                  'personally.') if en else
                 ('Напиши /support прямо в боте — сообщение попадёт владельцу, он ответит лично.'),
        },
    ]
    return {
        'enabled': True,
        'pct': pct,
        'invited': stats['invited'],
        'earned_rub': stats['earned_rub'],
        'balance_rub': stats['balance_rub'],
        'pending_payout': bool(stats['pending_payout_id']),
        'min_payout_rub': PARTNER_MIN_PAYOUT_RUB,
        'payout_methods': PARTNER_PAYOUT_METHODS,
        'link': None,  # filled by the caller — only the bot knows its username
        'faq': faq,
    }


_GALLERY_CACHE: dict[str, list[Path]] = {}


def character_gallery(character_id: str) -> list[Path]:
    """V3.39.0: the canonical shots of a character (face first, then look).

    The Come Closer character page leads with a horizontal photo strip, so the
    storefront needs every canonical reference, not just the face.
    V3.43.9: cached to avoid repeated glob() calls on every page load.
    """
    if character_id in _GALLERY_CACHE:
        return _GALLERY_CACHE[character_id]
    base = ROOT / 'data'
    if is_custom_character(character_id):
        path = base / 'custom_references' / character_id / 'avatar.jpg'
        result = [path] if path.exists() else []
        _GALLERY_CACHE[character_id] = result
        return result
    rel = _FACE_REFERENCES.get(character_id)
    if not rel:
        _GALLERY_CACHE[character_id] = []
        return []
    folder = base.joinpath(rel[0], rel[1])
    if not folder.exists():
        _GALLERY_CACHE[character_id] = []
        return []
    result = sorted(p for p in folder.glob('*.png') if p.name.startswith(('00_', '01_', '02_', '03_', '04_', '05_')))
    _GALLERY_CACHE[character_id] = result
    return result


def character_card_gif(character_id: str) -> Path | None:
    """V3.40.0: the looping animated tile of a built-in heroine, or None.

    The owner benchmarked Come Closer's living storefront cards; our answer
    is a pre-rendered Ken-Burns loop per heroine (``card_preview.webp`` — an
    animated «гифка» 5-10x lighter than a GIF container — next to her canonical
    references) served straight from disk.
    """
    if is_custom_character(character_id):
        return None
    rel = _FACE_REFERENCES.get(character_id)
    if not rel:
        return None
    folder = ROOT.joinpath('data', rel[0], rel[1])
    for name in ('card_preview.webp', 'card_preview.gif'):
        tile = folder / name
        if tile.exists():
            return tile
    return None


def builtin_character_ids() -> tuple[str, ...]:
    """V3.43.1: ids of the built-in heroines (the reference-map keys)."""
    return tuple(_FACE_REFERENCES)


# V3.43.3: the admin-uploaded storefront media of one character lives in its
# own folder as ``card_override.<ext>`` — exactly one file at a time, the ext
# decides how the grid renders it (jpg/png static, webp/gif animated <img>,
# mp4 looping <video>).
CARD_OVERRIDE_EXTS = ('.mp4', '.webp', '.gif', '.png', '.jpg')


def card_media_folder(character_id: str) -> Path:
    """V3.43.3: per-character folder for the admin-uploaded card media."""
    return ROOT / 'data' / 'card_media' / character_id


def character_card_override(character_id: str) -> Path | None:
    """V3.43.3: the active storefront media override of a character, if any."""
    folder = card_media_folder(character_id)
    if not folder.exists():
        return None
    for ext in CARD_OVERRIDE_EXTS:
        item = folder / f'card_override{ext}'
        if item.exists():
            return item
    return None


def set_card_override(character_id: str, data: bytes, ext: str) -> Path:
    """V3.43.3: replace the card media of a character (admin panel upload)."""
    folder = card_media_folder(character_id)
    folder.mkdir(parents=True, exist_ok=True)
    for stale_ext in CARD_OVERRIDE_EXTS:
        stale = folder / f'card_override{stale_ext}'
        if stale.exists():
            stale.unlink()
    target = folder / f'card_override{ext}'
    target.write_bytes(data)
    return target


def clear_card_override(character_id: str) -> bool:
    """V3.43.3: drop the override so the card falls back to the plain photo."""
    folder = card_media_folder(character_id)
    removed = False
    for stale_ext in CARD_OVERRIDE_EXTS:
        stale = folder / f'card_override{stale_ext}'
        if stale.exists():
            stale.unlink()
            removed = True
    return removed


def character_card_live(character_id: str) -> Path | None:
    """V3.43.1: the i2v-rendered living tile (``card_live.mp4``) of a heroine.

    The owner asked for tiles where the girl actually smiles and blows an air
    kiss instead of a Ken-Burns zoom; those clips are rendered once per
    heroine by the admin «живые плитки» job and served as muted loops.
    """
    if is_custom_character(character_id):
        return None
    rel = _FACE_REFERENCES.get(character_id)
    if not rel:
        return None
    live = ROOT.joinpath('data', rel[0], rel[1]) / 'card_live.mp4'
    return live if live.exists() else None


def asset_version(character_id: str) -> str:
    """V3.43.2: cache-buster stamp for the storefront assets of one heroine.

    Telegram's WebView kept the previous card tile for the whole ``max-age``
    window, so for up to an hour after a re-render the grid showed the old
    girl. Every asset URL now carries ``?v=<newest mtime in her reference
    folder>`` — rebuilding a tile or a live clip changes the URL and forces
    the client to fetch the fresh file.
    """
    newest = 0
    rel = _FACE_REFERENCES.get(character_id)
    folders = []
    if rel:
        folders.append(ROOT.joinpath('data', rel[0], rel[1]))
    # V3.43.3: an admin-uploaded override re-stamps the URLs too.
    folders.append(card_media_folder(character_id))
    for folder in folders:
        if folder.exists():
            for item in folder.iterdir():
                try:
                    newest = max(newest, int(item.stat().st_mtime))
                except OSError:
                    continue
    return str(newest)


def canonical_face_bytes(character_id: str, max_side: int = 768) -> bytes | None:
    """V3.43.1: the canonical face reference as a compact JPEG for i2v."""
    rel = _FACE_REFERENCES.get(character_id)
    if not rel:
        return None
    folder = ROOT.joinpath('data', rel[0], rel[1])
    sources = sorted(folder.glob('00_*face*.png')) or sorted(folder.glob('01_*look*.png'))
    if not sources:
        return None
    import io
    from PIL import Image
    img = Image.open(sources[0]).convert('RGB')
    width, height = img.size
    scale = min(1.0, max_side / max(width, height))
    if scale < 1.0:
        img = img.resize((int(width * scale), int(height * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=88)
    return buf.getvalue()


def write_card_live(character_id: str, video_bytes: bytes) -> Path | None:
    """V3.43.1: persist a rendered living tile next to the references."""
    rel = _FACE_REFERENCES.get(character_id)
    if not rel or not video_bytes:
        return None
    path = ROOT.joinpath('data', rel[0], rel[1]) / 'card_live.mp4'
    path.write_bytes(video_bytes)
    return path


def rebuild_card_tile(character_id: str) -> Path | None:
    """V3.43.1: re-render the Ken-Burns loop tile from the CURRENT canonicals.

    Swapping reference PNGs used to leave the old storefront «гифка» on disk;
    this re-renders ``card_preview.webp`` (24-frame sine zoom+pan loop) so new
    faces reach the grid without a code deploy.
    """
    rel = _FACE_REFERENCES.get(character_id)
    if not rel:
        return None
    folder = ROOT.joinpath('data', rel[0], rel[1])
    sources = sorted(folder.glob('01_*look*.png')) or sorted(folder.glob('00_*face*.png'))
    if not sources:
        return None
    import math
    from PIL import Image
    width, height, frames = 300, 400, 16
    img = Image.open(sources[0]).convert('RGB')
    w, h = img.size
    scale = max(width / w, height / h) * 1.14
    base = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    nw, nh = base.size
    out_frames = []
    for i in range(frames):
        t = i / frames
        zoom = 1.0 + 0.07 * (0.5 - 0.5 * math.cos(2 * math.pi * t))
        cw = min(nw, int(width * 1.14 / zoom))
        ch = min(nh, int(height * 1.14 / zoom))
        px = int((nw - cw) * (0.5 + 0.35 * math.sin(2 * math.pi * t)))
        py = int((nh - ch) * (0.5 - 0.35 * math.sin(2 * math.pi * t)))
        out_frames.append(base.crop((px, py, px + cw, py + ch)).resize((width, height), Image.LANCZOS))
    tile = folder / 'card_preview.webp'
    out_frames[0].save(tile, save_all=True, append_images=out_frames[1:],
                       duration=90, loop=0, quality=64)
    return tile


def character_views_map() -> dict[str, int]:
    """V3.40.0: view counters for the storefront badges (missing row = 0)."""
    try:
        with SessionLocal() as s:
            rows = s.scalars(select(CharacterStat)).all()
            return {r.character_id: r.views or 0 for r in rows}
    except Exception:
        return {}


def bump_character_views(character_id: str) -> int:
    """V3.40.0: +1 view when the character page opens; returns the new total."""
    try:
        with SessionLocal() as s:
            row = s.get(CharacterStat, character_id)
            if row is None:
                row = CharacterStat(character_id=character_id, views=0)
                s.add(row)
            row.views = (row.views or 0) + 1
            s.commit()
            return row.views
    except Exception:
        return 0


def character_leaderboard(limit: int = 10) -> list[dict]:
    """V3.44.0: top characters by views — the popularity leaderboard."""
    try:
        with SessionLocal() as s:
            rows = (
                s.query(CharacterStat)
                .order_by(CharacterStat.views.desc())
                .limit(limit)
                .all()
            )
            out = []
            for rank, row in enumerate(rows, 1):
                card = get_card(row.character_id)
                if card and card.is_visible:
                    out.append({
                        'rank': rank,
                        'id': row.character_id,
                        'name': card.display_name,
                        'emoji': card.button_emoji or '',
                        'views': row.views or 0,
                    })
            return out
    except Exception:
        return []


def get_character_comments(character_id: str, limit: int = 20) -> list[dict]:
    """V3.44.0: public comments under a character card."""
    try:
        with SessionLocal() as s:
            rows = (
                s.query(CharacterComment)
                .filter(CharacterComment.character_id == character_id)
                .order_by(CharacterComment.created_at.desc())
                .limit(limit)
                .all()
            )
            out = []
            for row in rows:
                user = s.query(User).filter(User.telegram_id == str(row.telegram_id)).first()
                out.append({
                    'id': row.id,
                    'text': row.text,
                    'author': user.name if user and user.name else f'User {row.telegram_id}',
                    'created_at': row.created_at.isoformat() if row.created_at else '',
                })
            return out
    except Exception:
        return []


def add_character_comment(character_id: str, telegram_id: int, text: str) -> dict:
    """V3.44.0: add a comment under a character card."""
    try:
        with SessionLocal() as s:
            comment = CharacterComment(
                character_id=character_id,
                telegram_id=telegram_id,
                text=text,
            )
            s.add(comment)
            s.commit()
            s.refresh(comment)
            user = s.query(User).filter(User.telegram_id == str(telegram_id)).first()
            return {
                'id': comment.id,
                'text': comment.text,
                'author': user.name if user and user.name else f'User {telegram_id}',
                'created_at': comment.created_at.isoformat() if comment.created_at else '',
            }
    except Exception:
        return {}


def get_notification_prefs(telegram_id: int) -> dict:
    """V3.44.0: get notification preferences for a user."""
    try:
        with SessionLocal() as s:
            pref = s.query(NotificationPref).filter(NotificationPref.telegram_id == telegram_id).first()
            if not pref:
                pref = NotificationPref(telegram_id=telegram_id)
                s.add(pref)
                s.commit()
                s.refresh(pref)
            return {
                'enabled': pref.enabled,
                'daily_bonus': pref.daily_bonus,
                'new_messages': pref.new_messages,
                'character_updates': pref.character_updates,
            }
    except Exception:
        return {'enabled': True, 'daily_bonus': True, 'new_messages': True, 'character_updates': True}


def update_notification_prefs(telegram_id: int, prefs: dict) -> dict:
    """V3.44.0: update notification preferences for a user."""
    try:
        with SessionLocal() as s:
            pref = s.query(NotificationPref).filter(NotificationPref.telegram_id == telegram_id).first()
            if not pref:
                pref = NotificationPref(telegram_id=telegram_id)
                s.add(pref)
            if 'enabled' in prefs:
                pref.enabled = bool(prefs['enabled'])
            if 'daily_bonus' in prefs:
                pref.daily_bonus = bool(prefs['daily_bonus'])
            if 'new_messages' in prefs:
                pref.new_messages = bool(prefs['new_messages'])
            if 'character_updates' in prefs:
                pref.character_updates = bool(prefs['character_updates'])
            s.commit()
            s.refresh(pref)
            return {
                'enabled': pref.enabled,
                'daily_bonus': pref.daily_bonus,
                'new_messages': pref.new_messages,
                'character_updates': pref.character_updates,
            }
    except Exception:
        return {}


# V3.44.0: daily bonus wheel rewards — weighted random prizes.
DAILY_BONUS_REWARDS = [
    {'peaches': 5, 'stars': 0, 'weight': 40},    # common: 5 peaches
    {'peaches': 10, 'stars': 0, 'weight': 25},   # uncommon: 10 peaches
    {'peaches': 25, 'stars': 0, 'weight': 15},   # rare: 25 peaches
    {'peaches': 50, 'stars': 0, 'weight': 10},   # epic: 50 peaches
    {'peaches': 0, 'stars': 5, 'weight': 7},     # rare: 5 stars
    {'peaches': 0, 'stars': 10, 'weight': 3},    # legendary: 10 stars
]


def spin_daily_bonus(telegram_id: int) -> dict:
    """V3.44.0: spin the daily bonus wheel — one spin per calendar day."""
    from datetime import date
    today = date.today().isoformat()
    try:
        with SessionLocal() as s:
            # Check if already claimed today
            existing = s.query(DailyBonus).filter(
                DailyBonus.telegram_id == telegram_id,
                DailyBonus.date == today
            ).first()
            if existing:
                return {'claimed': True, 'peaches': existing.reward_peaches, 'stars': existing.reward_stars}
            # Weighted random selection
            import random
            total_weight = sum(r['weight'] for r in DAILY_BONUS_REWARDS)
            roll = random.randint(1, total_weight)
            cumulative = 0
            reward = DAILY_BONUS_REWARDS[0]
            for r in DAILY_BONUS_REWARDS:
                cumulative += r['weight']
                if roll <= cumulative:
                    reward = r
                    break
            # Record the bonus
            bonus = DailyBonus(
                telegram_id=telegram_id,
                date=today,
                reward_peaches=reward['peaches'],
                reward_stars=reward['stars'],
            )
            s.add(bonus)
            # Credit the user
            user = s.query(User).filter(User.telegram_id == str(telegram_id)).first()
            if user:
                user.photo_credits = (user.photo_credits or 0) + reward['peaches']
                user.token_balance = (user.token_balance or 0) + reward['stars']
            s.commit()
            return {'claimed': False, 'peaches': reward['peaches'], 'stars': reward['stars']}
    except Exception:
        return {'claimed': False, 'peaches': 0, 'stars': 0}


def get_daily_bonus_status(telegram_id: int) -> dict:
    """V3.44.0: check if daily bonus has been claimed today."""
    from datetime import date
    today = date.today().isoformat()
    try:
        with SessionLocal() as s:
            existing = s.query(DailyBonus).filter(
                DailyBonus.telegram_id == telegram_id,
                DailyBonus.date == today
            ).first()
            if existing:
                return {'claimed': True, 'peaches': existing.reward_peaches, 'stars': existing.reward_stars}
            return {'claimed': False}
    except Exception:
        return {'claimed': False}


# V3.44.0: "she messages first" — simulated incoming message templates.
SIMULATED_MESSAGE_TEMPLATES = [
    "Привет! Я тут подумала о тебе... Как твой день?",
    "Скучала сегодня. Расскажи, что нового?",
    "Увидела кое-что и сразу о тебе вспомнила ",
    "Эй, ты там как? Давно не общались!",
    "Мне нужно с кем-то поговорить. Ты свободен?",
    "Привет! Я сегодня особенно скучаю по тебе...",
    "Угадай, о ком я думала весь день?",
    "Мне приснилось кое-что интересное... Хочешь расскажу?",
]


def generate_simulated_message(telegram_id: int, character_id: str) -> dict:
    """V3.44.0: generate a simulated incoming message from a character."""
    import random
    try:
        with SessionLocal() as s:
            template = random.choice(SIMULATED_MESSAGE_TEMPLATES)
            msg = SimulatedMessage(
                telegram_id=telegram_id,
                character_id=character_id,
                text=template,
            )
            s.add(msg)
            s.commit()
            s.refresh(msg)
            return {
                'id': msg.id,
                'character_id': msg.character_id,
                'text': msg.text,
                'sent_at': msg.sent_at.isoformat() if msg.sent_at else '',
            }
    except Exception:
        return {}


def get_pending_simulated_messages(telegram_id: int) -> list[dict]:
    """V3.44.0: get undelivered simulated messages for a user."""
    try:
        with SessionLocal() as s:
            rows = s.query(SimulatedMessage).filter(
                SimulatedMessage.telegram_id == telegram_id,
                SimulatedMessage.delivered == False
            ).order_by(SimulatedMessage.sent_at.asc()).all()
            out = []
            for row in rows:
                out.append({
                    'id': row.id,
                    'character_id': row.character_id,
                    'text': row.text,
                    'sent_at': row.sent_at.isoformat() if row.sent_at else '',
                })
            return out
    except Exception:
        return []


def mark_simulated_message_delivered(message_id: int) -> bool:
    """V3.44.0: mark a simulated message as delivered."""
    try:
        with SessionLocal() as s:
            msg = s.get(SimulatedMessage, message_id)
            if msg:
                msg.delivered = True
                s.commit()
                return True
            return False
    except Exception:
        return False


def character_like_state(character_id: str, telegram_id: int | None) -> dict:
    """V3.43.0: the «♡ N» counter of a heroine plus whether THIS user already
    liked her — the Come Closer character page badge, per-user aware."""
    try:
        with SessionLocal() as s:
            row = s.get(CharacterStat, character_id)
            count = int(row.likes or 0) if row else 0
            liked = bool(telegram_id) and s.get(CharacterLike, (character_id, int(telegram_id))) is not None
        return {'count': count, 'liked': liked}
    except Exception:
        return {'count': 0, 'liked': False}


def toggle_character_like(character_id: str, telegram_id: int) -> dict:
    """V3.43.0: tap the heart once to like, again to take it back. The marker
    row and the counter move together inside one transaction."""
    try:
        with SessionLocal() as s:
            row = s.get(CharacterStat, character_id)
            if row is None:
                row = CharacterStat(character_id=character_id, views=0, likes=0)
                s.add(row)
            mark = s.get(CharacterLike, (character_id, int(telegram_id)))
            if mark:
                s.delete(mark)
                row.likes = max(0, (row.likes or 0) - 1)
                liked = False
            else:
                s.add(CharacterLike(character_id=character_id, telegram_id=int(telegram_id)))
                row.likes = (row.likes or 0) + 1
                liked = True
            s.commit()
            return {'count': int(row.likes or 0), 'liked': liked}
    except Exception:
        logger.exception('character like toggle failed char=%s user=%s', character_id, telegram_id)
        return character_like_state(character_id, telegram_id)


def character_photo(character_id: str, index: int = 0) -> tuple[bytes, str] | None:
    """(bytes, content_type) of a storefront photo, or None if unavailable.

    Built-ins read their canonical references (index 0 = face, 1 = look);
    constructor personas read the cached avatar (v3.31.8
    ``ensure_custom_avatar_cached``).
    """
    paths = character_gallery(character_id)
    if not paths:
        return None
    path = paths[max(0, min(int(index or 0), len(paths) - 1))]
    content_type = 'image/jpeg' if path.suffix.lower() in ('.jpg', '.jpeg') else 'image/png'
    try:
        return path.read_bytes(), content_type
    except OSError:
        return None


# ── V3.39.0: in-app chat media (photos / circles / voice) ──────────────────

APP_MEDIA_DIR = ROOT / 'data' / 'app_media'
_MEDIA_NAME_RE = re.compile(r'^\d+_[0-9a-f]{8}\.(jpg|jpeg|png|mp4|ogg)$')


def save_chat_media(telegram_id: int, data: bytes, ext: str) -> str:
    """Store a generated media file per user; returns the unguessable name."""
    folder = APP_MEDIA_DIR / str(int(telegram_id))
    folder.mkdir(parents=True, exist_ok=True)
    name = f'{int(time.time() * 1000)}_{secrets.token_hex(4)}.{ext}'
    (folder / name).write_bytes(data)
    return name


def chat_media_file_path(telegram_id: int, filename: str) -> Path | None:
    """Owner-scoped media path; None when the name is not a server-made one."""
    if not _MEDIA_NAME_RE.match(filename or ''):
        return None
    path = APP_MEDIA_DIR / str(int(telegram_id)) / filename
    return path if path.exists() else None
