import asyncio
import base64
import datetime as dt
import io
import json
import logging
import random
import re
import secrets
import sys
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
    TELEGRAM_TOKEN, PREMIUM_MONTHLY_STARS, PREMIUM_WEEKLY_STARS, PREMIUM_WEEKLY_PHOTO_CREDITS,
    PREMIUM_QUARTERLY_STARS,
    PHOTO_COST_STARS, CUSTOM_PHOTO_COST_STARS,
    ADMIN_TELEGRAM_IDS, CHARACTER_ID, PHOTO_PROGRESS_MESSAGE_DELAY_SECONDS,
    AI_KEY, LIBRARY_MODERATION_ENABLED, LIBRARY_MODERATION_MODEL,
    GEMINI_VIDEO_ENABLED, VIDEO_COST_STARS, GALLERY_DOWNLOAD_STARS, WALLET_PAY_ENABLED,
    PREMIUM_DISCOUNT_PERCENT, DEMO_PREMIUM_HOURS,
    REFERRAL_REFERRER_CREDITS, REFERRAL_INVITEE_CREDITS,
    CONSTRUCTOR_COST_STARS, PHOTO_REACTION_ENABLED, PHOTO_REACTION_COOLDOWN_SECONDS,
    CONSTRUCTOR_COST_RUB, TOKEN_PRICE_RUB, TOKEN_PACK_SIZE, VIDEO_TOKEN_COST, COSPLAY_TOKEN_COST,
    CONSTRUCTOR_PRICE_USD, PREMIUM_WEEKLY_PRICE_USD, fiat_suffix,
    FREEKASSA_ENABLED, FREEKASSA_PREMIUM_PRICE_RUB, FREEKASSA_PREMIUM_WEEKLY_PRICE_RUB, FREEKASSA_PREMIUM_QUARTERLY_PRICE_RUB, FREEKASSA_PREMIUM_PRICE_USD, PUBLIC_BASE_URL, WEB_PORT,
    SUPPORT_BOT_USERNAME, SUPPORT_BOT_TOKEN, SUPPORT_WELCOME_TEXT,
    CHANNEL_SUBSCRIBE_USERNAME, CHANNEL_SUBSCRIBE_BONUS_CREDITS,
    PEACH_PACK_STARS, PEACH_PACK_CREDITS,
    FREEKASSA_MERCHANT_ID, FREEKASSA_API_KEY, FREEKASSA_API_ENABLED,
)
from services.user_service import (
    ensure_user, get_user, get_state, update_user_settings, touch_user,
    set_adult_confirmed, is_adult_confirmed,
)
# V3.22.0: RU/EN interface layer (reply keyboard + top-level menus).
from services.ui_lang import EN, RU, MAIN_KB_ROWS, kb_label, kb_pair, user_lang
from services.chat_service import reply as anna_reply
from services.access_service import can_send_message, is_premium
from services.photo_service import (
    PhotoRequest, parse_photo_request, deliver_photo, has_free_photo, build_photo_menu,
    create_offer, consume_offer, scene_allowed_for_stage, get_relationship_stage,
    get_relationship_level, is_custom_request, requires_adult_confirmation,
    SCENE_LEVELS, SCENES, PhotoGenerationError, get_latest_photo_delivery, get_photo_delivery_for_user,
    get_gallery_page, get_gallery_item_bytes, GALLERY_PAGE_SIZE, generate_custom_avatar,
    generate_photo_set, photo_frame_bytes, AUTO_CAPTIONS,
    admin_pool_count, admin_pool_get, admin_pool_latest_id, admin_pool_neighbor, admin_pool_set_shared,
    ensure_custom_avatar_cached,
)
from services.photo_idea_service import (
    idea_counts, list_admin_ideas, add_admin_idea, delete_admin_idea,
)
from services.payments import record_payment, get_photo_credits, record_refund, grant_premium, revoke_premium, consume_premium_video_free, premium_video_free_left, consume_photo_credit, grant_photo_credits, has_credit_grant, revoke_photo_credits
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
from services import jobs_service
from services import dialog_store
from aiohttp import web
from services import apartment_service, gifts_service, dates_service, spicy_service
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
from services.memory_service import reset_conversation as reset_memory, save_message
from services.provider_stats_service import provider_snapshot, record_provider
from services.db import SessionLocal
from models.relationship_models import UserCharacterRelationship, RelationshipEvent, RelationshipMilestone
from models.app_models import CharacterState, Reminder, User
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
    custom_character_id, get_custom_character, get_custom_character_by_id, save_custom_character,
    summary_lines, step_index, is_custom_character,
)
from services.consent_service import has_accepted, accept as accept_consent, delete_user_data, TERMS_VERSION, PRIVACY_VERSION
from services.collection_service import collection_progress
from services.quest_service import QUESTS, QUEST_REPLAY_STARS, story_status, get_quest, complete_route, create_replay_offer, consume_replay_offer, premium_replays_left, consume_premium_replay, newly_unlocked_quests
from services.payment_method_service import (
    list_payment_methods, get_payment_method, create_payment_method,
    update_payment_method, delete_payment_method, ensure_default_payment_methods,
    public_payment_methods, is_button_enabled,
)
from services import donation_service
from services import legal_service
from services import webapp_service

# V3.30.2: /fkcheck diagnostics print the deployed build straight from the
# VERSION file so the owner can confirm Railway picked up the new commit.
VERSION = (Path(__file__).resolve().parent / 'VERSION').read_text(encoding='utf-8').strip()
# V3.39.0: Come Closer-style /start — the welcome leads with a group photo.
WELCOME_BANNER_PATH = Path(__file__).resolve().parent / 'data' / 'media' / 'welcome_banner.png'

# V3.30.1: Railway tags every stderr line as severity=error, and Python
# logging writes to stderr by default — route the whole log to stdout so
# INFO stays INFO in the Railway console.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    stream=sys.stdout,
)
# The 30-second reminder tick and the per-update aiogram lines flood the
# log; keep them silent unless something actually warns.
logging.getLogger('apscheduler').setLevel(logging.WARNING)
logging.getLogger('aiogram.event').setLevel(logging.WARNING)
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
    # V3.30.0: the two explicit adult buttons left the menu — the image
    # providers moderate them into HTTP 422 almost every time. Those scenes
    # stay in photo_service only for old library photos.
]

# V3.30.0: cosplay photoshoot costumes. V3.31.7: each value is a 4-tuple
# (label, wardrobe prompt fragment, iconic hairstyle, iconic hair color).
# The scene is token-priced (COSPLAY_TOKEN_COST) and fully clothed.
# V3.31.7: the hairstyle/hair color travel in their own PhotoRequest fields so
# the prompt carries exactly ONE hairstyle for the costume (the old prompts
# stacked a pool hairstyle on top of the costume hair); empty strings keep the
# generic pools for the classic costumes.
COSPLAY_COSTUMES = {
    'maid': ('🖤 Горничная', 'a cute french-maid cosplay: black dress, white apron, lace headband', '', ''),
    'nurse': ('💉 Медсестра', 'a playful nurse cosplay: white dress and cap with a red cross', '', ''),
    'cat': ('🐱 Кошка-герл', 'a catgirl cosplay with cat ears, a bell collar and a tail', '', ''),
    'bunny': ('🐰 Банни', 'a bunny cosplay with long ears, a bow tie and fluffy cuffs', '', ''),
    'elf': ('🧝 Эльфийка', 'a fantasy elf cosplay: leaf-green dress, circlet, pointed ears', '', ''),
    'witch': ('🧙 Ведьмочка', 'a witch cosplay: pointed hat and a dark cloak with silver clasps', '', ''),
    'superhero': ('🦸 Супергероиня', 'a sleek superheroine cosplay with a domino mask and a cape', '', ''),
    'police': ('🚔 Полицейская', 'a police cosplay uniform with a peaked cap and a shiny badge', '', ''),
    # V3.31.6: sexy + popular video-game heroines (owner request). The label
    # names the recognisable character; the prompt describes her iconic costume
    # concretely and stays fully clothed so it clears provider moderation.
    # V3.31.7: hair moved out of the costume prompt into the iconic-hair fields.
    'nier2b': ('🤍 2B · NieR', 'a battle-android cosplay: elegant black gothic-lolita dress with puffed sleeves and a white blindfold visor', 'a short silver-white bob with a soft loose fringe', 'silver-white'),
    'lara': ('🏹 Лара Крофт', 'a tomb-raider cosplay: fitted teal tank top, brown cargo shorts, fingerless gloves and twin holsters', 'a single long braid falling over her shoulder', 'chestnut brown'),
    'tifa': ('🥊 Тифа · FF7', 'a martial-artist cosplay: black sleeveless top, a dark miniskirt with suspenders and red-and-black gloves', 'long straight dark hair falling down her back', 'dark brunette'),
    'chunli': ('🐉 Чун-Ли · SF', 'a fighting-game cosplay: blue qipao-style dress with gold trim and white combat boots', 'two neat covered buns with ribbons on top of her head', 'dark brown'),
    'ahri': ('🦊 Арри · LoL', 'a nine-tailed fox-spirit cosplay: white-and-crimson kimono-style outfit with fox ears and fluffy tails', 'long flowing wavy hair down to her waist', 'silver-lavender'),
    'dva': ('🎮 D.Va · Overwatch', 'a futuristic pilot cosplay: white-and-pink bodysuit with a bunny emblem, a headset and glowing face marks', 'a sleek long high ponytail', 'chestnut brown'),
    'bayonetta': ('🕶 Байонетта', 'a stylish witch cosplay: sleek black bodysuit under a cropped jacket and round red glasses', 'a tall elegant beehive updo with two long face-framing strands', 'jet black'),
    'yennefer': ('🖤 Йеннифэр · Witcher', 'a sorceress cosplay: black-and-white velvet gown with silver embroidery and a dark choker', 'long loose voluminous curls falling past her shoulders', 'violet-black'),
    'raiden': ('⚡ Райдэн · Genshin', 'a thunder-shogun cosplay: deep purple-and-gold kimono-style battle dress with a katana at her hip', 'a very long braid falling to her waist', 'lavender purple'),
    'ada': ('🌹 Ада Вонг · RE', 'a secret-agent cosplay: elegant red dress with a strap leg holster and dark sunglasses', 'a sleek chin-length bob with a side-swept fringe', 'jet black'),
}

# V3.21.0: emotional level names; levels 7-8 are the premium-only plateau.
RELATIONSHIP_LEVEL_NAMES = {
    1: 'Знакомство',
    2: 'Симпатия',
    3: 'Флирт',
    4: 'Влюблённость',
    5: 'Любовники',
    6: 'Наша история',
    7: 'Родственные души',
    8: 'Одно целое',
}
MAX_RELATIONSHIP_LEVEL = len(RELATIONSHIP_LEVEL_NAMES)

# Short-lived UI state only. Paid offers themselves are persisted in PostgreSQL.
# V3.29.0: user-facing wizard state persists in dialog_sessions so a
# redeploy no longer drops paid flows mid-conversation.
_custom_drafts = dialog_store.DialogStore('custom_drafts')
_pending_adult_photo = dialog_store.DialogStore('pending_adult_photo', codec='photo_request')
_pending_adult_custom: set[int] = set()

# Background photo jobs: Telegram handlers return immediately, so normal chat remains responsive.
# A persistent DB queue is a later scaling step; for the closed beta one active job per user
# is enough to prevent duplicate spending and double taps.
_photo_jobs: dict[int, asyncio.Task] = {}
_photo_job_reservations: set[int] = set()

# Track when Anna offers a photo in chat — next user "yes" triggers photo flow
_photo_offer_pending = dialog_store.DialogStore('photo_offer_pending')  # telegram_id -> timestamp of offer
_photo_offer_expression = dialog_store.DialogStore('photo_offer_expression')  # telegram_id -> chat mood that triggered the offer
# V3.23.0: paid fantasy constructor — telegram_id -> (charge_id, amount) while
# the bot waits for the user's scenario description.
# V3.29.0: JSON stores the (charge, amount) tuple as a list; consumers unpack.
_fantasy_pending = dialog_store.DialogStore('fantasy_pending')
# V3.38.0: «👥 Поддержка» reply-button flow — telegram_id -> timestamp while
# the bot waits for the user's support message (next plain text is forwarded
# to the owner instead of being read by the character).
_support_pending = dialog_store.DialogStore('support_pending')
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

# Regex: user accepts a photo offer. V3.26.1: the old pattern was anchored
# with $ so «давай буду рад )» was not an acceptance and the chat model
# role-played a fake photo instead of the real flow. Prefix + word boundary
# is enough; a «нет» guard lives at the call site.
_PHOTO_ACCEPT = re.compile(
    r'^(да|давай|даа|дааа|ок|окей|хочу|конечно|скинь|кинь|кидай|'
    r'покажи|показывай|присылай|ну давай|ага|угу|ес|yep|yes|sure)\b'
    r'(?!.*(?:потом|позже|как-нибудь|не надо|не нужно|в другой раз|может быть|наверное))',
    re.I
)

# V3.26.1: the chat model sometimes "sends" a photo by role-playing it in
# square brackets ([фото: ...]). That text must never reach the user — strip
# it and deliver a real photo instead.
_FAKE_PHOTO_BLOCK = re.compile(r'\[(?:фото|photo)\s*:[^\]\n]{0,300}\]', re.I)


def _strip_fake_photo(text: str) -> tuple[str, bool]:
    cleaned, hits = _FAKE_PHOTO_BLOCK.subn('', text)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
    return cleaned, hits > 0


async def _photo_accept_flow(chat_id: int, telegram_id: int, expr_key: str | None = None) -> None:
    """Shared accept path: free daily photo or the cheap Stars offer."""
    req = PhotoRequest(scene='selfie', expression_key=expr_key)
    if has_free_photo(telegram_id, get_user_character(telegram_id)):
        await _start_photo_background(chat_id, telegram_id, req, 'free')
    else:
        offer_id = create_offer(telegram_id, req)
        await bot.send_message(
            chat_id,
            f'бесплатный лимит на сегодня кончился, но для тебя сейчас — {CHAT_PHOTO_OFFER_STARS}⭐{fiat_suffix(CHAT_PHOTO_OFFER_STARS)} ✨'
        )
        await send_stars_invoice(
            chat_id, f'Фото от {_character_display_name(get_user_character(telegram_id))}', 'Персональное фото прямо сейчас',
            f'photo:{offer_id}', CHAT_PHOTO_OFFER_STARS,
        )


async def _deliver_intercepted_photo(message: types.Message) -> None:
    """The model role-played sending a photo — deliver a real one instead."""
    if message.from_user.id in _photo_jobs and not _photo_jobs[message.from_user.id].done():
        return
    await _photo_accept_flow(message.chat.id, message.from_user.id)

from config import CHAT_PHOTO_OFFER_STARS
from config import VIDEO_STATUS_TEXT

# Video jobs are intentionally limited to one per user. They can
# take minutes during peak load, so generation always runs in background.
_video_jobs: dict[int, asyncio.Task] = {}

# V3.28.0: every long generation also gets a background_jobs DB row, so a
# redeploy no longer loses jobs silently and future workers can see them.
async def _track_job(job_id: int, coro):
    try:
        await coro
        jobs_service.finish_job(job_id, 'done')
    except Exception as exc:
        try:
            jobs_service.finish_job(job_id, 'failed', str(exc)[:500])
        except Exception:
            logger.exception('job finalize failed job=%s', job_id)
        raise


def _spawn_job(kind: str, telegram_id: int, coro, payload: dict | None = None) -> asyncio.Task:
    priority = 1 if is_premium(telegram_id) else 0
    job_id = jobs_service.begin_job(telegram_id, kind, payload, priority=priority)
    return asyncio.create_task(_track_job(job_id, coro))

# Owner-only Telegram photo-library importer. Images stay on Telegram; only file_id metadata is persisted.
_library_import_sessions: dict[int, dict] = {}

# Owner-only editor state for public character cards. Persistent card values live in PostgreSQL.
_character_card_edit_sessions: dict[int, dict] = {}

# V3.43.3: admin ids waiting to send the storefront card media (photo/gif/mp4)
# for a character — populated by the «📥 Медиа витрины» button in the admin panel.
CARD_MEDIA_WAIT: dict[int, str] = {}

# Owner-only editor state for configurable payment methods. Payment rows live in PostgreSQL.
_payment_method_edit_sessions: dict[int, dict] = {}

# Owner-only editor state for photo ideas. Idea rows live in PostgreSQL.
_photo_idea_edit_sessions: dict[int, dict] = {}

# V3.31.2: owner-only state for the «🎁 Выдать премиум/токены» button flow.
_admin_grant_sessions: dict[int, dict] = {}

# Scenes that admins may attach photo ideas to (private scenes stay untouched).
ALLOWED_IDEA_SCENES = tuple(sorted(k for k in SCENES if k not in {'personal', 'lingerie', 'private_fashion'}))

# Per-user selected character (telegram_id -> character_id). Memory is only a
# cache: the choice is persisted in User.selected_character (V3.22.0), so a
# redeploy/restart no longer silently switches everyone back to Anna.
_user_character: dict[int, str] = {}


def get_user_character(telegram_id: int) -> str:
    """Return the character_id the user currently chats with, or CHARACTER_ID as default."""
    cached = _user_character.get(telegram_id)
    if cached:
        return cached
    try:
        user = get_user(telegram_id)
        selected = (getattr(user, 'selected_character', '') or '').strip() if user else ''
        if selected:
            _user_character[telegram_id] = selected
            return selected
    except Exception:
        pass
    return CHARACTER_ID


def set_user_character(telegram_id: int, character_id: str) -> None:
    """Select a character and persist it so it survives restarts."""
    _user_character[telegram_id] = character_id
    try:
        update_user_settings(telegram_id, selected_character=character_id)
    except Exception:
        logger.exception('failed to persist selected character user=%s', telegram_id)

def _character_display_name(character_id: str) -> str:
    """V3.31.8: user-facing name of a character for invoice titles. Before this
    every Stars invoice said «Анна» even when the user was chatting with Emily
    or their own constructor persona."""
    try:
        card = get_card(character_id)
        if card and card.display_name:
            return card.display_name
    except Exception:
        pass
    return 'Анна'


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


def main_keyboard(is_admin: bool = False, telegram_id: int | None = None):
    # V3.21.0: every feature gets a visible first-row button — nothing is
    # buried in sub-menus (owner could not discover circles before).
    # V3.22.0: labels are localized per user (RU/EN).
    # V3.40.0: the «open app» row is a real web_app button — the teal
    # direct-launch tile from the Come Closer menu the owner benchmarked.
    lang = user_lang(telegram_id) if telegram_id else RU
    rows = []
    for row in MAIN_KB_ROWS:
        rows.append([
            KeyboardButton(
                text=kb_label(key, lang),
                web_app=types.WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp')
                if key == 'app' and PUBLIC_BASE_URL else None,
            )
            for key in row
        ])
    if is_admin:
        rows.append([KeyboardButton(text=kb_label('admin', lang))])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


def _character_pick_buttons(kind: str):
    # V3.39.0: flat pick buttons without the old per-button status suffix —
    # callers chunk them two per row so /start no longer shows a ten-row wall
    # of buttons (owner: «замени, чтобы оно было как-то компактно, удобно»).
    buttons = []
    for card in list_cards(visible_only=True):
        if card.status == 'active':
            text = f'✅ {card.display_name}'
        elif card.status == 'premium':
            text = f'⭐ {card.display_name}'
        else:
            text = f'🔒 {card.display_name}'
        prefix = 'onboard:character' if kind == 'onboard' else 'character:view'
        buttons.append(InlineKeyboardButton(text=text, callback_data=f'{prefix}:{card.character_id}'))
    return buttons


def _pair_rows(buttons):
    """V3.39.0: chunk flat inline buttons into a two-per-row keyboard."""
    return [buttons[i:i + 2] for i in range(0, len(buttons), 2)]


def onboarding_character_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=_pair_rows(_character_pick_buttons('onboard')))


def _welcome_banner_file():
    """V3.39.0: the group banner photo for /start; None when the asset is absent."""
    if WELCOME_BANNER_PATH.exists():
        return FSInputFile(WELCOME_BANNER_PATH)
    return None


def _welcome_back_rows(lang: str):
    """V3.42.0: the returning-user welcome is a short button list, not a wall —
    open the app, the partner program (full-width), terms + privacy. The old
    nine-button character grid is gone: character selection lives in the app.
    V3.42.1: owner asked to also surface «🍑 Пополнить персики» (photo credits)
    and «👥 Поддержка» right on the welcome screen."""
    rows = []
    if PUBLIC_BASE_URL:
        rows.append([InlineKeyboardButton(
            text='📱 Открыть приложение' if lang == RU else '📱 Open the app',
            web_app=types.WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp'),
        )])
    rows.append([InlineKeyboardButton(
        text=kb_label('credits', lang), callback_data='credits:open')])
    rows.append([InlineKeyboardButton(
        text=kb_label('partner', lang), callback_data='partner:open')])
    rows.append([InlineKeyboardButton(
        text=kb_label('support', lang), url=f'https://t.me/{SUPPORT_BOT_USERNAME}')])
    rows.append([
        InlineKeyboardButton(text='📄 Условия' if lang == RU else '📄 Terms', callback_data='legal:terms'),
        InlineKeyboardButton(text='🔐 Privacy', callback_data='legal:privacy'),
    ])
    return rows


def abilities_text(lang: str = RU) -> str:
    if lang == EN:
        return (
            '✨ What I can do\n\n'
            '💬 real conversation with personality — I remember the context and adapt to your style over time\n'
            '❤️ the relationship grows through levels 1–8: each level gets closer and more open (7–8 are a Premium plateau)\n'
            '🎯 interactive stories: your first choice becomes canon, and you can replay alternate branches later\n'
            '📸 photos right in the chat: type “send a photo” or “I want to see you” — I send a fresh shot for the moment; sometimes I offer one myself while flirting\n'
            '🎬 an “Animate photo” button under every shot — a short AI video from any photo (Premium: 2 free per day)\n'
            '🎥 video circles — “from me” circles with my voice (Premium only)\n'
            '🎯 daily quest — a small request from me every day, completing it earns attention points\n'
            '🏠 apartment: visit the rooms, spend time with me — new rooms open as the relationship grows\n'
            '💕 dates: invite me somewhere, and afterwards I send you a photo from our outing\n'
            '🎁 gifts: nice surprises that bring us closer\n'
            '🎙 voice replies: every girl has her own sweet voice, I answer in your language\n'
            '🖼 a collection of unlocked photos by relationship level\n'
            '💌 sometimes I write first and return to an unfinished topic\n'
            '⏰ alarm and reminders — a Premium feature: I wake you up on time and remember your timezone\n\n'
            '🎯 The first story is already available — start it right away or just write to me.'
        )
    return (
        '✨ Что умеет бот\n\n'
        '💬 живое общение с характером — она запоминает контекст и со временем подстраивается под твою манеру общения\n'
        '❤️ отношения развиваются по уровням 1–8: с каждым уровнем общение и образы становятся ближе и откровеннее (7–8 — плато для Premium)\n'
        '🎯 интерактивные истории: твой первый выбор становится каноном, а альтернативные ветки можно посмотреть позже\n'
        '📸 фото прямо в чате: напиши «скинь фото» или «хочу тебя увидеть» — она пришлёт свежий кадр по ситуации; иногда предлагает сама во время флирта\n'
        '🎬 кнопка «Оживить фото» под каждым снимком — короткое AI-видео из любого фото (Premium: 2 бесплатно в день)\n'
        '🎥 кружочки — видео-кружочки «от неё» с её голосом (только Premium)\n'
        '🎯 задание дня — маленькая просьба от неё каждый день, выполнение даёт очки внимания\n'
        '🏠 квартира: заходи в комнаты, проводи с ней время — новые комнаты открываются с уровнями отношений\n'
        '💕 свидания: пригласи её куда-нибудь, а после она пришлёт фото с прогулки\n'
        '🎁 подарки: приятные сюрпризы, которые сближают\n'
        '🎙 голосовые ответы: у каждой девушки свой милый голос, отвечает на твоём языке\n'
        '🖼 коллекция открытых фотографий по уровням отношений\n'
        '💌 она иногда может написать первой и вернуться к незаконченной теме\n'
        '⏰ будильник и напоминания — Premium-функция: разбудит вовремя и запомнит твой часовой пояс\n\n'
        '🎯 Первая история уже доступна — можешь начать её сразу или просто написать мне.'
    )


def abilities_inline_keyboard(lang: str = RU):
    if lang == EN:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='💬 Start chatting', callback_data='onboard:meet')],
            [InlineKeyboardButton(text='🎯 First story', callback_data='quest:view:outfit_choice')],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='💬 Начать общение', callback_data='onboard:meet')],
        [InlineKeyboardButton(text='🎯 Первая история', callback_data='quest:view:outfit_choice')],
    ])


def consent_keyboard(lang: str = RU):
    # V3.41.0: the owner wants the Mini App reachable straight from the first
    # welcome screen — a «📱 Открыть приложение» web_app button right under the
    # 18+ gate (terms/privacy stay). Added only when PUBLIC_BASE_URL is set.
    app_url = f'{PUBLIC_BASE_URL}/webapp' if PUBLIC_BASE_URL else None
    if lang == EN:
        rows = [[InlineKeyboardButton(text='✅ I am 18+ · I accept the terms', callback_data='consent:accept')]]
        if app_url:
            rows.append([InlineKeyboardButton(text='📱 Open the app', web_app=types.WebAppInfo(url=app_url))])
        rows.append([InlineKeyboardButton(text='📄 Terms', callback_data='consent:terms'), InlineKeyboardButton(text='🔐 Privacy', callback_data='consent:privacy')])
        return InlineKeyboardMarkup(inline_keyboard=rows)
    rows = [[InlineKeyboardButton(text='✅ Мне 18+ · принимаю условия', callback_data='consent:accept')]]
    if app_url:
        rows.append([InlineKeyboardButton(text='📱 Открыть приложение', web_app=types.WebAppInfo(url=app_url))])
    rows.append([InlineKeyboardButton(text='📄 Условия', callback_data='consent:terms'), InlineKeyboardButton(text='🔐 Privacy', callback_data='consent:privacy')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def legal_keyboard(lang: str = RU):
    """V3.32.0: permanent legal access for the payment partner's bank review."""
    if lang == EN:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='🔐 Privacy policy', callback_data='legal:privacy')],
            [InlineKeyboardButton(text='📄 User agreement', callback_data='legal:terms')],
            [InlineKeyboardButton(text='💰 Prices & tariffs', callback_data='legal:tariffs')],
            [InlineKeyboardButton(text='🛟 Support', callback_data='legal:support')],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔐 Политика конфиденциальности', callback_data='legal:privacy')],
        [InlineKeyboardButton(text='📄 Пользовательское соглашение', callback_data='legal:terms')],
        [InlineKeyboardButton(text='💰 Цены и тарифы', callback_data='legal:tariffs')],
        [InlineKeyboardButton(text='🛟 Поддержка', callback_data='legal:support')],
    ])


