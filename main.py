import asyncio
import base64
import datetime as dt
import io
import json
import logging
import random
import re
import time as _time
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from dataclasses import replace

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, BufferedInputFile, FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from sqlalchemy import select
from aiogram.utils.chat_action import ChatActionSender

from config import (
    TELEGRAM_TOKEN, PREMIUM_MONTHLY_STARS, PHOTO_COST_STARS, CUSTOM_PHOTO_COST_STARS,
    ADMIN_TELEGRAM_IDS, CHARACTER_ID, PHOTO_PROGRESS_MESSAGE_DELAY_SECONDS,
    AI_KEY, LIBRARY_MODERATION_ENABLED, LIBRARY_MODERATION_MODEL,
    GEMINI_VIDEO_ENABLED, VIDEO_COST_STARS, GALLERY_DOWNLOAD_STARS, WALLET_PAY_ENABLED,
    REFERRAL_REFERRER_CREDITS, REFERRAL_INVITEE_CREDITS,
    CONSTRUCTOR_COST_STARS, PHOTO_REACTION_ENABLED, PHOTO_REACTION_COOLDOWN_SECONDS,
    FREEKASSA_ENABLED, FREEKASSA_PREMIUM_PRICE_RUB, PUBLIC_BASE_URL, WEB_PORT,
)
from services.user_service import (
    ensure_user, get_user, get_state, update_user_settings, touch_user,
    set_adult_confirmed, is_adult_confirmed,
)
from services.chat_service import reply as anna_reply
from services.access_service import can_send_message, is_premium
from services.photo_service import (
    PhotoRequest, parse_photo_request, deliver_photo, has_free_photo, build_photo_menu,
    create_offer, consume_offer, scene_allowed_for_stage, get_relationship_stage,
    get_relationship_level, is_custom_request, requires_adult_confirmation,
    SCENE_LEVELS, SCENES, PhotoGenerationError, get_latest_photo_delivery, get_photo_delivery_for_user,
    get_gallery_page, get_gallery_item_bytes, GALLERY_PAGE_SIZE, generate_custom_avatar,
)
from services.photo_idea_service import (
    idea_counts, list_admin_ideas, add_admin_idea, delete_admin_idea,
)
from services.payments import record_payment, get_photo_credits, record_refund, grant_premium, revoke_premium, consume_premium_video_free, premium_video_free_left
from services.bot_description import apply_bot_descriptions
from services.referral_service import (
    parse_referral_payload, apply_first_start_bonuses, apply_referral, referral_count, referral_link,
    referral_user_lock, pending_referral, remember_referral, referral_leaderboard, referral_rank,
    settle_monthly_contest,
)
from services.gemini_video_service import animate_image, video_available
from services.cloud_video_service import (
    animate_image_replicate, animate_image_fal,
    replicate_available, fal_available, CloudVideoError, SENSUAL_ANIMATION_PROMPT,
    VIDEO_PRESETS,
)
from services.hf_video_service import animate_image_hf, HfVideoError, hf_video_available
from services import freekassa_service
from aiohttp import web
from services import apartment_service, gifts_service, dates_service
from services.relationship_service import record_user_message, set_stage_change_notifier
from services.relationship_signals import infer_delta


def _any_video_engine() -> bool:
    """At least one image-to-video provider is configured."""
    return bool(
        video_available()
        or replicate_available()
        or fal_available()
        or hf_video_available()
    )


def _video_unavailable_text(telegram_id: int) -> str:
    """V3.19.1: admins see exactly which video engines are off, so a broken
    Railway env is diagnosable in one tap instead of a silent failure."""
    if telegram_id in ADMIN_TELEGRAM_IDS:
        return (
            'Видео недоступно: нет ни одного активного движка.\n'
            f'Gemini/Veo: {"✅" if video_available() else "❌ нет/битый GEMINI_API_KEY (должен быть чистый ASCII)"}\n'
            f'Replicate: {"✅" if replicate_available() else "❌ нет REPLICATE_API_TOKEN"}\n'
            f'fal.ai: {"✅" if fal_available() else "❌ нет FAL_KEY"}\n'
            f'HF spaces: {"✅" if hf_video_available() else "❌ выключен"}\n\n'
            'Проверь переменные окружения на Railway.'
        )
    return 'Видео пока недоступно.'
from services.llm_provider_service import provider_status
from services.reminder_service import set_timezone, create_from_text, cancel_active_wake, due_reminders
from services.scheduler_service import start_scheduler
from services.memory_service import reset_conversation as reset_memory
from services.db import SessionLocal
from models.relationship_models import UserCharacterRelationship, RelationshipEvent, RelationshipMilestone
from models.app_models import CharacterState, Reminder
from services.test_mode import STAGES, STAGE_LABELS, set_stage, clear_stage
from services.voice_service import transcribe, synthesize_bytes, VALID_VOICES
from services.adaptation_service import get_profile, observe_photo_preference, observe_photo_feedback
from services.analytics_service import track_event, admin_snapshot, budget_allows_photo
from services.photo_library_service import import_buffered_photos, library_stats, choose_unseen_pack, regroup_collection_packs, get_linked_video
from services.state_service import ensure_life_state, apply_life_choice
from services.character_card_service import (
    get_card, list_cards, update_card, reset_card, ensure_default_cards, create_card, delete_card,
    get_scenario_hook,
)
from services.character_dna_service import trait_bars
from services.photo_reaction_service import react_to_photo
from services.custom_character_service import (
    CONSTRUCTOR_STEPS, OPTION_LABELS, PARAM_TITLES, build_avatar_prompt,
    custom_character_id, get_custom_character, save_custom_character,
    summary_lines, step_index, is_custom_character,
)
from services.consent_service import has_accepted, accept as accept_consent, delete_user_data, TERMS_VERSION, PRIVACY_VERSION
from services.collection_service import collection_progress
from services.quest_service import QUESTS, QUEST_REPLAY_STARS, story_status, get_quest, complete_route, create_replay_offer, consume_replay_offer, premium_replays_left, consume_premium_replay, newly_unlocked_quests
from services.payment_method_service import (
    list_payment_methods, get_payment_method, create_payment_method,
    update_payment_method, delete_payment_method, ensure_default_payment_methods,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger('annabot')
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

PHOTO_LABELS = {
    'selfie': '📸 Селфи',
    'home': '🏠 Дома',
    'park': '🌿 Парк',
    'cafe': '☕ Кафе',
    'street': '🌆 Улица',
    'mirror': '🪞 Зеркало',
    'outfit': '👗 Образ',
    'shop': '🛍 Магазин',
    'car': '🚗 В машине',
    'gym': '🏋️ Зал',
    'restaurant': '🍽 Ресторан',
    'cinema': '🎬 Кино',
    'embankment': '🌊 Набережная',
    'fashion': '💎 Fashion',
    'evening': '✨ Вечер',
    'bar': '🍸 Бар',
    'karaoke': '🎤 Караоке',
    'rooftop': '🌃 Крыша',
    'club': '💃 Клуб',
    'personal': '💌 Личное фото',
    'lingerie': '🖤 Приватный fashion',
    'private_fashion': '🔐 Premium private',
    'nude': '🔥 Обнажённая',
    'tease': '🍑 Дразнит',
}

PHOTO_MENU_ORDER = [
    'selfie', 'home', 'park', 'cafe', 'street',
    'mirror', 'outfit', 'shop', 'car', 'gym',
    'restaurant', 'cinema', 'embankment', 'fashion',
    'evening', 'bar', 'karaoke', 'rooftop',
    'club', 'personal', 'lingerie', 'private_fashion',
    'nude', 'tease',
]

RELATIONSHIP_LEVEL_NAMES = {
    1: 'Знакомство',
    2: 'Симпатия',
    3: 'Доверие',
    4: 'Близость',
    5: 'Особая связь',
    6: 'Наша история',
}

# Short-lived UI state only. Paid offers themselves are persisted in PostgreSQL.
_custom_drafts: dict[int, dict] = {}
_pending_adult_photo: dict[int, PhotoRequest] = {}
_pending_adult_custom: set[int] = set()

# Background photo jobs: Telegram handlers return immediately, so normal chat remains responsive.
# A persistent DB queue is a later scaling step; for the closed beta one active job per user
# is enough to prevent duplicate spending and double taps.
_photo_jobs: dict[int, asyncio.Task] = {}
_photo_job_reservations: set[int] = set()

# Track when Anna offers a photo in chat — next user "yes" triggers photo flow
_photo_offer_pending: dict[int, float] = {}  # telegram_id -> timestamp of offer
_photo_offer_expression: dict[int, str | None] = {}  # telegram_id -> chat mood that triggered the offer
_PHOTO_OFFER_TTL = 120  # offer expires after 2 minutes

# Regex: Anna offered a photo in her response
_PHOTO_OFFER_DETECT = re.compile(
    r'(хочешь.*(?:фот|фото|скин|покаж|увид)|'
    r'(?:скин|покаж|присл|отправ).*тебе.*(?:фот|фото|кое-что|что-нибудь)|'
    r'(?:могу|хочу).*(?:показать|скинуть|прислать)|'
    r'а хочешь (?:увидеть|посмотреть)|'
    r'скинуть тебе|показать тебе|прислать тебе)',
    re.I
)

# Regex: user accepts a photo offer
_PHOTO_ACCEPT = re.compile(
    r'^(да|давай|даа|дааа|ок|окей|хочу|конечно|скинь|кинь|кидай|'
    r'покажи|показывай|присылай|давай да|ну давай|ага|угу|ес|yep|yes|sure)$',
    re.I
)

from config import CHAT_PHOTO_OFFER_STARS
from config import VIDEO_STATUS_TEXT

# Video jobs are intentionally limited to one per user. They can
# take minutes during peak load, so generation always runs in background.
_video_jobs: dict[int, asyncio.Task] = {}

# Owner-only Telegram photo-library importer. Images stay on Telegram; only file_id metadata is persisted.
_library_import_sessions: dict[int, dict] = {}

# Owner-only editor state for public character cards. Persistent card values live in PostgreSQL.
_character_card_edit_sessions: dict[int, dict] = {}

# Owner-only editor state for configurable payment methods. Payment rows live in PostgreSQL.
_payment_method_edit_sessions: dict[int, dict] = {}

# Owner-only editor state for photo ideas. Idea rows live in PostgreSQL.
_photo_idea_edit_sessions: dict[int, dict] = {}

# Scenes that admins may attach photo ideas to (private scenes stay untouched).
ALLOWED_IDEA_SCENES = tuple(sorted(k for k in SCENES if k not in {'personal', 'lingerie', 'private_fashion'}))

# Per-user selected character (telegram_id -> character_id). Falls back to CHARACTER_ID.
_user_character: dict[int, str] = {}


def get_user_character(telegram_id: int) -> str:
    """Return the character_id the user currently chats with, or CHARACTER_ID as default."""
    return _user_character.get(telegram_id, CHARACTER_ID)

LIBRARY_CHARACTERS = {
    'anna_01': '👩🏻 Анна',
    'alena_01': '👱‍♀️ Emily',
    'maria_01': '💃 Мария',
}

LIBRARY_SCENES = [
    'selfie', 'home', 'park', 'cafe', 'street', 'shop', 'car', 'gym', 'mirror', 'outfit',
    'restaurant', 'cinema', 'embankment', 'evening', 'fashion', 'bar', 'karaoke', 'rooftop', 'club',
    'personal', 'private_fashion',
]


def main_keyboard(is_admin: bool = False):
    rows = [
        [KeyboardButton(text='💬 Общение'), KeyboardButton(text='📸 Фото')],
        [KeyboardButton(text='🎯 Истории'), KeyboardButton(text='🖼 Коллекция')],
        [KeyboardButton(text='✨ Возможности'), KeyboardButton(text='🚀 Премиум')],
        [KeyboardButton(text='⏰ Будильник'), KeyboardButton(text='👤 Профиль')],
        [KeyboardButton(text='🏠 Квартира'), KeyboardButton(text='💕 Свидание')],
        [KeyboardButton(text='⚙️ Настройки'), KeyboardButton(text='👩 Персонажи')],
        [KeyboardButton(text='🔗 Пригласить'), KeyboardButton(text='🎁 Подарить')],
        [KeyboardButton(text='🎨 Мой персонаж')],
    ]
    if is_admin:
        rows.append([KeyboardButton(text='🛠 Админка')])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


def onboarding_character_keyboard():
    rows = []
    for card in list_cards(visible_only=True):
        if card.status == 'active':
            text = f'✅ {card.display_name} · выбрать'
        elif card.status == 'premium':
            text = f'⭐ {card.display_name} · Premium'
        else:
            text = f'🔒 {card.display_name} · скоро'
        rows.append([InlineKeyboardButton(text=text, callback_data=f'onboard:character:{card.character_id}')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def abilities_text() -> str:
    return (
        '✨ Что умеет бот\n\n'
        '💬 живое общение с характером — она запоминает контекст и со временем подстраивается под твою манеру общения\n'
        '❤️ отношения развиваются по уровням 1–6: с каждым уровнем общение и образы становятся ближе и откровеннее\n'
        '🎯 интерактивные истории: твой первый выбор становится каноном, а альтернативные ветки можно посмотреть позже\n'
        '📸 фото прямо в чате: напиши «скинь фото» или «хочу тебя увидеть» — она пришлёт свежий кадр по ситуации; иногда предлагает сама во время флирта\n'
        '🎬 кнопка «Оживить фото» под каждым снимком — короткое AI-видео из любого фото (Premium: 1 бесплатно в день)\n'
        '🏠 квартира: заходи в комнаты, проводи с ней время — новые комнаты открываются с уровнями отношений\n'
        '💕 свидания: пригласи её куда-нибудь, а после она пришлёт фото с прогулки\n'
        '🎁 подарки: приятные сюрпризы, которые сближают\n'
        '🎙 голосовые ответы: у каждой девушки свой милый голос, отвечает на твоём языке\n'
        '🖼 коллекция открытых фотографий по уровням отношений\n'
        '💌 она иногда может написать первой и вернуться к незаконченной теме\n'
        '⏰ будильник и напоминания — Premium-функция: разбудит вовремя и запомнит твой часовой пояс\n\n'
        '🎯 Первая история уже доступна — можешь начать её сразу или просто написать мне.'
    )


def abilities_inline_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='💬 Начать общение', callback_data='onboard:meet')],
        [InlineKeyboardButton(text='🎯 Первая история', callback_data='quest:view:outfit_choice')],
    ])


def consent_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ Мне 18+ · принимаю условия', callback_data='consent:accept')],
        [InlineKeyboardButton(text='📄 Условия', callback_data='consent:terms'), InlineKeyboardButton(text='🔐 Privacy', callback_data='consent:privacy')],
    ])


def delete_confirm_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🗑 Да, удалить мои данные', callback_data='delete:confirm')],
        [InlineKeyboardButton(text='Отмена', callback_data='delete:cancel')],
    ])


def stories_keyboard(telegram_id: int):
    level = get_relationship_level(telegram_id, get_user_character(telegram_id))
    rows = []
    for item in story_status(telegram_id, level):
        if item['unlocked']:
            count = len(item['done']); total = len(item['routes'])
            if not item.get('canonical'):
                label = f"🟢 {item['title']} · начать"
            elif count >= total:
                label = f"✅ {item['title']} · {count}/{total}"
            else:
                label = f"↩️ {item['title']} · {count}/{total}"
            rows.append([InlineKeyboardButton(text=label, callback_data=f"quest:view:{item['key']}")])
        else:
            rows.append([InlineKeyboardButton(text=f"🔒 {item['title']} · откроется L{item['min_level']}", callback_data=f"quest:locked:{item['key']}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def quest_routes_keyboard(telegram_id: int, quest_key: str):
    q=get_quest(quest_key); status=next((x for x in story_status(telegram_id,get_relationship_level(telegram_id, get_user_character(telegram_id))) if x['key']==quest_key),None)
    rows=[]
    for key,route in q['routes'].items():
        if key in (status or {}).get('done',[]):
            suffix=' ✅' + (' · канон' if key==(status or {}).get('canonical') else '')
            rows.append([InlineKeyboardButton(text=route['label']+suffix, callback_data='quest:done')])
        elif (status or {}).get('canonical'):
            rows.append([InlineKeyboardButton(text=f"🔒 {route['label']} · replay {QUEST_REPLAY_STARS}⭐", callback_data=f"quest:route:{quest_key}:{key}")])
        else:
            rows.append([InlineKeyboardButton(text=route['label'], callback_data=f"quest:route:{quest_key}:{key}")])
    rows.append([InlineKeyboardButton(text='⬅️ Истории', callback_data='quest:list')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def characters_keyboard():
    rows = []
    for card in list_cards(visible_only=True):
        if card.status == 'active':
            text = f'✅ {card.display_name} · доступна'
        elif card.status == 'premium':
            text = f'⭐ {card.display_name} · Premium'
        else:
            text = f'🔒 {card.display_name} · скоро'
        rows.append([InlineKeyboardButton(text=text, callback_data=f'character:view:{card.character_id}')])
    # V3.19.0: entry point to the personal character constructor.
    rows.append([InlineKeyboardButton(text=f'🎨 Создать свою · {CONSTRUCTOR_COST_STARS}⭐', callback_data='constructor:start')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_keyboard():
    # ADMIN_TELEGRAM_IDS is a set, so peek via next(iter(...)) instead of indexing.
    premium_state = ('✅ вкл' if is_premium(next(iter(ADMIN_TELEGRAM_IDS))) else '❌ выкл') if ADMIN_TELEGRAM_IDS else '—'
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🎭 Карточки персонажей', callback_data='admin:cards')],
        [InlineKeyboardButton(text='💳 Способы оплаты', callback_data='admin:payments')],
        [InlineKeyboardButton(text='📚 Библиотека фото', callback_data='admin:library_help')],
        [InlineKeyboardButton(text='💡 Идеи для фото', callback_data='admin:ideas')],
        [InlineKeyboardButton(text='📊 Статистика', callback_data='admin:stats')],
        [InlineKeyboardButton(text=f'⭐ Premium себе (тесты): {premium_state}', callback_data='admin:premium_toggle')],
    ])


def admin_ideas_keyboard():
    _, db_count = idea_counts()
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='➕ Добавить идею', callback_data='admin:ideaadd:start')],
        [InlineKeyboardButton(text=f'🗑 Удалить идею ({db_count})', callback_data='admin:ideadel:list')],
        [InlineKeyboardButton(text='⬅️ Админка', callback_data='admin:home')],
    ])


def admin_cards_keyboard():
    rows = [[InlineKeyboardButton(text=card.button_text, callback_data=f'admin:card:{card.character_id}')] for card in list_cards()]
    rows.append([InlineKeyboardButton(text='➕ Добавить персонажа', callback_data='admin:cardadd:start')])
    rows.append([InlineKeyboardButton(text='⬅️ Админка', callback_data='admin:home')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_card_keyboard(character_id: str):
    rows = [
        [InlineKeyboardButton(text='👁 Предпросмотр', callback_data=f'admin:preview:{character_id}')],
        [InlineKeyboardButton(text='✏️ Имя', callback_data=f'admin:cardedit:{character_id}:display_name'),
         InlineKeyboardButton(text='⚧ Пол', callback_data=f'admin:cardedit:{character_id}:gender')],
        [InlineKeyboardButton(text='🎂 Возраст', callback_data=f'admin:cardedit:{character_id}:age')],
        [InlineKeyboardButton(text='📝 Описание', callback_data=f'admin:cardedit:{character_id}:short_bio')],
        [InlineKeyboardButton(text='🏷 Статус', callback_data=f'admin:status:{character_id}'),
         InlineKeyboardButton(text='🖼 Фото', callback_data=f'admin:cardedit:{character_id}:photo')],
        [InlineKeyboardButton(text='👁 Видимость', callback_data=f'admin:toggle:{character_id}'),
         InlineKeyboardButton(text='🗑 Убрать фото', callback_data=f'admin:clearphoto:{character_id}')],
        [InlineKeyboardButton(text='↩️ Сбросить карточку', callback_data=f'admin:reset:{character_id}')],
    ]
    from services.character_card_service import DEFAULT_CARDS
    if character_id not in DEFAULT_CARDS:
        rows.append([InlineKeyboardButton(text='🗑 Удалить персонажа', callback_data=f'admin:carddelete:{character_id}')])
    rows.append([InlineKeyboardButton(text='⬅️ Все персонажи', callback_data='admin:cards')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_status_keyboard(character_id: str):
    rows = [
        [InlineKeyboardButton(text='✅ Активна', callback_data=f'admin:setstatus:{character_id}:active'),
         InlineKeyboardButton(text='🕒 Скоро', callback_data=f'admin:setstatus:{character_id}:soon')],
        [InlineKeyboardButton(text='🔒 Закрыта', callback_data=f'admin:setstatus:{character_id}:locked'),
         InlineKeyboardButton(text='⭐ Premium', callback_data=f'admin:setstatus:{character_id}:premium')],
        [InlineKeyboardButton(text='⬅️ Назад', callback_data=f'admin:card:{character_id}')],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_payments_keyboard():
    ensure_default_payment_methods()
    rows = [
        [InlineKeyboardButton(text=method.button_text, callback_data=f'admin:payment:{method.id}')]
        for method in list_payment_methods()
    ]
    rows.extend([
        [InlineKeyboardButton(text='➕ Добавить QR', callback_data='admin:paymentadd:qr'),
         InlineKeyboardButton(text='➕ Добавить ссылку', callback_data='admin:paymentadd:link')],
        [InlineKeyboardButton(text='⬅️ Админка', callback_data='admin:home')],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_payment_keyboard(method_id: int):
    method = get_payment_method(method_id)
    if not method:
        return admin_payments_keyboard()
    rows = [
        [InlineKeyboardButton(text='👁 Предпросмотр', callback_data=f'admin:paymentpreview:{method_id}')],
    ]
    if method.method_type != 'stars':
        rows.append([
            InlineKeyboardButton(text='✏️ Название', callback_data=f'admin:paymentedit:{method_id}:display_name'),
            InlineKeyboardButton(text='📝 Инструкция', callback_data=f'admin:paymentedit:{method_id}:instructions'),
        ])
        if method.method_type == 'qr':
            rows.append([InlineKeyboardButton(text='🖼 Заменить QR', callback_data=f'admin:paymentedit:{method_id}:qr'),
                         InlineKeyboardButton(text='🔗 Ссылка на QR', callback_data=f'admin:paymentedit:{method_id}:url')])
        elif method.method_type == 'link':
            rows.append([InlineKeyboardButton(text='🔗 Изменить ссылку', callback_data=f'admin:paymentedit:{method_id}:url')])
        rows.append([InlineKeyboardButton(text='🏷 Статус', callback_data=f'admin:paymentstatus:{method_id}')])
        if not method.is_system:
            rows.append([InlineKeyboardButton(text='🗑 Удалить', callback_data=f'admin:paymentdelete:{method_id}')])
    rows.append([InlineKeyboardButton(text='⬅️ Способы оплаты', callback_data='admin:payments')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_payment_status_keyboard(method_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ Включён', callback_data=f'admin:paymentsetstatus:{method_id}:active'),
         InlineKeyboardButton(text='⏸ Выключен', callback_data=f'admin:paymentsetstatus:{method_id}:disabled')],
        [InlineKeyboardButton(text='🕒 Скоро', callback_data=f'admin:paymentsetstatus:{method_id}:soon')],
        [InlineKeyboardButton(text='⬅️ Назад', callback_data=f'admin:payment:{method_id}')],
    ])


def _admin_payment_summary(method_id: int) -> str:
    method = get_payment_method(method_id)
    if not method:
        return 'Способ оплаты не найден.'
    value = '—'
    if method.method_type == 'qr':
        parts = []
        if method.qr_photo_file_id:
            parts.append('QR загружен')
        if method.external_url:
            parts.append(f'ссылка: {method.external_url}')
        value = ' · '.join(parts) if parts else 'QR не загружен'
    elif method.method_type == 'link':
        value = method.external_url or 'ссылка не указана'
    elif method.method_type == 'stars':
        value = 'XTR / Telegram Stars'
    return (
        f'💳 {method.display_name}\n\n'
        f'Тип: {method.type_label}\n'
        f'Статус: {method.status_label}\n'
        f'Область: {method.scope_label}\n'
        f'Данные: {value}\n\n'
        f'{method.instructions or "Инструкция не заполнена."}\n\n'
        '⚠️ Для Premium, фото, квестов и другого цифрового контента внутри Telegram используется только Stars. '
        'QR/ссылки здесь хранятся как внешние способы и не подменяют XTR-checkout.'
    )


async def _send_payment_preview(chat_id: int, method_id: int):
    method = get_payment_method(method_id)
    if not method:
        await bot.send_message(chat_id, 'способ оплаты не найден')
        return
    text_value = _admin_payment_summary(method_id)
    if method.method_type == 'qr' and method.qr_photo_file_id:
        await bot.send_photo(chat_id, method.qr_photo_file_id, caption=text_value)
    elif method.method_type == 'qr' and method.external_url:
        await bot.send_message(chat_id, f'{text_value}\n\n🔗 QR-ссылка: {method.external_url}')
    else:
        await bot.send_message(chat_id, text_value)


def _character_card_text(card, viewer_id: int | None = None) -> str:
    lines = [
        f'{card.button_emoji} {card.display_name}, {card.age}',
        '',
        card.short_bio or 'Описание пока не заполнено.',
    ]
    # V3.19.0: WildGrl-style trait bars and cinematic scenario hook.
    bars = trait_bars(card.character_id)
    if bars:
        lines.append('')
        lines.append('Характер:')
        lines.extend(bars)
    hook = get_scenario_hook(card.character_id)
    if hook:
        lines.extend(['', f'🎬 {hook}'])
    lines.extend(['', f'🏷 Статус: {card.status_label}'])
    if viewer_id and card.character_id == CHARACTER_ID:
        try:
            level = get_relationship_level(viewer_id, get_user_character(viewer_id))
            lines.append(f'❤️ {RELATIONSHIP_LEVEL_NAMES.get(level, "Знакомство")}')
        except Exception:
            pass
        lines.extend([
            ('🎬 Оживить фото: ✅ доступно' if _any_video_engine() else '🎬 Оживить фото: 🔒 скоро'),
            '📞 Звонок с Анной: 🔒 скоро',
        ])
    return '\n'.join(lines)


def _character_fallback_photo(character_id: str) -> Path | None:
    """Return a canonical face reference image for a character, if available."""
    base = Path(__file__).resolve().parent / 'data' / 'references'
    candidates = {
        CHARACTER_ID: base / 'anna' / '00_anna_canonical_face_v3.png',
        'alena_01': base / 'emily' / '00_emily_canonical_face.png',
        'maria_01': base / 'maria' / '00_maria_canonical_face.png',
    }
    return candidates.get(character_id)


async def _send_character_card(chat_id: int, character_id: str, *, viewer_id: int | None = None, admin_preview: bool = False):
    card = get_card(character_id)
    if not card:
        await bot.send_message(chat_id, 'карточка не найдена')
        return
    text_value = _character_card_text(card, viewer_id=viewer_id)
    markup = None if admin_preview else characters_keyboard()
    if card.card_photo_file_id:
        await bot.send_photo(chat_id, card.card_photo_file_id, caption=text_value, reply_markup=markup)
        return
    fallback = _character_fallback_photo(character_id)
    if fallback and fallback.exists():
        await bot.send_photo(chat_id, FSInputFile(fallback), caption=text_value, reply_markup=markup)
        return
    await bot.send_message(chat_id, text_value, reply_markup=markup)


def _admin_card_summary(character_id: str) -> str:
    card = get_card(character_id)
    if not card:
        return 'Карточка не найдена.'
    return (
        f'⚙️ Карточка: {card.button_emoji} {card.display_name}\n\n'
        f'ID: {card.character_id}\n'
        f'Возраст: {card.age}\n'
        f'Статус: {card.status_label}\n'
        f'Видимость: {"да" if card.is_visible else "нет"}\n'
        f'Фото: {"установлено" if card.card_photo_file_id else "нет"}\n\n'
        f'{card.short_bio or "Описание не заполнено."}\n\n'
        'ℹ️ Статус «активна» открывает персонажа для выбора в чате. Premium — за платный доступ.'
    )


def library_character_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f'libchar:{cid}')]
        for cid, label in LIBRARY_CHARACTERS.items()
    ])


def library_scene_keyboard(character_id: str):
    buttons = [InlineKeyboardButton(text=PHOTO_LABELS.get(scene, scene), callback_data=f'libscene:{character_id}:{scene}') for scene in LIBRARY_SCENES]
    return InlineKeyboardMarkup(inline_keyboard=[buttons[i:i+2] for i in range(0, len(buttons), 2)])


def library_level_keyboard(character_id: str, scene: str):
    required = max(1, int(SCENE_LEVELS.get(scene, 1)))
    allowed = list(range(required, 7))
    rows = []
    for i in range(0, len(allowed), 3):
        rows.append([InlineKeyboardButton(text=f'❤️ {level}', callback_data=f'liblevel:{character_id}:{scene}:{level}') for level in allowed[i:i+3]])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def library_mode_keyboard(character_id: str, scene: str, level: int):
    # Backward compatibility only. New V3.9.2 imports always use 3-photo progression packs.
    base = f'{character_id}:{scene}:{level}'
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🎞 Авто-сеты по 3', callback_data=f'libmode:{base}:progression')],
    ])


def _library_upload_status_text(sess: dict, *, preview: bool = False) -> str:
    photos = sess.get('photos', [])
    count = len(photos)
    video_count = sum(1 for p in photos if p.get('video_file_id'))
    rejected = int(sess.get('rejected', 0))
    moderation_errors = int(sess.get('moderation_errors', 0))
    packs, tail = divmod(count, 3)
    char_label = LIBRARY_CHARACTERS.get(sess.get('character_id'), sess.get('character_id', ''))
    scene_label = PHOTO_LABELS.get(sess.get('scene'), sess.get('scene', ''))
    level = sess.get('level', 1)
    if preview:
        tail_text = f'\n➕ Остаток: {tail} фото сохранится отдельно в коллекции.' if tail else ''
        return (
            f'Предпросмотр:\n{char_label} · {scene_label} · ❤️ {level}\n'
            f'Получено: {count} фото\n'
            f'Будет сохранено: {count} фото · видео: {video_count} · полных сетов по 3: {packs}{tail_text}\n\n'
            'Порядок каждого сета: 1 — Base · 2 — Stylish · 3 — Premium.\n'
            'Видео хранится вместе с конкретным фото и не считается отдельным фото.'
        )
    return (
        f'📚 {char_label} → {scene_label} → ❤️ {level}\n'
        'Режим: автоматические сеты по 3.\n'
        'Отправляй фото в нужном порядке. До 10 фото на один уровень.\n'
        'Если у фото есть готовое видео — отправь его СРАЗУ ПОСЛЕ этого фото. Тогда оно привяжется к нему.\n'
        'Схема: фото → видео → следующее фото → видео. Видео не входит в лимит 10/10.\n'
        'Каждые 3 фото = один сет: Base → Stylish → Premium.\n\n'
        f'Принято: {count} / 10 · видео: {video_count} · готовых сетов: {packs}'
        + (f' · остаток: {tail}' if tail else '')
        + (f' · отклонено: {rejected}' if rejected else '')
        + (f' · ошибок проверки: {moderation_errors}' if moderation_errors else '')
    )


async def _library_refresh_status(sess: dict, *, preview: bool = False) -> None:
    chat_id = sess.get('status_chat_id')
    message_id = sess.get('status_message_id')
    if not chat_id or not message_id:
        return
    try:
        await bot.edit_message_text(
            _library_upload_status_text(sess, preview=preview),
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=library_import_controls(preview=preview),
        )
    except Exception as exc:
        logger.debug('library status edit skipped: %s', exc)


def library_import_controls(preview: bool = False):
    if preview:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='✅ Сохранить всё', callback_data='libimp:save')],
            [InlineKeyboardButton(text='➕ Продолжить загрузку', callback_data='libimp:continue')],
            [InlineKeyboardButton(text='🗑 Очистить', callback_data='libimp:clear')],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ Закончить загрузку', callback_data='libimp:finish')],
        [InlineKeyboardButton(text='↩️ Удалить последнее', callback_data='libimp:undo')],
        [InlineKeyboardButton(text='❌ Отмена', callback_data='libimp:cancel')],
    ])


def life_choice_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='☕ Кафе', callback_data='life:cafe'), InlineKeyboardButton(text='🌿 Парк', callback_data='life:park')],
        [InlineKeyboardButton(text='🛍 Магазин', callback_data='life:shop'), InlineKeyboardButton(text='🌆 Прогулка', callback_data='life:street')],
        [InlineKeyboardButton(text='🍸 Бар', callback_data='life:bar')],
    ])


def _contextualize_vague_photo(telegram_id: int, text: str, request: PhotoRequest | None):
    if not request or request.scene != 'selfie':
        return request
    low = (text or '').lower().strip()
    vague = any(x in low for x in ('покажись', 'покажи себя', 'сфоткайся', 'пришли фото', 'фото сейчас'))
    if not vague:
        return request
    state = get_state(telegram_id)
    location = (getattr(state, 'location', '') or '').lower()
    mapping = {
        'кафе': 'cafe', 'парк': 'park', 'магазин': 'shop', 'ресторан': 'restaurant',
        'бар': 'bar', 'набереж': 'embankment', 'город': 'street', 'улиц': 'street', 'дома': 'home',
    }
    for token, scene in mapping.items():
        if token in location:
            return replace(request, scene=scene, location=location)
    return request


def premium_keyboard():
    if _any_video_engine():
        video_button = InlineKeyboardButton(text=f'🎬 Оживить последнее фото — {VIDEO_COST_STARS}⭐', callback_data='video:animate_last')
    else:
        video_button = InlineKeyboardButton(text='🔒 🎬 Оживить фото · скоро', callback_data='future:animate_photo')
    rows = [
        [InlineKeyboardButton(text=f'⭐ Premium — {PREMIUM_MONTHLY_STARS} Stars / 30 дней', callback_data='buy:premium')],
    ]
    if WALLET_PAY_ENABLED:
        rows.append([InlineKeyboardButton(text=f'💎 Premium — Wallet Pay (крипта/карта)', callback_data='walletpay:premium')])
    if FREEKASSA_ENABLED:
        # V3.19.6: external card/SBP scenario (Telegram policy keeps Stars for
        # in-Telegram digital purchases; this link pays on FreeKassa's page).
        rows.append([InlineKeyboardButton(text=f'💳 Premium — {FREEKASSA_PREMIUM_PRICE_RUB} ₽ картой / СБП', callback_data='fk:premium')])
    rows.append([video_button])
    rows.append([InlineKeyboardButton(text='🔒 📞 Звонок с персонажем · скоро', callback_data='future:anna_call')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def adult_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ Мне 18+', callback_data='age:yes')],
        [InlineKeyboardButton(text='↩️ Нет', callback_data='age:no')],
    ])


def photo_keyboard(telegram_id: int):
    level = get_relationship_level(telegram_id, get_user_character(telegram_id))
    unlocked = [scene for scene in PHOTO_MENU_ORDER if SCENE_LEVELS.get(scene, 99) <= level]
    rows = []
    for i in range(0, len(unlocked), 2):
        rows.append([
            InlineKeyboardButton(text=PHOTO_LABELS[scene], callback_data=f'photo:{scene}')
            for scene in unlocked[i:i + 2]
        ])

    # Show the NEXT unlock instead of hiding progression. This gives users a
    # concrete reason to continue the relationship without turning it into a paywall.
    future_levels = sorted({SCENE_LEVELS[s] for s in PHOTO_MENU_ORDER if SCENE_LEVELS.get(s, 99) > level})
    if future_levels:
        next_level = future_levels[0]
        locked = [s for s in PHOTO_MENU_ORDER if SCENE_LEVELS.get(s) == next_level]
        for i in range(0, len(locked), 2):
            rows.append([
                InlineKeyboardButton(
                    text=f'🔒 {PHOTO_LABELS[scene]} · ур.{next_level}',
                    callback_data=f'locked:{scene}',
                )
                for scene in locked[i:i + 2]
            ])
        if level == 4 and next_level == 5:
            rows.append([InlineKeyboardButton(
                text='🔒 ✨ Кастомное фото · ур.5',
                callback_data='locked:custom',
            )])

    if level >= 5:
        rows.append([InlineKeyboardButton(text=f'✨ Кастомное фото — {CUSTOM_PHOTO_COST_STARS}⭐', callback_data='custom:start')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def photo_retry_keyboard(scene: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔄 Повторить', callback_data=f'retry_photo:{scene}')],
        [InlineKeyboardButton(text='📸 Другой сюжет', callback_data='photo_menu:open')],
    ])


def photo_feedback_keyboard(scene: str):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='🔥 Нравится', callback_data=f'photo_feedback:like:{scene}'),
        InlineKeyboardButton(text='Не мой стиль', callback_data=f'photo_feedback:dislike:{scene}'),
    ]])


def photo_menu_text(telegram_id: int) -> str:
    info = build_photo_menu(telegram_id, get_user_character(telegram_id))
    level = info['level']
    name = RELATIONSHIP_LEVEL_NAMES.get(level, '')
    future = sorted({required for required in SCENE_LEVELS.values() if required > level})
    next_line = f'\n🔒 Следующие фото откроются на уровне {future[0]}/6' if future else '\n✨ Все уровни фото уже открыты'
    return (
        f'что показать? 😌\n'
        f'❤️ Близость: {level}/6 · {name}\n'
        f'🎁 Бесплатно сегодня: {info["free_left"]}/{info["limit"]} · credits: {info["credits"]}\n'
        f'📷 Progression pack: базовый → стильный → premium · до {info["set_size"]} фото'
        f'{next_line}'
    )


def custom_color_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='🖤 Чёрный', callback_data='custom:color:black'),
            InlineKeyboardButton(text='🤍 Белый', callback_data='custom:color:white'),
            InlineKeyboardButton(text='❤️ Красный', callback_data='custom:color:red'),
        ]
    ])


def custom_addon_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🧦 Чулки', callback_data='custom:addon:stockings')],
        [InlineKeyboardButton(text='Без дополнения', callback_data='custom:addon:none')],
    ])


def custom_hair_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='Хвост', callback_data='custom:hair:ponytail'),
            InlineKeyboardButton(text='Пучок', callback_data='custom:hair:bun'),
            InlineKeyboardButton(text='Распущенные', callback_data='custom:hair:loose'),
        ]
    ])


def custom_place_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='🪞 Зеркало', callback_data='custom:place:mirror'),
            InlineKeyboardButton(text='🛋 Диван', callback_data='custom:place:sofa'),
        ],
        [InlineKeyboardButton(text='🏨 Отель', callback_data='custom:place:hotel')],
    ])


def _track_proactive_reply_if_any(telegram_id: int, uid: int):
    try:
        user = get_user(telegram_id)
        state = get_state(telegram_id)
        if user and state and state.last_nudge_at and user.last_active_at and state.last_nudge_at >= user.last_active_at:
            track_event(uid, 'proactive_replied')
    except Exception:
        pass


async def send_stars_invoice(chat_id: int, title: str, description: str, payload: str, stars: int):
    await bot.send_invoice(
        chat_id=chat_id,
        title=title,
        description=description,
        payload=payload,
        currency='XTR',
        prices=[LabeledPrice(label=title, amount=stars)],
        provider_token='',
    )


async def _offer_custom_photo(chat_id: int, telegram_id: int, request: PhotoRequest):
    offer_id = create_offer(telegram_id, request)
    await send_stars_invoice(
        chat_id,
        'Кастомное фото Анны',
        'Персональный образ: одежда / цвет / причёска / место / ракурс',
        f'photo:{offer_id}',
        CUSTOM_PHOTO_COST_STARS,
    )


async def _photo_progress_ping(chat_id: int, telegram_id: int):
    try:
        await asyncio.sleep(max(5.0, PHOTO_PROGRESS_MESSAGE_DELAY_SECONDS))
        task = _photo_jobs.get(telegram_id)
        if task and not task.done():
            await bot.send_message(chat_id, 'ещё сек 🙂 докручиваю остальные кадры')
    except asyncio.CancelledError:
        pass
    except Exception:
        pass


async def _run_photo_background(chat_id: int, telegram_id: int, request: PhotoRequest, delivery_type: str):
    uid = ensure_user(telegram_id)
    ping = asyncio.create_task(_photo_progress_ping(chat_id, telegram_id))
    try:
        track_event(uid, 'photo_generation_started', metadata={'scene': request.scene, 'delivery_type': delivery_type})
        async with ChatActionSender.upload_photo(bot=bot, chat_id=chat_id):
            sent = await deliver_photo(bot, chat_id, telegram_id, request, delivery_type, character_id=get_user_character(telegram_id))
        track_event(uid, 'photo_job_completed', metadata={'scene': request.scene, 'count': len(sent), 'delivery_type': delivery_type})
        if len(sent) >= 2 and random.random() < 0.30:
            await bot.send_message(chat_id, 'кстати, такой стиль тебе заходит?', reply_markup=photo_feedback_keyboard(request.scene))
    except PermissionError as exc:
        logger.info('photo denied user=%s reason=%s', telegram_id, exc)
        track_event(uid, 'photo_failed', metadata={'scene': request.scene, 'reason': str(exc), 'provider': 'access'})
        await bot.send_message(chat_id, 'этот вариант сейчас недоступен 😌')
    except PhotoGenerationError as exc:
        logger.warning('photo generation failed provider=%s reason=%s user=%s scene=%s', exc.provider, exc.reason, telegram_id, request.scene)
        track_event(uid, 'photo_failed', metadata={'scene': request.scene, 'reason': exc.reason, 'provider': exc.provider})
        debug_hint = f' ({exc.provider}/{exc.reason})' if exc.reason else ''
        await bot.send_message(chat_id, f'фото сейчас не получилось 😕{debug_hint}\nлимит не списан. можно повторить.', reply_markup=photo_retry_keyboard(request.scene))
    except Exception as exc:
        logger.exception('photo generation failed user=%s', telegram_id)
        track_event(uid, 'photo_failed', metadata={'scene': request.scene, 'reason': type(exc).__name__, 'provider': 'unknown'})
        await bot.send_message(chat_id, 'фото сейчас не получилось 😕 лимит не списан. можно повторить.', reply_markup=photo_retry_keyboard(request.scene))
    finally:
        ping.cancel()
        _photo_jobs.pop(telegram_id, None)


async def _start_photo_background(chat_id: int, telegram_id: int, request: PhotoRequest, delivery_type: str):
    active = _photo_jobs.get(telegram_id)
    if (active and not active.done()) or telegram_id in _photo_job_reservations:
        await bot.send_message(chat_id, 'я уже делаю тебе один сет 😄 сначала закончу его')
        return False
    _photo_job_reservations.add(telegram_id)
    try:
        # Always check budget and show the generating message — AI generation
        # is the primary route now, library/community are fallbacks only.
        if delivery_type in {'free', 'story'}:
            allowed, reason = budget_allows_photo()
            if not allowed:
                logger.error('image budget guard blocked generation reason=%s user=%s', reason, telegram_id)
                track_event(ensure_user(telegram_id), 'photo_budget_blocked', metadata={'scene': request.scene, 'reason': reason})
                await bot.send_message(chat_id, 'с фото сейчас техническая пауза 😕 попробуй чуть позже. лимит не списан.')
                return False
        await bot.send_message(chat_id, random.choice((
            'сек 😄 сейчас выберу нормальные кадры',
            'погоди чуть-чуть 😌 хочу сделать красиво',
            'сейчас 🙂 не хочу отправлять первый попавшийся кадр',
        )))
        task = asyncio.create_task(_run_photo_background(chat_id, telegram_id, request, delivery_type))
        _photo_jobs[telegram_id] = task
        return True
    finally:
        _photo_job_reservations.discard(telegram_id)


async def handle_photo_request(chat_id: int, telegram_id: int, request: PhotoRequest):
    db_uid = ensure_user(telegram_id)
    if not has_accepted(telegram_id):
        await bot.send_message(chat_id, 'Сначала подтверди 18+ и условия через /start.', reply_markup=consent_keyboard())
        return
    track_event(db_uid, 'photo_requested', metadata={'scene': request.scene, 'customized': bool(request.customized)})
    observe_photo_preference(db_uid, request.scene, request.clothing, request.hairstyle, request.location, get_user_character(telegram_id))
    stage = get_relationship_stage(telegram_id, get_user_character(telegram_id))
    if not scene_allowed_for_stage(request.scene, stage):
        track_event(db_uid, 'photo_locked_view', metadata={'scene': request.scene, 'level': get_relationship_level(telegram_id, get_user_character(telegram_id))})
        await bot.send_message(chat_id, 'такой образ я пока оставлю при себе 😏')
        return

    if requires_adult_confirmation(request) and not is_adult_confirmed(telegram_id):
        _pending_adult_photo[telegram_id] = request
        await bot.send_message(chat_id, 'для более смелых fashion-образов нужно один раз подтвердить, что тебе 18+.', reply_markup=adult_keyboard())
        return

    if telegram_id in ADMIN_TELEGRAM_IDS:
        await _start_photo_background(chat_id, telegram_id, request, 'admin')
        return

    if is_custom_request(request):
        track_event(db_uid, 'paywall_view', metadata={'product': 'custom_photo', 'scene': request.scene})
        await _offer_custom_photo(chat_id, telegram_id, request)
        return

    credits = get_photo_credits(telegram_id)
    if has_free_photo(telegram_id, get_user_character(telegram_id)):
        await _start_photo_background(chat_id, telegram_id, request, 'free')
        return
    if credits > 0:
        await _start_photo_background(chat_id, telegram_id, request, 'credit')
        return

    offer_id = create_offer(telegram_id, request)
    track_event(db_uid, 'paywall_view', metadata={'product': 'photo', 'scene': request.scene, 'stars': PHOTO_COST_STARS})
    await bot.send_message(chat_id, f'бесплатный лимит на сегодня использован. следующее фото — {PHOTO_COST_STARS}⭐ ✨')
    await send_stars_invoice(chat_id, 'Фото Анны', f'Новый сет до 3 фото: {PHOTO_LABELS.get(request.scene, request.scene)}', f'photo:{offer_id}', PHOTO_COST_STARS)


@dp.message(CommandStart())
async def start(message: types.Message, command: CommandObject):
    name = message.from_user.first_name or message.from_user.username or 'ты'
    uid = ensure_user(message.from_user.id, name, language_code=message.from_user.language_code)
    track_event(uid, 'onboarding_started')

    # Referral: a new user may have arrived via https://t.me/<bot>?start=ref_<referrer_id>.
    # We only STASH the referrer id here — the bonus itself is granted only after
    # the invitee accepts the 18+/terms gate, so referral farming via throwaway
    # accounts that never confirm is impossible and the wow-bonus always lands
    # at the moment the user is actually allowed to use the bot.
    referrer_id = parse_referral_payload(command.args)
    has_referral = bool(referrer_id)
    if has_referral:
        remember_referral(message.from_user.id, referrer_id)
        track_event(uid, 'referral_link_opened', metadata={'referrer_id': str(referrer_id)})
    track_event(uid, 'onboarding_completed')

    if not has_accepted(message.from_user.id):
        welcome = (
            f'привет, {name} 🙂 я — AI-подруга, которая всегда рядом.\n\n'
            'Что я умею:\n'
            '💬 живое общение с памятью и характером\n'
            '❤️ отношения по уровням 1–6 — с каждым уровнем ближе и откровеннее\n'
            '📸 реалистичные фото по твоим сценариям\n'
            '🎬 оживление фото в AI-видео\n'
            '🎙 голосовые ответы на твоём языке\n'
            '🎯 интерактивные истории с выбором\n\n'
        )
        welcome += '🎁 после подтверждения 18+ ты получишь бесплатные фото-кредиты на первое фото — это наш подарок за знакомство.\n\n'
        if has_referral:
            welcome += 'пришёл по приглашению друга — бонусы начислятся вам обоим сразу после подтверждения.\n\n'
        welcome += 'Перед началом подтверди, что тебе 18+, и прими условия использования и политику конфиденциальности.'
        await message.answer(welcome, reply_markup=consent_keyboard())
        return

    # Returning user who already accepted: apply any pending referral/bonus now
    # (idempotent — no-op if already granted). Wrapped in a per-user lock to
    # avoid double-grants on concurrent /start re-entries.
    async with referral_user_lock(message.from_user.id):
        ref = pending_referral(message.from_user.id)
        if ref:
            apply_referral(message.from_user.id, ref)
        first_start = apply_first_start_bonuses(message.from_user.id)
        if first_start['credits'] or first_start['trial_days']:
            track_event(uid, 'first_start_bonus_granted', metadata=first_start)
    # Surface the user's own referral link so they can invite friends right away.
    try:
        me = await message.bot.get_me()
        ref_link = referral_link(me.username, message.from_user.id)
        ref_hint = f'\n\n🔗 твоя ссылка для приглашения друзей:\n{ref_link}\nза каждого друга, который подтвердит 18+, ты получишь {REFERRAL_REFERRER_CREDITS}, а друг — {REFERRAL_INVITEE_CREDITS} фото-кредитов.'
    except Exception:
        ref_hint = '\n\nприглашай друзей командой /referral — бонусы за обоих.'
    await message.answer(
        f'с возвращением, {name} 🙂 если ещё не забрал — у тебя могут быть бесплатные фото-кредиты на первое фото.\n'
        'нажми «✅ Возможности» или просто отправь мне сообщение.'
        + ref_hint,
        reply_markup=onboarding_character_keyboard(),
    )


@dp.callback_query(F.data == 'consent:accept')
async def consent_accept(cq: types.CallbackQuery):
    accept_consent(cq.from_user.id)
    set_adult_confirmed(cq.from_user.id, True)
    uid = ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    track_event(uid, 'consent_accepted', metadata={'terms': TERMS_VERSION, 'privacy': PRIVACY_VERSION})
    # Wow-effect + referral payout happen HERE, after consent — wrapped in a
    # per-user lock so a double-tap on the consent button can't double-grant.
    async with referral_user_lock(cq.from_user.id):
        ref = pending_referral(cq.from_user.id)
        if ref:
            res = apply_referral(cq.from_user.id, ref)
            if res.get('awarded'):
                track_event(uid, 'referral_awarded_on_consent', metadata={'referrer_id': str(ref)})
        first_start = apply_first_start_bonuses(cq.from_user.id)
    await cq.answer('готово')
    # Show the user their own referral link right after consent so they can
    # invite friends immediately, and announce the wow-bonus.
    try:
        me = await cq.bot.get_me()
        ref_link = referral_link(me.username, cq.from_user.id)
    except Exception:
        ref_link = None
    bonus_line = (
        f'🎁 добро пожаловать! подарил тебе {first_start["credits"]} фото-кредитов — '
        'попробуй первое фото бесплатно.\n'
        'Выбери персонажа и начни общаться:'
    ) if first_start['credits'] else 'Отлично 🙂 теперь выбери персонажа:'
    ref_line = ''
    if ref_link:
        ref_line = (
            f'\n\n🔗 твоя ссылка для приглашения друзей:\n{ref_link}\n'
            f'за каждого друга, который подтвердит 18+, ты получишь {REFERRAL_REFERRER_CREDITS}, '
            f'а друг — {REFERRAL_INVITEE_CREDITS} фото-кредитов.'
        )
    await cq.message.answer(bonus_line + ref_line, reply_markup=onboarding_character_keyboard())


@dp.callback_query(F.data == 'consent:terms')
async def consent_terms(cq: types.CallbackQuery):
    await cq.answer()
    await cq.message.answer('📄 Условия: сервис предоставляет общение с вымышленным взрослым AI-персонажем. Покупки цифровых функций внутри Telegram проводятся через Stars. Не используйте сервис для незаконных целей. /terms — полная краткая версия.')

@dp.callback_query(F.data == 'consent:privacy')
async def consent_privacy(cq: types.CallbackQuery):
    await cq.answer()
    await cq.message.answer('🔐 Privacy: бот хранит Telegram ID, сообщения, память, настройки, прогресс отношений и данные покупок, необходимые для работы сервиса. Чувствительные данные намеренно не извлекаются в память. /privacy — подробнее; /delete_me — удалить данные.')