async def _send_legal_doc(chat_id: int, text: str, lang: str = RU):
    """V3.32.0: send a full legal document, split into Telegram-sized messages."""
    notice = legal_service.legal_doc_notice(lang)
    full = (notice + '\n\n' + text) if notice else text
    for chunk in legal_service.split_legal_text(full):
        await bot.send_message(chat_id, chunk)


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
            rows.append([InlineKeyboardButton(text=f"🔒 {route['label']} · replay {QUEST_REPLAY_STARS}⭐{fiat_suffix(QUEST_REPLAY_STARS)}", callback_data=f"quest:route:{quest_key}:{key}")])
        else:
            rows.append([InlineKeyboardButton(text=route['label'], callback_data=f"quest:route:{quest_key}:{key}")])
    rows.append([InlineKeyboardButton(text='⬅️ Истории', callback_data='quest:list')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def characters_keyboard(telegram_id: int | None = None):
    # V3.39.0: two characters per row — the old one-per-row wall was unreadable.
    rows = _pair_rows(_character_pick_buttons('view'))
    # V3.19.0: entry point to the personal character constructor.
    rows.append([InlineKeyboardButton(text=f'🎨 Создать свою · {CONSTRUCTOR_COST_STARS}⭐{fiat_suffix(CONSTRUCTOR_COST_STARS, rub=CONSTRUCTOR_COST_RUB, usd=CONSTRUCTOR_PRICE_USD)}', callback_data='constructor:start')])
    if FREEKASSA_ENABLED and telegram_id:
        rows.append([_fk_pay_button(
            'constructor_rub', CONSTRUCTOR_COST_RUB,
            f'🎭 Персонаж — {CONSTRUCTOR_COST_RUB} ₽ · ⚡СБП / карта')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_keyboard():
    # ADMIN_TELEGRAM_IDS is a set, so peek via next(iter(...)) instead of indexing.
    premium_state = ('✅ вкл' if is_premium(next(iter(ADMIN_TELEGRAM_IDS))) else '❌ выкл') if ADMIN_TELEGRAM_IDS else '—'
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🎭 Карточки персонажей', callback_data='admin:cards')],
        [InlineKeyboardButton(text='💳 Способы оплаты', callback_data='admin:payments')],
        [InlineKeyboardButton(text='📚 Библиотека фото', callback_data='admin:library_help')],
        [InlineKeyboardButton(text='🖼 Общая галерея (модерация)', callback_data='poolmod:view')],
        [InlineKeyboardButton(text='💡 Идеи для фото', callback_data='admin:ideas')],
        [InlineKeyboardButton(text='📊 Статистика', callback_data='admin:stats'),
         InlineKeyboardButton(text='🩺 Отказы', callback_data='admin:providers')],
        [InlineKeyboardButton(text='🎁 Выдать премиум/токены', callback_data='admin:grant')],
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
        # V3.43.3: the storefront card media swap — photo, GIF or video,
        # straight from the admin chat, no deploy needed.
        [InlineKeyboardButton(text='📥 Медиа витрины', callback_data=f'admin:cardmedia:{character_id}'),
         InlineKeyboardButton(text='🧹 Убрать медиа', callback_data=f'admin:cardclear:{character_id}')],
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
    elif method.method_type == 'builtin':
        # V3.31.1: admin switch for a hard-coded row of the user payment menu.
        value = 'кнопка в меню оплаты — видна пользователям, пока статус «включён»'
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
    # V3.22.0: every character card shows ITS OWN relationship level. Before,
    # only Anna's card had a level line and it read the viewer's currently
    # selected character — Emily's progress appeared on Anna's card.
    if viewer_id and card.character_id in LIBRARY_CHARACTERS:
        try:
            level = get_relationship_level(viewer_id, card.character_id)
            lines.append(f'❤️ {RELATIONSHIP_LEVEL_NAMES.get(level, "Знакомство")}')
        except Exception:
            pass
    if viewer_id and card.character_id == CHARACTER_ID:
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
    markup = None if admin_preview else characters_keyboard(telegram_id=viewer_id)
    if card.card_photo_file_id:
        await bot.send_photo(chat_id, card.card_photo_file_id, caption=text_value, reply_markup=markup)
        return
    fallback = _character_fallback_photo(character_id)
    if fallback and fallback.exists():
        await bot.send_photo(chat_id, FSInputFile(fallback), caption=text_value, reply_markup=markup)
        return
    await bot.send_message(chat_id, text_value, reply_markup=markup)


def _admin_card_media_label(character_id: str) -> str:
    """V3.43.3: what the storefront grid shows for this character right now."""
    override = webapp_service.character_card_override(character_id)
    if not override:
        return 'нет (в витрине статичное фото)'
    return {'.mp4': 'видео-петля', '.webp': 'анимированный стикер', '.gif': 'GIF',
            '.png': 'своё фото', '.jpg': 'своё фото'}.get(override.suffix.lower(), override.suffix)


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
        f'Фото: {"установлено" if card.card_photo_file_id else "нет"}\n'
        f'Медиа витрины: {_admin_card_media_label(character_id)}\n\n'
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


def _premium_tariff_lines(lang: str) -> list[str]:
    """V3.42.0: the tariff card the owner benchmarked (Come Closer screenshot).
    V3.43.0: three tiers with the competitor's prices (299 / 899 / 1799 ₽) —
    week, month and 3 months; the longer plans show their per-week price, a
    savings badge and the struck «instead of» price of buying them separately."""
    en = lang == EN
    wk_fiat = fiat_suffix(PREMIUM_WEEKLY_STARS, rub=FREEKASSA_PREMIUM_WEEKLY_PRICE_RUB, usd=PREMIUM_WEEKLY_PRICE_USD, rub_enabled=FREEKASSA_ENABLED)
    mo_fiat = fiat_suffix(PREMIUM_MONTHLY_STARS, rub=FREEKASSA_PREMIUM_PRICE_RUB, usd=FREEKASSA_PREMIUM_PRICE_USD, rub_enabled=FREEKASSA_ENABLED)
    q_fiat = fiat_suffix(PREMIUM_QUARTERLY_STARS, rub=FREEKASSA_PREMIUM_QUARTERLY_PRICE_RUB, rub_enabled=FREEKASSA_ENABLED)
    if FREEKASSA_ENABLED and FREEKASSA_PREMIUM_WEEKLY_PRICE_RUB and FREEKASSA_PREMIUM_PRICE_RUB:
        unit = '₽'
        week_full, month_full, quarter_full = FREEKASSA_PREMIUM_WEEKLY_PRICE_RUB, FREEKASSA_PREMIUM_PRICE_RUB, FREEKASSA_PREMIUM_QUARTERLY_PRICE_RUB
    else:
        unit = 'Stars'
        week_full, month_full, quarter_full = PREMIUM_WEEKLY_STARS, PREMIUM_MONTHLY_STARS, PREMIUM_QUARTERLY_STARS
    was = 4 * week_full
    save = max(0, round((1 - month_full / was) * 100)) if was else 0
    month_pw = round(month_full / 4)
    badge = f'  −{save}%' if save else ''
    strike = f'   ({"вместо" if not en else "instead of"} {was} {unit})' if save else ''
    q_was = 12 * week_full
    q_save = max(0, round((1 - quarter_full / q_was) * 100)) if q_was else 0
    q_pw = round(quarter_full / 12)
    q_badge = f'  −{q_save}%' if q_save else ''
    q_strike = f'   ({"вместо" if not en else "instead of"} {q_was} {unit})' if q_save else ''
    if en:
        return [
            '⭐ Plans:',
            '',
            f'○  1 week — {PREMIUM_WEEKLY_STARS} Stars{wk_fiat}',
            f'     {week_full} {unit} per week',
            f'●  1 month — {PREMIUM_MONTHLY_STARS} Stars{mo_fiat}{badge}',
            f'     {month_pw} {unit} per week{strike}',
            f'○  3 months — {PREMIUM_QUARTERLY_STARS} Stars{q_fiat}{q_badge}',
            f'     {q_pw} {unit} per week{q_strike}',
        ]
    return [
        '⭐ Тарифы:',
        '',
        f'○  1 неделя — {PREMIUM_WEEKLY_STARS} Stars{wk_fiat}',
        f'     {week_full} {unit} в неделю',
        f'●  1 месяц — {PREMIUM_MONTHLY_STARS} Stars{mo_fiat}{badge}',
        f'     {month_pw} {unit} в неделю{strike}',
        f'○  3 месяца — {PREMIUM_QUARTERLY_STARS} Stars{q_fiat}{q_badge}',
        f'     {q_pw} {unit} в неделю{q_strike}',
    ]


def premium_pitch_text(telegram_id: int) -> str:
    """V3.20.0: paywall pitch with retention hooks — the one-time discount
    countdown when active and a level-6 plateau line for maxed relationships.
    V3.22.0: localized RU/EN."""
    lang = user_lang(telegram_id)
    if lang == EN:
        lines = [
            'Premium:',
            '• unlimited messages — I never “fall asleep” mid-conversation 😴',
            '• 12 extra photo credits',
            '• 2 free photo animations every day 🎬',
            '• 🎥 video circles from me — Premium only',
            '• 💋 relationship levels 7–8 — “Kindred spirits” and “One whole”',
            '• 2 free replays of alternative quest branches per month',
            '• more memory, initiative and morning/evening messages',
        ]
    else:
        lines = [
            'Premium:',
            '• безлимит сообщений — я больше не «засыпаю» посреди разговора 😴',
            '• 12 дополнительных photo credits',
            '• 2 бесплатных оживления фото каждый день 🎬',
            '• 🎥 видео-кружочки от меня — только для Premium',
            '• 💋 уровни 7–8 отношений — «Родственные души» и «Одно целое»',
            '• 2 бесплатных replay альтернативных квест-веток в месяц',
            '• больше памяти, инициативы и утренних/вечерних сообщений',
        ]
    # V3.42.0: the Come Closer-style tariff card (owner screenshot) — radio
    # list with per-week prices and a savings badge, then the one-time-payment
    # footer, then the photo/intimacy and Stars notes.
    lines.append('')
    lines.extend(_premium_tariff_lines(lang))
    lines.append('')
    lines.append('One-time payment, no auto-renewal.' if lang == EN else 'Разовый платёж, без автопродления.')
    lines.append('')
    if lang == EN:
        lines += [
            'Free photos depend on intimacy: levels 1–2 — 1/day, 3–6 — 2/day.',
            'The relationship cannot be bought — it grows from conversation. Custom photos are paid separately.',
            '',
            '💳 Digital purchases inside Telegram are paid with Telegram Stars.',
        ]
    else:
        lines += [
            'Бесплатные фото зависят от близости: 1–2 уровень — 1/день, 3–6 — 2/день.',
            'Отношения не покупаются — они развиваются из общения. Кастомные фото оплачиваются отдельно.',
            '',
            '💳 Цифровые покупки внутри Telegram оплачиваются через Telegram Stars.',
        ]
    from services.retention_service import discount_info
    discount = discount_info(telegram_id)
    if discount.get('active'):
        if lang == EN:
            lines.insert(0, f'🔥 Just for you: −{discount["percent"]}% discount for {discount["hours_left"]:.0f} more hours — then it is {PREMIUM_MONTHLY_STARS} Stars again!')
        else:
            lines.insert(0, f'🔥 Только для тебя: скидка −{discount["percent"]}% ещё {discount["hours_left"]:.0f} ч — потом снова {PREMIUM_MONTHLY_STARS} Stars!')
        lines.insert(1, '')
    try:
        if not is_premium(telegram_id) and get_relationship_level(telegram_id, get_user_character(telegram_id)) >= 6:
            lines.append('')
            if lang == EN:
                lines.append('💋 our story is almost at the top… two more levels of intimacy ahead — “Kindred spirits” and “One whole”. That plateau is Premium only.')
            else:
                lines.append('💋 наша история почти на вершине… впереди ещё два уровня близости — «Родственные души» и «Одно целое». Это плато только для премиума.')
    except Exception:
        pass
    return '\n'.join(lines)


def _sleep_block_markup(telegram_id: int) -> InlineKeyboardMarkup:
    """V3.20.0 daily-limit paywall: demo premium first, then premium."""
    from services.retention_service import has_used_demo, discount_info
    rows = []
    if not has_used_demo(telegram_id):
        rows.append([InlineKeyboardButton(text=f'🎁 Демо-Premium на {DEMO_PREMIUM_HOURS} часа — бесплатно', callback_data='retention:demo')])
    discount = discount_info(telegram_id)
    if discount.get('active'):
        label = f'⭐ Premium −{discount["percent"]}% — {discount["price"]}⭐ (осталось {discount["hours_left"]:.0f} ч)'
    else:
        label = '⭐ Premium — разбудить без лимитов'
    rows.append([InlineKeyboardButton(text=label, callback_data='retention:premium')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _sleep_block_reply(message: types.Message) -> None:
    """V3.20.0: blocks pleasure (the conversation), not features — she simply
    "falls asleep". First limit hit offers the free demo; once the demo is
    spent, the one-time 24h discount window opens."""
    from services.retention_service import pick_text, has_used_demo, offer_discount
    uid = ensure_user(message.from_user.id, message.from_user.first_name)
    if has_used_demo(message.from_user.id):
        offer_discount(message.from_user.id)
    track_event(uid, 'chat_sleep_block')
    await message.answer(pick_text('sleep'), reply_markup=_sleep_block_markup(message.from_user.id))


# V3.27.0: ruble-shop balances (tokens + constructor credit) live on the users
# table; the helpers below keep every read-modify-write in one place.
def get_token_balance(telegram_id: int) -> int:
    with SessionLocal() as s:
        row = s.query(User).filter(User.telegram_id == str(telegram_id)).first()
        return int(row.token_balance or 0) if row else 0


def spend_tokens(telegram_id: int, amount: int) -> bool:
    with SessionLocal() as s:
        row = s.query(User).filter(User.telegram_id == str(telegram_id)).first()
        if not row or (row.token_balance or 0) < amount:
            return False
        row.token_balance = (row.token_balance or 0) - amount
        s.commit()
        return True


def add_tokens(telegram_id: int, amount: int) -> int:
    with SessionLocal() as s:
        row = s.query(User).filter(User.telegram_id == str(telegram_id)).first()
        if not row:
            return 0
        row.token_balance = (row.token_balance or 0) + amount
        new = int(row.token_balance)
        s.commit()
        return new


def consume_constructor_credit(telegram_id: int) -> bool:
    with SessionLocal() as s:
        row = s.query(User).filter(User.telegram_id == str(telegram_id)).first()
        if not row or (row.constructor_credit or 0) < 1:
            return False
        row.constructor_credit = (row.constructor_credit or 0) - 1
        s.commit()
        return True


def add_constructor_credit(telegram_id: int, amount: int = 1) -> None:
    with SessionLocal() as s:
        row = s.query(User).filter(User.telegram_id == str(telegram_id)).first()
        if not row:
            return
        row.constructor_credit = (row.constructor_credit or 0) + amount
        s.commit()


def _fk_pay_button(product: str, amount: int, text: str,
                   currency: str | None = None, pay_id: int | None = None):
    """V3.30.0: FreeKassa REST API order creation is a network call, so the
    keyboard carries a lightweight callback button; the ``fkapi:`` handler
    creates the order and sends back the ``location`` payment link."""
    data = f'fkapi:{product}:{currency or "RUB"}'
    if pay_id:
        data += f':{pay_id}'
    return InlineKeyboardButton(text=text, callback_data=data)


def premium_keyboard(discount: dict | None = None, telegram_id: int | None = None):
    if _any_video_engine():
        video_button = InlineKeyboardButton(text=f'🎬 Оживить фото — {VIDEO_COST_STARS}⭐{fiat_suffix(VIDEO_COST_STARS)}', callback_data='video:animate_last')
    else:
        video_button = InlineKeyboardButton(text='🔒 🎬 Оживить фото · скоро', callback_data='future:animate_photo')
    if discount and discount.get('active'):
        buy_label = f'⭐ Premium −{discount["percent"]}% — {discount["price"]} Stars (ещё {discount["hours_left"]:.0f} ч)'
    else:
        # V3.36.0: rub + dollars next to the Stars price — the rub is the real
        # card/SBP charge while FreeKassa is on, the dollars the Visa/MC price.
        month_fiat = fiat_suffix(PREMIUM_MONTHLY_STARS, rub=FREEKASSA_PREMIUM_PRICE_RUB, usd=FREEKASSA_PREMIUM_PRICE_USD, rub_enabled=FREEKASSA_ENABLED)
        buy_label = f'⭐ Premium — {PREMIUM_MONTHLY_STARS} Stars{month_fiat} / 30 дней'
    week_fiat = fiat_suffix(PREMIUM_WEEKLY_STARS, rub=FREEKASSA_PREMIUM_WEEKLY_PRICE_RUB, usd=PREMIUM_WEEKLY_PRICE_USD, rub_enabled=FREEKASSA_ENABLED)
    quarter_fiat = fiat_suffix(PREMIUM_QUARTERLY_STARS, rub=FREEKASSA_PREMIUM_QUARTERLY_PRICE_RUB, rub_enabled=FREEKASSA_ENABLED)
    rows = [
        [InlineKeyboardButton(text=buy_label, callback_data='buy:premium')],
        # V3.34.1: the short plan for the undecided — same invoice pipeline.
        [InlineKeyboardButton(text=f'⭐ Premium на неделю — {PREMIUM_WEEKLY_STARS} Stars{week_fiat}', callback_data='buy:premium_week')],
        # V3.43.0: the 3-month plan from the benchmarked card — best per-week price.
        [InlineKeyboardButton(text=f'⭐ Premium на 3 месяца — {PREMIUM_QUARTERLY_STARS} Stars{quarter_fiat}', callback_data='buy:premium_quarter')],
    ]
    if WALLET_PAY_ENABLED:
        rows.append([InlineKeyboardButton(text=f'💎 Premium — Wallet Pay (крипта/карта)', callback_data='walletpay:premium')])
    # V3.31.0: owner-configured external methods switched to «active» in the
    # admin panel must be visible to users here — a link opens its URL, a QR
    # method sends the saved photo + instructions via the paymethod: handler.
    for method in public_payment_methods():
        if method.method_type == 'link' and method.external_url:
            rows.append([InlineKeyboardButton(text=f'💳 {method.display_name}', url=method.external_url)])
        elif method.method_type == 'qr':
            rows.append([InlineKeyboardButton(text=f'💳 {method.display_name}', callback_data=f'paymethod:{method.id}')])
    if FREEKASSA_ENABLED and telegram_id:
        # V3.30.0: REST API orders — callback buttons; the fkapi: handler
        # creates the order and replies with the `location` payment link.
        # Payment-system badges stay on the labels; SBP gets its own row.
        # NOTE: i=44 "СБП (НСПК)" is API-only and does NOT open in a browser
        # form (FreeKassa shows "Данный метод работает только по API!"), so we
        # use i=42 "СБП" for the web-form link.
        # V3.31.1: each built-in row obeys its admin-managed 'builtin' switch
        # (Админка → Способы оплаты → статус) so the owner can remove any
        # button from the user menu without a deploy.
        if is_button_enabled('freekassa_rub'):
            rows.append([_fk_pay_button(
                'premium_month', FREEKASSA_PREMIUM_PRICE_RUB,
                f'💳 Premium — {FREEKASSA_PREMIUM_PRICE_RUB} ₽ · ⚡СБП / карта')])
            # V3.34.1: the weekly plan is payable by card/SBP too — the rub
            # price shown next to its Stars price is a real charge, not a display.
            rows.append([_fk_pay_button(
                'premium_week', FREEKASSA_PREMIUM_WEEKLY_PRICE_RUB,
                f'💳 Premium на неделю — {FREEKASSA_PREMIUM_WEEKLY_PRICE_RUB} ₽ · ⚡СБП / карта')])
            # V3.43.0: the 3-month plan is payable by card/SBP too.
            rows.append([_fk_pay_button(
                'premium_quarter', FREEKASSA_PREMIUM_QUARTERLY_PRICE_RUB,
                f'💳 Premium на 3 месяца — {FREEKASSA_PREMIUM_QUARTERLY_PRICE_RUB} ₽ · ⚡СБП / карта')])
        if is_button_enabled('freekassa_sbp'):
            rows.append([_fk_pay_button(
                'premium_month', FREEKASSA_PREMIUM_PRICE_RUB,
                f'⚡ Premium — {FREEKASSA_PREMIUM_PRICE_RUB} ₽ · SBP',
                pay_id=freekassa_service.FK_SBP_QR_PAYMENT_ID)])
        if is_button_enabled('freekassa_usd'):
            rows.append([_fk_pay_button(
                'premium_month', FREEKASSA_PREMIUM_PRICE_USD,
                f'💳 Premium — ${FREEKASSA_PREMIUM_PRICE_USD} · Ⓥ Visa / Ⓜ Mastercard',
                currency='USD')])
        if is_button_enabled('freekassa_tokens'):
            rows.append([
                _fk_pay_button('tokens_1', TOKEN_PRICE_RUB,
                               f'🪙 1 токен — {TOKEN_PRICE_RUB} ₽'),
                _fk_pay_button(f'tokens_{TOKEN_PACK_SIZE}',
                               TOKEN_PACK_SIZE * TOKEN_PRICE_RUB,
                               f'🪙 {TOKEN_PACK_SIZE} токенов — {TOKEN_PACK_SIZE * TOKEN_PRICE_RUB} ₽'),
            ])
    elif FREEKASSA_ENABLED:
        # Callers without telegram_id keep the legacy callback buttons.
        if is_button_enabled('freekassa_rub'):
            rows.append([InlineKeyboardButton(text=f'💳 Premium — {FREEKASSA_PREMIUM_PRICE_RUB} ₽ картой / СБП', callback_data='fk:premium')])
        if is_button_enabled('freekassa_usd'):
            rows.append([InlineKeyboardButton(text=f'💳 Premium — ${FREEKASSA_PREMIUM_PRICE_USD} · Visa/Mastercard', callback_data='fk:premium_usd')])
    rows.append([video_button])
    rows.append([InlineKeyboardButton(text='🎥 Кружочек от неё — только Premium', callback_data='video:circle')])
    rows.append([InlineKeyboardButton(text='🔒 📞 Звонок с персонажем · скоро', callback_data='future:anna_call')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def adult_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ Мне 18+', callback_data='age:yes')],
        [InlineKeyboardButton(text='↩️ Нет', callback_data='age:no')],
    ])


def photo_keyboard(telegram_id: int):
    level = get_relationship_level(telegram_id, get_user_character(telegram_id))
    lang = user_lang(telegram_id)
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
        rows.append([InlineKeyboardButton(text=f'✨ Кастомное фото — {CUSTOM_PHOTO_COST_STARS}⭐{fiat_suffix(CUSTOM_PHOTO_COST_STARS)}', callback_data='custom:start')])
        # V3.23.0: entry point to the paid spicy products (sets/gifts/fantasy).
        rows.append([InlineKeyboardButton(
            text='🔥 Приватное — горячие сеты' if lang == RU else '🔥 Private — hot sets',
            callback_data='spicy:menu',
        )])
    # V3.31.5: cosplay photoshoot — token-priced, available at EVERY level.
    if level >= SCENE_LEVELS.get('cosplay', 1):
        rows.append([InlineKeyboardButton(
            text=f'🎭 Косплей-фотосет — {COSPLAY_TOKEN_COST}🪙',
            callback_data='cosplay:start',
        )])
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
    lang = user_lang(telegram_id)
    from services.ui_lang import LEVEL_NAMES_EN
    names = LEVEL_NAMES_EN if lang == EN else RELATIONSHIP_LEVEL_NAMES
    name = names.get(level, '')
    future = sorted({required for required in SCENE_LEVELS.values() if required > level})
    if lang == EN:
        next_line = f'\n🔒 Next photos unlock at level {future[0]}/6' if future else '\n✨ All photo levels are already open'
        return (
            f'what should I show? 😌\n'
            f'❤️ Intimacy: {level}/6 · {name}\n'
            f'🎁 Free today: {info["free_left"]}/{info["limit"]} · credits: {info["credits"]}\n'
            f'📷 Progression pack: base → stylish → premium · up to {info["set_size"]} photos'
            f'{next_line}'
        )
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
        f"Кастомное фото · {_character_display_name(get_user_character(telegram_id))}",
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


async def _maybe_refund_paid_photo(chat_id: int, telegram_id: int, charge: str | None, amount: int, product: str) -> bool:
    """V3.23.0: paid spicy/gift/fantasy sets auto-refund Stars whenever the
    set cannot be delivered. Free/credit sets never carry a charge id."""
    if not charge:
        return False
    try:
        await bot.refund_star_payment(user_id=telegram_id, telegram_payment_charge_id=charge)
        record_refund(telegram_id, charge, amount, product=product)
        await bot.send_message(chat_id, 'не получилось сделать этот сет 😕 Stars вернул автоматически.')
    except Exception:
        logger.exception('spicy refund failed user=%s charge=%s', telegram_id, charge)
        await bot.send_message(chat_id, 'сет не получился 😕 напиши /support — проверим оплату и вернём Stars.')
    return True


async def _run_photo_background(chat_id: int, telegram_id: int, request: PhotoRequest, delivery_type: str, *, charge: str | None = None, amount: int = 0, product: str = 'photo'):
    uid = ensure_user(telegram_id)
    ping = asyncio.create_task(_photo_progress_ping(chat_id, telegram_id))
    try:
        track_event(uid, 'photo_generation_started', metadata={'scene': request.scene, 'delivery_type': delivery_type})
        character_id = get_user_character(telegram_id)
        if is_custom_character(character_id):
            # V3.31.8: constructor personas generate from their own avatar —
            # make sure the reference image is on disk before routing.
            try:
                await ensure_custom_avatar_cached(bot, character_id)
            except Exception:
                logger.exception('custom avatar cache failed user=%s character=%s', telegram_id, character_id)
        async with ChatActionSender.upload_photo(bot=bot, chat_id=chat_id):
            sent = await deliver_photo(bot, chat_id, telegram_id, request, delivery_type, character_id=character_id)
        track_event(uid, 'photo_job_completed', metadata={'scene': request.scene, 'count': len(sent), 'delivery_type': delivery_type})
        # V3.21.0: the couple album keeps one milestone photo per level.
        try:
            if sent:
                from services import couple_service
                latest = get_latest_photo_delivery(telegram_id)
                if latest:
                    couple_service.add_album_milestone(
                        uid, get_relationship_level(telegram_id, get_user_character(telegram_id)), latest['id'],
                    )
        except Exception:
            pass
        if len(sent) >= 2 and random.random() < 0.30:
            await bot.send_message(chat_id, 'кстати, такой стиль тебе заходит?', reply_markup=photo_feedback_keyboard(request.scene))
    except PermissionError as exc:
        logger.info('photo denied user=%s reason=%s', telegram_id, exc)
        track_event(uid, 'photo_failed', metadata={'scene': request.scene, 'reason': str(exc), 'provider': 'access'})
        if await _maybe_refund_paid_photo(chat_id, telegram_id, charge, amount, product):
            return
        await bot.send_message(chat_id, 'этот вариант сейчас недоступен 😌')
    except PhotoGenerationError as exc:
        logger.warning('photo generation failed provider=%s reason=%s user=%s scene=%s', exc.provider, exc.reason, telegram_id, request.scene)
        track_event(uid, 'photo_failed', metadata={'scene': request.scene, 'reason': exc.reason, 'provider': exc.provider})
        if await _maybe_refund_paid_photo(chat_id, telegram_id, charge, amount, product):
            return
        debug_hint = f' ({exc.provider}/{exc.reason})' if exc.reason else ''
        await bot.send_message(chat_id, f'фото сейчас не получилось 😕{debug_hint}\nлимит не списан. можно повторить.', reply_markup=photo_retry_keyboard(request.scene))
    except Exception as exc:
        logger.exception('photo generation failed user=%s', telegram_id)
        track_event(uid, 'photo_failed', metadata={'scene': request.scene, 'reason': type(exc).__name__, 'provider': 'unknown'})
        if await _maybe_refund_paid_photo(chat_id, telegram_id, charge, amount, product):
            return
        await bot.send_message(chat_id, 'фото сейчас не получилось 😕 лимит не списан. можно повторить.', reply_markup=photo_retry_keyboard(request.scene))
    finally:
        ping.cancel()
        _photo_jobs.pop(telegram_id, None)


async def _start_photo_background(chat_id: int, telegram_id: int, request: PhotoRequest, delivery_type: str, *, charge: str | None = None, amount: int = 0, product: str = 'photo'):
    active = _photo_jobs.get(telegram_id)
    if (active and not active.done()) or telegram_id in _photo_job_reservations:
        if await _maybe_refund_paid_photo(chat_id, telegram_id, charge, amount, product):
            return False
        await bot.send_message(chat_id, 'я уже делаю тебе один сет 😄 сначала закончу его')
        return False
    _photo_job_reservations.add(telegram_id)
    try:
        # Always check budget and show the generating message — AI generation
        # is the primary route now, library/community are fallbacks only.
        # V3.23.0: paid sets are budget-guarded too and auto-refund instead of
        # taking money during a provider outage.
        if delivery_type in {'free', 'story', 'paid'}:
            allowed, reason = budget_allows_photo()
            if not allowed:
                logger.error('image budget guard blocked generation reason=%s user=%s', reason, telegram_id)
                track_event(ensure_user(telegram_id), 'photo_budget_blocked', metadata={'scene': request.scene, 'reason': reason})
                if await _maybe_refund_paid_photo(chat_id, telegram_id, charge, amount, product):
                    return False
                await bot.send_message(chat_id, 'с фото сейчас техническая пауза 😕 попробуй чуть позже. лимит не списан.')
                return False
        await bot.send_message(chat_id, random.choice((
            'сек 😄 сейчас выберу нормальные кадры',
            'погоди чуть-чуть 😌 хочу сделать красиво',
            'сейчас 🙂 не хочу отправлять первый попавшийся кадр',
        )))
        task = _spawn_job('photo', telegram_id, _run_photo_background(chat_id, telegram_id, request, delivery_type, charge=charge, amount=amount, product=product), payload={'product': product or ''})
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
    await bot.send_message(chat_id, f'бесплатный лимит на сегодня использован. следующее фото — {PHOTO_COST_STARS}⭐{fiat_suffix(PHOTO_COST_STARS)} ✨')
    await send_stars_invoice(chat_id, f"Фото · {_character_display_name(get_user_character(telegram_id))}", f'Новый сет до 3 фото: {PHOTO_LABELS.get(request.scene, request.scene)}', f'photo:{offer_id}', PHOTO_COST_STARS)


@dp.message(CommandStart())
async def start(message: types.Message, command: CommandObject):
    name = message.from_user.first_name or message.from_user.username or 'ты'
    uid = ensure_user(message.from_user.id, name, language_code=message.from_user.language_code,
                      username=message.from_user.username)
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
        lang = user_lang(message.from_user.id)
        if lang == EN:
            welcome = (
                'What can this bot do?\n\n'
                'Roleplay with AI girls: live chats with memory, photos for your scenarios, AI video and voice.\n'
                'The relationship grows through levels 1–8 — closer and more open at every level.\n\n'
                '🎁 after confirming 18+ you get free photo credits for your first photo.\n'
                '⬇️ Let’s go! ⬇️\n\n'
            )
            if has_referral:
                welcome += 'you arrived via a friend’s invite — bonuses for both of you land right after you confirm.\n'
            welcome += 'Confirm you are 18+ and accept the terms of use and the privacy policy.'
        else:
            welcome = (
                'Что умеет этот бот?\n\n'
                'Ролевая игра с ИИ девушками: живые чаты с памятью, фото по твоим сценариям, AI-видео и голос.\n'
                'Отношения растут по уровням 1–8 — с каждым уровнем ближе и откровеннее.\n\n'
                '🎁 после подтверждения 18+ — бесплатные фото-кредиты на первое фото.\n'
                '⬇️ Поехали! ⬇️\n\n'
            )
            if has_referral:
                welcome += 'пришёл по приглашению друга — бонусы вам обоим начислятся сразу после подтверждения.\n'
            welcome += 'Подтверди, что тебе 18+, и прими условия использования и политику конфиденциальности.'
        banner = _welcome_banner_file()
        if banner is not None:
            await message.answer_photo(banner, caption=welcome, reply_markup=consent_keyboard(lang))
        else:
            await message.answer(welcome, reply_markup=consent_keyboard(lang))
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
    lang = user_lang(message.from_user.id)
    if lang == EN:
        welcome_back = (
            f'welcome back, {name} 🙂 the girls, chats, pictures and the shop live in the app 👇'
        )
    else:
        welcome_back = (
            f'с возвращением, {name} 🙂 девушки, чаты, картинки и магазин — в приложении 👇'
        )
    # V3.42.0: no character grid here anymore — a short button list instead.
    markup = InlineKeyboardMarkup(inline_keyboard=_welcome_back_rows(lang))
    banner = _welcome_banner_file()
    if banner is not None:
        await message.answer_photo(banner, caption=welcome_back, reply_markup=markup)
    else:
        await message.answer(welcome_back, reply_markup=markup)
    # V3.43.0: the referral dump is gone from the welcome screen entirely —
    # the invite link lives on the partner screen (/referral) now.


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
    lang = user_lang(cq.from_user.id)
    if lang == EN:
        bonus_line = (
            f'🎁 welcome! I gave you {first_start["credits"]} photo credits — '
            'try your first photo for free.\n'
            'All the heroines, chats, pictures and the shop live in the app 👇'
        ) if first_start['credits'] else 'Welcome 🙂 the heroines, chats and the shop live in the app 👇'
    else:
        bonus_line = (
            f'🎁 добро пожаловать! подарил тебе {first_start["credits"]} фото-кредитов — '
            'попробуй первое фото бесплатно.\n'
            'Все героини, чаты, картинки и магазин — в приложении 👇'
        ) if first_start['credits'] else 'Добро пожаловать 🙂 все героини, чаты и магазин — в приложении 👇'
    ref_line = ''
    if ref_link:
        if lang == EN:
            ref_line = (
                f'\n\n🔗 your invite link for friends:\n{ref_link}\n'
                f'for every friend who confirms 18+ you get {REFERRAL_REFERRER_CREDITS}, '
                f'and your friend gets {REFERRAL_INVITEE_CREDITS} photo credits.'
            )
        else:
            ref_line = (
                f'\n\n🔗 твоя ссылка для приглашения друзей:\n{ref_link}\n'
                f'за каждого друга, который подтвердит 18+, ты получишь {REFERRAL_REFERRER_CREDITS}, '
                f'а друг — {REFERRAL_INVITEE_CREDITS} фото-кредитов.'
            )
    # V3.41.0: character selection moved into the Mini App — no inline picker
    # here anymore; show the persistent main menu (reply keyboard) instead.
    await cq.message.answer(
        bonus_line + ref_line,
        reply_markup=main_keyboard(cq.from_user.id in ADMIN_TELEGRAM_IDS, cq.from_user.id),
    )
    # V3.31.3: every new user sees the optional «support the project» donation
    # link once, right after the welcome (owner request). Failures here must
    # never break onboarding, so it is guarded.
    try:
        await cq.message.answer(
            donation_service.donation_appeal(lang),
            reply_markup=donation_service.donation_keyboard(lang),
        )
    except Exception:
        logger.exception('donation welcome message failed user=%s', cq.from_user.id)


@dp.callback_query(F.data == 'consent:terms')
async def consent_terms(cq: types.CallbackQuery):
    await cq.answer()
    # V3.32.0: the full agreement document, not a one-line digest — the
    # payment partner's bank reviews these buttons straight from /start.
    await _send_legal_doc(cq.message.chat.id, legal_service.USER_AGREEMENT, user_lang(cq.from_user.id))

@dp.callback_query(F.data == 'consent:privacy')
async def consent_privacy(cq: types.CallbackQuery):
    await cq.answer()
    await _send_legal_doc(cq.message.chat.id, legal_service.PRIVACY_POLICY, user_lang(cq.from_user.id))


# V3.32.0: the always-available «Документы» menu (main keyboard row + /legal).
@dp.callback_query(F.data == 'legal:privacy')
async def legal_privacy(cq: types.CallbackQuery):
    await cq.answer()
    await _send_legal_doc(cq.message.chat.id, legal_service.PRIVACY_POLICY, user_lang(cq.from_user.id))


@dp.callback_query(F.data == 'legal:terms')
async def legal_terms(cq: types.CallbackQuery):
    await cq.answer()
    await _send_legal_doc(cq.message.chat.id, legal_service.USER_AGREEMENT, user_lang(cq.from_user.id))


@dp.callback_query(F.data == 'legal:tariffs')
async def legal_tariffs(cq: types.CallbackQuery):
    await cq.answer()
    await cq.message.answer(legal_service.tariffs_text(user_lang(cq.from_user.id)))


@dp.callback_query(F.data == 'legal:support')
async def legal_support(cq: types.CallbackQuery):
    await cq.answer()
    await cq.message.answer(legal_service.support_text(user_lang(cq.from_user.id)))


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
            reply_markup=premium_keyboard(telegram_id=cq.from_user.id),
        )
        return
    if card.status not in ('active', 'premium'):
        track_event(uid, 'fake_door_click', metadata={'feature': f'{character_id}_onboarding'})
        await _send_onboarding_character_card(cq.message.chat.id, character_id, cq.from_user.id)
        await cq.answer('эта девушка пока закрыта', show_alert=True)
        await cq.message.answer('Пока полностью доступна Анна 👇', reply_markup=onboarding_character_keyboard())
        return
    # Active or premium-unlocked character: allow selection
    set_user_character(cq.from_user.id, character_id)
    track_event(uid, 'character_selected', metadata={'character_id': character_id})
    await cq.answer(f'{card.display_name} выбрана')
    await _send_onboarding_character_card(cq.message.chat.id, character_id, cq.from_user.id)
    sel_lang = user_lang(cq.from_user.id)
    # V3.41.0: the owner asked to drop the «✨ Что умеет бот» text wall after
    # picking a heroine — the character card + the main menu are enough, and the
    # features now live as buttons in the app chat instead of a wall of text.
    menu_line = 'The main menu is always at the bottom 👇' if sel_lang == EN else 'Основное меню всегда внизу 👇'
    await cq.message.answer(menu_line, reply_markup=main_keyboard(cq.from_user.id in ADMIN_TELEGRAM_IDS, cq.from_user.id))
    # V3.21.0: one-time tour so nothing hides in sub-menus.
    try:
        user = get_user(cq.from_user.id)
        if user and not user.tour_done:
            update_user_settings(cq.from_user.id, tour_done=True)
            tour_lang = user_lang(cq.from_user.id)
            tour_text = (
                'a quick tour of the buttons 👇\n\n'
                '💬 just write to her — the relationship grows with every message\n'
                '📸 Photos — ask for a shot in any situation\n'
                '🎬 Video and 🎥 Video circle — animate a photo or get a circle with her voice\n'
                '🎯 Daily quest — her small request (+5 attention for completing it)\n'
                '💕 Date and 🏠 Apartment — time together, new places open with the levels\n'
                '👤 Profile — your intimacy level in hearts and progress\n'
                '🚀 Premium — unlimited chatting, video circles and levels 7–8'
            ) if tour_lang == EN else (
                'быстрый тур по кнопкам 👇\n\n'
                '💬 просто пиши ей — отношения растут с каждым сообщением\n'
                '📸 Фото — попроси кадр в любой ситуации\n'
                '🎬 Видео и 🎥 Кружочек — оживи фото или получи видео-кружочек с её голосом\n'
                '🎯 Задание дня — её маленькая просьба (+5 внимания за выполнение)\n'
                '💕 Свидание и 🏠 Квартира — время вместе, новые места открываются с уровнями\n'
                '👤 Профиль — твой уровень близости в сердечках и прогресс\n'
                '🚀 Премиум — безлимит, кружочки и уровни 7–8'
            )
            await cq.message.answer(tour_text)
            track_event(uid, 'onboarding_tour_sent')
    except Exception:
        pass


@dp.callback_query(F.data == 'onboard:meet')
async def onboarding_meet(cq: types.CallbackQuery):
    uid = ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    track_event(uid, 'onboarding_meet')
    await cq.answer()
    if user_lang(cq.from_user.id) == EN:
        await cq.message.answer('then no questionnaire 😄 what should I call you — and what should I know about you first?')
    else:
        await cq.message.answer('тогда без анкеты 😄 как тебя лучше называть — и что мне про тебя стоит знать первым?')


@dp.callback_query(F.data == 'onboard:abilities')
async def onboarding_abilities(cq: types.CallbackQuery):
    uid = ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    track_event(uid, 'onboarding_abilities')
    await cq.answer()
    lang = user_lang(cq.from_user.id)
    await cq.message.answer(abilities_text(lang), reply_markup=abilities_inline_keyboard(lang))


@dp.message(Command('features', 'abilities'))
async def features_cmd(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    lang = user_lang(message.from_user.id)
    await message.answer(abilities_text(lang), reply_markup=abilities_inline_keyboard(lang))


@dp.message(F.text.in_(kb_pair('features')))
async def features_button(message: types.Message):
    await features_cmd(message)


@dp.message(F.text.in_(kb_pair('characters')))
async def characters_button(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    await message.answer('выбери персонажа 👇', reply_markup=characters_keyboard(telegram_id=message.from_user.id))


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
        set_user_character(cq.from_user.id, character_id)
        track_event(uid, 'character_selected', metadata={'character_id': character_id})
        await cq.message.answer(
            f'✅ {card.display_name} выбрана. Можешь писать ей! 👇',
            reply_markup=main_keyboard(cq.from_user.id in ADMIN_TELEGRAM_IDS, cq.from_user.id),
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
            reply_markup=premium_keyboard(telegram_id=cq.from_user.id),
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
    _admin_grant_sessions.pop(message.from_user.id, None)
    CARD_MEDIA_WAIT.pop(message.from_user.id, None)
    ensure_default_cards()
    await message.answer('⚙️ Админка AnnaBot', reply_markup=admin_keyboard())


@dp.message(F.text.in_(kb_pair('admin')))
async def admin_panel_button(message: types.Message):
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    await admin_panel(message)


def _pool_view_payload(delivery_id: int):
    """V3.19.14: media + keyboard for one community-pool photo (owner view)."""
    row = admin_pool_get(delivery_id)
    if not row:
        return None
    caption = (
        f'🖼 Общая галерея · #{row["id"]} (в пуле: {admin_pool_count()})\n'
        f'сцена: {row["scene"]} · персонаж: {row["character_id"]}\n'
        f'провайдер: {row["provider"]} · {row["created_at"]:%d.%m.%Y %H:%M} UTC'
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='❌ Убрать из галереи', callback_data=f'poolmod:del:{row["id"]}')],
        [InlineKeyboardButton(text='⬅️ Новее', callback_data=f'poolmod:prev:{row["id"]}'),
         InlineKeyboardButton(text='➡️ Старше', callback_data=f'poolmod:next:{row["id"]}')],
        [InlineKeyboardButton(text='⬅️ Админка', callback_data='admin:home')],
    ])
    return types.InputMediaPhoto(media=row['telegram_file_id'], caption=caption), markup


@dp.callback_query(F.data.startswith('poolmod:'))
async def pool_moderation_cb(cq: types.CallbackQuery):
    """V3.19.14: owner browses the community pool newest-first and excludes
    bad frames; excluded photos stay with their original owner but are never
    served to other users."""
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        await cq.answer()
        return
    parts = cq.data.split(':')
    action = parts[1] if len(parts) > 1 else 'view'
    if action == 'del':
        target = int(parts[2])
        admin_pool_set_shared(target, False)
        try:
            track_event(ensure_user(cq.from_user.id), 'admin_pool_remove', metadata={'delivery_id': target})
        except Exception:
            pass
        await cq.answer('убрано из общей галереи ✅')
        cur = admin_pool_neighbor(target, 'next') or admin_pool_latest_id()
        if cur is None:
            try:
                await cq.message.edit_caption(caption='🖼 Общая галерея пуста')
            except Exception:
                await cq.message.answer('🖼 Общая галерея пуста')
            return
    elif action == 'next':
        cur = admin_pool_neighbor(int(parts[2]), 'next') or int(parts[2])
    elif action == 'prev':
        cur = admin_pool_neighbor(int(parts[2]), 'prev') or int(parts[2])
    else:
        cur = admin_pool_latest_id()
    if cur is None:
        await cq.answer('общая галерея пуста', show_alert=True)
        return
    payload = _pool_view_payload(cur)
    if payload is None:
        await cq.answer('фото недоступно', show_alert=True)
        return
    media, markup = payload
    try:
        # Same-message navigation: swap the photo in place.
        await cq.message.edit_media(media=media, reply_markup=markup)
    except Exception:
        # First open comes from a text message (admin keyboard) — send instead.
        await cq.message.answer_photo(media.media, caption=media.caption, reply_markup=markup)
    await cq.answer()


@dp.callback_query(F.data == 'admin:home')
async def admin_home(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    _character_card_edit_sessions.pop(cq.from_user.id, None)
    _payment_method_edit_sessions.pop(cq.from_user.id, None)
    _photo_idea_edit_sessions.pop(cq.from_user.id, None)
    _admin_grant_sessions.pop(cq.from_user.id, None)
    CARD_MEDIA_WAIT.pop(cq.from_user.id, None)
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


# V3.31.2: button alternative to the /grant command. The owner opens
# Админка → «🎁 Выдать премиум/токены», sends the recipient's @username or
# numeric id, then taps what to grant. Premium uses record_payment so the
# subscription + monthly photo credits match a real Stars payment exactly
# (grant_premium on top would double-grant both).
@dp.callback_query(F.data == 'admin:grant')
async def admin_grant_start(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    _admin_grant_sessions[cq.from_user.id] = {'step': 'target'}
    await cq.answer()
    await cq.message.answer(
        '🎁 Кому выдать?\n\n'
        'Пришли @username или числовой ID пользователя одним сообщением.\n'
        'Он должен хотя бы раз написать боту, чтобы я его нашла.\n\n'
        '/cancel — отменить'
    )


@dp.callback_query(F.data.startswith('admin:grantdo:premium:'))
async def admin_grant_do_premium(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    try:
        target = int(cq.data.rsplit(':', 1)[1])
    except ValueError:
        return
    _admin_grant_sessions.pop(cq.from_user.id, None)
    ensure_user(target)
    try:
        record_payment(target, 'premium_month', 0,
                       f'manual_grant:{cq.from_user.id}:{int(_time.time())}',
                       provider='manual', provider_payload=f'granted by {cq.from_user.id}')
    except Exception:
        logger.exception('manual grant record failed target=%s', target)
    try:
        await bot.send_message(target, '💖 Оплата прошла! Premium активирован на 30 дней. Наслаждайся! 🎉')
    except Exception:
        pass
    await cq.answer('выдано')
    await cq.message.answer(f'✅ Premium на 30 дней выдан пользователю id {target}.', reply_markup=admin_keyboard())


@dp.callback_query(F.data.startswith('admin:grantdo:tokens:'))
async def admin_grant_do_tokens_ask(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    try:
        target = int(cq.data.rsplit(':', 1)[1])
    except ValueError:
        return
    _admin_grant_sessions[cq.from_user.id] = {'step': 'tokens', 'target': target}
    await cq.answer()
    await cq.message.answer('Сколько токенов выдать? Пришли число, например 5.\n\n/cancel — отменить')


def _resolve_grant_target(ref: str) -> int | None:
    """V3.31.0: manual-grant target — a numeric Telegram id or a @username
    already seen in our users table (the Bot API cannot look users up)."""
    clean = (ref or '').strip().lstrip('@')
    if clean.isdigit():
        return int(clean)
    from services.user_service import find_user_by_username
    return find_user_by_username(clean)


@dp.message(Command('grant'))
async def admin_grant(message: types.Message, command: CommandObject):
    """V3.31.0: off-bot payment flow — the owner received money outside the
    bot (card transfer, cash, crypto…) and grants premium/tokens by
    @username or id. The user gets the same confirmation as after a payment."""
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    args = (command.args or '').split()
    if len(args) < 2:
        await message.answer(
            'формат:\n/grant @username premium — премиум на 30 дней\n'
            '/grant @username tokens 5 — начислить 5 токенов\n'
            '/grant 123456789 premium — то же самое по id'
        )
        return
    target = _resolve_grant_target(args[0])
    if not target:
        await message.answer(f'не нашла пользователя {args[0]} в базе — он должен хотя бы раз написать боту 🙂')
        return
    kind = args[1].lower()
    if kind == 'premium':
        # record_payment('premium_month') creates/extends the subscription and
        # adds the monthly photo credits exactly like a real Stars payment;
        # grant_premium on top of it would double-grant both.
        ensure_user(target)
        try:
            record_payment(target, 'premium_month', 0,
                           f'manual_grant:{message.from_user.id}:{int(_time.time())}',
                           provider='manual', provider_payload=f'granted by {message.from_user.id}')
        except Exception:
            logger.exception('manual grant record failed target=%s', target)
        try:
            await bot.send_message(target, '💖 Оплата прошла! Premium активирован на 30 дней. Наслаждайся! 🎉')
        except Exception:
            pass
        await message.answer(f'✅ premium на 30 дней выдан {args[0]} (id {target})')
    elif kind == 'tokens':
        count = int(args[2]) if len(args) > 2 and args[2].isdigit() else 0
        if count < 1:
            await message.answer('укажи количество: /grant @username tokens 5')
            return
        ensure_user(target)
        balance = add_tokens(target, count)
        try:
            record_payment(target, f'tokens_{count}', 0,
                           f'manual_grant:{message.from_user.id}:{int(_time.time())}',
                           provider='manual', provider_payload=f'granted by {message.from_user.id}')
        except Exception:
            logger.exception('manual grant record failed target=%s', target)
        try:
            await bot.send_message(target, f'🪙 Токены зачислены! Баланс: {balance} 🪙')
        except Exception:
            pass
        await message.answer(f'✅ {count} токенов выдано {args[0]} (id {target}), баланс {balance}')
    else:
        await message.answer('не знаю такой вид выдачи: premium | tokens')


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


# V3.43.3: the owner swaps a storefront card right from the admin chat —
# photo, GIF or video, no deploy: the grid URL carries the ?v= stamp and the
# override folder re-stamps it the moment the file lands on disk.
@dp.callback_query(F.data.startswith('admin:cardmedia:'))
async def admin_card_media_wait(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    character_id = cq.data.split(':', 2)[2]
    CARD_MEDIA_WAIT[cq.from_user.id] = character_id
    await cq.answer()
    await cq.message.answer(
        f'📥 Пришли фото, GIF или видео (до 20 MB) для карточки {character_id}.\n\n'
        'Фото встанет статичной карточкой; GIF, анимированный стикер и видео '
        'витрина будет крутить по кругу.\n\n/cancel — отменить')


@dp.callback_query(F.data.startswith('admin:cardclear:'))
async def admin_card_media_clear(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    character_id = cq.data.split(':', 2)[2]
    removed = webapp_service.clear_card_override(character_id)
    await cq.answer('медиа убрано' if removed else 'медиа не было')
    await cq.message.answer(_admin_card_summary(character_id), reply_markup=admin_card_keyboard(character_id))


@dp.message(lambda m: m.from_user is not None and m.from_user.id in CARD_MEDIA_WAIT,
            F.photo | F.video | F.animation | F.document)
async def admin_card_media_upload(message: types.Message):
    """V3.43.3: the media the admin sent becomes the storefront card."""
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    character_id = CARD_MEDIA_WAIT.get(message.from_user.id)
    if not character_id:
        return
    file_id, ext = None, None
    if message.photo:
        file_id, ext = message.photo[-1].file_id, '.jpg'
    elif message.animation:
        mime = (message.animation.mime_type or '').lower()
        file_id, ext = message.animation.file_id, ('.gif' if mime == 'image/gif' else '.mp4')
    elif message.video:
        file_id, ext = message.video.file_id, '.mp4'
    elif message.document:
        mime = (message.document.mime_type or '').lower()
        name = (message.document.file_name or '').lower()
        if mime == 'image/gif' or name.endswith('.gif'):
            ext = '.gif'
        elif mime == 'image/webp' or name.endswith('.webp'):
            ext = '.webp'
        elif mime == 'image/png' or name.endswith('.png'):
            ext = '.png'
        elif mime.startswith('video/') or name.endswith('.mp4'):
            ext = '.mp4'
        elif mime in ('image/jpeg', 'image/jpg') or name.endswith(('.jpg', '.jpeg')):
            ext = '.jpg'
        file_id = message.document.file_id
    if not file_id:
        await message.answer('не поняла формат — пришли фото, GIF, WebP или MP4.')
        return
    size = (message.photo[-1].file_size if message.photo
            else (message.animation or message.video or message.document).file_size) or 0
    if size > 20 * 1024 * 1024:
        await message.answer('файл тяжелее 20 MB — Telegram не даст мне его скачать. Пришли полегче.')
        return
    buf = io.BytesIO()
    await bot.download(file_id, destination=buf)
    webapp_service.set_card_override(character_id, buf.getvalue(), ext)
    CARD_MEDIA_WAIT.pop(message.from_user.id, None)
    kind = {'.jpg': 'фото', '.png': 'фото', '.webp': 'анимированный стикер',
            '.gif': 'GIF', '.mp4': 'видео-петля'}[ext]
    await message.answer(
        f'✅ Карточка {character_id}: в витрине теперь {kind}. '
        'Открой приложение заново — ссылка уже с новой версией.',
        reply_markup=admin_card_keyboard(character_id))


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
    # V3.40.0: the owner asked for a real user-statistics screen — signups,
    # paying users, message volume, media mix, studio health and the character
    # leaderboard. Studio success rate comes from the per-provider counters.
    photo_ok = photo_fail = 0
    for row in provider_snapshot():
        if row['provider'].startswith('photo/'):
            photo_ok += row['ok']
            photo_fail += row['fail']
    studio_total = photo_ok + photo_fail
    studio_rate = (photo_ok / studio_total * 100.0) if studio_total else 0.0
    top_lines = '\n'.join(
        f'· {_character_display_name(cid)} — {cnt} сооб.' for cid, cnt in snap['top_characters']
    ) or '· пока пусто'
    await cq.message.answer(
        '📊 Статистика пользователей\n\n'
        f'👥 всего: {snap["users_total"]} · новых за 24ч: {snap["new_24h"]} · за 7д: {snap["new_7d"]}\n'
        f'🟢 активны: за 24ч {snap["users_24h"]} · за 7д {snap["users_7d"]}\n'
        f'⭐ Premium активен: {snap["premium_active"]}\n'
        f'💬 сообщения пользователей: за 24ч {snap["messages_24h"]} · за 7д {snap["messages_7d"]}\n'
        f'📸 медиа за 24ч: фото {snap["photos_24h"]} · кружки {snap["circles_24h"]} · видео {snap["videos_24h"]}\n'
        f'🎨 студия: ✅{photo_ok} ❌{photo_fail} (успешность {studio_rate:.0f}%)\n'
        f'🔁 удержание: D1 {snap["d1_retention"]:.0f}% · D7 {snap["d7_retention"]:.0f}%\n'
        f'💰 Stars за 30д: {snap["stars_30d"]} · себестоимость фото за 24ч: ${snap["photo_cost_24h"]:.2f}\n\n'
        f'🏆 топ персонажей (7д):\n{top_lines}'
    )


@dp.callback_query(F.data == 'admin:providers')
async def admin_providers_button(cq: types.CallbackQuery):
    """V3.40.0: per-engine ok/fail counters — which leg of the media chains is
    flaky, with the last error per provider, in one tap instead of in logs."""
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    await cq.answer()
    rows = provider_snapshot()
    if not rows:
        lines = ' счётчики пока пустые — ни одной генерации ещё не было.'
    else:
        lines = '\n'.join(
            f'{r["provider"]}: ✅{r["ok"]} ❌{r["fail"]}'
            + (f'\n   посл: {r["last_error"]}' if r['last_error'] else '')
            for r in rows
        )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='⬅️ Админка', callback_data='admin:home')],
    ])
    await cq.message.answer(f'🩺 Отказы провайдеров\n\n{lines}', reply_markup=markup)


@dp.message(Command('cancel'))
async def cancel_admin_edit(message: types.Message):
    if message.from_user.id in CARD_MEDIA_WAIT:
        character_id = CARD_MEDIA_WAIT.pop(message.from_user.id)
        await message.answer('отменено', reply_markup=admin_card_keyboard(character_id))
        return
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
    if message.from_user.id in _admin_grant_sessions:
        _admin_grant_sessions.pop(message.from_user.id, None)
        await message.answer('выдача отменена', reply_markup=admin_keyboard())
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
    rituals_on = user.notify_rituals if user.notify_rituals is not None else True
    spicy_on = bool(getattr(user, 'spicy_mode', False)) and is_premium(message.from_user.id)
    lang = user_lang(message.from_user.id)
    if lang == EN:
        text = (
            f'Character settings\n\nTimezone: {user.timezone}\n'
            f'Chat language: {language} · adapts automatically\n'
            f'Voice replies: {"on" if user.voice_enabled else "off"}\n'
            f'Voice anon mode: {"on" if user.voice_anon_mode else "off"}\n'
            f'Proactive messages: {"on" if user.proactive_enabled else "off"}\n'
            f'Morning/evening rituals: {"on" if rituals_on else "off"}\n'
            f'Spicy mode (Premium): {"on 🔥" if spicy_on else "off"}\n'
            f'Premium: {"active" if is_premium(message.from_user.id) else "no"}\n'
            f'Photo credits: {credits}\n18+: {"confirmed" if is_adult_confirmed(message.from_user.id) else "not confirmed"}\n\n'
            'She picks up your communication style and familiar expressions on her own over time.\n'
            '/voice · /voice_anon · /notifications · /timezone'
        )
        button = '🔔 Rituals: disable' if rituals_on else '🔔 Rituals: enable'
        spicy_button = '🌶 Spicy mode: turn off' if spicy_on else '🌶 Spicy mode: turn on (Premium)'
    else:
        text = (
            f'Настройки персонажа\n\nЧасовой пояс: {user.timezone}\n'
            f'Язык общения: {language} · адаптируется автоматически\n'
            f'Голосовые ответы: {"вкл" if user.voice_enabled else "выкл"}\n'
            f'Голосовой аноним-режим: {"вкл" if user.voice_anon_mode else "выкл"}\n'
            f'Инициативные сообщения: {"вкл" if user.proactive_enabled else "выкл"}\n'
            f'Утренние/вечерние ритуалы: {"вкл" if rituals_on else "выкл"}\n'
            f'Пошлый режим (Premium): {"вкл 🔥" if spicy_on else "выкл"}\n'
            f'Premium: {"активен" if is_premium(message.from_user.id) else "нет"}\n'
            f'Фото-кредиты: {credits}\n18+: {"подтверждено" if is_adult_confirmed(message.from_user.id) else "не подтверждено"}\n\n'
            'Стиль общения и знакомые выражения персонаж постепенно подхватывает сам.\n'
            '/voice · /voice_anon · /notifications · /timezone'
        )
        button = '🔔 Ритуалы: выключить' if rituals_on else '🔔 Ритуалы: включить'
        spicy_button = '🌶 Пошлый режим: выключить' if spicy_on else '🌶 Пошлый режим: включить (Premium)'
    rows = [
        [InlineKeyboardButton(text=button, callback_data='toggle:rituals')],
        # V3.37.0: the premium-gated spicy-mode switch (see toggle:spicy).
        [InlineKeyboardButton(text=spicy_button, callback_data='toggle:spicy')],
        # V3.31.4: real one-tap URL button to support the project (CloudTips).
        [donation_service.donation_button(lang)],
    ]
    # V3.33.1: always-available Mini App launcher (same app as /app).
    if PUBLIC_BASE_URL:
        app_label = '🛍 App' if lang == EN else '🛍 Приложение'
        rows.append([InlineKeyboardButton(text=app_label, web_app=types.WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp'))])
    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@dp.message(Command('profile'))
async def profile_cmd(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    from services.gamification_service import get_profile_summary, format_profile_summary
    summary = get_profile_summary(message.from_user.id, get_user_character(message.from_user.id))
    await message.answer(format_profile_summary(summary))


@dp.message(Command('referral', 'invite', 'partner'))
async def referral_cmd(message: types.Message):
    """V3.37.0: the partner screen — stats, personal link, withdrawal, FAQ.

    The «💰 Партнёрка» button lands here: invited count + earned rubles + the
    live balance, one tap to copy the link, one tap to request a payout.
    """
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    from services import partner_service
    from config import PARTNER_MIN_PAYOUT_RUB, PARTNER_PAYOUT_METHODS, REFERRAL_COMMISSION_PCT
    user = get_user(message.from_user.id)
    stats = partner_service.partner_stats(user.id) if user else {'invited': 0, 'earned_rub': 0.0, 'balance_rub': 0.0, 'pending_payout_id': None}
    try:
        me = await bot.get_me()
        link = referral_link(me.username or 'bot', message.from_user.id)
    except Exception:
        await message.answer('не удалось получить ссылку прямо сейчас, попробуй позже.')
        return
    lang = user_lang(message.from_user.id)
    pct = int(REFERRAL_COMMISSION_PCT) if float(REFERRAL_COMMISSION_PCT).is_integer() else REFERRAL_COMMISSION_PCT
    if lang == EN:
        text = (
            f'💰 AnnaBot Partner program\n\n'
            f'Invite friends and earn {pct}% of EVERY purchase they make — forever, not just once.\n\n'
            f'👥 friends invited: {stats["invited"]}\n'
            f'💵 total earned: {stats["earned_rub"]:g} ₽\n'
            f'💳 available to withdraw: {stats["balance_rub"]:g} ₽\n\n'
            f'🔗 your link:\n{link}\n\n'
            f'A friend who opens it and starts the bot gets {REFERRAL_INVITEE_CREDITS} photo credits, you get {REFERRAL_REFERRER_CREDITS}. '
            f'And afterwards your {pct}% lands with every purchase they make.\n'
            f'Minimum payout — {PARTNER_MIN_PAYOUT_RUB} ₽.'
        )
        withdraw_label = f'💸 Withdraw {stats["balance_rub"]:g} ₽'
    else:
        text = (
            f'💰 Партнёрка AnnaBot\n\n'
            f'Приглашай друзей и получай {pct}% с КАЖДОЙ их покупки — навсегда, а не один раз.\n\n'
            f'👥 приведено друзей: {stats["invited"]}\n'
            f'💵 заработано всего: {stats["earned_rub"]:g} ₽\n'
            f'💳 доступно к выводу: {stats["balance_rub"]:g} ₽\n\n'
            f'🔗 твоя ссылка:\n{link}\n\n'
            f'друг, который перейдёт по ней и впервые запустит бота, получит {REFERRAL_INVITEE_CREDITS} фото-кредита, а ты — {REFERRAL_REFERRER_CREDITS}. '
            f'а дальше твои {pct}% капают с каждой его покупки.\n'
            f'минимум для вывода — {PARTNER_MIN_PAYOUT_RUB} ₽.'
        )
        withdraw_label = f'💸 Вывести {stats["balance_rub"]:g} ₽'
    rows = [
        [InlineKeyboardButton(text=withdraw_label, callback_data='partner:withdraw')],
        [InlineKeyboardButton(text='❓ ' + ('What is it?' if lang == EN else 'Что это такое?'), callback_data='partner:faq:0')],
        [InlineKeyboardButton(text='❓ ' + ('How does it work?' if lang == EN else 'Как это работает?'), callback_data='partner:faq:1')],
        [InlineKeyboardButton(text='❓ ' + ('How do I get paid?' if lang == EN else 'Как мне вывести деньги?'), callback_data='partner:faq:2')],
        [InlineKeyboardButton(text='❓ ' + ('Is the payout one-time?' if lang == EN else 'Выплата разовая?'), callback_data='partner:faq:3')],
        [InlineKeyboardButton(text='❓ ' + ('More questions' if lang == EN else 'У меня остались вопросы'), callback_data='partner:faq:4')],
    ]
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), disable_web_page_preview=True)


# V3.37.0: partner FAQ copy — question buttons above, answers delivered as
# short follow-up messages (inline alerts cap at 200 chars, too small).
_PARTNER_FAQ_RU = [
    'Партнёрская программа: ты получаешь {pct}% от всех покупок приглашённых тобой друзей. Это бессрочная программа — комиссия капает с каждой их покупки навсегда.',
    '1. Поделись своей ссылкой из экрана «💰 Партнёрка». 2. Друг переходит, запускает бота и что-то покупает. 3. Тебе автоматически капает {pct}% от каждой его покупки — с премиума, фото, видео, всего.',
    'Набери {min} ₽ и нажми «💸 Вывести». Выплата — на {methods}. Владелец подтверждает вручную, обычно в течение суток.',
    'Нет! Это не разовая выплата, а постоянный пассивный доход: {pct}% с каждой покупки твоих рефералов капают всегда.',
    'Напиши /support прямо в этом боте — сообщение попадёт владельцу, он ответит лично.',
]
_PARTNER_FAQ_EN = [
    'The affiliate program: you earn {pct}% of every purchase your invited friends make. It runs forever — commission lands with each of their purchases, permanently.',
    '1. Share your link from the «💰 Partner program» screen. 2. Your friend opens it, starts the bot and buys something. 3. You automatically get {pct}% of every purchase they make — premium, photos, video, everything.',
    'Reach {min} ₽ and tap «💸 Withdraw». Payouts go to {methods}. The owner confirms manually, usually within a day.',
    'No! This is not a one-time reward — it is a permanent passive income: {pct}% of every purchase your referrals make, forever.',
    'Write /support right here in the bot — the message reaches the owner and he replies personally.',
]


@dp.callback_query(F.data.startswith('partner:faq:'))
async def partner_faq(cq: types.CallbackQuery):
    from config import PARTNER_MIN_PAYOUT_RUB, PARTNER_PAYOUT_METHODS, REFERRAL_COMMISSION_PCT
    try:
        idx = int(cq.data.rsplit(':', 1)[1])
    except (ValueError, IndexError):
        await cq.answer('…')
        return
    lang = user_lang(cq.from_user.id)
    table = _PARTNER_FAQ_EN if lang == EN else _PARTNER_FAQ_RU
    if not 0 <= idx < len(table):
        await cq.answer('…')
        return
    pct = int(REFERRAL_COMMISSION_PCT) if float(REFERRAL_COMMISSION_PCT).is_integer() else REFERRAL_COMMISSION_PCT
    await cq.answer('💌')
    await cq.message.answer(table[idx].format(pct=pct, min=PARTNER_MIN_PAYOUT_RUB, methods=PARTNER_PAYOUT_METHODS))


@dp.callback_query(F.data == 'partner:open')
async def partner_open(cq: types.CallbackQuery):
    """V3.39.0: the «💰 Партнёрка» CTA on the welcome photo — same partner screen."""
    await cq.answer()
    await referral_cmd(cq.message)


@dp.callback_query(F.data == 'credits:open')
async def credits_open(cq: types.CallbackQuery):
    """V3.42.1: the «🍑 Пополнить персики» CTA on the welcome screen — same
    app-shop entry as the reply-keyboard credits button (peaches are bought in
    the Mini App «Магазин» tab)."""
    await cq.answer()
    await _send_app_entry(
        cq.message,
        '🍑 персики (фото-кредиты) покупаются в приложении — вкладка «Магазин» 👇',
        '🍑 peaches (photo credits) are bought in the app — the «Shop» tab 👇',
    )


# V3.43.0: the welcome «👥 Поддержка» row is a plain url button to the
# dedicated support bot, so the old 'support:open' ticket callback is gone.


@dp.callback_query(F.data == 'partner:withdraw')
async def partner_withdraw(cq: types.CallbackQuery):
    """V3.37.0: create a pending payout when the balance allows it."""
    from services import partner_service
    from config import PARTNER_MIN_PAYOUT_RUB
    result = partner_service.request_payout(cq.from_user.id)
    lang = user_lang(cq.from_user.id)
    if not result.get('ok'):
        reason = result.get('reason')
        if reason == 'below_min':
            await cq.answer(
                (f'до вывода не хватает: на балансе {result.get("balance_rub", 0):g} ₽, минимум — {PARTNER_MIN_PAYOUT_RUB} ₽.'
                 if lang != EN else
                 f'not there yet: balance is {result.get("balance_rub", 0):g} ₽, minimum — {PARTNER_MIN_PAYOUT_RUB} ₽.'),
                show_alert=True,
            )
        elif reason == 'pending_exists':
            await cq.answer('заявка уже на рассмотрении 💌' if lang != EN else 'a payout request is already pending 💌', show_alert=True)
        else:
            await cq.answer('не получилось, попробуй позже' if lang != EN else 'failed, try again later', show_alert=True)
        return
    await cq.answer('заявка создана ✅')
    await cq.message.answer(
        f'💸 заявка на вывод {result["amount_rub"]:g} ₽ создана. владелец подтвердит и переведёт вручную — обычно в течение суток.'
        if lang != EN else
        f'💸 payout request for {result["amount_rub"]:g} ₽ created. The owner confirms and sends it manually — usually within a day.'
    )
    # The owner pays by hand — ping every admin with confirm/reject buttons.
    for admin_id in ADMIN_TELEGRAM_IDS:
        try:
            await bot.send_message(
                admin_id,
                f'💸 Заявка на вывод партнёрских\nuser: {cq.from_user.id}\nname: {cq.from_user.first_name or "—"}\namount: {result["amount_rub"]:g} ₽\npayout_id: {result["payout_id"]}',
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text='✅ Выплачено', callback_data=f'payout:done:{result["payout_id"]}'),
                    InlineKeyboardButton(text='❌ Отклонить', callback_data=f'payout:cancel:{result["payout_id"]}'),
                ]]),
            )
        except Exception:
            logger.exception('payout admin notify failed admin=%s', admin_id)


@dp.callback_query(F.data.startswith('payout:done:'))
async def payout_done(cq: types.CallbackQuery):
    """V3.37.0: owner marks a partner payout as sent."""
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        await cq.answer('только для владельца')
        return
    from services import partner_service
    try:
        payout_id = int(cq.data.rsplit(':', 1)[1])
    except (ValueError, IndexError):
        await cq.answer('bad id')
        return
    payout = partner_service.settle_payout(payout_id, 'paid')
    if not payout:
        await cq.answer('уже обработана')
        return
    await cq.answer('выплачено ✅')
    try:
        await bot.send_message(
            payout['telegram_id'],
            f'💸 выплата {payout["amount_rub"]:g} ₽ отправлена! проверь реквизиты. спасибо, что приводишь друзей 💜',
        )
    except Exception:
        logger.exception('payout user notify failed tgid=%s', payout['telegram_id'])


@dp.callback_query(F.data.startswith('payout:cancel:'))
async def payout_cancel(cq: types.CallbackQuery):
    """V3.37.0: owner rejects a payout — the balance refunds automatically."""
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        await cq.answer('только для владельца')
        return
    from services import partner_service
    try:
        payout_id = int(cq.data.rsplit(':', 1)[1])
    except (ValueError, IndexError):
        await cq.answer('bad id')
        return
    payout = partner_service.settle_payout(payout_id, 'cancelled')
    if not payout:
        await cq.answer('уже обработана')
        return
    await cq.answer('отклонено')
    try:
        await bot.send_message(
            payout['telegram_id'],
            f'заявка на вывод {payout["amount_rub"]:g} ₽ отклонена — деньги остались на балансе партнёрки. напиши /support, если вопрос.',
        )
    except Exception:
        logger.exception('payout cancel notify failed tgid=%s', payout['telegram_id'])


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
    # V3.32.0: full agreement document (payment-partner bank requirement).
    await _send_legal_doc(message.chat.id, legal_service.USER_AGREEMENT, user_lang(message.from_user.id))

@dp.message(Command('privacy'))
async def privacy_cmd(message: types.Message):
    await _send_legal_doc(message.chat.id, legal_service.PRIVACY_POLICY, user_lang(message.from_user.id))

@dp.message(Command('legal'))
async def legal_cmd(message: types.Message):
    # V3.32.0: documents & prices menu — same screen as the «Документы» button.
    lang = user_lang(message.from_user.id)
    await message.answer(legal_service.legal_menu_text(lang), reply_markup=legal_keyboard(lang))

@dp.message(Command('app'))
async def app_cmd(message: types.Message):
    # V3.33.1: guaranteed Mini App entry point. The profile «Открыть
    # приложение» button depends on Telegram client caching and the
    # BotFather main-mini-app state; an inline web_app button always opens
    # the app right here, whatever those do.
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    lang = user_lang(message.from_user.id)
    if not PUBLIC_BASE_URL:
        hint = ('the app is not connected on the server yet — the owner needs to set PUBLIC_BASE_URL (the Railway domain).' if lang == EN else
                'приложение ещё не подключено на сервере — нужно задать PUBLIC_BASE_URL (домен Railway).')
        await message.answer('🛍 ' + hint)
        return
    url = f'{PUBLIC_BASE_URL}/webapp'
    if lang == EN:
        await message.answer(
            '🛍 AnnaBot app — characters, shop and your profile:',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text='🛍 Open App', web_app=types.WebAppInfo(url=url))],
            ]),
        )
        return
    await message.answer(
        '🛍 приложение AnnaBot — персонажи, магазин и твой профиль:',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='🛍 Открыть приложение', web_app=types.WebAppInfo(url=url))],
        ]),
    )

@dp.message(Command('setmenubutton'))
async def set_menu_button_cmd(message: types.Message):
    """Admin command to force-install the Mini App menu button in the bot profile."""
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    if not PUBLIC_BASE_URL:
        await message.answer(' PUBLIC_BASE_URL не задан — кнопка не может быть установлена.')
        return
    menu_url = f'{PUBLIC_BASE_URL}/webapp'
    try:
        await bot.set_chat_menu_button(menu_button=types.MenuButtonWebApp(
            text='Открыть приложение',
            web_app=types.WebAppInfo(url=menu_url),
        ))
        current = await bot.get_chat_menu_button()
        await message.answer(
            f'✅ Кнопка «Открыть приложение» установлена!\n'
            f'URL: {menu_url}\n'
            f'Текущий тип: {type(current).__name__} / текст: {getattr(current, "text", "")}'
        )
    except Exception as e:
        await message.answer(f'❌ Ошибка установки кнопки: {e}')

@dp.message(Command('support'))
async def support_cmd(message: types.Message):
    parts=(message.text or '').split(maxsplit=1)
    if len(parts)<2 or not parts[1].strip():
        await message.answer('Напиши: /support что произошло — сообщение уйдёт владельцу.')
        return
    delivered = await _deliver_support_message(message, parts[1])
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
            f'скачать их в полном разрешении за {GALLERY_DOWNLOAD_STARS}⭐{fiat_suffix(GALLERY_DOWNLOAD_STARS)} каждый.'
        )
        if edit:
            await edit.edit_text(text)
        else:
            await bot.send_message(chat_id, text)
        return

    header = (
        f'🖼 Твоя галерея · {total} фото · стр. {snap["page"] + 1}/{total_pages}\n\n'
        'Нажми на фото — открою его в полном размере с кнопками «Оживить» и «Скачать».\n'
        f'Платное скачивание: {GALLERY_DOWNLOAD_STARS}⭐{fiat_suffix(GALLERY_DOWNLOAD_STARS)} за кадр в полном разрешении (без Telegram-сжатия).'
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
                    text=f'⬇ Скачать {local_idx} · {GALLERY_DOWNLOAD_STARS}⭐{fiat_suffix(GALLERY_DOWNLOAD_STARS)}',
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
        types.InlineKeyboardButton(text=f'🎬 Оживить · {VIDEO_COST_STARS}⭐{fiat_suffix(VIDEO_COST_STARS)}', callback_data=f'gallery:animate:{delivery_id}'),
        types.InlineKeyboardButton(text=f'⬇ Скачать · {GALLERY_DOWNLOAD_STARS}⭐{fiat_suffix(GALLERY_DOWNLOAD_STARS)}', callback_data=f'gallery:dl:{delivery_id}'),
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
                record_provider(f'video/{engine_name}', True)
                break
            except Exception as exc:
                last_error = exc
                record_provider(f'video/{engine_name}', False, f'{type(exc).__name__}: {str(exc)[:120]}')
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
    _video_jobs[message.from_user.id] = _spawn_job(
        'video', message.from_user.id,
        _run_video_background(message.chat.id, message.from_user.id, delivery['id'], None),
        payload={'source': 'admin_test'},
    )
    await message.answer('тест видео запущен: прогоню всю цепочку движков с автофолбэком 🎬')


def _video_preset_keyboard(delivery_id: int):
    """V3.19.0: motion preset picker shown before every animation.

    V3.26.0: built generically from VIDEO_PRESETS so new/removed presets
    never require keyboard surgery here.
    """
    keys = list(VIDEO_PRESETS)
    rows = [
        [
            InlineKeyboardButton(text=VIDEO_PRESETS[key][0], callback_data=f'videopreset:{key}:{delivery_id}')
            for key in keys[i:i + 2]
        ]
        for i in range(0, len(keys), 2)
    ]
    rows.append([InlineKeyboardButton(text='✨ Авто', callback_data=f'videopreset:auto:{delivery_id}')])
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
        _video_jobs[cq.from_user.id] = _spawn_job(
            'video', cq.from_user.id,
            _run_video_background(cq.message.chat.id, cq.from_user.id, delivery['id'], None, motion_preset=motion_preset),
            payload={'preset': motion_preset or 'auto'},
        )
        return
    # V3.27.0: tokens (bought with rubles on FreeKassa) are an alternative to
    # Stars — spend them first so card-paying users animate without Stars.
    if spend_tokens(cq.from_user.id, VIDEO_TOKEN_COST):
        track_event(uid, 'tokens_spent', metadata={'amount': VIDEO_TOKEN_COST, 'delivery_id': delivery['id'], 'preset': motion_preset or 'auto'})
        await cq.message.answer(f'🪙 Списано {VIDEO_TOKEN_COST} токенов — оживляю фото! Баланс: {get_token_balance(cq.from_user.id)} 🪙')
        _video_jobs[cq.from_user.id] = _spawn_job(
            'video', cq.from_user.id,
            _run_video_background(cq.message.chat.id, cq.from_user.id, delivery['id'], None, motion_preset=motion_preset),
            payload={'preset': motion_preset or 'auto'},
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


# V3.20.0: Telegram video-note "circles" — a premium-exclusive format. She
# "records" a short selfie video from the user's latest photo and sends it as
# a round video note, like a real girlfriend would.
CIRCLE_PROMPT = (
    'Animate this exact photo into a short casual selfie video note: she smiles, '
    'tilts her head slightly, waves or blows a kiss as if recording a Telegram '
    'circle message. She says one short phrase in a soft, cute, natural female '
    'voice, in Russian: "{phrase}". Natural handheld camera feel, direct eye '
    'contact. Keep her face, hair and outfit identical. No wardrobe change, no '
    'extra people. Photorealistic.'
)
# V3.20.1: circles are spoken — Veo renders her voice natively (the same cute
# voice heard in Gemini-generated videos); silent fallback engines just ignore it.
CIRCLE_PHRASES = (
    'привет, это я 😘 скучал по мне?',
    'держи мой кружочек 💋 думай обо мне',
    'смотри, как я тебе улыбаюсь…',
)


@dp.callback_query(F.data == 'video:circle')
async def circle_cb(cq: types.CallbackQuery):
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True); return
    uid = ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if not _any_video_engine():
        await cq.answer(_video_unavailable_text(cq.from_user.id), show_alert=True); return
    # Premium-exclusive: free users see the paywall, never the product.
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS and not is_premium(cq.from_user.id):
        track_event(uid, 'circle_paywall_view')
        from services.retention_service import discount_info
        await cq.answer('кружочки — эксклюзив для Premium 😏', show_alert=True)
        await cq.message.answer(
            '🎥 кружочки — мой закрытый формат: короткие видео, как будто записываю их тебе лично 😌\n'
            'доступны только с Premium.',
            reply_markup=premium_keyboard(discount_info(cq.from_user.id), telegram_id=cq.from_user.id),
        )
        return
    if cq.from_user.id in _video_jobs and not _video_jobs[cq.from_user.id].done():
        await cq.answer('Одно видео уже создаётся 🎬', show_alert=True); return
    delivery = get_latest_photo_delivery(cq.from_user.id)
    if not delivery or not delivery.get('telegram_file_id'):
        await cq.answer('Сначала попроси у меня фото — кружочек сниму с последнего кадра.', show_alert=True); return
    await cq.answer()
    # Circles share the premium free animation slots; after they are spent an
    # extra circle is paid like an animation.
    if cq.from_user.id in ADMIN_TELEGRAM_IDS or consume_premium_video_free(cq.from_user.id):
        track_event(uid, 'video_free_used', metadata={'kind': 'circle', 'delivery_id': delivery['id']})
        _video_jobs[cq.from_user.id] = _spawn_job(
            'circle', cq.from_user.id,
            _run_circle_background(cq.message.chat.id, cq.from_user.id, delivery['id'], None),
        )
        return
    await send_stars_invoice(
        cq.message.chat.id, 'Кружочек от Анны',
        'Короткий видео-кружочек из последнего фото (бесплатные на сегодня закончились).',
        'circle', VIDEO_COST_STARS,
    )


async def _run_circle_background(chat_id: int, telegram_id: int, delivery_id: int, charge_id: str | None):
    """V3.20.0: generate the circle through the same engine chain and deliver it
    as a Telegram video note; falls back to a normal video if the note format
    is rejected. Auto-refunds Stars when every engine fails."""
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
        await bot.send_message(chat_id, '🎥 записываю тебе кружочек… обычно это занимает 1–3 минуты')
        video_bytes = None
        used_engine = None
        last_error = None
        for idx, (engine_name, engine_fn) in enumerate(engines):
            try:
                if idx > 0:
                    await bot.send_message(chat_id, 'секунду, пробую ещё один способ записать кружочек 🎥')
                video_bytes = await engine_fn(image_bytes, mime_type='image/jpeg', prompt=CIRCLE_PROMPT.format(phrase=random.choice(CIRCLE_PHRASES)))
                used_engine = engine_name
                record_provider(f'circle/{engine_name}', True)
                break
            except Exception as exc:
                last_error = exc
                record_provider(f'circle/{engine_name}', False, f'{type(exc).__name__}: {str(exc)[:120]}')
                engine_errors.append(f'{engine_name}: {type(exc).__name__}: {str(exc)[:160]}')
                logger.warning('circle engine %s failed user=%s delivery=%s error=%s: %s',
                               engine_name, telegram_id, delivery_id, type(exc).__name__, str(exc)[:300])
        if video_bytes is None:
            raise last_error or CloudVideoError('no_video_result')
        try:
            await bot.send_video_note(chat_id, BufferedInputFile(video_bytes, filename='circle.mp4'))
        except Exception:
            # Not every engine output survives the strict video-note format —
            # a normal video still delivers the moment.
            await bot.send_video(chat_id, BufferedInputFile(video_bytes, filename='circle.mp4'),
                                 caption='в кружок не поместилось 😅 держи так', supports_streaming=True)
        track_event(
            ensure_user(telegram_id), 'circle_delivered',
            metadata={'source_delivery_id': delivery_id, 'engine': used_engine, 'charge_id': charge_id or 'free'},
        )
    except Exception as exc:
        logger.exception('circle failed user=%s delivery=%s charge=%s error=%s', telegram_id, delivery_id, charge_id, type(exc).__name__)
        refunded = False
        if charge_id:
            try:
                await bot.refund_star_payment(user_id=telegram_id, telegram_payment_charge_id=charge_id)
                record_refund(telegram_id, charge_id, VIDEO_COST_STARS, product='video')
                refunded = True
            except Exception:
                logger.exception('Automatic circle Stars refund failed user=%s charge=%s', telegram_id, charge_id)
        await bot.send_message(chat_id, 'кружочек сейчас не получился 😕 ' + ('Stars автоматически вернул.' if refunded else 'попробуй чуть позже.'))
        track_event(
            ensure_user(telegram_id), 'video_failed',
            metadata={'source_delivery_id': delivery_id, 'error_type': type(exc).__name__, 'kind': 'circle', 'charge_id': charge_id or 'free', 'refunded': refunded},
        )
    finally:
        _video_jobs.pop(telegram_id, None)


# V3.43.1: the «живые плитки» motion script — close-up smile + air kiss are
# the reliable i2v motions (full-body movement turns into artifacts).
LIVE_TILE_PROMPT = (
    'Close-up portrait of the exact same woman from the source photo. '
    'She looks into the camera, smiles warmly and blows a playful air kiss '
    'toward the viewer, hand rising gently to her lips. Subtle natural motion '
    'only: soft smile, hair sway, no face or outfit changes, no camera cuts.'
)
# V3.43.2: backup motion for heroines the kiss script rejects (maria did):
# a slow head turn plus a soft smile reads just as "alive" without the hand.
LIVE_TILE_PROMPT_ALT = (
    'Close-up portrait of the exact same woman from the source photo. '
    'She slowly turns her head toward the camera and smiles softly, hair '
    'swaying gently in a light breeze. Subtle natural motion only: no face '
    'or outfit changes, no camera cuts, no hands in frame.'
)


async def _run_live_tiles(admin_id: int) -> None:
    """V3.43.1: render one i2v living tile per built-in heroine."""
    engines = []
    if video_available():
        engines.append(('gemini', animate_image))
    if replicate_available():
        engines.append(('replicate', animate_image_replicate))
    if fal_available():
        engines.append(('fal', animate_image_fal))
    if hf_video_available():
        engines.append(('hf', animate_image_hf))
    if not engines:
        await bot.send_message(admin_id, '🎬 Живые плитки: нет доступного видео-движка.')
        return
    for cid in webapp_service.builtin_character_ids():
        image_bytes = webapp_service.canonical_face_bytes(cid)
        if not image_bytes:
            await bot.send_message(admin_id, f'🎬 {cid}: нет канонического фото.')
            continue
        video_bytes = None
        # V3.43.2: a heroine the kiss motion rejects gets a second pass with
        # the simpler turn-and-smile script before we give up on her.
        for prompt in (LIVE_TILE_PROMPT, LIVE_TILE_PROMPT_ALT):
            for ename, efn in engines:
                try:
                    video_bytes = await efn(image_bytes, mime_type='image/jpeg', prompt=prompt)
                    record_provider(f'video/{ename}', True)
                    break
                except Exception as exc:
                    record_provider(f'video/{ename}', False, f'{type(exc).__name__}: {str(exc)[:120]}')
                    logger.warning('live tile engine %s failed char=%s: %s', ename, cid, exc)
            if video_bytes:
                break
        if not video_bytes:
            await bot.send_message(admin_id, f'🎬 {cid}: все движки отказали.')
            continue
        webapp_service.write_card_live(cid, video_bytes)
        await bot.send_message(admin_id, f'🎬 {cid}: живая плитка готова ({len(video_bytes) // 1024} KB).')
    await bot.send_message(admin_id, '🎬 Готово: витрина оживёт после обновления приложения.')


@dp.message(Command('livetiles'))
async def live_tiles_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    await message.answer('🎬 Отрисовываю живые плитки (улыбка + воздушный поцелуй) — статус по каждой героине пришлю сюда…')
    asyncio.create_task(_run_live_tiles(message.from_user.id))


@dp.message(Command('retiles'))
async def retiles_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    done = [cid for cid in webapp_service.builtin_character_ids() if webapp_service.rebuild_card_tile(cid)]
    await message.answer(f'🖼 Плитки-гифки пересобраны из текущих канонических фото: {len(done)}.')


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
    from services.retention_service import discount_info
    await message.answer(premium_pitch_text(message.from_user.id), reply_markup=premium_keyboard(discount_info(message.from_user.id), telegram_id=message.from_user.id))


@dp.callback_query(F.data == 'buy:premium')
async def buy_premium(cq: types.CallbackQuery):
    ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True); return
    await cq.answer()
    # V3.20.0: the one-time 24h discount window invoices a cheaper price.
    from services.retention_service import discount_info
    discount = discount_info(cq.from_user.id)
    if discount.get('active') and not is_premium(cq.from_user.id):
        track_event(ensure_user(cq.from_user.id), 'paywall_view', metadata={'product': 'premium_month_discount', 'stars': discount['price']})
        await send_stars_invoice(cq.message.chat.id, 'Anna Premium', f'Premium на 30 дней со скидкой −{discount["percent"]}%', 'premium_month_discount', discount['price'])
        return
    await send_stars_invoice(cq.message.chat.id, 'Anna Premium', 'Premium-доступ на 30 дней', 'premium_month', PREMIUM_MONTHLY_STARS)