async def _send_onboarding_character_card(chat_id: int, character_id: str, viewer_id: int):
    card = get_card(character_id)
    if not card:
        await bot.send_message(chat_id, 'карточка сейчас недоступна')
        return
    text_value = f'{card.button_emoji} {card.display_name}, {card.age}\n\n{card.short_bio or "Описание скоро появится."}'
    if character_id == CHARACTER_ID:
        text_value += '\n\n❤️ Сейчас: знакомство · L1\n🎯 Первая история уже открыта'
    elif card.status == 'active':
        text_value += '\n\n❤️ Готова общаться — пиши ей!'
    if card.card_photo_file_id:
        await bot.send_photo(chat_id, card.card_photo_file_id, caption=text_value)
        return
    fallback = _character_fallback_photo(character_id)
    if fallback and fallback.exists():
        await bot.send_photo(chat_id, FSInputFile(fallback), caption=text_value)
        return
    await bot.send_message(chat_id, text_value)


@dp.callback_query(F.data.startswith('onboard:character:'))
async def onboarding_character_select(cq: types.CallbackQuery):
    character_id = cq.data.split(':', 2)[2]
    card = get_card(character_id)
    if not card or not card.is_visible:
        await cq.answer('персонаж сейчас недоступен', show_alert=True)
        return
    uid = ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    # Admins may open any character, including premium ones, for moderation/testing.
    is_admin = cq.from_user.id in ADMIN_TELEGRAM_IDS
    if card.status == 'premium' and not is_admin and not is_premium(cq.from_user.id):
        track_event(uid, 'fake_door_click', metadata={'feature': f'{character_id}_onboarding'})
        await _send_onboarding_character_card(cq.message.chat.id, character_id, cq.from_user.id)
        await cq.answer('⭐ Premium-персонаж')
        await cq.message.answer(
            f'⭐ {card.display_name} доступна с Premium.\n\n'
            f'Premium — {PREMIUM_MONTHLY_STARS} Stars на 30 дней.\n'
            'Нежная, заботливая и очень сексуальная — она будет спрашивать про твой день, слушать и создавать уют.\n',
            reply_markup=premium_keyboard(),
        )
        return
    if card.status not in ('active', 'premium'):
        track_event(uid, 'fake_door_click', metadata={'feature': f'{character_id}_onboarding'})
        await _send_onboarding_character_card(cq.message.chat.id, character_id, cq.from_user.id)
        await cq.answer('эта девушка пока закрыта', show_alert=True)
        await cq.message.answer('Пока полностью доступна Анна 👇', reply_markup=onboarding_character_keyboard())
        return
    # Active or premium-unlocked character: allow selection
    _user_character[cq.from_user.id] = character_id
    track_event(uid, 'character_selected', metadata={'character_id': character_id})
    await cq.answer(f'{card.display_name} выбрана')
    await _send_onboarding_character_card(cq.message.chat.id, character_id, cq.from_user.id)
    await cq.message.answer(abilities_text(), reply_markup=abilities_inline_keyboard())
    await cq.message.answer('Основное меню всегда внизу 👇', reply_markup=main_keyboard(cq.from_user.id in ADMIN_TELEGRAM_IDS))


@dp.callback_query(F.data == 'onboard:meet')
async def onboarding_meet(cq: types.CallbackQuery):
    uid = ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    track_event(uid, 'onboarding_meet')
    await cq.answer()
    await cq.message.answer('тогда без анкеты 😄 как тебя лучше называть — и что мне про тебя стоит знать первым?')


@dp.callback_query(F.data == 'onboard:abilities')
async def onboarding_abilities(cq: types.CallbackQuery):
    uid = ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    track_event(uid, 'onboarding_abilities')
    await cq.answer()
    await cq.message.answer(abilities_text(), reply_markup=abilities_inline_keyboard())