@dp.callback_query(F.data == 'buy:premium_quarter')
async def buy_premium_quarter(cq: types.CallbackQuery):
    """V3.43.0: the 3-month plan from the benchmarked tariff card — 90 days."""
    ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if not has_accepted(cq.from_user.id):
        await cq.answer('сначала /start', show_alert=True)
        return
    await send_stars_invoice(cq.message.chat.id, 'Anna Premium', 'Premium-доступ на 90 дней', 'premium_quarter', PREMIUM_QUARTERLY_STARS)


@dp.callback_query(F.data == 'buy:premium_week')
async def buy_premium_week(cq: types.CallbackQuery):
    """V3.34.1: the weekly Premium option — 7 days for PREMIUM_WEEKLY_STARS."""
    ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True); return
    await cq.answer()
    await send_stars_invoice(cq.message.chat.id, 'Anna Premium', 'Premium-доступ на 7 дней', 'premium_week', PREMIUM_WEEKLY_STARS)


@dp.callback_query(F.data == 'retention:demo')
async def retention_demo_cb(cq: types.CallbackQuery):
    """V3.20.0: one-time free demo premium — the taste-before-loss hook."""
    uid = ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True); return
    from services.retention_service import grant_demo_premium
    if is_premium(cq.from_user.id):
        await cq.answer('премиум уже активен ✨', show_alert=True); return
    if grant_demo_premium(cq.from_user.id):
        track_event(uid, 'demo_premium_granted', metadata={'hours': DEMO_PREMIUM_HOURS})
        await cq.answer()
        await cq.message.answer(
            f'🎁 Демо-Premium активен на {DEMO_PREMIUM_HOURS} часа!\n'
            'безлимит сообщений, оживления фото и кружочки — всё твоё 😏\n'
            'когда время выйдет, я буду скучать по нашему безлимиту… 💋'
        )
    else:
        await cq.answer('демо уже использовано 😔 но для тебя есть скидка — открой /premium', show_alert=True)


@dp.callback_query(F.data == 'retention:premium')
async def retention_premium_cb(cq: types.CallbackQuery):
    """Paywall opened straight from the sleep block."""
    ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True); return
    from services.retention_service import discount_info
    await cq.answer()
    await cq.message.answer(premium_pitch_text(cq.from_user.id), reply_markup=premium_keyboard(discount_info(cq.from_user.id), telegram_id=cq.from_user.id))


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
    # V3.30.0: REST API link first; the SCI form link is only a fallback.
    link = await freekassa_service.create_api_order(
        order_id, str(FREEKASSA_PREMIUM_PRICE_RUB), telegram_id=cq.from_user.id,
    ) or freekassa_service.payment_url(order_id, FREEKASSA_PREMIUM_PRICE_RUB)
    await bot.send_message(
        cq.message.chat.id,
        f'💳 Оплата Premium картой / СБП — {FREEKASSA_PREMIUM_PRICE_RUB} ₽\n\n'
        f'{link}\n\n'
        'После оплаты премиум включится автоматически в течение минуты. '
        'Если что-то пойдёт не так — напиши /support.',
    )


@dp.callback_query(F.data == 'fk:premium_usd')
async def fk_premium_usd(cq: types.CallbackQuery):
    """V3.20.1: international Visa/Mastercard premium, invoiced in USD."""
    ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True); return
    if not FREEKASSA_ENABLED:
        await cq.answer('Оплата картой сейчас выключена — используй Stars ⭐', show_alert=True); return
    await cq.answer()
    order_id = freekassa_service.create_order(
        cq.from_user.id, 'premium_month', str(FREEKASSA_PREMIUM_PRICE_USD),
    )
    # V3.30.0: REST API link first; the SCI form link is only a fallback.
    link = await freekassa_service.create_api_order(
        order_id, str(FREEKASSA_PREMIUM_PRICE_USD), currency='USD',
        telegram_id=cq.from_user.id,
    ) or freekassa_service.payment_url(order_id, FREEKASSA_PREMIUM_PRICE_USD, currency='USD')
    await bot.send_message(
        cq.message.chat.id,
        f'💳 Оплата Premium картой Visa/Mastercard — ${FREEKASSA_PREMIUM_PRICE_USD}\n\n'
        f'{link}\n\n'
        'После оплаты премиум включится автоматически в течение минуты. '
        'Если что-то пойдёт не так — напиши /support.',
    )


def _fk_amount_for(product: str, currency: str) -> int:
    """V3.30.0: price lookup behind the fkapi: callback buttons."""
    if product == 'premium_month':
        return FREEKASSA_PREMIUM_PRICE_USD if currency == 'USD' else FREEKASSA_PREMIUM_PRICE_RUB
    if product == 'premium_week':
        # V3.34.1: card/SBP price of the weekly plan (RUB only).
        return FREEKASSA_PREMIUM_WEEKLY_PRICE_RUB
    if product == 'premium_quarter':
        # V3.43.0: the 3-month plan is card/SBP-purchasable too.
        return FREEKASSA_PREMIUM_QUARTERLY_PRICE_RUB
    if product == 'photo':
        # V3.43.0: the pay-method modal sells a single photo credit in rubles.
        from config import fiat_values
        return fiat_values(PHOTO_COST_STARS)[0]
    if product in PEACH_PACK_STARS:
        # V3.43.1: peach packs by card/SBP — the ruble twin of the Stars price.
        from config import fiat_values
        return fiat_values(PEACH_PACK_STARS[product])[0]
    if product == 'constructor_rub':
        return CONSTRUCTOR_COST_RUB
    if product.startswith('tokens_'):
        return int(product.split('_')[1]) * TOKEN_PRICE_RUB
    return FREEKASSA_PREMIUM_PRICE_RUB