@dp.message(Command('features', 'abilities'))
async def features_cmd(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    await message.answer(abilities_text(), reply_markup=abilities_inline_keyboard())


@dp.message(F.text == '✨ Возможности')
async def features_button(message: types.Message):
    await features_cmd(message)


@dp.message(F.text == '👩 Персонажи')
async def characters_button(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    await message.answer('выбери персонажа 👇', reply_markup=characters_keyboard())


@dp.callback_query(F.data.startswith('character:view:'))
async def character_view(cq: types.CallbackQuery):
    character_id = cq.data.split(':', 2)[2]
    card = get_card(character_id)
    if not card or not card.is_visible:
        await cq.answer('карточка сейчас недоступна', show_alert=True)
        return
    uid = ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if card.status in {'soon', 'locked'}:
        track_event(uid, 'fake_door_click', metadata={'feature': f'{character_id}_character_card'})
    await cq.answer()
    await _send_character_card(cq.message.chat.id, character_id, viewer_id=cq.from_user.id)
    is_admin = cq.from_user.id in ADMIN_TELEGRAM_IDS
    can_open = card.status == 'active' or (card.status == 'premium' and (is_admin or is_premium(cq.from_user.id)))
    if can_open:
        _user_character[cq.from_user.id] = character_id
        track_event(uid, 'character_selected', metadata={'character_id': character_id})
        await cq.message.answer(
            f'✅ {card.display_name} выбрана. Можешь писать ей! 👇',
            reply_markup=main_keyboard(cq.from_user.id in ADMIN_TELEGRAM_IDS),
        )
        # V3.19.0: scenario hook as her cinematic opening line.
        hook = get_scenario_hook(character_id)
        if hook:
            await asyncio.sleep(1.0)
            await cq.message.answer(hook)
    elif card.status == 'premium' and not is_premium(cq.from_user.id) and not is_admin:
        await cq.message.answer(
            f'⭐ {card.display_name} — Premium-персонаж.\n'
            f'Открыть за {PREMIUM_MONTHLY_STARS} Stars на 30 дней:',
            reply_markup=premium_keyboard(),
        )


# Backward compatibility for buttons sent by V3.9.x.
@dp.callback_query(F.data == 'character:anna')
async def character_anna(cq: types.CallbackQuery):
    await cq.answer()
    await _send_character_card(cq.message.chat.id, 'anna_01', viewer_id=cq.from_user.id)


@dp.callback_query(F.data == 'character:alena_soon')
async def character_alena_soon(cq: types.CallbackQuery):
    uid = ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    track_event(uid, 'fake_door_click', metadata={'feature': 'alena_character_card'})
    await cq.answer()
    await _send_character_card(cq.message.chat.id, 'alena_01', viewer_id=cq.from_user.id)


@dp.message(Command('admin'))
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    _character_card_edit_sessions.pop(message.from_user.id, None)
    _payment_method_edit_sessions.pop(message.from_user.id, None)
    _photo_idea_edit_sessions.pop(message.from_user.id, None)
    ensure_default_cards()
    await message.answer('⚙️ Админка AnnaBot', reply_markup=admin_keyboard())


@dp.message(F.text == '🛠 Админка')
async def admin_panel_button(message: types.Message):
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    await admin_panel(message)


@dp.callback_query(F.data == 'admin:home')
async def admin_home(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    _character_card_edit_sessions.pop(cq.from_user.id, None)
    _payment_method_edit_sessions.pop(cq.from_user.id, None)
    _photo_idea_edit_sessions.pop(cq.from_user.id, None)
    await cq.answer()
    await cq.message.answer('⚙️ Админка AnnaBot', reply_markup=admin_keyboard())


@dp.callback_query(F.data == 'admin:premium_toggle')
async def admin_premium_toggle(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if is_premium(cq.from_user.id):
        revoke_premium(cq.from_user.id)
        track_event(ensure_user(cq.from_user.id), 'admin_premium_revoke')
        await cq.answer('Premium выключен', show_alert=False)
        text = '⭐ Тестовый Premium выключен.'
    else:
        grant_premium(cq.from_user.id)
        track_event(ensure_user(cq.from_user.id), 'admin_premium_grant')
        await cq.answer('Premium включён на 30 дней', show_alert=False)
        text = f'⭐ Тестовый Premium включён на 30 дней. Photo credits: {get_photo_credits(cq.from_user.id)}.'
    await cq.message.answer(text, reply_markup=admin_keyboard())


@dp.callback_query(F.data == 'admin:ideas')
async def admin_ideas(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    _photo_idea_edit_sessions.pop(cq.from_user.id, None)
    json_count, db_count = idea_counts()
    await cq.answer()
    await cq.message.answer(
        '💡 Идеи для фото\n\n'
        f'Встроенный банк: {json_count} идей (в коде, пополняется через data/photo_ideas.json)\n'
        f'Добавлено через админку: {db_count} идей (хранятся в БД, переживают деплой)\n\n'
        'Идеи автоматически подставляются в обычные фото, квесты и предложения Анны, '
        'когда пользователь не указал свои детали.',
        reply_markup=admin_ideas_keyboard(),
    )


@dp.callback_query(F.data == 'admin:ideaadd:start')
async def admin_idea_add_start(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    _photo_idea_edit_sessions[cq.from_user.id] = {'step': 'scene'}
    await cq.answer()
    await cq.message.answer(
        'Добавляем идею для фото.\n\n'
        'Шаг 1/3: отправь сцену одним словом из списка:\n'
        f"{', '.join(ALLOWED_IDEA_SCENES)}"
    )


@dp.callback_query(F.data == 'admin:ideadel:list')
async def admin_idea_delete_list(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    ideas = list_admin_ideas(10)
    await cq.answer()
    if not ideas:
        await cq.message.answer('Через админку пока ничего не добавлено — удалять нечего.', reply_markup=admin_ideas_keyboard())
        return
    rows = [
        [InlineKeyboardButton(text=f"❌ #{idea['id']} {idea['scene']}: {idea['location'][:44]}{'…' if len(idea['location']) > 44 else ''}", callback_data=f"admin:ideadel:{idea['id']}")]
        for idea in ideas
    ]
    rows.append([InlineKeyboardButton(text='⬅️ Идеи', callback_data='admin:ideas')])
    await cq.message.answer('Последние идеи, добавленные через админку. Нажми, чтобы удалить:', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data.startswith('admin:ideadel:'))
async def admin_idea_delete(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    try:
        idea_id = int(cq.data.rsplit(':', 1)[1])
    except ValueError:
        await cq.answer('сессия устарела', show_alert=True)
        return
    deleted = delete_admin_idea(idea_id)
    await cq.answer('удалено' if deleted else 'уже удалена')
    _, db_count = idea_counts()
    await cq.message.answer(
        f"Идея #{idea_id} удалена. Осталось админ-идей: {db_count}.",
        reply_markup=admin_ideas_keyboard(),
    )


async def _admin_idea_text_step(message: types.Message, sess: dict) -> None:
    value = (message.text or '').strip()
    step = sess.get('step')
    if step == 'scene':
        scene = value.lower()
        if scene not in ALLOWED_IDEA_SCENES:
            await message.answer(f"Такой сцены нет. Выбери из списка:\n{', '.join(ALLOWED_IDEA_SCENES)}")
            return
        sess['scene'] = scene
        sess['step'] = 'location'
        await message.answer(
            f'Сцена: {scene}.\n\n'
            'Шаг 2/3: опиши место по-английски одним сообщением (что в кадре, свет, атмосфера).\n'
            'Пример: a warm modern cocktail bar with amber pendant lights and a polished wooden counter'
        )
        return
    if step == 'location':
        if not (10 <= len(value) <= 400):
            await message.answer('Описание места должно быть от 10 до 400 символов, по-английски.')
            return
        sess['location'] = value
        sess['step'] = 'angle'
        await message.answer(
            'Шаг 3/3: опиши ракурс/позу по-английски (или отправь «-» без кавычек, если не важно).\n'
            'Пример: a casual photo seated at the bar counter with a colorful mocktail in frame'
        )
        return
    if step == 'angle':
        angle = '' if value in {'-', '—'} else value
        if len(angle) > 300:
            await message.answer('Ракурс до 300 символов.')
            return
        _photo_idea_edit_sessions.pop(message.from_user.id, None)
        idea_id = add_admin_idea(sess['scene'], sess['location'], angle, message.from_user.id)
        if idea_id is None:
            await message.answer('не получилось сохранить идею 😕 попробуй ещё раз через Админка → Идеи для фото.')
            return
        track_event(ensure_user(message.from_user.id), 'admin_idea_added', metadata={'scene': sess['scene'], 'idea_id': idea_id})
        await message.answer(
            f'Идея #{idea_id} добавлена ✅\n\n'
            f"Сцена: {sess['scene']}\nМесто: {sess['location']}\nРакурс: {angle or '(на усмотрение бота)'}\n\n"
            'Она сразу участвует в генерации фото.',
            reply_markup=admin_ideas_keyboard(),
        )


@dp.callback_query(F.data == 'admin:cards')
async def admin_cards(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    _character_card_edit_sessions.pop(cq.from_user.id, None)
    _payment_method_edit_sessions.pop(cq.from_user.id, None)
    await cq.answer()
    await cq.message.answer('👩 Карточки девушек\nИзменения сохраняются в PostgreSQL и переживают redeploy.', reply_markup=admin_cards_keyboard())


@dp.callback_query(F.data.startswith('admin:card:'))
async def admin_card_open(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    character_id = cq.data.split(':', 2)[2]
    _character_card_edit_sessions.pop(cq.from_user.id, None)
    await cq.answer()
    await cq.message.answer(_admin_card_summary(character_id), reply_markup=admin_card_keyboard(character_id))


@dp.callback_query(F.data.startswith('admin:preview:'))
async def admin_card_preview(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    character_id = cq.data.split(':', 2)[2]
    await cq.answer()
    await _send_character_card(cq.message.chat.id, character_id, viewer_id=cq.from_user.id, admin_preview=True)


@dp.callback_query(F.data.startswith('admin:cardedit:'))
async def admin_card_edit(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    _, _, character_id, field = cq.data.split(':', 3)
    if field not in {'display_name', 'age', 'short_bio', 'photo', 'gender'}:
        await cq.answer('неизвестное поле', show_alert=True)
        return
    if field == 'gender':
        await cq.answer()
        await cq.message.answer('Выбери пол персонажа:', reply_markup=_admin_gender_keyboard(f'admin:cardgender:{character_id}'))
        return
    _character_card_edit_sessions[cq.from_user.id] = {'character_id': character_id, 'field': field}
    prompts = {
        'display_name': 'Отправь новое имя одним сообщением.',
        'age': 'Отправь возраст числом от 18 до 99.',
        'short_bio': 'Отправь новое описание карточки. Можно несколько строк.',
        'photo': 'Отправь фотографию, которая должна быть обложкой карточки.',
    }
    await cq.answer()
    await cq.message.answer(prompts[field] + '\n\n/cancel — отменить редактирование')


@dp.callback_query(F.data.startswith('admin:cardadd:gender:'))
async def admin_card_add_gender(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    gender = cq.data.rsplit(':', 1)[1]
    sess = _character_card_edit_sessions.get(cq.from_user.id)
    if not sess or sess.get('mode') != 'add' or sess.get('step') != 'gender':
        await cq.answer('сессия устарела', show_alert=True)
        return
    sess['draft']['gender'] = gender
    sess['step'] = 'age'
    await cq.answer()
    await cq.message.answer('Шаг 4/5: отправь возраст числом (18–99).\n\n/cancel — отменить')


@dp.callback_query(F.data.startswith('admin:cardgender:'))
async def admin_card_set_gender(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    parts = cq.data.split(':', 3)
    if len(parts) != 3:
        await cq.answer('неверный формат', show_alert=True)
        return
    _, _, character_id, gender = parts
    try:
        update_card(character_id, gender=gender)
    except ValueError as exc:
        await cq.answer(str(exc), show_alert=True)
        return
    await cq.answer('пол обновлён')
    await cq.message.answer('✅ Карточка обновлена.\n\n' + _admin_card_summary(character_id), reply_markup=admin_card_keyboard(character_id))


@dp.callback_query(F.data.startswith('admin:status:'))
async def admin_card_status(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    character_id = cq.data.split(':', 2)[2]
    await cq.answer()
    await cq.message.answer('Выбери статус карточки:', reply_markup=admin_status_keyboard(character_id))


@dp.callback_query(F.data.startswith('admin:setstatus:'))
async def admin_card_set_status(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    _, _, character_id, status = cq.data.split(':', 3)
    update_card(character_id, status=status)
    await cq.answer('сохранено')
    await cq.message.answer(_admin_card_summary(character_id), reply_markup=admin_card_keyboard(character_id))


@dp.callback_query(F.data.startswith('admin:toggle:'))
async def admin_card_toggle(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    character_id = cq.data.split(':', 2)[2]
    card = get_card(character_id)
    if not card:
        await cq.answer('карточка не найдена', show_alert=True)
        return
    update_card(character_id, is_visible=not card.is_visible)
    await cq.answer('видимость изменена')
    await cq.message.answer(_admin_card_summary(character_id), reply_markup=admin_card_keyboard(character_id))


@dp.callback_query(F.data.startswith('admin:clearphoto:'))
async def admin_card_clear_photo(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    character_id = cq.data.split(':', 2)[2]
    update_card(character_id, card_photo_file_id=None)
    await cq.answer('фото убрано')
    await cq.message.answer(_admin_card_summary(character_id), reply_markup=admin_card_keyboard(character_id))


@dp.callback_query(F.data.startswith('admin:reset:'))
async def admin_card_reset(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    character_id = cq.data.split(':', 2)[2]
    reset_card(character_id)
    _character_card_edit_sessions.pop(cq.from_user.id, None)
    await cq.answer('карточка сброшена')
    await cq.message.answer(_admin_card_summary(character_id), reply_markup=admin_card_keyboard(character_id))


def _admin_gender_keyboard(prefix: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='👨 Мужской', callback_data=f'{prefix}:male'),
         InlineKeyboardButton(text='👩 Женский', callback_data=f'{prefix}:female')],
        [InlineKeyboardButton(text='🎭 Другое', callback_data=f'{prefix}:other')],
    ])


@dp.callback_query(F.data == 'admin:cardadd:start')
async def admin_card_add_start(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    _character_card_edit_sessions[cq.from_user.id] = {'mode': 'add', 'step': 'id'}
    await cq.answer()
    await cq.message.answer(
        'Добавляем нового персонажа.\n\n'
        'Шаг 1/5: отправь уникальный ID маленькими латинскими буквами, например «maria_01» или «luna».\n\n'
        '/cancel — отменить'
    )


@dp.callback_query(F.data.startswith('admin:carddelete:'))
async def admin_card_delete(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    character_id = cq.data.split(':', 2)[2]
    try:
        if delete_card(character_id):
            await cq.answer('удалено')
        else:
            await cq.answer('не найдена', show_alert=True)
    except ValueError as exc:
        await cq.answer(str(exc), show_alert=True)
        return
    _character_card_edit_sessions.pop(cq.from_user.id, None)
    await cq.message.answer('🎭 Карточки персонажей', reply_markup=admin_cards_keyboard())


@dp.callback_query(F.data == 'admin:payments')
async def admin_payments(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    _payment_method_edit_sessions.pop(cq.from_user.id, None)
    await cq.answer()
    await cq.message.answer(
        '💳 Способы оплаты\n\n'
        'Stars остаются обязательным checkout для цифровых покупок внутри Telegram.\n'
        'QR и ссылки можно хранить и менять здесь без deploy — для внешнего/нецифрового сценария.',
        reply_markup=admin_payments_keyboard(),
    )


@dp.callback_query(F.data.startswith('admin:payment:'))
async def admin_payment_open(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    try:
        method_id = int(cq.data.rsplit(':', 1)[1])
    except ValueError:
        return
    _payment_method_edit_sessions.pop(cq.from_user.id, None)
    await cq.answer()
    await cq.message.answer(_admin_payment_summary(method_id), reply_markup=admin_payment_keyboard(method_id))


@dp.callback_query(F.data.startswith('admin:paymentpreview:'))
async def admin_payment_preview(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    try:
        method_id = int(cq.data.rsplit(':', 1)[1])
    except ValueError:
        return
    await cq.answer()
    await _send_payment_preview(cq.message.chat.id, method_id)


@dp.callback_query(F.data.startswith('admin:paymentadd:'))
async def admin_payment_add(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    method_type = cq.data.rsplit(':', 1)[1]
    if method_type not in {'qr', 'link'}:
        await cq.answer('неизвестный тип', show_alert=True)
        return
    _payment_method_edit_sessions[cq.from_user.id] = {
        'mode': 'add', 'method_type': method_type, 'step': 'name', 'draft': {}
    }
    await cq.answer()
    label = 'QR-способа' if method_type == 'qr' else 'провайдера / ссылки'
    await cq.message.answer(f'Отправь название {label} одним сообщением.\n\n/cancel — отменить')


@dp.callback_query(F.data.startswith('admin:paymentedit:'))
async def admin_payment_edit(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    parts = cq.data.split(':', 3)
    if len(parts) != 4:
        return
    try:
        method_id = int(parts[2])
    except ValueError:
        return
    field = parts[3]
    if field not in {'display_name', 'instructions', 'qr', 'url'}:
        await cq.answer('неизвестное поле', show_alert=True)
        return
    method = get_payment_method(method_id)
    if not method or method.method_type == 'stars':
        await cq.answer('это системный способ', show_alert=True)
        return
    _payment_method_edit_sessions[cq.from_user.id] = {'mode': 'edit', 'method_id': method_id, 'field': field}
    prompts = {
        'display_name': 'Отправь новое название.',
        'instructions': 'Отправь текст инструкции для этого способа оплаты.',
        'qr': 'Отправь новое изображение QR-кода.',
        'url': 'Отправь HTTPS-ссылку провайдера.',
    }
    await cq.answer()
    await cq.message.answer(prompts[field] + '\n\n/cancel — отменить')


@dp.callback_query(F.data.startswith('admin:paymentstatus:'))
async def admin_payment_status(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    try:
        method_id = int(cq.data.rsplit(':', 1)[1])
    except ValueError:
        return
    method = get_payment_method(method_id)
    if not method or method.method_type == 'stars':
        await cq.answer('Stars остаются активными для цифровых покупок', show_alert=True)
        return
    await cq.answer()
    await cq.message.answer(
        'Статус относится к внешнему способу. Он не заменяет Stars для цифрового контента внутри Telegram.',
        reply_markup=admin_payment_status_keyboard(method_id),
    )


@dp.callback_query(F.data.startswith('admin:paymentsetstatus:'))
async def admin_payment_set_status(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    _, _, method_id_raw, status = cq.data.split(':', 3)
    try:
        method_id = int(method_id_raw)
    except ValueError:
        return
    try:
        update_payment_method(method_id, status=status)
    except ValueError as exc:
        await cq.answer(str(exc), show_alert=True)
        return
    await cq.answer('сохранено')
    await cq.message.answer(_admin_payment_summary(method_id), reply_markup=admin_payment_keyboard(method_id))


@dp.callback_query(F.data.startswith('admin:paymentdelete:'))
async def admin_payment_delete(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    try:
        method_id = int(cq.data.rsplit(':', 1)[1])
        delete_payment_method(method_id)
    except ValueError as exc:
        await cq.answer(str(exc), show_alert=True)
        return
    await cq.answer('удалено')
    await cq.message.answer('💳 Способ оплаты удалён.', reply_markup=admin_payments_keyboard())


@dp.callback_query(F.data.startswith('future:'))
async def future_feature_locked(cq: types.CallbackQuery):
    feature = cq.data.split(':', 1)[1]
    labels = {
        'animate_photo': '🎬 Оживить фото',
        'anna_call': '📞 Звонок с Анной',
    }
    await cq.answer(f'🔒 {labels.get(feature, "Функция")} — появится скоро.', show_alert=True)


@dp.callback_query(F.data == 'admin:library_help')
async def admin_library_help(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    await cq.answer()
    await cq.message.answer('📚 Импорт библиотеки: /libraryimport\nФото + готовое видео: отправляй фото → видео → следующее фото.\nСтатистика библиотеки: /librarystats\nПерегруппировка старых паков: /libraryregroup')


@dp.callback_query(F.data == 'admin:stats')
async def admin_stats_button(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    await cq.answer()
    snap = admin_snapshot()
    await cq.message.answer(
        '📊 Anna beta stats\n\n'
        f'Users: {snap["users_total"]} · active 24h: {snap["users_24h"]} · active 7d: {snap["users_7d"]}\n'
        f'Photo requests 24h: {snap["photo_requests_24h"]} · delivered sets: {snap["photos_24h"]}\n'
        f'Image cost: ${snap["photo_cost_24h"]:.2f}/24h · Stars 30d: {snap["stars_30d"]}'
    )


@dp.message(Command('cancel'))
async def cancel_admin_edit(message: types.Message):
    if message.from_user.id in _character_card_edit_sessions:
        sess = _character_card_edit_sessions.pop(message.from_user.id)
        if sess.get('mode') == 'add':
            await message.answer('добавление отменено', reply_markup=admin_cards_keyboard())
        else:
            await message.answer('редактирование отменено', reply_markup=admin_card_keyboard(sess['character_id']))
        return
    if message.from_user.id in _payment_method_edit_sessions:
        sess = _payment_method_edit_sessions.pop(message.from_user.id)
        method_id = sess.get('method_id')
        markup = admin_payment_keyboard(method_id) if method_id else admin_payments_keyboard()
        await message.answer('редактирование оплаты отменено', reply_markup=markup)
        return
    # V3.19.0: abort an in-flight constructor wizard (name/face entry steps).
    if message.from_user.id in _constructor_sessions:
        _constructor_sessions.pop(message.from_user.id, None)
        await message.answer('конструктор отменён. вернуться можно через «🎨 Мой персонаж».')


@dp.message(Command('plans', 'today'))
async def plans_cmd(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    state = ensure_life_state(message.from_user.id)
    await message.answer(
        f'сейчас по нашей истории я {state.activity or "занята своими делами"}. можешь немного повлиять на мой следующий план 😄',
        reply_markup=life_choice_keyboard(),
    )


@dp.callback_query(F.data.startswith('life:'))
async def life_choice_cb(cq: types.CallbackQuery):
    choice = cq.data.split(':', 1)[1]
    state = apply_life_choice(cq.from_user.id, choice)
    uid = ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    track_event(uid, 'life_choice', metadata={'choice': choice, 'location': state.location})
    await cq.answer('уговорил 😄')
    await cq.message.answer(f'ладно 😄 {state.activity}')


_library_moderation_sem = asyncio.Semaphore(5)


async def _library_photo_is_allowed(photo: types.PhotoSize) -> tuple[bool, str]:
    """Return (allowed, reason) for a Telegram photo before it enters the library.

    Library photos are intentionally kept non-explicit. If the moderation check
    itself fails, fail closed so an unverified image cannot accidentally appear
    at a low relationship level.
    """
    if not LIBRARY_MODERATION_ENABLED:
        return True, 'disabled'
    try:
        async with _library_moderation_sem:
            buf = io.BytesIO()
            await bot.download(photo, destination=buf)
            raw = buf.getvalue()
            data_url = 'data:image/jpeg;base64,' + base64.b64encode(raw).decode('ascii')
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    'https://api.openai.com/v1/moderations',
                    headers={'Authorization': f'Bearer {AI_KEY}', 'Content-Type': 'application/json'},
                    json={
                        'model': LIBRARY_MODERATION_MODEL,
                        'input': [{'type': 'image_url', 'image_url': {'url': data_url}}],
                    },
                )
            response.raise_for_status()
            result = response.json()['results'][0]
            categories = result.get('categories') or {}
            if categories.get('sexual/minors'):
                return False, 'sexual/minors'
            if categories.get('sexual'):
                return False, 'sexual'
            return True, 'ok'
    except Exception as exc:
        logger.warning('library moderation failed: %s', exc)
        return False, 'moderation_error'


@dp.message(Command('libraryimport'))
async def library_import_start(message: types.Message):
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    _library_import_sessions.pop(message.from_user.id, None)
    await message.answer('📚 Кого загружаем?', reply_markup=library_character_keyboard())


@dp.callback_query(F.data.startswith('libchar:'))
async def library_choose_character(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        await cq.answer('только для владельца', show_alert=True)
        return
    character_id = cq.data.split(':', 1)[1]
    await cq.answer()
    await cq.message.answer(f'{LIBRARY_CHARACTERS.get(character_id, character_id)} → выбери сцену:', reply_markup=library_scene_keyboard(character_id))


@dp.callback_query(F.data.startswith('libscene:'))
async def library_choose_scene(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    _, character_id, scene = cq.data.split(':', 2)
    await cq.answer()
    required = max(1, int(SCENE_LEVELS.get(scene, 1)))
    await cq.message.answer(
        f'{LIBRARY_CHARACTERS.get(character_id, character_id)} · {PHOTO_LABELS.get(scene, scene)}\n'
        f'Минимальный уровень этой сцены: L{required}. Выбери уровень отношений:',
        reply_markup=library_level_keyboard(character_id, scene),
    )


@dp.callback_query(F.data.startswith('liblevel:'))
async def library_choose_level(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    _, character_id, scene, level = cq.data.split(':', 3)
    chosen_level = int(level)
    required = max(1, int(SCENE_LEVELS.get(scene, 1)))
    if chosen_level < required:
        await cq.answer(f'эта сцена открывается с L{required}', show_alert=True)
        return
    sess = {
        'character_id': character_id,
        'scene': scene,
        'level': chosen_level,
        'mode': 'progression',
        'photos': [],
        'rejected': 0,
        'moderation_errors': 0,
        'preview': False,
    }
    _library_import_sessions[cq.from_user.id] = sess
    await cq.answer()
    status = await cq.message.answer(_library_upload_status_text(sess), reply_markup=library_import_controls())
    sess['status_chat_id'] = status.chat.id
    sess['status_message_id'] = status.message_id


@dp.callback_query(F.data.startswith('libmode:'))
async def library_choose_mode(cq: types.CallbackQuery):
    # Old V3.9.1 buttons may still be visible in Telegram. Treat any old mode as progression.
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    _, character_id, scene, level, _mode = cq.data.split(':', 4)
    sess = {
        'character_id': character_id,
        'scene': scene,
        'level': int(level),
        'mode': 'progression',
        'photos': [],
        'rejected': 0,
        'moderation_errors': 0,
        'preview': False,
    }
    _library_import_sessions[cq.from_user.id] = sess
    await cq.answer()
    status = await cq.message.answer(_library_upload_status_text(sess), reply_markup=library_import_controls())
    sess['status_chat_id'] = status.chat.id
    sess['status_message_id'] = status.message_id


@dp.callback_query(F.data == 'libimp:undo')
async def library_import_undo(cq: types.CallbackQuery):
    sess = _library_import_sessions.get(cq.from_user.id)
    if not sess:
        await cq.answer('нет активной загрузки', show_alert=True)
        return
    if sess['photos']:
        sess['photos'].pop()
    await cq.answer('последнее убрала')
    await _library_refresh_status(sess)


@dp.callback_query(F.data == 'libimp:finish')
async def library_import_finish(cq: types.CallbackQuery):
    sess = _library_import_sessions.get(cq.from_user.id)
    if not sess:
        await cq.answer('нет активной загрузки', show_alert=True)
        return
    count = len(sess['photos'])
    if count == 0:
        await cq.answer('сначала пришли фото', show_alert=True)
        return
    sess['preview'] = True
    await cq.answer()
    await _library_refresh_status(sess, preview=True)


@dp.callback_query(F.data == 'libimp:continue')
async def library_import_continue(cq: types.CallbackQuery):
    sess = _library_import_sessions.get(cq.from_user.id)
    if not sess:
        return
    sess['preview'] = False
    await cq.answer()
    await _library_refresh_status(sess)


@dp.callback_query(F.data == 'libimp:clear')
async def library_import_clear(cq: types.CallbackQuery):
    sess = _library_import_sessions.pop(cq.from_user.id, None)
    await cq.answer('очищено')
    await cq.message.answer('загрузка отменена. /libraryimport — начать заново')


@dp.callback_query(F.data == 'libimp:cancel')
async def library_import_cancel(cq: types.CallbackQuery):
    _library_import_sessions.pop(cq.from_user.id, None)
    await cq.answer('отменено')
    await cq.message.answer('загрузка отменена')


@dp.callback_query(F.data == 'libimp:save')
async def library_import_save(cq: types.CallbackQuery):
    sess = _library_import_sessions.get(cq.from_user.id)
    if not sess:
        await cq.answer('нет активной загрузки', show_alert=True)
        return
    ordered_photos = sorted(sess['photos'], key=lambda p: p.get('message_id', 0))
    result = import_buffered_photos(
        sess['character_id'], sess['scene'], sess['level'], 'progression', ordered_photos,
    )
    _library_import_sessions.pop(cq.from_user.id, None)
    await cq.answer('сохранено')
    tail = ''
    await cq.message.answer(
        f'✅ Библиотека обновлена\nПаков: {result["packs_created"]}\nФото: {result["photos_saved"]}\nВидео привязано: {result.get("videos_saved", 0)}{tail}\n\n/library — статистика'
    )


@dp.message(Command('library'))
async def library_stats_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    snap = library_stats()
    lines = [f'📚 Библиотека: {snap["total_photos"]} фото · 🎬 {snap.get("total_videos", 0)} видео · {snap["total_packs"]} паков']
    grouped = {}
    for (char_id, scene, level), values in snap['by_scene'].items():
        grouped.setdefault(char_id, []).append((scene, level, values))
    for char_id, rows in grouped.items():
        lines.append(f'\n{LIBRARY_CHARACTERS.get(char_id, char_id)}')
        for scene, level, values in sorted(rows, key=lambda x: (x[0], x[1])):
            lines.append(f'{PHOTO_LABELS.get(scene, scene)} · L{level}: {values["photos"]} фото · 🎬 {values.get("videos", 0)} / {values["packs"]} паков')
    if snap['total_photos'] == 0:
        lines.append('\nПока пусто. /libraryimport')
    await message.answer('\n'.join(lines[:80]))


@dp.message(Command('libraryregroup'))
async def library_regroup_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    parts = (message.text or '').split()
    if len(parts) != 4:
        await message.answer(
            'Формат: /libraryregroup <персонаж> <сцена> <уровень>\n'
            'Пример: /libraryregroup anna_01 selfie 1\n\n'
            'Команда собирает уже загруженные одиночные фото в сеты по 3 без повторной загрузки.'
        )
        return
    _, character_id, scene, level_text = parts
    try:
        level = int(level_text)
    except ValueError:
        await message.answer('Уровень должен быть числом от 1 до 6.')
        return
    result = regroup_collection_packs(character_id, scene, level)
    await message.answer(
        f'♻️ Перегруппировка завершена\n'
        f'{LIBRARY_CHARACTERS.get(character_id, character_id)} · {PHOTO_LABELS.get(scene, scene)} · L{level}\n'
        f'Создано сетов по 3: {result["packs_created"]}\n'
        f'Перенесено фото: {result["photos_regrouped"]}\n'
        f'Осталось одиночных фото: {result["leftover_single_photos"]}\n\n/library — проверить статистику'
    )


@dp.message(Command('help'))
async def help_cmd(message: types.Message):
    await message.answer(
        'просто пиши мне как обычно 🙂\n'
        '/photo — фото персонажа\n'
        '/premium · /buy — Premium и кредиты (Stars + Wallet Pay)\n'
        '/profile — прогресс, стрик, достижения и кредиты\n'
        '/collection — коллекция\n/stories — истории\n'
        '/voice · /voice_anon — голосовые ответы и анонимный режим\n'
        '/settings — настройки\n'
        '/wake 08:00 — разбудить\n/timezone Europe/Moscow — часовой пояс\n'
        '/reset — очистить переписку и память\n'
        '/privacy · /terms · /support · /delete_me'
    )


@dp.message(Command('settings'))
async def settings(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    user = get_user(message.from_user.id)
    credits = get_photo_credits(message.from_user.id)
    profile = get_profile(user.id, CHARACTER_ID) if user else None
    language = {'ru':'Русский','en':'English','zh':'中文','es':'Español','de':'Deutsch','fr':'Français','it':'Italiano','pt':'Português','uk':'Українська','ja':'日本語','ko':'한국어'}.get(getattr(profile, 'preferred_language', 'auto'), getattr(profile, 'preferred_language', 'Авто') if profile else 'Авто')
    await message.answer(
        f'Настройки персонажа\n\nЧасовой пояс: {user.timezone}\n'
        f'Язык общения: {language} · адаптируется автоматически\n'
        f'Голосовые ответы: {"вкл" if user.voice_enabled else "выкл"}\n'
        f'Голосовой аноним-режим: {"вкл" if user.voice_anon_mode else "выкл"}\n'
        f'Инициативные сообщения: {"вкл" if user.proactive_enabled else "выкл"}\n'
        f'Premium: {"активен" if is_premium(message.from_user.id) else "нет"}\n'
        f'Фото-кредиты: {credits}\n18+: {"подтверждено" if is_adult_confirmed(message.from_user.id) else "не подтверждено"}\n\n'
        'Стиль общения и знакомые выражения персонаж постепенно подхватывает сам.\n'
        '/voice · /voice_anon · /notifications · /timezone'
    )


@dp.message(Command('profile'))
async def profile_cmd(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    from services.gamification_service import get_profile_summary, format_profile_summary
    summary = get_profile_summary(message.from_user.id, get_user_character(message.from_user.id))
    await message.answer(format_profile_summary(summary))


@dp.message(Command('referral', 'invite'))
async def referral_cmd(message: types.Message):
    """Show the user's personal referral link and current invite stats."""
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    count = referral_count(message.from_user.id)
    try:
        me = await bot.get_me()
        link = referral_link(me.username or 'bot', message.from_user.id)
    except Exception:
        await message.answer('не удалось получить ссылку прямо сейчас, попробуй позже.')
        return
    from config import REFERRAL_REFERRER_CREDITS, REFERRAL_INVITEE_CREDITS
    text = (
        '🎁 поделись своим приглашением и получай бонусы\n\n'
        f'твоя ссылка: {link}\n\n'
        f'приятель, который перейдёт по ней и впервые запустит бота, получит {REFERRAL_INVITEE_CREDITS} фото-кредитов, а ты — {REFERRAL_REFERRER_CREDITS}.\n'
        f'уже приглашено: {count}\n\n'
        'отправь ссылку другу в личном сообщении, в свой канал или в сторис — чем больше переходов, тем больше кредитов.'
    )
    await message.answer(text)


@dp.message(Command('contest'))
async def contest_cmd(message: types.Message):
    """Monthly referral race: top inviters of the previous month get Premium automatically."""
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    # Idempotent: once a new month starts, the previous month's top-3 get
    # Premium automatically the first time anyone opens /contest.
    try:
        settlement = settle_monthly_contest()
    except Exception:
        logger.exception('contest settlement failed')
        settlement = None
    board = referral_leaderboard(limit=10, period_days=30)
    rank, total = referral_rank(message.from_user.id, period_days=30)
    lines = ['🏆 гонка пригласивших за 30 дней\n', 'топ-10 лидеров:']
    if not board:
        lines.append('пока нет ни одного приглашения — будь первым!')
    else:
        medals = {1: '🥇', 2: '🥈', 3: '🥉'}
        for row in board:
            medal = medals.get(row['rank'], f"{row['rank']}.")
            me = ' (это ты!)' if row['telegram_id'] == message.from_user.id else ''
            lines.append(f"{medal} {row['name']}{me} — {row['count']} пригл.")
    lines.append('')
    lines.append('призы: топ-3 по итогам месяца автоматически получают Premium на месяц. конкурс обновляется каждый месяц.')
    if settlement and not settlement['already_settled'] and settlement['winners']:
        lines.append(f"🎉 итоги за {settlement['month']}: победители уже получили Premium!")
    if rank > 0:
        lines.append(f'\nты сейчас на {rank} месте из {total} — пригласи ещё друзей командой /referral!')
    else:
        lines.append('\nты пока не в гонке — начни с /referral, чтобы получить свою ссылку.')
    await message.answer('\n'.join(lines))


@dp.message(Command('adult'))
async def adult_cmd(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    await message.answer('подтверди возраст для более смелых fashion-категорий:', reply_markup=adult_keyboard())


@dp.callback_query(F.data == 'age:yes')
async def age_yes(cq: types.CallbackQuery):
    set_adult_confirmed(cq.from_user.id, True)
    await cq.answer('18+ подтверждено')
    await cq.message.answer('готово 🙂')
    if cq.from_user.id in _pending_adult_custom:
        _pending_adult_custom.discard(cq.from_user.id)
        await start_custom_flow(cq.message.chat.id, cq.from_user.id)
        return
    req = _pending_adult_photo.pop(cq.from_user.id, None)
    if req:
        await handle_photo_request(cq.message.chat.id, cq.from_user.id, req)


@dp.callback_query(F.data == 'age:no')
async def age_no(cq: types.CallbackQuery):
    set_adult_confirmed(cq.from_user.id, False)
    _pending_adult_photo.pop(cq.from_user.id, None)
    _pending_adult_custom.discard(cq.from_user.id)
    await cq.answer()
    await cq.message.answer('поняла. тогда оставим обычные фото 🙂')


@dp.message(Command('terms'))
async def terms_cmd(message: types.Message):
    await message.answer(
        f'📄 Условия использования · версия {TERMS_VERSION}\n\n'
        'Анна — вымышленный взрослый AI-персонаж, а не реальный человек. Сервис предназначен только для пользователей 18+. '
        'Цифровые покупки внутри Telegram оплачиваются Stars. Результаты AI могут быть неточными; сервис не заменяет профессиональную медицинскую, юридическую или финансовую помощь. '
        'Запрещено использовать сервис для незаконных действий, эксплуатации несовершеннолетних или нарушения прав других людей.\n\n'
        'По вопросам: /support · по оплате: /paysupport · удалить данные: /delete_me'
    )

@dp.message(Command('privacy'))
async def privacy_cmd(message: types.Message):
    await message.answer(
        f'🔐 Политика конфиденциальности · версия {PRIVACY_VERSION}\n\n'
        'Для работы бот хранит Telegram ID/имя, сообщения, сохранённые воспоминания, настройки, прогресс отношений, историю фото/коллекции и технические записи покупок. '
        'Память настроена не сохранять пароли, платёжные реквизиты, точные адреса, диагнозы, сексуальную историю и другие особо чувствительные категории. '
        'Данные используются для работы персонализации, поддержки и аналитики продукта. /reset очищает историю общения и память; /delete_me удаляет пользовательские данные целиком.'
    )

@dp.message(Command('support'))
async def support_cmd(message: types.Message):
    parts=(message.text or '').split(maxsplit=1)
    if len(parts)<2 or not parts[1].strip():
        await message.answer('Напиши: /support что произошло — сообщение уйдёт владельцу.')
        return
    text_value=parts[1].strip()[:1500]; delivered=False
    for admin_id in ADMIN_TELEGRAM_IDS:
        try:
            await bot.send_message(admin_id, f'🛟 Support\nuser: {message.from_user.id}\nname: {message.from_user.first_name or "—"}\n\n{text_value}')
            delivered=True
        except Exception:
            logger.exception('failed to forward support admin=%s', admin_id)
    track_event(ensure_user(message.from_user.id), 'support_request')
    await message.answer('Передала владельцу 🙂' if delivered else 'Запрос записан, но сейчас не удалось доставить сообщение.')

@dp.message(Command('delete_me'))
async def delete_me_cmd(message: types.Message):
    await message.answer('Это удалит переписку, память, отношения, настройки, историю коллекции/квестов и локальные записи покупок. Сам платёж в Telegram отменён не будет. Продолжить?', reply_markup=delete_confirm_keyboard())

@dp.callback_query(F.data == 'delete:confirm')
async def delete_confirm(cq: types.CallbackQuery):
    ok=delete_user_data(cq.from_user.id)
    clear_stage(cq.from_user.id)
    await cq.answer()
    await cq.message.answer('Твои данные удалены. Если захочешь вернуться — /start' if ok else 'Данных для удаления уже нет.')

@dp.callback_query(F.data == 'delete:cancel')
async def delete_cancel(cq: types.CallbackQuery):
    await cq.answer('отменено')
    await cq.message.answer('ничего не удаляла 🙂')

@dp.message(Command('paysupport'))
async def pay_support(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    parts = (message.text or '').split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer('Напиши одним сообщением: /paysupport что случилось с оплатой. Я передам это владельцу.')
        return
    text_value = parts[1].strip()[:1500]
    delivered = False
    for admin_id in ADMIN_TELEGRAM_IDS:
        try:
            await bot.send_message(
                admin_id,
                f'💳 Payment support\nuser: {message.from_user.id}\nname: {message.from_user.first_name or "—"}\n\n{text_value}',
            )
            delivered = True
        except Exception:
            logger.exception('failed to forward payment support to admin=%s', admin_id)
    track_event(ensure_user(message.from_user.id), 'payment_support_request')
    await message.answer('Сообщение по оплате передано владельцу.' if delivered else 'Запрос записан, но сейчас не удалось доставить его владельцу.')


@dp.message(Command('collection'))
async def collection_cmd(message: types.Message):
    if not has_accepted(message.from_user.id):
        await message.answer('Сначала /start и подтверждение 18+.'); return
    level=get_relationship_level(message.from_user.id, get_user_character(message.from_user.id))
    snap=collection_progress(message.from_user.id, get_user_character(message.from_user.id), level)
    lines=[f'📸 Коллекция Анны: {snap["seen"]}/{snap["total"]} открыто']
    for row in snap['per_level']:
        if row['unlocked']:
            lines.append(f'L{row["level"]} · {row["seen"]}/{row["total"]}' + (' ✅' if row['total'] and row['seen']>=row['total'] else ''))
        else:
            lines.append(f'L{row["level"]} · 🔒')
    await message.answer('\n'.join(lines))


def _gallery_caption(item: dict, index: int, total_on_page: int) -> str:
    when = item['created_at']
    stamp = when.strftime('%d.%m %H:%M') if when else 'недавно'
    dl_mark = '⬇' if item.get('downloadable') else ''
    return f'🖼 {index}/{total_on_page} · {item["scene"]}{dl_mark}\n{stamp}'


def _gallery_keyboard(page: int, total_pages: int) -> types.InlineKeyboardMarkup:
    """Grid of gallery items on one page + page navigation."""
    rows: list[list[types.InlineKeyboardButton]] = []
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_gallery_page(chat_id: int, telegram_id: int, page: int = 0, *, edit: types.Message | None = None) -> None:
    snap = get_gallery_page(telegram_id, page)
    items = snap['items']
    total_pages = snap['pages']
    total = snap['total']
    if total == 0:
        text = (
            '🖼 Твоя галерея пуста.\n\n'
            'Попроси у Анны фото — и все твои кадры появятся здесь, с возможностью '
            f'скачать их в полном разрешении за {GALLERY_DOWNLOAD_STARS}⭐ каждый.'
        )
        if edit:
            await edit.edit_text(text)
        else:
            await bot.send_message(chat_id, text)
        return

    header = (
        f'🖼 Твоя галерея · {total} фото · стр. {snap["page"] + 1}/{total_pages}\n\n'
        'Нажми на фото — открою его в полном размере с кнопками «Оживить» и «Скачать».\n'
        f'Платное скачивание: {GALLERY_DOWNLOAD_STARS}⭐ за кадр в полном разрешении (без Telegram-сжатия).'
    )
    # Render each item as a small photo message with its own action row.
    if edit:
        await edit.edit_text(header)
    else:
        await bot.send_message(chat_id, header)
    for local_idx, item in enumerate(items, start=1):
        row_buttons: list[types.InlineKeyboardButton] = [
            types.InlineKeyboardButton(
                text=f'👁 {local_idx}. {item["scene"]}',
                callback_data=f'gallery:view:{item["id"]}',
            ),
        ]
        if item.get('downloadable'):
            row_buttons.append(
                types.InlineKeyboardButton(
                    text=f'⬇ Скачать {local_idx} · {GALLERY_DOWNLOAD_STARS}⭐',
                    callback_data=f'gallery:dl:{item["id"]}',
                )
            )
        else:
            row_buttons.append(
                types.InlineKeyboardButton(
                    text=f'⬇ {local_idx} · без байтов',
                    callback_data=f'gallery:no_dl:{item["id"]}',
                )
            )
        row_buttons.append(
            types.InlineKeyboardButton(
                text=f'🎬 {local_idx}',
                callback_data=f'gallery:animate:{item["id"]}',
            )
        )
        kb = types.InlineKeyboardMarkup(inline_keyboard=[row_buttons])
        try:
            await bot.send_photo(
                chat_id, item['telegram_file_id'],
                caption=_gallery_caption(item, local_idx, len(items)),
                reply_markup=kb,
            )
        except Exception:
            await bot.send_message(
                chat_id, _gallery_caption(item, local_idx, len(items)),
                reply_markup=kb,
            )
    # Page navigation row.
    nav: list[types.InlineKeyboardButton] = []
    if snap['page'] > 0:
        nav.append(types.InlineKeyboardButton(text='◀', callback_data=f'gallery:page:{snap["page"] - 1}'))
    nav.append(types.InlineKeyboardButton(text=f'{snap["page"] + 1} / {total_pages}', callback_data='gallery:noop'))
    if snap['page'] + 1 < total_pages:
        nav.append(types.InlineKeyboardButton(text='▶', callback_data=f'gallery:page:{snap["page"] + 1}'))
    await bot.send_message(chat_id, 'страницы 👇', reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[nav]))


@dp.message(Command('gallery', 'photos'))
async def gallery_cmd(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    if not has_accepted(message.from_user.id):
        await message.answer('Сначала /start и подтверждение 18+.'); return
    track_event(ensure_user(message.from_user.id), 'gallery_opened')
    await _send_gallery_page(message.chat.id, message.from_user.id, page=0)


@dp.callback_query(F.data.startswith('gallery:page:'))
async def gallery_page_cb(cq: types.CallbackQuery):
    try:
        page = int(cq.data.split(':', 2)[2])
    except ValueError:
        await cq.answer(); return
    await cq.answer()
    track_event(ensure_user(cq.from_user.id), 'gallery_page', metadata={'page': page})
    await _send_gallery_page(cq.message.chat.id, cq.from_user.id, page=page, edit=cq.message)


@dp.callback_query(F.data == 'gallery:noop')
async def gallery_noop_cb(cq: types.CallbackQuery):
    await cq.answer()


@dp.callback_query(F.data.startswith('gallery:view:'))
async def gallery_view_cb(cq: types.CallbackQuery):
    try:
        delivery_id = int(cq.data.split(':', 2)[2])
    except ValueError:
        await cq.answer('не понял', show_alert=True); return
    delivery = get_photo_delivery_for_user(cq.from_user.id, delivery_id)
    if not delivery or not delivery.get('telegram_file_id'):
        await cq.answer('это фото уже недоступно', show_alert=True); return
    await cq.answer()
    # Show the photo full-size with a clean action row: animate / download / back.
    row = [
        types.InlineKeyboardButton(text=f'🎬 Оживить · {VIDEO_COST_STARS}⭐', callback_data=f'gallery:animate:{delivery_id}'),
        types.InlineKeyboardButton(text=f'⬇ Скачать · {GALLERY_DOWNLOAD_STARS}⭐', callback_data=f'gallery:dl:{delivery_id}'),
        types.InlineKeyboardButton(text='↩ назад', callback_data='gallery:back'),
    ]
    kb = types.InlineKeyboardMarkup(inline_keyboard=[row])
    try:
        await bot.send_photo(
            cq.message.chat.id, delivery['telegram_file_id'],
            caption=f'🖼 {delivery["scene"]} · открыто {delivery["created_at"].strftime("%d.%m %H:%M") if delivery.get("created_at") else "недавно"}',
            reply_markup=kb,
        )
    except Exception:
        await bot.send_message(
            cq.message.chat.id,
            f'🖼 {delivery["scene"]} — не могу показать фото, но оно в коллекции.',
            reply_markup=kb,
        )


@dp.callback_query(F.data == 'gallery:back')
async def gallery_back_cb(cq: types.CallbackQuery):
    await cq.answer()
    track_event(ensure_user(cq.from_user.id), 'gallery_opened')
    await _send_gallery_page(cq.message.chat.id, cq.from_user.id, page=0, edit=cq.message)


@dp.callback_query(F.data.startswith('gallery:dl:'))
async def gallery_download_cb(cq: types.CallbackQuery):
    try:
        delivery_id = int(cq.data.split(':', 2)[2])
    except ValueError:
        await cq.answer('не понял', show_alert=True); return
    snap = get_gallery_item_bytes(cq.from_user.id, delivery_id)
    if not snap:
        await cq.answer('это фото нельзя скачать (нет исходных байтов)', show_alert=True); return
    await cq.answer()
    track_event(ensure_user(cq.from_user.id), 'gallery_download_invoice', metadata={'delivery_id': delivery_id})
    await send_stars_invoice(
        cq.message.chat.id,
        'Скачать фото в полном разрешении',
        f'Отправлю этот кадр как документ — без Telegram-сжатия, {snap["filename"]}',
        f'gallery_dl:{delivery_id}',
        GALLERY_DOWNLOAD_STARS,
    )


@dp.callback_query(F.data.startswith('gallery:no_dl:'))
async def gallery_no_download_cb(cq: types.CallbackQuery):
    await cq.answer('это фото нельзя скачать — оно было выдано без сохранения исходных байтов', show_alert=True)


@dp.callback_query(F.data.startswith('gallery:animate:'))
async def gallery_animate_cb(cq: types.CallbackQuery):
    try:
        delivery_id = int(cq.data.split(':', 2)[2])
    except ValueError:
        await cq.answer('не понял', show_alert=True); return
    delivery = get_photo_delivery_for_user(cq.from_user.id, delivery_id)
    if not delivery or not delivery.get('telegram_file_id'):
        await cq.answer('это фото уже не оживить — попроси у меня новое 🙂', show_alert=True); return
    await cq.answer()
    # V3.19.0: pick the motion first; the existing video gate runs after.
    await _show_video_preset_menu(cq.message.chat.id, delivery['id'])



@dp.message(Command('stories', 'quests'))
async def stories_cmd(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    if not has_accepted(message.from_user.id):
        await message.answer('Сначала /start и подтверждение 18+.'); return
    await message.answer('🎯 Истории с Анной\n\n🟢 доступно — можно начать сейчас\n🔒 закрыто — откроется с новым уровнем отношений\n✅ пройдено — выбор уже стал частью вашей истории\n\nПервый выбор становится каноном. Альтернативную ветку можно посмотреть позже, не переписывая основной сюжет.', reply_markup=stories_keyboard(message.from_user.id))

@dp.callback_query(F.data == 'quest:list')
async def quest_list_cb(cq: types.CallbackQuery):
    await cq.answer(); await cq.message.answer('🎯 Истории с Анной\n\nВыбирай открытую историю или посмотри, на каком уровне откроются следующие.', reply_markup=stories_keyboard(cq.from_user.id))

@dp.callback_query(F.data.startswith('quest:locked:'))
async def quest_locked_cb(cq: types.CallbackQuery):
    key = cq.data.split(':', 2)[2]
    q = get_quest(key)
    if not q:
        await cq.answer('история пока недоступна', show_alert=True)
        return
    await cq.answer(f'🔒 «{q["title"]}» откроется на L{q["min_level"]}. Продолжай общаться с Анной.', show_alert=True)

@dp.callback_query(F.data == 'quest:done')
async def quest_done_cb(cq: types.CallbackQuery):
    await cq.answer('Эта ветка уже открыта 🙂')

@dp.callback_query(F.data.startswith('quest:view:'))
async def quest_view_cb(cq: types.CallbackQuery):
    key=cq.data.split(':',2)[2]; q=get_quest(key)
    if not q or get_relationship_level(cq.from_user.id, get_user_character(cq.from_user.id))<q['min_level']:
        await cq.answer('пока закрыто', show_alert=True); return
    await cq.answer(); await cq.message.answer(f'🎯 {q["title"]}\n\n{q.get("teaser", "")}\n\n{q["intro"]}\n\nПервый выбор станет частью вашей основной истории.', reply_markup=quest_routes_keyboard(cq.from_user.id,key))

@dp.callback_query(F.data.startswith('quest:route:'))
async def quest_route_cb(cq: types.CallbackQuery):
    _,_,quest_key,route_key=cq.data.split(':',3)
    result=complete_route(cq.from_user.id,quest_key,route_key,paid_replay=False)
    if result.get('needs_payment'):
        if consume_premium_replay(cq.from_user.id,quest_key,route_key):
            result=complete_route(cq.from_user.id,quest_key,route_key,paid_replay=True)
            await cq.answer('Premium replay использован ✨')
            await cq.message.answer('👑 Premium replay\n\n'+result['route']['result'], reply_markup=quest_routes_keyboard(cq.from_user.id,quest_key))
            scene=result['route'].get('photo_scene')
            if scene: await _start_photo_background(cq.message.chat.id,cq.from_user.id,PhotoRequest(scene=scene),'story')
            return
        offer_id=create_replay_offer(cq.from_user.id,quest_key,route_key)
        await cq.answer()
        await send_stars_invoice(cq.message.chat.id,'Альтернативная история',f'Посмотреть другой вариант: {get_quest(quest_key)["title"]}',f'quest_replay:{offer_id}',QUEST_REPLAY_STARS)
        return
    await cq.answer(); track_event(ensure_user(cq.from_user.id),'quest_route_completed',metadata={'quest':quest_key,'route':route_key,'canonical':result.get('canonical',False)})
    await cq.message.answer(result['route']['result'], reply_markup=quest_routes_keyboard(cq.from_user.id,quest_key))
    scene=result['route'].get('photo_scene')
    if scene:
        # Story reward: generate/deliver without consuming the daily free quota.
        await _start_photo_background(cq.message.chat.id,cq.from_user.id,PhotoRequest(scene=scene),'story')

async def _run_video_background(chat_id: int, telegram_id: int, delivery_id: int, charge_id: str | None = None, motion_preset: str | None = None) -> None:
    """Animate a delivered photo with automatic engine fallback.

    V3.19.5 order: Gemini/Veo first again (owner decision), then Replicate,
    fal.ai, then the free HF route (which walks its own list of public spaces
    internally). The V3.19.3 key gate keeps a broken Gemini key out of the
    chain. The user only hears about a failure when every available engine
    failed; a paid run is then refunded.
    """
    engine_errors: list[str] = []
    engine_names: list[str] = []
    try:
        delivery = get_photo_delivery_for_user(telegram_id, delivery_id)
        if not delivery or not delivery.get('telegram_file_id'):
            raise CloudVideoError('source_photo_missing')

        tg_file = await bot.get_file(delivery['telegram_file_id'])
        if not tg_file.file_path:
            raise CloudVideoError('telegram_file_path_missing')
        source = io.BytesIO()
        await bot.download_file(tg_file.file_path, destination=source)
        image_bytes = source.getvalue()
        if not image_bytes:
            raise CloudVideoError('telegram_download_empty')

        engines = []
        # V3.19.5: Gemini/Veo is the primary engine again; Replicate (hailuo),
        # fal.ai and the free HF spaces are the fallback chain.
        if video_available():
            engines.append(('gemini', animate_image))
        if replicate_available():
            engines.append(('replicate', animate_image_replicate))
        if fal_available():
            engines.append(('fal', animate_image_fal))
        if hf_video_available():
            engines.append(('hf', animate_image_hf))
        if not engines:
            raise CloudVideoError('no_video_engine')
        engine_names = [name for name, _ in engines]

        # V3.19.0: a user-chosen motion preset wins; otherwise the scene-aware
        # sensual prompt applies to intimate scenes only.
        preset = VIDEO_PRESETS.get((motion_preset or '').strip())
        if preset:
            anim_prompt = preset[1]
        else:
            scene = delivery.get('scene')
            anim_prompt = SENSUAL_ANIMATION_PROMPT if scene in {'nude', 'tease', 'personal', 'lingerie', 'private_fashion'} else None

        await bot.send_message(chat_id, VIDEO_STATUS_TEXT)
        video_bytes = None
        used_engine = None
        last_error = None
        for idx, (engine_name, engine_fn) in enumerate(engines):
            try:
                if idx > 0:
                    await bot.send_message(chat_id, 'секунду, пробую ещё один способ снять это видео 🎬')
                video_bytes = await engine_fn(image_bytes, mime_type='image/jpeg', prompt=anim_prompt)
                used_engine = engine_name
                break
            except Exception as exc:
                last_error = exc
                engine_errors.append(f'{engine_name}: {type(exc).__name__}: {str(exc)[:160]}')
                logger.warning('video engine %s failed user=%s delivery=%s error=%s: %s',
                               engine_name, telegram_id, delivery_id, type(exc).__name__, str(exc)[:300])
        if video_bytes is None:
            raise last_error or CloudVideoError('no_video_result')

        await bot.send_video(
            chat_id,
            BufferedInputFile(video_bytes, filename='animated_photo.mp4'),
            caption='вот 😌🎬',
            supports_streaming=True,
        )
        track_event(
            ensure_user(telegram_id),
            f'{used_engine}_video_delivered',
            metadata={'source_delivery_id': delivery_id, 'scene': delivery.get('scene'), 'charge_id': charge_id or 'free'},
        )
    except Exception as exc:
        logger.exception('video failed user=%s delivery=%s charge=%s error=%s', telegram_id, delivery_id, charge_id, type(exc).__name__)
        refunded = False
        if charge_id:
            try:
                await bot.refund_star_payment(
                    user_id=telegram_id,
                    telegram_payment_charge_id=charge_id,
                )
                record_refund(telegram_id, charge_id, VIDEO_COST_STARS, product='video')
                refunded = True
            except Exception:
                logger.exception('Automatic video Stars refund failed user=%s charge=%s', telegram_id, charge_id)
        if refunded:
            await bot.send_message(chat_id, 'видео сейчас не получилось 😕 Stars автоматически вернул.')
        elif charge_id:
            await bot.send_message(chat_id, 'видео сейчас не получилось 😕 напиши /support — проверим оплату и возврат.')
        else:
            await bot.send_message(chat_id, 'видео сейчас не получилось 😕 попробуй чуть позже.')
        if telegram_id in ADMIN_TELEGRAM_IDS:
            # Owner diagnostic: exact reason chain so the pipeline can be fixed.
            configured = ', '.join(engine_names) or 'none'
            chain = ' | '.join(engine_errors) if engine_errors else 'no per-engine errors captured'
            await bot.send_message(
                chat_id,
                f'🔧 диагностика видео: {type(exc).__name__}: {str(exc)[:200]}\n'
                f'движки: {configured}\n'
                f'цепочка: {chain[:600]}',
            )
        track_event(
            ensure_user(telegram_id),
            'video_failed',
            metadata={'source_delivery_id': delivery_id, 'error_type': type(exc).__name__, 'error_message': str(exc)[:200], 'charge_id': charge_id or 'free', 'refunded': refunded},
        )
    finally:
        _video_jobs.pop(telegram_id, None)


@dp.message(Command('videotest'))
async def video_test_cmd(message: types.Message):
    """Owner diagnostic: animate my latest photo for free through the whole
    engine fallback chain, to see end-to-end how video generation works."""
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    if not _any_video_engine():
        await message.answer('видео-движки сейчас выключены.')
        return
    if message.from_user.id in _video_jobs and not _video_jobs[message.from_user.id].done():
        await message.answer('одно видео уже создаётся 🎬')
        return
    delivery = get_latest_photo_delivery(message.from_user.id)
    if not delivery or not delivery.get('telegram_file_id'):
        await message.answer('сначала попроси фото — оживлю последний кадр.')
        return
    _video_jobs[message.from_user.id] = asyncio.create_task(
        _run_video_background(message.chat.id, message.from_user.id, delivery['id'], None)
    )
    await message.answer('тест видео запущен: прогоню всю цепочку движков с автофолбэком 🎬')


def _video_preset_keyboard(delivery_id: int):
    """V3.19.0: motion preset picker shown before every animation."""
    rows = [
        [
            InlineKeyboardButton(text=VIDEO_PRESETS['kiss'][0], callback_data=f'videopreset:kiss:{delivery_id}'),
            InlineKeyboardButton(text=VIDEO_PRESETS['hug'][0], callback_data=f'videopreset:hug:{delivery_id}'),
        ],
        [
            InlineKeyboardButton(text=VIDEO_PRESETS['dance'][0], callback_data=f'videopreset:dance:{delivery_id}'),
            InlineKeyboardButton(text='✨ Авто', callback_data=f'videopreset:auto:{delivery_id}'),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_video_preset_menu(chat_id: int, delivery_id: int):
    await bot.send_message(
        chat_id,
        '🎬 Как мне её оживить? Выбери движение — или оставь авто 🎥',
        reply_markup=_video_preset_keyboard(delivery_id),
    )


@dp.callback_query(F.data.startswith('videopreset:'))
async def video_preset_cb(cq: types.CallbackQuery):
    parts = cq.data.split(':')
    if len(parts) != 3:
        await cq.answer(); return
    # V3.19.12: data is 'videopreset:<preset>:<id>' — the first token is the
    # router prefix, the preset is the SECOND one. The old unpack treated
    # 'videopreset' as the preset and silently exited, so the kiss/hug/dance
    # buttons looked dead.
    _, preset, raw_id = parts
    if preset not in VIDEO_PRESETS and preset != 'auto':
        await cq.answer(); return
    try:
        delivery_id = int(raw_id)
    except ValueError:
        await cq.answer(); return
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True); return
    if not _any_video_engine():
        await cq.answer(_video_unavailable_text(cq.from_user.id), show_alert=True); return
    if cq.from_user.id in _video_jobs and not _video_jobs[cq.from_user.id].done():
        await cq.answer('Одно видео уже создаётся 🎬', show_alert=True); return
    delivery = get_photo_delivery_for_user(cq.from_user.id, delivery_id)
    if not delivery or not delivery.get('telegram_file_id'):
        await cq.answer('Это фото уже не оживить — попроси у меня новое 🙂', show_alert=True); return
    await cq.answer()
    await _video_gate(cq, delivery, preset if preset != 'auto' else None)


async def _video_gate(cq: types.CallbackQuery, delivery: dict, motion_preset: str | None = None) -> None:
    """Start the animation free (admin or Premium daily slot) or invoice Stars."""
    uid = ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    track_event(uid, 'video_animate_click', metadata={'delivery_id': delivery['id'], 'preset': motion_preset or 'auto'})
    free = cq.from_user.id in ADMIN_TELEGRAM_IDS
    if not free and is_premium(cq.from_user.id):
        free = consume_premium_video_free(cq.from_user.id)
    if free:
        track_event(uid, 'video_free_used', metadata={'delivery_id': delivery['id'], 'admin': cq.from_user.id in ADMIN_TELEGRAM_IDS})
        _video_jobs[cq.from_user.id] = asyncio.create_task(
            _run_video_background(cq.message.chat.id, cq.from_user.id, delivery['id'], None, motion_preset=motion_preset)
        )
        return
    # Preset rides along inside the invoice payload: video:<delivery_id>:<preset>
    payload = f'video:{delivery["id"]}:{motion_preset or "auto"}'
    await send_stars_invoice(
        cq.message.chat.id,
        'Оживить фото Анны',
        'Короткое AI-видео из выбранного фото. Генерация занимает 1–3 минуты.',
        payload,
        VIDEO_COST_STARS,
    )


@dp.callback_query(F.data.startswith('video:animate:'))
async def animate_photo_cb(cq: types.CallbackQuery):
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True)
        return
    if not _any_video_engine():
        await cq.answer(_video_unavailable_text(cq.from_user.id), show_alert=True)
        return
    if cq.from_user.id in _video_jobs and not _video_jobs[cq.from_user.id].done():
        await cq.answer('Одно видео уже создаётся 🎬', show_alert=True)
        return
    try:
        delivery_id = int(cq.data.split(':', 2)[2])
    except (ValueError, IndexError):
        await cq.answer()
        return
    delivery = get_photo_delivery_for_user(cq.from_user.id, delivery_id)
    if not delivery or not delivery.get('telegram_file_id'):
        await cq.answer('Это фото уже не оживить — попроси у меня новое 🙂', show_alert=True)
        return
    await cq.answer()
    await _show_video_preset_menu(cq.message.chat.id, delivery['id'])


@dp.callback_query(F.data == 'video:animate_last')
async def animate_last_photo_cb(cq: types.CallbackQuery):
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True)
        return
    if not _any_video_engine():
        await cq.answer(_video_unavailable_text(cq.from_user.id), show_alert=True)
        return
    if cq.from_user.id in _video_jobs and not _video_jobs[cq.from_user.id].done():
        await cq.answer('Одно видео уже создаётся 🎬', show_alert=True)
        return
    delivery = get_latest_photo_delivery(cq.from_user.id)
    if not delivery or not delivery.get('telegram_file_id'):
        await cq.answer('Сначала попроси у Анны фото — оживлю последний кадр.', show_alert=True)
        return
    await cq.answer()
    await _show_video_preset_menu(cq.message.chat.id, delivery['id'])


@dp.message(Command('geministatus'))
async def gemini_status_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    st = provider_status()
    await message.answer(
        '🧠 LLM status\n\n'
        f'OpenRouter: {"✅" if st["openrouter_key_present"] else "❌"} model: {st["openrouter_model"]}\n'
        f'OpenRouter URL: {st["openrouter_base_url"]}\n'
        f'Gemini (fallback): {"✅" if st["gemini_key_present"] else "❌"} model: {st["gemini_model"]}\n'
        f'Gemini Video: {"✅" if video_available() else "❌"} (primary, V3.19.5)\n'
        f'Replicate Video: {"✅" if replicate_available() else "❌"}\n'
        f'fal.ai Video: {"✅" if fal_available() else "❌"}\n'
        f'HF Video (paid engine): {"✅" if hf_video_available() else "❌"}'
    )


@dp.message(Command('premium'))
async def premium(message: types.Message):
    uid = ensure_user(message.from_user.id, message.from_user.first_name)
    if not has_accepted(message.from_user.id):
        await message.answer('Сначала подтверди 18+ и условия через /start.', reply_markup=consent_keyboard()); return
    track_event(uid, 'paywall_view', metadata={'product': 'premium_month', 'stars': PREMIUM_MONTHLY_STARS})
    if is_premium(message.from_user.id):
        await message.answer(f'Premium уже активен ✨\nФото-кредиты: {get_photo_credits(message.from_user.id)}\nQuest replay осталось в этом месяце: {premium_replays_left(message.from_user.id)}')
        return
    await message.answer(
        'Premium на 30 дней:\n• расширенная память и полный лимит сообщений\n'
        '• 12 дополнительных photo credits\n• 1 бесплатное оживление фото каждый день\n• 2 бесплатных replay альтернативных квест-веток в месяц\n• больше continuity и инициативных сообщений\n• ранний доступ к будущим функциям персонажей\n\n'
        'Бесплатные фото зависят от близости: 1–2 уровень — 1/день, 3–6 — 2/день.\n'
        'Отношения не покупаются — они развиваются из общения. Кастомные фото оплачиваются отдельно.\n\n'
        '💳 Цифровые покупки внутри Telegram оплачиваются через Telegram Stars.',
        reply_markup=premium_keyboard(),
    )


@dp.callback_query(F.data == 'buy:premium')
async def buy_premium(cq: types.CallbackQuery):
    ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True); return
    await cq.answer()
    await send_stars_invoice(cq.message.chat.id, 'Anna Premium', 'Premium-доступ на 30 дней', 'premium_month', PREMIUM_MONTHLY_STARS)


@dp.callback_query(F.data == 'fk:premium')
async def fk_premium(cq: types.CallbackQuery):
    """V3.19.6: card/SBP premium via FreeKassa payment link."""
    ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True); return
    if not FREEKASSA_ENABLED:
        await cq.answer('Оплата картой сейчас выключена — используй Stars ⭐', show_alert=True); return
    await cq.answer()
    order_id = freekassa_service.create_order(
        cq.from_user.id, 'premium_month', str(FREEKASSA_PREMIUM_PRICE_RUB),
    )
    link = freekassa_service.payment_url(order_id, FREEKASSA_PREMIUM_PRICE_RUB)
    await bot.send_message(
        cq.message.chat.id,
        f'💳 Оплата Premium картой / СБП — {FREEKASSA_PREMIUM_PRICE_RUB} ₽\n\n'
        f'{link}\n\n'
        'После оплаты премиум включится автоматически в течение минуты. '
        'Если что-то пойдёт не так — напиши /support.',
    )


@dp.callback_query(F.data.startswith('walletpay:'))
async def walletpay_callback(cq: types.CallbackQuery):
    ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True); return
    if not WALLET_PAY_ENABLED:
        await cq.answer('Wallet Pay не настроен', show_alert=True); return
    product = cq.data.split(':', 1)[1]
    stars = PREMIUM_MONTHLY_STARS if product == 'premium' else int(product.split(':')[-1])
    description = 'Anna Premium — 30 дней' if product == 'premium' else f'Пополнение на {stars} Stars'
    from services.wallet_pay_service import create_invoice
    invoice = await create_invoice(cq.from_user.id, 'premium_month' if product == 'premium' else 'topup', stars, description)
    if not invoice:
        await cq.answer('не удалось создать счёт', show_alert=True)
        return
    await cq.answer()
    await cq.message.answer(
        f'Счёт на {invoice["amount_usd"]:.2f} USD создан.\n\n'
        'Оплата криптовалютой (TON/USDT) или картой через Telegram Wallet:',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='💎 Оплатить в Wallet', url=invoice['payment_link'])],
            [InlineKeyboardButton(text='🔍 Проверить статус', callback_data=f'walletpay_status:{invoice["invoice_id"]}')],
        ]),
    )


@dp.callback_query(F.data.startswith('walletpay_status:'))
async def walletpay_status_callback(cq: types.CallbackQuery):
    invoice_id = cq.data.split(':', 1)[1]
    from services.wallet_pay_service import get_invoice_status
    status = await get_invoice_status(invoice_id)
    if not status:
        await cq.answer('не удалось получить статус', show_alert=True)
        return
    payment_status = status.get('status', status.get('paymentStatus', 'unknown'))
    await cq.answer(f'статус: {payment_status}')
    if payment_status in {'PAID', 'COMPLETED', 'paid', 'completed'}:
        from services.wallet_pay_service import process_webhook
        process_webhook(status)
        await cq.message.answer('✅ Оплата получена. Спасибо!')


@dp.pre_checkout_query()
async def pre_checkout(query: types.PreCheckoutQuery):
    payload=query.invoice_payload or ''
    amount=query.total_amount
    ok=(query.currency == 'XTR')
    if query.currency != 'XTR':
        ok=False
    elif payload=='premium_month':
        ok=amount==PREMIUM_MONTHLY_STARS
    elif payload.startswith('photo:'):
        ok=amount in {PHOTO_COST_STARS, CUSTOM_PHOTO_COST_STARS}
    elif payload.startswith('quest_replay:'):
        ok=amount==QUEST_REPLAY_STARS
    elif payload.startswith('video:'):
        # Payload format: video:<delivery_id>:<preset>
        try:
            delivery_id = int(payload.split(':')[1])
        except (ValueError, IndexError):
            ok = False
        else:
            ok = amount == VIDEO_COST_STARS and bool(get_photo_delivery_for_user(query.from_user.id, delivery_id)) and _any_video_engine()
    elif payload.startswith('constructor:'):
        ok = amount == CONSTRUCTOR_COST_STARS
    elif payload.startswith('gallery_dl:'):
        try:
            delivery_id = int(payload.split(':', 1)[1])
        except ValueError:
            ok = False
        else:
            ok = amount == GALLERY_DOWNLOAD_STARS and bool(get_gallery_item_bytes(query.from_user.id, delivery_id))
    elif payload.startswith('gift:'):
        gift = gifts_service.get(payload.split(':', 1)[1])
        ok = bool(gift) and amount == gifts_service.effective_cost(gift)
    elif payload.startswith('date:'):
        date = dates_service.get(payload.split(':', 1)[1])
        ok = bool(date) and amount == date.cost and date.min_level <= get_relationship_level(query.from_user.id, get_user_character(query.from_user.id))
    if not ok:
        logger.warning('pre_checkout rejected user=%s payload=%s amount=%s', query.from_user.id,payload,amount)
        await query.answer(ok=False,error_message='Сумма или товар изменились. Открой покупку заново.')
        return
    await query.answer(ok=True)


@dp.message(F.successful_payment)
async def successful_payment(message: types.Message):
    payment = message.successful_payment
    payload = payment.invoice_payload
    charge = payment.telegram_payment_charge_id
    if payload == 'premium_month':
        record_payment(message.from_user.id, 'premium_month', payment.total_amount, charge)
        track_event(ensure_user(message.from_user.id), 'stars_purchase', value=payment.total_amount, metadata={'product': 'premium_month'})
        await message.answer('готово ✨ Premium активирован на 30 дней, и я добавила 12 photo credits. Теперь под каждым моим фото есть кнопка «Оживить» — раз в день сделаю видео бесплатно 🎬')
        return

    if payload.startswith('quest_replay:'):
        try:
            offer_id=int(payload.split(':',1)[1])
        except ValueError:
            return
        offer=consume_replay_offer(message.from_user.id,offer_id)
        if not offer:
            await message.answer('Оплата прошла, но эта ветка уже устарела. Напиши /support — разберёмся.')
            return
        result=complete_route(message.from_user.id,offer['quest_key'],offer['route_key'],paid_replay=True)
        record_payment(message.from_user.id,'quest_replay',payment.total_amount,charge)
        track_event(ensure_user(message.from_user.id),'stars_purchase',value=payment.total_amount,metadata={'product':'quest_replay','quest':offer['quest_key'],'route':offer['route_key']})
        await message.answer('↩️ Альтернативная ветка открыта ✨\n\n'+result['route']['result'],reply_markup=quest_routes_keyboard(message.from_user.id,offer['quest_key']))
        scene=result['route'].get('photo_scene')
        if scene:
            await _start_photo_background(message.chat.id,message.from_user.id,PhotoRequest(scene=scene),'story')
        return

    if payload.startswith('video:'):
        # Payload format: video:<delivery_id>:<preset>
        parts = payload.split(':')
        try:
            delivery_id = int(parts[1])
        except (ValueError, IndexError):
            return
        motion_preset = parts[2] if len(parts) > 2 and parts[2] in VIDEO_PRESETS else None
        delivery = get_photo_delivery_for_user(message.from_user.id, delivery_id)
        if not delivery or (message.from_user.id in _video_jobs and not _video_jobs[message.from_user.id].done()):
            try:
                await bot.refund_star_payment(user_id=message.from_user.id, telegram_payment_charge_id=charge)
                record_refund(message.from_user.id, charge, payment.total_amount, product='video')
                await message.answer('этот запрос уже нельзя запустить, поэтому Stars сразу вернул 🙂')
            except Exception:
                logger.exception('Video pre-generation refund failed user=%s charge=%s', message.from_user.id, charge)
                await message.answer('не смог запустить видео. Напиши /support — проверим оплату.')
            return
        record_payment(message.from_user.id, 'video', payment.total_amount, charge)
        track_event(
            ensure_user(message.from_user.id),
            'stars_purchase',
            value=payment.total_amount,
            metadata={'product': 'video', 'source_delivery_id': delivery_id},
        )
        # One unified job: Gemini/Veo first, cloud + HF fallbacks otherwise,
        # with automatic engine fallback; auto-refunds Stars if all fail.
        task = asyncio.create_task(_run_video_background(message.chat.id, message.from_user.id, delivery_id, charge, motion_preset=motion_preset))
        _video_jobs[message.from_user.id] = task
        return

    if payload.startswith('constructor:'):
        # V3.19.0: paid character constructor — avatar generation may take a
        # minute, so it runs as a task like the video pipeline.
        record_payment(message.from_user.id, 'constructor', payment.total_amount, charge)
        asyncio.create_task(_finish_constructor(message, charge))
        return

    if payload.startswith('gallery_dl:'):
        try:
            delivery_id = int(payload.split(':', 1)[1])
        except ValueError:
            return
        snap = get_gallery_item_bytes(message.from_user.id, delivery_id)
        if not snap:
            # The source bytes were removed between invoice and payment — refund.
            try:
                await bot.refund_star_payment(user_id=message.from_user.id, telegram_payment_charge_id=charge)
                record_refund(message.from_user.id, charge, payment.total_amount, product='gallery_download')
                await message.answer('исходник этого фото уже недоступен — Stars вернул автоматически 🙂')
            except Exception:
                logger.exception('Gallery download refund failed user=%s charge=%s', message.from_user.id, charge)
                await message.answer('не смог отправить скачанное фото. Напиши /support — проверим.')
            return
        record_payment(message.from_user.id, 'gallery_download', payment.total_amount, charge)
        track_event(
            ensure_user(message.from_user.id),
            'stars_purchase',
            value=payment.total_amount,
            metadata={'product': 'gallery_download', 'source_delivery_id': delivery_id, 'scene': snap.get('scene')},
        )
        try:
            await bot.send_document(
                message.chat.id,
                BufferedInputFile(snap['bytes'], filename=snap['filename']),
                caption=f'🖼 {snap["scene"]} — твоё фото в полном разрешении, без Telegram-сжатия.',
            )
        except Exception:
            logger.exception('Gallery download delivery failed user=%s delivery=%s', message.from_user.id, delivery_id)
            try:
                await bot.refund_star_payment(user_id=message.from_user.id, telegram_payment_charge_id=charge)
                record_refund(message.from_user.id, charge, payment.total_amount, product='gallery_download')
            except Exception:
                logger.exception('Gallery download refund after delivery failure failed user=%s charge=%s', message.from_user.id, charge)
            await message.answer('не получилось отправить файл. Stars вернул автоматически 🙂')
        return

    if payload.startswith('gift:'):
        gift = gifts_service.get(payload.split(':', 1)[1])
        if not gift:
            await message.answer('Оплата прошла, но подарок уже не найден. Напиши /support — разберёмся.')
            return
        record_payment(message.from_user.id, 'gift', payment.total_amount, charge)
        track_event(ensure_user(message.from_user.id), 'stars_purchase', value=payment.total_amount, metadata={'product': 'gift', 'gift': gift.id})
        character_id = get_user_character(message.from_user.id)
        await record_user_message(message.from_user.id, message.from_user.first_name or '', relationship=gift.affection, trust=max(0.5, round(gift.affection * 0.25, 2)), event_type='gift', reason=f'gift:{gift.id}', character_id=character_id)
        from services.gamification_service import unlock_achievement
        unlock_achievement(message.from_user.id, 'first_gift')
        await message.answer(f'🎁 Ты подарил {gift.emoji} {gift.name}!\n\n{gift.reaction}')
        await _send_voice_note(message.chat.id, message.from_user.id, gift.reaction)
        return

    if payload.startswith('date:'):
        date = dates_service.get(payload.split(':', 1)[1])
        if not date:
            await message.answer('Оплата прошла, но свидание уже не найдено. Напиши /support — разберёмся.')
            return
        record_payment(message.from_user.id, 'date', payment.total_amount, charge)
        track_event(ensure_user(message.from_user.id), 'stars_purchase', value=payment.total_amount, metadata={'product': 'date', 'date': date.id})
        await _deliver_date_reward(message.chat.id, message.from_user.id, message.from_user.first_name or '', date)
        return

    if payload.startswith('photo:'):
        try:
            offer_id = int(payload.split(':', 1)[1])
        except ValueError:
            return
        request = consume_offer(message.from_user.id, offer_id)
        product = 'custom_photo' if payment.total_amount >= CUSTOM_PHOTO_COST_STARS else 'photo'
        record_payment(message.from_user.id, product, payment.total_amount, charge)
        if not request:
            await message.answer('оплата прошла, а запрос уже устарел. Photo credit сохранён — он не пропадёт.')
            return
        track_event(ensure_user(message.from_user.id), 'stars_purchase', value=payment.total_amount, metadata={'product': product})
        await _start_photo_background(message.chat.id, message.from_user.id, request, 'credit')


# === КВАРТИРА / ПОДАРКИ / СВИДАНИЯ (v3.17.0) ===

async def _send_voice_note(chat_id: int, telegram_id: int, text: str) -> None:
    """She answers with her voice after gifts/dates — only when the user has
    voice replies enabled. Emojis are stripped so TTS reads naturally."""
    try:
        user = get_user(telegram_id)
        if not user or not getattr(user, 'voice_enabled', False):
            return
        clean = ''.join(ch for ch in text if ch.isalnum() or ch in ' .,!?:;-—…()«»\'\n')
        if not clean.strip():
            return
        character_id = get_user_character(telegram_id)
        audio = await synthesize_bytes(clean, user.voice_style, character_id=character_id)
        await bot.send_voice(chat_id, BufferedInputFile(audio, filename=f'{character_id}.ogg'))
    except Exception:
        logger.exception('event voice note failed user=%s', telegram_id)


async def _deliver_date_reward(chat_id: int, telegram_id: int, user_name: str, date) -> None:
    """Shared date reward path for paid dates and the free streak date."""
    character_id = get_user_character(telegram_id)
    await record_user_message(telegram_id, user_name, relationship=date.affection, intimacy=date.affection / 2, event_type='date', reason=f'date:{date.id}', character_id=character_id)
    from services.gamification_service import completed_date_ids, unlock_achievement
    unlock_achievement(telegram_id, 'first_date')
    completed = completed_date_ids(telegram_id)
    if len(completed) >= 10:
        unlock_achievement(telegram_id, 'ten_dates')
    if len(completed) >= len(dates_service.get_all()):
        unlock_achievement(telegram_id, 'date_collector')
    await bot.send_message(chat_id, f'{date.emoji} {date.text}\n\nА вот и фото с нашей прогулки 😊')
    await _send_voice_note(chat_id, telegram_id, date.text)
    await _start_photo_background(chat_id, telegram_id, PhotoRequest(scene=date.scene, mood='romantic'), 'story')

@dp.message(F.text == '🏠 Квартира')
async def apartment_cmd(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    level = get_relationship_level(message.from_user.id, get_user_character(message.from_user.id))
    rows = [[InlineKeyboardButton(text=f'{r.emoji} {r.name}', callback_data=f'room:{r.id}')]
            for r in apartment_service.get_available_rooms(level)]
    rows += [[InlineKeyboardButton(text=f'🔒 {r.name} — уровень {r.min_level}', callback_data=f'room_locked:{r.id}')]
             for r in apartment_service.get_locked_rooms(level)]
    await message.answer('🏠 Моя квартира 😊\n\nВыбери комнату:', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data.startswith('room:'))
async def room_enter(cq: types.CallbackQuery):
    room = apartment_service.get_room(cq.data.split(':', 1)[1])
    if not room:
        await cq.answer('Такой комнаты нет', show_alert=True)
        return
    level = get_relationship_level(cq.from_user.id, get_user_character(cq.from_user.id))
    if room.min_level > level:
        await cq.answer(f'Эта комната откроется на уровне {room.min_level} 😉', show_alert=True)
        return
    ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    rows = [[InlineKeyboardButton(text=title, callback_data=f'apt_action:{room.id}:{action_id}')]
            for title, action_id in room.actions]
    await cq.answer()
    try:
        await cq.message.edit_text(f'{room.emoji} {room.name}\n\n{room.description}',
                                   reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    except Exception:
        await cq.message.answer(f'{room.emoji} {room.name}\n\n{room.description}',
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data.startswith('room_locked:'))
async def room_locked(cq: types.CallbackQuery):
    room = apartment_service.get_room(cq.data.split(':', 1)[1])
    if room:
        await cq.answer(f'Сюда пока нельзя — комната откроется на уровне {room.min_level} 😉', show_alert=True)
    else:
        await cq.answer()


@dp.callback_query(F.data.startswith('apt_action:'))
async def room_action(cq: types.CallbackQuery):
    _, room_id, action_id = cq.data.split(':', 2)
    result = apartment_service.room_action_reply(room_id, action_id)
    if not result:
        await cq.answer()
        return
    text, rel_delta, int_delta = result
    character_id = get_user_character(cq.from_user.id)
    await record_user_message(cq.from_user.id, cq.from_user.first_name or '',
                              relationship=rel_delta, intimacy=int_delta,
                              event_type='apartment', reason=f'apartment:{room_id}:{action_id}',
                              character_id=character_id)
    track_event(ensure_user(cq.from_user.id), 'apartment_action', metadata={'room': room_id, 'action': action_id})
    await cq.answer()
    await cq.message.answer(text)


@dp.message(F.text == '🎁 Подарить')
async def gifts_cmd(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    gifts = gifts_service.get_all()
    lines = []
    for g in gifts:
        if gifts_service.is_featured(g):
            lines.append(f'{g.emoji} {g.name} — {gifts_service.effective_cost(g)}⭐ 🔥 подарок дня (вместо {g.cost}⭐)')
        else:
            lines.append(f'{g.emoji} {g.name} — {g.cost}⭐')
    rows = [[InlineKeyboardButton(
        text=(f'{g.emoji} {g.name} · {gifts_service.effective_cost(g)}⭐ 🔥' if gifts_service.is_featured(g)
              else f'{g.emoji} {g.name} · {g.cost}⭐'),
        callback_data=f'gift:{g.id}')]
        for g in gifts]
    await message.answer('🎁 Выбери подарок — она будет рада 😊\n\n' + '\n'.join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data.startswith('gift:'))
async def gift_buy(cq: types.CallbackQuery):
    gift = gifts_service.get(cq.data.split(':', 1)[1])
    if not gift:
        await cq.answer('Подарок не найден', show_alert=True)
        return
    # Admin test mode: deliver the gift instantly, without a Stars invoice.
    if cq.from_user.id in ADMIN_TELEGRAM_IDS:
        character_id = get_user_character(cq.from_user.id)
        await record_user_message(cq.from_user.id, cq.from_user.first_name or '', relationship=gift.affection, trust=max(0.5, round(gift.affection * 0.25, 2)), event_type='gift', reason=f'gift:{gift.id}', character_id=character_id)
        from services.gamification_service import unlock_achievement
        unlock_achievement(cq.from_user.id, 'first_gift')
        track_event(ensure_user(cq.from_user.id), 'admin_test_gift', metadata={'gift': gift.id})
        await cq.answer('🔧 админ-тест: Stars не списаны')
        await cq.message.answer(f'🎁 Ты подарил {gift.emoji} {gift.name}!\n\n{gift.reaction}')
        await _send_voice_note(cq.message.chat.id, cq.from_user.id, gift.reaction)
        return
    await cq.answer()
    await send_stars_invoice(cq.message.chat.id, f'Подарок: {gift.name}',
                             f'{gift.emoji} {gift.name} для неё — она точно оценит 😉',
                             f'gift:{gift.id}', gifts_service.effective_cost(gift))


@dp.message(F.text == '💕 Свидание')
async def dates_cmd(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    level = get_relationship_level(message.from_user.id, get_user_character(message.from_user.id))
    from services.gamification_service import completed_date_ids, has_free_date
    done = completed_date_ids(message.from_user.id)
    rows = [[InlineKeyboardButton(text=f'{"✅ " if d.id in done else ""}{d.emoji} {d.name} · {d.cost}⭐', callback_data=f'date:{d.id}')]
            for d in dates_service.get_available(level)]
    rows += [[InlineKeyboardButton(text=f'🔒 {d.name} — уровень {d.min_level}', callback_data=f'date_locked:{d.id}')]
             for d in dates_service.get_locked(level)]
    banner = '\n\n🎁 У тебя есть бесплатное свидание за неделю стрика!' if has_free_date(message.from_user.id) else ''
    progress = f'\n\n📖 Свиданий в коллекции: {len(done)}/{len(dates_service.get_all())}'
    await message.answer(f'💕 Куда пойдём?{banner}{progress}', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data.startswith('date:'))
async def date_start(cq: types.CallbackQuery):
    date = dates_service.get(cq.data.split(':', 1)[1])
    if not date:
        await cq.answer('Свидание не найдено', show_alert=True)
        return
    level = get_relationship_level(cq.from_user.id, get_user_character(cq.from_user.id))
    if date.min_level > level:
        await cq.answer(f'Это свидание откроется на уровне {date.min_level} 😉', show_alert=True)
        return
    from services.gamification_service import has_free_date, consume_free_date
    # Admin test mode: run the date instantly, without invoice or voucher.
    if cq.from_user.id in ADMIN_TELEGRAM_IDS:
        await cq.answer('🔧 админ-тест: Stars не списаны')
        track_event(ensure_user(cq.from_user.id), 'admin_test_date', metadata={'date': date.id})
        await _deliver_date_reward(cq.message.chat.id, cq.from_user.id, cq.from_user.first_name or '', date)
        return
    if has_free_date(cq.from_user.id):
        consume_free_date(cq.from_user.id)
        await cq.answer('Бесплатное свидание за твой стрик 🔥')
        track_event(ensure_user(cq.from_user.id), 'free_date_used', metadata={'date': date.id})
        await _deliver_date_reward(cq.message.chat.id, cq.from_user.id, cq.from_user.first_name or '', date)
        return
    await cq.answer()
    await send_stars_invoice(cq.message.chat.id, f'Свидание: {date.name}',
                             f'{date.emoji} {date.name}. В конце она пришлёт фото с прогулки 📸',
                             f'date:{date.id}', date.cost)


@dp.callback_query(F.data.startswith('date_locked:'))
async def date_locked(cq: types.CallbackQuery):
    date = dates_service.get(cq.data.split(':', 1)[1])
    if date:
        await cq.answer(f'Это свидание откроется на уровне {date.min_level} 😉', show_alert=True)
    else:
        await cq.answer()


@dp.message(Command('photo', 'selfie'))
async def photo_menu(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    if not has_accepted(message.from_user.id):
        await message.answer('Сначала подтверди 18+ и условия через /start.', reply_markup=consent_keyboard()); return
    await message.answer(
        photo_menu_text(message.from_user.id),
        reply_markup=photo_keyboard(message.from_user.id),
    )


@dp.callback_query(F.data.startswith('locked:'))
async def locked_photo_callback(cq: types.CallbackQuery):
    item = cq.data.split(':', 1)[1]
    required = 5 if item == 'custom' else SCENE_LEVELS.get(item, 6)
    current = get_relationship_level(cq.from_user.id, get_user_character(cq.from_user.id))
    await cq.answer(
        f'🔒 Откроется на уровне {required}/6. Сейчас {current}/6. Близость растёт от общения — купить уровень нельзя.',
        show_alert=True,
    )


@dp.callback_query(F.data == 'photo_menu:open')
async def photo_menu_callback(cq: types.CallbackQuery):
    ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    await cq.answer()
    await cq.message.answer(photo_menu_text(cq.from_user.id), reply_markup=photo_keyboard(cq.from_user.id))


@dp.callback_query(F.data.startswith('photo_feedback:'))
async def photo_feedback_callback(cq: types.CallbackQuery):
    _, action, scene = cq.data.split(':', 2)
    uid = ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    state = get_state(cq.from_user.id)
    liked = action == 'like'
    observe_photo_feedback(uid, liked, scene, getattr(state, 'outfit', '') or '', getattr(state, 'hairstyle', '') or '', get_user_character(cq.from_user.id))
    track_event(uid, 'photo_feedback_like' if liked else 'photo_feedback_dislike', metadata={'scene': scene})
    await cq.answer('запомнила 😌' if liked else 'поняла, буду менять стиль')
    try:
        await cq.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


@dp.callback_query(F.data.startswith('retry_photo:'))
async def retry_photo_callback(cq: types.CallbackQuery):
    await cq.answer('пробую ещё раз')
    scene = cq.data.split(':', 1)[1]
    await handle_photo_request(cq.message.chat.id, cq.from_user.id, PhotoRequest(scene=scene))


@dp.callback_query(F.data.startswith('photo:'))
async def photo_callback(cq: types.CallbackQuery):
    await cq.answer()
    scene = cq.data.split(':', 1)[1]
    tid = cq.from_user.id
    ensure_user(tid, cq.from_user.first_name)
    await handle_photo_request(cq.message.chat.id, tid, PhotoRequest(scene=scene))


async def start_custom_flow(chat_id: int, telegram_id: int):
    if get_relationship_level(telegram_id, get_user_character(telegram_id)) < 5:
        await bot.send_message(chat_id, 'кастомные приватные образы откроются позже — тут Stars уровень отношений не заменяют 😏')
        return
    if not is_adult_confirmed(telegram_id):
        _pending_adult_custom.add(telegram_id)
        await bot.send_message(chat_id, 'сначала одно подтверждение 18+.', reply_markup=adult_keyboard())
        return
    _custom_drafts[telegram_id] = {}
    await bot.send_message(chat_id, 'начнём с цвета:', reply_markup=custom_color_keyboard())


@dp.callback_query(F.data == 'custom:start')
async def custom_start(cq: types.CallbackQuery):
    await cq.answer()
    await start_custom_flow(cq.message.chat.id, cq.from_user.id)


@dp.callback_query(F.data.startswith('custom:color:'))
async def custom_color(cq: types.CallbackQuery):
    await cq.answer()
    color = cq.data.rsplit(':', 1)[1]
    _custom_drafts.setdefault(cq.from_user.id, {})['color'] = color
    await cq.message.answer('добавить чулки?', reply_markup=custom_addon_keyboard())


@dp.callback_query(F.data.startswith('custom:addon:'))
async def custom_addon(cq: types.CallbackQuery):
    await cq.answer()
    addon = cq.data.rsplit(':', 1)[1]
    _custom_drafts.setdefault(cq.from_user.id, {})['addon'] = addon
    await cq.message.answer('причёска?', reply_markup=custom_hair_keyboard())


@dp.callback_query(F.data.startswith('custom:hair:'))
async def custom_hair(cq: types.CallbackQuery):
    await cq.answer()
    hair = cq.data.rsplit(':', 1)[1]
    _custom_drafts.setdefault(cq.from_user.id, {})['hair'] = hair
    await cq.message.answer('и где сделать кадр?', reply_markup=custom_place_keyboard())


@dp.callback_query(F.data.startswith('custom:place:'))
async def custom_place(cq: types.CallbackQuery):
    await cq.answer()
    draft = _custom_drafts.pop(cq.from_user.id, {})
    place = cq.data.rsplit(':', 1)[1]
    color = draft.get('color', 'black')
    clothing = f'{color} elegant lingerie fashion set with opaque fabric and polished catalog styling'
    if draft.get('addon') == 'stockings':
        clothing += ', with matching thigh-high stockings'
    hair_map = {
        'ponytail': 'high ponytail',
        'bun': 'neat bun',
        'loose': 'long loose softly wavy hair',
    }
    place_map = {
        'mirror': ('realistic mirror photo in a tasteful modern apartment', 'full-body mirror framing'),
        'sofa': ('sitting naturally on a modern sofa in a tidy apartment', 'natural three-quarter seated framing'),
        'hotel': ('tasteful modern hotel room', 'elegant full-body fashion portrait'),
    }
    location, angle = place_map.get(place, place_map['mirror'])
    request = PhotoRequest(
        scene='lingerie',
        clothing=clothing,
        hairstyle=hair_map.get(draft.get('hair', 'loose'), hair_map['loose']),
        location=location,
        angle=angle,
        mood='confident, warm, polished fashion editorial',
    )
    await _offer_custom_photo(cq.message.chat.id, cq.from_user.id, request)


@dp.message(Command('voice'))
async def voice_toggle(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    user = get_user(message.from_user.id)
    new = not user.voice_enabled
    update_user_settings(message.from_user.id, voice_enabled=new)
    await message.answer('голосовые ответы включены 🎙️' if new else 'голосовые ответы выключены')


@dp.message(Command('voice_anon'))
async def voice_anon_toggle(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    user = get_user(message.from_user.id)
    new = not user.voice_anon_mode
    update_user_settings(message.from_user.id, voice_anon_mode=new)
    await message.answer(
        'голосовой аноним-режим включён 🔒\nя не буду использовать твоё имя в голосовых ответах'
        if new else
        'голосовой аноним-режим выключен'
    )


@dp.message(Command('voice_style'))
async def voice_style(message: types.Message):
    parts = (message.text or '').split(maxsplit=1)
    if len(parts) < 2 or parts[1] not in VALID_VOICES:
        await message.answer('Доступно: ' + ', '.join(VALID_VOICES))
        return
    update_user_settings(message.from_user.id, voice_style=parts[1])
    await message.answer(f'голос: {parts[1]} 🎙️')


@dp.message(Command('notifications'))
async def notifications(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    user = get_user(message.from_user.id)
    new = not user.proactive_enabled
    update_user_settings(message.from_user.id, proactive_enabled=new)
    await message.answer('иногда буду писать первой 😌' if new else 'хорошо, первой писать не буду')


@dp.message(Command('timezone'))
async def timezone_cmd(message: types.Message):
    parts = (message.text or '').split(maxsplit=1)
    if len(parts) < 2:
        ensure_user(message.from_user.id)
        await message.answer(f'Сейчас: {get_user(message.from_user.id).timezone}\nПример: /timezone Europe/Moscow')
        return
    try:
        set_timezone(message.from_user.id, parts[1].strip())
        await message.answer('готово, запомнила часовой пояс')
    except Exception:
        await message.answer('не узнаю такой часовой пояс. пример: Europe/Moscow')


@dp.message(Command('wake'))
async def wake_cmd(message: types.Message):
    if not is_premium(message.from_user.id):
        await message.answer('⏰ Будильник — Premium-функция. /premium — подключить')
        return
    rid = create_from_text(message.from_user.id, message.text or '')
    if rid:
        user = get_user(message.from_user.id)
        tz = user.timezone or 'UTC' if user else 'UTC'
        await message.answer(f'запомнила 😌 разбужу вовремя по {tz}. если не ответишь — буду настойчивее')
    else:
        await message.answer('напиши время, например /wake 08:00')


@dp.message(Command('myreminders'))
async def myreminders_cmd(message: types.Message):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer('сначала /start')
        return
    with SessionLocal() as s:
        rows = s.scalars(
            select(Reminder).where(Reminder.user_id == user.id, Reminder.active == True).order_by(Reminder.due_at_utc)
        ).all()
    if not rows:
        await message.answer('у тебя нет активных будильников/напоминаний')
        return
    lines = ['⏰ активные:']
    for r in rows:
        local = r.due_at_utc
        try:
            local = r.due_at_utc.replace(tzinfo=dt.timezone.utc).astimezone(ZoneInfo(r.timezone or 'UTC'))
            time_str = local.strftime('%d.%m %H:%M')
        except Exception:
            time_str = r.due_at_utc.strftime('%d.%m %H:%M UTC')
        kind = '🔔' if r.reminder_type == 'wake' else '📝'
        lines.append(f'{kind} {time_str} — {r.text} (попыток {r.attempts}/{r.max_attempts})')
    await message.answer('\n'.join(lines))


@dp.message(Command('reset'))
async def reset_cmd(message: types.Message):
    uid = ensure_user(message.from_user.id, message.from_user.first_name)
    char_id = get_user_character(message.from_user.id)
    reset_memory(uid, char_id)
    with SessionLocal() as session:
        rel = session.query(UserCharacterRelationship).filter_by(user_id=uid, character_id=char_id).first()
        if rel:
            session.query(RelationshipEvent).filter(RelationshipEvent.user_character_id == rel.id).delete(synchronize_session=False)
            session.query(RelationshipMilestone).filter(RelationshipMilestone.user_character_id == rel.id).delete(synchronize_session=False)
            session.delete(rel)
        state = session.query(CharacterState).filter_by(user_id=uid, character_id=char_id).first()
        if state:
            state.mood = 'neutral'
            state.energy = .65
            state.affection = .45
            state.playfulness = .55
            state.irritation = 0
            state.location = None
            state.outfit = None
            state.hairstyle = None
            state.recent_outfits_json = '[]'
            state.recent_hairstyles_json = '[]'
            state.pending_hook = None
        session.query(Reminder).filter_by(user_id=uid).delete(synchronize_session=False)
        session.commit()
    clear_stage(message.from_user.id)
    await message.answer('готово. нашу переписку, память и развитие отношений начала заново.')


@dp.message(Command('testlevel', 'relationship_test'))
async def testlevel(message: types.Message):
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        await message.answer('эта команда только для владельца')
        return
    parts = (message.text or '').split(maxsplit=1)
    if len(parts) < 2:
        await message.answer('Использование: /testlevel 1..6 или /testlevel off')
        return
    arg = parts[1].strip().lower()
    if arg == 'off':
        clear_stage(message.from_user.id)
        await message.answer('тестовый уровень выключен')
        return
    if not arg.isdigit() or not 1 <= int(arg) <= 6:
        await message.answer('нужен уровень от 1 до 6')
        return
    stage = STAGES[int(arg) - 1]
    set_stage(message.from_user.id, stage)
    await message.answer(f'тест: {STAGE_LABELS[stage]}')


async def send_answer(message: types.Message, text: str):
    user = get_user(message.from_user.id)
    if user and user.voice_enabled:
        try:
            character_id = get_user_character(message.from_user.id)
            audio = await synthesize_bytes(text, user.voice_style, character_id=character_id)
            filename = 'voice.ogg' if user.voice_anon_mode else f'{character_id}.ogg'
            await message.answer_voice(BufferedInputFile(audio, filename=filename))
            return
        except Exception:
            logger.exception('tts failed')

    # Short paragraph breaks feel more like Telegram bubbles; keep code blocks intact.
    if '```' not in text and '\n\n' in text and len(text) < 700:
        parts = [p.strip() for p in text.split('\n\n') if p.strip()]
        if 1 < len(parts) <= 3:
            for part in parts:
                await message.answer(part)
                await asyncio.sleep(0.35)
            return
    await message.answer(text)


@dp.message(F.text == '💬 Общение')
async def chat_button(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    await message.answer('я здесь 🙂 просто пиши мне как обычно')


@dp.message(F.text == '📸 Фото')
async def photo_button(message: types.Message):
    await photo_menu(message)


@dp.message(F.text == '🔗 Пригласить')
async def referral_button(message: types.Message):
    """Persistent menu button so the referral link is always one tap away,
    not buried in a one-time consent message that scrolls out of view."""
    await referral_cmd(message)


@dp.message(F.text == '🎭 Образы')
async def looks_button_legacy(message: types.Message):
    # Old Telegram reply keyboards can remain cached after a deploy. The button is
    # removed from the new UI; redirect stale clicks into the consolidated photo menu.
    await message.answer('Раздел «Образы» теперь внутри 📸 Фото.', reply_markup=main_keyboard(message.from_user.id in ADMIN_TELEGRAM_IDS))
    await photo_menu(message)


@dp.message(F.text == '🚀 Премиум')
async def premium_button(message: types.Message):
    await premium(message)


@dp.message(F.text == '🎯 Истории')
async def stories_button(message: types.Message):
    await stories_cmd(message)


@dp.message(F.text == '🖼 Коллекция')
async def collection_button(message: types.Message):
    await collection_cmd(message)


@dp.message(F.text == '👤 Профиль')
async def profile_button(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    char_id = get_user_character(message.from_user.id)
    info = build_photo_menu(message.from_user.id, char_id)
    uid = ensure_user(message.from_user.id, message.from_user.first_name)
    milestone_text = ''
    bond_text = ''
    progress_text = ''
    with SessionLocal() as session:
        rel = session.query(UserCharacterRelationship).filter_by(user_id=uid, character_id=char_id).first()
        if rel:
            from services.relationship_engine import bond_character, next_stage_progress, progress_bar
            bond_title, _bond_hint = bond_character(rel)
            bond_text = f'💞 Характер связи: {bond_title}\n'
            progress = next_stage_progress(rel)
            if progress:
                lines = [f'{label} {progress_bar(current, target)} {int(current)}/{int(target)}' for label, current, target in progress]
                progress_text = '📈 До следующего этапа:\n' + '\n'.join(lines) + '\n'
            milestones = session.query(RelationshipMilestone).filter_by(user_character_id=rel.id).order_by(RelationshipMilestone.achieved_at.desc()).limit(3).all()
            if milestones:
                milestone_text = '\n🏷 ' + '\n🏷 '.join(m.title for m in reversed(milestones))
    await message.answer(
        f'👤 Твой профиль\n\n'
        f'❤️ {RELATIONSHIP_LEVEL_NAMES.get(info["level"], "Знакомство")}\n'
        f'{bond_text}'
        f'{progress_text}'
        f'⭐ Premium: {"активен" if info["premium"] else "нет"}\n'
        f'📸 Фото сегодня: {info["free_left"]} включено\n'
        f'🎟 Photo credits: {info["credits"]}\n'
        f'📸 Коллекция: {collection_progress(message.from_user.id, CHARACTER_ID, info["level"])["seen"]}/{collection_progress(message.from_user.id, CHARACTER_ID, info["level"])["total"]} · /collection\n'
        f'🎯 Истории: /stories'
        f'{milestone_text}'
    )


@dp.message(F.text == '⏰ Будильник')
async def alarm_button(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    premium = is_premium(message.from_user.id)
    if not premium:
        await message.answer(
            '⏰ Будильник и напоминания — Premium-функция\n\n'
            'С Premium Анна будет будить тебя утром, напоминать о делах и всегда помнить твой часовой пояс.\n\n'
            '/premium — подключить',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text='⭐ Получить Premium', callback_data='premium:view')]
            ]),
        )
        return
    user = get_user(message.from_user.id)
    tz = user.timezone or 'UTC'
    # Fetch active reminders
    with SessionLocal() as s:
        active = s.scalars(
            select(Reminder).where(
                Reminder.user_id == user.id,
                Reminder.active == True,
            )
        ).all()
    lines = ['⏰ Будильник и напоминания\n']
    lines.append(f'Часовой пояс: {tz}')
    if active:
        lines.append('\nАктивные:')
        for r in active:
            kind_label = '🔔 Будильник' if r.reminder_type == 'wake' else '📝 Напоминание'
            lines.append(f'  {kind_label}: {r.text} · {r.due_at_utc.strftime("%d.%m %H:%M")} UTC')
    else:
        lines.append('\nПока нет активных напоминаний.')
    lines.append('\nКак установить:')
    lines.append('• Напиши: «разбуди в 08:00» или «напомни в 14:30»')
    lines.append('• Или команда: /wake 08:00')
    lines.append(f'• Сменить пояс: /timezone Europe/Moscow')
    await message.answer('\n'.join(lines))


@dp.message(F.text == '⚙️ Настройки')
async def settings_button(message: types.Message):
    await settings(message)


# V3.19.0: per-user cooldown for vision reactions to user photos.
_photo_reaction_ts: dict[int, float] = {}


async def _react_to_user_photo(message: types.Message):
    """In-character vision reaction to a photo the user sent in chat.

    Fully fail-silent: a broken provider or download must never block chat.
    """
    if not PHOTO_REACTION_ENABLED or not has_accepted(message.from_user.id):
        return
    now = _time.time()
    if now - _photo_reaction_ts.get(message.from_user.id, 0) < PHOTO_REACTION_COOLDOWN_SECONDS:
        return
    try:
        buffer = io.BytesIO()
        await bot.download(message.photo[-1], destination=buffer)
        image_b64 = base64.b64encode(buffer.getvalue()).decode('ascii')
    except Exception:
        logger.warning('photo reaction download failed user=%s', message.from_user.id)
        return
    _photo_reaction_ts[message.from_user.id] = now
    character_id = get_user_character(message.from_user.id)
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        reaction = await react_to_photo(image_b64, caption=message.caption, character_id=character_id)
    if not reaction:
        return
    await message.answer(reaction)
    # Sharing a photo is a meaningful gesture: let the bond grow a little.
    try:
        await record_user_message(
            message.from_user.id, message.from_user.first_name or 'ты',
            relationship=1, trust=1, intimacy=1,
            event_type='meaningful_share', reason='пользователь прислал фото',
            character_id=character_id,
        )
        track_event(ensure_user(message.from_user.id), 'photo_reaction_sent', metadata={'character_id': character_id})
    except Exception:
        pass


# ── V3.19.0: personal character constructor ─────────────────────────────────

_constructor_sessions: dict[int, dict] = {}

AGE_BY_GROUP = {'age_young': 20, 'age_mid': 25, 'age_mature': 30, 'age_confident': 35}


def _constructor_step_keyboard(step_key: str):
    step = CONSTRUCTOR_STEPS[step_index(step_key)]
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f'cbuild:{step["key"]}:{value}')]
        for value, label, _ in step['options']
    ]
    back_label = '↩ назад' if step_index(step_key) > 0 else '❌ отменить'
    rows.append([InlineKeyboardButton(text=back_label, callback_data=f'cbuild:back:{step["key"]}')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _constructor_prompt(step_key: str) -> str:
    index = step_index(step_key)
    return f'🎨 Шаг {index + 1}/{len(CONSTRUCTOR_STEPS)}: {CONSTRUCTOR_STEPS[index]["title"]}'


async def _constructor_intro(chat_id: int, telegram_id: int):
    if get_custom_character(telegram_id):
        await _show_my_character(chat_id, telegram_id)
        return
    _constructor_sessions[telegram_id] = {'params': {}, 'step': 0}
    await bot.send_message(
        chat_id,
        f'🎨 Конструктор персонажа\n\n'
        f'Собери свою личную собеседницу: внешность, характер, роль. '
        f'Можно приложить фото лица — персонаж получит эту внешность.\n\n'
        f'Стоимость: {CONSTRUCTOR_COST_STARS} Stars, платишь один раз.',
        reply_markup=_constructor_step_keyboard(CONSTRUCTOR_STEPS[0]['key']),
    )
    await bot.send_message(chat_id, _constructor_prompt(CONSTRUCTOR_STEPS[0]['key']))


async def _constructor_face_step(chat_id: int, telegram_id: int):
    cons = _constructor_sessions.get(telegram_id)
    if not cons:
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='📷 Загрузить фото лица', callback_data='cbuild:face_upload'),
        InlineKeyboardButton(text='Пропустить', callback_data='cbuild:face_skip'),
    ]])
    await bot.send_message(
        chat_id,
        f'🎨 Шаг {len(CONSTRUCTOR_STEPS) + 1}/{len(CONSTRUCTOR_STEPS) + 1}: хочешь, чтобы она была похожа на кого-то конкретного?\n'
        'Пришли фото лица — персонаж получит именно эту внешность (face-swap). Или пропусти.',
        reply_markup=keyboard,
    )


async def _constructor_confirm(chat_id: int, telegram_id: int):
    cons = _constructor_sessions.get(telegram_id)
    if not cons:
        return
    params = cons['params']
    lines = summary_lines(params, str(params.get('name') or 'Без имени'))
    face_line = '📷 Лицо: по твоему фото (face-swap)' if cons.get('face_bytes') else '🎭 Внешность: полностью AI'
    # V3.19.1: admins create their personal character for free.
    if telegram_id in ADMIN_TELEGRAM_IDS:
        buy_label = '✅ Создать · бесплатно (админ)'
        price_note = 'Админский доступ: бесплатно.'
    else:
        buy_label = f'✅ Создать · {CONSTRUCTOR_COST_STARS}⭐'
        price_note = f'Готова родиться за {CONSTRUCTOR_COST_STARS} Stars ✨'
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=buy_label, callback_data='constructor:buy')],
        [InlineKeyboardButton(text='❌ Отменить', callback_data='constructor:cancel')],
    ])
    await bot.send_message(
        chat_id,
        '🎨 Твой персонаж:\n\n' + '\n'.join(lines) + f'\n{face_line}\n\n' + price_note,
        reply_markup=keyboard,
    )


async def _constructor_receive_face(message: types.Message):
    telegram_id = message.from_user.id
    cons = _constructor_sessions.get(telegram_id)
    if not cons:
        return
    try:
        buffer = io.BytesIO()
        await bot.download(message.photo[-1], destination=buffer)
        face_bytes = buffer.getvalue()
        if not face_bytes:
            raise ValueError('empty photo')
    except Exception:
        await message.answer('не смогла прочитать фото 😕 попробуй другое.')
        return
    cons['face_bytes'] = face_bytes
    cons['face_file_id'] = message.photo[-1].file_id
    cons['await'] = None
    await message.answer('✅ Лицо принято — буду похожа на него 🙂')
    await _constructor_confirm(message.chat.id, telegram_id)


def _my_character_keyboard(character_id: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='💬 Общаться с ней', callback_data=f'mychar:chat:{character_id}')],
        [InlineKeyboardButton(text='🔄 Создать заново', callback_data='constructor:restart')],
    ])


async def _show_my_character(chat_id: int, telegram_id: int):
    row = get_custom_character(telegram_id)
    if not row:
        await _constructor_intro(chat_id, telegram_id)
        return
    try:
        params = json.loads(row.params_json or '{}')
    except (TypeError, ValueError):
        params = {}
    lines = ['🎨 Твой персонаж готов:', '']
    lines += summary_lines(params, row.display_name or 'Без имени')
    if row.face_file_id:
        lines.append('📷 Внешность — по твоему фото.')
    markup = _my_character_keyboard(row.character_id)
    if row.avatar_file_id:
        await bot.send_photo(chat_id, row.avatar_file_id, caption='\n'.join(lines), reply_markup=markup)
    else:
        await bot.send_message(chat_id, '\n'.join(lines), reply_markup=markup)


async def _finish_constructor(message: types.Message, charge: str | None):
    """After Stars payment: generate the avatar, save the persona, open chat."""
    telegram_id = message.from_user.id
    cons = _constructor_sessions.pop(telegram_id, None)
    if not cons:
        await message.answer('что-то потерялось 😕 нажми «🎨 Мой персонаж» ещё раз.')
        return
    params = cons['params']
    display_name = str(params.get('name') or 'Она')[:48]
    await message.answer('✨ Отлично! Рисую твою героиню — это займёт до минуты...')
    face_path = None
    if cons.get('face_bytes'):
        import tempfile
        face_path = Path(tempfile.gettempdir()) / f'constructor_face_{telegram_id}.jpg'
        try:
            face_path.write_bytes(cons['face_bytes'])
        except OSError:
            face_path = None
    try:
        avatar_bytes, _mime = await generate_custom_avatar(
            build_avatar_prompt(params, face_swap=bool(face_path)), face_path,
        )
    except Exception:
        logger.exception('constructor avatar generation failed user=%s', telegram_id)
        if charge:
            try:
                await bot.refund_star_payment(user_id=telegram_id, telegram_payment_charge_id=charge)
                record_refund(telegram_id, charge, CONSTRUCTOR_COST_STARS, product='constructor')
                await message.answer('аватар сейчас не получился 😕 Stars вернул автоматически. Попробуй ещё раз чуть позже.')
            except Exception:
                logger.exception('constructor refund failed user=%s', telegram_id)
                await message.answer('аватар не получился 😕 напиши /support — вернём Stars.')
        else:
            # Admin free run — nothing to refund.
            await message.answer('аватар сейчас не получился 😕 попробуй ещё раз чуть позже.')
        return
    finally:
        if face_path:
            try:
                face_path.unlink()
            except OSError:
                pass
    try:
        sent = await bot.send_photo(telegram_id, BufferedInputFile(avatar_bytes, filename='avatar.jpg'))
        avatar_file_id = sent.photo[-1].file_id
    except Exception:
        logger.exception('constructor avatar telegram upload failed user=%s', telegram_id)
        avatar_file_id = None
    row = save_custom_character(
        telegram_id, display_name=display_name, params=params,
        avatar_file_id=avatar_file_id, face_file_id=cons.get('face_file_id'),
    )
    # Register her as a real character card so photo/relationship pipelines
    # recognize the id; bio carries the appearance description for prompts.
    descriptor_bits = [
        OPTION_LABELS[str(params[key])] for key in ('age', 'body', 'hair', 'eyes', 'temperament', 'profession', 'role')
        if key in params and str(params[key]) in OPTION_LABELS
    ]
    bio = (display_name + ': ' + ', '.join(descriptor_bits).lower())[:900]
    card_age = AGE_BY_GROUP.get(str(params.get('age')), 25)
    try:
        if get_card(row.character_id):
            update_card(
                row.character_id, display_name=display_name, age=card_age,
                short_bio=bio, status='active', card_photo_file_id=avatar_file_id,
            )
        else:
            create_card(row.character_id, display_name, card_age, bio, '🎨', 'female')
            update_card(row.character_id, status='active', card_photo_file_id=avatar_file_id)
    except Exception:
        logger.exception('constructor card registration failed user=%s', telegram_id)
    track_event(
        ensure_user(telegram_id),
        'stars_purchase', value=CONSTRUCTOR_COST_STARS,
        metadata={'product': 'constructor', 'face_swap': bool(cons.get('face_bytes'))},
    )
    await bot.send_message(
        message.chat.id,
        f'🎉 Знакомься — это {display_name}! Теперь она твоя личная собеседница.',
        reply_markup=_my_character_keyboard(row.character_id),
    )


@dp.callback_query(F.data == 'constructor:start')
async def constructor_start_cb(cq: types.CallbackQuery):
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True)
        return
    await cq.answer()
    await _constructor_intro(cq.message.chat.id, cq.from_user.id)


@dp.callback_query(F.data == 'constructor:restart')
async def constructor_restart_cb(cq: types.CallbackQuery):
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True)
        return
    await cq.answer()
    _constructor_sessions.pop(cq.from_user.id, None)
    _constructor_sessions[cq.from_user.id] = {'params': {}, 'step': 0}
    await cq.message.answer(
        f'🎨 Собираем заново. Стоимость: {CONSTRUCTOR_COST_STARS} Stars.',
        reply_markup=_constructor_step_keyboard(CONSTRUCTOR_STEPS[0]['key']),
    )
    await cq.message.answer(_constructor_prompt(CONSTRUCTOR_STEPS[0]['key']))


@dp.callback_query(F.data.startswith('cbuild:'))
async def constructor_step_cb(cq: types.CallbackQuery):
    parts = cq.data.split(':')
    telegram_id = cq.from_user.id
    cons = _constructor_sessions.get(telegram_id)
    if not cons:
        await cq.answer('Сессия конструктора закончилась — начни заново.', show_alert=True)
        return
    action = parts[1] if len(parts) > 1 else ''
    if action == 'back':
        index = cons.get('step', 0)
        if index == 0:
            _constructor_sessions.pop(telegram_id, None)
            await cq.answer('Конструктор отменён.')
            await cq.message.answer('Хорошо, конструктор отменила. Вернуться можно в любой момент: «🎨 Мой персонаж».')
            return
        cons['step'] = index - 1
        key = CONSTRUCTOR_STEPS[cons['step']]['key']
        await cq.answer()
        await cq.message.answer(_constructor_prompt(key), reply_markup=_constructor_step_keyboard(key))
        return
    if action == 'face_upload':
        cons['await'] = 'face'
        await cq.answer()
        await cq.message.answer('Пришли фото лица одним сообщением 📷\n/cancel — отменить')
        return
    if action == 'face_skip':
        cons['await'] = None
        await cq.answer()
        await _constructor_confirm(cq.message.chat.id, telegram_id)
        return
    # Regular step option: cbuild:<step_key>:<option_value>
    if len(parts) != 3:
        await cq.answer()
        return
    key, value = parts[1], parts[2]
    index = step_index(key)
    if index < 0 or value not in OPTION_LABELS:
        await cq.answer()
        return
    if index != cons.get('step', 0):
        await cq.answer('Шаги по порядку 🙂', show_alert=True)
        return
    cons['params'][key] = value
    cons['step'] = index + 1
    await cq.answer()
    if cons['step'] < len(CONSTRUCTOR_STEPS):
        next_key = CONSTRUCTOR_STEPS[cons['step']]['key']
        await cq.message.answer(_constructor_prompt(next_key), reply_markup=_constructor_step_keyboard(next_key))
        return
    # All inline steps done — ask for the name as plain text.
    cons['await'] = 'name'
    await cq.message.answer('Шаг: как её зовут? Напиши имя одним сообщением (до 24 символов).')


@dp.callback_query(F.data == 'constructor:buy')
async def constructor_buy_cb(cq: types.CallbackQuery):
    telegram_id = cq.from_user.id
    cons = _constructor_sessions.get(telegram_id)
    if not cons or not cons.get('params', {}).get('name'):
        await cq.answer('Сначала собери персонажа до конца 🙂', show_alert=True)
        return
    await cq.answer()
    # V3.19.1: admins skip the Stars invoice entirely.
    if telegram_id in ADMIN_TELEGRAM_IDS:
        asyncio.create_task(_finish_constructor(cq.message, None))
        return
    await send_stars_invoice(
        cq.message.chat.id,
        'Личный персонаж',
        'Конструктор создаст уникальную собеседницу с аватаром. Платёж одноразовый.',
        f'constructor:{telegram_id}',
        CONSTRUCTOR_COST_STARS,
    )


@dp.callback_query(F.data == 'constructor:cancel')
async def constructor_cancel_cb(cq: types.CallbackQuery):
    _constructor_sessions.pop(cq.from_user.id, None)
    await cq.answer('Конструктор отменён.')
    await cq.message.answer('Хорошо, отменила. Вернуться можно в любой момент: «🎨 Мой персонаж».')


@dp.callback_query(F.data.startswith('mychar:chat:'))
async def my_character_chat_cb(cq: types.CallbackQuery):
    character_id = cq.data.split(':', 2)[2]
    if not is_custom_character(character_id):
        await cq.answer()
        return
    row = get_custom_character(cq.from_user.id)
    if not row or row.character_id != character_id:
        await cq.answer('Это не твой персонаж 🙂', show_alert=True)
        return
    await cq.answer()
    _user_character[cq.from_user.id] = character_id
    track_event(ensure_user(cq.from_user.id), 'character_selected', metadata={'character_id': character_id, 'custom': True})
    await cq.message.answer(
        f'✅ Теперь ты общаешься с {row.display_name or "ней"}. Пиши ей прямо сюда 👇',
        reply_markup=main_keyboard(cq.from_user.id in ADMIN_TELEGRAM_IDS),
    )
    await cq.message.answer(f'{row.display_name or "Она"}: «Ну привет... я ждала, когда ты наконец выберешь меня 😏 Расскажи мне о себе.»')


@dp.message(F.text == '🎨 Мой персонаж')
async def my_character_button(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    if not has_accepted(message.from_user.id):
        await message.answer('Сначала подтверди 18+ и условия через /start.', reply_markup=consent_keyboard())
        return
    await _show_my_character(message.chat.id, message.from_user.id)


@dp.message(F.photo)
async def library_photo_upload(message: types.Message):
    # Payment QR editing is owner-only and takes priority over other photo importers.
    payment_edit = _payment_method_edit_sessions.get(message.from_user.id)
    if message.from_user.id in ADMIN_TELEGRAM_IDS and payment_edit:
        mode = payment_edit.get('mode')
        field = payment_edit.get('field')
        step = payment_edit.get('step')
        if (mode == 'edit' and field == 'qr') or (mode == 'add' and payment_edit.get('method_type') == 'qr' and step == 'qr'):
            ph = message.photo[-1]
            if mode == 'edit':
                method_id = int(payment_edit['method_id'])
                update_payment_method(method_id, qr_photo_file_id=ph.file_id)
            else:
                name = (payment_edit.get('draft') or {}).get('display_name') or 'Банковский QR'
                method = create_payment_method('qr', name)
                method_id = method.id
                update_payment_method(method_id, qr_photo_file_id=ph.file_id)
            _payment_method_edit_sessions.pop(message.from_user.id, None)
            await message.answer(
                '✅ QR сохранён. Его можно заменить в любой момент из админки — redeploy не нужен.\n\n'
                + _admin_payment_summary(method_id),
                reply_markup=admin_payment_keyboard(method_id),
            )
            return

    # Character-card cover upload has priority over the library importer.
    card_edit = _character_card_edit_sessions.get(message.from_user.id)
    if message.from_user.id in ADMIN_TELEGRAM_IDS and card_edit and card_edit.get('field') == 'photo':
        ph = message.photo[-1]
        allowed, reason = await _library_photo_is_allowed(ph)
        if not allowed and reason not in ('moderation_error', 'disabled'):
            await message.answer('это фото не прошло проверку и не будет установлено в карточку.')
            return
        character_id = card_edit['character_id']
        update_card(character_id, card_photo_file_id=ph.file_id)
        _character_card_edit_sessions.pop(message.from_user.id, None)
        warn = ' ⚠️ moderation недоступна — фото сохранено без проверки.' if reason == 'moderation_error' else ''
        await message.answer(f'🖼 Фото карточки сохранено.{warn}', reply_markup=admin_card_keyboard(character_id))
        return

    # Constructor face-wait: the user is uploading an identity reference photo.
    constructor_session = _constructor_sessions.get(message.from_user.id)
    if constructor_session and constructor_session.get('await') == 'face':
        await _constructor_receive_face(message)
        return

    sess = _library_import_sessions.get(message.from_user.id)
    if message.from_user.id not in ADMIN_TELEGRAM_IDS or not sess:
        # V3.19.0: regular users get an in-character vision reaction instead
        # of silence; admins outside an import session do too.
        await _react_to_user_photo(message)
        return
    if sess.get('preview'):
        await message.answer('сначала нажми «Продолжить загрузку» или «Сохранить всё».')
        return
    if len(sess['photos']) >= 10:
        await message.answer('уже 10 / 10. нажми «Закончить загрузку».', reply_markup=library_import_controls())
        return
    ph = message.photo[-1]
    allowed, reason = await _library_photo_is_allowed(ph)
    if not allowed:
        if reason == 'moderation_error':
            sess['moderation_errors'] = int(sess.get('moderation_errors', 0)) + 1
        else:
            sess['rejected'] = int(sess.get('rejected', 0)) + 1
        await _library_refresh_status(sess)
        return

    sess['photos'].append({
        'file_id': ph.file_id,
        'unique_id': ph.file_unique_id,
        'caption': message.caption,
        'message_id': message.message_id,
    })
    sess['last_photo_index'] = len(sess['photos']) - 1
    count = len(sess['photos'])
    # Do not auto-enter preview at 10/10: the owner may still attach a video
    # to the tenth photo. More photos are blocked above; Finish remains available.
    if count in {1, 5, 10}:
        await _library_refresh_status(sess)


async def _attach_video_to_library_session(message: types.Message, file_id: str, unique_id: str | None, caption: str | None):
    """Attach an owner-uploaded Telegram video to the most recently uploaded library photo."""
    sess = _library_import_sessions.get(message.from_user.id)
    if message.from_user.id not in ADMIN_TELEGRAM_IDS or not sess:
        return False
    if sess.get('preview'):
        await message.answer('сначала нажми «Продолжить загрузку», затем отправь видео сразу после нужного фото.')
        return True
    photos = sess.get('photos') or []
    if not photos:
        await message.answer('сначала отправь фото, а сразу следующим сообщением — видео к нему.')
        return True
    index = int(sess.get('last_photo_index', len(photos) - 1))
    index = max(0, min(index, len(photos) - 1))
    target = photos[index]
    replaced = bool(target.get('video_file_id'))
    target['video_file_id'] = file_id
    target['video_unique_id'] = unique_id
    target['video_caption'] = caption
    await _library_refresh_status(sess)
    await message.answer(
        ('🔄 Видео у последнего фото заменено.' if replaced else '✅ Видео привязано к последнему фото.')
        + '\nСледующим сообщением можешь отправить новое фото.'
    )
    return True


@dp.message(F.video)
async def library_video_upload(message: types.Message):
    if await _attach_video_to_library_session(
        message, message.video.file_id, message.video.file_unique_id, message.caption
    ):
        return


@dp.callback_query(F.data.startswith('libvideo:'))
async def linked_library_video(cq: types.CallbackQuery):
    if not has_accepted(cq.from_user.id):
        await cq.answer('сначала пройди /start', show_alert=True)
        return
    try:
        item_id = int(cq.data.split(':', 1)[1])
    except (TypeError, ValueError):
        await cq.answer('видео недоступно', show_alert=True)
        return
    linked = get_linked_video(
        item_id, CHARACTER_ID, get_relationship_level(cq.from_user.id, get_user_character(cq.from_user.id))
    )
    if not linked:
        await cq.answer('это видео пока недоступно', show_alert=True)
        return
    await cq.answer('🎬 открываю')
    try:
        await bot.send_video(
            cq.message.chat.id,
            linked.video_file_id,
            caption=linked.caption or 'небольшое продолжение этого кадра 🎬',
            supports_streaming=True,
        )
        track_event(
            ensure_user(cq.from_user.id),
            'linked_library_video_viewed',
            metadata={'photo_item_id': item_id, 'scene': linked.scene, 'level': linked.relationship_level},
        )
    except Exception:
        logger.exception('linked library video send failed user=%s item=%s', cq.from_user.id, item_id)
        await cq.message.answer('видео сейчас не открылось 😕 попробуй ещё раз чуть позже.')


async def _notify_quest_unlocks(chat_id: int, telegram_id: int, before_level: int, after_level: int):
    if after_level <= before_level:
        return
    for item in newly_unlocked_quests(telegram_id, before_level, after_level):
        await bot.send_message(
            chat_id,
            f'🎯 Открылась новая история: «{item["title"]}» ✨\n\n{item.get("teaser", "У Анны появился новый выбор, на который можешь повлиять.")}',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text='Начать историю', callback_data=f'quest:view:{item["key"]}')]
            ]),
        )
        track_event(ensure_user(telegram_id), 'quest_unlocked', metadata={'quest': item['key'], 'level': after_level})


async def _on_relationship_stage_up(telegram_id: int, old_stage: str, new_stage: str, character_id: str):
    """Level-up ceremony: announce the new stage, list fresh unlocks and send a
    small celebration set. Registered as the relationship notifier, so it fires
    from chat, gifts, dates and apartment actions alike."""
    try:
        await asyncio.sleep(3)  # let her chat reply land first
        from services.photo_service import STAGE_INDEX, SCENE_LEVELS
        level = STAGE_INDEX.get(new_stage, 0) + 1
        name = RELATIONSHIP_LEVEL_NAMES.get(level, new_stage)
        unlocks = []
        scenes = [PHOTO_LABELS[s] for s in PHOTO_MENU_ORDER if s in PHOTO_LABELS and SCENE_LEVELS.get(s) == level]
        if scenes:
            unlocks.append('📸 фото: ' + ', '.join(scenes))
        rooms = [f'{r.emoji} {r.name}' for r in apartment_service.get_available_rooms(level) if r.min_level == level]
        if rooms:
            unlocks.append('🏠 квартира: ' + ', '.join(rooms))
        dates = [f'{d.emoji} {d.name}' for d in dates_service.get_all() if d.min_level == level]
        if dates:
            unlocks.append('💕 свидания: ' + ', '.join(dates))
        text = f'❤️ Между нами что-то изменилось…\nНовый этап: {name}'
        if unlocks:
            text += '\n\nТеперь доступно:\n' + '\n'.join('• ' + u for u in unlocks)
        text += '\n\nи небольшой подарок от меня 🤍'
        await bot.send_message(telegram_id, text)
        track_event(ensure_user(telegram_id), 'relationship_ceremony_sent', metadata={'level': level}, character_id=character_id)
        await _start_photo_background(telegram_id, telegram_id, PhotoRequest(scene='selfie', mood='romantic'), 'story')
    except Exception as exc:
        logger.warning('level-up ceremony failed user=%s error=%s', telegram_id, type(exc).__name__)


set_stage_change_notifier(_on_relationship_stage_up)


@dp.message(F.voice)
async def voice_message(message: types.Message):
    uid = ensure_user(message.from_user.id, message.from_user.first_name)
    track_event(uid, 'chat_user_message', metadata={'kind': 'voice'})
    _track_proactive_reply_if_any(message.from_user.id, uid)
    cancel_active_wake(message.from_user.id)
    if not can_send_message(message.from_user.id):
        await message.answer('на сегодня бесплатный лимит сообщений закончился. /premium')
        return
    try:
        data = await bot.download(message.voice)
        text = await transcribe(data)
        request = _contextualize_vague_photo(message.from_user.id, text, parse_photo_request(text))
        if request:
            await handle_photo_request(message.chat.id, message.from_user.id, request)
            touch_user(message.from_user.id)
            return
        before_level = get_relationship_level(message.from_user.id, get_user_character(message.from_user.id))
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            display_name = 'ты' if (user and user.voice_anon_mode) else (message.from_user.first_name or 'ты')
            answer = await anna_reply(message.from_user.id, display_name, text, language_code=message.from_user.language_code, character_id=get_user_character(message.from_user.id))
        await send_answer(message, answer)
        try:
            from services.gamification_service import unlock_achievement
            unlock_achievement(message.from_user.id, 'voice_user')
        except Exception:
            pass
        # Detect if Anna offered a photo in her voice response
        if _PHOTO_OFFER_DETECT.search(answer):
            _photo_offer_pending[message.from_user.id] = _time.time()
            try:
                from services.photo_expression_service import detect_expression_key
                _photo_offer_expression[message.from_user.id] = detect_expression_key(text)
            except Exception:
                _photo_offer_expression.pop(message.from_user.id, None)
            logger.info('photo_offer_detected user=%s source=voice', message.from_user.id)
        await _notify_quest_unlocks(message.chat.id, message.from_user.id, before_level, get_relationship_level(message.from_user.id, get_user_character(message.from_user.id)))
        if is_premium(message.from_user.id) and create_from_text(message.from_user.id, text):
            user = get_user(message.from_user.id)
            tz = user.timezone or 'UTC' if user else 'UTC'
            await message.answer(f'и время тоже запомнила 😌 пояс: {tz}')
        touch_user(message.from_user.id)
    except Exception:
        logger.exception('voice handler')
        await message.answer('голосовое сейчас не получилось разобрать 😕')


@dp.message(Command('refundstars'))
async def refund_stars_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        await message.answer('эта команда только для владельца')
        return
    parts=(message.text or '').split()
    if len(parts)<3 or not parts[1].isdigit():
        await message.answer('Формат: /refundstars <telegram_id> <telegram_payment_charge_id> [stars]')
        return
    user_id=int(parts[1]); charge_id=parts[2]
    stars=int(parts[3]) if len(parts)>3 and parts[3].isdigit() else 0
    try:
        await bot.refund_star_payment(user_id=user_id, telegram_payment_charge_id=charge_id)
        record_refund(user_id, charge_id, stars)
        await message.answer('✅ Возврат Stars отправлен.')
    except Exception as exc:
        logger.exception('refund stars failed user=%s charge=%s', user_id, charge_id)
        await message.answer(f'Не удалось сделать возврат: {type(exc).__name__}')


@dp.message(Command('stats', 'adminstats'))
async def admin_stats_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    snap = admin_snapshot()
    await message.answer(
        '📊 Anna beta stats\n\n'
        f'Users: {snap["users_total"]} · active 24h: {snap["users_24h"]} · active 7d: {snap["users_7d"]}\n'
        f'New 7d: {snap["new_7d"]} · messages 24h: {snap["messages_24h"]}\n'
        f'Retention D1/D3/D7: {snap["d1_retention"]:.1f}% / {snap["d3_retention"]:.1f}% / {snap["d7_retention"]:.1f}%\n'
        f'Photo requests 24h: {snap["photo_requests_24h"]} · delivered sets: {snap["photos_24h"]}\n'
        f'Failures: {snap["photo_failures_24h"]} ({snap["photo_failure_rate"]:.1f}%) · partial: {snap["photo_partial_24h"]}\n'
        f'Avg first photo: {snap["first_frame_avg_seconds"]:.1f}s\n'
        f'Proactive 7d: {snap["proactive_replied_7d"]}/{snap["proactive_sent_7d"]} replies ({snap["proactive_reply_rate"]:.1f}%)\n'
        f'Photo feedback 7d: 🔥 {snap["feedback_like_7d"]} · 👎 {snap["feedback_dislike_7d"]}\n'
        f'Image cost: ${snap["photo_cost_24h"]:.2f}/24h · ${snap["photo_cost_30d"]:.2f}/30d\n'
        f'Stars 30d: {snap["stars_30d"]}'
    )

@dp.message(F.text)
async def text_message(message: types.Message):
    if (message.text or '').startswith('/'):
        return

    if not has_accepted(message.from_user.id):
        await message.answer('Сначала нужно подтвердить 18+ и принять условия через /start.', reply_markup=consent_keyboard())
        return

    idea_edit = _photo_idea_edit_sessions.get(message.from_user.id)
    if message.from_user.id in ADMIN_TELEGRAM_IDS and idea_edit:
        await _admin_idea_text_step(message, idea_edit)
        return

    payment_edit = _payment_method_edit_sessions.get(message.from_user.id)
    if message.from_user.id in ADMIN_TELEGRAM_IDS and payment_edit:
        value = (message.text or '').strip()
        mode = payment_edit.get('mode')
        if mode == 'add':
            step = payment_edit.get('step')
            method_type = payment_edit.get('method_type')
            draft = payment_edit.setdefault('draft', {})
            if step == 'name':
                if not 1 <= len(value) <= 120:
                    await message.answer('Название должно быть от 1 до 120 символов.')
                    return
                draft['display_name'] = value
                if method_type == 'qr':
                    payment_edit['step'] = 'qr'
                    await message.answer('Теперь пришли изображение QR-кода.\n\n/cancel — отменить')
                    return
                payment_edit['step'] = 'url'
                await message.answer('Теперь пришли HTTPS-ссылку провайдера.\n\n/cancel — отменить')
                return
            if step == 'qr':
                await message.answer('Здесь нужно прислать изображение QR-кода, а не текст.\n/cancel — отменить')
                return
            if step == 'url':
                if not value.lower().startswith('https://') or len(value) > 1000:
                    await message.answer('Пришли полную HTTPS-ссылку, например https://example.com/pay')
                    return
                method = create_payment_method('link', draft.get('display_name') or 'Провайдер')
                update_payment_method(method.id, external_url=value)
                _payment_method_edit_sessions.pop(message.from_user.id, None)
                await message.answer(
                    '✅ Способ оплаты сохранён.\n\n' + _admin_payment_summary(method.id),
                    reply_markup=admin_payment_keyboard(method.id),
                )
                return
        elif mode == 'edit':
            method_id = int(payment_edit['method_id'])
            field = payment_edit.get('field')
            try:
                if field == 'display_name':
                    if not 1 <= len(value) <= 120:
                        raise ValueError('Название должно быть от 1 до 120 символов.')
                    update_payment_method(method_id, display_name=value)
                elif field == 'instructions':
                    if len(value) > 1500:
                        raise ValueError('Инструкция должна быть короче 1500 символов.')
                    update_payment_method(method_id, instructions=value)
                elif field == 'url':
                    if not value.lower().startswith('https://') or len(value) > 1000:
                        raise ValueError('Пришли полную HTTPS-ссылку.')
                    update_payment_method(method_id, external_url=value)
                elif field == 'qr':
                    await message.answer('Для QR пришли изображение, а не текст.\n/cancel — отменить')
                    return
                else:
                    raise ValueError('Неизвестное поле способа оплаты.')
            except ValueError as exc:
                await message.answer(str(exc))
                return
            _payment_method_edit_sessions.pop(message.from_user.id, None)
            await message.answer(
                '✅ Способ оплаты обновлён.\n\n' + _admin_payment_summary(method_id),
                reply_markup=admin_payment_keyboard(method_id),
            )
            return

    card_edit = _character_card_edit_sessions.get(message.from_user.id)
    if message.from_user.id in ADMIN_TELEGRAM_IDS and card_edit:
        value = (message.text or '').strip()
        # Add-new-character flow
        if card_edit.get('mode') == 'add':
            step = card_edit.get('step')
            draft = card_edit.setdefault('draft', {})
            try:
                if step == 'id':
                    cid = value.lower()
                    if not re.match(r'^[a-z0-9_]+$', cid):
                        raise ValueError('ID только маленькие латинские буквы, цифры и подчёркивание.')
                    if get_card(cid):
                        raise ValueError('Такой ID уже есть.')
                    draft['character_id'] = cid
                    card_edit['step'] = 'display_name'
                    await message.answer('Шаг 2/5: отправь имя персонажа.\n\n/cancel — отменить')
                    return
                elif step == 'display_name':
                    if not 1 <= len(value) <= 48:
                        raise ValueError('Имя должно быть от 1 до 48 символов.')
                    draft['display_name'] = value
                    card_edit['step'] = 'gender'
                    await message.answer('Шаг 3/5: выбери пол персонажа.', reply_markup=_admin_gender_keyboard('admin:cardadd:gender'))
                    return
                elif step == 'age':
                    if not value.isdigit() or not 18 <= int(value) <= 99:
                        raise ValueError('Возраст должен быть числом от 18 до 99.')
                    draft['age'] = int(value)
                    card_edit['step'] = 'short_bio'
                    await message.answer('Шаг 5/5: отправь короткое описание.\n\n/cancel — отменить')
                    return
                elif step == 'short_bio':
                    if not 1 <= len(value) <= 900:
                        raise ValueError('Описание должно быть от 1 до 900 символов.')
                    emoji = {'male': '👨', 'female': '👩', 'other': '🎭'}.get(draft.get('gender', 'female'), '👩')
                    card = create_card(
                        draft['character_id'], draft['display_name'],
                        draft['age'], value, emoji, draft.get('gender', 'female')
                    )
                    _character_card_edit_sessions.pop(message.from_user.id, None)
                    await message.answer(
                        '✅ Карточка создана.\n\n' + _admin_card_summary(card.character_id),
                        reply_markup=admin_card_keyboard(card.character_id)
                    )
                    return
                else:
                    raise ValueError('Неизвестный шаг.')
            except ValueError as exc:
                await message.answer(str(exc))
                return
        # Existing edit flow
        character_id = card_edit['character_id']
        field = card_edit['field']
        try:
            if field == 'display_name':
                if not 1 <= len(value) <= 48:
                    raise ValueError('Имя должно быть от 1 до 48 символов.')
                update_card(character_id, display_name=value)
            elif field == 'age':
                if not value.isdigit() or not 18 <= int(value) <= 99:
                    raise ValueError('Возраст должен быть числом от 18 до 99.')
                update_card(character_id, age=int(value))
            elif field == 'short_bio':
                if not 1 <= len(value) <= 900:
                    raise ValueError('Описание должно быть от 1 до 900 символов.')
                update_card(character_id, short_bio=value)
            elif field == 'photo':
                await message.answer('для фото пришли изображение, а не текст. /cancel — отменить')
                return
            else:
                raise ValueError('Неизвестное поле карточки.')
        except ValueError as exc:
            await message.answer(str(exc))
            return
        _character_card_edit_sessions.pop(message.from_user.id, None)
        await message.answer('✅ Карточка обновлена.\n\n' + _admin_card_summary(character_id), reply_markup=admin_card_keyboard(character_id))
        return

    uid = ensure_user(message.from_user.id, message.from_user.first_name)
    track_event(uid, 'chat_user_message', metadata={'kind': 'text'})
    _track_proactive_reply_if_any(message.from_user.id, uid)
    cancel_active_wake(message.from_user.id)
    # V3.19.0: constructor name step — the next plain text is the persona name.
    constructor_name_session = _constructor_sessions.get(message.from_user.id)
    if constructor_name_session and constructor_name_session.get('await') == 'name':
        name_value = (message.text or '').strip()
        if not 1 <= len(name_value) <= 24:
            await message.answer('имя должно быть от 1 до 24 символов 🙂')
            return
        constructor_name_session['params']['name'] = name_value
        constructor_name_session['await'] = None
        await _constructor_face_step(message.chat.id, message.from_user.id)
        return
    try:
        from services.gamification_service import touch_activity, check_first_message
        gam = touch_activity(message.from_user.id)
        check_first_message(message.from_user.id)
        if gam and gam.get('streak_reward_credits'):
            await message.answer(
                f'🔥 {gam["streak_count"]} дней подряд! подарил {gam["streak_reward_credits"]} фото-кредитов за постоянство. '
                'Заходи завтра — серию нельзя прерывать 😊'
            )
    except Exception:
        pass
    if not can_send_message(message.from_user.id):
        await message.answer('на сегодня бесплатный лимит сообщений закончился. Premium: /premium')
        return
    text = message.text or ''
    try:
        # Check if user is accepting a photo offer from Anna
        offer_ts = _photo_offer_pending.get(message.from_user.id, 0)
        offer_active = offer_ts and (_time.time() - offer_ts < _PHOTO_OFFER_TTL)
        if offer_active and _PHOTO_ACCEPT.match(text.strip().lower()):
            _photo_offer_pending.pop(message.from_user.id, None)
            # Match the character's facial expression to the mood of the
            # conversation. Prefer the mood captured at the moment Anna offered
            # the photo (e.g. a compliment); fall back to the acceptance message.
            from services.photo_expression_service import detect_expression_key
            expr_key = _photo_offer_expression.pop(message.from_user.id, None) or detect_expression_key(text)
            # User accepted Anna's photo offer
            if has_free_photo(message.from_user.id, get_user_character(message.from_user.id)):
                req = PhotoRequest(scene='selfie', expression_key=expr_key)
                await _start_photo_background(message.chat.id, message.from_user.id, req, 'free')
            else:
                # Offer cheap photo for 5 stars instead of full price
                req = PhotoRequest(scene='selfie', expression_key=expr_key)
                offer_id = create_offer(message.from_user.id, req)
                await bot.send_message(
                    message.chat.id,
                    f'бесплатный лимит на сегодня кончился, но для тебя сейчас — {CHAT_PHOTO_OFFER_STARS}⭐ \u2728'
                )
                await send_stars_invoice(
                    message.chat.id, 'Фото от Анны', 'Персональное фото прямо сейчас',
                    f'photo:{offer_id}', CHAT_PHOTO_OFFER_STARS,
                )
            touch_user(message.from_user.id)
            return

        # Natural photo requests are routed before the chat model, so Anna does not
        # first refuse/chat about the photo and only then start generating.
        request = _contextualize_vague_photo(message.from_user.id, text, parse_photo_request(text))
        if request:
            await handle_photo_request(message.chat.id, message.from_user.id, request)
            touch_user(message.from_user.id)
            return
        before_level = get_relationship_level(message.from_user.id, get_user_character(message.from_user.id))
        # Instant game-like feedback: sometimes react to messages that grew the
        # bond (care/flirt signals), so the user feels the relationship moving.
        try:
            sig = infer_delta(text)
            if (sig.trust > 0 or sig.intimacy > 0) and random.random() < 0.30:
                await message.react([types.ReactionTypeEmoji(emoji='❤️')])
        except Exception:
            pass
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            answer = await anna_reply(message.from_user.id, message.from_user.first_name or 'ты', text, language_code=message.from_user.language_code, character_id=get_user_character(message.from_user.id))
        await send_answer(message, answer)
        # Detect if Anna offered a photo in her response
        if _PHOTO_OFFER_DETECT.search(answer):
            _photo_offer_pending[message.from_user.id] = _time.time()
            try:
                from services.photo_expression_service import detect_expression_key
                _photo_offer_expression[message.from_user.id] = detect_expression_key(text)
            except Exception:
                _photo_offer_expression.pop(message.from_user.id, None)
            logger.info('photo_offer_detected user=%s', message.from_user.id)
        await _notify_quest_unlocks(message.chat.id, message.from_user.id, before_level, get_relationship_level(message.from_user.id, get_user_character(message.from_user.id)))
        if is_premium(message.from_user.id):
            rid = create_from_text(message.from_user.id, text)
            if rid:
                user = get_user(message.from_user.id)
                tz = user.timezone or 'UTC' if user else 'UTC'
                await message.answer(f'и время тоже запомнила 😌 пояс: {tz}')
        touch_user(message.from_user.id)
    except Exception as exc:
        logger.exception('chat handler user=%s error=%s', message.from_user.id, type(exc).__name__)
        err_msg = str(exc)[:200] if exc else 'unknown'
        await message.answer(f'я сейчас немного зависла 😅 попробуй ещё раз\n\n💡 если повторяется — напиши /support')


# ---------------------------------------------------------------------------
# V3.19.6: tiny public web server for FreeKassa callbacks (card/SBP premium).
# Railway injects PORT; the public domain is configured via PUBLIC_BASE_URL.
# ---------------------------------------------------------------------------

async def _fk_notify(request: web.Request) -> web.Response:
    """FreeKassa server notification: verify SIGN (secret 2) and grant."""
    params = dict(request.query)
    if request.method == 'POST':
        try:
            form = await request.post()
            params.update({k: str(v) for k, v in form.items()})
        except Exception:
            pass
    ok, order_id_or_reason = freekassa_service.verify_notify(params)
    if not ok:
        logger.warning('FreeKassa notify rejected reason=%s params=%s', order_id_or_reason, {k: v for k, v in list(params.items())[:12]})
        return web.Response(text=f'NO|{order_id_or_reason}')
    order_id = int(order_id_or_reason)
    order = freekassa_service.get_order(order_id)
    if order and freekassa_service.mark_paid(order_id, json.dumps(params, ensure_ascii=False)):
        try:
            record_payment(
                order['telegram_id'], order['product'], 0,
                f'freekassa:{order_id}', provider='freekassa',
                provider_payload=f'amount={order["amount"]}',
            )
        except Exception:
            logger.exception('FreeKassa premium grant failed order=%s', order_id)
        try:
            await bot.send_message(
                order['telegram_id'],
                '💳 Оплата получена — Premium активирован на 30 дней! ✨',
            )
        except Exception:
            logger.exception('FreeKassa confirmation message failed order=%s', order_id)
    # FreeKassa expects a plain YES (or YES|<order id>) on success.
    return web.Response(text=f'YES|{order_id}')


async def _fk_success(request: web.Request) -> web.Response:
    return web.Response(
        text='✅ Оплата прошла! Premium уже включён — возвращайся в бот 💫',
        content_type='text/html',
    )


async def _fk_fail(request: web.Request) -> web.Response:
    return web.Response(
        text='Оплата не завершена. Попробуй ещё раз или оплати Stars прямо в боте ⭐',
        content_type='text/html',
    )


async def _healthz(request: web.Request) -> web.Response:
    return web.Response(text='ok')


async def _root(request: web.Request) -> web.Response:
    # V3.19.10: plain liveness page for the bare Railway domain. Without it the
    # public URL showed aiohttp's default "404: Not Found" and looked like a
    # broken deploy; only /healthz and the FreeKassa routes existed.
    return web.Response(
        text='AnnaBot web endpoint is alive. Health check: /healthz',
        content_type='text/plain',
    )


async def _start_web_server() -> None:
    app = web.Application()
    app.router.add_get('/', _root)
    app.router.add_route('*', '/freekassa/notify', _fk_notify)
    # Success/fail are browser redirects; FreeKassa may send them as GET or
    # POST depending on the merchant form method dropdown, so accept both.
    app.router.add_route('*', '/freekassa/success', _fk_success)
    app.router.add_route('*', '/freekassa/fail', _fk_fail)
    app.router.add_get('/healthz', _healthz)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', WEB_PORT)
    await site.start()
    logger.info('web server listening port=%s freekassa=%s base=%s', WEB_PORT, FREEKASSA_ENABLED, PUBLIC_BASE_URL or '-')


async def main():
    public_commands = [
        types.BotCommand(command='start', description='Начать общение'),
        types.BotCommand(command='photo', description='📸 Фото Анны'),
        types.BotCommand(command='premium', description='⭐ Premium'),
        types.BotCommand(command='gallery', description='🖼 Моя галерея'),
        types.BotCommand(command='collection', description='📸 Прогресс коллекции'),
        types.BotCommand(command='stories', description='🎯 Наши истории'),
        types.BotCommand(command='features', description='✨ Возможности бота'),
        types.BotCommand(command='paysupport', description='Помощь с оплатой'),
        types.BotCommand(command='support', description='Поддержка'),
        types.BotCommand(command='privacy', description='Конфиденциальность'),
        types.BotCommand(command='terms', description='Условия'),
        types.BotCommand(command='delete_me', description='Удалить мои данные'),
        types.BotCommand(command='settings', description='Настройки'),
        types.BotCommand(command='voice', description='Голосовые ответы'),
        types.BotCommand(command='voice_anon', description='Анонимный голосовой режим'),
        types.BotCommand(command='profile', description='Прогресс, стрик, достижения'),
        types.BotCommand(command='referral', description='🔗 Моя ссылка для приглашения'),
        types.BotCommand(command='contest', description='🏆 Гонка пригласивших'),
        types.BotCommand(command='notifications', description='Инициативные сообщения'),
        types.BotCommand(command='wake', description='Будильник: /wake 08:00'),
        types.BotCommand(command='reset', description='Очистить память и историю'),
    ]
    await bot.set_my_commands(public_commands)
    logger.info('startup admin_ids_count=%s', len(ADMIN_TELEGRAM_IDS))
    if not ADMIN_TELEGRAM_IDS:
        logger.warning('ADMIN_TELEGRAM_IDS is empty; /admin will be inaccessible')
    for admin_id in ADMIN_TELEGRAM_IDS:
        try:
            await bot.set_my_commands(
                public_commands + [types.BotCommand(command='admin', description='🛠 Админка'), types.BotCommand(command='refundstars', description='↩️ Возврат Stars'), types.BotCommand(command='geministatus', description='🧠 Gemini status')],
                scope=types.BotCommandScopeChat(chat_id=admin_id),
            )
        except Exception:
            logger.exception('failed to install admin command scope chat_id=%s', admin_id)
    ensure_default_cards()
    ensure_default_payment_methods()
    start_scheduler(bot)
    try:
        active_reminders = due_reminders()
        logger.info('startup active_reminders=%s ids=%s', len(active_reminders), [r.id for r in active_reminders])
    except Exception:
        logger.exception('startup reminder check failed')
    st = provider_status()
    logger.info(
        'LLM status: openrouter=%s model=%s gemini=%s gemini_model=%s video=%s',
        st['openrouter_key_present'], st['openrouter_model'], st['gemini_key_present'],
        st['gemini_model'], video_available(),
    )
    logger.info('AnnaBot started')
    await _start_web_server()
    # V3.19.11: refresh the public storefront (profile description) on every
    # deploy. A description failure must never block startup.
    try:
        await apply_bot_descriptions(bot)
    except Exception:
        logger.exception('bot description apply failed (non-fatal)')
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