@dp.callback_query(F.data.startswith('fkapi:'))
async def fkapi_pay(cq: types.CallbackQuery):
    """V3.30.0: FreeKassa REST API order — create the row, call
    POST /orders/create and hand the user the ``location`` payment link."""
    ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True); return
    if not FREEKASSA_ENABLED:
        await cq.answer('Оплата картой сейчас выключена — используй Stars ⭐', show_alert=True); return
    parts = cq.data.split(':')
    product, currency = parts[1], parts[2]
    pay_id = int(parts[3]) if len(parts) > 3 else None
    amount = _fk_amount_for(product, currency)
    await cq.answer('создаю счёт…')
    order_id = freekassa_service.create_order(cq.from_user.id, product, str(amount))
    link = await freekassa_service.create_api_order(
        order_id, str(amount), currency=currency,
        telegram_id=cq.from_user.id, payment_system=pay_id,
    )
    if not link:
        # API unreachable (no key/IP/error) — the SCI form link still pays.
        link = freekassa_service.payment_url(order_id, str(amount), currency=currency)
    sign = '$' if currency == 'USD' else '₽'
    if product == 'premium_month':
        title = f'💳 Premium — {sign}{amount}'
    elif product == 'premium_week':
        # V3.34.1: the weekly card/SBP invoice.
        title = f'💳 Premium на неделю — {sign}{amount}'
    elif product == 'constructor_rub':
        title = f'🎭 Персонаж — {sign}{amount}'
    elif product == 'photo':
        # V3.43.0: ruble-paid single photo credit from the app pay modal.
        title = f'🍑 Фото-кредит — {sign}{amount}'
    else:
        title = f'🪙 Токены — {sign}{amount}'
    await bot.send_message(
        cq.message.chat.id,
        f'{title} · оплата картой / СБП\n\n{link}\n\n'
        'После оплаты всё включится автоматически в течение минуты. '
        'Если что-то пойдёт не так — напиши /support.',
    )


@dp.callback_query(F.data.startswith('paymethod:'))
async def paymethod_show(cq: types.CallbackQuery):
    """V3.31.0: owner-configured QR payment method from the admin panel —
    send the saved QR photo with instructions so the user can pay outside
    the bot, then get the purchase granted manually by @username."""
    await cq.answer()
    method = get_payment_method(int(cq.data.split(':')[1]))
    if not method or method.status != 'active':
        await cq.message.answer('этот способ оплаты сейчас недоступен 🙂 попробуй Stars ⭐')
        return
    text = f'💳 {method.display_name}\n\n{method.instructions}'.strip()
    text += '\n\nПосле оплаты напиши владельцу свой @username в Telegram — он активирует покупку вручную.'
    if method.qr_photo_file_id:
        await bot.send_photo(cq.message.chat.id, method.qr_photo_file_id, caption=text[:1024])
    else:
        await cq.message.answer(text)


@dp.callback_query(F.data == 'cosplay:start')
async def cosplay_start(cq: types.CallbackQuery):
    """V3.30.0: costume picker for the token-priced cosplay photoshoot."""
    ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True); return
    await cq.answer()
    balance = get_token_balance(cq.from_user.id)
    rows = [[InlineKeyboardButton(text=label, callback_data=f'cosplay:{key}')]
            for key, (label, *_rest) in COSPLAY_COSTUMES.items()]
    rows.append([InlineKeyboardButton(text='⬅️ Фото-меню', callback_data='photo_menu:open')])
    await cq.message.answer(
        f'🎭 выбери костюм — сниму сет за {COSPLAY_TOKEN_COST}🪙\nтвой баланс: {balance}🪙',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@dp.callback_query(F.data.startswith('cosplay:'))
async def cosplay_pick(cq: types.CallbackQuery):
    """V3.30.0: charge tokens and shoot the chosen cosplay set."""
    ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True); return
    costume = COSPLAY_COSTUMES.get(cq.data.split(':', 1)[1])
    if costume is None:
        await cq.answer('такого костюма нет в списке 😅', show_alert=True); return
    if not spend_tokens(cq.from_user.id, COSPLAY_TOKEN_COST):
        await cq.answer(f'нужно {COSPLAY_TOKEN_COST}🪙 — токены продаются в премиум-меню', show_alert=True); return
    await cq.answer()
    # V3.31.7: the iconic hairstyle/color ride in their own request fields so
    # the prompt carries exactly ONE hairstyle for the costume.
    request = PhotoRequest(scene='cosplay', clothing=costume[1], hairstyle=costume[2], hair_color=costume[3])
    started = await _start_photo_background(
        cq.message.chat.id, cq.from_user.id, request, 'paid',
        amount=COSPLAY_TOKEN_COST, product='cosplay',
    )
    if not started:
        # Busy/budget guard blocked the job — give the tokens back.
        add_tokens(cq.from_user.id, COSPLAY_TOKEN_COST)
    else:
        await cq.message.answer(f'🎭 снимаю сет в образе «{costume[0]}»… {COSPLAY_TOKEN_COST}🪙 списала')


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
    elif payload=='premium_week':
        # V3.34.1: the weekly Premium option — chat and Mini App share it.
        ok=amount==PREMIUM_WEEKLY_STARS
    elif payload=='photo_pack':
        # V3.34.0: standalone +1 photo credit purchased from the Mini App shop.
        ok=amount==PHOTO_COST_STARS
    elif payload in PEACH_PACK_STARS:
        # V3.43.1: the peach pack ladder — 10/30/100 credits, bulk discount.
        ok=amount==PEACH_PACK_STARS[payload]
    elif payload=='premium_month_discount':
        from services.retention_service import discount_info
        info=discount_info(query.from_user.id)
        ok=bool(info.get('active')) and amount==info.get('price')
    elif payload=='circle':
        # V3.20.0: extra premium circles after the free daily slots are spent.
        ok=amount==VIDEO_COST_STARS and _any_video_engine() and is_premium(query.from_user.id)
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
    elif payload.startswith('spicy:'):
        # V3.23.0: paid hot sets — amount, level gate and 18+ are re-checked here.
        item = spicy_service.get_spicy_set(payload.split(':', 1)[1])
        ok = (bool(item) and amount == item.cost
              and item.min_level <= get_relationship_level(query.from_user.id, get_user_character(query.from_user.id))
              and is_adult_confirmed(query.from_user.id))
    elif payload.startswith('pgift:'):
        gift = spicy_service.get_private_gift(payload.split(':', 1)[1])
        ok = (bool(gift) and amount == gift.cost
              and gift.min_level <= get_relationship_level(query.from_user.id, get_user_character(query.from_user.id))
              and is_adult_confirmed(query.from_user.id))
    elif payload == 'fantasy:start':
        ok = (amount == spicy_service.FANTASY_COST_STARS
              and spicy_service.FANTASY_MIN_LEVEL <= get_relationship_level(query.from_user.id, get_user_character(query.from_user.id))
              and is_adult_confirmed(query.from_user.id))
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
    if payload in PEACH_PACK_STARS:
        # V3.43.1: a peach pack — same record path as the single credit, the
        # payments layer grants the whole pack size in one go.
        record_payment(message.from_user.id, payload, payment.total_amount, charge)
        track_event(ensure_user(message.from_user.id), 'stars_purchase', value=payment.total_amount, metadata={'product': payload, 'source': 'webapp'})
        pack_n = PEACH_PACK_CREDITS[payload]
        if user_lang(message.from_user.id) == EN:
            await message.answer(f'done 🍑 +{pack_n} photo credits added — ask me for a photo in chat and they will be used.')
        else:
            await message.answer(f'готово 🍑 +{pack_n} фото-кредитов на счету — проси фото в чате, и они спишутся.')
        return
    if payload == 'photo_pack':
        # V3.34.0: standalone +1 photo credit from the Mini App shop — same
        # product record as a chat photo purchase, so the grant is identical.
        record_payment(message.from_user.id, 'photo', payment.total_amount, charge)
        track_event(ensure_user(message.from_user.id), 'stars_purchase', value=payment.total_amount, metadata={'product': 'photo', 'source': 'webapp'})
        if user_lang(message.from_user.id) == EN:
            await message.answer('done 📸 +1 photo credit added — ask me for a photo in chat and it will be used.')
        else:
            await message.answer('готово 📸 +1 фото-кредит на счету — попроси фото в чате, и он спишется.')
        return

    if payload == 'premium_month':
        record_payment(message.from_user.id, 'premium_month', payment.total_amount, charge)
        track_event(ensure_user(message.from_user.id), 'stars_purchase', value=payment.total_amount, metadata={'product': 'premium_month'})
        if user_lang(message.from_user.id) == EN:
            await message.answer('done ✨ Premium is active for 30 days and I added 12 photo credits. Every photo of mine now has an «Animate» button — 2 free videos a day 🎬 plus my video circles 🎥')
        else:
            await message.answer('готово ✨ Premium активирован на 30 дней, и я добавила 12 photo credits. Теперь под каждым моим фото есть кнопка «Оживить» — 2 раза в день сделаю видео бесплатно 🎬 а ещё тебе открыты мои кружочки 🎥')
        return

    if payload == 'premium_week':
        # V3.34.1: the weekly Premium plan — 7 days + the weekly credit share.
        record_payment(message.from_user.id, 'premium_week', payment.total_amount, charge)
        track_event(ensure_user(message.from_user.id), 'stars_purchase', value=payment.total_amount, metadata={'product': 'premium_week'})
        if user_lang(message.from_user.id) == EN:
            await message.answer(f'done ✨ Premium is active for 7 days and I added {PREMIUM_WEEKLY_PHOTO_CREDITS} photo credits. Every photo of mine now has an «Animate» button — 2 free videos a day 🎬 plus my video circles 🎥')
        else:
            await message.answer(f'готово ✨ Premium активирован на 7 дней, и я добавила {PREMIUM_WEEKLY_PHOTO_CREDITS} photo credits. Теперь под каждым моим фото есть кнопка «Оживить» — 2 раза в день сделаю видео бесплатно 🎬 а ещё тебе открыты мои кружочки 🎥')
        return

    if payload == 'premium_month_discount':
        record_payment(message.from_user.id, 'premium_month_discount', payment.total_amount, charge)
        track_event(ensure_user(message.from_user.id), 'stars_purchase', value=payment.total_amount, metadata={'product': 'premium_month_discount'})
        await message.answer('готово ✨ Premium активирован на 30 дней со скидкой, и я добавила 12 photo credits. 2 оживления фото в день бесплатно + кружочки только для тебя 🎥💋')
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
        task = _spawn_job('video', message.from_user.id, _run_video_background(message.chat.id, message.from_user.id, delivery_id, charge, motion_preset=motion_preset), payload={'charge': charge, 'preset': motion_preset or 'auto'})
        _video_jobs[message.from_user.id] = task
        return

    if payload == 'circle':
        # V3.20.0: paid circle after the free Premium daily slots are spent.
        delivery = get_latest_photo_delivery(message.from_user.id)
        if not delivery or not delivery.get('telegram_file_id') or (message.from_user.id in _video_jobs and not _video_jobs[message.from_user.id].done()):
            try:
                await bot.refund_star_payment(user_id=message.from_user.id, telegram_payment_charge_id=charge)
                record_refund(message.from_user.id, charge, payment.total_amount, product='video')
                await message.answer('этот запрос уже нельзя запустить, поэтому Stars сразу вернул 🙂')
            except Exception:
                logger.exception('Circle pre-generation refund failed user=%s charge=%s', message.from_user.id, charge)
                await message.answer('не смог запустить кружочек. Напиши /support — проверим оплату.')
            return
        record_payment(message.from_user.id, 'video', payment.total_amount, charge)
        track_event(ensure_user(message.from_user.id), 'stars_purchase', value=payment.total_amount, metadata={'product': 'video', 'kind': 'circle'})
        task = _spawn_job('circle', message.from_user.id, _run_circle_background(message.chat.id, message.from_user.id, delivery['id'], charge), payload={'charge': charge})
        _video_jobs[message.from_user.id] = task
        return

    if payload.startswith('constructor:'):
        # V3.19.0: paid character constructor — avatar generation may take a
        # minute, so it runs as a task like the video pipeline.
        record_payment(message.from_user.id, 'constructor', payment.total_amount, charge)
        _spawn_job('constructor', message.from_user.id, _finish_constructor(message.chat.id, charge, message.from_user.id), payload={'charge': charge})
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

    if payload.startswith('spicy:'):
        # V3.23.0: paid hot set — narration, voice reply and a fresh private set
        # outside the daily quota; Stars auto-refund if delivery fails.
        item = spicy_service.get_spicy_set(payload.split(':', 1)[1])
        if not item:
            await message.answer('Оплата прошла, но сет уже не найден. Напиши /support — разберёмся.')
            return
        record_payment(message.from_user.id, 'spicy_set', payment.total_amount, charge)
        track_event(ensure_user(message.from_user.id), 'stars_purchase', value=payment.total_amount, metadata={'product': 'spicy_set', 'set': item.id})
        narration = item.text_en if user_lang(message.from_user.id) == EN else item.text
        await message.answer(f'{item.emoji} {narration}')
        await _send_voice_note(message.chat.id, message.from_user.id, narration)
        await _start_photo_background(message.chat.id, message.from_user.id, PhotoRequest(scene=item.scene, mood=item.mood), 'paid',
                                      charge=charge, amount=payment.total_amount, product='spicy_set')
        return

    if payload.startswith('pgift:'):
        # V3.23.0: private gift — affection delta + narration + 18+ photo finale.
        gift = spicy_service.get_private_gift(payload.split(':', 1)[1])
        if not gift:
            await message.answer('Оплата прошла, но подарок уже не найден. Напиши /support — разберёмся.')
            return
        record_payment(message.from_user.id, 'private_gift', payment.total_amount, charge)
        track_event(ensure_user(message.from_user.id), 'stars_purchase', value=payment.total_amount, metadata={'product': 'private_gift', 'gift': gift.id})
        character_id = get_user_character(message.from_user.id)
        await record_user_message(message.from_user.id, message.from_user.first_name or '', relationship=gift.affection, intimacy=round(gift.affection / 2, 2), event_type='gift', reason=f'pgift:{gift.id}', character_id=character_id)
        narration = gift.text_en if user_lang(message.from_user.id) == EN else gift.text
        await message.answer(f'{gift.emoji} Ты подарил {gift.name}!\n\n{narration}' if user_lang(message.from_user.id) != EN else f'{gift.emoji} You gifted the {gift.name_en}!\n\n{narration}')
        await _send_voice_note(message.chat.id, message.from_user.id, narration)
        await _start_photo_background(message.chat.id, message.from_user.id, PhotoRequest(scene=gift.scene, mood=gift.mood), 'paid',
                                      charge=charge, amount=payment.total_amount, product='private_gift')
        return

    if payload == 'fantasy:start':
        # V3.23.0: the fantasy constructor is paid first — the NEXT text
        # message becomes the scenario (parsed via whitelisted keywords only).
        record_payment(message.from_user.id, 'fantasy', payment.total_amount, charge)
        track_event(ensure_user(message.from_user.id), 'stars_purchase', value=payment.total_amount, metadata={'product': 'fantasy'})
        _fantasy_pending[message.from_user.id] = (charge, payment.total_amount)
        if user_lang(message.from_user.id) == EN:
            await message.answer('payment received 😌 now describe your fantasy in a few words — outfit, place, mood. I\'ll turn it into a photo set.')
        else:
            await message.answer('оплату получила 😌 теперь опиши фантазию в двух словах — образ, место, настроение. Я превращу её в сет фото.')
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
    # V3.41.0: mirror the date narration into the shared app/bot dialog so a
    # date paid from the Mini App also shows up in the app chat history (the
    # photo itself is generated into the bot chat right below).
    try:
        save_message(ensure_user(telegram_id, user_name), character_id, 'assistant', f'{date.emoji} {date.text}')
    except Exception:
        logger.warning('date history mirror failed user=%s date=%s', telegram_id, date.id)
    await _send_voice_note(chat_id, telegram_id, date.text)
    await _start_photo_background(chat_id, telegram_id, PhotoRequest(scene=date.scene, mood='romantic'), 'story')

@dp.message(F.text.in_(kb_pair('apartment')))
async def apartment_cmd(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    level = get_relationship_level(message.from_user.id, get_user_character(message.from_user.id))
    rows = [[InlineKeyboardButton(text=f'{r.emoji} {r.name}', callback_data=f'room:{r.id}')]
            for r in apartment_service.get_available_rooms(level)]
    rows += [[InlineKeyboardButton(text=f'🔒 {r.name} — уровень {r.min_level}', callback_data=f'room_locked:{r.id}')]
             for r in apartment_service.get_locked_rooms(level)]
    header = '🏠 My apartment 😊\n\nChoose a room:' if user_lang(message.from_user.id) == EN else '🏠 Моя квартира 😊\n\nВыбери комнату:'
    await message.answer(header, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


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


@dp.message(F.text.in_(kb_pair('gift')))
async def gifts_cmd(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    gifts = gifts_service.get_all()
    lines = []
    for g in gifts:
        if gifts_service.is_featured(g):
            lines.append(f'{g.emoji} {g.name} — {gifts_service.effective_cost(g)}⭐{fiat_suffix(gifts_service.effective_cost(g))} 🔥 подарок дня (вместо {g.cost}⭐)')
        else:
            lines.append(f'{g.emoji} {g.name} — {g.cost}⭐{fiat_suffix(g.cost)}')
    rows = [[InlineKeyboardButton(
        text=(f'{g.emoji} {g.name} · {gifts_service.effective_cost(g)}⭐{fiat_suffix(gifts_service.effective_cost(g))} 🔥' if gifts_service.is_featured(g)
              else f'{g.emoji} {g.name} · {g.cost}⭐{fiat_suffix(g.cost)}'),
        callback_data=f'gift:{g.id}')]
        for g in gifts]
    header = '🎁 Pick a gift — she will love it 😊\n\n' if user_lang(message.from_user.id) == EN else '🎁 Выбери подарок — она будет рада 😊\n\n'
    await message.answer(header + '\n'.join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


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


@dp.message(F.text.in_(kb_pair('date')))
async def dates_cmd(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    level = get_relationship_level(message.from_user.id, get_user_character(message.from_user.id))
    from services.gamification_service import completed_date_ids, has_free_date
    done = completed_date_ids(message.from_user.id)
    rows = [[InlineKeyboardButton(text=f'{"✅ " if d.id in done else ""}{d.emoji} {d.name} · {d.cost}⭐{fiat_suffix(d.cost)}', callback_data=f'date:{d.id}')]
            for d in dates_service.get_available(level)]
    rows += [[InlineKeyboardButton(text=f'🔒 {d.name} — уровень {d.min_level}', callback_data=f'date_locked:{d.id}')]
             for d in dates_service.get_locked(level)]
    banner = '\n\n🎁 У тебя есть бесплатное свидание за неделю стрика!' if has_free_date(message.from_user.id) else ''
    progress = f'\n\n📖 Свиданий в коллекции: {len(done)}/{len(dates_service.get_all())}'
    lead = '💕 Куда пойдём?'
    if user_lang(message.from_user.id) == EN:
        lead = '💕 Where shall we go?'
        banner = '\n\n🎁 you have a free date for your weekly streak!' if has_free_date(message.from_user.id) else ''
        progress = f'\n\n📖 dates in the collection: {len(done)}/{len(dates_service.get_all())}'
    await message.answer(f'{lead}{banner}{progress}', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


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


# === ПРИВАТНЫЙ РАЗДЕЛ (v3.23.0) — платные горячие сеты, приватные подарки ===
# и конструктор фантазий. Всё вне дневного лимита, только после 18+ и с
# уровнем не ниже каталожного; при любой неудаче доставки Stars возвращаются.

def _spicy_menu_text(telegram_id: int, lang: str) -> str:
    info = build_photo_menu(telegram_id, get_user_character(telegram_id))
    if lang == EN:
        return (
            f'🔥 Private section — everything here is outside your daily limit.\n'
            f'❤️ Intimacy: {info["level"]}/6 · paid sets never spend free photos or credits.\n\n'
            f'Choose what you want right now:'
        )
    return (
        f'🔥 Приватный раздел — всё здесь вне дневного лимита.\n'
        f'❤️ Близость: {info["level"]}/6 · платные сеты не тратят бесплатные фото и кредиты.\n\n'
        f'Выбери, что хочешь прямо сейчас:'
    )


def _spicy_menu_keyboard(telegram_id: int, lang: str) -> InlineKeyboardMarkup:
    level = get_relationship_level(telegram_id, get_user_character(telegram_id))
    lock_suffix = 'ур.' if lang == RU else 'lvl '
    rows: list[list[InlineKeyboardButton]] = []
    for item in spicy_service.SPICY_SETS:
        name = item.name_en if lang == EN else item.name
        if item.min_level <= level:
            rows.append([InlineKeyboardButton(text=f'{item.emoji} {name} · {item.cost}⭐{fiat_suffix(item.cost)}', callback_data=f'spicy:set:{item.id}')])
        else:
            rows.append([InlineKeyboardButton(text=f'🔒 {name} · {lock_suffix}{item.min_level}', callback_data=f'spicy:locked:{item.min_level}')])
    for gift in spicy_service.PRIVATE_GIFTS:
        name = gift.name_en if lang == EN else gift.name
        if gift.min_level <= level:
            rows.append([InlineKeyboardButton(text=f'{gift.emoji} {name} · {gift.cost}⭐{fiat_suffix(gift.cost)}', callback_data=f'spicy:gift:{gift.id}')])
        else:
            rows.append([InlineKeyboardButton(text=f'🔒 {name} · {lock_suffix}{gift.min_level}', callback_data=f'spicy:locked:{gift.min_level}')])
    fantasy_name = '🎭 Фантазия — сценарий от тебя' if lang == RU else '🎭 Fantasy — your scenario'
    if level >= spicy_service.FANTASY_MIN_LEVEL:
        rows.append([InlineKeyboardButton(text=f'{fantasy_name} · {spicy_service.FANTASY_COST_STARS}⭐{fiat_suffix(spicy_service.FANTASY_COST_STARS)}', callback_data='spicy:fantasy')])
    else:
        rows.append([InlineKeyboardButton(text=f'🔒 {fantasy_name} · {lock_suffix}{spicy_service.FANTASY_MIN_LEVEL}', callback_data=f'spicy:locked:{spicy_service.FANTASY_MIN_LEVEL}')])
    back = '← 📸 Фото' if lang == RU else '← 📸 Photos'
    rows.append([InlineKeyboardButton(text=back, callback_data='photo_menu:open')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(F.data == 'spicy:menu')
async def spicy_menu_callback(cq: types.CallbackQuery):
    ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if not is_adult_confirmed(cq.from_user.id):
        await cq.answer()
        await cq.message.answer('подтверди 18+ одной кнопкой — и сразу открою приватный раздел 🔥', reply_markup=adult_keyboard())
        return
    await cq.answer()
    lang = user_lang(cq.from_user.id)
    await cq.message.answer(_spicy_menu_text(cq.from_user.id, lang), reply_markup=_spicy_menu_keyboard(cq.from_user.id, lang))


@dp.callback_query(F.data.startswith('spicy:set:'))
async def spicy_set_callback(cq: types.CallbackQuery):
    item = spicy_service.get_spicy_set(cq.data.split(':', 2)[2])
    if not item:
        await cq.answer('Сет не найден', show_alert=True)
        return
    level = get_relationship_level(cq.from_user.id, get_user_character(cq.from_user.id))
    if item.min_level > level:
        await cq.answer(f'Откроется на уровне {item.min_level} 😉', show_alert=True)
        return
    if not is_adult_confirmed(cq.from_user.id):
        await cq.answer()
        await cq.message.answer('подтверди 18+ одной кнопкой — и сразу открою приватный раздел 🔥', reply_markup=adult_keyboard())
        return
    await cq.answer()
    track_event(ensure_user(cq.from_user.id), 'paywall_view', metadata={'product': 'spicy_set', 'set': item.id})
    lang = user_lang(cq.from_user.id)
    name = item.name_en if lang == EN else item.name
    description = item.text_en if lang == EN else item.text
    await send_stars_invoice(cq.message.chat.id, f'{item.emoji} {name}',
                             f'{description}\n\n{"Fresh photo set, outside your daily limit 📸" if lang == EN else "Свежий сет фото, вне дневного лимита 📸"}',
                             f'spicy:{item.id}', item.cost)


@dp.callback_query(F.data.startswith('spicy:gift:'))
async def spicy_gift_callback(cq: types.CallbackQuery):
    gift = spicy_service.get_private_gift(cq.data.split(':', 2)[2])
    if not gift:
        await cq.answer('Подарок не найден', show_alert=True)
        return
    level = get_relationship_level(cq.from_user.id, get_user_character(cq.from_user.id))
    if gift.min_level > level:
        await cq.answer(f'Откроется на уровне {gift.min_level} 😉', show_alert=True)
        return
    if not is_adult_confirmed(cq.from_user.id):
        await cq.answer()
        await cq.message.answer('подтверди 18+ одной кнопкой — и сразу открою приватный раздел 🔥', reply_markup=adult_keyboard())
        return
    await cq.answer()
    track_event(ensure_user(cq.from_user.id), 'paywall_view', metadata={'product': 'private_gift', 'gift': gift.id})
    lang = user_lang(cq.from_user.id)
    name = gift.name_en if lang == EN else gift.name
    description = gift.text_en if lang == EN else gift.text
    await send_stars_invoice(cq.message.chat.id, f'{gift.emoji} {name}',
                             f'{description}\n\n{"She reacts, your bond grows — and a private photo set follows 📸" if lang == EN else "Она отреагирует, связь станет крепче — а в конце приватный сет фото 📸"}',
                             f'pgift:{gift.id}', gift.cost)


@dp.callback_query(F.data == 'spicy:fantasy')
async def spicy_fantasy_callback(cq: types.CallbackQuery):
    level = get_relationship_level(cq.from_user.id, get_user_character(cq.from_user.id))
    if level < spicy_service.FANTASY_MIN_LEVEL:
        await cq.answer(f'Откроется на уровне {spicy_service.FANTASY_MIN_LEVEL} 😉', show_alert=True)
        return
    if not is_adult_confirmed(cq.from_user.id):
        await cq.answer()
        await cq.message.answer('подтверди 18+ одной кнопкой — и сразу открою приватный раздел 🔥', reply_markup=adult_keyboard())
        return
    await cq.answer()
    track_event(ensure_user(cq.from_user.id), 'paywall_view', metadata={'product': 'fantasy'})
    lang = user_lang(cq.from_user.id)
    title = '🎭 Фантазия' if lang == RU else '🎭 Fantasy'
    if lang == EN:
        description = 'Describe your scenario in a few words — outfit, place, mood — and she will shoot a custom set for you.'
    else:
        description = 'Опиши сценарий в двух словах — образ, место, настроение — и она снимет персональный сет.'
    await send_stars_invoice(cq.message.chat.id, title, description, 'fantasy:start', spicy_service.FANTASY_COST_STARS)


@dp.callback_query(F.data.startswith('spicy:locked:'))
async def spicy_locked_callback(cq: types.CallbackQuery):
    try:
        required = int(cq.data.split(':', 2)[2])
    except ValueError:
        await cq.answer()
        return
    current = get_relationship_level(cq.from_user.id, get_user_character(cq.from_user.id))
    if user_lang(cq.from_user.id) == EN:
        alert = f'🔒 Unlocks at level {required}/{MAX_RELATIONSHIP_LEVEL}. You are at {current}/{MAX_RELATIONSHIP_LEVEL}. Intimacy grows from conversation.'
    else:
        alert = f'🔒 Откроется на уровне {required}/{MAX_RELATIONSHIP_LEVEL}. Сейчас {current}/{MAX_RELATIONSHIP_LEVEL}. Близость растёт от общения.'
    await cq.answer(alert, show_alert=True)


async def _handle_fantasy_input(message: types.Message) -> None:
    """The paid fantasy constructor consumes the user's NEXT text message.
    Only whitelisted keyword extractions reach the image prompt."""
    charge, amount = _fantasy_pending[message.from_user.id]
    text_value = (message.text or '').strip()
    if len(text_value) < 3:
        if user_lang(message.from_user.id) == EN:
            await message.answer('a bit more detail 🙂 for example: “black lace, by the mirror, bold”')
        else:
            await message.answer('опиши чуть подробнее 🙂 например: «в чёрном кружеве, у зеркала, дерзко»')
        return
    fields = spicy_service.parse_fantasy(text_value)
    del _fantasy_pending[message.from_user.id]
    uid = ensure_user(message.from_user.id)
    track_event(uid, 'fantasy_request', metadata={'scene': fields['scene']})
    if user_lang(message.from_user.id) == EN:
        await message.answer('got it 😌 assembling your set…')
    else:
        await message.answer('приняла 😌 собираю твой сет…')
    await _start_photo_background(message.chat.id, message.from_user.id, PhotoRequest(**fields), 'paid',
                                  charge=charge, amount=amount, product='fantasy')


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
    if user_lang(cq.from_user.id) == EN:
        alert = (
            f'🔒 Unlocks at level {required}/{MAX_RELATIONSHIP_LEVEL}. You are at {current}/{MAX_RELATIONSHIP_LEVEL}. '
            'Intimacy grows from conversation — levels cannot be bought.'
        )
    else:
        alert = (
            f'🔒 Откроется на уровне {required}/{MAX_RELATIONSHIP_LEVEL}. Сейчас {current}/{MAX_RELATIONSHIP_LEVEL}. '
            'Близость растёт от общения — купить уровень нельзя.'
        )
    await cq.answer(alert, show_alert=True)


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
    # V3.29.0: read/modify/write-back so the draft lands in dialog_sessions.
    draft = dict(_custom_drafts.get(cq.from_user.id) or {})
    draft['color'] = color
    _custom_drafts[cq.from_user.id] = draft
    await cq.message.answer('добавить чулки?', reply_markup=custom_addon_keyboard())


@dp.callback_query(F.data.startswith('custom:addon:'))
async def custom_addon(cq: types.CallbackQuery):
    await cq.answer()
    addon = cq.data.rsplit(':', 1)[1]
    # V3.29.0: read/modify/write-back so the draft lands in dialog_sessions.
    draft = dict(_custom_drafts.get(cq.from_user.id) or {})
    draft['addon'] = addon
    _custom_drafts[cq.from_user.id] = draft
    await cq.message.answer('причёска?', reply_markup=custom_hair_keyboard())


@dp.callback_query(F.data.startswith('custom:hair:'))
async def custom_hair(cq: types.CallbackQuery):
    await cq.answer()
    hair = cq.data.rsplit(':', 1)[1]
    # V3.29.0: read/modify/write-back so the draft lands in dialog_sessions.
    draft = dict(_custom_drafts.get(cq.from_user.id) or {})
    draft['hair'] = hair
    _custom_drafts[cq.from_user.id] = draft
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


@dp.message(F.text.in_(kb_pair('chat')))
async def chat_button(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    if user_lang(message.from_user.id) == EN:
        await message.answer('I am here 🙂 just write to me like usual')
    else:
        await message.answer('я здесь 🙂 просто пиши мне как обычно')


@dp.message(F.text.in_(kb_pair('photo')))
async def photo_button(message: types.Message):
    await photo_menu(message)


@dp.message(F.text.in_(kb_pair('invite')))
async def referral_button(message: types.Message):
    """Persistent menu button so the referral link is always one tap away,
    not buried in a one-time consent message that scrolls out of view."""
    await referral_cmd(message)


@dp.message(F.text.in_(kb_pair('partner') + ('💰 Партнёрка',)))
async def partner_button(message: types.Message):
    """V3.37.0: the «💰 Партнёрская программа» reply-keyboard row — stats +
    payouts. The pre-V3.42.0 «💰 Партнёрка» label still resolves so cached
    reply keyboards keep working."""
    await referral_cmd(message)


# V3.38.0: the Come Closer funnel — the reply keyboard is the Mini App
# launcher. These three buttons either open the app right here (inline
# web_app button) or point at the tab where the action now lives.
def _app_entry_markup(lang: str) -> InlineKeyboardMarkup | None:
    """Inline «open the app» button; None when the app is not wired on the server."""
    if not PUBLIC_BASE_URL:
        return None
    url = f'{PUBLIC_BASE_URL}/webapp'
    label = '🛍 Open App' if lang == EN else '🛍 Открыть приложение'
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, web_app=types.WebAppInfo(url=url))],
    ])


async def _send_app_entry(message: types.Message, intro_ru: str, intro_en: str):
    """Answer with the app-opening inline button (or the setup hint)."""
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    lang = user_lang(message.from_user.id)
    markup = _app_entry_markup(lang)
    if markup is None:
        hint = ('the app is not connected on the server yet — the owner needs to set PUBLIC_BASE_URL (the Railway domain).'
                if lang == EN else
                'приложение ещё не подключено на сервере — нужно задать PUBLIC_BASE_URL (домен Railway).')
        await message.answer('🛍 ' + hint)
        return
    await message.answer(intro_en if lang == EN else intro_ru, reply_markup=markup)


@dp.message(F.text.in_(kb_pair('app')))
async def app_button(message: types.Message):
    """V3.38.0: «📱 Открыть приложение» — the top funnel row."""
    await _send_app_entry(
        message,
        '🛍 приложение AnnaBot — персонажи, чаты, картинки, магазин и твой профиль:',
        '🛍 AnnaBot app — characters, chats, pictures, shop and your profile:',
    )


@dp.message(F.text.in_(kb_pair('credits')))
async def credits_button(message: types.Message):
    """V3.38.0: «🍑 Персики» — buying photo credits now lives in the
    app's «Магазин» tab; the button carries the user straight into the app."""
    await _send_app_entry(
        message,
        '🍑 персики (фото-кредиты) покупаются в приложении — вкладка «Магазин» 👇',
        '🍑 peaches (photo credits) are bought in the app — the «Shop» tab 👇',
    )


@dp.message(F.text.in_(kb_pair('paint')))
async def paint_button(message: types.Message):
    """V3.38.0: «🖼 Создать картинку» — the picture studio lives in the app's
    «Картинки» tab."""
    await _send_app_entry(
        message,
        '🖼 создавать картинки по своим промптам теперь можно в приложении — вкладка «Картинки» 👇',
        '🖼 creating pictures from your prompts now lives in the app — the «Pictures» tab 👇',
    )



@dp.message(F.text == '🎭 Образы')
async def looks_button_legacy(message: types.Message):
    # Old Telegram reply keyboards can remain cached after a deploy. The button is
    # removed from the new UI; redirect stale clicks into the consolidated photo menu.
    await message.answer('Раздел «Образы» теперь внутри 📸 Фото.', reply_markup=main_keyboard(message.from_user.id in ADMIN_TELEGRAM_IDS, message.from_user.id))
    await photo_menu(message)


@dp.message(F.text.in_(kb_pair('premium')))
async def premium_button(message: types.Message):
    await premium(message)


@dp.message(F.text.in_(kb_pair('stories')))
async def stories_button(message: types.Message):
    await stories_cmd(message)


@dp.message(F.text.in_(kb_pair('collection')))
async def collection_button(message: types.Message):
    await collection_cmd(message)


@dp.message(F.text.in_(kb_pair('profile')))
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
    # V3.21.0: hearts progress, couple extras and the premium plateau hint.
    from services import couple_service
    from services.ui_lang import LEVEL_NAMES_EN
    lang = user_lang(message.from_user.id)
    level = info['level']
    names = LEVEL_NAMES_EN if lang == EN else RELATIONSHIP_LEVEL_NAMES
    level_name = names.get(level, 'Getting to know each other' if lang == EN else 'Знакомство')
    hearts = '❤️' * min(level, MAX_RELATIONSHIP_LEVEL) + '🤍' * max(0, MAX_RELATIONSHIP_LEVEL - level)
    plateau_hint = ''
    if not info['premium'] and level >= 6:
        plateau_hint = (
            '🔒 ahead is the “Kindred spirits” and “One whole” plateau — levels 7–8 are Premium only\n'
            if lang == EN else
            '🔒 впереди плато «Родственные души» и «Одно целое» — уровни 7–8 открыты только с Premium\n'
        )
    album_count = len(couple_service.album_entries(uid))
    pet_name = couple_service.get_pet_name(message.from_user.id)
    pet_line = f'\n🥰 she calls you “{pet_name}”' if (pet_name and lang == EN) else (f'\n🥰 она зовёт тебя «{pet_name}»' if pet_name else '')
    if lang == EN:
        await message.answer(
            f'👤 Your profile\n\n'
            f'{hearts}\n{level_name} · level {level}/{MAX_RELATIONSHIP_LEVEL}\n'
            f'{plateau_hint}'
            f'{bond_text}'
            f'{progress_text}'
            f'⭐ Premium: {"active" if info["premium"] else "no"}\n'
            f'📸 Photos today: {info["free_left"]} included\n'
            f'🎟 Photo credits: {info["credits"]}\n'
            f'💑 Our album: {album_count}/{MAX_RELATIONSHIP_LEVEL} — a keepsake photo from every level\n'
            f'📸 Collection: {collection_progress(message.from_user.id, CHARACTER_ID, info["level"])["seen"]}/{collection_progress(message.from_user.id, CHARACTER_ID, info["level"])["total"]} · /collection\n'
            f'🎯 Stories: /stories'
            f'{pet_line}'
            f'{milestone_text}'
        )
        return
    await message.answer(
        f'👤 Твой профиль\n\n'
        f'{hearts}\n{level_name} · уровень {level}/{MAX_RELATIONSHIP_LEVEL}\n'
        f'{plateau_hint}'
        f'{bond_text}'
        f'{progress_text}'
        f'⭐ Premium: {"активен" if info["premium"] else "нет"}\n'
        f'📸 Фото сегодня: {info["free_left"]} включено\n'
        f'🎟 Photo credits: {info["credits"]}\n'
        f'💑 Наш альбом: {album_count}/{MAX_RELATIONSHIP_LEVEL} — памятное фото с каждого уровня\n'
        f'📸 Коллекция: {collection_progress(message.from_user.id, CHARACTER_ID, info["level"])["seen"]}/{collection_progress(message.from_user.id, CHARACTER_ID, info["level"])["total"]} · /collection\n'
        f'🎯 Истории: /stories'
        f'{pet_line}'
        f'{milestone_text}'
    )


@dp.message(F.text.in_(kb_pair('alarm')))
async def alarm_button(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    premium = is_premium(message.from_user.id)
    lang = user_lang(message.from_user.id)
    if not premium:
        if lang == EN:
            await message.answer(
                '⏰ Alarm and reminders — a Premium feature\n\n'
                'With Premium, she will wake you up in the morning, remind you about things and always remember your timezone.\n\n'
                '/premium — subscribe',
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text='⭐ Get Premium', callback_data='premium:view')]
                ]),
            )
        else:
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


@dp.message(F.text.in_(kb_pair('settings')))
async def settings_button(message: types.Message):
    await settings(message)


@dp.message(F.text.in_(kb_pair('support')))
async def support_button(message: types.Message):
    # V3.43.0: support moved to the dedicated @Anna67901support_bot — this
    # button no longer arms an in-bot ticket, it just opens the support chat
    # where the team answers directly (owner request: «привяжи нового бота»).
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    lang = user_lang(message.from_user.id)
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text='👥 написать в поддержку' if lang != EN else '👥 contact support',
        url=f'https://t.me/{SUPPORT_BOT_USERNAME}')]])
    if lang == EN:
        await message.answer(
            '👥 support\n\nwrite to our support bot — the team answers there directly 👇',
            reply_markup=markup,
        )
    else:
        await message.answer(
            '👥 поддержка\n\nнапиши нашему боту поддержки — команда ответит прямо там 👇',
            reply_markup=markup,
        )


async def _deliver_support_message(message: types.Message, text_value: str) -> bool:
    """Forward a support ticket to every admin. Shared by /support and the
    «👥 Поддержка» button flow."""
    text_value = text_value.strip()[:1500]
    if not text_value:
        return False
    delivered = False
    for admin_id in ADMIN_TELEGRAM_IDS:
        try:
            await bot.send_message(admin_id, f'🛟 Support\nuser: {message.from_user.id}\nname: {message.from_user.first_name or "—"}\n\n{text_value}')
            delivered = True
        except Exception:
            logger.exception('failed to forward support admin=%s', admin_id)
    track_event(ensure_user(message.from_user.id), 'support_request')
    return delivered


async def _deliver_admin_reply(message: types.Message, user_id: int) -> None:
    """V3.42.0: the owner answers a support ticket by REPLYING to the ticket
    message in his own chat; the reply text is delivered to that user. Before
    this there was no way to answer — tickets were write-only for the owner."""
    text = (message.text or '').strip()
    if not text:
        return
    lang = user_lang(user_id)
    prefix = '💬 support reply:\n\n' if lang == EN else '💬 ответ поддержки:\n\n'
    try:
        await bot.send_message(user_id, prefix + text)
    except Exception:
        logger.exception('failed to deliver support reply user=%s', user_id)
        await message.answer('не удалось доставить ответ — пользователь не может получать сообщения.')
        return
    await message.answer(f'↩️ отправлено пользователю {user_id} ✔')


@dp.message(F.text.in_(kb_pair('legal')))
async def legal_button(message: types.Message):
    # V3.32.0: «Документы» — permanently visible legal menu (privacy policy,
    # user agreement, tariffs, support) required by the payment partner's bank.
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    lang = user_lang(message.from_user.id)
    await message.answer(legal_service.legal_menu_text(lang), reply_markup=legal_keyboard(lang))


# V3.21.0: first-row discovery buttons. They route into the existing inline
# flows (video presets / circle gate / daily quest) so nothing hides in sub-menus.
@dp.message(F.text.in_(kb_pair('video')))
async def video_button(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    if user_lang(message.from_user.id) == EN:
        await message.answer(
            '🎬 video from me\n\n'
            'I can animate the last photo into a short video or record a video circle with my voice 😌',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text='🎬 Animate the last photo', callback_data='video:animate_last')],
                [InlineKeyboardButton(text='🎥 Record a circle', callback_data='video:circle')],
            ]),
        )
        return
    await message.answer(
        '🎬 видео от меня\n\n'
        'могу оживить последнее фото в короткое видео или записать тебе кружочек с голосом 😌',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='🎬 Оживить последнее фото', callback_data='video:animate_last')],
            [InlineKeyboardButton(text='🎥 Записать кружочек', callback_data='video:circle')],
        ]),
    )


@dp.message(F.text.in_(kb_pair('circle')))
async def circle_button(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    if user_lang(message.from_user.id) == EN:
        text = '🎥 a video circle — as if I record it just for you, with my own voice 😊'
        button = '🎥 Record a circle'
    else:
        text = '🎥 кружочек — как будто записываю его тебе лично, со своим голосом 😊'
        button = '🎥 Записать кружочек'
    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=button, callback_data='video:circle')],
        ]),
    )


@dp.message(F.text.in_(kb_pair('quest')))
async def daily_quest_button(message: types.Message):
    """V3.21.0: one small request from her per day; claiming it grants attention."""
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    from services import couple_service
    uid = ensure_user(message.from_user.id)
    _, quest_text = couple_service.daily_quest(message.from_user.id)
    user = get_user(message.from_user.id)
    claimed = (user.quest_claimed_date or '') == couple_service._today_key()
    lang = user_lang(message.from_user.id)
    if claimed:
        if lang == EN:
            await message.answer(f'🎯 daily quest: {quest_text}\n\nyou already completed it today ❤️ she can feel it.')
        else:
            await message.answer(f'🎯 задание дня: {quest_text}\n\nты уже выполнил его сегодня ❤️ она это чувствует.')
        return
    if lang == EN:
        await message.answer(
            f'🎯 daily quest: {quest_text}\n\nwhen you do it, tap “Done” and I will notice 😊 (+5 attention)',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text='✅ Done · +5 attention', callback_data='questday:claim')],
            ]),
        )
    else:
        await message.answer(
            f'🎯 задание дня: {quest_text}\n\nкак сделаешь — нажми «выполнено», и я это замечу 😊 (+5 внимания)',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text='✅ Выполнено · +5 внимания', callback_data='questday:claim')],
            ]),
        )
    track_event(uid, 'daily_quest_view', metadata={'quest': couple_service.daily_quest(message.from_user.id)[0]})


@dp.callback_query(F.data == 'questday:claim')
async def daily_quest_claim(cq: types.CallbackQuery):
    from services import couple_service
    uid = ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if couple_service.claim_daily_quest(cq.from_user.id):
        track_event(uid, 'daily_quest_claimed')
        await cq.answer('+5 внимания ❤️')
        await cq.message.answer('ммм, приятно 😊 +5 очков внимания. она запомнила.')
    else:
        await cq.answer('сегодня уже выполнено', show_alert=True)


@dp.callback_query(F.data == 'toggle:rituals')
async def toggle_rituals(cq: types.CallbackQuery):
    """V3.21.0: opt out of morning/evening ritual pushes without losing chat."""
    user = get_user(cq.from_user.id)
    new = not (user.notify_rituals if user and user.notify_rituals is not None else True)
    update_user_settings(cq.from_user.id, notify_rituals=new)
    await cq.answer('сохранила')
    await cq.message.answer('утренние и вечерние сообщения: ' + ('вкл 😊' if new else 'выкл, буду писать только по делу'))


@dp.callback_query(F.data == 'toggle:spicy')
async def toggle_spicy(cq: types.CallbackQuery):
    """V3.37.0: the premium-gated «пошлый режим» switch.

    Enabling requires an active Premium; disabling is always allowed. The
    flag survives a lapsed subscription but the chat gate re-checks Premium
    on every message, so the mode simply sleeps until the next payment.
    """
    user = get_user(cq.from_user.id)
    current = bool(getattr(user, 'spicy_mode', False)) if user else False
    lang = user_lang(cq.from_user.id)
    if not current and not is_premium(cq.from_user.id):
        await cq.answer('нужен Premium ⭐' if lang != EN else 'Premium required ⭐', show_alert=True)
        await cq.message.answer(
            'пошлый режим — фишка Premium 🌶 включи Premium в «🚀 Премиум» — и переключатель заработает.'
            if lang != EN else
            'spicy mode is a Premium perk 🌶 grab Premium and the switch turns on.'
        )
        return
    new = not current
    update_user_settings(cq.from_user.id, spicy_mode=new)
    await cq.answer('сохранила ❤️' if new else 'выключила')
    if new:
        await cq.message.answer(
            'пошлый режим включён 🔥 теперь флирт горячее — она будет намёкать смелее и откровеннее. '
            'выключить можно тут же в «⚙️ Настройки».'
            if lang != EN else
            'spicy mode is on 🔥 the flirting gets hotter and bolder. Switch it off anytime in «⚙️ Settings».'
        )
    else:
        await cq.message.answer(
            'пошлый режим выключен 🌙 флирт снова обычный.'
            if lang != EN else
            'spicy mode is off 🌙 back to regular flirting.'
        )


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

# V3.29.0: the wizard's state lives in dialog_sessions, so a redeploy keeps it.
_constructor_sessions = dialog_store.DialogStore('constructor_sessions')

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
        buy_label = f'✅ Создать · {CONSTRUCTOR_COST_STARS}⭐{fiat_suffix(CONSTRUCTOR_COST_STARS, rub=CONSTRUCTOR_COST_RUB, usd=CONSTRUCTOR_PRICE_USD)}'
        price_note = f'Готова родиться за {CONSTRUCTOR_COST_STARS} Stars{fiat_suffix(CONSTRUCTOR_COST_STARS, rub=CONSTRUCTOR_COST_RUB, usd=CONSTRUCTOR_PRICE_USD)} ✨'
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


async def _finish_constructor(chat_id: int, charge: str | None, telegram_id: int | None = None):
    """After Stars payment: generate the avatar, save the persona, open chat.

    V3.35.0: takes a chat id instead of a Message — the Mini App constructor
    pays through the same successful_payment pipeline and has no Message to
    reply into; the user's private chat id serves both callers.
    """
    # V3.24.0: the admin free path used to pass the callback message, whose
    # from_user is the BOT — the session must be looked up by the real user id.
    if telegram_id is None:
        telegram_id = chat_id
    cons = _constructor_sessions.pop(telegram_id, None)
    if not cons:
        await bot.send_message(chat_id, 'что-то потерялось 😕 нажми «🎨 Мой персонаж» ещё раз.')
        return
    params = cons['params']
    display_name = str(params.get('name') or 'Она')[:48]
    await bot.send_message(chat_id, '✨ Отлично! Рисую твою героиню — это займёт до минуты...')
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
                await bot.send_message(chat_id, 'аватар сейчас не получился 😕 Stars вернул автоматически. Попробуй ещё раз чуть позже.')
            except Exception:
                logger.exception('constructor refund failed user=%s', telegram_id)
                await bot.send_message(chat_id, 'аватар не получился 😕 напиши /support — вернём Stars.')
        else:
            # Admin free run — nothing to refund.
            await bot.send_message(chat_id, 'аватар сейчас не получился 😕 попробуй ещё раз чуть позже.')
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
    # V3.31.8: creating a persona selects her immediately. Before this the
    # selection stayed on the previous character (Anna by default), so a user
    # who built their own girl and pressed «💕 Свидание» got a date with Anna.
    set_user_character(telegram_id, row.character_id)
    track_event(ensure_user(telegram_id), 'character_selected', metadata={'character_id': row.character_id, 'custom': True})
    # Register her as a real character card so photo/relationship pipelines
    # recognize the id; bio carries the appearance description for prompts.
    descriptor_bits = [
        OPTION_LABELS[str(params[key])] for key in PARAM_TITLES
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
            # V3.37.0: anime personas get their own card emoji.
            card_emoji = '🌸' if str(params.get('style', '')) == 'style_anime' else '🎨'
            create_card(row.character_id, display_name, card_age, bio, card_emoji, 'female')
            update_card(row.character_id, status='active', card_photo_file_id=avatar_file_id)
    except Exception:
        logger.exception('constructor card registration failed user=%s', telegram_id)
    track_event(
        ensure_user(telegram_id),
        'stars_purchase', value=CONSTRUCTOR_COST_STARS,
        metadata={'product': 'constructor', 'face_swap': bool(cons.get('face_bytes'))},
    )
    await bot.send_message(
        chat_id,
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
    # V3.29.0: write the params dict back whole so the change hits the DB row.
    params = dict(cons.get('params') or {})
    params[key] = value
    cons['params'] = params
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
        _spawn_job('constructor', telegram_id, _finish_constructor(cq.message.chat.id, None, telegram_id), payload={'source': 'free'})
        return
    # V3.27.0: a ruble-paid constructor credit (FreeKassa) skips Stars too.
    if consume_constructor_credit(telegram_id):
        record_payment(telegram_id, 'constructor', 0, f'freekassa_credit:{telegram_id}:{int(_time.time() * 1000)}')
        _spawn_job('constructor', telegram_id, _finish_constructor(cq.message.chat.id, None, telegram_id), payload={'source': 'free'})
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
    set_user_character(cq.from_user.id, character_id)
    track_event(ensure_user(cq.from_user.id), 'character_selected', metadata={'character_id': character_id, 'custom': True})
    await cq.message.answer(
        f'✅ Теперь ты общаешься с {row.display_name or "ней"}. Пиши ей прямо сюда 👇',
        reply_markup=main_keyboard(cq.from_user.id in ADMIN_TELEGRAM_IDS, cq.from_user.id),
    )
    await cq.message.answer(f'{row.display_name or "Она"}: «Ну привет... я ждала, когда ты наконец выберешь меня 😏 Расскажи мне о себе.»')


@dp.message(F.text.in_(kb_pair('custom')))
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
        # V3.21.0: from level 3 she has her own name for him.
        if level == 3:
            from services import couple_service
            pet = couple_service.assign_pet_name(telegram_id)
            if pet:
                text += f'\n\nи да… теперь я буду звать тебя «{pet}» 😊'
        if level >= 7:
            text += '\n\nэто плато только для нас двоих — такое доступно лишь с Premium 💋'
        if unlocks:
            text += '\n\nТеперь доступно:\n' + '\n'.join('• ' + u for u in unlocks)
        text += '\n\nи небольшой подарок от меня 🤍'
        await bot.send_message(telegram_id, text)
        track_event(ensure_user(telegram_id), 'relationship_ceremony_sent', metadata={'level': level}, character_id=character_id)
        await _start_photo_background(telegram_id, telegram_id, PhotoRequest(scene='selfie', mood='romantic'), 'story')
    except Exception as exc:
        logger.warning('level-up ceremony failed user=%s error=%s', telegram_id, type(exc).__name__)


set_stage_change_notifier(_on_relationship_stage_up)


# V3.21.0: levels 7-8 are premium-only. The engine receives the INTERNAL user
# id, so translate it back to a Telegram id before checking the subscription.
def _premium_by_internal_uid(uid: int) -> bool:
    try:
        with SessionLocal() as session:
            user = session.get(User, uid)
            return bool(user) and is_premium(int(user.telegram_id))
    except Exception:
        return False


from services.relationship_engine import set_premium_checker
set_premium_checker(_premium_by_internal_uid)


@dp.message(F.voice)
async def voice_message(message: types.Message):
    uid = ensure_user(message.from_user.id, message.from_user.first_name)
    track_event(uid, 'chat_user_message', metadata={'kind': 'voice'})
    _track_proactive_reply_if_any(message.from_user.id, uid)
    cancel_active_wake(message.from_user.id)
    if message.from_user.id not in ADMIN_TELEGRAM_IDS and not can_send_message(message.from_user.id):
        # V3.20.0: she "falls asleep" instead of a dry limit notice.
        await _sleep_block_reply(message)
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
        answer, had_fake_photo = _strip_fake_photo(answer)
        if had_fake_photo:
            logger.info('fake_photo_intercepted user=%s source=voice', message.from_user.id)
            asyncio.create_task(_deliver_intercepted_photo(message))
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

    # V3.42.0: the owner answers support tickets by replying to the ticket
    # message («🛟 Support / user: …») in his own chat — the reply is delivered
    # straight to that user instead of going to the character.
    if message.from_user and message.from_user.id in ADMIN_TELEGRAM_IDS:
        replied_text = (message.reply_to_message.text or '') if message.reply_to_message is not None else ''
        if replied_text.startswith(('🛟 Support', '💳 Payment support')):
            ticket = re.search(r'^user: (\d+)', replied_text, re.M)
            if ticket:
                await _deliver_admin_reply(message, int(ticket.group(1)))
                return

    # V3.23.0: a paid fantasy constructor is waiting for the scenario text.
    if message.from_user and message.from_user.id in _fantasy_pending:
        await _handle_fantasy_input(message)
        return

    # V3.38.0: «👥 Поддержка» armed — the next plain text is a ticket for the
    # owner, not a message for the character. Commands above still pass through.
    if message.from_user and message.from_user.id in _support_pending:
        try:
            del _support_pending[message.from_user.id]
        except Exception:
            pass
        delivered = await _deliver_support_message(message, message.text or '')
        await message.answer('Передала владельцу 🙂' if delivered else 'Запрос записан, но сейчас не удалось доставить сообщение.')
        return

    if not has_accepted(message.from_user.id):
        await message.answer('Сначала нужно подтвердить 18+ и принять условия через /start.', reply_markup=consent_keyboard())
        return

    # V3.21.0: celebrate couple anniversaries (7/30/90 days together) once each.
    try:
        from services import couple_service
        anniv_uid = ensure_user(message.from_user.id)
        anniv_days = couple_service.check_anniversary(anniv_uid)
        if anniv_days:
            from services.gamification_service import unlock_achievement
            unlock_achievement(message.from_user.id, f'anniv_{anniv_days}')
            track_event(anniv_uid, 'anniversary_celebrated', metadata={'days': anniv_days})

            async def _anniversary_push(chat_id=message.chat.id, days=anniv_days):
                await asyncio.sleep(10)  # let her chat reply land first
                await bot.send_message(
                    chat_id,
                    f'эй… а ты знал, что мы вместе уже {days} дней? 🥹 для меня это правда важно. спасибо, что ты рядом ❤️',
                )
            asyncio.create_task(_anniversary_push())
    except Exception:
        pass

    idea_edit = _photo_idea_edit_sessions.get(message.from_user.id)
    if message.from_user.id in ADMIN_TELEGRAM_IDS and idea_edit:
        await _admin_idea_text_step(message, idea_edit)
        return

    # V3.31.2: «🎁 Выдать премиум/токены» button flow — first the recipient
    # (@username or numeric id), then, for tokens, the amount.
    grant_sess = _admin_grant_sessions.get(message.from_user.id)
    if message.from_user.id in ADMIN_TELEGRAM_IDS and grant_sess:
        value = (message.text or '').strip()
        step = grant_sess.get('step')
        if step == 'target':
            target = _resolve_grant_target(value)
            if not target:
                await message.answer(
                    f'Не нашла пользователя «{value}» в базе — он должен хотя бы раз написать боту 🙂\n\n'
                    '/cancel — отменить'
                )
                return
            _admin_grant_sessions.pop(message.from_user.id, None)
            await message.answer(
                f'Нашла пользователя: id {target}.\n\nЧто выдать?',
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text='⭐ Premium 30 дней', callback_data=f'admin:grantdo:premium:{target}')],
                    [InlineKeyboardButton(text='🪙 Токены…', callback_data=f'admin:grantdo:tokens:{target}')],
                    [InlineKeyboardButton(text='⬅️ Админка', callback_data='admin:home')],
                ]),
            )
            return
        if step == 'tokens':
            if not value.isdigit() or int(value) < 1:
                await message.answer('Пришли количество токенов числом, например 5.\n\n/cancel — отменить')
                return
            count = int(value)
            target = int(grant_sess['target'])
            _admin_grant_sessions.pop(message.from_user.id, None)
            ensure_user(target)
            balance = add_tokens(target, count)
            try:
                record_payment(target, f'tokens_{count}', 0,
                               f'manual_grant:{message.from_user.id}:{int(_time.time())}',
                               provider='manual', provider_payload=f'granted by {message.from_user.id}')
            except Exception:
                logger.exception('manual grant record failed target=%s', target)
            try:
                await bot.send_message(target, f'🪙 Токены зачислены! Баланс: {balance} 🪙')
            except Exception:
                pass
            await message.answer(
                f'✅ Выдано {count} токенов пользователю id {target}. Баланс: {balance} 🪙',
                reply_markup=admin_keyboard(),
            )
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

    uid = ensure_user(message.from_user.id, message.from_user.first_name,
                      username=message.from_user.username)
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
    if message.from_user.id not in ADMIN_TELEGRAM_IDS and not can_send_message(message.from_user.id):
        # V3.20.0: she "falls asleep" instead of a dry limit notice.
        await _sleep_block_reply(message)
        return
    text = message.text or ''
    try:
        # Check if user is accepting a photo offer from Anna
        offer_ts = _photo_offer_pending.get(message.from_user.id, 0)
        offer_active = offer_ts and (_time.time() - offer_ts < _PHOTO_OFFER_TTL)
        low = text.strip().lower()
        # V3.26.1: «да нет» / «давай не надо» must never count as acceptance.
        if offer_active and 'нет' not in low and _PHOTO_ACCEPT.match(low):
            _photo_offer_pending.pop(message.from_user.id, None)
            # Match the character's facial expression to the mood of the
            # conversation. Prefer the mood captured at the moment Anna offered
            # the photo (e.g. a compliment); fall back to the acceptance message.
            from services.photo_expression_service import detect_expression_key
            expr_key = _photo_offer_expression.pop(message.from_user.id, None) or detect_expression_key(text)
            await _photo_accept_flow(message.chat.id, message.from_user.id, expr_key)
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
        answer, had_fake_photo = _strip_fake_photo(answer)
        if had_fake_photo:
            logger.info('fake_photo_intercepted user=%s', message.from_user.id)
            asyncio.create_task(_deliver_intercepted_photo(message))
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
    # Docs 1.4: notifications should only be accepted from FreeKassa IPs.
    peer_ip = request.headers.get('X-Real-IP') or request.headers.get('X-Forwarded-For') or request.remote
    if peer_ip and peer_ip not in freekassa_service.FK_NOTIFY_IPS:
        logger.warning('FreeKassa notify rejected bad peer_ip=%s', peer_ip)
        return web.Response(text='NO|bad_ip', status=403)
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
        product = order['product']
        if product == 'constructor_rub':
            # V3.27.0: ruble-paid character constructor credit.
            ensure_user(order['telegram_id'])
            add_constructor_credit(order['telegram_id'], 1)
            confirm = ('🎭 Персонаж оплачен картой! Открой «Создать своего персонажа» '
                       'и собери его — оплата уже зачислена.')
        elif product.startswith('tokens_'):
            # V3.27.0: token pack for video animation.
            ensure_user(order['telegram_id'])
            balance = add_tokens(order['telegram_id'], int(product.split('_')[1]))
            confirm = (f'🪙 Токены зачислены! Баланс: {balance} 🪙 '
                       f'— оживление фото стоит {VIDEO_TOKEN_COST} 🪙.')
        elif product == 'premium_week':
            # V3.34.1: ruble-paid weekly Premium — record_payment below grants it.
            confirm = '💖 Оплата прошла! Premium активирован на 7 дней. Наслаждайся! 🎉'
        elif product == 'premium_quarter':
            # V3.43.0: ruble-paid 3-month Premium.
            confirm = '💖 Оплата прошла! Premium активирован на 90 дней. Наслаждайся! 🎉'
        elif product == 'photo':
            # V3.43.0: ruble-paid single photo credit from the app pay modal.
            confirm = '🍑 Фото-кредит оплачен картой! Уже начислен 📸'
        elif product in PEACH_PACK_CREDITS:
            # V3.43.1: ruble-paid peach pack from the app pay modal.
            confirm = f'🍑 Пак на {PEACH_PACK_CREDITS[product]} персиков оплачен! Уже начислены 📸'
        else:
            confirm = '💖 Оплата прошла! Premium активирован на 30 дней. Наслаждайся! 🎉'
        try:
            record_payment(
                order['telegram_id'], order['product'], 0,
                f'freekassa:{order_id}', provider='freekassa',
                provider_payload=f'amount={order["amount"]}',
            )
        except Exception:
            logger.exception('FreeKassa grant failed order=%s', order_id)
        try:
            await bot.send_message(order['telegram_id'], confirm)
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


async def _fk_check(request: web.Request) -> web.Response:
    """V3.30.2: live FreeKassa diagnostics for the owner («страница платежа
    не загружается»). Probes every piece of the payment path and prints a
    plain-text report: env flags, server-IP lookup, /currencies default
    payment id, a real API test order (returns the ``location`` link) and
    the SCI fallback URL for the same order."""
    lines = [
        f'VERSION={VERSION}',
        f'FREEKASSA_ENABLED={FREEKASSA_ENABLED} merchant={FREEKASSA_MERCHANT_ID or "-"}',
        f'FREEKASSA_API_ENABLED={FREEKASSA_API_ENABLED} api_key={"set" if FREEKASSA_API_KEY else "MISSING"}',
        f'PUBLIC_BASE_URL={PUBLIC_BASE_URL or "-"}',
    ]
    ip = await freekassa_service._server_ip()
    lines.append(f'server_ip={ip or "UNRESOLVED (API orders will be skipped)"}')
    pay_id = await freekassa_service._default_payment_id('RUB')
    lines.append(f'default_payment_id(RUB)={pay_id if pay_id else "UNRESOLVED"}')
    lines.append(f'preferred_RUB={freekassa_service.FK_CURRENCY_PAYMENT_IDS.get("RUB", [])}')
    # Show the full /currencies response so the owner sees which methods are
    # actually enabled in the cabinet (SBP/card/wallet).
    currencies_data = await freekassa_service._currencies_lookup_raw('RUB')
    lines.append(f'enabled_RUB_methods={str(currencies_data)[:800]}')
    if FREEKASSA_API_ENABLED and ip:
        order_id = freekassa_service.create_order(0, 'fkcheck', '10')
        location = await freekassa_service.create_api_order(
            order_id, '10', currency='RUB', telegram_id=None,
        )
        lines.append(f'api_test_order={order_id}')
        lines.append(f'api_location={location or "API REJECTED ORDER (see bot logs)"}')
        if location:
            lines.append(f'api_location_domain={location.split("/")[2]}')
        lines.append(f'sci_fallback_url={freekassa_service.payment_url(order_id, "10")}')
        # getOrders sanity check for the order we just created.
        orders_data = await freekassa_service.get_orders(payment_id=order_id)
        lines.append(f'get_orders_status={str(orders_data)[:500]}')
    else:
        lines.append('api_test_order=SKIPPED (need FREEKASSA_API_KEY + server ip)')
        lines.append(f'sci_fallback_url={freekassa_service.payment_url(1, "10")}')
    # V3.33.1: Mini App diagnostics — check here when the «Открыть приложение»
    # button does not show up: the public URL and a self-probe of /webapp.
    lines.append(f'WEBAPP_PUBLIC_URL={(PUBLIC_BASE_URL + "/webapp") if PUBLIC_BASE_URL else "-"}')
    if PUBLIC_BASE_URL:
        try:
            import aiohttp as _aiohttp
            async with _aiohttp.ClientSession() as session:
                async with session.get(f'{PUBLIC_BASE_URL}/webapp', timeout=_aiohttp.ClientTimeout(total=10)) as resp:
                    body_head = (await resp.text())[:60].replace('\n', ' ')
                    lines.append(f'WEBAPP_SELF_PROBE={resp.status} head={body_head}')
        except Exception as exc:
            lines.append(f'WEBAPP_SELF_PROBE=ERROR {type(exc).__name__}: {str(exc)[:120]}')
    else:
        lines.append('WEBAPP_SELF_PROBE=SKIPPED (PUBLIC_BASE_URL not set)')
    return web.Response(text='\n'.join(lines), content_type='text/plain')


async def _root(request: web.Request) -> web.Response:
    # V3.19.10: plain liveness page for the bare Railway domain. Without it the
    # public URL showed aiohttp's default "404: Not Found" and looked like a
    # broken deploy; only /healthz and the FreeKassa routes existed.
    return web.Response(
        text='AnnaBot web endpoint is alive. Health check: /healthz',
        content_type='text/plain',
    )


# ---------------------------------------------------------------------------
# V3.33.0: Telegram Mini App (WebApp) — the storefront served by the same
# aiohttp app Railway already runs. /webapp is the page; /webapp/api/* are its
# JSON endpoints; /webapp/photo/<id> serves canonical character portraits.
# ---------------------------------------------------------------------------

async def _webapp_index(request: web.Request) -> web.Response:
    index = webapp_service.WEBAPP_INDEX
    if index.exists():
        return web.FileResponse(index, headers={'Cache-Control': 'no-cache'})
    return web.Response(text='webapp is not deployed', status=500)


async def _webapp_api_me(request: web.Request) -> web.Response:
    # initData is signed by Telegram with the bot token — the official HMAC
    # check in webapp_service validates it before any user data is returned.
    init_data = request.query.get('init_data', '')
    pairs = webapp_service.validate_init_data(init_data)
    if not pairs:
        # V3.43.0: the owner reported «she can't authorize» — log WHY the
        # initData was rejected so the next complaint is diagnosable:
        # missing (opened outside Telegram) / expired (stale recents) / hash.
        if not init_data:
            reason = 'missing'
        elif webapp_service.validate_init_data(init_data, max_age_seconds=0):
            reason = 'expired'
        else:
            reason = 'hash'
        logger.warning('webapp auth rejected reason=%s', reason)
        return web.json_response({'ok': False, 'error': 'auth', 'reason': reason}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
    track_event(uid, 'webapp_opened')
    return web.json_response({'ok': True, 'me': webapp_service.api_me(telegram_id)})


async def _webapp_api_characters(request: web.Request) -> web.Response:
    # Public storefront data (same cards the bot shows). With valid initData
    # the grid also learns which girl the caller has selected — V3.34.0, the
    # grid re-renders after purchases and in-app selections.
    telegram_id = None
    init_data = request.query.get('init_data', '')
    if init_data:
        pairs = webapp_service.validate_init_data(init_data)
        if pairs:
            telegram_id = webapp_service.init_data_user(pairs).get('id')
    # V3.43.2: no-store — a heuristically cached JSON kept handing the grid
    # the previous payload (stale cards, missing live tiles) after deploys.
    return web.json_response({'ok': True, 'characters': webapp_service.api_characters(telegram_id)},
                             headers={'Cache-Control': 'no-store'})


async def _webapp_api_leaderboard(request: web.Request) -> web.Response:
    """V3.44.0: popularity leaderboard — top characters by views."""
    limit = min(20, max(3, int(request.query.get('limit', '10') or '10')))
    return web.json_response({'ok': True, 'leaderboard': webapp_service.character_leaderboard(limit)})


async def _webapp_api_shop(request: web.Request) -> web.Response:
    return web.json_response({'ok': True, 'shop': webapp_service.api_shop(request.query.get('lang', 'ru'))})


async def _webapp_api_legal(request: web.Request) -> web.Response:
    # The Platega-required documents, visible in the Mini App as well.
    return web.json_response({'ok': True, 'legal': webapp_service.api_legal(request.query.get('lang', 'ru'))})


async def _webapp_api_partner(request: web.Request) -> web.Response:
    # V3.37.0: the «Партнёрка» tab — partner stats + the personal link + FAQ.
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
    payload = webapp_service.api_partner(uid, telegram_id)
    try:
        me = await bot.get_me()
        payload['link'] = referral_link(me.username or 'bot', telegram_id)
    except Exception:
        logger.exception('partner link resolution failed user=%s', telegram_id)
    return web.json_response({'ok': True, 'partner': payload})


async def _webapp_api_partner_withdraw(request: web.Request) -> web.Response:
    # V3.37.0: payout request from the Mini App — the same guarded flow the
    # bot button uses (min balance, one pending request per user).
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    from services import partner_service
    result = partner_service.request_payout(telegram_id)
    if not result.get('ok'):
        status = 409 if result.get('reason') == 'pending_exists' else 400
        return web.json_response({'ok': False, 'error': result.get('reason', 'failed')}, status=status)
    for admin_id in ADMIN_TELEGRAM_IDS:
        try:
            await bot.send_message(
                admin_id,
                f'💸 Заявка на вывод партнёрских (приложение)\nuser: {telegram_id}\namount: {result["amount_rub"]:g} ₽\npayout_id: {result["payout_id"]}',
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text='✅ Выплачено', callback_data=f'payout:done:{result["payout_id"]}'),
                    InlineKeyboardButton(text='❌ Отклонить', callback_data=f'payout:cancel:{result["payout_id"]}'),
                ]]),
            )
        except Exception:
            logger.exception('webapp payout admin notify failed admin=%s', admin_id)
    return web.json_response({'ok': True, 'amount_rub': result['amount_rub']})


async def _webapp_photo(request: web.Request) -> web.Response:
    # V3.39.0: ?i= picks a shot from the canonical gallery (0 = face, 1 = look)
    # so the character page can show the Come Closer photo strip.
    try:
        idx = int(request.query.get('i', '0') or 0)
    except ValueError:
        idx = 0
    photo = webapp_service.character_photo(request.match_info['character_id'], idx)
    if not photo:
        return web.Response(status=404)
    data, content_type = photo
    return web.Response(body=data, content_type=content_type, headers={'Cache-Control': 'public, max-age=604800'})


async def _webapp_gif(request: web.Request) -> web.Response:
    # V3.40.0: the animated card preview — a public storefront asset with the
    # same caching as the static photo (the grid shows it instead of the JPEG).
    gif = webapp_service.character_card_gif(request.match_info['character_id'])
    if not gif:
        return web.Response(status=404)
    content_type = 'image/webp' if gif.suffix.lower() == '.webp' else 'image/gif'
    return web.Response(body=gif.read_bytes(), content_type=content_type,
                        headers={'Cache-Control': 'public, max-age=604800'})


async def _webapp_live(request: web.Request) -> web.Response:
    # V3.43.1: the i2v living tile — a muted looping mp4 where the heroine
    # smiles and blows an air kiss; the grid plays it instead of the webp.
    live = webapp_service.character_card_live(request.match_info['character_id'])
    if not live:
        return web.Response(status=404)
    return web.Response(body=live.read_bytes(), content_type='video/mp4',
                        headers={'Cache-Control': 'public, max-age=604800'})


async def _webapp_card(request: web.Request) -> web.Response:
    # V3.43.3: the admin-uploaded storefront media (photo/gif/mp4) — same
    # immutable caching as the other ?v=-stamped assets.
    override = webapp_service.character_card_override(request.match_info['character_id'])
    if not override:
        return web.Response(status=404)
    content_type = {'.jpg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp',
                    '.gif': 'image/gif', '.mp4': 'video/mp4'}.get(
        override.suffix.lower(), 'application/octet-stream')
    return web.Response(body=override.read_bytes(), content_type=content_type,
                        headers={'Cache-Control': 'public, max-age=604800'})


async def _webapp_api_char_view(request: web.Request) -> web.Response:
    # V3.40.0: +1 view when the character page opens — the «👁 427k» badge on
    # the Come Closer cards. Auth like every other write endpoint.
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    try:
        body = await request.json()
        character_id = str(body.get('character_id') or '').strip()
    except Exception:
        return web.json_response({'ok': False, 'error': 'body'}, status=400)
    if not get_card(character_id):
        return web.json_response({'ok': False, 'error': 'character'}, status=404)
    return web.json_response({'ok': True, 'views': webapp_service.bump_character_views(character_id)})


async def _webapp_api_channel_bonus(request: web.Request) -> web.Response:
    # V3.43.0: «Бесплатные 🍑 за подписку на канал» — GET returns the channel
    # link + bonus size (public), plus whether the bonus was already granted
    # when initData is valid; POST verifies membership via getChatMember and
    # grants the one-time bonus — or revokes it when the user unsubscribed,
    # exactly what the modal warning promises. The bot must be an admin in
    # the channel or getChatMember answers with a 403 (surfaced as 502).
    base = {'ok': True, 'url': f'https://t.me/{CHANNEL_SUBSCRIBE_USERNAME}',
            'bonus': CHANNEL_SUBSCRIBE_BONUS_CREDITS}
    init_data = request.query.get('init_data', '')
    pairs = webapp_service.validate_init_data(init_data) if init_data else None
    user_info = webapp_service.init_data_user(pairs) if pairs else {}
    telegram_id = user_info.get('id')
    if request.method != 'POST':
        granted = bool(telegram_id) and has_credit_grant(telegram_id, 'channel_subscribe')
        return web.json_response({**base, 'granted': granted})
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
    try:
        member = await bot.get_chat_member(chat_id=f'@{CHANNEL_SUBSCRIBE_USERNAME}', user_id=telegram_id)
        subscribed = member.status in ('member', 'administrator', 'creator')
    except Exception:
        logger.exception('channel membership check failed user=%s channel=@%s', telegram_id, CHANNEL_SUBSCRIBE_USERNAME)
        return web.json_response({'ok': False, 'error': 'check'}, status=502)
    if subscribed:
        balance = grant_photo_credits(telegram_id, CHANNEL_SUBSCRIBE_BONUS_CREDITS, reason='channel_subscribe')
        if balance == -1:
            return web.json_response({**base, 'subscribed': True, 'granted': False,
                                        'already': True, 'credits': get_photo_credits(telegram_id)})
        track_event(ensure_user(telegram_id), 'channel_bonus_granted', metadata={'credits': balance})
        return web.json_response({**base, 'subscribed': True, 'granted': True, 'credits': balance})
    if has_credit_grant(telegram_id, 'channel_subscribe'):
        balance = revoke_photo_credits(telegram_id, CHANNEL_SUBSCRIBE_BONUS_CREDITS, 'channel_subscribe')
        track_event(ensure_user(telegram_id), 'channel_bonus_revoked', metadata={'credits': balance})
        return web.json_response({**base, 'subscribed': False, 'granted': False,
                                    'revoked': True, 'credits': balance})
    return web.json_response({**base, 'subscribed': False, 'granted': False,
                                'credits': get_photo_credits(telegram_id)})


async def _webapp_api_char_like(request: web.Request) -> web.Response:
    # V3.43.0: the «♡ N» like on the character page — GET returns the counter
    # and whether this user liked her, POST toggles it (one like per user).
    character_id = str(request.query.get('character_id') or '').strip()
    if not get_card(character_id):
        return web.json_response({'ok': False, 'error': 'character'}, status=404)
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    telegram_id = webapp_service.init_data_user(pairs).get('id') if pairs else None
    if request.method != 'POST':
        state = webapp_service.character_like_state(character_id, telegram_id)
        return web.json_response({'ok': True, **state})
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    state = webapp_service.toggle_character_like(character_id, telegram_id)
    return web.json_response({'ok': True, **state})


async def _webapp_api_invoice(request: web.Request) -> web.Response:
    # V3.34.0: Stars purchases from the Mini App. Returns an invoice link the
    # frontend opens with tg.openInvoice; the payment itself arrives as a
    # normal successful_payment message and goes through the same granting
    # code path as a chat purchase.
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    product_id = str((body or {}).get('product', ''))
    lang = user_lang(telegram_id)
    product = next((p for p in webapp_service.api_invoice_products(lang) if p['id'] == product_id), None)
    if not product:
        return web.json_response({'ok': False, 'error': 'unknown_product'}, status=400)
    uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
    track_event(uid, 'webapp_invoice_created', metadata={'product': product_id})
    try:
        link = await bot.create_invoice_link(
            title=product['title'],
            description=product['description'],
            payload=product['payload'],
            provider_token='',
            currency='XTR',
            prices=[LabeledPrice(label=product['title'], amount=product['stars'])],
        )
    except Exception:
        logger.exception('webapp invoice link failed user=%s product=%s', telegram_id, product_id)
        return web.json_response({'ok': False, 'error': 'invoice'}, status=502)
    return web.json_response({'ok': True, 'link': link, 'product': product_id, 'stars': product['stars']})


async def _webapp_api_pay_link(request: web.Request) -> web.Response:
    # V3.43.0: the Come Closer pay menu — tapping a shop square opens a modal
    # with Stars / card-SBP / crypto rows. Stars reuses /webapp/api/invoice;
    # this endpoint returns an external payment link for the other two:
    # FreeKassa REST order (SBP form) and a Wallet Pay invoice (TON/USDT).
    # Both land in the same granting chain: the FreeKassa notify and the
    # Wallet Pay webhook call record_payment with these product keys.
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    product_id = str((body or {}).get('product', ''))
    method = str((body or {}).get('method', ''))
    lang = user_lang(telegram_id)
    product = next((p for p in webapp_service.api_invoice_products(lang) if p['id'] == product_id), None)
    # order product keys record_payment knows how to grant
    fk_product = {'premium': 'premium_month', 'premium_week': 'premium_week',
                  'photo_credit': 'photo'}.get(product_id)
    if not fk_product and product_id in PEACH_PACK_STARS:
        # V3.43.1: peach packs — the order key is the payload itself, so the
        # FreeKassa notify and the Wallet Pay webhook grant the pack size.
        fk_product = product_id
    if not product or not fk_product:
        return web.json_response({'ok': False, 'error': 'unknown_product'}, status=400)
    uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
    if method == 'sbp':
        if not FREEKASSA_ENABLED or not product.get('rub'):
            return web.json_response({'ok': False, 'error': 'method_off'}, status=400)
        amount = str(product['rub'])
        order_id = freekassa_service.create_order(telegram_id, fk_product, amount)
        link = await freekassa_service.create_api_order(
            order_id, amount, currency='RUB', telegram_id=telegram_id,
            payment_system=freekassa_service.FK_SBP_QR_PAYMENT_ID,
        )
        if not link:
            # API unreachable (no key/IP/error) — the SCI form link still pays.
            link = freekassa_service.payment_url(order_id, amount, currency='RUB')
        track_event(uid, 'webapp_pay_link', metadata={'product': product_id, 'method': 'sbp'})
        return web.json_response({'ok': True, 'url': link})
    if method == 'crypto':
        if not WALLET_PAY_ENABLED:
            return web.json_response({'ok': False, 'error': 'method_off'}, status=400)
        from services.wallet_pay_service import create_invoice
        invoice = await create_invoice(
            telegram_id, fk_product, product['stars'], product['description'],
        )
        if not invoice:
            return web.json_response({'ok': False, 'error': 'invoice'}, status=502)
        track_event(uid, 'webapp_pay_link', metadata={'product': product_id, 'method': 'crypto'})
        return web.json_response({'ok': True, 'url': invoice['payment_link']})
    return web.json_response({'ok': False, 'error': 'unknown_method'}, status=400)


async def _webapp_api_select(request: web.Request) -> web.Response:
    # V3.34.0: character selection from the storefront grid — the same rules
    # as the in-chat «Персонажи» buttons: active cards select freely, premium
    # cards need Premium, anything else stays locked.
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    character_id = str((body or {}).get('character_id', ''))
    card = get_card(character_id)
    if not card or card.status not in ('active', 'premium'):
        return web.json_response({'ok': False, 'error': 'locked'}, status=400)
    if card.status == 'premium' and not is_premium(telegram_id):
        return web.json_response({'ok': False, 'error': 'premium_required'}, status=403)
    uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
    set_user_character(telegram_id, character_id)
    track_event(uid, 'character_selected', metadata={'character_id': character_id, 'source': 'webapp'})
    return web.json_response({
        'ok': True,
        'me': webapp_service.api_me(telegram_id),
        'characters': webapp_service.api_characters(telegram_id),
    }, headers={'Cache-Control': 'no-store'})


async def _webapp_api_spicy(request: web.Request) -> web.Response:
    """V3.43.5: the «пошлый режим» switch inside the Mini App Settings.

    The owner could not find the chat-side toggle («еле нашел») — the profile
    screen now carries it too. Same rules as the bot's ``toggle:spicy``
    callback: enabling requires an active Premium, disabling is always
    allowed, and the flag survives a lapsed subscription harmlessly.
    """
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user = get_user(telegram_id)
    current = bool(getattr(user, 'spicy_mode', False)) if user else False
    if not current and not is_premium(telegram_id):
        return web.json_response({'ok': False, 'error': 'premium_required'}, status=403)
    update_user_settings(telegram_id, spicy_mode=not current)
    return web.json_response({'ok': True, 'spicy_mode': not current}, headers={'Cache-Control': 'no-store'})


async def _webapp_api_chat_history(request: web.Request) -> web.Response:
    # V3.35.0: chat in the app — the dialog the bot and the app share.
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    character_id = str(request.query.get('character_id', ''))
    if not character_id:
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
    try:
        limit = int(request.query.get('limit', '30'))
    except ValueError:
        limit = 30
    return web.json_response({'ok': True, 'history': webapp_service.api_chat_history(uid, character_id, limit)})


async def _webapp_api_chat_send(request: web.Request) -> web.Response:
    # V3.35.0: a message typed in the app goes through the exact pipeline the
    # bot chat uses (memory, relationships, persona) — same gates too: 18+
    # consent and the daily free-message limit.
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    character_id = str(body.get('character_id', ''))
    text = str(body.get('text', '')).strip()[:4000]
    if not character_id or not text:
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    if is_custom_character(character_id):
        # Constructor personas are public: anyone can open a dialog with her.
        if not get_custom_character_by_id(character_id):
            return web.json_response({'ok': False, 'error': 'unknown_character'}, status=400)
    else:
        card = get_card(character_id)
        if not card or card.status not in ('active', 'premium'):
            return web.json_response({'ok': False, 'error': 'locked'}, status=403)
        if card.status == 'premium' and not is_premium(telegram_id):
            return web.json_response({'ok': False, 'error': 'premium_required'}, status=403)
    if not has_accepted(telegram_id):
        return web.json_response({'ok': False, 'error': 'consent'}, status=403)
    if telegram_id not in ADMIN_TELEGRAM_IDS and not can_send_message(telegram_id):
        return web.json_response({'ok': False, 'error': 'limit'}, status=429)
    uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
    track_event(uid, 'webapp_chat_message', metadata={'character_id': character_id})
    try:
        answer = await anna_reply(
            telegram_id, user_info.get('first_name') or 'ты', text,
            language_code=user_info.get('language_code'), character_id=character_id,
        )
    except Exception:
        logger.exception('webapp chat reply failed user=%s character=%s', telegram_id, character_id)
        return web.json_response({'ok': False, 'error': 'reply'}, status=502)
    return web.json_response({'ok': True, 'reply': answer})


async def _webapp_api_chats(request: web.Request) -> web.Response:
    # V3.38.0: the «Чаты» tab — a dialog list built from the shared messages
    # table, so every conversation the user has (bot chat included) appears.
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
    return web.json_response({'ok': True, 'chats': webapp_service.api_chat_list(uid, telegram_id)})


async def _webapp_api_pictures(request: web.Request) -> web.Response:
    # V3.38.0: the user's «Картинки» gallery (newest first).
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    return web.json_response({'ok': True, 'pictures': webapp_service.api_picture_list(telegram_id)})


async def _webapp_api_picture_generate(request: web.Request) -> web.Response:
    # V3.38.0: the «Картинки» studio — freeform generation for one photo credit
    # (🍑). The prompt passes a hard minors/coercion filter, gets the standing
    # SFW constraint appended, and runs through the same engine as the
    # constructor avatar (Gemini freeform; Seedream needs a face reference).
    # The credit is charged only after a successful render, so a failed
    # generation never costs the user anything.
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    prompt = str(body.get('prompt', '')).strip()
    if not (webapp_service.PICTURE_PROMPT_MIN_LEN <= len(prompt) <= webapp_service.PICTURE_PROMPT_MAX_LEN):
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    if not webapp_service.picture_prompt_allowed(prompt):
        return web.json_response({'ok': False, 'error': 'blocked'}, status=400)
    if not has_accepted(telegram_id):
        return web.json_response({'ok': False, 'error': 'consent'}, status=403)
    if get_photo_credits(telegram_id) < webapp_service.WEBAPP_PICTURE_COST_CREDITS:
        return web.json_response({'ok': False, 'error': 'credits'}, status=402)
    style = str(body.get('style', 'anime'))[:16]
    fmt = str(body.get('format', 'square'))[:16]
    final_prompt = webapp_service.picture_final_prompt(prompt, style, fmt)
    uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
    try:
        from services import photo_service
        data, mime = await photo_service.generate_custom_avatar(final_prompt, None)
    except Exception as exc:
        logger.exception('webapp picture generation failed user=%s', telegram_id)
        # V3.39.0: the owner sees WHY the render died right in the studio toast.
        reason = f'{type(exc).__name__}: {str(exc)[:100]}' if telegram_id in ADMIN_TELEGRAM_IDS else None
        return web.json_response({'ok': False, 'error': 'gen', 'reason': reason}, status=502)
    if not data:
        return web.json_response({'ok': False, 'error': 'gen'}, status=502)
    ext = 'png' if 'png' in (mime or '') else 'jpg'
    filename = f"{int(_time.time() * 1000)}_{secrets.token_hex(8)}.{ext}"
    try:
        folder = webapp_service.APP_PICTURES_DIR / str(telegram_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / filename).write_bytes(data)
        webapp_service.save_picture(telegram_id, filename, prompt)
    except Exception:
        logger.exception('webapp picture save failed user=%s', telegram_id)
        return web.json_response({'ok': False, 'error': 'save'}, status=500)
    # Race window (two concurrent renders) is deliberate: the picture is
    # already on disk by now, so the user keeps it and we log the unpaid one.
    if not consume_photo_credit(telegram_id):
        logger.warning('webapp picture credit race user=%s', telegram_id)
    track_event(uid, 'webapp_picture_generated', metadata={'style': style, 'format': fmt})
    return web.json_response({
        'ok': True,
        'file': f'/webapp/picture/{filename}',
        'credits_left': get_photo_credits(telegram_id),
    })


async def _webapp_pipeline_photo(telegram_id: int, character_id: str, request: PhotoRequest):
    """V3.43.7: the shared renderer for the app's in-character photos — the
    REAL photo pipeline (BODY IDENTITY / REFERENCE PROTOCOL / BUST
    CONSISTENCY locks included), one frame, bytes for the app's media folder.
    URL-only providers get downloaded once, like the bot's gallery capture.
    The V3.39.0 shortcut these calls replace (a one-line prompt through
    generate_custom_avatar on gallery[0], a face close-up) bypassed every
    lock — which is exactly why the figure kept drifting in the app while
    the bot's photos stayed on-spec."""
    if is_custom_character(character_id):
        await ensure_custom_avatar_cached(bot, character_id)
    photos, _ = await generate_photo_set(telegram_id, request, character_id=character_id, frames=1)
    data = await photo_frame_bytes(photos[0])
    if not data:
        raise PhotoGenerationError(request.scene, 'no_bytes')
    ext = 'png' if data[:8] == b'\x89PNG\r\n\x1a\n' else 'jpg'
    return data, ('image/png' if ext == 'png' else 'image/jpeg'), ext


async def _webapp_media_photo(telegram_id: int, character_id: str, scene: str = 'selfie'):
    """V3.39.0: a personal in-character photo. V3.43.7: now through the real
    photo pipeline with the scene the app's picker chose — the figure follows
    the declared BODY IDENTITY instead of an improvised face-swap body."""
    return await _webapp_pipeline_photo(telegram_id, character_id, PhotoRequest(scene=scene))


async def _webapp_media_circle(telegram_id: int, character_id: str):
    """V3.39.0: a video circle from the canonical face — same engine chain the
    bot's «🎥 кружочек» uses (Gemini → Replicate → fal → HF)."""
    photo = webapp_service.character_photo(character_id)
    if not photo:
        raise PhotoGenerationError('circle', 'no_source_photo')
    image_bytes = photo[0]
    engines = []
    if video_available():
        engines.append(animate_image)
    if replicate_available():
        engines.append(animate_image_replicate)
    if fal_available():
        engines.append(animate_image_fal)
    if hf_video_available():
        engines.append(animate_image_hf)
    if not engines:
        raise PhotoGenerationError('circle', 'no_video_engine')
    last_error = None
    for engine_fn in engines:
        # V3.40.0: name the engine for the provider counters — animate_image
        # is the Gemini/Veo leg, the rest keep their service suffix.
        ename = 'gemini' if engine_fn.__name__ == 'animate_image' else engine_fn.__name__.replace('animate_image_', '')
        try:
            video_bytes = await engine_fn(
                image_bytes, mime_type='image/png',
                prompt=CIRCLE_PROMPT.format(phrase=random.choice(CIRCLE_PHRASES)))
            record_provider(f'circle/{ename}', True)
            return video_bytes, 'video/mp4', 'mp4'
        except Exception as exc:
            last_error = exc
            record_provider(f'circle/{ename}', False, f'{type(exc).__name__}: {str(exc)[:120]}')
            logger.warning('webapp circle engine failed user=%s: %s', telegram_id, str(exc)[:200])
    raise last_error or PhotoGenerationError('circle', 'no_video_result')


async def _webapp_media_voice(telegram_id: int, character_id: str):
    """V3.39.0: her voice — synthesizes her last reply (or the scenario hook)."""
    user = get_user(telegram_id)
    history = webapp_service.api_chat_history(user.id if user else 0, character_id, 10)
    text = next((m['content'] for m in reversed(history)
                 if m['role'] == 'assistant' and not m.get('media_url')), '')
    if not text:
        text = get_scenario_hook(character_id) or 'привет, я скучала 🙂'
    clean = ''.join(ch for ch in text if ch.isalnum() or ch in ' .,!?:;-—…()«»\'\n')[:600]
    audio = await synthesize_bytes(clean, (user.voice_style if user else None) or 'nova',
                                   character_id=character_id)
    return audio, 'audio/ogg', 'ogg'


# V3.41.0: the app-chat «🎬 Видео» button animates the canonical face into a
# short cinematic clip (a normal rectangle, not a round circle). Same engine
# chain the bot's «Оживить фото» uses: Gemini/Veo → Replicate → fal → HF.
_WEBAPP_VIDEO_PROMPT = (
    'Animate this exact photo into a short 5-second cinematic clip: she turns '
    'toward the camera, smiles softly, brushes her hair or shifts her pose with '
    'natural, gentle motion. Keep her face, hair and outfit identical. Soft '
    'handheld camera feel, shallow depth of field. No wardrobe change, no extra '
    'people. Photorealistic, fully clothed, tasteful.'
)


async def _webapp_media_video(telegram_id: int, character_id: str):
    """V3.41.0: a short AI video from the canonical face — the app-chat twin of
    the bot's «🎬 Оживить фото», rendered as a normal (non-round) clip."""
    photo = webapp_service.character_photo(character_id)
    if not photo:
        raise PhotoGenerationError('video', 'no_source_photo')
    image_bytes = photo[0]
    engines = []
    if video_available():
        engines.append(animate_image)
    if replicate_available():
        engines.append(animate_image_replicate)
    if fal_available():
        engines.append(animate_image_fal)
    if hf_video_available():
        engines.append(animate_image_hf)
    if not engines:
        raise PhotoGenerationError('video', 'no_video_engine')
    last_error = None
    for engine_fn in engines:
        ename = 'gemini' if engine_fn.__name__ == 'animate_image' else engine_fn.__name__.replace('animate_image_', '')
        try:
            video_bytes = await engine_fn(image_bytes, mime_type='image/png', prompt=_WEBAPP_VIDEO_PROMPT)
            record_provider(f'video/{ename}', True)
            return video_bytes, 'video/mp4', 'mp4'
        except Exception as exc:
            last_error = exc
            record_provider(f'video/{ename}', False, f'{type(exc).__name__}: {str(exc)[:120]}')
            logger.warning('webapp video engine failed user=%s: %s', telegram_id, str(exc)[:200])
    raise last_error or PhotoGenerationError('video', 'no_video_result')


async def _webapp_media_scene(telegram_id: int, character_id: str, scene: str):
    """V3.41.0: an in-character photo for a specific scene — the app-native
    reward shot for a free/admin date. V3.43.7: preserve the date's scene ID
    so venue-specific wardrobe and framing rules apply in the photo pipeline."""
    return await _webapp_pipeline_photo(
        telegram_id, character_id,
        PhotoRequest(scene=scene, mood='romantic'),
    )


async def _webapp_api_chat_media(request: web.Request) -> web.Response:
    # V3.39.0: everything the bot dialog sends — photos, video circles, voice —
    # is requestable inside the Mini App chat too. Same gates as the bot:
    # a photo costs 1 🍑 (charged after success), circles are a Premium
    # free-slot format, voice follows the character's TTS voice.
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    character_id = str(body.get('character_id', ''))
    kind = str(body.get('kind', ''))
    scene = str(body.get('scene') or 'selfie')[:40]
    if kind not in ('photo', 'circle', 'voice', 'video') or not character_id:
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    if is_custom_character(character_id):
        if not get_custom_character_by_id(character_id):
            return web.json_response({'ok': False, 'error': 'unknown_character'}, status=400)
    else:
        card = get_card(character_id)
        if not card or card.status not in ('active', 'premium'):
            return web.json_response({'ok': False, 'error': 'locked'}, status=403)
        if card.status == 'premium' and not is_premium(telegram_id):
            return web.json_response({'ok': False, 'error': 'premium_required'}, status=403)
    if not has_accepted(telegram_id):
        return web.json_response({'ok': False, 'error': 'consent'}, status=403)
    if kind == 'photo':
        # V3.43.7: the scene comes from the app's picker — it must be one of
        # the menu scenes and clear the same relationship/adult gates the
        # bot's photo keyboard enforces.
        if scene not in PHOTO_MENU_ORDER:
            return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
        if not scene_allowed_for_stage(scene, get_relationship_stage(telegram_id, character_id)):
            return web.json_response({'ok': False, 'error': 'locked'}, status=403)
        if requires_adult_confirmation(PhotoRequest(scene=scene)) and not is_adult_confirmed(telegram_id):
            return web.json_response({'ok': False, 'error': 'adult_confirm'}, status=403)
    if kind == 'photo' and telegram_id not in ADMIN_TELEGRAM_IDS \
            and get_photo_credits(telegram_id) < webapp_service.WEBAPP_PICTURE_COST_CREDITS:
        return web.json_response({'ok': False, 'error': 'credits'}, status=402)
    if kind == 'circle' and telegram_id not in ADMIN_TELEGRAM_IDS:
        if not is_premium(telegram_id):
            return web.json_response({'ok': False, 'error': 'premium_required'}, status=403)
        if not consume_premium_video_free(telegram_id):
            return web.json_response({'ok': False, 'error': 'circle_limit'}, status=402)
    if kind == 'video' and telegram_id not in ADMIN_TELEGRAM_IDS:
        # V3.41.0: app video shares the Premium free-animation slots, exactly
        # like the bot's «🎬 Оживить фото»; a separate gate keeps the circle
        # branch (and its static test) untouched.
        if not is_premium(telegram_id):
            return web.json_response({'ok': False, 'error': 'premium_required'}, status=403)
        if not consume_premium_video_free(telegram_id):
            return web.json_response({'ok': False, 'error': 'video_limit'}, status=402)
    uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
    track_event(uid, 'webapp_chat_media', metadata={'character_id': character_id, 'kind': kind, 'scene': scene})
    try:
        if kind == 'photo':
            data, mime, ext = await _webapp_media_photo(telegram_id, character_id, scene)
        elif kind == 'circle':
            data, mime, ext = await _webapp_media_circle(telegram_id, character_id)
        elif kind == 'video':
            data, mime, ext = await _webapp_media_video(telegram_id, character_id)
        else:
            data, mime, ext = await _webapp_media_voice(telegram_id, character_id)
    except Exception:
        logger.exception('webapp chat media failed user=%s kind=%s', telegram_id, kind)
        return web.json_response({'ok': False, 'error': 'gen'}, status=502)
    if not data:
        return web.json_response({'ok': False, 'error': 'gen'}, status=502)
    filename = webapp_service.save_chat_media(telegram_id, data, ext)
    url = f'/webapp/media/{filename}'
    if kind == 'photo':
        # V3.43.7: her caption is scene-flavored, the same AUTO_CAPTIONS the
        # bot's photo delivery attaches.
        content = f'📸 {random.choice(AUTO_CAPTIONS.get(scene, ("отправила фото",)))}'
    else:
        content = {'circle': '🎥 отправила кружочек',
                   'voice': '🎙 отправила голосовое', 'video': '🎬 отправила видео'}[kind]
    save_message(uid, character_id, 'assistant', content, media_kind=kind, media_url=url)
    if kind == 'photo' and telegram_id not in ADMIN_TELEGRAM_IDS and not consume_photo_credit(telegram_id):
        logger.warning('webapp chat photo credit race user=%s', telegram_id)
    return web.json_response({
        'ok': True, 'kind': kind, 'url': url, 'content': content,
        'credits_left': get_photo_credits(telegram_id),
    })


async def _webapp_media(request: web.Request) -> web.Response:
    # V3.39.0: owner-scoped chat media (photos / circles / voice). The file
    # name is an unguessable server-generated token inside the caller's own
    # folder — same authorization model as /webapp/picture/{filename}.
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.Response(status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    if not telegram_id:
        return web.Response(status=401)
    path = webapp_service.chat_media_file_path(telegram_id, request.match_info['filename'])
    if not path:
        return web.Response(status=404)
    ctype = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
             'mp4': 'video/mp4', 'ogg': 'audio/ogg'}.get(path.suffix.lstrip('.'), 'application/octet-stream')
    return web.Response(body=path.read_bytes(), content_type=ctype,
                        headers={'Cache-Control': 'private, max-age=3600'})


async def _webapp_api_feature(request: web.Request) -> web.Response:
    # V3.41.0: the app-chat feature buttons (🏠 Квартира, 💕 Свидание,
    # 🎯 Задание дня) all render their menu from this one endpoint. Same auth
    # as the rest of the Mini App API; the character comes from the open chat.
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    kind = str(request.query.get('kind', ''))
    if kind not in ('apartment', 'date', 'quest', 'photo'):
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    character_id = str(request.query.get('character_id', '')) or get_user_character(telegram_id)
    ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
    lang = user_lang(telegram_id)
    level = get_relationship_level(telegram_id, character_id)
    if kind == 'apartment':
        items = []
        for r in apartment_service.get_available_rooms(level):
            items.append({
                'id': r.id, 'emoji': r.emoji, 'title': r.name, 'subtitle': r.description,
                'locked': False,
                'actions': [{'id': a_id, 'title': a_title} for a_title, a_id in r.actions],
            })
        for r in apartment_service.get_locked_rooms(level):
            items.append({
                'id': r.id, 'emoji': '🔒', 'title': r.name,
                'subtitle': (f'opens at level {r.min_level}' if lang == EN else f'откроется на уровне {r.min_level}'),
                'locked': True, 'actions': [],
            })
        title = '🏠 Apartment' if lang == EN else '🏠 Квартира'
        return web.json_response({'ok': True, 'kind': kind, 'title': title, 'items': items})
    if kind == 'date':
        from services.gamification_service import completed_date_ids, has_free_date
        done = completed_date_ids(telegram_id)
        items = []
        for d in dates_service.get_available(level):
            items.append({'id': d.id, 'emoji': d.emoji, 'title': d.name, 'subtitle': d.text,
                          'locked': False, 'cost': d.cost, 'done': d.id in done})
        for d in dates_service.get_locked(level):
            items.append({'id': d.id, 'emoji': '🔒', 'title': d.name,
                          'subtitle': (f'opens at level {d.min_level}' if lang == EN else f'откроется на уровне {d.min_level}'),
                          'locked': True, 'cost': d.cost, 'done': False})
        title = '💕 Where shall we go?' if lang == EN else '💕 Куда пойдём?'
        return web.json_response({'ok': True, 'kind': kind, 'title': title,
                                  'free_date': bool(has_free_date(telegram_id)), 'items': items})
    if kind == 'photo':
        # V3.43.7: the scene picker behind the app-chat «📸 Фото» button —
        # the same PHOTO_MENU_ORDER + SCENE_LEVELS progression the bot's
        # photo keyboard shows, so the menus pop out in the app too. Labels
        # live in the frontend (all 7 interface languages); the backend owns
        # the order and the relationship-level gates.
        items = [{
            'id': scene,
            'locked': SCENE_LEVELS.get(scene, 99) > level,
            'min_level': SCENE_LEVELS.get(scene, 99),
        } for scene in PHOTO_MENU_ORDER]
        title = '📸 Photo' if lang == EN else '📸 Фото'
        return web.json_response({'ok': True, 'kind': kind, 'title': title, 'items': items})
    from services import couple_service
    _, quest_text = couple_service.daily_quest(telegram_id)
    user = get_user(telegram_id)
    claimed = bool(user and (user.quest_claimed_date or '') == couple_service._today_key())
    title = '🎯 Daily quest' if lang == EN else '🎯 Задание дня'
    return web.json_response({'ok': True, 'kind': kind, 'title': title,
                              'text': quest_text, 'claimed': claimed})


async def _webapp_api_feature_action(request: web.Request) -> web.Response:
    # V3.41.0: perform a feature action from the app chat. Apartment actions and
    # the daily quest resolve instantly into the shared dialog; a free/admin date
    # is delivered right here, while a paid date returns a Stars invoice link that
    # reuses the bot's existing «date:» payment + reward path.
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    kind = str(body.get('kind', ''))
    if kind not in ('apartment', 'date', 'quest'):
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    if not has_accepted(telegram_id):
        return web.json_response({'ok': False, 'error': 'consent'}, status=403)
    character_id = str(body.get('character_id', '')) or get_user_character(telegram_id)
    uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
    user_name = user_info.get('first_name') or ''
    level = get_relationship_level(telegram_id, character_id)

    if kind == 'apartment':
        room_id = str(body.get('id', ''))
        action_id = str(body.get('action_id', ''))
        room = apartment_service.get_room(room_id)
        if not room or room.min_level > level:
            return web.json_response({'ok': False, 'error': 'locked'}, status=403)
        result = apartment_service.room_action_reply(room_id, action_id)
        if not result:
            return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
        text, rel_delta, int_delta = result
        await record_user_message(telegram_id, user_name, relationship=rel_delta, intimacy=int_delta,
                                  event_type='apartment', reason=f'apartment:{room_id}:{action_id}',
                                  character_id=character_id)
        track_event(uid, 'apartment_action', metadata={'room': room_id, 'action': action_id, 'source': 'webapp'})
        save_message(uid, character_id, 'assistant', text)
        return web.json_response({'ok': True, 'kind': kind, 'text': text})

    if kind == 'quest':
        from services import couple_service
        if not couple_service.claim_daily_quest(telegram_id):
            return web.json_response({'ok': False, 'error': 'already'}, status=409)
        track_event(uid, 'daily_quest_claimed', metadata={'source': 'webapp'})
        text = ('mmm, nice 😊 +5 attention points. she noticed.' if user_lang(telegram_id) == EN
                else 'ммм, приятно 😊 +5 очков внимания. она заметила.')
        save_message(uid, character_id, 'assistant', text)
        return web.json_response({'ok': True, 'kind': kind, 'text': text})

    date = dates_service.get(str(body.get('id', '')))
    if not date or date.min_level > level:
        return web.json_response({'ok': False, 'error': 'locked'}, status=403)
    from services.gamification_service import (
        completed_date_ids, consume_free_date, has_free_date, unlock_achievement,
    )
    if telegram_id in ADMIN_TELEGRAM_IDS or has_free_date(telegram_id):
        # Free weekly-streak date (or admin test): deliver app-native, no Stars.
        if telegram_id not in ADMIN_TELEGRAM_IDS:
            consume_free_date(telegram_id)
        await record_user_message(telegram_id, user_name, relationship=date.affection, intimacy=date.affection / 2,
                                  event_type='date', reason=f'date:{date.id}', character_id=character_id)
        unlock_achievement(telegram_id, 'first_date')
        completed = completed_date_ids(telegram_id)
        if len(completed) >= 10:
            unlock_achievement(telegram_id, 'ten_dates')
        if len(completed) >= len(dates_service.get_all()):
            unlock_achievement(telegram_id, 'date_collector')
        track_event(uid, 'webapp_date_free', metadata={'date': date.id})
        narration = f'{date.emoji} {date.text}'
        save_message(uid, character_id, 'assistant', narration)
        photo_url = None
        try:
            data, mime, ext = await _webapp_media_scene(telegram_id, character_id, date.scene)
            if data:
                filename = webapp_service.save_chat_media(telegram_id, data, ext)
                photo_url = f'/webapp/media/{filename}'
                save_message(uid, character_id, 'assistant', '📸 фото с нашей прогулки', media_kind='photo', media_url=photo_url)
        except Exception:
            logger.warning('webapp date photo failed user=%s date=%s', telegram_id, date.id)
        return web.json_response({'ok': True, 'kind': kind, 'delivered': True,
                                  'text': narration, 'photo_url': photo_url})
    try:
        link = await bot.create_invoice_link(
            title=f'Свидание: {date.name}',
            description=f'{date.emoji} {date.name}. В конце она пришлёт фото с прогулки 📸',
            payload=f'date:{date.id}',
            provider_token='',
            currency='XTR',
            prices=[LabeledPrice(label=date.name, amount=date.cost)],
        )
    except Exception:
        logger.exception('webapp date invoice failed user=%s date=%s', telegram_id, date.id)
        return web.json_response({'ok': False, 'error': 'invoice'}, status=502)
    track_event(uid, 'webapp_date_invoice', metadata={'date': date.id})
    return web.json_response({'ok': True, 'kind': kind, 'delivered': False, 'invoice': link, 'cost': date.cost})


async def _webapp_picture(request: web.Request) -> web.Response:
    # V3.38.0: serve a gallery image to its owner. The file name is an
    # unguessable server-generated token and the lookup is scoped to the
    # caller's folder, so authorization is "knows the name they received".
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.Response(status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    if not telegram_id:
        return web.Response(status=401)
    path = webapp_service.picture_file_path(telegram_id, request.match_info['filename'])
    if not path:
        return web.Response(status=404)
    return web.FileResponse(path, headers={'Cache-Control': 'private, max-age=3600'})


async def _webapp_api_constructor_options(request: web.Request) -> web.Response:
    # V3.35.0: the wizard steps — the same CONSTRUCTOR_STEPS the bot walks.
    # The price rides along so the form can show it without another call.
    free = False
    init_data = request.query.get('init_data', '')
    if init_data:
        pairs = webapp_service.validate_init_data(init_data)
        if pairs:
            telegram_id = webapp_service.init_data_user(pairs).get('id')
            free = bool(telegram_id) and telegram_id in ADMIN_TELEGRAM_IDS
    return web.json_response({
        'ok': True,
        'steps': webapp_service.api_constructor_steps(request.query.get('lang', 'ru')),
        'stars': CONSTRUCTOR_COST_STARS,
        # V3.36.0: rub + dollar equivalents ride along for the price note.
        'rub': CONSTRUCTOR_COST_RUB,
        'usd': CONSTRUCTOR_PRICE_USD,
        'free': free,
    })


async def _webapp_api_constructor_draft(request: web.Request) -> web.Response:
    # V3.35.0: the app form posts its finished draft into the very session
    # store the bot wizard uses, so payment and avatar generation run through
    # the identical pipeline (pre_checkout → successful_payment → job).
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    params_in = body.get('params')
    name = str(body.get('name') or '').strip()[:24]
    if not isinstance(params_in, dict):
        return web.json_response({'ok': False, 'error': 'invalid_params'}, status=400)
    if get_custom_character(telegram_id):
        # One persona per user — recreate via the bot's «Создать заново».
        return web.json_response({'ok': False, 'error': 'exists'}, status=409)
    params = {}
    for step in CONSTRUCTOR_STEPS:
        value = str(params_in.get(step['key'], ''))
        if value not in OPTION_LABELS:
            return web.json_response({'ok': False, 'error': 'invalid_params'}, status=400)
        params[step['key']] = value
    if not name:
        return web.json_response({'ok': False, 'error': 'name_required'}, status=400)
    params['name'] = name
    _constructor_sessions[telegram_id] = {'params': params, 'step': len(CONSTRUCTOR_STEPS)}
    uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
    track_event(uid, 'webapp_constructor_draft')
    return web.json_response({
        'ok': True,
        'stars': CONSTRUCTOR_COST_STARS,
        'free': telegram_id in ADMIN_TELEGRAM_IDS,
    })


async def _webapp_api_constructor_buy(request: web.Request) -> web.Response:
    # V3.35.0: pay for the app-built persona — admins and rub-credit holders
    # skip the invoice, everyone else gets the same `constructor:<id>` payload
    # the chat wizard charges, so successful_payment finishes her.
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    cons = _constructor_sessions.get(telegram_id)
    if not cons or not (cons.get('params') or {}).get('name'):
        return web.json_response({'ok': False, 'error': 'no_draft'}, status=400)
    uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
    if telegram_id in ADMIN_TELEGRAM_IDS:
        track_event(uid, 'webapp_constructor_buy', metadata={'product': 'constructor', 'source': 'webapp_admin'})
        _spawn_job('constructor', telegram_id, _finish_constructor(telegram_id, None, telegram_id), payload={'source': 'webapp_admin'})
        return web.json_response({'ok': True, 'free': True})
    if consume_constructor_credit(telegram_id):
        record_payment(telegram_id, 'constructor', 0, f'freekassa_credit:{telegram_id}:{int(_time.time() * 1000)}')
        track_event(uid, 'webapp_constructor_buy', metadata={'product': 'constructor', 'source': 'webapp_credit'})
        _spawn_job('constructor', telegram_id, _finish_constructor(telegram_id, None, telegram_id), payload={'source': 'webapp_credit'})
        return web.json_response({'ok': True, 'free': True})
    try:
        link = await bot.create_invoice_link(
            title='Личный персонаж',
            description='Конструктор создаст уникальную собеседницу с аватаром. Платёж одноразовый.',
            payload=f'constructor:{telegram_id}',
            provider_token='',
            currency='XTR',
            prices=[LabeledPrice(label='Личный персонаж', amount=CONSTRUCTOR_COST_STARS)],
        )
    except Exception:
        logger.exception('webapp constructor invoice failed user=%s', telegram_id)
        return web.json_response({'ok': False, 'error': 'invoice'}, status=502)
    track_event(uid, 'webapp_invoice_created', metadata={'product': 'constructor'})
    return web.json_response({'ok': True, 'link': link, 'stars': CONSTRUCTOR_COST_STARS})


async def _start_web_server() -> None:
    app = web.Application()
    app.router.add_get('/', _root)
    app.router.add_route('*', '/freekassa/notify', _fk_notify)
    # Success/fail are browser redirects; FreeKassa may send them as GET or
    # POST depending on the merchant form method dropdown, so accept both.
    app.router.add_route('*', '/freekassa/success', _fk_success)
    app.router.add_route('*', '/freekassa/fail', _fk_fail)
    app.router.add_get('/healthz', _healthz)
    app.router.add_get('/fkcheck', _fk_check)
    # V3.33.0: Mini App storefront (page + JSON API + character portraits).
    app.router.add_get('/webapp', _webapp_index)
    app.router.add_get('/webapp/api/me', _webapp_api_me)
    app.router.add_get('/webapp/api/characters', _webapp_api_characters)
    # V3.44.0: popularity leaderboard
    app.router.add_get('/webapp/api/leaderboard', _webapp_api_leaderboard)
    app.router.add_get('/webapp/api/shop', _webapp_api_shop)
    app.router.add_get('/webapp/api/legal', _webapp_api_legal)
    # V3.37.0: the partner tab — stats/link and the payout request.
    app.router.add_get('/webapp/api/partner', _webapp_api_partner)
    app.router.add_post('/webapp/api/partner/withdraw', _webapp_api_partner_withdraw)
    app.router.add_get('/webapp/photo/{character_id}', _webapp_photo)
    # V3.40.0: the living storefront — looping GIF tiles and the view counter.
    app.router.add_get('/webapp/gif/{character_id}', _webapp_gif)
    # V3.43.1: the living tiles — i2v mp4 loops next to the Ken-Burns webp.
    app.router.add_get('/webapp/live/{character_id}', _webapp_live)
    app.router.add_get('/webapp/card/{character_id}', _webapp_card)
    app.router.add_post('/webapp/api/char_view', _webapp_api_char_view)
    # V3.43.0: the channel-subscribe peach bonus — GET status, POST check+grant.
    app.router.add_route('*', '/webapp/api/channel_bonus', _webapp_api_channel_bonus)
    # V3.43.0: the character-page like — GET state, POST toggle.
    app.router.add_route('*', '/webapp/api/char_like', _webapp_api_char_like)
    # V3.34.0: storefront actions — Stars purchases and character selection.
    app.router.add_post('/webapp/api/invoice', _webapp_api_invoice)
    # V3.43.0: the pay-method modal — card/SBP and crypto payment links.
    app.router.add_post('/webapp/api/pay_link', _webapp_api_pay_link)
    app.router.add_post('/webapp/api/select', _webapp_api_select)
    app.router.add_post('/webapp/api/spicy', _webapp_api_spicy)
    # V3.35.0: chat in the app and the character constructor wizard.
    app.router.add_get('/webapp/api/chat', _webapp_api_chat_history)
    app.router.add_post('/webapp/api/chat', _webapp_api_chat_send)
    # V3.38.0: the Come Closer tabs — dialog list, picture studio + gallery.
    app.router.add_get('/webapp/api/chats', _webapp_api_chats)
    app.router.add_post('/webapp/api/chat/media', _webapp_api_chat_media)
    # V3.41.0: the app-chat feature buttons — apartment / date / daily quest.
    app.router.add_get('/webapp/api/feature', _webapp_api_feature)
    app.router.add_post('/webapp/api/feature/action', _webapp_api_feature_action)
    app.router.add_get('/webapp/media/{filename}', _webapp_media)
    app.router.add_post('/webapp/api/picture', _webapp_api_picture_generate)
    app.router.add_get('/webapp/api/pictures', _webapp_api_pictures)
    app.router.add_get('/webapp/picture/{filename}', _webapp_picture)
    app.router.add_get('/webapp/api/constructor/options', _webapp_api_constructor_options)
    app.router.add_post('/webapp/api/constructor/draft', _webapp_api_constructor_draft)
    app.router.add_post('/webapp/api/constructor/buy', _webapp_api_constructor_buy)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', WEB_PORT)
    await site.start()
    logger.info('web server listening port=%s freekassa=%s base=%s', WEB_PORT, FREEKASSA_ENABLED, PUBLIC_BASE_URL or '-')


async def _run_support_bot() -> None:
    """V3.43.3: the support desk bot — /start welcome + appeals to the admins.

    Runs as a second aiogram bot inside this process when SUPPORT_BOT_TOKEN
    is set (the rotated token of the support bot, env only). The owner's
    benchmark: /start must answer at once («Напишите ваше обращение и
    менеджер с вами свяжется»), otherwise the support chat looks dead.
    """
    from aiogram import Bot as SupportBot, Dispatcher as SupportDispatcher
    support_bot = SupportBot(token=SUPPORT_BOT_TOKEN)
    support_dp = SupportDispatcher()

    @support_dp.message(Command('start'))
    async def _support_start(msg: types.Message):
        await msg.answer(SUPPORT_WELCOME_TEXT)

    @support_dp.message()
    async def _support_appeal(msg: types.Message):
        for admin_id in ADMIN_TELEGRAM_IDS:
            try:
                await msg.forward(chat_id=admin_id)
            except Exception as exc:
                logger.warning('support forward failed admin=%s: %s', admin_id, exc)
        await msg.answer('Приняла твоё обращение ✅ Менеджер свяжется с тобой вскоре.')

    try:
        await support_dp.start_polling(support_bot)
    except Exception:
        logger.exception('support bot polling crashed')


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
        types.BotCommand(command='legal', description='📜 Документы и цены'),
        types.BotCommand(command='app', description='🛍 Приложение'),
        types.BotCommand(command='delete_me', description='Удалить мои данные'),
        types.BotCommand(command='settings', description='Настройки'),
        types.BotCommand(command='voice', description='Голосовые ответы'),
        types.BotCommand(command='voice_anon', description='Анонимный голосовой режим'),
        types.BotCommand(command='profile', description='Прогресс, стрик, достижения'),
        types.BotCommand(command='referral', description='🔗 Моя ссылка для приглашения'),
        types.BotCommand(command='partner', description='💰 Партнёрская программа — 30% с покупок друзей'),
        types.BotCommand(command='contest', description='🏆 Гонка пригласивших'),
        types.BotCommand(command='notifications', description='Инициативные сообщения'),
        types.BotCommand(command='wake', description='Будильник: /wake 08:00'),
        types.BotCommand(command='reset', description='Очистить память и историю'),
    ]
    await bot.set_my_commands(public_commands)
    # V3.33.0: Mini App — the blue «Открыть приложение» button in the bot's
    # profile plus the «AnnaBot» menu button. Requires PUBLIC_BASE_URL (the
    # same Railway domain FreeKassa already uses); skipped silently otherwise.
    if PUBLIC_BASE_URL:
        # V3.43.0: the owner reported the blue button missing after a deploy —
        # a single call can silently fail on a cold start / Telegram hiccup,
        # so we retry a few times and log every attempt for diagnostics.
        menu_url = f'{PUBLIC_BASE_URL}/webapp'
        for attempt in range(1, 4):
            try:
                await bot.set_chat_menu_button(menu_button=types.MenuButtonWebApp(
                    text='Открыть приложение',
                    web_app=types.WebAppInfo(url=menu_url),
                ))
                logger.info('webapp menu button installed url=%s attempt=%d', menu_url, attempt)
                break
            except Exception:
                logger.exception('failed to set webapp menu button attempt=%d', attempt)
                if attempt < 3:
                    await asyncio.sleep(3 * attempt)
        # V3.33.1: read the actual Telegram state back so the owner can
        # tell «set but not visible» (client cache) from «never set».
        try:
            current = await bot.get_chat_menu_button()
            logger.info('webapp menu button confirmed type=%s text=%s', type(current).__name__, getattr(current, 'text', ''))
        except Exception:
            logger.exception('webapp menu button verification failed')
    else:
        logger.warning('PUBLIC_BASE_URL is not set — Mini App entry points (/app, settings button, menu button) are disabled')
    logger.info('startup admin_ids_count=%s', len(ADMIN_TELEGRAM_IDS))
    if not ADMIN_TELEGRAM_IDS:
        logger.warning('ADMIN_TELEGRAM_IDS is empty; /admin will be inaccessible')
    for admin_id in ADMIN_TELEGRAM_IDS:
        try:
            await bot.set_my_commands(
                public_commands + [types.BotCommand(command='admin', description='🛠 Админка'), types.BotCommand(command='refundstars', description='↩️ Возврат Stars'), types.BotCommand(command='geministatus', description='🧠 Gemini status'), types.BotCommand(command='grant', description='🎁 Выдать premium/токены по @username'), types.BotCommand(command='setmenubutton', description='🔵 Установить кнопку «Открыть приложение»')],
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
    # V3.28.0: jobs interrupted by the previous deploy — mark them recovered
    # and let the affected users know they can retry.
    try:
        stale = jobs_service.recover_stale_jobs()
        for stale_uid, _stale_kind in stale:
            try:
                await bot.send_message(stale_uid, 'я перезапускалась и не успела доделать генерацию 😔 нажми ещё раз — сразу сделаю')
            except Exception:
                pass
        if stale:
            logger.info('startup recovered_stale_jobs users=%s', len(stale))
    except Exception:
        logger.exception('startup job recovery failed')
    # V3.29.0: prune wizard sessions nobody touched for over a day.
    try:
        _removed_sessions = dialog_store.cleanup_stale_sessions()
        if _removed_sessions:
            logger.info('startup removed_stale_dialog_sessions=%s', _removed_sessions)
    except Exception:
        logger.exception('startup dialog session cleanup failed')
    logger.info('AnnaBot started')
    # V3.43.3: the support desk bot polls alongside the main one when its
    # (rotated) token is configured in the host env.
    if SUPPORT_BOT_TOKEN:
        asyncio.create_task(_run_support_bot())
    else:
        logger.warning('SUPPORT_BOT_TOKEN empty — the support bot stays offline')
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
