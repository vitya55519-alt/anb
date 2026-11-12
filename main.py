import asyncio
import base64
import datetime as dt
import io
import functools
import json
import os
import logging
import random
import re
import secrets
import sys
import tempfile
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
    TELEGRAM_TOKEN, PREMIUM_MONTHLY_STARS, PREMIUM_WEEKLY_STARS, PREMIUM_WEEKLY_PHOTO_CREDITS, PREMIUM_QUARTERLY_PHOTO_CREDITS,
    PREMIUM_QUARTERLY_STARS,
    PHOTO_COST_STARS, CUSTOM_PHOTO_COST_STARS,
    ADMIN_TELEGRAM_IDS, CHARACTER_ID, PHOTO_PROGRESS_MESSAGE_DELAY_SECONDS,
    PHOTO_TOTAL_BUDGET_SECONDS,
    AI_KEY, LIBRARY_MODERATION_ENABLED, LIBRARY_MODERATION_MODEL,
    GEMINI_VIDEO_ENABLED, VIDEO_COST_STARS, GALLERY_DOWNLOAD_STARS, WALLET_PAY_ENABLED,
    PREMIUM_DISCOUNT_PERCENT, DEMO_PREMIUM_HOURS,
    REFERRAL_REFERRER_CREDITS, REFERRAL_INVITEE_CREDITS, REFERRAL_QUALIFY_MESSAGES,
    CONSTRUCTOR_COST_STARS, PHOTO_REACTION_ENABLED, PHOTO_REACTION_COOLDOWN_SECONDS,
    CONSTRUCTOR_COST_RUB, TOKEN_PRICE_RUB, TOKEN_PACK_SIZE, VIDEO_TOKEN_COST, COSPLAY_TOKEN_COST,
    CONSTRUCTOR_COST_PEACHES, MARITAL_CHANGE_PEACHES,
    CONSTRUCTOR_PRICE_USD, PREMIUM_WEEKLY_PRICE_USD, fiat_suffix,
    PLATEGA_ENABLED, PLATEGA_PREMIUM_PRICE_RUB, PLATEGA_PREMIUM_WEEKLY_PRICE_RUB, PLATEGA_PREMIUM_QUARTERLY_PRICE_RUB, PREMIUM_PRICE_USD, PUBLIC_BASE_URL, WEB_PORT,
    BOT_CHAT_REDIRECT,
    SUPPORT_BOT_USERNAME, SUPPORT_BOT_TOKEN, SUPPORT_WELCOME_TEXT,
    CHANNEL_SUBSCRIBE_USERNAME, CHANNEL_SUBSCRIBE_BONUS_CREDITS, CHANNEL_BONUS_HOLD_DAYS,
    PEACH_PACK_STARS, PEACH_PACK_CREDITS, PEACH_PACK_RUB, PEACH_PACK_BONUS,
    PEACH_CUSTOM_STARS_PER_UNIT, PEACH_CUSTOM_RUB_PER_UNIT, PEACH_CUSTOM_UNIT, PEACH_SCALE,
    DAILY_GIFT_BALANCE_CAP, VIDEO_PEACH_COST,
    PLATEGA_MERCHANT_ID, PLATEGA_API_KEY, PLATEGA_API_BASE,
)
# V3.45.0: фото «наедине» и «косплей» — монетизация через персики
from config import (
    PRIVATE_PHOTO_PEACH_COST, COSPLAY_PHOTO_PEACH_COST, CHAT_PHOTO_PEACH_COST, CIRCLE_PEACH_COST,
    HOT_CIRCLE_PEACH_COST, HOT_CIRCLE_ENABLED,
    HOT_PASS_DAY_PEACHES, HOT_PASS_WEEK_PEACHES, HOT_PASS_MONTH_PEACHES, HOT_PASS_FREE_DAILY,
    VOICE_PHOTO_PEACH_COST,
)
from services.user_service import (
    ensure_user, get_user, get_state, update_user_settings, touch_user,
    set_adult_confirmed, is_adult_confirmed,
)
# V3.22.0: RU/EN interface layer (reply keyboard + top-level menus).
from services.ui_lang import EN, RU, menu_rows, app_lang, flow_text, full_user_lang, kb_label, kb_pair, user_lang
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
    ensure_custom_avatar_cached, attach_guest, spicy_needs_premium,
)
from services.photo_idea_service import (
    idea_counts, list_admin_ideas, add_admin_idea, delete_admin_idea,
)
from config import PREMIUM_TRIAL_DAYS, PREMIUM_TRIAL_STARS, PLATEGA_PREMIUM_TRIAL_PRICE_RUB  # V3.88.0
from config import UNDRESS_ONE_ENABLED, UNDRESS_ONE_PRICE_RUB, UNDRESS_ONE_STARS  # V3.132.0
from services.payments import trial_eligible  # V3.88.0
from services.payments import record_payment, get_photo_credits, get_paid_peaches, record_refund, grant_premium, revoke_premium, consume_photo_credit, grant_photo_credits, has_credit_grant, revoke_photo_credits, spend_peaches
from services.bot_description import apply_bot_descriptions
from services import seo_landing
from services.referral_service import (
    parse_referral_payload, apply_first_start_bonuses, apply_referral, referral_count, referral_link,
    referral_user_lock, pending_referral, remember_referral, referral_leaderboard, referral_rank,
    settle_monthly_contest,
    # V3.47.0: source attribution + referral bonus tiers (share links / ladder)
    parse_source_payload, set_source, share_link,
    maybe_grant_referral_tiers, referral_tier_progress,
)
from services.cloud_video_service import CloudVideoError, SENSUAL_ANIMATION_PROMPT, VIDEO_PRESETS
# V3.69.0: SpicyAPI is the only video engine (Veo/Replicate/fal/HF removed).
from services.spicy_video_service import video_engines, spicy_video_available, parked_frame, square_frame
from services import platega_service
from services import jobs_service
from services import dialog_store
from aiohttp import web
from services import apartment_service, gifts_service, dates_service, spicy_service
from services.relationship_service import record_user_message, set_stage_change_notifier
from services.relationship_signals import infer_delta


def _any_video_engine() -> bool:
    """The video engine (SpicyAPI) is configured."""
    return spicy_video_available()


def _video_unavailable_text(telegram_id: int) -> str:
    """V3.19.1: admins see why video is off, so a broken Railway env is
    diagnosable in one tap instead of a silent failure."""
    if telegram_id in ADMIN_TELEGRAM_IDS:
        return ('Видео недоступно: нужен SPICYAPI_KEY и PUBLIC_BASE_URL '
                '(SpicyAPI забирает кадр по ссылке). Проверь переменные окружения на Railway.')
    return 'Видео пока недоступно.'
from services.llm_provider_service import provider_status
from services.reminder_service import (set_timezone, create_from_text, cancel_active_wake, due_reminders,
                                       is_wake_request, wake_trial_available, parse_clock_text, create_at,
                                       reminder_body)
from services.scheduler_service import start_scheduler
from services.memory_service import reset_conversation as reset_memory, save_message
from services.paid_welcome import PREMIUM_PRODUCTS as PAID_PREMIUM_PRODUCTS  # V3.104.0
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
from services.photo_reaction_service import react_to_photo, MAX_BASE64_BYTES
from services.custom_character_service import (
    CONSTRUCTOR_STEPS, CONSTRUCTOR_TEMPLATES, OPTION_LABELS, PARAM_TITLES, build_avatar_prompt,
    custom_character_id, get_all_custom_characters, get_custom_character,
    get_custom_character_by_id, save_custom_character, write_card_bio, all_custom_character_ids,
    template_card_bio, bio_looks_glued,
    normalize_tags,
    request_community_review, moderate_community_submission, set_moderation_status,
    summary_lines, step_index, is_custom_character,
    custom_character_params, set_custom_avatar_file_id,
    save_constructor_draft, snapshot_constructor_draft, get_constructor_draft,
    mark_constructor_draft_paid, claim_constructor_draft, finish_constructor_draft,
    pending_constructor_drafts, abandoned_constructor_drafts, MAX_CONSTRUCTOR_ATTEMPTS,
)
from services.consent_service import has_accepted, accept as accept_consent, delete_user_data, TERMS_VERSION, PRIVACY_VERSION
from services.collection_service import collection_progress
from services.quest_service import QUESTS, QUEST_REPLAY_STARS, story_status, get_quest, complete_route, create_replay_offer, consume_replay_offer, premium_replays_left, consume_premium_replay, newly_unlocked_quests, resolve_story_choice, resolve_story_beat, route_branch, route_points
from services.payment_method_service import (
    list_payment_methods, get_payment_method, create_payment_method,
    update_payment_method, delete_payment_method, ensure_default_payment_methods,
    public_payment_methods, is_button_enabled,
)
from services import donation_service
from services import legal_service
from services import webapp_service
from services.webapp_service import peach_num

# V3.30.2: payment diagnostics (/platega/check since V3.44.21) print the
# deployed build straight from the VERSION file so the owner can confirm
# Railway picked up the new commit.
VERSION = (Path(__file__).resolve().parent / 'VERSION').read_text(encoding='utf-8').strip()
# V3.39.0: Come Closer-style /start — the welcome leads with a group photo.
WELCOME_BANNER_PATH = Path(__file__).resolve().parent / 'data' / 'media' / 'welcome_banner.png'
WELCOME_BANNER_EN_PATH = Path(__file__).resolve().parent / 'data' / 'media' / 'welcome_banner_en.png'
WELCOME_BANNER_GIF_PATH = Path(__file__).resolve().parent / 'data' / 'media' / 'welcome_banner.gif'
BOT_AVATAR_JPG_PATH = Path(__file__).resolve().parent / 'data' / 'media' / 'bot_avatar.jpg'
BOT_AVATAR_MP4_PATH = Path(__file__).resolve().parent / 'data' / 'media' / 'bot_avatar.mp4'

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
# V3.63.2: clean chat (Come Closer style) — menu screens replace each other
# instead of piling up; see services/chat_hygiene.py.
from services import chat_hygiene
chat_hygiene.install(bot)


def service_screen(handler):
    """V3.63.2: a menu-button / /start handler is a *screen*: the user's tap
    and the previous screen are deleted, and everything this handler sends
    becomes the new screen (swept on the next tap). aiogram unwraps the
    wrapper (functools.wraps) to read the handler's real signature, so
    injected kwargs like ``command`` still arrive."""
    import functools

    @functools.wraps(handler)
    async def wrapper(message, *args, **kwargs):
        token = await chat_hygiene.open_screen(bot, message.chat.id, message.message_id)
        try:
            return await handler(message, *args, **kwargs)
        finally:
            chat_hygiene.close_screen(token)
    return wrapper

PHOTO_LABELS = {
    'selfie': '📸 Селфи',
    'home': '🏠 Дома',
    'park': '🌿 Прогулка в парке',
    'cafe': '☕ В кафе',
    'street': '🌆 На улице',
    'mirror': '🪞 В зеркале',
    'outfit': '👗 Мой наряд сегодня',
    'shop': '🛍 На шопинге',
    'car': '🚗 В машине',
    'gym': '🏋️ В спортзале',
    'restaurant': '🍽 Ужин в ресторане',
    'cinema': '🎬 В кино',
    'embankment': '🌊 Закат у реки',
    'fashion': '💎 Фотосессия',
    'evening': '✨ Вечернее платье',
    'bar': '🍸 В баре',
    'karaoke': '🎤 Караоке',
    'rooftop': '🌃 На крыше ночью',
    'club': '💃 В клубе',
    'personal': '💌 Только для тебя',
    'lingerie': '🖤 В кружевном белье',
    'private_fashion': '🔐 Будуар',
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

# V3.21.0: emotional level names; levels 7+ are the premium-only plateau.
# V3.62.0: ten levels; 4-10 differ by path (romance names here, the engine's
# level_title() knows both paths).
RELATIONSHIP_LEVEL_NAMES = {
    1: 'Знакомство',
    2: 'Симпатия',
    3: 'Искра',
    4: 'Влюблённость',
    5: 'Первое свидание',
    6: 'Только ты',
    7: 'Наша история',
    8: 'Под одной крышей',
    9: 'Путешествие',
    10: 'Одно целое',
}
MAX_RELATIONSHIP_LEVEL = len(RELATIONSHIP_LEVEL_NAMES)

# Short-lived UI state only. Paid offers themselves are persisted in PostgreSQL.
# V3.29.0: user-facing wizard state persists in dialog_sessions so a
# redeploy no longer drops paid flows mid-conversation.
_custom_drafts = dialog_store.DialogStore('custom_drafts')
_pending_adult_photo = dialog_store.DialogStore('pending_adult_photo', codec='photo_request')
_pending_undress_photo = dialog_store.DialogStore('pending_undress_photo', codec='photo_request')
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
# V3.55.1: one-per-day paywall nudge for users who keep voice replies on
# without Premium (telegram_id -> ISO date of the last hint).
_voice_premium_hint = dialog_store.DialogStore('voice_premium_hint')
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

# V3.47.1: admin ids waiting to send the art (photo) for an achievement/mission
# badge — populated by the «🖼 Поставить арт» button in the badges screen.
BADGE_MEDIA_WAIT: dict[int, str] = {}

# V3.47.2: admin ids waiting to send media into the morning/evening ritual
# pool — populated by the «➕ Добавить» button in the pool screen.
# V3.47.3: the pool accepts photos, GIFs and short videos.
# V3.56.7: admin id -> character id the next uploaded media belongs to
# (the pool is per-character now — a stranger's face must never ping
# another girl's user). And admin id -> photo id currently being re-tagged.
PROPHOTO_WAIT: dict[int, str] = {}
PROPHOTO_BATCH: dict[int, dict] = {}
PROPHOTO_TAG_WAIT: dict[int, int] = {}

# V3.47.4: admin ids waiting to send carousel photos for one character page —
# pure storefront visuals (DB-backed), the canonical references stay intact.
PGAL_MEDIA_WAIT: dict[int, str] = {}

# Owner-only editor state for configurable payment methods. Payment rows live in PostgreSQL.
_payment_method_edit_sessions: dict[int, dict] = {}

# Owner-only editor state for photo ideas. Idea rows live in PostgreSQL.
_photo_idea_edit_sessions: dict[int, dict] = {}

# V3.31.2: owner-only state for the «🎁 Выдать премиум/токены» button flow.
_admin_grant_sessions: dict[int, dict] = {}

# V3.55.5: owner-only state for the «🎟 Промокоды» create wizard
# (code → credits → max activations → TTL → source tag).
_admin_promo_sessions: dict[int, dict] = {}

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
    # V3.149.0: the same role split as the inline menu — a plain user's reply
    # keyboard is the four clean rows, the owner keeps the whole kombayn. The
    # keyboard is persistent, so the next screen that sends it also replaces the
    # old cluttered one sitting on a returning user's account.
    lang = user_lang(telegram_id) if telegram_id else RU
    admin = bool(is_admin or (telegram_id and telegram_id in ADMIN_TELEGRAM_IDS))
    rows = []
    for row in menu_rows(admin):
        rows.append([
            KeyboardButton(
                text=kb_label(key, lang),
                web_app=types.WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp{MENU_APP_ROUTES[key]}')
                if key in MENU_APP_ROUTES and PUBLIC_BASE_URL else None,
            )
            for key in row
        ])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


def _character_pick_buttons(kind: str):
    # V3.39.0: flat pick buttons without the old per-button status suffix —
    # callers chunk them two per row so /start no longer shows a ten-row wall
    # of buttons (owner: «замени, чтобы оно было как-то компактно, удобно»).
    buttons = []
    # V3.76.0: card girls arrive through their scenario card, not the menu.
    from services.scenario_cards import SCENARIO_GIRLS
    for card in list_cards(visible_only=True):
        if card.character_id in SCENARIO_GIRLS:
            continue
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


def _welcome_banner_file(lang: str = RU):
    """V3.39.0: the group banner photo for /start; None when the asset is absent.
    V3.125.0: backup 7 Nov — 5 of 19 English-speaking newcomers left on the
    very first screen (Russian: 0 of 19). The banner said «Они уже пишут
    тебе» in Russian; English speakers now get the same picture in English.
    V3.142.0: the owner's animated promo leads the welcome in every language;
    the static PNGs stay as fallback.
    V3.148.0: the owner confirmed this gif IS the welcome media — the two girls
    in the frame are the product, not a defect. The one-day single portrait
    that replaced it is out."""
    if WELCOME_BANNER_GIF_PATH.exists():
        return FSInputFile(WELCOME_BANNER_GIF_PATH)
    if lang == EN and WELCOME_BANNER_EN_PATH.exists():
        return FSInputFile(WELCOME_BANNER_EN_PATH)
    if WELCOME_BANNER_PATH.exists():
        return FSInputFile(WELCOME_BANNER_PATH)
    return None


_welcome_gif_file_id = dialog_store.DialogStore('welcome_gif_file_id')


async def _send_welcome_banner(message, lang, caption, markup):
    banner = _welcome_banner_file(lang)
    if banner is None:
        return await message.answer(caption, reply_markup=markup)
    if not str(banner.path).endswith('.gif'):
        return await message.answer_photo(banner, caption=caption, reply_markup=markup)
    # the 6 MB promo uploads once; every later /start reuses Telegram's file_id
    cached = _welcome_gif_file_id.get(0)
    if cached:
        try:
            return await message.answer_animation(cached, caption=caption, reply_markup=markup)
        except Exception:
            _welcome_gif_file_id.pop(0, None)
    msg = await message.answer_animation(banner, caption=caption, reply_markup=markup)
    if msg.animation:
        _welcome_gif_file_id[0] = msg.animation.file_id
    return msg


def _app_row(lang: str):
    """V3.148.0: the chat is a door, not a menu — one wide row into the Mini
    App. The peach balance, the partner program and support all live inside
    it, and Telegram's own menu button opens the same URL with no bubble."""
    if PUBLIC_BASE_URL:
        return [InlineKeyboardButton(
            text=flow_text(lang, 'open_app'),
            web_app=types.WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp'),
        )]
    return [
        InlineKeyboardButton(text='📄 Условия' if lang == RU else '📄 Terms', callback_data='legal:terms'),
        InlineKeyboardButton(text='🔐 Privacy', callback_data='legal:privacy'),
    ]


# V3.149.0: where each menu row goes. The two app rows are Mini App deep links
# (the gallery lands on the character tab, not the chat tab), ⏰ and 📝 are the
# two utilities that arm the FSM below, and the money/content rows only ever
# render for an id in ADMIN_TELEGRAM_IDS — the kitchen stays the owner's.
MENU_APP_ROUTES = {'app': '', 'gallery': '?open=characters'}
MENU_CALLBACK_ROUTES = {
    'alarm': 'menu:alarm',
    'reminder': 'menu:reminder',
    'gallery': 'menu:gallery',
    'profile': 'menu:profile',
    'partner': 'partner:open',
    'recipe': 'photo:kitchen',
    'concert': 'photo:concert',
    'promo': 'admin:promos',
    'credits': 'credits:open',
    'premium': 'premium:view',
    'paint': 'photo_menu:open',
    'support': 'legal:support',
    'legal': 'legal:terms',
    'admin': 'admin:home',
}


def _menu_button(key: str, lang: str) -> InlineKeyboardButton:
    if key in MENU_APP_ROUTES and PUBLIC_BASE_URL:
        return InlineKeyboardButton(
            text=kb_label(key, lang),
            web_app=types.WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp{MENU_APP_ROUTES[key]}'),
        )
    if key == 'app':
        return InlineKeyboardButton(text=flow_text(lang, 'open_app'), callback_data='legal:terms')
    return InlineKeyboardButton(text=kb_label(key, lang), callback_data=MENU_CALLBACK_ROUTES[key])


def menu_markup(telegram_id: int | None = None, lang: str | None = None) -> InlineKeyboardMarkup:
    """V3.149.0: the main menu, drawn per role. A plain user gets exactly four
    rows — two doors into the app and the two chat utilities; an admin gets the
    whole kombayn below them, visually split off in its own rows."""
    menu_lang = lang or (user_lang(telegram_id) if telegram_id else RU)
    is_admin = bool(telegram_id and telegram_id in ADMIN_TELEGRAM_IDS)
    return InlineKeyboardMarkup(inline_keyboard=[
        [_menu_button(key, menu_lang) for key in row]
        for row in menu_rows(is_admin)
    ])


def abilities_text(lang: str = RU) -> str:
    if lang == EN:
        return (
            '✨ What I can do\n\n'
            '💬 real conversation with personality — I remember the context and adapt to your style over time\n'
            '❤️ the relationship grows through levels 1–10: each level gets closer and more open; at level 3 you choose the path of romance or passion (7–10 are a Premium plateau)\n'
            '🎯 interactive stories: your first choice becomes canon, and you can replay alternate branches later\n'
            '📸 photos right in the chat: type “send a photo” or “I want to see you” — I send a fresh shot for the moment; sometimes I offer one myself while flirting\n'
            f'🎬 an “Animate photo” button under every shot — a short AI video from any photo ({VIDEO_COST_STARS} Stars)\n'
            '🎥 video circles — “from me” circles with my voice (paid in 🍑)\n'
            '🎯 daily quest — a small request from me every day, completing it earns attention points\n'
            '🏠 apartment: visit the rooms, spend time with me — new rooms open as the relationship grows\n'
            '💕 dates: invite me somewhere, and afterwards I send you a photo from our outing\n'
            '🎁 gifts: nice surprises that bring us closer\n'
            '🎙 voice replies: every girl has her own sweet voice, I answer in your language\n'
            '🖼 a collection of unlocked photos by relationship level\n'
            '💌 sometimes I write first and return to an unfinished topic\n'
            '⏰ alarm: write «wake me at 8:00» — she wakes you with her voice. First one free, then alarms and reminders come with Premium\n\n'
            '🎯 The first story is already available — start it right away or just write to me.'
        )
    return (
        '✨ Что умеет бот\n\n'
        '💬 живое общение с характером — она запоминает контекст и со временем подстраивается под твою манеру общения\n'
        '❤️ отношения развиваются по уровням 1–10: с каждым уровнем общение и образы становятся ближе и откровеннее; на 3-м ты выбираешь путь романтики или страсти (7–10 — плато для Premium)\n'
        '🎯 интерактивные истории: твой первый выбор становится каноном, а альтернативные ветки можно посмотреть позже\n'
        '📸 фото прямо в чате: напиши «скинь фото» или «хочу тебя увидеть» — она пришлёт свежий кадр по ситуации; иногда предлагает сама во время флирта\n'
        f'🎬 кнопка «Оживить фото» под каждым снимком — короткое AI-видео из любого фото ({VIDEO_COST_STARS} Stars)\n'
        '🎥 кружочки — видео-кружочки «от неё» с её голосом (за 🍑)\n'
        '🎯 задание дня — маленькая просьба от неё каждый день, выполнение даёт очки внимания\n'
        '🏠 квартира: заходи в комнаты, проводи с ней время — новые комнаты открываются с уровнями отношений\n'
        '💕 свидания: пригласи её куда-нибудь, а после она пришлёт фото с прогулки\n'
        '🎁 подарки: приятные сюрпризы, которые сближают\n'
        '🎙 голосовые ответы: у каждой девушки свой милый голос, отвечает на твоём языке\n'
        '🖼 коллекция открытых фотографий по уровням отношений\n'
        '💌 она иногда может написать первой и вернуться к незаконченной теме\n'
        '⏰ будильник: напиши «разбуди в 8:00» — она разбудит тебя голосом. Первый раз бесплатно, дальше будильник и напоминания — с Premium\n\n'
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
    # V3.148.0: the gate is two buttons — 18+ and the app. Terms and privacy are
    # accepted by the 18+ label itself and stay reachable under /legal, so they
    # no longer crowd the first screen.
    if lang == EN:
        rows = [[InlineKeyboardButton(text='✅ I am 18+ · I accept the terms', callback_data='consent:accept')]]
    else:
        rows = [[InlineKeyboardButton(text='✅ Мне 18+ · принимаю условия', callback_data='consent:accept')]]
    rows.append(_app_row(lang))
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
    cid = get_user_character(telegram_id)
    level = get_relationship_level(telegram_id, cid)
    rows = []
    for item in story_status(telegram_id, level, cid):
        if item['unlocked']:
            count = len(item['done']); total = len(item['routes'])
            if not item.get('canonical'):
                label = f"🟢 {item['title']} · начать"
            elif count >= total:
                label = f"✅ {item['title']} · {count}/{total}"
            else:
                label = f"↩️ {item['title']} · {count}/{total}"
            rows.append([InlineKeyboardButton(text=label, callback_data=f"quest:view:{item['key']}")])
        elif not item.get('path_ok', True):
            # V3.62.2: the other path's story — visible, locked.
            where = 'на пути романтики' if item.get('path') == 'romance' else 'на пути страсти'
            rows.append([InlineKeyboardButton(text=f"🔒 {item['title']} · {where}", callback_data=f"quest:locked:{item['key']}")])
        else:
            rows.append([InlineKeyboardButton(text=f"🔒 {item['title']} · откроется L{item['min_level']}", callback_data=f"quest:locked:{item['key']}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def quest_routes_keyboard(telegram_id: int, quest_key: str):
    q=get_quest(quest_key); status=next((x for x in story_status(telegram_id,get_relationship_level(telegram_id, get_user_character(telegram_id)), get_user_character(telegram_id)) if x['key']==quest_key),None)
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


def quest_beat_keyboard(quest_key: str, route_key: str):
    # V3.51.0: the second-beat options hanging off a canonical first choice.
    branch = route_branch(quest_key, route_key)
    if not branch:
        return None
    rows = [[InlineKeyboardButton(text=opt['label'], callback_data=f'quest:beat:{quest_key}:{route_key}:{opt_key}')]
            for opt_key, opt in branch['options'].items()]
    rows.append([InlineKeyboardButton(text='⬅️ Истории', callback_data='quest:list')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def characters_keyboard(telegram_id: int | None = None):
    # V3.39.0: two characters per row — the old one-per-row wall was unreadable.
    rows = _pair_rows(_character_pick_buttons('view'))
    # V3.19.0: entry point to the personal character constructor.
    # V3.45.28: creating any character costs peaches — the «public is free»
    # perk is retired, so the teaser shows the single real price.
    rows.append([InlineKeyboardButton(
        text=f'🎨 Создать свою · {CONSTRUCTOR_COST_PEACHES} 🍑',
        callback_data='constructor:start')])
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
        [InlineKeyboardButton(text='🏆 Арт достижений/миссий', callback_data='admin:badges')],
        [InlineKeyboardButton(text='📸 Медиа для утра/вечера', callback_data='admin:prophoto')],
        # V3.94.0: a ready «🔥 Девушка дня» channel post in two taps.
        [InlineKeyboardButton(text='📣 Пост в канал', callback_data='gday:menu')],
        # V3.129.0: channel rubrics «🗳 Выбираете вы» and «💬 Диалог дня».
        [InlineKeyboardButton(text='🗳 Опрос в канал', callback_data='chpost:poll'),
         InlineKeyboardButton(text='💬 Диалог дня', callback_data='chpost:dlg')],
        [InlineKeyboardButton(text='📊 Статистика', callback_data='admin:stats'),
         InlineKeyboardButton(text='🩺 Отказы', callback_data='admin:providers')],
        # V3.141.0: owner ТЗ (Фаза 2, Задача 3) — net profit per traffic source.
        [InlineKeyboardButton(text='📈 ROI источников', callback_data='admin:roi')],
        [InlineKeyboardButton(text='🎁 Выдать премиум/токены', callback_data='admin:grant')],
        # V3.55.5: promo codes — create / list / toggle off.
        [InlineKeyboardButton(text='🎟 Промокоды', callback_data='admin:promos')],
        [InlineKeyboardButton(text=f'⭐ Premium себе (тесты): {premium_state}', callback_data='admin:premium_toggle')],
        # V3.59.3: put your own path with the current girl anywhere to test
        # passion/tender photos and story badges without replaying stories.
        [InlineKeyboardButton(text='🔥💗 Мой путь (тесты)', callback_data='admin:path')],
        # V3.59.4: rewrite the glued «реалистичная, 23–27, …» storefront bios
        # of the custom personas with the chat model.
        [InlineKeyboardButton(text='✨ Переписать описания своих персонажей', callback_data='admin:biofix')],
    ])


ADMIN_PATH_PRESETS = (('🔥 Страсть 60', 60), ('🔥 Страсть 25', 25), ('⚖️ Сброс 0', 0),
                      ('💗 Нежность 25', -25), ('💗 Нежность 60', -60))


def _admin_path_text(telegram_id: int) -> tuple[str, InlineKeyboardMarkup]:
    from services.relationship_engine import get_path_axis
    char_id = get_user_character(telegram_id)
    axis = get_path_axis(ensure_user(telegram_id), char_id)
    try:
        from services.character_registry import get_character as _gc
        name = _gc(char_id).get('name') or char_id
    except Exception:
        name = char_id
    side = 'страсть 🔥' if axis >= 20 else ('нежность 💗' if axis <= -20 else 'равновесие ⚖️')
    text = (f'🔥💗 Твой путь с {name}: {axis:+.0f} ({side})\n\n'
            'От +20 и выше включаются откровенные позы и мимика на всех фото этой девушки. '
            'Меняется только твой путь с выбранной сейчас девушкой.')
    rows = [[InlineKeyboardButton(text=label, callback_data=f'admin:pathset:{value}')]
            for label, value in ADMIN_PATH_PRESETS]
    rows.append([InlineKeyboardButton(text='⬅️ Админка', callback_data='admin:home')])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


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
        # V3.47.4: the character-PAGE carousel visuals (storefront only, the
        # canonical references behind generation are untouched).
        [InlineKeyboardButton(text='🎠 Карусель страницы', callback_data=f'admin:pgal:{character_id}')],
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
        f'Медиа витрины: {_admin_card_media_label(character_id)}\n'
        f'Карусель страницы: {len(webapp_service.page_gallery_shots(character_id))} фото (витрина, на генерацию не влияет)\n\n'
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


def _selfie_from_dialog(uid: int, character_id: str, request: PhotoRequest) -> PhotoRequest:
    """V3.60.5: a plain selfie takes its place and light from what she just
    wrote in this chat («лежу рядом с мужем» → in bed, night light)."""
    if request.scene != 'selfie' or request.location:
        return request
    try:
        from services.memory_service import get_recent_messages
        from services.photo_service import place_from_dialog
        recent = [m.content for m in reversed(get_recent_messages(uid, character_id, 6)) if m.role == 'assistant']
        place, light = place_from_dialog(recent[:3])
    except Exception:
        return request
    if not place:
        return request
    return replace(request, location=place, time_of_day=request.time_of_day or light)


def _premium_tariff_lines(lang: str) -> list[str]:
    """V3.42.0: the tariff card the owner benchmarked (Come Closer screenshot).
    V3.43.0: three tiers with the competitor's prices (299 / 899 / 1799 ₽) —
    week, month and 3 months; the longer plans show their per-week price, a
    savings badge and the struck «instead of» price of buying them separately."""
    en = lang == EN
    wk_fiat = fiat_suffix(PREMIUM_WEEKLY_STARS, rub=PLATEGA_PREMIUM_WEEKLY_PRICE_RUB, usd=PREMIUM_WEEKLY_PRICE_USD, rub_enabled=PLATEGA_ENABLED)
    mo_fiat = fiat_suffix(PREMIUM_MONTHLY_STARS, rub=PLATEGA_PREMIUM_PRICE_RUB, usd=PREMIUM_PRICE_USD, rub_enabled=PLATEGA_ENABLED)
    q_fiat = fiat_suffix(PREMIUM_QUARTERLY_STARS, rub=PLATEGA_PREMIUM_QUARTERLY_PRICE_RUB, rub_enabled=PLATEGA_ENABLED)
    if PLATEGA_ENABLED and PLATEGA_PREMIUM_WEEKLY_PRICE_RUB and PLATEGA_PREMIUM_PRICE_RUB:
        unit = '₽'
        week_full, month_full, quarter_full = PLATEGA_PREMIUM_WEEKLY_PRICE_RUB, PLATEGA_PREMIUM_PRICE_RUB, PLATEGA_PREMIUM_QUARTERLY_PRICE_RUB
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
            '• 🎥 video circles from me — paid in 🍑',
            '• 🎙 voice replies — Premium only',
            '• 💋 relationship levels 7–10 — the top of the romance or passion path',
            '• 🎚 any relationship level 1–10 — pick it yourself on the level panel in chat',
            '• 2 free replays of alternative quest branches per month',
            '• more memory, initiative and morning/evening messages',
        ]
    else:
        lines = [
            'Premium:',
            '• безлимит сообщений — я больше не «засыпаю» посреди разговора 😴',
            '• 12 дополнительных photo credits',
            '• 🎥 видео-кружочки от меня — за 🍑',
            '• 🎙 голосовые ответы — только для Premium',
            '• 💋 уровни 7–10 отношений — вершина пути романтики или страсти',
            '• 🎚 любой уровень общения 1–10 — выбираешь сам, в панели уровня в чате',
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
    # V3.120.0: auto-renewal exists, but only as his own choice — say where.
    lines.append('Want it to renew by itself? Only if you turn it on: /autopay' if lang == EN
                 else 'Хочешь, чтобы продлевалось само? Только если включишь сам: /autopay')
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
                lines.append('💋 our story is almost at the top… four more levels of intimacy ahead, levels 7–10. That plateau is Premium only.')
            else:
                lines.append('💋 наша история почти на вершине… впереди ещё четыре уровня близости, с 7-го по 10-й. Это плато только для премиума.')
    except Exception:
        pass
    return '\n'.join(lines)


def _sleep_block_markup(telegram_id: int) -> InlineKeyboardMarkup:
    """V3.20.0 daily-limit paywall: demo premium first, then premium."""
    from services.retention_service import has_used_demo, discount_info
    rows = []
    try:
        _en = user_lang(telegram_id) == EN
    except Exception:
        _en = False
    if _en:
        # V3.111.0: the wall the heaviest EN users stood at was all Russian and
        # card/SBP only — English, Stars first, crypto/card second.
        if not has_used_demo(telegram_id):
            rows.append([InlineKeyboardButton(text=f'🎁 Free Premium demo for {DEMO_PREMIUM_HOURS} hours', callback_data='retention:demo')])
        try:
            from services import vip_offer
            vinfo = vip_offer.info(telegram_id)
            if vinfo.get('active'):
                rows.append([InlineKeyboardButton(
                    text=f'💝 A month −{vinfo["percent"]}% just for you — {vinfo["stars"]} Stars ({vinfo["hours_left"]:.0f} h left)',
                    callback_data='buy:premium_vip')])
        except Exception:
            logger.warning('sleep block vip row failed', exc_info=True)
        from services import offer_buttons
        for t, c in offer_buttons.plan_rows(trial_eligible(telegram_id), True):
            rows.append([InlineKeyboardButton(text=t, callback_data=c)])
        rows.append([InlineKeyboardButton(text='⭐ Premium — wake her up, no limits', callback_data='retention:premium')])
        return InlineKeyboardMarkup(inline_keyboard=rows)
    if not has_used_demo(telegram_id):
        rows.append([InlineKeyboardButton(text=f'🎁 Демо-Premium на {DEMO_PREMIUM_HOURS} часа — бесплатно', callback_data='retention:demo')])
    # V3.97.0: his personal one-time −50% month once he keeps hitting the limit.
    try:
        from services import vip_offer
        vinfo = vip_offer.info(telegram_id)
        if vinfo.get('active'):
            rows.append([InlineKeyboardButton(
                text=f'💝 Месяц −{vinfo["percent"]}% только для тебя — {vinfo["stars"]} Stars (ещё {vinfo["hours_left"]:.0f} ч)',
                callback_data='buy:premium_vip')])
            if vinfo.get('rub') and is_button_enabled('platega_rub'):
                rows.append([_platega_pay_button(
                    vip_offer.PRODUCT, vinfo['rub'],
                    f'💳 💝 Месяц за {vinfo["rub"]} ₽ вместо {PLATEGA_PREMIUM_PRICE_RUB} ₽ · карта / СБП')])
    except Exception:
        logger.warning('sleep block vip row failed', exc_info=True)
    # V3.97.0: the 99 ₽ trial is the only thing people actually buy (2 of 2
    # who opened its link paid) — it now sits on the «she fell asleep» wall
    # too, where the most active users stood hundreds of times.
    try:
        if trial_eligible(telegram_id):
            trial_fiat = fiat_suffix(PREMIUM_TRIAL_STARS, rub=PLATEGA_PREMIUM_TRIAL_PRICE_RUB, rub_enabled=PLATEGA_ENABLED)
            rows.append([InlineKeyboardButton(
                text=f'🔥 {PREMIUM_TRIAL_DAYS} дня Premium — {PREMIUM_TRIAL_STARS} Stars{trial_fiat}',
                callback_data='buy:premium_trial')])
            if PLATEGA_ENABLED and is_button_enabled('platega_rub'):
                rows.append([_platega_pay_button(
                    'premium_trial', PLATEGA_PREMIUM_TRIAL_PRICE_RUB,
                    f'💳 🔥 {PREMIUM_TRIAL_DAYS} дня — {PLATEGA_PREMIUM_TRIAL_PRICE_RUB} ₽ · карта / СБП')])
    except Exception:
        logger.warning('sleep block trial row failed', exc_info=True)
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
    if is_premium(message.from_user.id):
        # V3.124.0: a trial man used his trial messages — offer the full plans.
        track_event(uid, 'trial_cap_messages', metadata={'source': 'bot'})
        from services import trial_caps
        if user_lang(message.from_user.id) == EN:
            text = (f'mm, the {trial_caps.TRIAL_MESSAGES} trial messages are over 🥺 '
                    'stay with me on full Premium: unlimited chat, voice, calls every day')
        else:
            text = (f'ммм, {trial_caps.TRIAL_MESSAGES} сообщений пробного закончились 🥺 '
                    'останься со мной в полном Premium: общение без лимита, голос и звонки каждый день')
        await message.answer(text, reply_markup=premium_keyboard(telegram_id=message.from_user.id))
        return
    if has_used_demo(message.from_user.id):
        offer_discount(message.from_user.id)
    track_event(uid, 'chat_sleep_block')
    try:
        from services import vip_offer
        if vip_offer.maybe_open(message.from_user.id):
            track_event(uid, 'vip_offer_shown', metadata={'source': 'bot'})
    except Exception:
        pass
    # V3.44.16: the moment she "falls asleep" is the exit door — give a
    # concrete reason to come back tomorrow, not just the premium upsell.
    # V3.55.5: the wheel became the daily streak gift (app → Магазин, or /profile).
    text = pick_text('sleep') + '\nа завтра утром будет дневной подарок 🍑 — заберёшь в приложении (Магазин) или через /profile'
    await message.answer(text, reply_markup=_sleep_block_markup(message.from_user.id))


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


# V3.44.2: grant peaches (photo credits) to users from admin panel
def add_peaches(telegram_id: int, amount: int) -> int:
    with SessionLocal() as s:
        row = s.query(User).filter(User.telegram_id == str(telegram_id)).first()
        if not row:
            return 0
        row.photo_credits = (row.photo_credits or 0) + amount
        new = int(row.photo_credits)
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


def _platega_pay_button(product: str, amount: int, text: str):
    """V3.44.21: Platega order creation is a network call, so the keyboard
    carries a lightweight callback button; the ``platega:`` handler creates
    the order and sends back the payment-page link (the payer picks SBP /
    card / crypto on the page — no currency or method ids to encode)."""
    return InlineKeyboardButton(text=text, callback_data=f'platega:{product}')


def _autopay_row(telegram_id: int | None, en: bool):
    """V3.120.0: one row under the one-time plans — the opt-in auto-renewal
    menu (terms first, then the pay link), or «manage» when it is on."""
    from services import autopay
    if not autopay.ENABLED or not telegram_id:
        return None
    try:
        live = autopay.get_live(telegram_id)
    except Exception:
        logger.warning('autopay row lookup failed user=%s', telegram_id, exc_info=True)
        live = None
    if live:
        text = '🔁 Auto-renewal is on · manage' if en else '🔁 Автопродление включено · управлять'
    else:
        text = '🔁 Premium with auto-renewal · terms' if en else '🔁 Premium с автопродлением · условия'
    return [InlineKeyboardButton(text=text, callback_data='autopay:menu')]


def _premium_keyboard_en(discount: dict | None, telegram_id: int):
    """V3.111.0: the Premium keyboard for English speakers. The Russian one
    hid every non-Stars row from them and spoke Russian («карта / СБП»), so
    abroad Stars was the only door — and Stars already failed for one of them.
    Now: Stars plans first, then one «💎 crypto / card» row per plan (Platega
    page, crypto is active there), Wallet Pay when configured."""
    rows = []
    trial_ok = trial_eligible(telegram_id)
    if trial_ok:
        rows.append([InlineKeyboardButton(text=f'🔥 Try {PREMIUM_TRIAL_DAYS} days — {PREMIUM_TRIAL_STARS} Stars',
                                          callback_data='buy:premium_trial')])
    if discount and discount.get('active'):
        month = f'⭐ Premium −{discount["percent"]}% — {discount["price"]} Stars ({discount["hours_left"]:.0f} h left)'
    else:
        month = f'⭐ Premium — {PREMIUM_MONTHLY_STARS} Stars / 30 days'
    rows += [
        [InlineKeyboardButton(text=month, callback_data='buy:premium')],
        [InlineKeyboardButton(text=f'⭐ Premium for a week — {PREMIUM_WEEKLY_STARS} Stars', callback_data='buy:premium_week')],
        [InlineKeyboardButton(text=f'⭐ Premium for 3 months — {PREMIUM_QUARTERLY_STARS} Stars', callback_data='buy:premium_quarter')],
    ]
    _ap_row = _autopay_row(telegram_id, True)
    if _ap_row:
        rows.append(_ap_row)
    if WALLET_PAY_ENABLED:
        rows.append([InlineKeyboardButton(text='💎 Premium — Wallet Pay (crypto)', callback_data='walletpay:premium')])
    if PLATEGA_ENABLED and is_button_enabled('platega_rub'):
        if trial_ok:
            rows.append([_platega_pay_button('premium_trial', PLATEGA_PREMIUM_TRIAL_PRICE_RUB,
                                             f'💎 {PREMIUM_TRIAL_DAYS} days — crypto / card · {PLATEGA_PREMIUM_TRIAL_PRICE_RUB} ₽')])
        rows.append([_platega_pay_button('premium_week', PLATEGA_PREMIUM_WEEKLY_PRICE_RUB,
                                         f'💎 a week — crypto / card · {PLATEGA_PREMIUM_WEEKLY_PRICE_RUB} ₽')])
        rows.append([_platega_pay_button('premium_month', PLATEGA_PREMIUM_PRICE_RUB,
                                         f'💎 a month — crypto / card · {PLATEGA_PREMIUM_PRICE_RUB} ₽')])
    if _any_video_engine():
        rows.append([InlineKeyboardButton(text='🎬 Animate a photo · Premium month, 1 a day', callback_data='video:animate_last')])
    rows.append([InlineKeyboardButton(text=f'🎥 A video circle from her — {peach_num(CIRCLE_PEACH_COST)} 🍑', callback_data='video:circle')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def premium_keyboard(discount: dict | None = None, telegram_id: int | None = None):
    try:
        if telegram_id and user_lang(telegram_id) == EN:
            return _premium_keyboard_en(discount, telegram_id)
    except Exception:
        logger.warning('en premium keyboard failed user=%s', telegram_id, exc_info=True)
    if _any_video_engine():
        video_button = InlineKeyboardButton(text='🎬 Оживить фото · Premium на месяц, 1 в день', callback_data='video:animate_last')
    else:
        video_button = InlineKeyboardButton(text='🔒 🎬 Оживить фото · скоро', callback_data='future:animate_photo')
    if discount and discount.get('active'):
        buy_label = f'⭐ Premium −{discount["percent"]}% — {discount["price"]} Stars (ещё {discount["hours_left"]:.0f} ч)'
    else:
        # V3.36.0: rub + dollars next to the Stars price — the rub is the real
        # card/SBP charge while Platega is on, the dollars a display equivalent.
        month_fiat = fiat_suffix(PREMIUM_MONTHLY_STARS, rub=PLATEGA_PREMIUM_PRICE_RUB, usd=PREMIUM_PRICE_USD, rub_enabled=PLATEGA_ENABLED)
        buy_label = f'⭐ Premium — {PREMIUM_MONTHLY_STARS} Stars{month_fiat} / 30 дней'
    week_fiat = fiat_suffix(PREMIUM_WEEKLY_STARS, rub=PLATEGA_PREMIUM_WEEKLY_PRICE_RUB, usd=PREMIUM_WEEKLY_PRICE_USD, rub_enabled=PLATEGA_ENABLED)
    quarter_fiat = fiat_suffix(PREMIUM_QUARTERLY_STARS, rub=PLATEGA_PREMIUM_QUARTERLY_PRICE_RUB, rub_enabled=PLATEGA_ENABLED)
    rows = []
    trial_ok = bool(telegram_id) and trial_eligible(telegram_id)
    if trial_ok:
        # V3.88.0: the cheap first purchase goes on top.
        trial_fiat = fiat_suffix(PREMIUM_TRIAL_STARS, rub=PLATEGA_PREMIUM_TRIAL_PRICE_RUB, rub_enabled=PLATEGA_ENABLED)
        rows.append([InlineKeyboardButton(text=f'🔥 Попробовать {PREMIUM_TRIAL_DAYS} дня — {PREMIUM_TRIAL_STARS} Stars{trial_fiat}',
                                          callback_data='buy:premium_trial')])
    rows += [
        [InlineKeyboardButton(text=buy_label, callback_data='buy:premium')],
        # V3.34.1: the short plan for the undecided — same invoice pipeline.
        [InlineKeyboardButton(text=f'⭐ Premium на неделю — {PREMIUM_WEEKLY_STARS} Stars{week_fiat}', callback_data='buy:premium_week')],
        # V3.43.0: the 3-month plan from the benchmarked card — best per-week price.
        [InlineKeyboardButton(text=f'⭐ Premium на 3 месяца — {PREMIUM_QUARTERLY_STARS} Stars{quarter_fiat}', callback_data='buy:premium_quarter')],
    ]
    _ap_row = _autopay_row(telegram_id, False)
    if _ap_row:
        rows.append(_ap_row)
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
    if PLATEGA_ENABLED:
        # V3.44.21: Platega rows — one payment-page link per product; the
        # payer picks SBP / card / crypto on the Platega page themselves, so
        # the old rub/sbp/usd trio collapsed into a single rub row set.
        # V3.31.1: each built-in row obeys its admin-managed 'builtin' switch
        # (Админка → Способы оплаты → статус) so the owner can remove any
        # button from the user menu without a deploy.
        if is_button_enabled('platega_rub'):
            if trial_ok:
                rows.append([_platega_pay_button(
                    'premium_trial', PLATEGA_PREMIUM_TRIAL_PRICE_RUB,
                    f'💳 🔥 {PREMIUM_TRIAL_DAYS} дня Premium — {PLATEGA_PREMIUM_TRIAL_PRICE_RUB} ₽ · карта / СБП')])
            rows.append([_platega_pay_button(
                'premium_month', PLATEGA_PREMIUM_PRICE_RUB,
                f'💳 Premium — {PLATEGA_PREMIUM_PRICE_RUB} ₽ · карта / СБП / крипта')])
            # V3.34.1: the weekly plan is payable by card/SBP too — the rub
            # price shown next to its Stars price is a real charge, not a display.
            rows.append([_platega_pay_button(
                'premium_week', PLATEGA_PREMIUM_WEEKLY_PRICE_RUB,
                f'💳 Premium на неделю — {PLATEGA_PREMIUM_WEEKLY_PRICE_RUB} ₽ · карта / СБП / крипта')])
            # V3.43.0: the 3-month plan is payable by card/SBP too.
            rows.append([_platega_pay_button(
                'premium_quarter', PLATEGA_PREMIUM_QUARTERLY_PRICE_RUB,
                f'💳 Premium на 3 месяца — {PLATEGA_PREMIUM_QUARTERLY_PRICE_RUB} ₽ · карта / СБП / крипта')])
        if is_button_enabled('platega_tokens'):
            rows.append([
                _platega_pay_button('tokens_1', TOKEN_PRICE_RUB,
                               f'🪙 1 токен — {TOKEN_PRICE_RUB} ₽'),
                _platega_pay_button(f'tokens_{TOKEN_PACK_SIZE}',
                               TOKEN_PACK_SIZE * TOKEN_PRICE_RUB,
                               f'🪙 {TOKEN_PACK_SIZE} токенов — {TOKEN_PACK_SIZE * TOKEN_PRICE_RUB} ₽'),
            ])
    rows.append([video_button])
    rows.append([InlineKeyboardButton(text=f'🎥 Кружочек от неё — {peach_num(CIRCLE_PEACH_COST)} 🍑', callback_data='video:circle')])
    rows.append([InlineKeyboardButton(text='🔒 📞 Звонок с персонажем · скоро', callback_data='future:anna_call')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def peaches_keyboard(telegram_id: int | None = None):
    """V3.71.0: «not enough peaches» — one tap to the app's shop tab."""
    if not PUBLIC_BASE_URL:
        return premium_keyboard(telegram_id=telegram_id)
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text='🍑 Пополнить персики', web_app=types.WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp?open=shop'))]])


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
    # V3.45.0: фото «наедине» и «косплей» — отдельная монетизация через персики.
    # Доступны на ЛЮБОМ уровне отношений, дополняют бесплатную прогрессию.
    from services.private_photo_service import get_private_photo_usage
    usage = get_private_photo_usage(telegram_id)
    private_free = usage['private_left']
    cosplay_free = usage['cosplay_left']
    hot_pass = ' 🔥' if usage['hot_pass_active'] else ''
    # Кнопка «Фото наедине»
    private_label = f'💋 Фото наедине{hot_pass}'
    if private_free > 0 and not usage['hot_pass_active']:
        private_label += f' ({private_free} бесплатн.)'
    rows.append([InlineKeyboardButton(
        text=private_label,
        callback_data='private_photo:start',
    )])
    # Кнопка «Косплей» (V3.45 — отдельная от старого косплей-фотосета)
    cosplay_label = f'🎭 Косплей{hot_pass}'
    if cosplay_free > 0 and not usage['hot_pass_active']:
        cosplay_label += f' ({cosplay_free} бесплатн.)'
    rows.append([InlineKeyboardButton(
        text=cosplay_label,
        callback_data='private_cosplay:start',
    )])
    # V3.45.0: приватная галерея и достижения
    # V3.45.27: achievements come from the single unified registry (lifecycle +
    # private photos) so the bot and the Mini App show the same «N из M».
    from services.private_photo_service import gallery_count
    from services.gamification_service import get_unified_progress
    gal_count = gallery_count(telegram_id)
    _ach = get_unified_progress(telegram_id)
    rows.append([
        InlineKeyboardButton(text=f'🖼️ Галерея ({gal_count})', callback_data='private_gallery:view'),
        InlineKeyboardButton(text=f'🏆 Ачивки ({_ach["unlocked"]}/{_ach["total"]})', callback_data='private_achievements:view'),
    ])
    # V3.46.0: missions funnel — a discoverable roadmap screen (same data as
    # the Mini App «Миссии» tab).
    rows.append([InlineKeyboardButton(text='🎯 Миссии', callback_data='missions:view')])
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


_EN_INVOICE = {
    # V3.111.0: the Stars invoice is what an EN user sees last before paying —
    # it was Russian («Premium на 3 дня — пробный»).
    'premium_trial': lambda: ('Premium trial', f'{PREMIUM_TRIAL_DAYS} days of Premium: explicit chat, photos, voice, a call'),
    'premium_week': lambda: ('Premium', '7 days of Premium: no limits, voice, photos'),
    'premium_month': lambda: ('Premium', '30 days of Premium: no limits, voice, photos'),
    'premium_month_discount': lambda: ('Premium', '30 days of Premium at a one-time discount'),
    'premium_quarter': lambda: ('Premium', '90 days of Premium: no limits, voice, photos'),
    'premium_month_vip': lambda: ('Premium', '30 days of Premium at your personal discount'),
}


def _invoice_texts_en(chat_id: int, title: str, description: str, payload: str) -> tuple[str, str]:
    try:
        if user_lang(chat_id) == EN:
            if payload in _EN_INVOICE:
                return _EN_INVOICE[payload]()
            if payload.startswith('video:'):
                return 'Photo animation', 'A short video from this photo'
    except Exception:
        pass
    return title, description


async def send_stars_invoice(chat_id: int, title: str, description: str, payload: str, stars: int):
    title, description = _invoice_texts_en(chat_id, title, description, payload)
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


async def _mirror_delivery_to_chat_history(telegram_id: int, character_id: str) -> None:
    """V3.44.8: mirror the just-delivered bot photo set into the Mini App chat
    history. Previously only app-side media was recorded, so photos asked in
    the bot never appeared in the app chat («висят как сообщения»). Bytes come
    from the delivery rows (PostgreSQL), so the mirror survives redeploys."""
    from models.photo_models import PhotoDelivery
    from services.db import SessionLocal as _Session
    uid = ensure_user(telegram_id)
    with _Session() as session:
        rows = session.scalars(
            select(PhotoDelivery)
            .where(PhotoDelivery.user_id == uid)
            .order_by(PhotoDelivery.created_at.desc(), PhotoDelivery.id.desc())
            .limit(4)
        ).all()
        frames = [r for r in rows if r.full_resolution_bytes]
    if not frames:
        return
    for row in reversed(frames):  # oldest first, so the set reads in order
        filename = webapp_service.save_chat_media(telegram_id, row.full_resolution_bytes, 'jpg', 'image/jpeg')
        save_message(uid, character_id, 'assistant', '📸 отправила фото',
                     media_kind='photo', media_url=f'/webapp/media/{filename}')


async def _run_photo_background(chat_id: int, telegram_id: int, request: PhotoRequest, delivery_type: str, *, charge: str | None = None, amount: int = 0, product: str = 'photo', spend_undress_credit: bool = False):
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
            # V3.44.15: one delivery, one hard cap. fal's worst-case silent
            # chain (3 routes x 3 retries x 210s read timeout) could grind
            # ~30 minutes — she wrote «смотри на меня» and nothing arrived.
            # The timeout lands in the failure branch: refund + retry button.
            sent = await asyncio.wait_for(
                deliver_photo(bot, chat_id, telegram_id, request, delivery_type, character_id=character_id,
                              skip_stage=spend_undress_credit),
                timeout=PHOTO_TOTAL_BUDGET_SECONDS,
            )
        track_event(uid, 'photo_job_completed', metadata={'scene': request.scene, 'count': len(sent), 'delivery_type': delivery_type})
        if sent and spend_undress_credit:
            from services import undress_credits
            await asyncio.to_thread(undress_credits.spend, telegram_id)
        # V3.44.8: bot-delivered photos land in the Mini App chat history too.
        try:
            if sent:
                await _mirror_delivery_to_chat_history(telegram_id, character_id)
        except Exception:
            logger.exception('chat history photo mirror failed user=%s', telegram_id)
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
        # V3.64.4: the raw engine chain is for the owner only; a user saw
        # «(spicyapi/spicyapi/empty_result:timeout_or_empty → …)» in the chat.
        debug_hint = f' ({exc.provider}/{exc.reason})' if exc.reason and telegram_id in ADMIN_TELEGRAM_IDS else ''
        await bot.send_message(chat_id, f'фото сейчас не получилось 😕{debug_hint}\nлимит не списан. можно повторить.', reply_markup=photo_retry_keyboard(request.scene))
    except asyncio.TimeoutError:
        logger.warning('photo generation timed out user=%s scene=%s budget=%ss', telegram_id, request.scene, PHOTO_TOTAL_BUDGET_SECONDS)
        track_event(uid, 'photo_failed', metadata={'scene': request.scene, 'reason': 'total_timeout', 'provider': 'timeout'})
        if await _maybe_refund_paid_photo(chat_id, telegram_id, charge, amount, product):
            return
        await bot.send_message(chat_id, 'фото делалось слишком долго, я остановила 😕 лимит не списан. попробуй ещё раз.', reply_markup=photo_retry_keyboard(request.scene))
    except Exception as exc:
        logger.exception('photo generation failed user=%s', telegram_id)
        track_event(uid, 'photo_failed', metadata={'scene': request.scene, 'reason': type(exc).__name__, 'provider': 'unknown'})
        if await _maybe_refund_paid_photo(chat_id, telegram_id, charge, amount, product):
            return
        await bot.send_message(chat_id, 'фото сейчас не получилось 😕 лимит не списан. можно повторить.', reply_markup=photo_retry_keyboard(request.scene))
    finally:
        ping.cancel()
        _photo_jobs.pop(telegram_id, None)


async def _start_photo_background(chat_id: int, telegram_id: int, request: PhotoRequest, delivery_type: str, *, charge: str | None = None, amount: int = 0, product: str = 'photo', spend_undress_credit: bool = False):
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
        task = _spawn_job('photo', telegram_id, _run_photo_background(chat_id, telegram_id, request, delivery_type, charge=charge, amount=amount, product=product, spend_undress_credit=spend_undress_credit), payload={'product': product or ''})
        _photo_jobs[telegram_id] = task
        return True
    finally:
        _photo_job_reservations.discard(telegram_id)


def _to_jpeg(data: bytes) -> bytes:
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.open(io.BytesIO(data)).convert('RGB').save(buf, 'JPEG', quality=90)
    return buf.getvalue()


async def _send_duo_teaser(chat_id: int, telegram_id: int, character_id: str, guest_id: str) -> None:
    """V3.139.0: Задача 5 in the bot — the blurred joint picture, both girls'
    hook in his language, and the Premium button under it."""
    from services import duo_teaser
    from services.chat_guest_service import character_name, host_name
    from services.ui_lang import duo_teaser as hook_text
    host_nm = host_name(character_id)
    guest_nm = character_name(guest_id)
    text = hook_text(full_user_lang(telegram_id), host_nm, guest_nm)
    body = None
    try:
        body = await asyncio.to_thread(duo_teaser.photo_for, character_id, guest_id)
    except Exception:
        logger.warning('duo teaser picture failed user=%s', telegram_id)
    try:
        track_event(ensure_user(telegram_id), 'paywall_view',
                    metadata={'product': 'duo_photo', 'source': 'bot'})
    except Exception:
        pass
    if body:
        await bot.send_photo(chat_id, BufferedInputFile(body, filename='duo.jpg'),
                             caption=text, reply_markup=premium_keyboard(telegram_id=telegram_id))
        return
    await bot.send_message(chat_id, text, reply_markup=premium_keyboard(telegram_id=telegram_id))


async def handle_photo_request(chat_id: int, telegram_id: int, request: PhotoRequest, *,
                               undress_credit: bool = False, text: str = ''):
    from services import spend_service
    spend_service.set_spend_user(telegram_id)
    db_uid = ensure_user(telegram_id)
    if not has_accepted(telegram_id):
        await bot.send_message(chat_id, 'Сначала подтверди 18+ и условия через /start.', reply_markup=consent_keyboard())
        return
    track_event(db_uid, 'photo_requested', metadata={'scene': request.scene, 'customized': bool(request.customized)})
    observe_photo_preference(db_uid, request.scene, request.clothing, request.hairstyle, request.location, get_user_character(telegram_id))
    stage = get_relationship_stage(telegram_id, get_user_character(telegram_id))
    # V3.88.0: spicy scenes are gated by Premium below, not by level.
    if not spicy_needs_premium(request) and not scene_allowed_for_stage(request.scene, stage):
        track_event(db_uid, 'photo_locked_view', metadata={'scene': request.scene, 'level': get_relationship_level(telegram_id, get_user_character(telegram_id))})
        await bot.send_message(chat_id, 'такой образ я пока оставлю при себе 😏')
        return

    if _card_girl_photo_locked(get_user_character(telegram_id), telegram_id):
        await bot.send_message(chat_id, CHAT_PHOTO_BLOCK_TEXT['premium'],
                               reply_markup=premium_keyboard(telegram_id=telegram_id))
        return
    if requires_adult_confirmation(request) and not is_adult_confirmed(telegram_id):
        _pending_adult_photo[telegram_id] = request
        await bot.send_message(chat_id, 'для более смелых fashion-образов нужно один раз подтвердить, что тебе 18+.', reply_markup=adult_keyboard())
        return

    if telegram_id in ADMIN_TELEGRAM_IDS:
        await _start_photo_background(chat_id, telegram_id, request, 'admin')
        return

    # V3.139.0: owner ТЗ (Задачи 5–6) — «сфоткайтесь вдвоём» is a duo thing.
    # A man with Premium gets the real joint frame (the second girl rides into
    # the prompt as reference images 3–4); a man without Premium gets a heavily
    # blurred teaser from the ready pool — the provider is never called, so the
    # tease costs nothing.
    request = attach_guest(request, telegram_id, get_user_character(telegram_id), text)
    if getattr(request, 'with_guest', '') and not is_premium(telegram_id):
        await _send_duo_teaser(chat_id, telegram_id, get_user_character(telegram_id), request.with_guest)
        return

    if not is_premium(telegram_id) and spicy_needs_premium(request):
        # V3.87.0: nude / lingerie photos are Premium-only — sell Premium here.
        # V3.137.0: a bought one-time «Раздеть» works without Premium.
        if undress_credit:
            from services import undress_credits
            if undress_credits.balance(telegram_id) > 0:
                await _start_photo_background(chat_id, telegram_id, request, 'paid',
                                              product='undress_one', spend_undress_credit=True)
                return
        track_event(db_uid, 'paywall_view', metadata={'product': 'spicy_photo', 'scene': request.scene, 'source': 'bot'})
        if undress_credit and UNDRESS_ONE_ENABLED:
            _pending_undress_photo[telegram_id] = request
            await bot.send_message(
                chat_id,
                f'🔥 одно «Раздеть» — {UNDRESS_ONE_PRICE_RUB} ₽ в приложении или {UNDRESS_ONE_STARS} ⭐. '
                'Premium тоже откроет все откровенные фото.',
                reply_markup=premium_keyboard(telegram_id=telegram_id))
            await send_stars_invoice(chat_id, f'Раздеть · {_character_display_name(get_user_character(telegram_id))}',
                                     'Одно откровенное фото без Premium', 'undress_one', UNDRESS_ONE_STARS)
            return
        await bot.send_message(chat_id, CHAT_PHOTO_BLOCK_TEXT['spicy'],
                               reply_markup=premium_keyboard(telegram_id=telegram_id))
        return

    if is_custom_request(request):
        track_event(db_uid, 'paywall_view', metadata={'product': 'custom_photo', 'scene': request.scene})
        await _offer_custom_photo(chat_id, telegram_id, request)
        return

    # V3.93.0: without Premium — one free photo a day, a ready-made one (no
    # render), then Premium; with Premium — two rendered a day, then peaches.
    from services.chat_photo_allowance import free_chat_photos_left, use_free_chat_photo, reused_photo
    premium = is_premium(telegram_id)
    character_id = get_user_character(telegram_id)
    if not premium:
        if await asyncio.to_thread(free_chat_photos_left, db_uid, False) <= 0:
            track_event(db_uid, 'paywall_view', metadata={'product': 'chat_photo', 'source': 'free_used_bot'})
            await bot.send_message(chat_id, CHAT_PHOTO_BLOCK_TEXT['free_used'],
                                   reply_markup=premium_keyboard(telegram_id=telegram_id))
            return
        ready = await asyncio.to_thread(reused_photo, character_id, db_uid)
        if ready:
            data, _mime, ext = ready
            if ext == 'webp':
                data = await asyncio.to_thread(_to_jpeg, data)
                ext = 'jpg'
            await bot.send_photo(chat_id, BufferedInputFile(data, filename=f'photo.{ext}'),
                                 caption='📸 ' + random.choice(AUTO_CAPTIONS.get(request.scene, ('это тебе 😘',))))
            await asyncio.to_thread(use_free_chat_photo, db_uid, character_id)
            from services.chat_photo_allowance import POOL_EVENT, note_today
            await asyncio.to_thread(note_today, db_uid, POOL_EVENT, character_id)
            return
        await asyncio.to_thread(use_free_chat_photo, db_uid, character_id)
        await _start_photo_background(chat_id, telegram_id, request, 'free')
        return
    credits = get_paid_peaches(telegram_id)
    if await asyncio.to_thread(free_chat_photos_left, db_uid, True) > 0:
        await asyncio.to_thread(use_free_chat_photo, db_uid, character_id)
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
@service_screen
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
    # V3.47.0: acquisition-source attribution. src_<tag> tags the ad/content/
    # catalogue channel; src_share_<uid> additionally credits the sharer as the
    # referrer (this is how a watermarked shared photo pays the person who sent
    # it). First touch wins — set_source never overwrites an existing tag.
    source_tag, share_referrer = parse_source_payload(command.args)
    if source_tag:
        if set_source(message.from_user.id, source_tag):
            track_event(uid, 'source_opened', metadata={'src': source_tag})
        if share_referrer and share_referrer != message.from_user.id:
            remember_referral(message.from_user.id, share_referrer)
            has_referral = True
    elif has_referral:
        # V3.62.6: a friend's invite is a source too — the stats screen
        # groups new users by it.
        set_source(message.from_user.id, 'ref')
    elif command.args:
        # V3.62.6: any other deep link (an ad network, a catalogue, a channel
        # post with its own ?start=) used to be dropped — keep it as-is.
        if set_source(message.from_user.id, 'link:' + command.args.strip()[:40]):
            track_event(uid, 'source_opened', metadata={'src': 'link:' + command.args.strip()[:40]})
    track_event(uid, 'onboarding_completed')
    # V3.92.0: the «🔥 Девушка дня» channel post opens a chat with her.
    try:
        from services import girl_of_day
        gday = await asyncio.to_thread(girl_of_day.girl_from_payload, command.args)
        if gday:
            set_user_character(message.from_user.id, gday)
    except Exception:
        logger.warning('girl of day deep link failed user=%s', message.from_user.id, exc_info=True)

    if not has_accepted(message.from_user.id):
        lang = user_lang(message.from_user.id)
        if lang == EN:
            welcome = (
                'What can this bot do?\n\n'
                'Roleplay with AI girls: live chats with memory, photos for your scenarios, AI video and voice.\n'
                'The relationship grows through levels 1–10 — closer and more open at every level.\n\n'
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
                'Отношения растут по уровням 1–10 — с каждым уровнем ближе и откровеннее.\n\n'
                '🎁 после подтверждения 18+ — бесплатные фото-кредиты на первое фото.\n'
                '⬇️ Поехали! ⬇️\n\n'
            )
            if has_referral:
                welcome += f'пришёл по приглашению друга — напиши ей {REFERRAL_QUALIFY_MESSAGES} сообщений, и вам обоим капнет по {REFERRAL_INVITEE_CREDITS} 🍑.\n'
            welcome += 'Подтверди, что тебе 18+, и прими условия использования и политику конфиденциальности.'
        await _send_welcome_banner(message, lang, welcome, consent_keyboard(lang))
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
    # V3.149.0: and that list is now the role menu — four rows for a user.
    markup = menu_markup(message.from_user.id, lang)
    # V3.147.0: nothing is pinned at /start any more. The pin cost a service
    # line («...закрепил(а) главное меню») right under the welcome and read as
    # bot noise; the app, the balance and the partner program live on the
    # native Telegram menu button (set_chat_menu_button) and in the reply
    # keyboard, so the pinned bubble carries nothing no tap can reach.
    await _send_welcome_banner(message, lang, welcome_back, markup)
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
            logger.info('referral on consent invitee=%s referrer=%s status=%s', cq.from_user.id, ref, res.get('status'))
            if res.get('awarded'):
                track_event(uid, 'referral_awarded_on_consent', metadata={'referrer_id': str(ref)})
        first_start = apply_first_start_bonuses(cq.from_user.id)
    await cq.answer('✅')
    flow_lang = full_user_lang(cq.from_user.id, cq.from_user.language_code)
    # V3.148.0: the start bubble is rewritten in place instead of answering with
    # a new one — no menu message, no girl picker, no service lines. The bonus
    # line and the menu rows all live inside that one bubble.
    # V3.149.0: and the rows are the role menu — a plain user gets exactly four.
    welcome_line = (flow_text(flow_lang, 'welcome_edit', amount=first_start['credits'])
                    if first_start['credits'] else flow_text(flow_lang, 'welcome_edit_plain'))
    kb = menu_markup(cq.from_user.id, flow_lang)
    try:
        if cq.message.animation or cq.message.photo or cq.message.video:
            await cq.message.edit_caption(caption=welcome_line, reply_markup=kb)
        else:
            await cq.message.edit_text(text=welcome_line, reply_markup=kb)
    except Exception:
        logger.exception('start bubble edit failed user=%s', cq.from_user.id)
        await cq.message.answer(welcome_line, reply_markup=kb)


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
            'Премиум-персонажи открываются вместе с подпиской — сразу после '
            'оплаты можно выбрать её в «Персонажах».\n',
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
                '🚀 Premium — unlimited chatting and levels 7–10'
            ) if tour_lang == EN else (
                'быстрый тур по кнопкам 👇\n\n'
                '💬 просто пиши ей — отношения растут с каждым сообщением\n'
                '📸 Фото — попроси кадр в любой ситуации\n'
                '🎬 Видео и 🎥 Кружочек — оживи фото или получи видео-кружочек с её голосом\n'
                '🎯 Задание дня — её маленькая просьба (+5 внимания за выполнение)\n'
                '💕 Свидание и 🏠 Квартира — время вместе, новые места открываются с уровнями\n'
                '👤 Профиль — твой уровень близости в сердечках и прогресс\n'
                '🚀 Премиум — безлимит общения и уровни 7–10'
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
@service_screen
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
    _admin_promo_sessions.pop(message.from_user.id, None)
    CARD_MEDIA_WAIT.pop(message.from_user.id, None)
    ensure_default_cards()
    await message.answer('⚙️ Админка AnnaBot', reply_markup=admin_keyboard())


@dp.message(Command('revoke_all_premium'))
async def admin_revoke_all_premium(message: types.Message):
    """V3.56.0: pull every live Premium entitlement in one shot (the test/admin
    grants). Admin-only; keeps subscription history and photo credits intact."""
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    from services.payments import revoke_all_premium
    n = revoke_all_premium()
    await message.answer(f'⭐ Снято active Premium у всех: {n} подписок отключено.')


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
    _admin_promo_sessions.pop(cq.from_user.id, None)
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


_BIOFIX_RUNNING: set[int] = set()


@dp.callback_query(F.data == 'admin:biofix')
async def admin_biofix(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    if _BIOFIX_RUNNING:
        await cq.answer('Уже переписываю, подожди', show_alert=False)
        return
    await cq.answer('Начала')
    await cq.message.answer('✨ Переписываю описания пользовательских персонажей, пришлю итог.')
    _spawn_background(_admin_biofix_run(cq.message.chat.id))


async def _admin_biofix_run(chat_id: int) -> None:
    _BIOFIX_RUNNING.add(chat_id)
    done = failed = 0
    try:
        for cid in all_custom_character_ids():
            params, name = custom_character_params(cid)
            if not params or not get_card(cid):
                continue
            try:
                bio = await asyncio.wait_for(write_card_bio(params, name or 'она'), timeout=30)
            except Exception:
                bio = None
            if bio:
                done += 1
            else:
                bio = template_card_bio(params, name or 'Она')
                failed += 1
            update_card(cid, short_bio=bio)
    finally:
        _BIOFIX_RUNNING.discard(chat_id)
    await bot.send_message(chat_id, f'✨ Готово: красиво переписано {done}, по шаблону {failed}.')


async def _startup_fix_glued_bios() -> None:
    """V3.59.4: cards still carrying the glued «реалистичная, 34+, мягкое…»
    bio get rewritten once after a deploy — no admin tap needed."""
    await asyncio.sleep(30)
    for cid in all_custom_character_ids():
        try:
            params, name = custom_character_params(cid)
            card = get_card(cid)
            if not params or not card or not bio_looks_glued(card.short_bio or '', params, name or ''):
                continue
            try:
                bio = await asyncio.wait_for(write_card_bio(params, name or 'Она'), timeout=30)
            except Exception:
                bio = None
            update_card(cid, short_bio=bio or template_card_bio(params, name or 'Она'))
        except Exception:
            logger.exception('glued bio rewrite failed character=%s', cid)


@dp.callback_query(F.data == 'admin:path')
async def admin_path_menu(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    await cq.answer()
    text, kb = _admin_path_text(cq.from_user.id)
    await cq.message.answer(text, reply_markup=kb)


@dp.callback_query(F.data.startswith('admin:pathset:'))
async def admin_path_set(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    from services.relationship_engine import set_path_axis
    try:
        value = int(cq.data.rsplit(':', 1)[1])
    except ValueError:
        await cq.answer()
        return
    uid = ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    set_path_axis(uid, get_user_character(cq.from_user.id), value)
    track_event(uid, 'admin_path_set')
    await cq.answer(f'Путь: {value:+d}', show_alert=False)
    text, kb = _admin_path_text(cq.from_user.id)
    try:
        await cq.message.edit_text(text, reply_markup=kb)
    except Exception:
        await cq.message.answer(text, reply_markup=kb)


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


# V3.44.2: peaches (photo credits) grant callback
@dp.callback_query(F.data.startswith('admin:grantdo:peaches:'))
async def admin_grant_do_peaches_ask(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    try:
        target = int(cq.data.rsplit(':', 1)[1])
    except ValueError:
        return
    _admin_grant_sessions[cq.from_user.id] = {'step': 'peaches', 'target': target}
    await cq.answer()
    await cq.message.answer(f'Сколько персиков выдать? Пришли число, например 1000 (фото в чате — {CHAT_PHOTO_PEACH_COST}).\n\n/cancel — отменить')


# ---------------------------------------------------------------------------
# V3.55.5: «🎟 Промокоды» — owner section: list with activation counters,
# toggle codes off/on, and a 4-step creation wizard (code → peaches → max
# activations → TTL → source tag). Redemption itself lives in gift_service.
# ---------------------------------------------------------------------------
def _promo_admin_keyboard():
    from models.app_models import PromoCode
    try:
        with SessionLocal() as s:
            codes = s.scalars(select(PromoCode).order_by(PromoCode.id.desc()).limit(12)).all()
    except Exception:
        logger.exception('promo list read failed')
        codes = []
    rows = []
    for pc in codes:
        cap = '∞' if not pc.max_activations else pc.max_activations
        flag = '✅' if pc.active else '⛔️'
        ttl = ''
        if pc.expires_at:
            ttl = f' · до {pc.expires_at:%d.%m %H:%M} UTC'
        rows.append([InlineKeyboardButton(
            text=f'{flag} {pc.code} · +{pc.credits}🍑 · {pc.activated_count}/{cap}{ttl}',
            callback_data=f'admin:promotgl:{pc.id}')])
    rows.append([InlineKeyboardButton(text='➕ Создать код', callback_data='admin:promoadd:start')])
    rows.append([InlineKeyboardButton(text='⬅️ Админка', callback_data='admin:home')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(F.data == 'admin:promos')
async def admin_promos_view(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    await cq.answer()
    await cq.message.answer(
        '🎟 Промокоды — персики за код\n\n'
        '· один юзер — одна активация на код\n'
        '· тап по коду — вкл/выкл\n'
        '· номинал ограничен сверху (Premium-дни кодами не выдаются)',
        reply_markup=_promo_admin_keyboard(),
    )


@dp.callback_query(F.data == 'admin:promoadd:start')
async def admin_promo_add_start(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    _admin_promo_sessions[cq.from_user.id] = {'step': 'code'}
    await cq.answer()
    await cq.message.answer(
        'Пришли сам код: 4–24 символа, A–Z и 0–9 (регистр не важен).\n'
        'Например WELCOME5.\n\n/cancel — отменить'
    )


@dp.callback_query(F.data.startswith('admin:promotgl:'))
async def admin_promo_toggle(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    try:
        pc_id = int(cq.data.rsplit(':', 1)[1])
    except ValueError:
        return
    from models.app_models import PromoCode
    with SessionLocal() as s:
        pc = s.scalar(select(PromoCode).where(PromoCode.id == pc_id))
        if not pc:
            await cq.answer('код не найден')
            return
        pc.active = not pc.active
        s.commit()
        state = 'включён' if pc.active else 'отключён'
        code = pc.code
    await cq.answer(f'{code}: {state}')
    await cq.message.answer(f'🎟 Код {code} — {state}.', reply_markup=_promo_admin_keyboard())


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


# ── V3.47.1: admin achievement/mission art (badges) ──────────────────────────
def admin_badges_keyboard():
    from services.gamification_service import badge_catalog, badge_keys
    have = badge_keys()
    rows = [[InlineKeyboardButton(
        text=f'{"✅" if key in have else "⬜️"} {name}',
        callback_data=f'admin:badge:{key}')]
        for key, name in badge_catalog()]
    rows.append([InlineKeyboardButton(text='⬅️ Админка', callback_data='admin:home')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_badge_keyboard(key: str, name: str):
    from services.gamification_service import badge_keys
    have = key in badge_keys()
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🖼 Поставить арт', callback_data=f'admin:badge:set:{key}')],
        [InlineKeyboardButton(text='🗑 Убрать арт', callback_data=f'admin:badge:clear:{key}')],
        [InlineKeyboardButton(text='⬅️ К списку', callback_data='admin:badges')],
    ]), have


@dp.callback_query(F.data == 'admin:badges')
async def admin_badges_view(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    await cq.answer()
    await cq.message.answer(
        '🏆 Арт достижений и миссий\n\n'
        'Выберите награду и пришлите ей картинку — она будет приходить в '
        'момент открытия и показываться в разделе «Достижения». Без артa '
        'уведомление остаётся текстом.',
        reply_markup=admin_badges_keyboard())


@dp.callback_query(F.data.startswith('admin:badge:')
                   & ~F.data.startswith('admin:badge:set:')
                   & ~F.data.startswith('admin:badge:clear:'))
async def admin_badge_one(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    key = cq.data.split(':', 2)[2]
    from services.gamification_service import badge_catalog
    name = dict(badge_catalog()).get(key, key)
    kb, have = admin_badge_keyboard(key, name)
    await cq.answer()
    await cq.message.answer(f'🖼 Арт для «{name}»\n\nСейчас: {"есть" if have else "нет"}.', reply_markup=kb)


@dp.callback_query(F.data.startswith('admin:badge:set:'))
async def admin_badge_wait(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    key = cq.data.split(':', 3)[3]
    BADGE_MEDIA_WAIT[cq.from_user.id] = key
    await cq.answer()
    await cq.message.answer(
        f'📥 Пришли фото (до 8 MB) для награды {key}.\n\n/cancel — отменить')


@dp.callback_query(F.data.startswith('admin:badge:clear:'))
async def admin_badge_clear(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    key = cq.data.split(':', 3)[3]
    from services.gamification_service import clear_badge
    removed = clear_badge(key)
    await cq.answer('арт убран' if removed else 'арта не было')
    await cq.message.answer(f'🏆 Готово: {"арт убран" if removed else "арта не было"}.',
                            reply_markup=admin_badges_keyboard())


@dp.message(lambda m: m.from_user is not None and m.from_user.id in BADGE_MEDIA_WAIT, F.photo)
async def admin_badge_upload(message: types.Message):
    """V3.47.1: the photo the admin sends becomes that achievement's badge art."""
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    key = BADGE_MEDIA_WAIT.get(message.from_user.id)
    if not key:
        return
    photo = message.photo[-1]
    if (photo.file_size or 0) > 8 * 1024 * 1024:
        await message.answer('файл тяжелее 8 MB — пришли полегче.')
        return
    buf = io.BytesIO()
    await bot.download(photo.file_id, destination=buf)
    from services.gamification_service import set_badge
    ok = set_badge(key, buf.getvalue(), 'image/jpeg')
    BADGE_MEDIA_WAIT.pop(message.from_user.id, None)
    await message.answer(
        f'✅ Арт для «{key}» сохранён.' if ok else '⚠️ Не удалось сохранить арт.',
        reply_markup=admin_badges_keyboard())


# ── V3.47.2: morning/evening ritual media pool (admin uploads many) ────────
# V3.47.3: photos, GIFs and videos — kind drives both storage limit and send.
_PROPHOTO_KIND_EMOJI = {'photo': '📸', 'gif': '🎞', 'video': '🎬'}


def _prophoto_char_names() -> dict:
    # V3.56.7: id -> display name for pool labels (built-in + constructor
    # personas all live in the card registry).
    from services.character_card_service import list_cards
    try:
        return {c.character_id: (c.display_name or c.character_id) for c in list_cards(visible_only=False)}
    except Exception:
        return {}


def admin_prophoto_keyboard():
    from services import retention_features_service as rfs
    photos = rfs.list_proactive_photos()
    names = _prophoto_char_names()
    rows = [[InlineKeyboardButton(text='➕ Добавить фото / GIF / видео', callback_data='admin:prophoto:add')],
            # V3.61.8: one tap renders fresh «я скучала» shots of every heroine.
            [InlineKeyboardButton(text='✨ Сгенерировать 20 фото «я скучала»', callback_data='admin:prophoto:gen')],
            # V3.150.0: the frame under today's voice note, picked by hand.
            [InlineKeyboardButton(text='🖼 Фото под утро', callback_data='ritual_ph:open:morning'),
             InlineKeyboardButton(text='🖼 Фото под вечер', callback_data='ritual_ph:open:evening')]]
    if photos:
        rows.append([InlineKeyboardButton(text='🧹 Удалить старые фото пула', callback_data='admin:prophoto:clear')])
    del_row = []
    for p in photos:
        _cid = p.get('character_id') or ''
        tag = names.get(_cid, _cid)[:10] if _cid else '❓'
        del_row.append(InlineKeyboardButton(
            text=f"🗑 {_PROPHOTO_KIND_EMOJI.get(p.get('kind'), '📸')} #{p['id']} {tag}",
            callback_data=f'admin:prophoto:del:{p["id"]}'))
        del_row.append(InlineKeyboardButton(
            text=f"🏷 #{p['id']}", callback_data=f'admin:prophoto:tag:{p["id"]}'))
    for i in range(0, len(del_row), 6):
        rows.append(del_row[i:i + 6])
    rows.append([InlineKeyboardButton(text='⬅️ Админка', callback_data='admin:home')])
    return InlineKeyboardMarkup(inline_keyboard=rows), len(photos)


def _prophoto_choose_keyboard():
    # V3.56.7: whose face is the next media? Every pool shot is tied to one
    # character and only ever sent in her chats.
    from services.character_card_service import list_cards
    rows = []
    line = []
    try:
        cards = list_cards(visible_only=False)
    except Exception:
        cards = []
    for c in cards:
        line.append(InlineKeyboardButton(
            text=(c.display_name or c.character_id)[:12],
            callback_data=f'admin:prophoto:pick:{c.character_id}'))
        if len(line) == 2:
            rows.append(line)
            line = []
    if line:
        rows.append(line)
    rows.append([InlineKeyboardButton(text='❌ Отменить', callback_data='admin:prophoto')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(F.data == 'admin:prophoto')
async def admin_prophoto_view(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    kb, n = admin_prophoto_keyboard()
    await cq.answer()
    await cq.message.answer(
        f'📸 Медиа для утра/вечера — в пуле: {n}\n\n'
        'Каждое фото/GIF/видео принадлежит ОДНОЙ героине и приходит только '
        'её пользователям — так «утреннее селфи» Нади больше не будет лицом '
        'совершенно другой девушки. Кнопка 🏷 — сменить героиню у кадра.',
        reply_markup=kb)


@dp.callback_query(F.data == 'admin:prophoto:add')
async def admin_prophoto_wait(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    PROPHOTO_TAG_WAIT.pop(cq.from_user.id, None)
    await cq.answer()
    await cq.message.answer(
        'Чьё это фото / GIF / видео? Пришлите кадр после выбора героини.',
        reply_markup=_prophoto_choose_keyboard())


@dp.callback_query(F.data.startswith('admin:prophoto:tag:'))
async def admin_prophoto_tag_wait(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    try:
        photo_id = int(cq.data.split(':', 3)[3])
    except (TypeError, ValueError):
        await cq.answer('не то id', show_alert=True)
        return
    PROPHOTO_TAG_WAIT[cq.from_user.id] = photo_id
    await cq.answer()
    await cq.message.answer(f'Кому теперь принадлежит кадр #{photo_id}?')


@dp.callback_query(F.data.startswith('admin:prophoto:pick:'))
async def admin_prophoto_pick(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    char_id = cq.data.split(':', 3)[3]
    from services import retention_features_service as rfs
    tag_id = PROPHOTO_TAG_WAIT.pop(cq.from_user.id, None)
    await cq.answer()
    if tag_id is not None:
        ok = rfs.set_proactive_photo_character(tag_id, char_id)
        kb, n = admin_prophoto_keyboard()
        await cq.message.answer(
            f'✅ Кадр #{tag_id} — теперь {char_id}. В пуле: {n}.' if ok else '⚠️ Кадр не найден.',
            reply_markup=kb)
        return
    PROPHOTO_WAIT[cq.from_user.id] = char_id
    PROPHOTO_BATCH.pop(cq.from_user.id, None)
    await cq.message.answer(
        f'📥 Пришли фото (до 8 MB), GIF или видео (до 20 MB) — они попадут в пул для «{char_id}».\n'
        'Можно сразу пачкой — выдели несколько фото и отправь альбомом. Когда закончишь, нажми «✅ Готово».',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='✅ Готово', callback_data='admin:prophoto:done')]]))


GIFT_POOL_RUNNING: set[int] = set()


@dp.callback_query(F.data == 'admin:prophoto:gen')
async def admin_prophoto_generate(cq: types.CallbackQuery):
    """V3.61.8: render ~20 «я скучала» photos across all heroines into the pool."""
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    from services import gift_pool_service
    if cq.from_user.id in GIFT_POOL_RUNNING:
        await cq.answer('уже генерирую, подожди', show_alert=True)
        return
    plan = gift_pool_service.plan_gift_pool()
    if not plan:
        await cq.answer('нет видимых героинь', show_alert=True)
        return
    await cq.answer()
    admin_id = cq.from_user.id
    status = await cq.message.answer(
        f'✨ Генерирую {len(plan)} фото «я скучала» — лицо целиком в кадре, у каждой героини свои. '
        'Это займёт несколько минут, напишу, когда закончу.')
    GIFT_POOL_RUNNING.add(admin_id)

    async def _progress(n: int, total: int, cid: str) -> None:
        if n % 4 == 0 and n < total:
            await status.edit_text(f'✨ Готово {n} из {total}…')

    async def _run() -> None:
        try:
            added, failed = await gift_pool_service.fill_gift_pool(admin_id, total=len(plan), progress=_progress)
            kb, n = admin_prophoto_keyboard()
            await bot.send_message(
                admin_id,
                f'✅ Добавлено в пул: {added}' + (f', не получилось: {failed}' if failed else '') +
                f'. Всего в пуле: {n}.\nЭти фото приходят с «Я скучала… вот, держи 💋», утренним приветом и её моментами дня.',
                reply_markup=kb)
        except Exception:
            logger.exception('gift pool generation failed')
            await bot.send_message(admin_id, '⚠️ Генерация оборвалась, посмотри ошибки в админке.')
        finally:
            GIFT_POOL_RUNNING.discard(admin_id)

    asyncio.create_task(_run())


@dp.callback_query(F.data == 'admin:prophoto:clear')
async def admin_prophoto_clear_ask(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    from services import retention_features_service as rfs
    n = len(rfs.list_proactive_photos())
    await cq.answer()
    await cq.message.answer(
        f'Удалить все {n} кадров пула? Это нельзя отменить. Лучше сначала сгенерируй новые, '
        'а потом удали старые — иначе подарки придут без фото.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='🧹 Да, удалить все', callback_data='admin:prophoto:clear:yes')],
            [InlineKeyboardButton(text='❌ Оставить', callback_data='admin:prophoto')],
        ]))


@dp.callback_query(F.data == 'admin:prophoto:clear:yes')
async def admin_prophoto_clear(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    from services import retention_features_service as rfs
    removed = sum(1 for p in rfs.list_proactive_photos() if rfs.delete_proactive_photo(p['id']))
    kb, n = admin_prophoto_keyboard()
    await cq.answer(f'удалено {removed}')
    await cq.message.answer(f'🧹 Удалено: {removed}. В пуле теперь: {n}.', reply_markup=kb)


@dp.callback_query(F.data.startswith('admin:prophoto:del:'))
async def admin_prophoto_del(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    try:
        photo_id = int(cq.data.split(':', 3)[3])
    except (TypeError, ValueError):
        await cq.answer('не то id', show_alert=True)
        return
    from services import retention_features_service as rfs
    removed = rfs.delete_proactive_photo(photo_id)
    kb, n = admin_prophoto_keyboard()
    await cq.answer('удалено' if removed else 'не найдено')
    await cq.message.answer(f'📸 В пуле теперь: {n}', reply_markup=kb)


@dp.message(lambda m: m.from_user is not None and m.from_user.id in PROPHOTO_WAIT,
            (F.photo | F.animation | F.video))
async def admin_prophoto_upload(message: types.Message):
    """V3.47.2/3: a photo, GIF or video the admin sends is appended to the pool.
    V3.56.7: it lands under the character picked right before the upload."""
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    from services import retention_features_service as rfs
    if message.photo:
        file, kind, ctype = message.photo[-1], 'photo', 'image/jpeg'
    elif message.animation:
        file, kind, ctype = message.animation, 'gif', (message.animation.mime_type or 'video/mp4')
    else:
        file, kind, ctype = message.video, 'video', (message.video.mime_type or 'video/mp4')
    limit = rfs.proactive_max_bytes(kind)
    if (file.file_size or 0) > limit:
        await message.answer(f'файл тяжелее {limit // (1024 * 1024)} MB — пришли полегче.')
        return
    buf = io.BytesIO()
    await bot.download(file.file_id, destination=buf)
    ok = rfs.add_proactive_photo(buf.getvalue(), ctype, kind,
                                 character_id=PROPHOTO_WAIT.get(message.from_user.id))
    # V3.61.9: the wait stays open — an album of 20 lands in one go. One
    # summary after the pack settles instead of a reply per photo.
    admin_id = message.from_user.id
    batch = PROPHOTO_BATCH.setdefault(admin_id, {'ok': 0, 'fail': 0, 'task': None})
    batch['ok' if ok else 'fail'] += 1
    if batch.get('task') and not batch['task'].done():
        batch['task'].cancel()

    async def _summary():
        await asyncio.sleep(2.5)
        b = PROPHOTO_BATCH.get(admin_id) or {}
        await bot.send_message(
            admin_id,
            f"✅ Добавлено: {b.get('ok', 0)}" + (f", не сохранилось: {b['fail']}" if b.get('fail') else '') +
            '. Присылай ещё или нажми «✅ Готово».',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text='✅ Готово', callback_data='admin:prophoto:done')]]))

    batch['task'] = asyncio.create_task(_summary())


@dp.callback_query(F.data == 'admin:prophoto:done')
async def admin_prophoto_done(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    PROPHOTO_WAIT.pop(cq.from_user.id, None)
    b = PROPHOTO_BATCH.pop(cq.from_user.id, None) or {}
    if b.get('task') and not b['task'].done():
        b['task'].cancel()
    kb, n = admin_prophoto_keyboard()
    await cq.answer()
    await cq.message.answer(f"✅ Загрузка закончена: +{b.get('ok', 0)}. В пуле: {n}.", reply_markup=kb)


# ── V3.47.4: character-page carousel — admin-set visuals, storefront only ──
# The owner can hang any pictures on the character page without touching the
# canonical references: generated photos keep the locked appearance. Shots are
# stored in PostgreSQL (survives redeploys) and the URL carries the row id.
def admin_pgal_keyboard(character_id: str):
    shots = webapp_service.page_gallery_shots(character_id)
    rows = [[InlineKeyboardButton(text='➕ Добавить фото', callback_data=f'admin:pgal:add:{character_id}')]]
    del_row = [InlineKeyboardButton(text=f'🗑 {i + 1}', callback_data=f'admin:pgal:del:{character_id}:{sh["id"]}')
               for i, sh in enumerate(shots)]
    for i in range(0, len(del_row), 6):
        rows.append(del_row[i:i + 6])
    if shots:
        rows.append([InlineKeyboardButton(text='🧹 Очистить всё', callback_data=f'admin:pgal:clear:{character_id}')])
    rows.append([InlineKeyboardButton(text='⬅️ Карточка', callback_data=f'admin:card:{character_id}')])
    return InlineKeyboardMarkup(inline_keyboard=rows), len(shots)


@dp.callback_query(F.data.startswith('admin:pgal:add:'))
async def admin_pgal_wait(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    character_id = cq.data.split(':', 3)[3]
    PGAL_MEDIA_WAIT[cq.from_user.id] = character_id
    await cq.answer()
    await cq.message.answer(
        f'📥 Пришли фото для карусели «{character_id}» — можно несколько подряд, '
        f'каждое встанет следующим слайдом (до 8 MB, максимум '
        f'{webapp_service.PAGE_GALLERY_MAX_SHOTS}).\n\n'
        '⚠️ Это только витрина: на генерацию фото не влияет.\n\n'
        '/cancel — закончить')


@dp.callback_query(F.data.startswith('admin:pgal:del:'))
async def admin_pgal_del(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    parts = cq.data.split(':', 4)
    try:
        character_id, shot_id = parts[3], int(parts[4])
    except (IndexError, ValueError):
        await cq.answer('не то id', show_alert=True)
        return
    removed = webapp_service.delete_page_gallery_shot(shot_id)
    kb, n = admin_pgal_keyboard(character_id)
    await cq.answer('удалено' if removed else 'не найдено')
    await cq.message.answer(f'🎠 Фото в карусели «{character_id}»: {n}', reply_markup=kb)


@dp.callback_query(F.data.startswith('admin:pgal:clear:'))
async def admin_pgal_clear(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    character_id = cq.data.split(':', 3)[3]
    removed = webapp_service.clear_page_gallery(character_id)
    kb, n = admin_pgal_keyboard(character_id)
    await cq.answer(f'убрано: {removed}' if removed else 'пусто')
    await cq.message.answer(
        f'🎠 Карусель «{character_id}» очищена — страница вернулась на канонические фото.'
        if removed else f'🎠 В карусели «{character_id}» и так нет фото',
        reply_markup=kb)


@dp.callback_query(F.data.startswith('admin:pgal:')
                   & ~F.data.startswith('admin:pgal:add:')
                   & ~F.data.startswith('admin:pgal:del:')
                   & ~F.data.startswith('admin:pgal:clear:'))
async def admin_pgal_view(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    character_id = cq.data.split(':', 2)[2]
    kb, n = admin_pgal_keyboard(character_id)
    await cq.answer()
    await cq.message.answer(
        f'🎠 Карусель на странице «{character_id}» — фото: {n} из '
        f'{webapp_service.PAGE_GALLERY_MAX_SHOTS}\n\n'
        'Эти картинки видны только в витрине (карусель страницы персонажа) и '
        'никак не влияют на генерацию — каноны не трогаем. Пустая карусель = '
        'показываются канонические фото.',
        reply_markup=kb)


@dp.message(lambda m: m.from_user is not None and m.from_user.id in PGAL_MEDIA_WAIT, F.photo)
async def admin_pgal_upload(message: types.Message):
    """V3.47.4: every photo the admin sends becomes the next carousel slide."""
    character_id = PGAL_MEDIA_WAIT.get(message.from_user.id)
    if not character_id or message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    photo = message.photo[-1]
    if (photo.file_size or 0) > webapp_service.PAGE_GALLERY_MAX_BYTES:
        await message.answer('файл тяжелее 8 MB — пришли полегче.')
        return
    buf = io.BytesIO()
    await bot.download(photo.file_id, destination=buf)
    ok = webapp_service.add_page_gallery_shot(character_id, buf.getvalue(), 'image/jpeg')
    kb, n = admin_pgal_keyboard(character_id)
    if not ok:
        PGAL_MEDIA_WAIT.pop(message.from_user.id, None)
        await message.answer(
            f'⚠️ Не удалось добавить (лимит {webapp_service.PAGE_GALLERY_MAX_SHOTS} фото или размер).',
            reply_markup=kb)
        return
    # stay in the wait state — the owner usually sends the whole set at once
    await message.answer(
        f'✅ Фото №{n} в карусели «{character_id}». Присылай следующее или /cancel.',
        reply_markup=kb)


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
    # V3.44.18: the money block. Until now /stats could only show a photo cost
    # that counted delivered images at a per-engine price (Gemini: $0), and said
    # nothing at all about LLM spend — so «$0.00» sat next to a real OpenRouter
    # bill. These lines name both streams and who ate them.
    from services import spend_service
    spend_lines = '\n'.join(spend_service.format_spend_lines(spend_service.spend_snapshot()))
    await cq.message.answer(
        '📊 Статистика пользователей\n\n'
        f'👥 всего: {snap["users_total"]} · новых за 24ч: {snap["new_24h"]} · за 7д: {snap["new_7d"]}\n'
        f'🟢 активны: за 24ч {snap["users_24h"]} · за 7д {snap["users_7d"]}\n'
        f'⭐ Premium активен: {snap["premium_active"]}\n'
        f'💬 сообщения пользователей: за 24ч {snap["messages_24h"]} · за 7д {snap["messages_7d"]}\n'
        f'📸 медиа за 24ч: фото {snap["photos_24h"]} · кружки {snap["circles_24h"]} · видео {snap["videos_24h"]}\n'
        f'🎨 студия: ✅{photo_ok} ❌{photo_fail} (успешность {studio_rate:.0f}%)\n'
        f'🔁 удержание: D1 {snap["d1_retention"]:.0f}% · D7 {snap["d7_retention"]:.0f}%\n'
        f'🚪 воронка 30д: /start {snap["funnel"]["started"]} → 18+ {snap["funnel"]["consent"]} → написали {snap["funnel"]["first_message"]}\n'
        f'💳 оплата 30д: видели предложение {snap["pay_funnel"]["offer"]} → открыли счёт {snap["pay_funnel"]["invoice"]} → оплатили {snap["pay_funnel"]["paid"]}\n'
        f'💰 Stars за 30д: {snap["stars_30d"]} · себестоимость фото за 24ч: ${snap["photo_cost_24h"]:.2f}\n\n'
        f'{spend_lines}\n\n'
        f'🏆 топ персонажей (7д):\n{top_lines}\n\n'
        f'{_sources_block(snap)}'
    )


def _source_label(tag: str) -> str:
    if tag in ('', 'organic'):
        return 'без метки (поиск, прямой заход, переслали бота)'
    if tag == 'ref':
        return 'по приглашению друга'
    if tag.startswith('share:'):
        return 'по фото, которым поделились'
    if tag.startswith('link:'):
        return f'ссылка ?start={tag[5:]}'
    return f'метка src_{tag}'


def _sources_block(snap: dict) -> str:
    """V3.62.6: where new users came from — the 30d breakdown was computed
    since V3.47.0 but never shown on the screen."""
    def lines(rows):
        return '\n'.join(f'· {_source_label(tag)} — {cnt}' for tag, cnt in rows) or '· нет новых'
    quality = '\n'.join(
        f'· {_source_label(tag)}: {n} → написали {w} → вернулись D1 {b} → оплатили {p}'
        for tag, n, w, b, p in (snap.get('source_quality') or [])) or '· нет новых'
    return (f'📥 откуда пришли новые (24ч):\n{lines(snap.get("sources_24h") or [])}\n'
            f'📥 за 7д:\n{lines(snap.get("sources_7d") or [])}\n'
            f'🎯 качество источников (30д):\n{quality}')


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


@dp.callback_query(F.data == 'admin:roi')
async def admin_roi_button(cq: types.CallbackQuery):
    """V3.141.0: owner ТЗ (Фаза 2, Задача 3) — [оплаты юзеров с меткой X] минус
    [их затраты на API: LLM + картинки] = чистая прибыль источника. Минусовый
    трафик видно сразу, плюсовый можно масштабировать."""
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    await cq.answer()
    from services import analytics_service
    roi = await asyncio.to_thread(analytics_service.source_roi, 30)
    lines = []
    for r in roi['rows'][:15]:
        sign = '🟢' if r['profit_rub'] >= 0 else '🔴'
        lines.append(
            f"{sign} {_source_label(r['tag'])}\n"
            f"   доход {r['revenue_rub']:.0f} ₽ − API {r['cost_rub']:.0f} ₽ "
            f"(LLM {r['llm_rub']:.0f} + фото {r['image_rub']:.0f}) = {r['profit_rub']:+.0f} ₽\n"
            f"   платили {r['payers']} · тратили API {r['cost_users']}"
        )
    body = '\n'.join(lines) or '· пока нет данных — оплаты и затраты появятся после первых покупок'
    note = f"\n\nкурс: 1 USD = {roi['usd_rub']:.0f} ₽ (env ROI_USD_RUB)"
    if roi['unattributed_rub'] > 0:
        note += (f"\n⚠️ не привязано к юзерам: {roi['unattributed_rub']:.0f} ₽ API "
                 '(строки до V3.141.0 и фоновые задачи без метки)')
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='⬅️ Админка', callback_data='admin:home')],
    ])
    await cq.message.answer(f'📈 ROI источников за 30д (доход − API):\n\n{body}{note}', reply_markup=markup)


@dp.message(Command('cancel'))
async def cancel_admin_edit(message: types.Message):
    # V3.149.0: /cancel also steps out of the ⏰/📝 wait — the answer would
    # otherwise be swallowed by the utility state.
    if _utility_wait_of(message.from_user.id):
        _drop_utility_wait(message.from_user.id)
        await message.answer('отменил, возвращаюсь в обычный чат')
        return
    if message.from_user.id in PGAL_MEDIA_WAIT:
        character_id = PGAL_MEDIA_WAIT.pop(message.from_user.id)
        kb, _n = admin_pgal_keyboard(character_id)
        await message.answer('отменено', reply_markup=kb)
        return
    if message.from_user.id in PROPHOTO_WAIT:
        PROPHOTO_WAIT.pop(message.from_user.id, None)
        PROPHOTO_TAG_WAIT.pop(message.from_user.id, None)
        kb, _n = admin_prophoto_keyboard()
        await message.answer('отменено', reply_markup=kb)
        return
    if message.from_user.id in BADGE_MEDIA_WAIT:
        BADGE_MEDIA_WAIT.pop(message.from_user.id, None)
        await message.answer('отменено', reply_markup=admin_badges_keyboard())
        return
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
    # V3.55.5: abort the promo-code creation wizard.
    if message.from_user.id in _admin_promo_sessions:
        _admin_promo_sessions.pop(message.from_user.id, None)
        await message.answer('промокод не создан', reply_markup=admin_keyboard())
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
        '/promo КОД — активировать промокод\n'
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
    text = format_profile_summary(summary)
    # V3.55.5: daily streak gift row + claim button — replaces the V3.44.0
    # bonus wheel (two daily bonuses on one rail made no sense, and the wheel
    # paid fractional peaches into an INTEGER balance).
    from services import gift_service
    markup = None
    try:
        gs = gift_service.gift_status(message.from_user.id)
    except Exception:
        gs = None
    if gs and gs.get('enabled'):
        lang = user_lang(message.from_user.id)
        if gs.get('claimed_today'):
            if lang == EN:
                text += f"\n🎁 Gift: day {gs['streak']}/7 — already taken, back after 03:00"
                label = '🎁 Already claimed — after 03:00'
            else:
                text += f"\n🎁 Подарок: день {gs['streak']}/7 — уже взят, обновится в 03:00"
                label = '🎁 Уже взят — жди 03:00'
        elif gs.get('capped'):
            if lang == EN:
                text += f'\n🎁 Gift: piggy bank full ({DAILY_GIFT_BALANCE_CAP} 🍑) — spend some, then claim'
                label = '🎁 Piggy bank full'
            else:
                text += f'\n🎁 Подарок: копилка полная ({DAILY_GIFT_BALANCE_CAP} 🍑) — потрать и забирай'
                label = '🎁 Копилка полная'
        else:
            # slot of the NEXT claim within the 1..7 cycle (7 wraps to 1)
            next_day = ((gs.get('streak') or 0) % 7) + 1
            amount = gs.get('amount', 1)
            if lang == EN:
                text += f'\n🎁 Gift: day {next_day}/7 — +{amount} 🍑'
                label = f'🎁 Claim +{amount} 🍑'
            else:
                text += f'\n🎁 Подарок: день {next_day}/7 — +{amount} 🍑'
                label = f'🎁 Забрать +{amount} 🍑'
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data='gift:claim')]])
    await message.answer(text, reply_markup=markup)


@dp.callback_query(F.data == 'gift:claim')
async def gift_claim_cb(cq: types.CallbackQuery):
    """V3.55.5: claim today's streak gift from /profile. All the money rules
    (once-per-day, 7th-day jackpot, 15 🍑 cap without eating the day) live in
    gift_service.claim_daily_gift — this is just the Telegram skin."""
    from services import gift_service
    res = gift_service.claim_daily_gift(cq.from_user.id)
    lang = user_lang(cq.from_user.id)
    if res.get('ok'):
        amount, streak = res['amount'], res['streak']
        if lang == EN:
            toast = f'+{amount} 🍑'
            body = (f'🎉 day {streak}/7 — jackpot +{amount} 🍑! Balance: {res["balance"]} 🍑'
                    if amount > 1 else
                    f'🎁 +{amount} 🍑 for day {streak}/7. Balance: {res["balance"]} 🍑 — come back tomorrow!')
        else:
            toast = f'+{amount} 🍑'
            body = (f'🎉 день {streak}/7 — джекпот +{amount} 🍑! Баланс: {res["balance"]} 🍑'
                    if amount > 1 else
                    f'🎁 +{amount} 🍑 за день {streak}/7. Баланс: {res["balance"]} 🍑 — завтра будет ещё!')
        await cq.answer(toast)
        await cq.message.answer(body)
        return
    error = res.get('error')
    if res.get('capped') or error == 'capped':
        await cq.answer('копилка полная' if lang != EN else 'piggy bank full', show_alert=True)
    elif error == 'duplicate':
        await cq.answer('уже взято — обнулится в 03:00' if lang != EN else 'already claimed — 03:00', show_alert=True)
    elif error == 'consent':
        await cq.answer('сначала /start' if lang != EN else 'press /start first', show_alert=True)
    elif error == 'inactive':
        await cq.answer('подарок сейчас выключен' if lang != EN else 'gift is off right now', show_alert=True)
    else:
        await cq.answer('не получилось, попробуй позже', show_alert=True)


PROMO_ERROR_RU = {
    'unknown': 'такого кода я не нашла 🤔 проверь раскладку и пробелы',
    'expired': 'срок действия кода истёк ⏳',
    'exhausted': 'все активации по этому коду уже разобрали 😔',
    'inactive': 'этот код отключён',
    'duplicate': 'ты этот код уже активировал — повтор нельзя',
    'consent': 'сначала нужно пройти /start и подтвердить условия',
    'auth': 'сначала нажми /start',
}
PROMO_ERROR_EN = {
    'unknown': 'I could not find that code 🤔 check spelling and spaces',
    'expired': 'that code has expired ⏳',
    'exhausted': 'all activations of that code are taken 😔',
    'inactive': 'that code is disabled',
    'duplicate': 'you already redeemed that code',
    'consent': 'press /start and accept the terms first',
    'auth': 'press /start first',
}


@dp.message(Command('promo'))
async def promo_cmd(message: types.Message, command: CommandObject):
    """V3.55.5: /promo CODE — redeem a promo code for peaches. Codes are minted
    in the admin panel («🎟 Промокоды»); one redemption per user per code, the
    same rail lives in the Mini App shop."""
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    from services import gift_service
    lang = user_lang(message.from_user.id)
    code = (command.args or '').strip().upper()
    if not code:
        rows = []
        if PUBLIC_BASE_URL:
            app_label = '🛍 Open the app (shop)' if lang == EN else '🛍 Открыть приложение (магазин)'
            rows.append([InlineKeyboardButton(text=app_label, web_app=types.WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp'))])
        await message.answer(
            '🎟 Промокод активируется так: /promo КОД\n\n'
            'или в приложении — блок «Промокод» в магазине.\n'
            'Коды дают в наших постах и у партнёров.' if lang != EN else
            '🎟 Redeem a promo code: /promo CODE\n\n'
            'or in the app — the promo field inside the shop.\n'
            'We hand codes out in our posts and via partners.',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None,
        )
        return
    res = gift_service.redeem_promo(message.from_user.id, code)
    if res.get('ok'):
        await message.answer(
            f'🎁 Код {code} активирован: +{res["credits"]} 🍑! Баланс: {res["balance"]} 🍑' if lang != EN else
            f'🎁 Code {code} redeemed: +{res["credits"]} 🍑! Balance: {res["balance"]} 🍑')
        return
    err = res.get('error', 'unknown')
    await message.answer((PROMO_ERROR_RU if lang != EN else PROMO_ERROR_EN).get(err, PROMO_ERROR_RU['unknown']))


@dp.message(Command('referral', 'invite', 'partner'))
async def referral_cmd(message: types.Message, who: types.User | None = None):
    """V3.37.0: the partner screen — stats, personal link, withdrawal, FAQ.

    The «💰 Партнёрка» button lands here: invited count + earned rubles + the
    live balance, one tap to copy the link, one tap to request a payout.

    V3.95.0: `who` is the person who tapped. From an inline button the
    message is the bot's own, so its from_user is the bot — everyone then got
    the same ref_<bot id> link and the bot's empty stats.
    """
    who = who or message.from_user
    ensure_user(who.id, who.first_name, language_code=who.language_code)
    from services import partner_service
    from config import PARTNER_MIN_PAYOUT_RUB, PARTNER_PAYOUT_METHODS, REFERRAL_COMMISSION_PCT
    user = get_user(who.id)
    stats = partner_service.partner_stats(user.id) if user else {'invited': 0, 'earned_rub': 0.0, 'balance_rub': 0.0, 'pending_payout_id': None}
    try:
        me = await bot.get_me()
        link = referral_link(me.username or 'bot', who.id)
    except Exception:
        await message.answer('не удалось получить ссылку прямо сейчас, попробуй позже.')
        return
    lang = user_lang(who.id)
    pct = int(REFERRAL_COMMISSION_PCT) if float(REFERRAL_COMMISSION_PCT).is_integer() else REFERRAL_COMMISSION_PCT
    if lang == EN:
        text = (
            f'💰 AnnaBot Partner program\n\n'
            f'Invite friends and earn {pct}% of EVERY purchase they make — forever, not just once.\n\n'
            f'👥 friends invited: {stats["invited"]}\n'
            f'💵 total earned: {stats["earned_rub"]:g} ₽\n'
            f'💳 available to withdraw: {stats["balance_rub"]:g} ₽\n\n'
            f'🔗 your link:\n{link}\n\n'
            f'Once a friend who came through it writes her {REFERRAL_QUALIFY_MESSAGES} messages, they get {REFERRAL_INVITEE_CREDITS} 🍑 and you get {REFERRAL_REFERRER_CREDITS} 🍑. '
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
            f'когда друг, пришедший по ней, напишет ей {REFERRAL_QUALIFY_MESSAGES} сообщений, он получит {REFERRAL_INVITEE_CREDITS} 🍑, а ты — {REFERRAL_REFERRER_CREDITS} 🍑. '
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
    await referral_cmd(cq.message, cq.from_user)


@dp.callback_query(F.data == 'credits:open')
async def credits_open(cq: types.CallbackQuery):
    """V3.42.1: the «🍑 Пополнить персики» CTA on the welcome screen — same
    app-shop entry as the reply-keyboard credits button (peaches are bought in
    the Mini App «Магазин» tab)."""
    await cq.answer()
    await _send_peach_shop(cq.message, cq.from_user)


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
    # V3.47.0: opening /contest also settles any bonus tier the user has newly
    # crossed (invite-count ladder), then shows their progress and the money
    # affiliate board — real earners, not just volume.
    try:
        newly = maybe_grant_referral_tiers(message.from_user.id)
    except Exception:
        logger.exception('contest tier grant failed user=%s', message.from_user.id)
        newly = []
    if newly:
        for g in newly:
            parts = ([f'+{g["credits"]} 🍑'] if g['credits'] else []) + (
                [f'{g["premium_days"]} дн. Premium'] if g['premium_days'] else [])
            reward = ' и '.join(parts)
            lines.append(f'🎁-tier пройден: {g["invites"]} приглашений → {reward}')
        lines.append('')
    try:
        prog = referral_tier_progress(message.from_user.id)
    except Exception:
        prog = {'count': 0, 'tiers': [], 'next': None}
    if prog['tiers']:
        lines.append('📊 бонус-тиры (за количество друзей):')
        for t in prog['tiers']:
            mark = '✅' if t['granted'] else ('▶' if t['reached'] else '🔒')
            bonus = ' '.join(([f'+{t["credits"]} 🍑'] if t['credits'] else []) + (
                [f'+{t["premium_days"]}д Premium'] if t['premium_days'] else []))
            lines.append(f"  {mark} {t['invites']} пригл. → {bonus}")
        if prog['next']:
            need = prog['next']['invites'] - prog['count']
            lines.append(f"  осталось {need} до следующего тира 🔥")
        lines.append('')
    try:
        from services import partner_service as _ps
        earners = _ps.affiliate_leaderboard(limit=5, period_days=30)
    except Exception:
        earners = []
    if earners:
        lines.append('💰 топ партнёров по заработку за 30 дней:')
        medals = {1: '🥇', 2: '🥈', 3: '🥉'}
        for row in earners:
            medal = medals.get(row['rank'], f"{row['rank']}.")
            me = ' (это ты!)' if row['telegram_id'] == message.from_user.id else ''
            lines.append(f"  {medal} {row['name']}{me} — {row['earned_rub']:g} ₽ · {row['invited']} пригл.")
        lines.append('')
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

@dp.message(Command('wardrobe'))
async def wardrobe_cmd(message: types.Message):
    """V3.114.0: «👗 Гардероб» lives in the app — the button opens her chat with the wardrobe sheet."""
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    en = user_lang(message.from_user.id) == EN
    if not PUBLIC_BASE_URL:
        await message.answer('👗 …')
        return
    await message.answer(
        '👗 Give her clothes and things for her room: she wears them in her photos and remembers who gave them.' if en else
        '👗 Дари ей одежду и вещи для комнаты: она будет в них на фото и помнит, кто подарил.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text='👗 Open the wardrobe' if en else '👗 Открыть гардероб',
            web_app=types.WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp?open=wardrobe'))]]))


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


# V3.44.0: admin photo replacement tool — /setcardphoto <character_id> then send photo
_CARD_PHOTO_PENDING: dict[int, str] = {}


@dp.message(Command('setcardphoto'))
async def set_card_photo_cmd(message: types.Message):
    """Admin: replace a character's card photo. Usage: /setcardphoto emily_01"""
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    parts = (message.text or '').split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        chars = ', '.join(c for c in webapp_service._FACE_REFERENCES.keys())
        await message.answer(
            f'📷 Использование: /setcardphoto <character_id>\n'
            f'Затем отправь фото (или несколько) — я сохраню их как галерею.\n\n'
            f'Доступные персонажи: {chars}'
        )
        return
    char_id = parts[1].strip()
    if char_id not in webapp_service._FACE_REFERENCES:
        await message.answer(f'❌ Персонаж «{char_id}» не найден.\nДоступные: {", ".join(webapp_service._FACE_REFERENCES.keys())}')
        return
    _CARD_PHOTO_PENDING[message.from_user.id] = char_id
    folder_name = webapp_service._FACE_REFERENCES[char_id][1]
    await message.answer(f'✅ Отправь фото для «{char_id}» (папка: {folder_name}).\n' +
                         f'Можно несколько — первое станет лицом, второе — обликом.')


@dp.message(F.photo, lambda m: m.from_user.id in _CARD_PHOTO_PENDING and m.from_user.id in ADMIN_TELEGRAM_IDS)
async def handle_card_photo(message: types.Message):
    """Admin: save uploaded photo to character's reference folder."""
    char_id = _CARD_PHOTO_PENDING.pop(message.from_user.id, None)
    if not char_id:
        return
    rel = webapp_service._FACE_REFERENCES.get(char_id)
    if not rel:
        await message.answer('❌ Внутренняя ошибка: персонаж не найден.')
        return
    folder = ROOT / 'data' / rel[0] / rel[1]
    folder.mkdir(parents=True, exist_ok=True)
    # Get the largest photo resolution
    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    file_url = f'https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.path}'
    # Determine next slot number
    existing = sorted(folder.glob('*.png'))
    next_num = len(existing)
    filename = f'{next_num:02d}_{rel[1]}_reference_{next_num - 1 if next_num > 1 else 0}.png'
    if next_num == 0:
        filename = f'00_{rel[1]}_canonical_face.png'
    elif next_num == 1:
        filename = f'01_{rel[1]}_canonical_look.png'
    # Download and save
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.get(file_url) as resp:
            if resp.status == 200:
                dest = folder / filename
                dest.write_bytes(await resp.read())
                # Clear gallery cache so new photo shows immediately
                webapp_service._GALLERY_CACHE.pop(char_id, None)
                await message.answer(f'✅ Фото сохранено: {filename}\nГалерея обновлена!')
            else:
                await message.answer(f'❌ Не удалось скачать фото (HTTP {resp.status})')

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
        types.InlineKeyboardButton(text='🎬 Оживить · Premium на месяц', callback_data=f'gallery:animate:{delivery_id}'),
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
    if q.get('path'):
        where = 'романтики' if q['path'] == 'romance' else 'страсти'
        await cq.answer(f'🔒 «{q["title"]}» — история пути {where}. Она откроется только на этом пути.', show_alert=True)
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

async def _deliver_story_result(cq, result, quest_key, route_key, *, crown=False):
    # V3.51.0: shared delivery for a first choice and its second beat — the
    # story line, her live reaction, any threshold scene (with a photo on the
    # deep crossings), the route's reward photo, then the beat prompt or the
    # routes keyboard. The reaction is already persisted to the shared dialog by
    # the resolver, so the Mini App shows it too.
    prefix = '👑 Premium replay\n\n' if crown else ''
    await cq.message.answer(prefix + (result.get('result_text') or ''))
    if result.get('reaction'):
        await cq.message.answer(result['reaction'])
    for ev in result.get('path_events', []):
        if ev.get('text'):
            await cq.message.answer('💫 ' + ev['text'])
        if ev.get('photo_scene'):
            await _start_photo_background(cq.message.chat.id, cq.from_user.id, PhotoRequest(scene=ev['photo_scene']), 'story')
    scene = result.get('photo_scene')
    if scene:
        await _start_photo_background(cq.message.chat.id, cq.from_user.id, PhotoRequest(scene=scene), 'story')
    beat = result.get('beat_options')
    if beat:
        await cq.message.answer('💭 ' + beat['prompt'], reply_markup=quest_beat_keyboard(quest_key, route_key))
    else:
        await cq.message.answer('Твой выбор стал частью вашей истории 🌿', reply_markup=quest_routes_keyboard(cq.from_user.id, quest_key))

@dp.callback_query(F.data.startswith('quest:route:'))
async def quest_route_cb(cq: types.CallbackQuery):
    _,_,quest_key,route_key=cq.data.split(':',3)
    cid=get_user_character(cq.from_user.id); uname=cq.from_user.first_name or ''
    result=await resolve_story_choice(cq.from_user.id,cid,quest_key,route_key,paid_replay=False,user_name=uname)
    if result.get('needs_payment'):
        if consume_premium_replay(cq.from_user.id,quest_key,route_key):
            result=await resolve_story_choice(cq.from_user.id,cid,quest_key,route_key,paid_replay=True,user_name=uname)
            await cq.answer('Premium replay использован ✨')
            await _deliver_story_result(cq,result,quest_key,route_key,crown=True)
            return
        offer_id=create_replay_offer(cq.from_user.id,quest_key,route_key)
        await cq.answer()
        await send_stars_invoice(cq.message.chat.id,'Альтернативная история',f'Посмотреть другой вариант: {get_quest(quest_key)["title"]}',f'quest_replay:{offer_id}',QUEST_REPLAY_STARS)
        return
    await cq.answer(); track_event(ensure_user(cq.from_user.id),'quest_route_completed',metadata={'quest':quest_key,'route':route_key,'canonical':result.get('canonical',False)})
    await _deliver_story_result(cq,result,quest_key,route_key)

@dp.callback_query(F.data.startswith('quest:beat:'))
async def quest_beat_cb(cq: types.CallbackQuery):
    _,_,quest_key,route_key,opt_key=cq.data.split(':',4)
    cid=get_user_character(cq.from_user.id); uname=cq.from_user.first_name or ''
    result=await resolve_story_beat(cq.from_user.id,cid,quest_key,route_key,opt_key,user_name=uname)
    if result.get('error'):
        await cq.answer('это продолжение уже закрыто 🙂', show_alert=True); return
    await cq.answer(); track_event(ensure_user(cq.from_user.id),'quest_beat_completed',metadata={'quest':quest_key,'route':route_key,'beat':opt_key})
    await _deliver_story_result(cq,result,quest_key,route_key)

async def _run_video_background(chat_id: int, telegram_id: int, delivery_id: int, charge_id: str | None = None, motion_preset: str | None = None) -> None:
    """Animate a delivered photo with automatic engine fallback.

    V3.69.0: SpicyAPI is the only engine (owner: photos and video on one
    provider). A paid run is refunded when it fails.
    """
    # V3.46.0: mission — ordering any animated video/circle unlocks «Живое
    # видео» (voucher). All order paths funnel through here.
    await _notify_unlock(chat_id, telegram_id, 'first_video')
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
        engines.extend(video_engines())  # V3.69.0: SpicyAPI only
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
    """Платное оживление за Stars; генерация для администратора остаётся бесплатной."""
    uid = ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    track_event(uid, 'video_animate_click', metadata={'delivery_id': delivery['id'], 'preset': motion_preset or 'auto'})
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        track_event(uid, 'video_invoice', metadata={'delivery_id': delivery['id'], 'stars': VIDEO_COST_STARS})
        await send_stars_invoice(
            cq.message.chat.id,
            'Оживление фото',
            'Короткое видео из этого фото',
            f'video:{delivery["id"]}:{motion_preset or "auto"}',
            VIDEO_COST_STARS,
        )
        return
    track_event(uid, 'video_admin_used', metadata={'delivery_id': delivery['id']})
    _video_jobs[cq.from_user.id] = _spawn_job(
        'video', cq.from_user.id,
        _run_video_background(cq.message.chat.id, cq.from_user.id, delivery['id'], None, motion_preset=motion_preset),
        payload={'preset': motion_preset or 'auto'},
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
    'Vertical handheld front-camera selfie video, close-up of her face and shoulders, '
    'like a Telegram video circle she records for her boyfriend. She looks straight into '
    'the lens, smiles and talks to him, the phone held at arm\'s length with a slight natural '
    'hand shake. She says in Russian, in a soft, cute, natural young female voice, clearly '
    'and with lip sync: "{phrase}". Light natural head movement, a small laugh or a wink at '
    'the end. Keep her face, hair, makeup and outfit identical to the photo. Same place and '
    'light. No wardrobe change, no extra people, no text on screen. Photorealistic.'
)
# V3.20.1 fallback lines; V3.69.0: the circle normally says a line from the
# dialogue (her last reply) — see _circle_phrase.
CIRCLE_PHRASES = (
    'привет, это я 😘 скучал по мне?',
    'держи мой кружочек 💋 думай обо мне',
    'смотри, как я тебе улыбаюсь…',
)


def _circle_phrase(telegram_id: int, character_id: str | None = None) -> str:
    """V3.69.0: what she says in the circle — the first sentence or two of her
    last reply in this dialogue (≤ ~5 s of speech), else a stock line."""
    import re as _re
    try:
        user = get_user(telegram_id)
        cid = character_id or get_user_character(telegram_id)
        history = webapp_service.api_chat_history(user.id if user else 0, cid, 10)
        text = next((m['content'] for m in reversed(history)
                     if m['role'] == 'assistant' and not m.get('media_url') and (m.get('content') or '').strip()), '')
    except Exception:
        logger.warning('circle phrase lookup failed user=%s', telegram_id, exc_info=True)
        text = ''
    text = _re.sub(r'[*_`#\[\]<>"]', '', text or '')
    text = ''.join(ch for ch in text if ch.isalnum() or ch in ' .,!?:;-…()«»\'\n')
    text = _re.sub(r'\s+', ' ', text).strip()
    if not text:
        return random.choice(CIRCLE_PHRASES)
    out = ''
    for sent in _re.split(r'(?<=[.!?…])\s+', text):
        if out and len(out) + len(sent) > 90:
            break
        out = f'{out} {sent}'.strip()
        if len(out) >= 40:
            break
    if len(out) > 90:
        out = out[:90].rsplit(' ', 1)[0] + '…'
    return out or random.choice(CIRCLE_PHRASES)


@dp.callback_query(F.data == 'video:circle')
async def circle_cb(cq: types.CallbackQuery):
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True); return
    uid = ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if not _any_video_engine():
        await cq.answer(_video_unavailable_text(cq.from_user.id), show_alert=True); return
    if cq.from_user.id in _video_jobs and not _video_jobs[cq.from_user.id].done():
        await cq.answer('Одно видео уже создаётся 🎬', show_alert=True); return
    delivery = get_latest_photo_delivery(cq.from_user.id)
    if not delivery or not delivery.get('telegram_file_id'):
        await cq.answer('Сначала попроси у меня фото — кружочек сниму с последнего кадра.', show_alert=True); return
    # V3.71.0: every circle costs CIRCLE_PEACH_COST peaches, Premium included —
    # it is the priciest render we make. Charged up front, refunded on failure.
    charge = None
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        if not spend_peaches(cq.from_user.id, CIRCLE_PEACH_COST, paid_only=True):
            track_event(uid, 'circle_paywall_view', metadata={'reason': 'peaches'})
            await cq.answer(f'Кружочек стоит {peach_num(CIRCLE_PEACH_COST)} 🍑 — персиков не хватает', show_alert=True)
            await cq.message.answer(
                f'🎥 кружочек — короткое видео, как будто я записываю его тебе лично 😌\n'
                f'стоит {peach_num(CIRCLE_PEACH_COST)} купленных 🍑, а у тебя {peach_num(get_paid_peaches(cq.from_user.id))} 🍑.' + _bonus_peach_note(cq.from_user.id),
                reply_markup=peaches_keyboard(cq.from_user.id),
            )
            return
        charge = CIRCLE_PEACH_CHARGE
    await cq.answer()
    track_event(uid, 'circle_ordered', metadata={'delivery_id': delivery['id'], 'peaches': 0 if charge is None else CIRCLE_PEACH_COST})
    _video_jobs[cq.from_user.id] = _spawn_job(
        'circle', cq.from_user.id,
        _run_circle_background(cq.message.chat.id, cq.from_user.id, delivery['id'], charge),
    )


# V3.71.0: charge_id marker of a circle paid in peaches (not a Stars charge).
CIRCLE_PEACH_CHARGE = 'peaches'


def _bonus_peach_note(telegram_id: int) -> str:
    """V3.123.0: when a render is refused although he holds bonus peaches,
    say why (bonus goes to outfits/dates/gifts, renders take bought ones)."""
    try:
        from services.payments import get_bonus_peaches
        n = get_bonus_peaches(telegram_id)
    except Exception:
        return ''
    if n <= 0:
        return ''
    if user_lang(telegram_id) == EN:
        return f'\nYour {peach_num(n)} bonus 🍑 go to outfits, dates and gifts; photos and videos take bought peaches.'
    return f'\nТвои {peach_num(n)} бонусных 🍑 идут на гардероб, свидания и подарки, а фото и видео за купленные.'



async def _run_circle_background(chat_id: int, telegram_id: int, delivery_id: int, charge_id: str | None):
    """V3.20.0: generate the circle through the same engine chain and deliver it
    as a Telegram video note; falls back to a normal video if the note format
    is rejected. Auto-refunds Stars when every engine fails."""
    # V3.46.0: mission — a video-note circle also counts as «Живое видео».
    await _notify_unlock(chat_id, telegram_id, 'first_video')
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
        engines.extend(video_engines())  # V3.69.0: SpicyAPI only
        if not engines:
            raise CloudVideoError('no_video_engine')
        engine_names = [name for name, _ in engines]
        phrase = await asyncio.to_thread(_circle_phrase, telegram_id)
        await bot.send_message(chat_id, '🎥 записываю тебе кружочек… обычно это занимает 1–3 минуты')
        video_bytes = None
        used_engine = None
        last_error = None
        for idx, (engine_name, engine_fn) in enumerate(engines):
            try:
                if idx > 0:
                    await bot.send_message(chat_id, 'секунду, пробую ещё один способ записать кружочек 🎥')
                video_bytes = await engine_fn(square_frame(image_bytes), mime_type='image/jpeg', prompt=CIRCLE_PROMPT.format(phrase=phrase),
                                              scene='circle')
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
        if charge_id == CIRCLE_PEACH_CHARGE:
            try:
                await asyncio.to_thread(add_peaches, telegram_id, CIRCLE_PEACH_COST)
                refunded = True
            except Exception:
                logger.exception('Automatic circle peach refund failed user=%s', telegram_id)
        elif charge_id:
            try:
                await bot.refund_star_payment(user_id=telegram_id, telegram_payment_charge_id=charge_id)
                record_refund(telegram_id, charge_id, VIDEO_COST_STARS, product='video')
                refunded = True
            except Exception:
                logger.exception('Automatic circle Stars refund failed user=%s charge=%s', telegram_id, charge_id)
        back = f'{peach_num(CIRCLE_PEACH_COST)} 🍑 вернула на баланс.' if charge_id == CIRCLE_PEACH_CHARGE else 'Stars автоматически вернул.'
        await bot.send_message(chat_id, 'кружочек сейчас не получился 😕 ' + (back if refunded else 'попробуй чуть позже.'))
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
    engines.extend(video_engines())  # V3.69.0: SpicyAPI only
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
        f'Video (SpicyAPI): {"✅" if spicy_video_available() else "❌"}'
    )


@dp.message(Command('premium'))
async def premium(message: types.Message):
    uid = ensure_user(message.from_user.id, message.from_user.first_name)
    if not has_accepted(message.from_user.id):
        await message.answer('Сначала подтверди 18+ и условия через /start.', reply_markup=consent_keyboard()); return
    track_event(uid, 'paywall_view', metadata={'product': 'premium_month', 'stars': PREMIUM_MONTHLY_STARS})
    if is_premium(message.from_user.id):
        await message.answer(f'Premium уже активен ✨\nФото-кредиты: {get_photo_credits(message.from_user.id)}\nQuest replay осталось в этом месяце: {premium_replays_left(message.from_user.id)}\n\n🔁 Автопродление (по желанию): /autopay')
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
    await cq.answer()
    await send_stars_invoice(cq.message.chat.id, 'Anna Premium', 'Premium-доступ на 90 дней', 'premium_quarter', PREMIUM_QUARTERLY_STARS)


@dp.callback_query(F.data == 'buy:premium_vip')
async def buy_premium_vip(cq: types.CallbackQuery):
    """V3.97.0: Stars invoice for the one-time −50% month."""
    ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True); return
    from services import vip_offer
    vinfo = vip_offer.info(cq.from_user.id)
    if not vinfo.get('active'):
        await cq.answer('это предложение уже закончилось 💗', show_alert=True); return
    await cq.answer()
    track_event(ensure_user(cq.from_user.id), 'paywall_view', metadata={'product': vip_offer.PRODUCT, 'stars': vinfo['stars']})
    await send_stars_invoice(cq.message.chat.id, 'Anna Premium', f'Premium на 30 дней −{vinfo["percent"]}% — только для тебя',
                             vip_offer.PRODUCT, vinfo['stars'])


@dp.callback_query(F.data == 'buy:premium_trial')
async def buy_premium_trial(cq: types.CallbackQuery):
    """V3.88.0: the first-purchase trial — PREMIUM_TRIAL_DAYS for PREMIUM_TRIAL_STARS."""
    ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True); return
    if not trial_eligible(cq.from_user.id):
        await cq.answer('the trial is already used — pick a week or a month 💗' if user_lang(cq.from_user.id) == EN
                        else 'пробный период уже использован — выбери неделю или месяц 💗', show_alert=True); return
    await cq.answer()
    await send_stars_invoice(cq.message.chat.id, 'Anna Premium', f'Premium на {PREMIUM_TRIAL_DAYS} дня — пробный', 'premium_trial', PREMIUM_TRIAL_STARS)


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
            'безлимит сообщений — всё твоё 😏\n'
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
    track_event(ensure_user(cq.from_user.id), 'paywall_view', metadata={'product': 'premium', 'source': 'retention'})
    await cq.message.answer(premium_pitch_text(cq.from_user.id), reply_markup=premium_keyboard(discount_info(cq.from_user.id), telegram_id=cq.from_user.id))


@dp.message(F.photo, F.caption.regexp(r'^/storyphoto\b'))
async def storyphoto_upload(message: types.Message):
    """V3.63.2: owner sends a photo captioned «/storyphoto Вика» — it becomes
    one of Vika's push photos (story hooks + the locked first-offer cover).
    Only Telegram's file_id is kept; nothing lands in the public repo."""
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    from services import push_photos
    name = (message.caption or '').split(maxsplit=1)[1:] or ['']
    cards = list_cards()
    character_id = push_photos.resolve_character(name[0], cards)
    if not character_id:
        known = ', '.join(c.display_name for c in cards[:20])
        await message.answer(f'не понял, для кого фото. пример: /storyphoto Вика\nгероини: {known}')
        return
    total = push_photos.add(character_id, message.photo[-1].file_id)
    await message.answer(f'✅ фото для {_character_display_name(character_id)} сохранено — теперь у неё {total} шт.')


@dp.message(Command('storyphotos'))
async def storyphotos_list(message: types.Message):
    """V3.63.2: how many push photos each girl has; «/storyphotos clear Вика» wipes hers."""
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    from services import push_photos
    parts = (message.text or '').split(maxsplit=2)
    if len(parts) == 3 and parts[1].lower() in ('clear', 'очистить'):
        character_id = push_photos.resolve_character(parts[2], list_cards())
        if not character_id:
            await message.answer('не нашёл такую героиню'); return
        await message.answer(f'🗑 удалено фото: {push_photos.clear(character_id)}')
        return
    counts = push_photos.counts()
    lines = [f'• {_character_display_name(cid)} — {n}' for cid, n in sorted(counts.items())] or ['пока пусто']
    await message.answer('📸 фото для пушей по героиням:\n' + '\n'.join(lines) +
                         '\n\nдобавить: отправь фото с подписью /storyphoto Имя\nочистить: /storyphotos clear Имя')


# ── V3.75.0: scenario cards (services/scenario_cards.py) ─────────────────────

_scenario_renders: set[str] = set()


def _scenes_admin_view():
    import html
    from services import scenario_cards as sc
    from config import SCENARIO_COVER_COST_USD
    have = sc.covers()
    lines = ['🎬 <b>Сценарии-карточки</b>', '']
    rows = []
    missing = []
    for s in sc.SCENARIOS:
        name = _character_display_name(s.character_id)
        kind = (have.get(s.key) or {}).get('kind')
        mark = {'photo': '📸', None: '⏳'}.get(kind, '🎞')
        lines.append(f'{mark} {html.escape(name)} — {html.escape(s.button)} <code>{s.key}</code>')
        row = [InlineKeyboardButton(text=f'{"👀" if kind else "📸"} {name}: {s.button}',
                                    callback_data=f'scnadm:{"show" if kind else "gen"}:{s.key}')]
        if kind:
            row.append(InlineKeyboardButton(text='📸🔁', callback_data=f'scnadm:gen:{s.key}'))
        row.append(InlineKeyboardButton(text='🎞', callback_data=f'scnadm:vid:{s.key}'))
        rows.append(row)
        if not kind:
            missing.append(s.key)
    if missing:
        rows.insert(0, [InlineKeyboardButton(text=f'📸 Фото-обложки для всех недостающих ({len(missing)} × ~$0.035)',
                                             callback_data='scnadm:genall')])
    lines += ['',
              '📸 фото-обложка ~$0.035, 🎞 живая (видео 4 с) ~$'
              f'{SCENARIO_COVER_COST_USD + 0.035:.2f}. Делается один раз и потом уходит всем бесплатно. '
              'Карточки получают только сцены с обложкой: раз в сутки, вечером, тем, кто заходил за 2 недели.',
              'Своя обложка: пришли фото, видео или GIF с подписью <code>/scenecover ключ</code>.',
              'Убрать обложку: <code>/scenes clear ключ</code>']
    return '\n'.join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(Command('scenes'))
async def scenes_admin(message: types.Message):
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    from services import scenario_cards as sc
    parts = (message.text or '').split()
    if len(parts) == 3 and parts[1].lower() in ('clear', 'очистить'):
        await message.answer('🗑 обложка убрана' if sc.clear_cover(parts[2]) else 'нет такой обложки')
        return
    text, markup = _scenes_admin_view()
    await message.answer(text, parse_mode='HTML', reply_markup=markup)


@dp.message(F.caption.regexp(r'^/scenecover\b'))
async def scenecover_upload(message: types.Message):
    """Owner's own cover: a video / GIF / photo captioned «/scenecover key»."""
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    from services import scenario_cards as sc
    parts = (message.caption or '').split()
    s = sc.get(parts[1]) if len(parts) > 1 else None
    if not s:
        await message.answer('не понял, для какой сцены. пример: /scenecover boss_late\n'
                             'ключи: ' + ', '.join(x.key for x in sc.SCENARIOS))
        return
    if message.animation:
        sc.set_cover(s.key, message.animation.file_id, 'animation')
    elif message.video:
        sc.set_cover(s.key, message.video.file_id, 'video')
    elif message.photo:
        sc.set_cover(s.key, message.photo[-1].file_id, 'photo')
    else:
        await message.answer('нужно видео, GIF или фото'); return
    await message.answer(f'✅ обложка для «{s.button}» сохранена. /scenes — посмотреть')


async def _render_scenario_cover(chat_id: int, key: str, video: bool = False) -> None:
    from services import scenario_cards as sc
    s = sc.get(key)
    if not s or key in _scenario_renders:
        return
    _scenario_renders.add(key)
    try:
        caption = sc.caption(s, 0) + f'\n\n✅ обложка <code>{key}</code> готова'
        markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text='📸🔁 другое фото', callback_data=f'scnadm:gen:{key}'),
            InlineKeyboardButton(text='🎞 оживить', callback_data=f'scnadm:vid:{key}'),
        ]])
        if video:
            clip, _still = await sc.render_cover(s)
            msg = await bot.send_animation(chat_id, BufferedInputFile(clip, filename=f'{key}.mp4'),
                                           caption=caption, parse_mode='HTML', reply_markup=markup)
            if msg.animation:
                sc.set_cover(key, msg.animation.file_id, 'animation')
            elif msg.video:
                sc.set_cover(key, msg.video.file_id, 'video')
            elif msg.document:
                sc.set_cover(key, msg.document.file_id, 'animation')
        else:
            still = await sc.render_still(s)
            msg = await bot.send_photo(chat_id, BufferedInputFile(still, filename=f'{key}.jpg'),
                                       caption=caption, parse_mode='HTML', reply_markup=markup)
            sc.set_cover(key, msg.photo[-1].file_id, 'photo')
        logger.info('scenario cover ready key=%s video=%s', key, video)
    except Exception as exc:
        logger.warning('scenario cover failed key=%s: %s', key, exc)
        await bot.send_message(chat_id, f'❌ обложка {key} не получилась: {str(exc)[:300]}\nможно нажать ещё раз')
    finally:
        _scenario_renders.discard(key)


async def _render_scenario_covers(chat_id: int, keys: list[str]) -> None:
    for key in keys:
        await _render_scenario_cover(chat_id, key)


@dp.callback_query(F.data.startswith('scnadm:'))
async def scenes_admin_cb(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        await cq.answer(); return
    from services import scenario_cards as sc
    parts = (cq.data or '').split(':')
    action = parts[1] if len(parts) > 1 else ''
    if action == 'genall':
        have = sc.covers()
        keys = [s.key for s in sc.SCENARIOS if s.key not in have and s.key not in _scenario_renders]
        await cq.answer('запустил')
        await cq.message.answer(f'📸 делаю фото-обложки: {len(keys)} шт., примерно по минуте. пришлю по одной.')
        asyncio.create_task(_render_scenario_covers(cq.message.chat.id, keys))
        return
    s = sc.get(parts[2]) if len(parts) > 2 else None
    if not s:
        await cq.answer(); return
    if action in ('gen', 'vid'):
        if s.key in _scenario_renders:
            await cq.answer('уже делаю', show_alert=True); return
        video = action == 'vid'
        await cq.answer('запустил')
        await cq.message.answer(f'🎞 оживляю обложку «{s.button}» (~4–5 минут)' if video
                                else f'📸 делаю фото-обложку «{s.button}» (~1 минута)')
        asyncio.create_task(_render_scenario_cover(cq.message.chat.id, s.key, video))
    elif action == 'show':
        await cq.answer()
        from services.scheduler_service import send_scenario_card
        if not await send_scenario_card(bot, None, cq.from_user.id, s):
            await cq.message.answer('нет обложки или PUBLIC_BASE_URL')


@dp.callback_query(F.data.startswith('story:'))
async def story_choice_cb(cq: types.CallbackQuery):
    """V3.63.2: a tap on a story-hook choice (services/story_hooks.py). She
    answers in character, both lines land in the shared dialog so the Mini
    App chat continues from here, and the buttons go away (one choice only)."""
    from services import story_hooks
    parts = (cq.data or '').split(':')
    story = story_hooks.get(parts[1]) if len(parts) == 3 else None
    picked = story_hooks.choice(story, parts[2]) if story else None
    if not picked:
        await cq.answer(); return
    uid = ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    await cq.answer()
    try:
        await cq.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    lang = 'en' if user_lang(cq.from_user.id) == EN else 'ru'
    character_id = get_user_character(cq.from_user.id)
    said = story_hooks.label(picked, lang)
    answer = story_hooks.reply(picked, lang)
    rows = []
    if picked.offer and not is_premium(cq.from_user.id):
        rows.append([InlineKeyboardButton(text='🔓 see the photo' if lang == 'en' else '🔓 посмотреть фото', callback_data='first_offer:open')])
    if PUBLIC_BASE_URL:
        rows.append([InlineKeyboardButton(text='💬 reply to her' if lang == 'en' else '💬 ответить ей',
                                          web_app=types.WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp?open=chat'))])
    await cq.message.answer(answer, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None)
    try:
        await asyncio.to_thread(save_message, uid, character_id, 'user', said)
        await asyncio.to_thread(save_message, uid, character_id, 'assistant', answer)
    except Exception:
        logger.exception('story persist failed user=%s', cq.from_user.id)
    touch_user(cq.from_user.id)
    track_event(uid, 'story_hook_choice', metadata={'story': story.key, 'side': parts[2]})


@dp.callback_query(F.data == 'first_offer:open')
async def first_offer_open_cb(cq: types.CallbackQuery):
    """V3.63.2: «🔓 открыть» on the first-evening locked card — the Premium
    screen with the one-time 24h discount switched on (urgency the sleep
    block used to give only after the free demo was spent)."""
    uid = ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True); return
    await cq.answer()
    if is_premium(cq.from_user.id):
        await cq.message.answer('у тебя уже Premium ✨ попроси у меня фото прямо в чате 😏')
        return
    from services.retention_service import discount_info, offer_discount
    offer_discount(cq.from_user.id)
    track_event(uid, 'paywall_view', metadata={'product': 'premium_month', 'source': 'first_offer'})
    await cq.message.answer(premium_pitch_text(cq.from_user.id), reply_markup=premium_keyboard(discount_info(cq.from_user.id), telegram_id=cq.from_user.id))


def _platega_amount_for(product: str) -> int:
    """V3.44.21: price lookup behind the platega: callback buttons."""
    if product == 'premium_month':
        return PLATEGA_PREMIUM_PRICE_RUB
    if product == 'premium_week':
        # V3.34.1: card/SBP price of the weekly plan.
        return PLATEGA_PREMIUM_WEEKLY_PRICE_RUB
    if product == 'premium_trial':
        # V3.88.0: the 99 ₽ first-purchase trial.
        return PLATEGA_PREMIUM_TRIAL_PRICE_RUB
    if product == 'premium_month_vip':
        # V3.97.0: the one-time −50% month (platega_pay re-checks the window).
        from services import vip_offer
        return vip_offer.VIP_RUB
    if product == 'premium_quarter':
        # V3.43.0: the 3-month plan is card/SBP-purchasable too.
        return PLATEGA_PREMIUM_QUARTERLY_PRICE_RUB
    if product == 'photo':
        # V3.43.0: the pay-method modal sells a single photo credit in rubles.
        from config import fiat_values
        return fiat_values(PHOTO_COST_STARS)[0]
    if product in PEACH_PACK_RUB:
        # V3.43.1 → V3.44.22: peach packs by card/SBP — explicit round ruble
        # prices instead of the old star-ladder guess.
        return PEACH_PACK_RUB[product]
    if product.startswith('donation_'):
        # V3.44.22: «Поддержать проект» — the amount IS the product suffix.
        try:
            return max(1, int(product.split('_')[1]))
        except (IndexError, ValueError):
            return PLATEGA_PREMIUM_PRICE_RUB
    if product.startswith('peach_custom_'):
        # V3.44.23: custom peach amount — count × per-unit rub price.
        try:
            n = max(1, int(product.split('_')[-1]))
        except (ValueError, IndexError):
            n = 1
        return n * PEACH_CUSTOM_RUB_PER_UNIT
    if product == 'constructor_rub':
        return CONSTRUCTOR_COST_RUB
    if product.startswith('tokens_'):
        return int(product.split('_')[1]) * TOKEN_PRICE_RUB
    return PLATEGA_PREMIUM_PRICE_RUB


# ---------------------------------------------------------------- V3.120.0
# Premium auto-renewal (services/autopay.py): opt-in only, terms before the
# pay link, a reminder before every charge, «Отключить» in one tap.

def _autopay_menu_keyboard(telegram_id: int, en: bool, live: dict | None) -> InlineKeyboardMarkup:
    from services import autopay
    rows = []
    if live:
        rows.append([InlineKeyboardButton(text='❌ Turn off auto-renewal' if en else '❌ Отключить автопродление',
                                          callback_data='autopay:cancel_ask')])
        return InlineKeyboardMarkup(inline_keyboard=rows)
    if (not en and PLATEGA_ENABLED and autopay.PLATEGA_SUB_ENABLED and is_button_enabled('platega_rub')):
        rows.append([InlineKeyboardButton(text=f'🔁 Месяц — {PLATEGA_PREMIUM_PRICE_RUB} ₽ раз в месяц · СБП',
                                          callback_data='autopay:sbp:premium_month')])
        rows.append([InlineKeyboardButton(text=f'🔁 Неделя — {PLATEGA_PREMIUM_WEEKLY_PRICE_RUB} ₽ раз в неделю · СБП',
                                          callback_data='autopay:sbp:premium_week')])
    if autopay.STARS_ENABLED:
        rows.append([InlineKeyboardButton(
            text=(f'🔁 A month — {PREMIUM_MONTHLY_STARS} Stars every 30 days' if en
                  else f'🔁 Месяц — {PREMIUM_MONTHLY_STARS} Stars раз в 30 дней'),
            callback_data='autopay:stars')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _autopay_show(chat_id: int, telegram_id: int) -> None:
    from services import autopay
    en = user_lang(telegram_id) == EN
    if not autopay.ENABLED:
        await bot.send_message(chat_id, 'Auto-renewal is not available right now — plans in /premium are one-time.' if en
                               else 'Автопродление сейчас недоступно — тарифы в /premium разовые.')
        return
    live = await asyncio.to_thread(autopay.get_live, telegram_id)
    text = autopay.status_text(live, en) if live else autopay.terms_text(en)
    await bot.send_message(chat_id, text, parse_mode='HTML',
                           reply_markup=_autopay_menu_keyboard(telegram_id, en, live))


@dp.message(Command('autopay'))
async def autopay_cmd(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    if not has_accepted(message.from_user.id):
        await message.answer('Сначала подтверди 18+ и условия через /start.'); return
    await _autopay_show(message.chat.id, message.from_user.id)


@dp.callback_query(F.data == 'autopay:menu')
async def autopay_menu(cq: types.CallbackQuery):
    ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True); return
    await cq.answer()
    await _autopay_show(cq.message.chat.id, cq.from_user.id)


@dp.callback_query(F.data == 'autopay:stars')
async def autopay_stars(cq: types.CallbackQuery):
    from services import autopay
    ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True); return
    en = user_lang(cq.from_user.id) == EN
    if not (autopay.ENABLED and autopay.STARS_ENABLED):
        await cq.answer('not available right now' if en else 'сейчас недоступно', show_alert=True); return
    if await asyncio.to_thread(autopay.get_live, cq.from_user.id):
        await cq.answer('auto-renewal is already on — /autopay' if en else 'автопродление уже включено — /autopay',
                        show_alert=True); return
    await cq.answer()
    title = 'Premium · auto-renewal' if en else 'Premium · автопродление'
    desc = (f'Premium for 30 days, renews every 30 days for {PREMIUM_MONTHLY_STARS} Stars. Cancel any time: /autopay'
            if en else
            f'Premium на 30 дней, продлевается каждые 30 дней за {PREMIUM_MONTHLY_STARS} Stars. Отключить в любой момент: /autopay')
    try:
        link = await bot.create_invoice_link(
            title=title, description=desc, payload=autopay.STARS_PAYLOAD,
            provider_token='', currency='XTR',
            prices=[LabeledPrice(label=title, amount=PREMIUM_MONTHLY_STARS)],
            subscription_period=autopay.STARS_PERIOD_SECONDS,
        )
    except Exception:
        logger.exception('autopay stars invoice failed user=%s', cq.from_user.id)
        await bot.send_message(cq.message.chat.id, "couldn't create the subscription 😔 one-time plans: /premium" if en
                               else 'не получилось оформить подписку 😔 разовые тарифы — в /premium')
        return
    await asyncio.to_thread(autopay.create_pending, cq.from_user.id, 'stars', 'premium_month', PREMIUM_MONTHLY_STARS)
    track_event(ensure_user(cq.from_user.id), 'autopay_link_created', metadata={'provider': 'stars', 'plan': 'premium_month'})
    await bot.send_message(
        cq.message.chat.id,
        (f'⭐ Stars subscription: {PREMIUM_MONTHLY_STARS} Stars now and then every 30 days.\n'
         'A reminder comes the day before each charge; turn it off any time in /autopay or in Telegram settings.')
        if en else
        (f'⭐ Подписка в Stars: {PREMIUM_MONTHLY_STARS} Stars сейчас и дальше раз в 30 дней.\n'
         'Накануне каждого списания напомню; отключить можно в любой момент в /autopay или в настройках Telegram.'),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text=(f'⭐ Subscribe — {PREMIUM_MONTHLY_STARS} Stars / 30 days' if en
                  else f'⭐ Оформить — {PREMIUM_MONTHLY_STARS} Stars / 30 дней'), url=link)]]),
    )


@dp.callback_query(F.data.startswith('autopay:sbp:'))
async def autopay_sbp(cq: types.CallbackQuery):
    from services import autopay
    ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True); return
    plan = cq.data.split(':', 2)[2]
    if plan not in autopay.PLATEGA_INTERVAL or not (autopay.ENABLED and autopay.PLATEGA_SUB_ENABLED and PLATEGA_ENABLED):
        await cq.answer('сейчас недоступно', show_alert=True); return
    if await asyncio.to_thread(autopay.get_live, cq.from_user.id):
        await cq.answer('автопродление уже включено — /autopay', show_alert=True); return
    amount = PLATEGA_PREMIUM_WEEKLY_PRICE_RUB if plan == 'premium_week' else PLATEGA_PREMIUM_PRICE_RUB
    await cq.answer('создаю подписку…')
    row_id = await asyncio.to_thread(autopay.create_pending, cq.from_user.id, 'platega', plan, amount)
    link = await autopay.platega_create(row_id, cq.from_user.id, plan, amount, username=cq.from_user.username)
    if not link:
        await asyncio.to_thread(autopay.set_status, row_id, 'failed')
        await bot.send_message(cq.message.chat.id,
                               'не получилось оформить автопродление 😔 можно оплатить разово в /premium — '
                               'ничего не будет списываться само. Если повторяется — /support')
        return
    track_event(ensure_user(cq.from_user.id), 'autopay_link_created', metadata={'provider': 'platega', 'plan': plan})
    period = 'раз в неделю' if plan == 'premium_week' else 'раз в месяц'
    await bot.send_message(
        cq.message.chat.id,
        f'🔁 Автопродление через СБП: {amount} ₽ {period}.\n\n'
        'На странице подтверди привязку в своём банке — это одно согласие на регулярные списания. '
        'Premium включится сразу после первого списания. Накануне каждого следующего я напомню; '
        'отключить можно в любой момент в /autopay (или по ссылке отмены в письме от Platega).',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text=f'🏦 Подключить — {amount} ₽ {period}', url=link)]]),
    )


@dp.callback_query(F.data == 'autopay:cancel_ask')
async def autopay_cancel_ask(cq: types.CallbackQuery):
    from services import autopay
    en = user_lang(cq.from_user.id) == EN
    live = await asyncio.to_thread(autopay.get_live, cq.from_user.id)
    await cq.answer()
    if not live:
        await bot.send_message(cq.message.chat.id, 'Auto-renewal is already off 💗' if en else 'Автопродление уже выключено 💗')
        return
    await bot.send_message(
        cq.message.chat.id,
        'Turn off auto-renewal? Nothing more will be charged, your paid days stay.' if en
        else 'Отключить автопродление? Больше ничего не спишется, оплаченные дни останутся.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='❌ Yes, turn off' if en else '❌ Да, отключить',
                                  callback_data=f'autopay:cancel:{live["id"]}')],
            [InlineKeyboardButton(text='✅ Keep it' if en else '✅ Оставить', callback_data='autopay:keep')],
        ]))


@dp.callback_query(F.data == 'autopay:keep')
async def autopay_keep(cq: types.CallbackQuery):
    en = user_lang(cq.from_user.id) == EN
    await cq.answer('ok, auto-renewal stays on 💗' if en else 'хорошо, автопродление остаётся 💗')


@dp.callback_query(F.data.startswith('autopay:cancel:'))
async def autopay_cancel(cq: types.CallbackQuery):
    from services import autopay
    en = user_lang(cq.from_user.id) == EN
    try:
        row_id = int(cq.data.rsplit(':', 1)[1])
    except ValueError:
        await cq.answer(); return
    row = await asyncio.to_thread(autopay.get, row_id)
    if not row or row['telegram_id'] != int(cq.from_user.id):
        await cq.answer(); return
    if row['status'] not in autopay.LIVE:
        await cq.answer('already off 💗' if en else 'уже выключено 💗', show_alert=True); return
    await cq.answer('turning off…' if en else 'отключаю…')
    ok = False
    if row['provider'] == 'stars':
        try:
            ok = bool(await bot.edit_user_star_subscription(
                user_id=cq.from_user.id, telegram_payment_charge_id=row['external_id'], is_canceled=True))
        except Exception:
            logger.exception('stars subscription cancel failed user=%s row=%s', cq.from_user.id, row_id)
    else:
        ok = await autopay.platega_cancel(row['external_id'])
    if not ok:
        await bot.send_message(
            cq.message.chat.id,
            ("couldn't turn it off right now 😔 try again in a minute or write /support. "
             'A Stars subscription can also be cancelled in Telegram settings → My Stars.') if en else
            ('не получилось отключить прямо сейчас 😔 попробуй через минуту или напиши /support — отключим вручную.'
             + (' Подписку в Stars можно отменить и в настройках Telegram → Мои звёзды.' if row['provider'] == 'stars' else '')))
        try:
            for admin_id in ADMIN_TELEGRAM_IDS:
                await bot.send_message(admin_id, f'⚠️ autopay cancel failed user={cq.from_user.id} row={row_id} provider={row["provider"]}')
        except Exception:
            pass
        return
    await asyncio.to_thread(autopay.set_status, row_id, 'canceled')
    track_event(ensure_user(cq.from_user.id), 'autopay_canceled', metadata={'provider': row['provider'], 'plan': row['plan'],
                                                                             'charges': row['charges']})
    until = await asyncio.to_thread(autopay.premium_until, cq.from_user.id)
    await bot.send_message(cq.message.chat.id, autopay.canceled_text(until, en))


def _autopay_stars_row(telegram_id: int, first: bool) -> int:
    """The row a Stars subscription payment belongs to (created if missing)."""
    from services import autopay
    from models.app_models import AutoRenewal
    from services.db import SessionLocal
    with SessionLocal() as s:
        q = s.query(AutoRenewal).filter(AutoRenewal.telegram_id == int(telegram_id), AutoRenewal.provider == 'stars')
        statuses = ('pending',) if first else ('active', 'past_due', 'canceled', 'pending')
        row = q.filter(AutoRenewal.status.in_(statuses)).order_by(AutoRenewal.id.desc()).first()
        if row is not None:
            return row.id
    return autopay.create_pending(telegram_id, 'stars', 'premium_month', PREMIUM_MONTHLY_STARS)


async def _autopay_stars_paid(message: types.Message) -> None:
    from services import autopay
    payment = message.successful_payment
    tid = message.from_user.id
    charge = payment.telegram_payment_charge_id
    recurring = bool(getattr(payment, 'is_recurring', False))
    first = bool(getattr(payment, 'is_first_recurring', False)) or not recurring
    record_payment(tid, 'premium_month', payment.total_amount, charge, provider_payload='autopay=stars')
    row_id = await asyncio.to_thread(_autopay_stars_row, tid, first)
    if first:
        # the first payment's charge id is the handle editUserStarSubscription needs
        await asyncio.to_thread(autopay.set_external, row_id, charge)
    nxt = autopay.parse_dt(getattr(payment, 'subscription_expiration_date', None))
    await asyncio.to_thread(autopay.record_charge, row_id, nxt)
    await asyncio.to_thread(autopay.extend_premium_to, tid, nxt)
    track_event(ensure_user(tid), 'stars_purchase', value=payment.total_amount,
                metadata={'product': 'premium_month', 'autopay': 'first' if first else 'renewal'})
    row = await asyncio.to_thread(autopay.get, row_id)
    en = user_lang(tid) == EN
    await message.answer(autopay.renewed_text(row, (row or {}).get('next_charge_at'), first, en))
    if first:
        _spawn_background(_after_premium_paid(tid, 'premium_month'))


async def _autopay_platega_callback(body: dict) -> None:
    from services import autopay
    status = str(body.get('status') or '').strip().upper()
    row = await autopay.resolve_callback_row(body)
    if row is None:
        logger.warning('Platega subscription callback for unknown subscription id=%s sub=%s status=%s',
                       body.get('id'), body.get('subscriptionId'), status)
        return
    tid = row['telegram_id']
    en = user_lang(tid) == EN
    if status == platega_service.STATUS_CONFIRMED:
        payment_id = str(body.get('id') or '').strip()
        charge = f'platega_sub:{payment_id}'
        if not payment_id or await asyncio.to_thread(autopay.charge_seen, charge):
            return
        remote = await platega_service.get_transaction(payment_id)
        if remote is not None and str(remote.get('status') or '').upper() != platega_service.STATUS_CONFIRMED:
            logger.warning('Platega subscription debit status mismatch id=%s remote=%s', payment_id, remote.get('status'))
            return
        if not platega_service.amount_covers(body.get('amount'), str(row['amount'])):
            logger.error('Platega subscription amount mismatch row=%s expected=%s paid=%s',
                         row['id'], row['amount'], body.get('amount'))
            return
        record_payment(tid, row['plan'], 0, charge, provider='platega',
                       provider_payload=f'autopay=platega;sub={row.get("external_id")};amount={row["amount"]}')
        nxt = autopay.parse_dt(body.get('nextChargeAt'))
        first = await asyncio.to_thread(autopay.record_charge, row['id'], nxt)
        await asyncio.to_thread(autopay.extend_premium_to, tid, nxt)
        track_event(ensure_user(tid), 'platega_paid', metadata={'product': row['plan'], 'amount': str(row['amount']),
                                                                 'autopay': 'first' if first else 'renewal'})
        fresh = await asyncio.to_thread(autopay.get, row['id'])
        try:
            await bot.send_message(tid, autopay.renewed_text(fresh, (fresh or {}).get('next_charge_at'), first, en))
        except Exception:
            logger.exception('autopay renewal message failed user=%s', tid)
        if first:
            _spawn_background(_after_premium_paid(int(tid), row['plan']))
        return
    mapped = autopay.SUB_STATUSES.get(status)
    if mapped:
        before = row['status']
        if mapped == 'active' and before != 'pending':
            return  # already active (a debit came first)
        await asyncio.to_thread(autopay.set_status, row['id'], mapped)
        try:
            if mapped == 'canceled' and before in autopay.LIVE:
                until = await asyncio.to_thread(autopay.premium_until, tid)
                await bot.send_message(tid, autopay.canceled_text(until, en))
            elif mapped == 'failed':
                await bot.send_message(tid, 'не получилось подключить автопродление в банке 😔 '
                                            'можно оплатить разово в /premium — ничего само списываться не будет.')
            elif mapped == 'past_due' and before == 'active':
                fresh = await asyncio.to_thread(autopay.get, row['id'])
                await bot.send_message(tid, autopay.status_text(fresh, en))
        except Exception:
            logger.exception('autopay status message failed user=%s', tid)
        return
    if status == platega_service.STATUS_CANCELED and row['status'] == 'pending':
        await asyncio.to_thread(autopay.set_status, row['id'], 'failed')
        return
    logger.warning('Platega subscription callback status=%s row=%s (no action)', status, row['id'])


@dp.callback_query(F.data.startswith('platega:'))
async def platega_pay(cq: types.CallbackQuery):
    """V3.44.21: Platega card/SBP order — create the row, call
    POST /v2/transaction/process and hand the user the payment-page link."""
    ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True); return
    if not PLATEGA_ENABLED:
        await cq.answer('Оплата картой сейчас выключена — используй Stars ⭐', show_alert=True); return
    product = cq.data.split(':', 1)[1]
    _en = user_lang(cq.from_user.id) == EN
    if product == 'premium_trial' and not trial_eligible(cq.from_user.id):
        # V3.88.0: the trial is a one-time first purchase.
        await cq.answer('the trial is already used — pick a week or a month 💗' if _en
                        else 'пробный период уже использован — выбери неделю или месяц 💗', show_alert=True); return
    if product == 'premium_month_vip':
        from services import vip_offer
        if not vip_offer.is_active(cq.from_user.id):
            await cq.answer('это предложение уже закончилось 💗', show_alert=True); return
    amount = _platega_amount_for(product)
    await cq.answer('creating the invoice…' if _en else 'создаю счёт…')
    order_id = platega_service.create_order(cq.from_user.id, product, str(amount))
    link = await platega_service.create_payment(
        order_id, str(amount), telegram_id=cq.from_user.id,
        username=cq.from_user.username,
    )
    if not link:
        # Platega unreachable (no key / API error) — no SCI fallback exists
        # (that was a FreeKassa thing), so say so instead of a dead link.
        await bot.send_message(
            cq.message.chat.id,
            "couldn't create the invoice 😔 try again in a minute or pay with Stars right here ⭐\n\n"
            '💡 if it keeps happening, write /support' if _en else
            'не получилось создать счёт 😔 попробуй ещё раз через минуту '
            'или оплати Stars прямо в боте ⭐\n\n'
            '💡 если повторяется — напиши /support',
        )
        return
    if product == 'premium_month':
        title = f'💳 Premium — {amount} ₽'
    elif product == 'premium_week':
        # V3.34.1: the weekly card/SBP invoice.
        title = f'💳 Premium на неделю — {amount} ₽'
    elif product == 'premium_trial':
        title = f'🔥 Premium на {PREMIUM_TRIAL_DAYS} дня — {amount} ₽'
    elif product == 'premium_quarter':
        # V3.43.0: the 3-month card/SBP invoice.
        title = f'💳 Premium на 3 месяца — {amount} ₽'
    elif product == 'constructor_rub':
        title = f'🎭 Персонаж — {amount} ₽'
    elif product == 'photo':
        # V3.43.0: ruble-paid single photo credit from the app pay modal.
        title = f'🍑 Фото-кредит — {amount} ₽'
    elif product.startswith('donation_'):
        # V3.44.22: the support-the-project donation invoice.
        title = f'💜 Поддержать проект — {amount} ₽'
    elif product.startswith('peach_custom_'):
        # V3.44.23: custom peach amount invoice.
        try:
            _cn = max(1, int(product.split('_')[-1]))
        except (ValueError, IndexError):
            _cn = 1
        title = f'🍑 {_cn * PEACH_CUSTOM_UNIT} персиков — {amount} ₽'
    elif product in PEACH_PACK_CREDITS:
        # V3.65.0: a pack invoice was falling through to «🪙 Токены».
        title = f'🍑 {PEACH_PACK_CREDITS[product]} персиков — {amount} ₽'
    else:
        title = f'🪙 Токены — {amount} ₽'
    # V3.62.8: a tap-to-pay button instead of a bare URL in the text.
    track_event(ensure_user(cq.from_user.id), 'platega_link_created', metadata={'product': product, 'amount': str(amount)})
    if _en:
        # V3.111.0: abroad this page is the crypto way (USDT etc.) — say so in English.
        _en_names = {'premium_trial': f'Premium for {PREMIUM_TRIAL_DAYS} days', 'premium_week': 'Premium for a week',
                     'premium_month': 'Premium for a month', 'premium_quarter': 'Premium for 3 months',
                     'premium_month_vip': 'Premium for a month, your discount'}
        await bot.send_message(
            cq.message.chat.id,
            f'💎 {_en_names.get(product, "Purchase")} — {amount} ₽ · crypto or card\n\n'
            'On the payment page pick crypto (USDT and others) or a card. The price is in rubles; '
            'the page converts it. One-time payment, no auto-renewal. '
            'Everything turns on automatically within a minute after payment. Problems? Write /support.',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='💎 Pay', url=link)]]),
        )
        return
    await bot.send_message(
        cq.message.chat.id,
        f'{title} · оплата картой / СБП / криптой\n\n'
        'Способ оплаты выберешь на странице платежа. '
        'Это разовый платёж, без автопродления: сам ничего не спишется. '
        'После оплаты всё включится автоматически в течение минуты. '
        'Если что-то пойдёт не так — напиши /support.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='💳 Оплатить', url=link)]]),
    )


@dp.callback_query(F.data == 'donate:open')
async def donate_open_cb(cq: types.CallbackQuery):
    """V3.44.22: «Поддержать проект» — the owner's 50/100/500 ₽ chooser.

    The button on the weekly reminder / welcome / settings became a callback
    now that Platega is live; each amount reuses the stock ``platega:``
    payment path, so the donation rides the same order + callback + ledger
    chain as any other purchase.
    """
    ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True); return
    if not PLATEGA_ENABLED:
        # Normally unreachable — the CTA is a plain URL button while Platega
        # is off — kept for crafted callback data.
        await cq.answer('Оплата картой сейчас выключена 🙂', show_alert=True); return
    await cq.answer()
    lang = user_lang(cq.from_user.id)
    if lang == EN:
        text = ('💖 Support the project\n\nPick an amount — the payment page opens with card / SBP / crypto. '
                'Every donation keeps new characters, photos and videos coming ❤️')
    else:
        text = ('💖 Поддержать проект\n\nВыбери сумму — откроется страница оплаты: карта / СБП / крипта. '
                'Каждый донат — это новые персонажи, фото и видео ❤️')
    await cq.message.answer(text, reply_markup=donation_service.donation_amounts_keyboard(lang))


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


# ─── V3.45.0: Фото «наедине» и «Косплей» — монетизация через персики ──────────

@dp.callback_query(F.data == 'private_photo:start')
async def private_photo_start(cq: types.CallbackQuery):
    """V3.45.0: начало выбора фото «наедине»."""
    ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True); return
    await cq.answer()
    from services.private_photo_service import PRIVATE_PHOTO_CATEGORIES, get_private_photo_usage
    usage = get_private_photo_usage(cq.from_user.id)
    lang = user_lang(cq.from_user.id)
    rows = []
    for cat_id, cat_data in PRIVATE_PHOTO_CATEGORIES.items():
        name = cat_data['name_ru'] if lang == RU else cat_data.get('name_en', cat_data['name_ru'])
        rows.append([InlineKeyboardButton(text=name, callback_data=f'private_photo:cat:{cat_id}')])
    if not usage['hot_pass_active']:
        rows.append([InlineKeyboardButton(
            text=f'🔥 Hot Pass день — {HOT_PASS_DAY_PEACHES} 🍑',
            callback_data='private_photo:hotpass:day',
        )])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data='photo_menu:open')])
    if usage['hot_pass_active']:
        limit_text = (f'🔥 Hot Pass: {usage["hot_pass_left"]} free photos left today, then 🍑'
                      if user_lang(cq.from_user.id) == EN else
                      f'🔥 Hot Pass: сегодня бесплатно ещё {usage["hot_pass_left"]}, дальше за 🍑')
    else:
        limit_text = f'Бесплатно сегодня: {usage["private_left"]} фото'
    await cq.message.answer(
        f'💋 Фото наедине\n\n{limit_text}\n\nВыбери категорию:',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@dp.callback_query(F.data == 'private_cosplay:start')
async def private_cosplay_start(cq: types.CallbackQuery):
    """V3.45.0: начало выбора косплея."""
    ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True); return
    await cq.answer()
    from services.private_photo_service import COSPLAY_CHARACTERS, get_private_photo_usage
    usage = get_private_photo_usage(cq.from_user.id)
    rows = []
    for i in range(0, len(COSPLAY_CHARACTERS), 2):
        row = []
        for char in COSPLAY_CHARACTERS[i:i+2]:
            row.append(InlineKeyboardButton(
                text=char['name'],
                callback_data=f'private_cosplay:char:{char["id"]}',
            ))
        rows.append(row)
    if not usage['hot_pass_active']:
        rows.append([InlineKeyboardButton(
            text=f'🔥 Hot Pass день — {HOT_PASS_DAY_PEACHES} 🍑',
            callback_data='private_photo:hotpass:day',
        )])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data='photo_menu:open')])
    if usage['hot_pass_active']:
        limit_text = (f'🔥 Hot Pass: {usage["hot_pass_left"]} free photos left today, then 🍑'
                      if user_lang(cq.from_user.id) == EN else
                      f'🔥 Hot Pass: сегодня бесплатно ещё {usage["hot_pass_left"]}, дальше за 🍑')
    else:
        limit_text = f'Бесплатно сегодня: {usage["cosplay_left"]} фото'
    await cq.message.answer(
        f'🎭 Косплей\n\n{limit_text}\n\nВыбери образ:',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


# ─── V3.45.0: Многошаговый выбор «Фото наедине» ─────────────────────────────

@dp.callback_query(F.data.startswith('private_photo:cat:'))
async def private_photo_category(cq: types.CallbackQuery):
    cat_id = cq.data.split(':')[2]
    from services.private_photo_service import PRIVATE_PHOTO_CATEGORIES
    cat_data = PRIVATE_PHOTO_CATEGORIES.get(cat_id)
    if not cat_data:
        await cq.answer('категория не найдена', show_alert=True); return
    await cq.answer()
    lang = user_lang(cq.from_user.id)
    rows = []
    for i in range(0, len(cat_data['types']), 2):
        row = []
        for t in cat_data['types'][i:i+2]:
            name = t['name_ru'] if lang == RU else t.get('name_en', t['name_ru'])
            row.append(InlineKeyboardButton(text=name, callback_data=f'private_photo:type:{cat_id}:{t["id"]}'))
        rows.append(row)
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data='private_photo:start')])
    await cq.message.answer(
        f'{cat_data["name_ru"]}\n\nВыбери тип:',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@dp.callback_query(F.data.startswith('private_photo:type:'))
async def private_photo_type(cq: types.CallbackQuery):
    parts = cq.data.split(':')
    cat_id, type_id = parts[2], parts[3]
    from services.private_photo_service import LOCATIONS, PLACE_TYPED_CATEGORIES
    await cq.answer()
    lang = user_lang(cq.from_user.id)
    if cat_id in PLACE_TYPED_CATEGORIES:
        # V3.64.3: the type already names the place — straight to the mood.
        await _private_photo_moods(cq, cat_id, type_id, 'auto', back=f'private_photo:cat:{cat_id}')
        return
    rows = []
    for i in range(0, len(LOCATIONS), 2):
        row = []
        for loc in LOCATIONS[i:i+2]:
            name = loc['name_ru'] if lang == RU else loc.get('name_en', loc['name_ru'])
            row.append(InlineKeyboardButton(text=name, callback_data=f'private_photo:loc:{cat_id}:{type_id}:{loc["id"]}'))
        rows.append(row)
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data=f'private_photo:cat:{cat_id}')])
    await cq.message.answer('🏠 Выбери обстановку:', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data.startswith('private_photo:loc:'))
async def private_photo_location(cq: types.CallbackQuery):
    parts = cq.data.split(':')
    cat_id, type_id, loc_id = parts[2], parts[3], parts[4]
    await cq.answer()
    await _private_photo_moods(cq, cat_id, type_id, loc_id, back=f'private_photo:type:{cat_id}:{type_id}')


async def _private_photo_moods(cq: types.CallbackQuery, cat_id: str, type_id: str, loc_id: str, *, back: str):
    from services.private_photo_service import MOODS
    lang = user_lang(cq.from_user.id)
    rows = []
    for i in range(0, len(MOODS), 2):
        row = []
        for mood in MOODS[i:i+2]:
            name = mood['name_ru'] if lang == RU else mood.get('name_en', mood['name_ru'])
            row.append(InlineKeyboardButton(text=name, callback_data=f'private_photo:go:{cat_id}:{type_id}:{loc_id}:{mood["id"]}'))
        rows.append(row)
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data=back)])
    await cq.message.answer('💫 Выбери настроение:', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data.startswith('private_photo:go:'))
async def private_photo_generate(cq: types.CallbackQuery):
    """V3.45.0: генерация фото «наедине» через SpicyAPI."""
    parts = cq.data.split(':')
    cat_id, type_id, loc_id, mood_id = parts[2], parts[3], parts[4], parts[5]
    from services.private_photo_service import (
        PrivatePhotoRequest, consume_free_private_photo,
        get_type_name, generate_private_photo_real,
    )
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS and not is_premium(cq.from_user.id):
        # V3.87.0: «Наедине» shots are Premium-only — the button sells Premium.
        track_event(ensure_user(cq.from_user.id), 'paywall_view',
                    metadata={'product': 'spicy_private', 'scene': cat_id, 'source': 'bot'})
        await cq.answer()
        await cq.message.answer(CHAT_PHOTO_BLOCK_TEXT['spicy'],
                                reply_markup=premium_keyboard(telegram_id=cq.from_user.id))
        return
    is_free = consume_free_private_photo(cq.from_user.id, cat_id)
    if not is_free:
        from services.payments import spend_peaches
        if not spend_peaches(cq.from_user.id, PRIVATE_PHOTO_PEACH_COST, paid_only=True):
            await cq.answer(f'Нужно {PRIVATE_PHOTO_PEACH_COST} купленных 🍑 — не хватает' + _bonus_peach_note(cq.from_user.id), show_alert=True)
            return
    await cq.answer()
    type_name = get_type_name(cat_id, type_id, user_lang(cq.from_user.id))
    status_msg = await cq.message.answer(f'💋 Генерирую «{type_name}»...\n⏳ 30-60 сек')
    request = PrivatePhotoRequest(
        category=cat_id, type_id=type_id, location_id=loc_id, mood_id=mood_id,
        character_id=get_user_character(cq.from_user.id),
    )
    # Получаем описание персонажа из ДНК
    from services.character_dna_service import character_dna_context
    from services.private_photo_service import (
        cache_get, cache_save, gallery_save, check_achievements,
        build_private_photo_prompt,
    )
    char_desc = character_dna_context(get_user_character(cq.from_user.id))
    # Проверяем кэш
    prompt = build_private_photo_prompt(request, char_desc)
    prompt = _with_marital_ring(prompt, cq.from_user.id, get_user_character(cq.from_user.id))
    image_bytes = cache_get(prompt, get_user_character(cq.from_user.id))
    rendered = False
    if not image_bytes:
        image_bytes = await generate_private_photo_real(request, char_desc)
        rendered = bool(image_bytes)
        if image_bytes:
            cache_save(prompt, get_user_character(cq.from_user.id), cat_id, type_id, image_bytes)
    if image_bytes:
        # V3.56.0: audit the Telegram «наедине» render into the admin feed too —
        # only a fresh paid SpicyAPI job carries cost; a cache hit is $0.
        try:
            from config import SPICYAPI_ESTIMATED_COST_USD as _spicy_cost
            webapp_service.record_generation(
                cq.from_user.id, 'hot', get_user_character(cq.from_user.id),
                f'{cat_id}:{type_id}', None,
                engine=('spicyapi' if rendered else 'cache'),
                cost_usd=(_spicy_cost if rendered else 0.0),
            )
        except Exception:
            pass
        gallery_save(cq.from_user.id, get_user_character(cq.from_user.id), cat_id, type_id, image_bytes)
        # Увеличиваем счётчик и проверяем достижения
        from services.user_service import get_user
        user = get_user(cq.from_user.id)
        if user:
            user.total_private_photos = (user.total_private_photos or 0) + 1
            from services.db import SessionLocal
            with SessionLocal() as session:
                from sqlalchemy import select as sa_select
                from models.app_models import User as UserModel
                db_user = session.scalar(sa_select(UserModel).where(UserModel.id == user.id))
                if db_user:
                    db_user.total_private_photos = (db_user.total_private_photos or 0) + 1
                    session.commit()
        new_ach = check_achievements(cq.from_user.id)
        await status_msg.delete()
        await cq.message.answer_photo(
            photo=types.BufferedInputFile(image_bytes, filename='private_photo.jpg'),
            caption=f'💋 {type_name}',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text='🔄 Ещё такое', callback_data=f'private_photo:go:{cat_id}:{type_id}:{loc_id}:{mood_id}')],
                [InlineKeyboardButton(text='💋 Ещё фото наедине', callback_data='private_photo:start')],
                [InlineKeyboardButton(text='🖼️ Моя галерея', callback_data='private_gallery:view')],
            ]),
        )
        if new_ach:
            from services.private_photo_service import ACHIEVEMENTS
            ach_names = [ACHIEVEMENTS[a]["name"] for a in new_ach if a in ACHIEVEMENTS]
            if ach_names:
                await cq.message.answer(f'🏆 Новые достижения:\n' + '\n'.join(ach_names))
        # V3.46.0: mission — ordering a first private/spicy photo unlocks «Искра».
        await _notify_unlock(cq.message.chat.id, cq.from_user.id, 'first_spicy_photo')
    else:
        await status_msg.edit_text('😔 Не получилось сгенерировать. Попробуй ещё раз — персики не спишутся.')


# ─── V3.45.0: Многошаговый выбор «Косплей» ───────────────────────────────────

@dp.callback_query(F.data.startswith('private_cosplay:char:'))
async def private_cosplay_character(cq: types.CallbackQuery):
    cosplay_id = cq.data.split(':')[2]
    from services.private_photo_service import LOCATIONS, get_cosplay_name
    await cq.answer()
    lang = user_lang(cq.from_user.id)
    rows = []
    for i in range(0, len(LOCATIONS), 2):
        row = []
        for loc in LOCATIONS[i:i+2]:
            name = loc['name_ru'] if lang == RU else loc.get('name_en', loc['name_ru'])
            row.append(InlineKeyboardButton(text=name, callback_data=f'private_cosplay:loc:{cosplay_id}:{loc["id"]}'))
        rows.append(row)
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data='private_cosplay:start')])
    await cq.message.answer(f'🎭 {get_cosplay_name(cosplay_id)}\n\n🏠 Выбери обстановку:', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data.startswith('private_cosplay:loc:'))
async def private_cosplay_location(cq: types.CallbackQuery):
    parts = cq.data.split(':')
    cosplay_id, loc_id = parts[2], parts[3]
    from services.private_photo_service import MOODS, get_cosplay_name
    await cq.answer()
    lang = user_lang(cq.from_user.id)
    rows = []
    for i in range(0, len(MOODS), 2):
        row = []
        for mood in MOODS[i:i+2]:
            name = mood['name_ru'] if lang == RU else mood.get('name_en', mood['name_ru'])
            row.append(InlineKeyboardButton(text=name, callback_data=f'private_cosplay:go:{cosplay_id}:{loc_id}:{mood["id"]}'))
        rows.append(row)
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data=f'private_cosplay:char:{cosplay_id}')])
    await cq.message.answer(f'🎭 {get_cosplay_name(cosplay_id)}\n\n💫 Выбери настроение:', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data.startswith('private_cosplay:go:'))
async def private_cosplay_generate(cq: types.CallbackQuery):
    """V3.45.0: генерация косплей-фото через SpicyAPI."""
    parts = cq.data.split(':')
    cosplay_id, loc_id, mood_id = parts[2], parts[3], parts[4]
    from services.private_photo_service import (
        PrivatePhotoRequest, consume_free_private_photo,
        get_cosplay_name, generate_private_photo_real,
    )
    is_free = consume_free_private_photo(cq.from_user.id, 'cosplay')
    if not is_free:
        from services.payments import spend_peaches
        if not spend_peaches(cq.from_user.id, COSPLAY_PHOTO_PEACH_COST, paid_only=True):
            await cq.answer(f'Нужно {COSPLAY_PHOTO_PEACH_COST} купленных 🍑 — не хватает' + _bonus_peach_note(cq.from_user.id), show_alert=True)
            return
    await cq.answer()
    char_name = get_cosplay_name(cosplay_id)
    status_msg = await cq.message.answer(f'🎭 Генерирую «{char_name}»...\n⏳ 30-60 сек')
    request = PrivatePhotoRequest(
        category='cosplay', type_id=cosplay_id, cosplay_id=cosplay_id,
        location_id=loc_id, mood_id=mood_id,
        character_id=get_user_character(cq.from_user.id),
    )
    from services.character_dna_service import character_dna_context
    from services.private_photo_service import (
        cache_get, cache_save, gallery_save, check_achievements,
        build_private_photo_prompt,
    )
    char_desc = character_dna_context(get_user_character(cq.from_user.id))
    prompt = build_private_photo_prompt(request, char_desc)
    prompt = _with_marital_ring(prompt, cq.from_user.id, get_user_character(cq.from_user.id))
    image_bytes = cache_get(prompt, get_user_character(cq.from_user.id))
    rendered = False
    if not image_bytes:
        image_bytes = await generate_private_photo_real(request, char_desc)
        rendered = bool(image_bytes)
        if image_bytes:
            cache_save(prompt, get_user_character(cq.from_user.id), 'cosplay', cosplay_id, image_bytes)
    if image_bytes:
        # V3.56.0: audit the Telegram cosplay render into the admin feed (paid
        # SpicyAPI job carries cost, cache hit is $0).
        try:
            from config import SPICYAPI_ESTIMATED_COST_USD as _spicy_cost
            webapp_service.record_generation(
                cq.from_user.id, 'cosplay', get_user_character(cq.from_user.id),
                f'cosplay:{cosplay_id}', None,
                engine=('spicyapi' if rendered else 'cache'),
                cost_usd=(_spicy_cost if rendered else 0.0),
            )
        except Exception:
            pass
        gallery_save(cq.from_user.id, get_user_character(cq.from_user.id), 'cosplay', cosplay_id, image_bytes)
        from services.user_service import get_user
        user = get_user(cq.from_user.id)
        if user:
            from services.db import SessionLocal
            from sqlalchemy import select as sa_select
            from models.app_models import User as UserModel
            with SessionLocal() as session:
                db_user = session.scalar(sa_select(UserModel).where(UserModel.id == user.id))
                if db_user:
                    db_user.total_private_photos = (db_user.total_private_photos or 0) + 1
                    session.commit()
        new_ach = check_achievements(cq.from_user.id)
        await status_msg.delete()
        await cq.message.answer_photo(
            photo=types.BufferedInputFile(image_bytes, filename='cosplay_photo.jpg'),
            caption=f'🎭 {char_name}',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text='🔄 Ещё такой образ', callback_data=f'private_cosplay:go:{cosplay_id}:{loc_id}:{mood_id}')],
                [InlineKeyboardButton(text='🎭 Другой косплей', callback_data='private_cosplay:start')],
                [InlineKeyboardButton(text='🖼️ Моя галерея', callback_data='private_gallery:view')],
            ]),
        )
        if new_ach:
            from services.private_photo_service import ACHIEVEMENTS
            ach_names = [ACHIEVEMENTS[a]["name"] for a in new_ach if a in ACHIEVEMENTS]
            if ach_names:
                await cq.message.answer(f'🏆 Новые достижения:\n' + '\n'.join(ach_names))
    else:
        await status_msg.edit_text('😔 Не получилось. Попробуй ещё раз — персики не спишутся.')


# ─── V3.45.0: Hot Pass покупка ───────────────────────────────────────────────

@dp.callback_query(F.data.startswith('private_photo:hotpass:'))
async def private_photo_hotpass(cq: types.CallbackQuery):
    duration = cq.data.split(':')[2]
    durations = {'day': (HOT_PASS_DAY_PEACHES, 1), 'week': (HOT_PASS_WEEK_PEACHES, 7), 'month': (HOT_PASS_MONTH_PEACHES, 30)}
    if duration not in durations:
        await cq.answer('неверный тариф', show_alert=True); return
    cost, days = durations[duration]
    from services.payments import spend_peaches
    if not spend_peaches(cq.from_user.id, cost, paid_only=True):
        await cq.answer(f'Нужно {cost} купленных 🍑 — не хватает' + _bonus_peach_note(cq.from_user.id), show_alert=True); return
    from services.private_photo_service import activate_hot_pass
    expires = activate_hot_pass(cq.from_user.id, days)
    await cq.answer()
    if user_lang(cq.from_user.id) == EN:
        text = (f'🔥 Hot Pass is active for {days} days!\n\n'
                f'{HOT_PASS_FREE_DAILY} free private/cosplay photos per day in total, then peaches. '
                f'Active until {expires.strftime("%d.%m.%Y %H:%M")}\n\n'
                f'Charged {cost} 🍑')
    else:
        text = (f'🔥 Hot Pass активирован на {days} дн.!\n\n'
                f'{HOT_PASS_FREE_DAILY} бесплатных фото «наедине» и «косплей» в день суммарно, дальше за персики. '
                f'Действует до {expires.strftime("%d.%m.%Y %H:%M")}\n\n'
                f'Списано {cost} 🍑')
    await cq.message.answer(text)


# ─── V3.45.0: Приватная галерея ─────────────────────────────────────────────

@dp.callback_query(F.data == 'private_gallery:view')
async def private_gallery_view(cq: types.CallbackQuery):
    """V3.45.0: просмотр приватной галереи."""
    from services.private_photo_service import gallery_list, gallery_count
    items = gallery_list(cq.from_user.id, limit=10)
    total = gallery_count(cq.from_user.id)
    if not items:
        await cq.answer()
        await cq.message.answer('🖼️ Галерея пуста. Купи фото «наедине» или «косплей» — они сохранятся здесь.')
        return
    await cq.answer()
    await cq.message.answer(f'🖼️ Приватная галерея ({total} фото):\n\nПоследние 10:')
    for item in items:
        if item['image_bytes']:
            from services.private_photo_service import get_type_name, get_cosplay_name
            if item['category'] == 'cosplay':
                label = get_cosplay_name(item['type_id'])
            else:
                label = get_type_name(item['category'], item['type_id'])
            await cq.message.answer_photo(
                photo=types.BufferedInputFile(item['image_bytes'], filename='gallery.jpg'),
                caption=f'{label}\n{item["created_at"].strftime("%d.%m.%Y")}',
            )


# ─── V3.45.0: Достижения ─────────────────────────────────────────────────────

@dp.callback_query(F.data == 'private_achievements:view')
async def private_achievements_view(cq: types.CallbackQuery):
    """V3.45.0: просмотр достижений. V3.45.27: единый реестр (жизненный цикл +
    приватные фото) — тот же список и тот же «N из M», что и в Mini App."""
    from services.gamification_service import get_unified_progress
    data = get_unified_progress(cq.from_user.id)
    if not data['items']:
        await cq.answer()
        await cq.message.answer('🏆 Достижения пока не открыты.')
        return
    lines = [f'{it["name"]} {"✅" if it["unlocked"] else "⬜️"}' for it in data['items']]
    pct = round(data['unlocked'] / data['total'] * 100) if data['total'] else 0
    # V3.47.1: an unlocked achievement with owner-uploaded art gets a «🖼» button
    # that reveals the badge photo on demand.
    art = [it for it in data['items'] if it['unlocked'] and it.get('has_badge')]
    kb = None
    if art:
        rows = [[InlineKeyboardButton(text=f'🖼 {it["name"]}', callback_data=f'ach:badge:{it["key"]}')]
                for it in art]
        kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await cq.answer()
    await cq.message.answer(
        f'🏆 Достижения: {data["unlocked"]} из {data["total"]} ({pct}%)\n\n' + '\n'.join(lines),
        reply_markup=kb)


@dp.callback_query(F.data.startswith('ach:badge:'))
async def achievement_badge_view(cq: types.CallbackQuery):
    """V3.47.1: send the owner-uploaded art of one unlocked achievement."""
    key = cq.data.split(':', 2)[2]
    from services.gamification_service import get_badge
    badge = get_badge(key)
    if not badge:
        await cq.answer('арт не загружен', show_alert=True)
        return
    await cq.answer()
    try:
        await bot.send_photo(cq.from_user.id, types.BufferedInputFile(badge[0], filename='badge.jpg'))
    except Exception:
        logger.exception('achievement badge send failed key=%s', key)


# ─── V3.46.0: Миссии — воронка достижений ────────────────────────────────────

_MISSION_GROUP_TITLES = {
    'start': '🌱 Первые шаги',
    'romance': '❤️ Романтика',
    'creator': '🎨 Творчество',
}


def _missions_screen(telegram_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """V3.46.0: the «/миссии» roadmap — grouped list, each row is a status icon
    + reward chip, plus one CTA button per still-locked actionable mission. Every
    CTA reuses an existing live callback (constructor:start / video:animate_last /
    spicy:menu / photo_menu:open) so there is nothing new to route."""
    from services.gamification_service import get_missions, MISSION_NAV
    data = get_missions(telegram_id)
    lines = [f'🎯 Миссии: {data["unlocked"]} из {data["total"]} ({data["pct"]}%)', '']
    rows: list[list[InlineKeyboardButton]] = []
    seen_cta: set[str] = set()
    current_group: str | None = None
    for it in data['items']:
        if it['group'] != current_group:
            current_group = it['group']
            lines.append(_MISSION_GROUP_TITLES.get(current_group, current_group))
        status = '✅' if it['unlocked'] else '🔒'
        prog = f' ({it["progress"][0]}/{it["progress"][1]})' if it['progress'] else ''
        chip = f' · {it["reward"]}' if it['reward'] and it['reward'] != '🎖' else ''
        lines.append(f'{status} {it["name"]}{prog}{chip}')
        cb = it['cta_cb']
        if cb and not it['unlocked'] and cb not in seen_cta:
            seen_cta.add(cb)
            rows.append([InlineKeyboardButton(text=it['cta_label'], callback_data=cb)])
    if not rows:
        rows.append([InlineKeyboardButton(text='🏆 Все достижения', callback_data='private_achievements:view')])
    # V3.47.1: always leave a navigation row so a tap on the roadmap lands
    # somewhere real even when every remaining mission is passive.
    nav = [[InlineKeyboardButton(text=l, callback_data=cb) for l, cb in MISSION_NAV[i:i + 2]]
           for i in range(0, len(MISSION_NAV), 2)]
    rows.extend(nav)
    return '\n'.join(lines).rstrip(), InlineKeyboardMarkup(inline_keyboard=rows)


async def _notify_unlock(chat_id: int, telegram_id: int, key: str) -> None:
    """V3.46.0: fire a mission/achievement unlock (the reward is handed out
    inside) and ping the user ONLY when it was genuinely new. Idempotent, so a
    repeat trigger never re-pings and never double-grants."""
    from services.gamification_service import try_unlock
    text = try_unlock(telegram_id, key)
    if not text:
        return
    try:
        # V3.47.1: if the owner uploaded art for this achievement, the unlock
        # lands as a photo (the wow-moment); otherwise it stays plain text.
        badge = None
        try:
            from services.gamification_service import get_badge
            badge = get_badge(key)
        except Exception:
            badge = None
        if badge:
            await bot.send_photo(chat_id, types.BufferedInputFile(badge[0], filename='badge.jpg'), caption=text)
        else:
            await bot.send_message(chat_id, text)
    except Exception:
        logger.exception('mission unlock notify failed user=%s key=%s', telegram_id, key)


@dp.callback_query(F.data == 'missions:view')
async def missions_view_cb(cq: types.CallbackQuery):
    await cq.answer()
    text, kb = _missions_screen(cq.from_user.id)
    await cq.message.answer(text, reply_markup=kb)


@dp.message(Command('missions'))
async def missions_cmd(message: types.Message):
    if not has_accepted(message.from_user.id):
        await message.answer('Сначала /start и подтверждение 18+.')
        return
    text, kb = _missions_screen(message.from_user.id)
    await message.answer(text, reply_markup=kb)


# ─── V3.45.0: Голос + фото комбо ───────────────────────────────────────────

@dp.callback_query(F.data.startswith('private_voice:'))
async def private_voice_combo(cq: types.CallbackQuery):
    """V3.45.0: голос + фото комбо."""
    parts = cq.data.split(':')
    cat_id, type_id, loc_id, mood_id = parts[2], parts[3], parts[4], parts[5]
    from services.private_photo_service import (
        PrivatePhotoRequest, generate_voice_photo_combo, VOICE_PHOTO_PEACH_COST,
    )
    from services.payments import spend_peaches
    if not spend_peaches(cq.from_user.id, VOICE_PHOTO_PEACH_COST, paid_only=True):
        await cq.answer(f'Нужно {VOICE_PHOTO_PEACH_COST} купленных 🍑 — не хватает' + _bonus_peach_note(cq.from_user.id), show_alert=True)
        return
    await cq.answer()
    request = PrivatePhotoRequest(
        category=cat_id, type_id=type_id, location_id=loc_id, mood_id=mood_id,
        character_id=get_user_character(cq.from_user.id),
    )
    from services.character_dna_service import character_dna_context
    char_desc = character_dna_context(get_user_character(cq.from_user.id))
    status_msg = await cq.message.answer('💋🎙️ Генерирую фото + голос...\n⏳ 30-60 сек')
    ok = await generate_voice_photo_combo(cq.from_user.id, request, char_desc, bot)
    if ok:
        await status_msg.delete()
    else:
        await status_msg.edit_text('😔 Не получилось. Персики возвращены.')
        add_peaches(cq.from_user.id, VOICE_PHOTO_PEACH_COST)


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
    elif payload=='premium_month_auto':
        # V3.120.0: the opt-in Stars subscription (30 days, same month price).
        ok=amount==PREMIUM_MONTHLY_STARS
    elif payload=='premium_week':
        # V3.34.1: the weekly Premium option — chat and Mini App share it.
        ok=amount==PREMIUM_WEEKLY_STARS
    elif payload=='premium_trial':
        # V3.88.0: the first-purchase trial — once per user.
        ok=amount==PREMIUM_TRIAL_STARS and trial_eligible(query.from_user.id)
    elif payload=='premium_quarter':
        # V3.62.8: the 3-month plan was never validated or granted — Stars
        # were taken and Premium never switched on.
        ok=amount==PREMIUM_QUARTERLY_STARS
    elif payload=='undress_one':
        # V3.132.0: one «Раздеть» without Premium — adults only.
        ok=UNDRESS_ONE_ENABLED and amount==UNDRESS_ONE_STARS and is_adult_confirmed(query.from_user.id)
    elif payload=='photo_pack':
        # V3.34.0: standalone +1 photo credit purchased from the Mini App shop.
        ok=amount==PHOTO_COST_STARS
    elif payload in PEACH_PACK_STARS:
        # V3.43.1: the peach pack ladder — 10/30/100 credits, bulk discount.
        ok=amount==PEACH_PACK_STARS[payload]
    elif payload.startswith('peach_custom_'):
        # V3.44.23: custom peach amount — the count is encoded in the payload.
        try:
            _pn = max(1, int(payload.split('_')[-1]))
        except (ValueError, IndexError):
            ok = False
        else:
            ok = amount == _pn * PEACH_CUSTOM_STARS_PER_UNIT
    elif payload=='premium_month_discount':
        from services.retention_service import discount_info
        info=discount_info(query.from_user.id)
        ok=bool(info.get('active')) and amount==info.get('price')
    elif payload=='premium_month_vip':
        # V3.97.0: the one-time −50% month for the most active users.
        from services import vip_offer
        vinfo=vip_offer.info(query.from_user.id)
        ok=bool(vinfo.get('active')) and amount==vinfo.get('stars')
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
            delivery = get_photo_delivery_for_user(query.from_user.id, delivery_id)
            ok = (amount == VIDEO_COST_STARS and _any_video_engine()
                  and bool(delivery and delivery.get('telegram_file_id')))
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
        # V3.50.0: the boldest set also needs an uninhibited relationship path.
        from services.relationship_engine import get_path_axis
        item = spicy_service.get_spicy_set(payload.split(':', 1)[1])
        ok = (bool(item) and amount == item.cost
              and item.min_level <= get_relationship_level(query.from_user.id, get_user_character(query.from_user.id))
              and get_path_axis(ensure_user(query.from_user.id), get_user_character(query.from_user.id)) >= item.min_path
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
    # V3.104.0: «что теперь открыто» + her own word a few seconds after the
    # grant below (the task starts at the first await, after record_payment).
    if payload == 'premium_month_auto':
        # V3.120.0: first payment or a renewal of his Stars subscription.
        await _autopay_stars_paid(message)
        return
    if payload in PAID_PREMIUM_PRODUCTS:
        _spawn_background(_after_premium_paid(message.from_user.id, payload))
    if payload in PEACH_PACK_STARS:
        # V3.43.1: a peach pack — same record path as the single credit, the
        # payments layer grants the whole pack size in one go.
        record_payment(message.from_user.id, payload, payment.total_amount, charge)
        track_event(ensure_user(message.from_user.id), 'stars_purchase', value=payment.total_amount, metadata={'product': payload, 'source': 'webapp'})
        pack_n = PEACH_PACK_CREDITS[payload]
        if user_lang(message.from_user.id) == EN:
            await message.answer(f'done 🍑 +{pack_n} peaches added — ask me for a photo in chat and they will be used.')
        else:
            await message.answer(f'готово 🍑 +{pack_n} персиков на счету — проси фото в чате, и они спишутся.')
        return
    if payload.startswith('peach_custom_'):
        # V3.44.23: custom peach amount — the count is encoded in the payload.
        record_payment(message.from_user.id, payload, payment.total_amount, charge)
        track_event(ensure_user(message.from_user.id), 'stars_purchase', value=payment.total_amount, metadata={'product': payload, 'source': 'webapp'})
        try:
            _cn = max(1, int(payload.split('_')[-1]))
        except (ValueError, IndexError):
            _cn = 1
        if user_lang(message.from_user.id) == EN:
            await message.answer(f'done 🍑 +{_cn * PEACH_CUSTOM_UNIT} peaches added — ask me for a photo in chat and they will be used.')
        else:
            await message.answer(f'готово 🍑 +{_cn * PEACH_CUSTOM_UNIT} персиков на счету — проси фото в чате, и они спишутся.')
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
            await message.answer('done ✨ Premium is active for 30 days and I added 12 photo credits. Unlimited chat, voice, calls and my explicit photos are open now 🔥')
        else:
            await message.answer('готово ✨ Premium активирован на 30 дней, и я добавила 12 photo credits. Теперь тебе открыто общение без лимита, голос, звонки и мои откровенные фото 🔥')
        return

    if payload == 'undress_one':
        # V3.132.0: one «Раздеть» bought on its own.
        record_payment(message.from_user.id, 'undress_one', payment.total_amount, charge)
        track_event(ensure_user(message.from_user.id), 'stars_purchase', value=payment.total_amount, metadata={'product': 'undress_one'})
        pending = _pending_undress_photo.pop(message.from_user.id, None)
        if pending:
            await handle_photo_request(message.chat.id, message.from_user.id, pending, undress_credit=True)
            return
        if user_lang(message.from_user.id) == EN:
            await message.answer('done 🔥 one «Undress» is yours — tap it under my photo in the app')
        else:
            await message.answer('готово 🔥 одно «Раздеть» твоё — нажми его под моим фото в приложении')
        return

    if payload == 'premium_trial':
        # V3.88.0: the 3-day first-purchase trial.
        record_payment(message.from_user.id, 'premium_trial', payment.total_amount, charge)
        track_event(ensure_user(message.from_user.id), 'stars_purchase', value=payment.total_amount, metadata={'product': 'premium_trial'})
        if user_lang(message.from_user.id) == EN:
            await message.answer(f'done ✨ trial Premium is on for {PREMIUM_TRIAL_DAYS} days — my most private photos, «Undress», voice and a call with me 🔥')
        else:
            await message.answer(f'готово ✨ пробный Premium включён на {PREMIUM_TRIAL_DAYS} дня — мои самые откровенные фото, «Раздеть», голос и звонок со мной 🔥')
        return

    if payload == 'premium_week':
        # V3.34.1: the weekly Premium plan — 7 days + the weekly credit share.
        record_payment(message.from_user.id, 'premium_week', payment.total_amount, charge)
        track_event(ensure_user(message.from_user.id), 'stars_purchase', value=payment.total_amount, metadata={'product': 'premium_week'})
        if user_lang(message.from_user.id) == EN:
            await message.answer(f'done ✨ Premium is active for 7 days and I added {PREMIUM_WEEKLY_PHOTO_CREDITS} photo credits. Photo animations are available for Stars 🎬 plus my video circles 🎥')
        else:
            await message.answer(f'готово ✨ Premium активирован на 7 дней, и я добавила {PREMIUM_WEEKLY_PHOTO_CREDITS} photo credits. Оживление фото доступно за Stars 🎬 а ещё тебе открыты мои кружочки 🎥')
        return

    if payload == 'premium_quarter':
        record_payment(message.from_user.id, 'premium_quarter', payment.total_amount, charge)
        track_event(ensure_user(message.from_user.id), 'stars_purchase', value=payment.total_amount, metadata={'product': 'premium_quarter'})
        if user_lang(message.from_user.id) == EN:
            await message.answer(f'done ✨ Premium is active for 90 days and I added {PREMIUM_QUARTERLY_PHOTO_CREDITS} photo credits. Photo animations are available for Stars 🎬 plus my video circles 🎥')
        else:
            await message.answer(f'готово ✨ Premium активирован на 90 дней, и я добавила {PREMIUM_QUARTERLY_PHOTO_CREDITS} photo credits. Оживление фото доступно за Stars 🎬 и мои кружочки 🎥')
        return

    if payload == 'premium_month_vip':
        record_payment(message.from_user.id, 'premium_month_vip', payment.total_amount, charge)
        track_event(ensure_user(message.from_user.id), 'stars_purchase', value=payment.total_amount, metadata={'product': 'premium_month_vip'})
        if user_lang(message.from_user.id) == EN:
            await message.answer('done ✨ Premium is active for 30 days at half price. No more limits, I am all yours 💋')
        else:
            await message.answer('готово ✨ Premium на 30 дней за полцены. Больше никаких лимитов, я вся твоя 💋')
        return

    if payload == 'premium_month_discount':
        record_payment(message.from_user.id, 'premium_month_discount', payment.total_amount, charge)
        track_event(ensure_user(message.from_user.id), 'stars_purchase', value=payment.total_amount, metadata={'product': 'premium_month_discount'})
        await message.answer('готово ✨ Premium активирован на 30 дней со скидкой, и я добавила 12 photo credits. Общение без лимита, голос и мои откровенные фото — только для тебя 💋')
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
        result=complete_route(message.from_user.id,offer['quest_key'],offer['route_key'],paid_replay=True,character_id=get_user_character(message.from_user.id))
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
        # One unified job on SpicyAPI; auto-refunds Stars if it fails.
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
        # V3.44.13: snapshot the wizard session into Postgres and flag it paid
        # so a redeploy mid-creation resumes her instead of eating the persona.
        try:
            _cons = _constructor_sessions.get(message.from_user.id)
            if _cons and (_cons.get('params') or {}).get('name'):
                snapshot_constructor_draft(
                    message.from_user.id, params=_cons['params'],
                    photo_reference_base64=_cons.get('photo_reference_base64'),
                )
            mark_constructor_draft_paid(message.from_user.id, 'stars')
        except Exception:
            logger.exception('constructor draft snapshot failed user=%s', message.from_user.id)
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
        clean = _tts_text(text)
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
    # V3.50.0: the boldest set additionally asks for a passionate path.
    from services.relationship_engine import get_path_axis
    axis = get_path_axis(ensure_user(telegram_id), get_user_character(telegram_id))
    lock_suffix = 'ур.' if lang == RU else 'lvl '
    rows: list[list[InlineKeyboardButton]] = []
    for item in spicy_service.SPICY_SETS:
        name = item.name_en if lang == EN else item.name
        if item.min_level <= level and axis >= item.min_path:
            rows.append([InlineKeyboardButton(text=f'{item.emoji} {name} · {item.cost}⭐{fiat_suffix(item.cost)}', callback_data=f'spicy:set:{item.id}')])
        elif item.min_level <= level:
            hint = f'🔒 {name} · нужна страсть в вашей связи' if lang == RU else f'🔒 {name} · needs a passionate path'
            rows.append([InlineKeyboardButton(text=hint, callback_data=f'spicy:locked:{item.min_level}')])
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
    # V3.50.0: the boldest set is additionally gated by the relationship path.
    from services.relationship_engine import get_path_axis
    if item.min_path and get_path_axis(ensure_user(cq.from_user.id), get_user_character(cq.from_user.id)) < item.min_path:
        await cq.answer('этот сет она покажет только когда между нами будет больше страсти 🔥', show_alert=True)
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
    # V3.55.1: the toggle survives, but voice only actually fires on Premium.
    if new and not is_premium(message.from_user.id) and message.from_user.id not in ADMIN_TELEGRAM_IDS:
        await message.answer('голосовые ответы включены 🎙️\nно голос — привилегия Premium: с тобой заговорю голосом, когда оформишь подписку 😉')
    else:
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


async def _maybe_set_alarm(message: types.Message, text: str, confirm: str) -> bool:
    """V3.63.2: Premium sets alarms/reminders freely; everyone else gets ONE
    free alarm (she wakes him by voice) and then a Premium nudge instead of
    her silently promising to wake him and never doing it."""
    tid = message.from_user.id
    premium = is_premium(tid)
    wake = is_wake_request(text)
    trial = (not premium) and wake and wake_trial_available(tid)
    if not premium and not trial:
        if wake:
            await message.answer('⏰ Будильник — Premium-функция: она будит тебя голосом. '
                                 'Пробный будильник уже был. /premium — подключить')
        return False
    rid = create_from_text(tid, text)
    if not rid:
        return False
    user = get_user(tid)
    tz = (user.timezone or 'UTC') if user else 'UTC'
    msg = confirm.format(tz=tz)
    if trial:
        msg += '\n\n🎁 Это твой бесплатный пробный будильник — разбужу голосом. Дальше будильник — с Premium.'
    await message.answer(msg)
    if trial:
        track_event(ensure_user(tid), 'wake_trial_set')
    return True


@dp.message(Command('wake'))
async def wake_cmd(message: types.Message):
    text = message.text or ''
    if not is_wake_request(text):
        await message.answer('напиши время, например /wake 08:00')
        return
    await _maybe_set_alarm(message, text, 'запомнила 😌 разбужу вовремя по {tz}. если не ответишь — буду настойчивее')


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
        await message.answer('Использование: /testlevel 1..10 или /testlevel off')
        return
    arg = parts[1].strip().lower()
    if arg == 'off':
        clear_stage(message.from_user.id)
        await message.answer('тестовый уровень выключен')
        return
    # V3.61.9: levels 7-8 (premium plateau) are testable too.
    # V3.82.2: «7/10», «7 из 10», «ур 7» — take the first number.
    m = re.search(r'\d+', arg)
    arg = m.group(0) if m else arg
    if not arg.isdigit() or not 1 <= int(arg) <= len(STAGES):
        await message.answer(f'нужен уровень от 1 до {len(STAGES)}')
        return
    stage = STAGES[int(arg) - 1]
    set_stage(message.from_user.id, stage)
    await message.answer(f'тест: {STAGE_LABELS[stage]}')


def _bubble_pause(part: str) -> float:
    """Seconds of «печатает…» before a follow-up bubble: ~1s plus typing speed, capped."""
    return min(3.5, 0.9 + len(part) / 45)


def _on_trial(telegram_id: int) -> bool:
    if telegram_id in ADMIN_TELEGRAM_IDS:
        return False
    try:
        from services import trial_caps
        return trial_caps.window_start(telegram_id) is not None
    except Exception:
        return False


def _plan_calls_out(uid: int, telegram_id: int) -> bool:
    """V3.124.0: his plan's call-minute total is spent (not just today's)."""
    if telegram_id in ADMIN_TELEGRAM_IDS:
        return False
    try:
        from services import trial_caps, voice_call
        left = trial_caps.call_seconds_left(uid, voice_call.EVENT_PREMIUM)
        return left is not None and left <= 0
    except Exception:
        return False


def _trial_voice_ok(telegram_id: int) -> bool:
    """V3.124.0: on the trial her voice notes are counted (TRIAL_VOICE)."""
    try:
        from services import trial_caps
        return trial_caps.take_voice(telegram_id)
    except Exception:
        return True


def _duo_speakers(telegram_id: int) -> dict[str, str]:
    """V3.139.0: {name: character_id} of the two girls in this chat; {} if she
    writes alone. Used to send each line as its own message in its own voice."""
    try:
        from services import chat_guest_service as cgs
        return cgs.speakers(telegram_id, get_user_character(telegram_id) or '')
    except Exception:
        logger.warning('duo speakers read failed user=%s', telegram_id)
        return {}


async def _send_duo_answer(message: types.Message, lines: list[tuple[str, str]],
                           duo: dict[str, str], user) -> None:
    """V3.139.0: owner ТЗ — «это две разные девушки, каждое сообщение отдельно».
    Her friend's line is not a paragraph of one script: it arrives as its own
    message after a «печатает…» pause, and for a Premium man it is spoken by
    that girl's own voice, not by one voice reading both parts."""
    tid = message.from_user.id
    character_id = get_user_character(tid) or ''
    voice = bool(user and getattr(user, 'voice_enabled', False)
                 and (is_premium(tid) or tid in ADMIN_TELEGRAM_IDS))
    for i, (who, line) in enumerate(lines[:3]):
        if i:
            try:
                await bot.send_chat_action(message.chat.id, 'typing')
            except Exception:
                pass
            await asyncio.sleep(_bubble_pause(line))
        if voice and (tid in ADMIN_TELEGRAM_IDS or _trial_voice_ok(tid)):
            try:
                audio = await synthesize_bytes(
                    line, getattr(user, 'voice_style', None),
                    character_id=duo.get(who) or character_id)
                filename = 'voice.ogg' if getattr(user, 'voice_anon_mode', False) else f'{duo.get(who) or character_id}.ogg'
                await message.answer_voice(BufferedInputFile(audio, filename=filename))
                continue
            except Exception:
                logger.exception('duo tts failed user=%s', tid)
        # one Telegram account speaks for both, so the text keeps her name
        await message.answer(f'{who}: {line}')


async def send_answer(message: types.Message, text: str):
    await _send_answer_body(message, text)
    # V3.140.0: he agreed to invite the friend — her cleaned line just went
    # out, now the blurred joint teaser with the Premium button lands after it.
    from services import invite_funnel
    character_id = get_user_character(message.from_user.id)
    guest_id = invite_funnel.take_pending(message.from_user.id, character_id)
    if guest_id:
        await _send_duo_teaser(message.chat.id, message.from_user.id, character_id, guest_id)
    # V3.141.0: the scripted onboarding selfie lands right after her line —
    # a pre-saved picture, no generation and no paid-photo flow.
    from services import onboarding_demo
    if onboarding_demo.take_pending(message.from_user.id, character_id):
        try:
            await onboarding_demo.send_bot_photo(bot, message.chat.id, message.from_user.id, character_id)
        except Exception:
            logger.exception('onboarding demo photo failed user=%s', message.from_user.id)


async def _send_answer_body(message: types.Message, text: str):
    user = get_user(message.from_user.id)
    # V3.139.0: a duo answer is two messages, not one script.
    duo = await asyncio.to_thread(_duo_speakers, message.from_user.id)
    from services.chat_service import duo_lines
    lines = duo_lines(text) if duo else []
    if len(lines) > 1:
        await _send_duo_answer(message, lines, duo, user)
        return
    # V3.55.1: voice replies are a Premium perk (owner decision — the shop
    # card line «голосовые ответы» becomes literally true). Non-premium keeps
    # the toggle, gets text, and the once-a-day nudge at the bottom.
    if user and user.voice_enabled and (is_premium(message.from_user.id) or message.from_user.id in ADMIN_TELEGRAM_IDS) \
            and (message.from_user.id in ADMIN_TELEGRAM_IDS or _trial_voice_ok(message.from_user.id)):
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
            # V3.63.13: the next bubble comes after a «печатает…» pause sized
            # to its length, like a person typing it — not 0.35s later.
            for i, part in enumerate(parts):
                if i:
                    try:
                        await bot.send_chat_action(message.chat.id, 'typing')
                    except Exception:
                        pass
                    await asyncio.sleep(_bubble_pause(part))
                await message.answer(part)
            return
    await message.answer(text)
    # V3.55.1: once per day, a voice user without Premium hears how to unlock it.
    try:
        if user and user.voice_enabled and not is_premium(message.from_user.id) \
                and message.from_user.id not in ADMIN_TELEGRAM_IDS:
            today = dt.datetime.now(dt.timezone.utc).date().isoformat()
            if _voice_premium_hint.get(message.from_user.id) != today:
                _voice_premium_hint[message.from_user.id] = today
                hint = ('🎙 Voice replies are a Premium perk — subscribe and I\'ll speak to you in my real voice 😉'
                        if user_lang(message.from_user.id) == EN else
                        '🎙 Голосовые ответы — привилегия Premium: оформи подписку, и я заговорю с тобой настоящим голосом 😉')
                await message.answer(hint)
    except Exception:
        logger.warning('voice premium hint failed user=%s', message.from_user.id)


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
@service_screen
async def referral_button(message: types.Message):
    """Persistent menu button so the referral link is always one tap away,
    not buried in a one-time consent message that scrolls out of view."""
    await referral_cmd(message)


@dp.message(F.text.in_(kb_pair('partner') + ('💰 Партнёрка',)))
@service_screen
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


async def _send_gallery_entry(message: types.Message, telegram_id: int):
    """V3.149.0: «👯‍♀️ Галерея персонажей» — the same Mini App, but landed on the
    character tab instead of the chat tab, so a tap opens her directly."""
    lang = user_lang(telegram_id)
    if not PUBLIC_BASE_URL:
        await message.answer('👯‍♀️ приложение ещё не подключено — задай PUBLIC_BASE_URL (домен Railway).'
                           if lang != EN else '👯‍♀️ the app is not connected on the server yet.')
        return
    await message.answer(
        '👯‍♀️ Все девушки, их фото и характеры — в галерее приложения 👇' if lang != EN
        else '👯‍♀️ Every girl, her photos and personality — in the app gallery 👇',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[_menu_button('gallery', lang)]])
    )


@dp.message(F.text.in_(kb_pair('app')))
@service_screen
async def app_button(message: types.Message):
    """V3.38.0: «📱 Открыть приложение» — the top funnel row."""
    await _send_app_entry(
        message,
        '🛍 приложение AnnaBot — персонажи, чаты, картинки, магазин и твой профиль:',
        '🛍 AnnaBot app — characters, chats, pictures, shop and your profile:',
    )


@dp.message(F.text.in_(kb_pair('credits')))
@service_screen
async def credits_button(message: types.Message):
    """V3.38.0: «🍑 Персики». V3.95.0: the shop right in the chat — each
    pack is one tap to a payment link, no Mini App needed."""
    await _send_peach_shop(message)


def peach_shop_keyboard(telegram_id: int, lang: str = 'ru') -> InlineKeyboardMarkup:
    """V3.95.0: owner — «через бота сразу на ссылку оплаты, тот же магазин».
    The same packs as the app's «Магазин» tab: card/SBP via the stock
    ``platega:`` path, Stars via ``buy:peach_pack_*``; then Premium and the app."""
    en = lang == EN
    rows = []
    card_ok = PLATEGA_ENABLED and is_button_enabled('platega_rub')
    for key, credits in PEACH_PACK_CREDITS.items():
        bonus = PEACH_PACK_BONUS.get(key, 0)
        gift = f' (+{peach_num(bonus)} 🎁)' if bonus else ''
        if card_ok:
            rows.append([_platega_pay_button(
                key, PEACH_PACK_RUB[key],
                f'🍑 {peach_num(credits)}{gift} — {PEACH_PACK_RUB[key]} ₽ · ' + ('card / SBP' if en else 'карта / СБП'))])
        rows.append([InlineKeyboardButton(
            text=f'⭐ {peach_num(credits)} 🍑 — {PEACH_PACK_STARS[key]} Stars',
            callback_data=f'buy:{key}')])
    if not is_premium(telegram_id):
        rows.append([InlineKeyboardButton(text='👑 Premium' if en else '👑 Premium — все девушки и откровенный режим',
                                          callback_data='premium:view')])
    if PUBLIC_BASE_URL:
        rows.append([InlineKeyboardButton(text='👗 Her wardrobe' if en else '👗 Гардероб: одежда и комната для неё',
                                          web_app=types.WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp?open=wardrobe'))])
        rows.append([InlineKeyboardButton(text='🛍 Open the app shop' if en else '🛍 Магазин в приложении',
                                          web_app=types.WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp'))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_peach_shop(message: types.Message, who: types.User | None = None):
    """V3.95.0: «🍑 Персики» — balance + the pack ladder with pay buttons.
    `who` is the person who tapped (an inline button's message is the bot's)."""
    who = who or message.from_user
    uid = ensure_user(who.id, who.first_name, language_code=who.language_code)
    lang = user_lang(who.id)
    from services.payments import peach_wallet
    _w = peach_wallet(who.id)
    balance = peach_num(_w['paid'])
    bonus = peach_num(_w['bonus'])
    photo = peach_num(CHAT_PHOTO_PEACH_COST)
    if lang == EN:
        text = (f'🍑 Peaches\n\nBought: {balance} 🍑\nBonus: {bonus} 🎁 (missions, channel, friends — for outfits, dates and gifts)\n\n'
                f'A photo from her in chat costs {photo} 🍑, peaches also open circles and secret videos.\n'
                'Pick a pack: the payment page opens right away, peaches land within a minute.')
    else:
        text = (f'🍑 Персики\n\nКупленные: {balance} 🍑\nБонусные: {bonus} 🎁 (задания, канал, друзья — на гардероб, свидания и подарки)\n\n'
                f'Фото от неё в чате — {photo} купленных 🍑, ещё за них кружочки и тайные видео.\n'
                'Выбери пак: сразу откроется оплата, персики придут в течение минуты.')
    track_event(uid, 'paywall_view', metadata={'product': 'peach_shop_bot'})
    await message.answer(text, reply_markup=peach_shop_keyboard(who.id, lang))


@dp.callback_query(F.data.startswith('buy:peach_pack_'))
async def buy_peach_pack(cq: types.CallbackQuery):
    """V3.95.0: a peach pack for Stars from the in-chat shop — the invoice
    payload is the pack key, which pre-checkout and the grant already know."""
    ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    if not has_accepted(cq.from_user.id):
        await cq.answer('Сначала /start и подтверждение 18+', show_alert=True); return
    key = cq.data.split(':', 1)[1]
    if key not in PEACH_PACK_STARS:
        await cq.answer('…'); return
    await cq.answer()
    credits = peach_num(PEACH_PACK_CREDITS[key])
    await send_stars_invoice(cq.message.chat.id, f'{credits} персиков', f'{credits} 🍑 на баланс', key, PEACH_PACK_STARS[key])


@dp.message(F.text.in_(kb_pair('paint')))
@service_screen
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
@service_screen
async def premium_button(message: types.Message):
    await premium(message)


@dp.message(F.text.in_(kb_pair('stories')))
async def stories_button(message: types.Message):
    await stories_cmd(message)


@dp.message(F.text.in_(kb_pair('collection')))
async def collection_button(message: types.Message):
    await collection_cmd(message)


@dp.message(F.text.in_(kb_pair('profile')))
@service_screen
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
            '🔒 ahead is the top of your path — levels 7–10 are Premium only\n'
            if lang == EN else
            '🔒 впереди вершина вашего пути — уровни 7–10 открыты только с Premium\n'
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


# ── V3.149.0: the two chat utilities are a state machine, not a command ────
# Tapping ⏰ or 📝 arms a state; the NEXT text message belongs to that state and
# never reaches her roleplay brain. The state lives in dialog_sessions (the
# V3.29.0 foundation), so a redeploy can't drop a user mid-sentence, and a
# fifteen-minute silence expires it back to the ordinary chat.
ALARM_WAIT = 'waiting_for_alarm_time'
REMINDER_WAIT = 'waiting_for_reminder_text_and_time'
_UTILITY_WAIT = dialog_store.DialogStore('utility_wait')
_UTILITY_TTL_SECONDS = 900
_UTILITY_ASKS = {
    ALARM_WAIT: (
        '⏰ На какое время поставить будильник?\n\nПросто напиши время — например, 08:00 или 8 утра.',
        '⏰ What time should the alarm go off?\n\nJust write the time — for example, 08:00 or 8 am.',
    ),
    REMINDER_WAIT: (
        '📝 О чём напомнить и когда?\n\nНапиши одним сообщением — например, «в 14:30 позвонить маме».',
        '📝 What should I remind you about, and when?\n\nOne message is enough — for example, «at 14:30 call mum».',
    ),
}


def _utility_wait_of(telegram_id: int) -> str:
    entry = _UTILITY_WAIT.get(telegram_id) or {}
    state = str(entry.get('state') or '')
    if not state:
        return ''
    try:
        age = (dt.datetime.now(dt.timezone.utc)
               - dt.datetime.fromisoformat(str(entry.get('asked_at')))).total_seconds()
    except Exception:
        age = 0
    if age > _UTILITY_TTL_SECONDS:
        _UTILITY_WAIT.pop(telegram_id, None)
        return ''
    return state


def _arm_utility_wait(telegram_id: int, state: str) -> None:
    _UTILITY_WAIT[telegram_id] = {
        'state': state,
        'asked_at': dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def _drop_utility_wait(telegram_id: int) -> None:
    _UTILITY_WAIT.pop(telegram_id, None)


def _active_utility_lines(telegram_id: int) -> str:
    """What is already scheduled — times only, his own words stay in the DB."""
    user = get_user(telegram_id)
    if not user:
        return ''
    with SessionLocal() as s:
        active = s.scalars(select(Reminder).where(
            Reminder.user_id == user.id, Reminder.active == True).order_by(Reminder.due_at_utc)
        ).all()
    if not active:
        return ''
    lang = user_lang(telegram_id)
    head = '\n\n⏰ Already set:' if lang == EN else '\n\n⏰ Уже стоит:'
    rows = [f'{"🔔" if r.reminder_type == "wake" else "📝"} {r.due_at_utc.strftime("%d.%m %H:%M")} UTC'
            for r in active[:5]]
    return head + '\n'.join(rows)


async def _utility_paywall(message: types.Message, lang: str) -> None:
    # A blocked utility must not leave a stale wait armed: the next line then
    # belongs to her chat again, not to a tap the user can no longer answer.
    _drop_utility_wait(message.from_user.id)
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


async def _ask_utility(message: types.Message, state: str, extra: str = '') -> None:
    lang = user_lang(message.from_user.id)
    ru, en = _UTILITY_ASKS[state]
    _arm_utility_wait(message.from_user.id, state)
    await message.answer((en if lang == EN else ru) + extra)


async def _alarm_screen(message: types.Message, who: types.User) -> None:
    """⏰ — the first alarm stays a free try, the rest is Premium; either way the
    bot now waits for a plain time message instead of a /wake command."""
    tid = who.id
    ensure_user(tid, who.first_name, language_code=who.language_code)
    lang = user_lang(tid)
    if not is_premium(tid) and not wake_trial_available(tid):
        await _utility_paywall(message, lang)
        return
    extra = _active_utility_lines(tid)
    if not is_premium(tid):
        extra += ('\n\n🎁 Your first alarm is free — she wakes you with her voice.'
                  if lang == EN else '\n\n🎁 Первый будильник бесплатно — разбужу голосом.')
    await _ask_utility(message, ALARM_WAIT, extra)


async def _reminder_screen(message: types.Message, who: types.User) -> None:
    tid = who.id
    ensure_user(tid, who.first_name, language_code=who.language_code)
    lang = user_lang(tid)
    if not is_premium(tid):
        await _utility_paywall(message, lang)
        return
    await _ask_utility(message, REMINDER_WAIT, _active_utility_lines(tid))


@dp.message(F.text.in_(kb_pair('alarm')))
async def alarm_button(message: types.Message):
    await _alarm_screen(message, message.from_user)


@dp.callback_query(F.data == 'menu:alarm')
async def menu_alarm_cb(cq: types.CallbackQuery):
    await cq.answer()
    await _alarm_screen(cq.message, cq.from_user)


@dp.message(F.text.in_(kb_pair('reminder')))
async def reminder_button(message: types.Message):
    await _reminder_screen(message, message.from_user)


@dp.callback_query(F.data == 'menu:reminder')
async def menu_reminder_cb(cq: types.CallbackQuery):
    await cq.answer()
    await _reminder_screen(cq.message, cq.from_user)


@dp.message(F.text, lambda m: m.from_user is not None and bool(_utility_wait_of(m.from_user.id)))
async def utility_wait_answer(message: types.Message):
    """The FSM edge: this text is an answer to the utility question, not a line
    for her. Slash commands still work — they are registered earlier."""
    tid = message.from_user.id
    state = _utility_wait_of(tid)
    lang = user_lang(tid)
    text = (message.text or '').strip()
    parsed = parse_clock_text(text)
    if not parsed:
        await message.answer(
            "I can't read the time. Write it like 08:00 or 8 am ⏰" if lang == EN
            else 'не узнаю время. Напиши как 08:00 или 8 утра ⏰')
        return
    hour, minute, days = parsed
    uid = ensure_user(tid, message.from_user.first_name, language_code=message.from_user.language_code)
    _drop_utility_wait(tid)
    if state == ALARM_WAIT:
        create_at(tid, 'wake', 'Пора вставать', hour, minute, days)
        track_event(uid, 'alarm_set_fsm', metadata={'hour': hour, 'minute': minute})
        await message.answer(
            f'🔔 Done! I will wake you at {hour:02d}:{minute:02d}.' if lang == EN
            else f'🔔 Готово! Разбужу в {hour:02d}:{minute:02d}.')
        return
    body = reminder_body(text)
    create_at(tid, 'reminder', body, hour, minute, days)
    track_event(uid, 'reminder_set_fsm', metadata={'hour': hour, 'minute': minute})
    await message.answer(
        f'📝 Done! I will remind you at {hour:02d}:{minute:02d}: {body}' if lang == EN
        else f'📝 Готово! Напомню в {hour:02d}:{minute:02d}: {body}')


@dp.callback_query(F.data == 'menu:gallery')
async def menu_gallery_cb(cq: types.CallbackQuery):
    await cq.answer()
    await _send_gallery_entry(cq.message, cq.from_user.id)


@dp.callback_query(F.data == 'menu:profile')
async def menu_profile_cb(cq: types.CallbackQuery):
    await cq.answer()
    await profile_button(cq.message)


@dp.message(Command('menu'))
async def menu_cmd(message: types.Message):
    """V3.149.0: the menu on demand — the same role keyboard /start leaves under
    the welcome, four rows for him and the full kombayn for the owner."""
    lang = user_lang(message.from_user.id)
    if not has_accepted(message.from_user.id):
        await message.answer('сначала подтверди 18+ через /start' if lang != EN
                             else 'confirm 18+ first, then /start',
                             reply_markup=consent_keyboard(lang))
        return
    await message.answer('🧭 меню 👇' if lang != EN else '🧭 menu 👇',
                         reply_markup=menu_markup(message.from_user.id, lang))


@dp.message(F.text.in_(kb_pair('gallery')))
async def gallery_button(message: types.Message):
    await _send_gallery_entry(message, message.from_user.id)


@dp.message(F.text.in_(kb_pair('recipe')))
async def recipe_button(message: types.Message):
    await _owner_photo_scene(message, 'kitchen')


@dp.message(F.text.in_(kb_pair('concert')))
async def concert_button(message: types.Message):
    await _owner_photo_scene(message, 'concert')


@dp.message(F.text.in_(kb_pair('promo')))
async def promo_button(message: types.Message):
    await promo_cmd(message, CommandObject(command='promo', args=''))


async def _owner_photo_scene(message: types.Message, scene: str):
    """🍳 and 🎫 are the owner's test rows: the same scene render the app offers,
    reached in one tap instead of a command. Anyone else gets the app door."""
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        await _send_app_entry(message, 'всё это — в приложении 👇', 'all of this lives in the app 👇')
        return
    await handle_photo_request(message.chat.id, message.from_user.id, PhotoRequest(scene=scene))


@dp.message(F.text.in_(kb_pair('settings')))
@service_screen
async def settings_button(message: types.Message):
    await settings(message)


@dp.message(F.text.in_(kb_pair('support')))
@service_screen
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
@service_screen
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


async def _bot_deliver_bonus_media(cq: types.CallbackQuery):
    """V3.51.1: mirror the app's spontaneous free photo in the bot chat, now of
    the character actually being talked to (V3.49.0 used the owner's generic
    pool -> wrong face for community girls). Never mints peaches/Stars."""
    try:
        character_id = get_user_character(cq.from_user.id)
        data, mime, ext = await _webapp_media_photo(cq.from_user.id, character_id, 'selfie')
        if not data:
            return
        await cq.message.answer_photo(BufferedInputFile(data, filename=f'bonus.{ext}'),
                                      caption='захотелось поделиться с тобой этим кадром 📸')
    except Exception:
        logger.exception('bot bonus media delivery failed')


@dp.message(F.text.in_(kb_pair('quest')))
async def daily_quest_button(message: types.Message):
    """V3.21.0 / V3.49.0: a few small requests from her per day (2-3), each one
    claimable on its own for +5 attention; every claim also feeds the story
    unlock ladder."""
    ensure_user(message.from_user.id, message.from_user.first_name, language_code=message.from_user.language_code)
    from services import couple_service
    uid = ensure_user(message.from_user.id)
    lang = user_lang(message.from_user.id)
    user = get_user(message.from_user.id)
    completed = int(getattr(user, 'quests_completed', 0) or 0) if user else 0
    quests = couple_service.daily_quests_state(message.from_user.id)
    rows = []
    for q in quests:
        if q['claimed']:
            label = '✅ ' + q['text'] + (' · done' if lang == EN else ' · готово')
        else:
            label = '🎯 ' + q['text'] + ' · +5'
        rows.append([InlineKeyboardButton(text=label, callback_data='questday:claim:' + q['key'])])
    if lang == EN:
        header = f"🎯 today's quests · {completed} completed in total\n\ntap a task when you have done it — she will notice 😊"
    else:
        header = f"🎯 задания дня · всего выполнено: {completed}\n\nнажми на задание, когда сделаешь — она заметит 😊"
    await message.answer(header, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    track_event(uid, 'daily_quest_view', metadata={
        'quests': [q['key'] for q in quests],
        'primary': couple_service.daily_quest(message.from_user.id)[0],
    })


@dp.callback_query(F.data.startswith('questday:claim'))
async def daily_quest_claim(cq: types.CallbackQuery):
    from services import couple_service
    uid = ensure_user(cq.from_user.id, cq.from_user.first_name, language_code=cq.from_user.language_code)
    data = cq.data or ''
    quest_key = data.split(':', 2)[2] if data.count(':') >= 2 else ''
    if quest_key:
        result = couple_service.claim_quest(cq.from_user.id, quest_key)
    else:
        result = {'attention': 5} if couple_service.claim_daily_quest(cq.from_user.id) else None
    if result and result.get('not_done'):
        await cq.answer('сначала сделай это в чате с ней 😉 потом жми ещё раз', show_alert=True)
        return
    if result:
        track_event(uid, 'daily_quest_claimed')
        await cq.answer('+5 внимания ❤️')
        await cq.message.answer('ммм, приятно 😊 +5 очков внимания. она запомнила.')
        if result.get('bonus_media'):
            await _bot_deliver_bonus_media(cq)
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


# ── V3.52.0: «Жизнь без тебя» one-tap reply continuation ──────────────────
@dp.callback_query(F.data == 'wake:up')
async def on_wake_up_tap(cq: types.CallbackQuery):
    """V3.63.2: «☀️ я проснулся» under her wake-up voice stops the alarm."""
    cancel_active_wake(cq.from_user.id)
    await cq.answer('☀️')
    try:
        await cq.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await cq.message.answer('ура, проснулся 😌 доброе утро! хорошего тебе дня ☀️')
    track_event(ensure_user(cq.from_user.id), 'wake_stopped_button')


@dp.callback_query(F.data.startswith('life_reply:'))
async def on_life_reply_tap(cq: types.CallbackQuery):
    """A life-event push ends with two low-friction buttons. Tapping one feeds a
    natural user line into the SAME reply pipeline the typed chat uses, so she
    continues her own moment in context (memory, persona, relationship) instead
    of a canned answer. Guarded by the daily message limit like a normal turn."""
    parts = cq.data.split(':', 2)
    character_id = parts[1] if len(parts) > 1 else get_user_character(cq.from_user.id)
    key = parts[2] if len(parts) > 2 else 'tell_more'
    from services.life_event_service import tap_reply_text
    user_line = tap_reply_text(key)
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS and not can_send_message(cq.from_user.id):
        await cq.answer('лимит сообщений на сегодня', show_alert=True)
        return
    await cq.answer()
    try:
        async with ChatActionSender.typing(bot=bot, chat_id=cq.message.chat.id):
            answer = await anna_reply(
                cq.from_user.id, cq.from_user.first_name or 'ты', user_line,
                language_code=cq.from_user.language_code, character_id=character_id,
            )
        answer, _ = _strip_fake_photo(answer)
        if answer:
            await cq.message.answer(answer)
    except Exception:
        logger.exception('life_reply tap failed user=%s', cq.from_user.id)


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
    # V3.44.6: no character limit — the intro always starts a fresh wizard;
    # existing characters stay reachable via «🎨 Мой персонаж».
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
    # V3.45.28: creation always costs peaches (the free «Сообщество» perk is
    # retired — every avatar is drawn on our GPU bill). Admins stay free.
    if telegram_id in ADMIN_TELEGRAM_IDS:
        buy_label = '✅ Создать · бесплатно (админ)'
        price_note = 'Админский доступ: бесплатно.'
        pay_rows = [[InlineKeyboardButton(text=buy_label, callback_data='constructor:buy')]]
    else:
        buy_label = f'🍑 Создать · {CONSTRUCTOR_COST_PEACHES} 🍑'
        price_note = f'Создание персонажа — {CONSTRUCTOR_COST_PEACHES} 🍑: аватар рисуется за наш счёт.'
        pay_rows = [[InlineKeyboardButton(text=buy_label, callback_data='constructor:buy_peaches')]]
    pay_rows.append([InlineKeyboardButton(text='❌ Отменить', callback_data='constructor:cancel')])
    keyboard = InlineKeyboardMarkup(inline_keyboard=pay_rows)
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
    # V3.44.8: list ALL of the user's characters (was only the first one) —
    # each gets a chat button, and «create new» always stays available.
    rows = get_all_custom_characters(telegram_id)
    if not rows:
        await _constructor_intro(chat_id, telegram_id)
        return
    lines = ['🎨 Твои персонажи:', '']
    buttons = []
    for row in rows:
        name = row.display_name or 'Без имени'
        lines.append(f'• {name}')
        buttons.append([InlineKeyboardButton(text=f'💬 {name}', callback_data=f'mychar:chat:{row.character_id}')])
    buttons.append([InlineKeyboardButton(text='🆕 Создать нового', callback_data='constructor:restart')])
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    latest = rows[-1]
    if latest.avatar_file_id:
        await bot.send_photo(chat_id, latest.avatar_file_id, caption='\n'.join(lines), reply_markup=markup)
    else:
        await bot.send_message(chat_id, '\n'.join(lines), reply_markup=markup)


async def _retry_constructor_avatar(telegram_id: int, character_id: str) -> None:
    """V3.44.12: creation-time providers were down — retry the avatar after
    five and fifteen minutes so she gets a face without any user action. The
    first photo request also heals her (ensure_custom_avatar_cached)."""
    for delay in (300, 900):
        await asyncio.sleep(delay)
        try:
            row = get_custom_character_by_id(character_id)
            if not row or row.avatar_file_id:
                return
            params, name = custom_character_params(character_id)
            avatar_bytes, _mime = await asyncio.wait_for(
                generate_custom_avatar(build_avatar_prompt(params)), timeout=260,
            )
            sent = await bot.send_photo(telegram_id, BufferedInputFile(avatar_bytes, filename='avatar.jpg'))
            from services.photo_service import _custom_reference_dir
            avatar_folder = _custom_reference_dir(character_id)
            avatar_folder.mkdir(parents=True, exist_ok=True)
            (avatar_folder / 'avatar.jpg').write_bytes(avatar_bytes)
            set_custom_avatar_file_id(character_id, sent.photo[-1].file_id)
            await bot.send_message(telegram_id, f'дорисовала аватар для {name} ✅')
            return
        except Exception:
            logger.exception('constructor avatar retry failed user=%s char=%s', telegram_id, character_id)


async def _constructor_draft_sweep() -> None:
    """V3.44.14: resume paid creations whose run died WITHOUT a server restart.

    The V3.44.13 startup scan only covers deploys; an exception between payment
    and save used to strand the draft forever — peaches spent, persona missing
    (owner: «её просто нет»). The sweep re-checks every few minutes; the claim
    freshness window (12 min) is wider than the worst bounded run (~10 min), so
    a live creation is never double-spawned.
    V3.44.15: drafts that burned MAX_CONSTRUCTOR_ATTEMPTS tries are abandoned
    here — refund + honest message — instead of re-drawing her forever.
    """
    while True:
        await asyncio.sleep(180)
        try:
            for _telegram_id, _source, _name in abandoned_constructor_drafts():
                try:
                    if _source == 'peaches':
                        grant_photo_credits(
                            _telegram_id, CONSTRUCTOR_COST_PEACHES,
                            reason=f'constructor_refund:{_telegram_id}:{int(_time.time() * 1000)}', bonus=False,
                        )
                        await bot.send_message(_telegram_id, f'не получилось создать {_name or "персонажа"} 😕 {CONSTRUCTOR_COST_PEACHES} 🍑 вернула на баланс — попробуй ещё раз, я уже починила причину.')
                    else:
                        await bot.send_message(_telegram_id, f'не получилось создать {_name or "персонажа"} 😕 напиши /support — вернём оплату вручную. попробуй ещё раз, я уже починила причину.')
                except Exception:
                    logger.exception('constructor abandon notify failed user=%s', _telegram_id)
            for _draft in pending_constructor_drafts():
                try:
                    logger.info('sweep resuming constructor creation user=%s source=%s attempt=%s', _draft.telegram_id, _draft.source, _draft.attempts)
                    _spawn_job('constructor', int(_draft.telegram_id), _finish_constructor(int(_draft.telegram_id), None, int(_draft.telegram_id), source=_draft.source or ''), payload={'source': _draft.source or 'sweep'})
                except Exception:
                    logger.exception('constructor draft sweep resume failed user=%s', _draft.telegram_id)
        except Exception:
            logger.exception('constructor draft sweep failed')


async def _request_character_moderation(character_id: str, owner_tgid: int, display_name: str, avatar_file_id: str | None = None) -> None:
    """V3.45.28: ping every admin with a submitted persona + approve/reject
    buttons. A missing avatar (providers were down at creation) still routes a
    text-only review card — better to queue her than publish her unreviewed."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='✅ Одобрить', callback_data=f'charmod:approve:{character_id}'),
        InlineKeyboardButton(text='❌ Отклонить', callback_data=f'charmod:reject:{character_id}'),
    ]])
    caption = (f'🛡 На модерацию в «Сообщество»:\n{display_name}\n'
               f'id: {character_id}\nавтор: {owner_tgid}')
    for admin_id in ADMIN_TELEGRAM_IDS:
        try:
            if avatar_file_id:
                await bot.send_photo(admin_id, avatar_file_id, caption=caption, reply_markup=keyboard)
            else:
                await bot.send_message(admin_id, caption, reply_markup=keyboard)
        except Exception:
            logger.exception('character moderation ping failed admin=%s char=%s', admin_id, character_id)


@dp.callback_query(F.data.startswith('charmod:'))
async def charmod_cb(cq: types.CallbackQuery):
    """V3.45.28: an admin passes or rejects a community persona. Approving
    publishes her storefront card; rejecting keeps her private to the author."""
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        await cq.answer('только для владельца')
        return
    parts = (cq.data or '').split(':', 2)
    if len(parts) != 3 or parts[1] not in ('approve', 'reject'):
        await cq.answer('bad request')
        return
    approve = parts[1] == 'approve'
    character_id = parts[2][:64]
    row = moderate_community_submission(character_id, approve)
    if not row:
        await cq.answer('персонаж не найден')
        return
    try:
        update_card(character_id, is_visible=bool(approve))
    except Exception:
        logger.exception('charmod card visibility failed char=%s', character_id)
    await cq.answer('одобрена ✅' if approve else 'отклонена ❌')
    try:
        await cq.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    try:
        await bot.send_message(
            int(row.telegram_id),
            (f'🎉 {row.display_name} одобрена и появилась на витрине «Сообщество» — теперь с ней могут общаться другие.'
             if approve else
             f'😔 модератор не пропустил {row.display_name} в «Сообщество». она осталась твоей личной — '
             'можно отредактировать и отправить снова из «Кабинета создателя».'),
        )
    except Exception:
        logger.exception('charmod author notify failed char=%s', character_id)
    # V3.46.0: mission — a persona actually reaching the «Сообщество» витрина
    # (only on approval) unlocks its author's «Голос сообщества».
    if approve:
        try:
            await _notify_unlock(int(row.telegram_id), int(row.telegram_id), 'community_publish')
        except Exception:
            logger.exception('community_publish unlock failed char=%s', character_id)


async def _finish_constructor(chat_id: int, charge: str | None, telegram_id: int | None = None, source: str = ''):
    """After Stars payment: generate the avatar, save the persona, open chat.

    V3.35.0: takes a chat id instead of a Message — the Mini App constructor
    pays through the same successful_payment pipeline and has no Message to
    reply into; the user's private chat id serves both callers.
    V3.44.10: ``source`` tells a no-charge run how it was paid ('peaches') so
    a failed avatar generation can refund peaches instead of going silent.
    """
    # V3.24.0: the admin free path used to pass the callback message, whose
    # from_user is the BOT — the session must be looked up by the real user id.
    if telegram_id is None:
        telegram_id = chat_id
    cons = _constructor_sessions.pop(telegram_id, None)
    if not cons:
        # V3.44.13: a redeploy wipes the in-memory session — fall back to the
        # persisted draft so a paid creation still completes instead of dying
        # with «что-то потерялось» (owner: «отображается только один персонаж»).
        draft = claim_constructor_draft(telegram_id)
        if draft is not None:
            try:
                draft_params = json.loads(draft.params_json or '{}')
            except ValueError:
                draft_params = {}
            cons = {'params': draft_params, 'step': len(CONSTRUCTOR_STEPS)}
            if draft.photo_reference_base64:
                cons['photo_reference_base64'] = draft.photo_reference_base64
            source = source or (draft.source or '')
        elif get_constructor_draft(telegram_id) is not None:
            # A resumed run already owns her — stay silent, it sends the messages.
            return
    else:
        # V3.44.14: stamp ownership on the draft too, so the periodic sweep
        # never double-spawns while this run is legitimately grinding.
        try:
            claim_constructor_draft(telegram_id)
        except Exception:
            pass
    if not cons:
        await bot.send_message(chat_id, 'что-то потерялось 😕 нажми «🎨 Мой персонаж» ещё раз.')
        return
    params = cons['params']
    display_name = str(params.get('name') or 'Она')[:48]
    await bot.send_message(chat_id, '✨ Отлично! Рисую твою героиню — это займёт до минуты...')
    face_path = None
    photo_reference_path = None
    if telegram_id not in ADMIN_TELEGRAM_IDS:
        # V3.64.6: generating from a real person's uploaded photo is admin-only.
        cons = {k: v for k, v in cons.items() if k not in ('photo_reference_base64', 'face_bytes', 'face_file_id')}
        params = {k: v for k, v in params.items() if k != 'photo_reference'}
    # V3.44.5: handle base64 photo reference from Mini App.
    photo_reference_base64 = cons.get('photo_reference_base64')
    if photo_reference_base64:
        import tempfile, base64
        photo_reference_path = Path(tempfile.gettempdir()) / f'constructor_photo_ref_{telegram_id}.jpg'
        try:
            # Decode base64 data URL: data:image/jpeg;base64,...
            header, data = photo_reference_base64.split(',', 1)
            photo_bytes = base64.b64decode(data)
            photo_reference_path.write_bytes(photo_bytes)
        except Exception:
            logger.exception('constructor base64 photo decode failed user=%s', telegram_id)
            photo_reference_path = None
    # V3.44.5: download photo reference if user uploaded via bot (file_id).
    photo_reference_file_id = params.get('photo_reference', '')
    if photo_reference_file_id and photo_reference_file_id != 'base64_pending':
        import tempfile
        photo_reference_path = Path(tempfile.gettempdir()) / f'constructor_photo_ref_{telegram_id}.jpg'
        try:
            photo_file = await bot.get_file(photo_reference_file_id)
            photo_bytes = await bot.download_file(photo_file.file_path)
            photo_reference_path.write_bytes(photo_bytes)
        except Exception:
            logger.exception('constructor photo reference download failed user=%s', telegram_id)
            photo_reference_path = None
    if cons.get('face_bytes'):
        import tempfile
        face_path = Path(tempfile.gettempdir()) / f'constructor_face_{telegram_id}.jpg'
        try:
            face_path.write_bytes(cons['face_bytes'])
        except OSError:
            face_path = None
    # Use photo_reference as the primary identity anchor if available.
    identity_anchor = photo_reference_path or face_path
    # V3.44.12/14: two attempts 20s apart, each capped by wait_for — when fal
    # hangs on every candidate one attempt could otherwise eat ~30 minutes
    # (3 routes × 3 retries × 210s) and the persona never reached the save.
    # Whatever happens, the character is STILL saved below within minutes:
    # an invisible persona was exactly the owner's complaint («создал, а её
    # нет нигде»). A missing avatar heals lazily on the first photo request
    # (ensure_custom_avatar_cached), via the delayed retry task, and via the
    # V3.44.13/14 draft resume (startup scan + periodic sweep).
    avatar_bytes = None
    try:
        for attempt in (1, 2):
            try:
                avatar_bytes, _mime = await asyncio.wait_for(
                    generate_custom_avatar(
                        build_avatar_prompt(params, face_swap=bool(identity_anchor)), identity_anchor,
                    ),
                    timeout=260,
                )
                break
            except Exception:
                logger.exception('constructor avatar generation failed user=%s attempt=%s', telegram_id, attempt)
                if attempt < 2:
                    await asyncio.sleep(20)
    finally:
        if face_path:
            try:
                face_path.unlink()
            except OSError:
                pass
        if photo_reference_path:
            try:
                photo_reference_path.unlink()
            except OSError:
                pass
    avatar_failed = avatar_bytes is None
    if avatar_failed:
        await bot.send_message(chat_id, 'провайдеры рисования сейчас лежат 😔 создаю её без аватара — фото появится само, как только они оживут.')
    avatar_file_id = None
    if avatar_bytes:
        try:
            sent = await bot.send_photo(telegram_id, BufferedInputFile(avatar_bytes, filename='avatar.jpg'))
            avatar_file_id = sent.photo[-1].file_id
        except Exception:
            logger.exception('constructor avatar telegram upload failed user=%s', telegram_id)
            avatar_file_id = None
    # V3.44.15: the save itself used to be the unprotected step — a legacy
    # UNIQUE index (v3.19.0 schema) on custom_characters.telegram_id rejected
    # every second persona with IntegrityError, the run crashed silently and
    # the sweep re-drew her forever. Now: clear message, refund, draft closed.
    is_community = params.get('community') == 'community_yes'
    try:
        row = save_custom_character(
            telegram_id, display_name=display_name, params=params,
            avatar_file_id=avatar_file_id, face_file_id=cons.get('face_file_id'),
            description=params.get('backstory', ''),
            personality=params.get('personality', ''),
            backstory=params.get('backstory', ''),
            # V3.45.28: a community submit is NOT auto-published — she waits in
            # the moderation queue, so the storefront flag stays off for now.
            community_published=False,
            photo_reference_file_id=photo_reference_file_id or None,
            # V3.45.28: sanitized free-text tags for the storefront + filter.
            tags=normalize_tags(params.get('tags', '')),
            moderation_status='pending' if is_community else 'none',
            # V3.44.6: author revenue sharing — creator earns 5% from spending.
            author_telegram_id=str(telegram_id),
            author_revenue_percent=5.0,
        )
    except Exception:
        logger.exception('constructor persona save failed user=%s name=%s', telegram_id, display_name)
        try:
            await bot.send_message(chat_id, f'не получилось сохранить {display_name} 😕 техническая ошибка на моей стороне — попробуй ещё раз через минуту, оплата вернулась.')
        except Exception:
            logger.exception('constructor save-fail notify failed user=%s', telegram_id)
        if charge:
            try:
                await bot.refund_star_payment(user_id=telegram_id, telegram_payment_charge_id=charge)
                record_refund(telegram_id, charge, CONSTRUCTOR_COST_STARS, product='constructor')
            except Exception:
                logger.exception('constructor save-fail stars refund failed user=%s', telegram_id)
        elif source == 'peaches':
            try:
                grant_photo_credits(
                    telegram_id, CONSTRUCTOR_COST_PEACHES,
                    reason=f'constructor_refund:{telegram_id}:{int(_time.time() * 1000)}', bonus=False,
                )
            except Exception:
                logger.exception('constructor save-fail peach refund failed user=%s', telegram_id)
        try:
            finish_constructor_draft(telegram_id)
        except Exception:
            logger.exception('constructor draft finish mark failed user=%s', telegram_id)
        return
    # V3.44.7: save avatar to disk immediately so the Mini App can serve it
    # without waiting for ensure_custom_avatar_cached to download from Telegram.
    if avatar_bytes:
        try:
            from services.photo_service import _custom_reference_dir
            avatar_folder = _custom_reference_dir(row.character_id)
            avatar_folder.mkdir(parents=True, exist_ok=True)
            (avatar_folder / 'avatar.jpg').write_bytes(avatar_bytes)
        except Exception:
            logger.exception('constructor avatar disk save failed user=%s', telegram_id)
    # V3.31.8: creating a persona selects her immediately. Before this the
    # selection stayed on the previous character (Anna by default), so a user
    # who built their own girl and pressed «💕 Свидание» got a date with Anna.
    set_user_character(telegram_id, row.character_id)
    track_event(ensure_user(telegram_id), 'character_selected', metadata={'character_id': row.character_id, 'custom': True})
    # Register her as a real character card so photo/relationship pipelines
    # recognize the id; bio carries the appearance description for prompts.
    # V3.44.7: build a human-readable bio from appearance params only.
    # Previously it dumped ALL option labels (including "да, опубликовать")
    # which looked like garbage on the character page.
    APPEARANCE_KEYS = ('style', 'age', 'face', 'body', 'breast', 'waist', 'hips', 'hair', 'eyes', 'temperament', 'profession', 'role')
    descriptor_bits = [
        OPTION_LABELS[str(params[key])] for key in APPEARANCE_KEYS
        if key in params and str(params[key]) in OPTION_LABELS
    ]
    # V3.44.4: include backstory and personality in the bio if provided.
    backstory_text = params.get('backstory', '')
    personality_text = params.get('personality', '')
    # Build a proper sentence: "Name — appearance. Backstory. Personality."
    bio_parts = []
    if descriptor_bits:
        bio_parts.append(f'{display_name} — {", ".join(descriptor_bits).lower()}.')
    if backstory_text:
        bio_parts.append(backstory_text)
    if personality_text:
        bio_parts.append(personality_text)
    bio = ' '.join(bio_parts)[:900] if bio_parts else f'{display_name} — загадочная незнакомка.'
    # V3.59.4: the glued option labels read crooked on the storefront — ask the
    # chat model for a short teaser; the glued line stays as the fallback.
    try:
        nice_bio = await asyncio.wait_for(write_card_bio(params, display_name), timeout=25)
    except Exception:
        nice_bio = None
    bio = nice_bio or template_card_bio(params, display_name)
    card_age = AGE_BY_GROUP.get(str(params.get('age')), 25)
    # V3.45.28: a community persona is queued for review, so her card stays
    # hidden until an admin approves; is_community still drives the ping below.
    is_community = params.get('community') == 'community_yes'
    # V3.55.3: a persona drafted on the «⭐ Premium» tab by an admin registers
    # with the premium card status — the same flag the admin panel sets and
    # every existing premium gate keys on.
    card_status = ('premium' if cons.get('premium') and telegram_id in ADMIN_TELEGRAM_IDS
                   else 'active')
    try:
        if get_card(row.character_id):
            update_card(
                row.character_id, display_name=display_name, age=card_age,
                short_bio=bio, status=card_status, card_photo_file_id=avatar_file_id,
                is_visible=False,
            )
        else:
            # V3.37.0: anime personas get their own card emoji.
            card_emoji = '🌸' if str(params.get('style', '')) == 'style_anime' else ''
            create_card(row.character_id, display_name, card_age, bio, card_emoji, 'female')
            update_card(row.character_id, status=card_status, card_photo_file_id=avatar_file_id, is_visible=False)
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
    # V3.46.0: mission — the user has now built their own character (covers the
    # bot Stars flow, the peach flow and the Mini App wizard, all of which land
    # here).
    if telegram_id:
        await _notify_unlock(chat_id, telegram_id, 'first_creation')
    # V3.45.28: publishing to the «Сообщество» витрина goes through a human
    # first — ping every admin with approve/reject and tell the owner why she
    # is not live yet. A private persona skips this entirely.
    if is_community:
        try:
            await bot.send_message(
                chat_id,
                '🕓 она отправлена на модерацию в «Сообщество» — как только админ её '
                'одобрит, она появится на витрине для всех. пока она полностью твоя.',
            )
        except Exception:
            logger.exception('constructor moderation owner-notify failed user=%s', telegram_id)
        await _request_character_moderation(row.character_id, telegram_id, display_name, avatar_file_id)
    if avatar_failed:
        # V3.44.12: the persona exists but the paid product did not fully
        # deliver (no avatar) — return the money and queue the delayed avatar
        # retries. The Stars branch mirrors the original V3.35.0 refund.
        if charge:
            try:
                await bot.refund_star_payment(user_id=telegram_id, telegram_payment_charge_id=charge)
                record_refund(telegram_id, charge, CONSTRUCTOR_COST_STARS, product='constructor')
                await bot.send_message(chat_id, 'Stars вернула автоматически ✅ персонаж остался у тебя — аватар дорисую позже.')
            except Exception:
                logger.exception('constructor refund failed user=%s', telegram_id)
                await bot.send_message(chat_id, 'не смогла вернуть Stars автоматически 😕 напиши /support — вернём вручную.')
        elif source == 'peaches':
            # V3.44.10/12: peaches were already spent at the buy step — put
            # them back; the unique reason sidesteps the idempotency marker.
            try:
                grant_photo_credits(
                    telegram_id, CONSTRUCTOR_COST_PEACHES,
                    reason=f'constructor_refund:{telegram_id}:{int(_time.time() * 1000)}', bonus=False,
                )
                await bot.send_message(chat_id, f'{CONSTRUCTOR_COST_PEACHES} 🍑 снова на балансе ✅ персонаж остался у тебя — аватар дорисую позже.')
            except Exception:
                logger.exception('constructor peaches refund failed user=%s', telegram_id)
                await bot.send_message(chat_id, f'аватар не получился 😕 напиши /support — вернём {CONSTRUCTOR_COST_PEACHES} 🍑.')
        asyncio.create_task(_retry_constructor_avatar(telegram_id, row.character_id))
    # V3.44.13: her draft is complete — the startup scan must not resume her.
    try:
        finish_constructor_draft(telegram_id)
    except Exception:
        logger.exception('constructor draft finish mark failed user=%s', telegram_id)


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
        if telegram_id not in ADMIN_TELEGRAM_IDS:
            await cq.answer()
            await _constructor_confirm(cq.message.chat.id, telegram_id)
            return
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
    # V3.64.6: the look-alike photo step is admin-only.
    while (telegram_id not in ADMIN_TELEGRAM_IDS and cons['step'] < len(CONSTRUCTOR_STEPS)
           and CONSTRUCTOR_STEPS[cons['step']].get('photo_upload')):
        cons['step'] += 1
    await cq.answer()
    # V3.44.4: handle free_text steps (backstory, personality) and community step.
    # V3.44.5: handle photo_upload steps (reference photo).
    if cons['step'] < len(CONSTRUCTOR_STEPS):
        next_key = CONSTRUCTOR_STEPS[cons['step']]['key']
        next_step = CONSTRUCTOR_STEPS[cons['step']]
        # Free text steps: ask for text input instead of showing buttons.
        if next_step.get('free_text'):
            cons['await'] = f'text_{next_key}'
            await cq.message.answer(f'🎨 {next_step["title"]}\n\nНапиши текст одним сообщением или отправь /skip чтобы пропустить.')
            return
        # Photo upload steps: ask for a photo.
        if next_step.get('photo_upload'):
            cons['await'] = f'photo_{next_key}'
            await cq.message.answer(f'📷 {next_step["title"]}\n\nПришли фото одним сообщением или отправь /skip чтобы пропустить.')
            return
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
    # V3.27.0: a ruble-paid constructor credit (Platega since V3.44.21) skips Stars too.
    if consume_constructor_credit(telegram_id):
        record_payment(telegram_id, 'constructor', 0, f'rub_credit:{telegram_id}:{int(_time.time() * 1000)}')
        _spawn_job('constructor', telegram_id, _finish_constructor(cq.message.chat.id, None, telegram_id), payload={'source': 'free'})
        return
    await send_stars_invoice(
        cq.message.chat.id,
        'Личный персонаж',
        'Конструктор создаст уникальную собеседницу с аватаром. Платёж одноразовый.',
        f'constructor:{telegram_id}',
        CONSTRUCTOR_COST_STARS,
    )


# V3.44.2: pay for constructor with peaches (photo credits)
@dp.callback_query(F.data == 'constructor:buy_peaches')
async def constructor_buy_peaches_cb(cq: types.CallbackQuery):
    telegram_id = cq.from_user.id
    cons = _constructor_sessions.get(telegram_id)
    if not cons or not cons.get('params', {}).get('name'):
        await cq.answer('Сначала собери персонажа до конца 🙂', show_alert=True)
        return
    await cq.answer()
    # Check if user has enough peaches
    credits = get_photo_credits(telegram_id)
    if credits < CONSTRUCTOR_COST_PEACHES:
        await cq.answer(f'Не хватает персиков! Нужно {CONSTRUCTOR_COST_PEACHES}, у тебя {credits} 🍑', show_alert=True)
        return
    # Deduct peaches and create character
    if not spend_peaches(telegram_id, CONSTRUCTOR_COST_PEACHES):
        await cq.answer('Не удалось списать персики ', show_alert=True)
        return
    record_payment(telegram_id, 'constructor_peaches', 0, f'peaches:{telegram_id}:{int(_time.time() * 1000)}', provider='peaches')
    await cq.message.answer(f'🍑 Списано {CONSTRUCTOR_COST_PEACHES} персиков. Создаю персонажа...')
    _spawn_job('constructor', telegram_id, _finish_constructor(cq.message.chat.id, None, telegram_id, source='peaches'), payload={'source': 'peaches'})


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
    # V3.44.8: the user may own several characters — check the whole list,
    # not just the first one (which blocked chat for character #2+).
    row = next((c for c in get_all_custom_characters(cq.from_user.id)
                if c.character_id == character_id), None)
    if not row:
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
    for item in newly_unlocked_quests(telegram_id, before_level, after_level, get_user_character(telegram_id)):
        await bot.send_message(
            chat_id,
            f'🎯 Открылась новая история: «{item["title"]}» ✨\n\n{item.get("teaser", "У Анны появился новый выбор, на который можешь повлиять.")}',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text='Начать историю', callback_data=f'quest:view:{item["key"]}')]
            ]),
        )
        track_event(ensure_user(telegram_id), 'quest_unlocked', metadata={'quest': item['key'], 'level': after_level})


# V3.61.9 / V3.62.0: the top levels of each path — her own words and a photo
# that belongs to that moment. Romance (default), romance when she is taken,
# and passion. Levels 4-6 get a line of her own (LEVEL_UP_LINES) and the
# usual celebration selfie.
LEVEL_UP_SCENES = {
    'devoted': (
        'знаешь… я проснулась сегодня и первым делом подумала о тебе. '
        'надела твою рубашку — пусть будет наше утро 🤍',
        PhotoRequest(scene='selfie', location='her bed in soft morning light, white sheets, two coffee cups on the nightstand',
                     clothing="his oversized white button-up shirt, sleeves rolled up", mood='tender, sleepy, in love',
                     angle='she lies on the pillow and holds the phone above her face, her whole face in frame', customized=True),
    ),
    'soulmate': (
        'я тут подумала… а давай уже не «ты у себя, я у себя»? '
        'наш дом, наши выходные, наше всё. вот, держи ключи 🏠',
        PhotoRequest(scene='selfie', location='a cozy shared apartment at golden hour, warm light, moving boxes and flowers on the table',
                     clothing='a soft oversized sweater and home shorts', accessory='she holds a set of apartment keys near her face',
                     mood='happy, glowing, at home',
                     angle='selfie at arm\'s length in the new apartment, the keys and her whole face in frame', customized=True),
    ),
    'voyage': (
        'мы правда это сделали — только ты, я и море 🌊 '
        'я хочу запомнить этот день навсегда',
        PhotoRequest(scene='selfie', location='a seaside hotel balcony at sunset, the sea and palm trees behind her',
                     clothing='a light summer dress, sunglasses pushed up into her hair', mood='happy, free, in love',
                     angle='selfie at arm\'s length, the sea behind her, her whole face in frame', customized=True),
    ),
    'eternal': (
        'я тут подумала… я хочу просыпаться с тобой всегда. '
        'и да — я согласна 💍',
        PhotoRequest(scene='selfie', location='your shared apartment in the evening, candles and flowers on the table',
                     clothing='a soft elegant dress', accessory='a delicate engagement ring on her ring finger, clearly visible',
                     mood='happy tears, glowing, in love',
                     angle='she holds her hand with the ring near her face, both the ring and her whole face in frame', customized=True),
    ),
}

# She is married or has a boyfriend: a secret romance, never a ring from him.
LEVEL_UP_SCENES_TAKEN = {
    'devoted': (
        'он уехал до вечера… а я проснулась и думаю только о тебе. '
        'надела твою рубашку, которую ты у меня забыл 🤫 это наше утро',
        PhotoRequest(scene='selfie', location='her bed in soft morning light, white sheets, the apartment quiet and empty',
                     clothing="a man's oversized white button-up shirt, sleeves rolled up", mood='tender, secretive, in love',
                     angle='she lies on the pillow and holds the phone above her face, her whole face in frame', customized=True),
    ),
    'soulmate': (
        'я сняла кольцо. когда я с тобой — я только твоя. '
        'у нас теперь есть своё место, только для нас двоих 🔑',
        PhotoRequest(scene='selfie', location='a small cozy rented apartment in the evening, warm lamp light, a single key on the table',
                     clothing='a soft elegant dress', accessory='she holds a small apartment key near her face, no ring on her fingers',
                     mood='nervous, happy, in love',
                     angle='selfie at arm\'s length, the key and her whole face in frame', customized=True),
    ),
    'voyage': (
        'я сказала ему, что еду к подруге… а сама еду к тебе. '
        'два дня только наши, сбежим? 🚗',
        PhotoRequest(scene='selfie', location='the passenger seat of a car on a sunny country road, a small weekend bag on her lap',
                     clothing='a denim jacket over a light dress, sunglasses in her hair', accessory='no ring on her fingers',
                     mood='excited, a little guilty, in love',
                     angle='selfie at arm\'s length inside the car, her whole face in frame', customized=True),
    ),
    'eternal': (
        'я ушла от него. совсем. собрала вещи и стою у твоей двери… '
        'я выбираю тебя 🧳',
        PhotoRequest(scene='selfie', location='a doorway of an apartment building at night, warm light from the hall, a small suitcase beside her',
                     clothing='a light trench coat over a simple dress', accessory='no ring on her fingers',
                     mood='nervous, hopeful, a little teary, in love',
                     angle='selfie at arm\'s length, the suitcase and her whole face in frame', customized=True),
    ),
}

# The passion path: bolder, teasing, a secret affair when she is taken.
LEVEL_UP_SCENES_PASSION = {
    'devoted': (
        'я сняла номер на вечер. адрес пришлю позже… '
        'никто не должен знать 🤫🔥',
        PhotoRequest(scene='selfie', location='a dim boutique hotel room at night, city lights in the window, a key card on the bed',
                     clothing='a black silk robe over lace lingerie', mood='seductive, secretive, confident',
                     angle='mirror selfie by the bed, her whole face in frame', customized=True),
    ),
    'soulmate': (
        'я не могу без тебя. весь день думаю только о тебе… '
        'где ты был? я ждала 😈',
        PhotoRequest(scene='selfie', location='her bedroom late at night, only a bedside lamp on, messy sheets',
                     clothing='his oversized t-shirt slipping off one shoulder', mood='longing, possessive, sultry',
                     angle='she lies on the bed and holds the phone above her face, her whole face in frame', customized=True),
    ),
    'voyage': (
        'у меня есть фантазия… и сегодня я в образе. '
        'угадаешь, кто я? 😏',
        PhotoRequest(scene='selfie', location='a stylish dim room with soft red light',
                     clothing='a fitted roleplay costume: a strict secretary look with a pencil skirt, open-collar blouse and glasses',
                     mood='playful, daring, seductive',
                     angle='mirror selfie, her whole face in frame', customized=True),
    ),
    'eternal': (
        'с тобой у меня больше нет правил. '
        'только ты и всё, что ты захочешь 🔥',
        PhotoRequest(scene='selfie', location='a luxurious bedroom at night, candles, silk sheets',
                     clothing='elegant black lace lingerie under a sheer robe', mood='confident, bold, in love',
                     angle='mirror selfie, her whole face in frame', customized=True),
    ),
}
LEVEL_UP_LINES = {
    'romance': {
        'intimate': 'я поймала себя на том, что весь день улыбаюсь в телефон… это из-за тебя 🙈',
        'deeply_connected': 'это было лучшее свидание в моей жизни. я до сих пор улыбаюсь 🥰',
        'committed': 'для меня теперь есть только ты. и у меня для тебя есть особое имя 💞',
    },
    'passion': {
        'intimate': 'интересно, что ты сейчас представил? 😏 я — кое-что очень смелое',
        'deeply_connected': 'давай сыграем. угадай, что на мне надето… подсказок не будет 😈',
        'committed': 'я больше не хочу сдерживаться. пиши мне ночью 🔥',
    },
}
LEVEL_UP_LINES_TAKEN = {
    'passion': {'committed': 'он уже спит… а я пишу тебе. и мне совсем не стыдно 🤫🔥'},
}


def _level_up_scene(new_stage: str, branch: str | None, taken: bool):
    if branch == 'passion':
        return LEVEL_UP_SCENES_PASSION.get(new_stage)
    return (LEVEL_UP_SCENES_TAKEN if taken else LEVEL_UP_SCENES).get(new_stage)


def _level_up_line(new_stage: str, branch: str | None, taken: bool) -> str:
    if not branch:
        return ''
    if taken and new_stage in LEVEL_UP_LINES_TAKEN.get(branch, {}):
        return LEVEL_UP_LINES_TAKEN[branch][new_stage]
    return LEVEL_UP_LINES.get(branch, {}).get(new_stage, '')


def _relationship_branch(telegram_id: int, character_id: str) -> str | None:
    try:
        from services.relationship_engine import branch_of, get_state
        with SessionLocal() as session:
            return branch_of(get_state(session, ensure_user(telegram_id), character_id))
    except Exception:
        return None


async def _on_relationship_stage_up(telegram_id: int, old_stage: str, new_stage: str, character_id: str):
    """Level-up ceremony: announce the new stage, list fresh unlocks and send a
    small celebration set. Registered as the relationship notifier, so it fires
    from chat, gifts, dates and apartment actions alike."""
    try:
        await asyncio.sleep(3)  # let her chat reply land first
        from services.photo_service import STAGE_INDEX, SCENE_LEVELS
        level = STAGE_INDEX.get(new_stage, 0) + 1
        # V3.62.0: the name of the level on HIS path.
        from services.chat_guest_service import guest_marital
        from services.relationship_engine import TAKEN_STATUSES, BRANCH_LABELS, level_title
        taken = guest_marital(telegram_id, character_id) in TAKEN_STATUSES
        branch = _relationship_branch(telegram_id, character_id)
        name = level_title(level, branch, taken) or RELATIONSHIP_LEVEL_NAMES.get(level, new_stage)
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
        text = f'❤️ Между нами что-то изменилось…\nНовый этап: {name} · уровень {level}/10'
        if branch and level >= 4:
            text += f'\n{BRANCH_LABELS[branch]}'
        line = _level_up_line(new_stage, branch, taken)
        if line:
            text += '\n\n' + line
        # V3.21.0: from level 3 she has her own name for him.
        if level == 3:
            from services import couple_service
            pet = couple_service.assign_pet_name(telegram_id)
            if pet:
                text += f'\n\nи да… теперь я буду звать тебя «{pet}» 😊'
        if level >= 7:
            text += '\n\nэто плато только для нас двоих — такое доступно лишь с Premium 💋'
        # V3.61.9: levels 7+ get their own scene and photo instead of the
        # generic «небольшой подарок» selfie — per path and status.
        special = _level_up_scene(new_stage, branch, taken)
        if special:
            text += '\n\n' + special[0]
        if unlocks:
            text += '\n\nТеперь доступно:\n' + '\n'.join('• ' + u for u in unlocks)
        if not special:
            text += '\n\nи небольшой подарок от меня 🤍'
        await bot.send_message(telegram_id, text)
        try:
            save_message(ensure_user(telegram_id), character_id, 'assistant', text)
        except Exception:
            pass
        # V3.62.0: from level 3 she asks him which path they are on.
        from services import branch_service
        if level >= 3 and not branch:
            await asyncio.to_thread(branch_service.maybe_offer_fork, ensure_user(telegram_id), character_id, taken=taken)
        if taken and branch != 'passion' and new_stage == 'eternal':
            await asyncio.to_thread(branch_service.mark_left_him, ensure_user(telegram_id), character_id)
        track_event(ensure_user(telegram_id), 'relationship_ceremony_sent', metadata={'level': level}, character_id=character_id)
        await _maybe_level_up_premium_offer(telegram_id, level)
        if special:
            await _start_photo_background(telegram_id, telegram_id, special[1], 'story')
        else:
            await _start_photo_background(telegram_id, telegram_id, PhotoRequest(scene='selfie', mood='romantic'), 'story')
    except Exception as exc:
        logger.warning('level-up ceremony failed user=%s error=%s', telegram_id, type(exc).__name__)


async def _maybe_level_up_premium_offer(telegram_id: int, level: int) -> None:
    """V3.62.9: nobody saw Premium on day one (the first 24h are unlimited and
    the first limit hit gives a free demo) — 0 purchases in 30 days. The first
    level-up is a warm moment: she opens the one-time −30% window herself,
    once per user (offer_discount is True only when it just opened)."""
    try:
        from services.retention_service import offer_discount, discount_info
        if level < 2 or telegram_id in ADMIN_TELEGRAM_IDS or is_premium(telegram_id):
            return
        if not await asyncio.to_thread(offer_discount, telegram_id):
            return
        d = discount_info(telegram_id)
        text = ('кстати… мне так хорошо с тобой, что хочу сделать подарок 🙈 '
                f'сегодня Premium для тебя −{d.get("percent", 30)}%: без лимита сообщений, мои кружочки, '
                'голосовые и уровни 7–10, где я только твоя 💋 предложение действует {d.get("hours_left", 24):.0f} ч')
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text=f'⭐ Premium −{d.get("percent", 30)}% — {d.get("price")}⭐', callback_data='retention:premium')]])
        await bot.send_message(telegram_id, text, reply_markup=kb)
        track_event(ensure_user(telegram_id), 'premium_offer_levelup', metadata={'level': level})
    except Exception:
        logger.exception('level-up premium offer failed user=%s', telegram_id)


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


# V3.55.6: premium floor — a Premium user meeting a premium-status character
# (built-in lineup or a constructor persona flipped to «premium») starts at level 6
# («Наша история»). Admins count as premium here. The engine keeps zero access
# logic: it only asks this callback.
def _premium_floor_needs(uid: int, character_id: str) -> bool:
    try:
        with SessionLocal() as session:
            user = session.get(User, uid)
            tid = int(user.telegram_id) if user else 0
        if not (tid in ADMIN_TELEGRAM_IDS or is_premium(tid)):
            return False
        card = get_card(character_id)
        return bool(card and card.status == 'premium')
    except Exception:
        return False


from services.relationship_engine import set_premium_floor_provider
set_premium_floor_provider(_premium_floor_needs)


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
        direct_undress = _direct_undress_request(text)
        if not request:
            request = _show_me_request(text) or direct_undress
        if request:
            await handle_photo_request(message.chat.id, message.from_user.id, request,
                                       undress_credit=direct_undress is not None, text=text)
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
        await _maybe_set_alarm(message, text, 'и время тоже запомнила 😌 пояс: {tz}')
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


@dp.message(Command('backup'))
async def admin_backup_cmd(message: types.Message):
    """V3.82.0: an on-demand DB backup for the owner (the daily one runs at 03:30 MSK)."""
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    from services import backup_service
    await message.answer('🗄 собираю бэкап базы…')
    try:
        data, counts = await asyncio.to_thread(backup_service.dump_database)
    except Exception:
        logger.exception('db backup dump failed (manual)')
        await message.answer('⚠️ бэкап не получился, смотри логи Railway (db backup).')
        return
    caption = backup_service.summary_line(counts, len(data))
    if len(data) > backup_service.TELEGRAM_DOC_LIMIT:
        await message.answer(caption + '\n⚠️ файл больше лимита Telegram (50 МБ).')
        return
    await message.answer_document(BufferedInputFile(data, filename=backup_service.backup_filename()),
                                  caption=caption[:1000])


@dp.message(Command('girlday', 'post'))
async def admin_girlday_cmd(message: types.Message):
    """V3.92.0: today's «🔥 Девушка дня» with the channel post and a switch.
    V3.94.0: starts with the girl picker."""
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    from services import girl_of_day
    markup = await asyncio.to_thread(girl_of_day.picker_markup)
    await message.answer('📣 Пост в канал: выбери девушку (🔥 — сегодняшняя). '
                         'Она станет «Девушкой дня» до 03:00 МСК.', reply_markup=markup)


@dp.callback_query(F.data.startswith('gday:'))
async def admin_girlday_cb(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        await cq.answer()
        return
    from services import girl_of_day
    parts = cq.data.split(':')
    # V3.94.0: «📣 Пост в канал» → pick the girl → a ready post with a random
    # inviting text; «🎲 Другой текст» rolls another one.
    if parts[1] in ('menu', 'next'):
        markup = await asyncio.to_thread(girl_of_day.picker_markup)
        await cq.answer()
        await cq.message.answer('📣 Пост в канал: выбери девушку (🔥 — сегодняшняя). '
                                'Она станет «Девушкой дня» до 03:00 МСК.', reply_markup=markup)
        return
    if parts[1] == 'pick' and len(parts) > 2:
        girls = await asyncio.to_thread(girl_of_day.pool)
        if parts[2] not in girls:
            await cq.answer('этой девушки нет в ротации', show_alert=True)
            return
        await asyncio.to_thread(girl_of_day.set_today, parts[2])
        await cq.answer(f'сегодня: {girl_of_day.name_of(parts[2])}')
        await girl_of_day.send_admin_preview(bot, cq.message.chat.id, parts[2])
        return
    if parts[1] == 'post' and len(parts) > 2:
        channel = '@' + CHANNEL_SUBSCRIBE_USERNAME
        variant = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None
        try:
            await girl_of_day.publish(bot, channel, parts[2], variant)
        except Exception as e:
            logger.warning('girl of day publish failed: %s', e)
            await cq.answer('не получилось: бот должен быть админом канала с правом публикации', show_alert=True)
            return
        await cq.answer('опубликовано в канале ✅', show_alert=True)
        return
    await cq.answer()


# ── V3.129.0: channel rubrics «🗳 Выбираете вы» + «💬 Диалог дня» ──
# Owner brought a «как вести канал» template: polls where the audience picks
# the next girl/look/story, and short example chats. Admin preview first;
# poll results come only from Telegram's real vote counts (stop_poll).
def _chpost_kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=c)] for t, c in rows])


@dp.message(Command('rubric'))
async def admin_rubric_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    await message.answer('Рубрики канала: выбери, что подготовить.', reply_markup=_chpost_kb(
        [('🗳 Опрос «Выбираете вы»', 'chpost:poll'), ('💬 Диалог дня', 'chpost:dlg')]))


@dp.callback_query(F.data.startswith('chpost:'))
async def admin_chpost_cb(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        await cq.answer()
        return
    from services import channel_rubrics as cr
    from services import girl_of_day
    parts = (cq.data or '').split(':')
    action = parts[1] if len(parts) > 1 else ''
    channel = '@' + CHANNEL_SUBSCRIBE_USERNAME
    no_rights = 'не получилось: бот должен быть админом канала с правом публикации'
    if action == 'poll':
        n = cr.random_poll()
        await cq.answer()
        await cq.message.answer(cr.poll_preview(n), reply_markup=_chpost_kb(
            [('📣 Опубликовать опрос', f'chpost:pollpub:{n}'), ('🎲 Другой опрос', 'chpost:poll')]))
        return
    if action == 'pollpub' and len(parts) > 2 and parts[2].isdigit():
        n = int(parts[2])
        q, opts = cr.poll(n)
        try:
            sent = await bot.send_poll(channel, question=q, options=opts, is_anonymous=True)
        except Exception as e:
            logger.warning('channel poll publish failed: %s', e)
            await cq.answer(no_rights, show_alert=True)
            return
        await asyncio.to_thread(cr.remember_poll, sent.message_id, n)
        await cq.answer('опрос в канале ✅')
        await cq.message.answer('🗳 Опрос опубликован. Когда наберутся голоса (обычно через 1–2 дня), '
                                'нажми кнопку: опрос закроется, и я подготовлю пост с итогом.',
                                reply_markup=_chpost_kb([('🛑 Закрыть и посчитать', f'chpost:pollstop:{sent.message_id}')]))
        return
    if action == 'pollstop' and len(parts) > 2 and parts[2].isdigit():
        mid = int(parts[2])
        try:
            res = await bot.stop_poll(channel, mid)
        except Exception as e:
            logger.warning('channel poll stop failed: %s', e)
            await cq.answer('не получилось закрыть опрос (уже закрыт или удалён?)', show_alert=True)
            return
        counts = [(o.text, int(o.voter_count or 0)) for o in res.options]
        text = cr.results_text(res.question, counts)
        if text:
            await asyncio.to_thread(cr.save_poll_results, mid, text)
        await cq.answer()
        if not text:
            await cq.message.answer('В опросе нет ни одного голоса, итог публиковать нечего.')
            return
        await cq.message.answer('👇 Пост с итогом (цифры из самого опроса):\n\n' + text,
                                reply_markup=_chpost_kb([('📣 Опубликовать итог', f'chpost:respub:{mid}')]))
        return
    if action == 'respub' and len(parts) > 2 and parts[2].isdigit():
        # the text was built at closing time from Telegram's own vote counts
        text = await asyncio.to_thread(cr.poll_results, int(parts[2]))
        if not text:
            await cq.answer('итог этого опроса не найден, закрой опрос ещё раз', show_alert=True)
            return
        try:
            await bot.send_message(channel, text, reply_markup=cr.results_markup())
        except Exception as e:
            logger.warning('channel poll results publish failed: %s', e)
            await cq.answer(no_rights, show_alert=True)
            return
        await cq.answer('итог в канале ✅', show_alert=True)
        return
    if action == 'dlg':
        girls = await asyncio.to_thread(girl_of_day.pool)
        if not girls:
            await cq.answer('в ротации нет девушек', show_alert=True)
            return
        cid = random.choice(girls)
        n = cr.random_dialog()
        await cq.answer()
        await _chpost_dialog_preview(cq.message.chat.id, cid, n)
        return
    if action == 'dlgpub' and len(parts) > 3 and parts[3].isdigit():
        cid, n = parts[2], int(parts[3])
        name = girl_of_day.name_of(cid)
        photo, _ = await asyncio.to_thread(girl_of_day.build_post, cid, 0)
        caption = cr.dialog_caption(name, n)
        try:
            if photo:
                await bot.send_photo(channel, BufferedInputFile(photo, filename=f'{cid}.jpg'),
                                     caption=caption[:1024], reply_markup=cr.dialog_markup(cid, name))
            else:
                await bot.send_message(channel, caption, reply_markup=cr.dialog_markup(cid, name))
        except Exception as e:
            logger.warning('channel dialog publish failed: %s', e)
            await cq.answer(no_rights, show_alert=True)
            return
        await cq.answer('опубликовано в канале ✅', show_alert=True)
        return
    await cq.answer()


async def _chpost_dialog_preview(chat_id: int, cid: str, n: int) -> None:
    from services import channel_rubrics as cr
    from services import girl_of_day
    name = girl_of_day.name_of(cid)
    photo, _ = await asyncio.to_thread(girl_of_day.build_post, cid, 0)
    head = '👇 «Диалог дня». Переписка постановочная, в посте так и написано:\n\n'
    kb = _chpost_kb([('📣 Опубликовать в канал', f'chpost:dlgpub:{cid}:{n}'), ('🎲 Другой диалог / девушка', 'chpost:dlg')])
    caption = cr.dialog_caption(name, n)
    if photo:
        await bot.send_photo(chat_id, BufferedInputFile(photo, filename=f'{cid}.jpg'),
                             caption=(head + caption)[:1024], reply_markup=kb)
    else:
        await bot.send_message(chat_id, head + caption, reply_markup=kb)


@dp.message(Command('week'))
async def admin_week_cmd(message: types.Message):
    """V3.97.0: the weekly report on demand (it also arrives Mondays 09:00 MSK)."""
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    from services import weekly_report
    data = await asyncio.to_thread(weekly_report.collect, 7)
    await message.answer(weekly_report.render(data, _character_display_name))


# ── V3.108.0: /voicecast — the owner's one-off evening voice to everyone ──
# Owner: «отправить всем пользователям голосовое… мягкое, человеческое,
# сексуальное. посмотрим, как звучит». First the admin hears it himself; the
# cast to everyone goes only after he taps the confirm button.
_voice_cast_running = False
@dp.callback_query(F.data.startswith('ritual_ok:'))
async def admin_ritual_approve(cq: types.CallbackQuery):
    """V3.110.0: test mode — the owner's «✅ Отправить всем» under the ritual
    preview releases today's morning/evening ritual to every user."""
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        await cq.answer()
        return
    try:
        _, kind, day = (cq.data or '').split(':', 2)
    except ValueError:
        await cq.answer()
        return
    if kind not in ('morning', 'evening'):
        await cq.answer()
        return
    from services import scheduler_service as _ss
    await asyncio.to_thread(_ss.approve_ritual, kind, day, cq.from_user.id)
    await cq.answer('Отправляю всем…')
    try:
        await cq.message.edit_reply_markup(reply_markup=None)
        await cq.message.answer('✅ Одобрено. Голосовые с фото уходят сейчас, а у кого другой часовой пояс, придут в их 9:00/20:00.')
    except Exception:
        pass
    asyncio.create_task(_ss._rituals(bot))


# ── V3.150.0: the owner picks the photo that goes under the voice note ────
# Owner: «дай мне возможность выбирать фото под голосовое». Under every ritual
# preview he now flips through her READY frames (no new renders, $0) and pins
# one for today's morning/evening ritual of that girl. The pin is a
# ProductEvent row, so a redeploy keeps it and the next day the automatic
# rotation takes over again; «🔄 Авто-подбор» hands it back sooner. Where the
# carousel stands is an admin editor session — in memory, like the other
# admin media screens.
RITUAL_PH_WAIT: dict[int, dict] = {}


def _ritual_ph_char(telegram_id: int) -> str:
    user = get_user(telegram_id)
    return (getattr(user, 'selected_character', '') or CHARACTER_ID) if user else CHARACTER_ID


def _ritual_ph_name(character_id: str) -> str:
    return _prophoto_char_names().get(character_id, character_id)


def _ritual_ph_choose_keyboard() -> InlineKeyboardMarkup:
    from services.character_card_service import list_cards
    try:
        cards = list_cards(visible_only=False)
    except Exception:
        cards = []
    rows, line = [], []
    for c in cards:
        line.append(InlineKeyboardButton(text=(c.display_name or c.character_id)[:12],
                                         callback_data=f'ritual_ph:char:{c.character_id}'))
        if len(line) == 2:
            rows.append(line)
            line = []
    if line:
        rows.append(line)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _ritual_ph_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='◀️', callback_data='ritual_ph:prev'),
         InlineKeyboardButton(text='✅ Это фото', callback_data='ritual_ph:set'),
         InlineKeyboardButton(text='▶️', callback_data='ritual_ph:next')],
        [InlineKeyboardButton(text='🔄 Авто-подбор', callback_data='ritual_ph:auto'),
         InlineKeyboardButton(text='👩 Другая героиня', callback_data='ritual_ph:char')]])


async def _ritual_ph_show(cq: types.CallbackQuery, state: dict, note: str = '') -> None:
    """One bubble: her frame, «3/18» and the pin buttons."""
    from services import evening_voice as _ev
    from services import scheduler_service as _ss
    cands = await asyncio.to_thread(_ev.owner_candidates, state['character_id'])
    if not cands:
        await cq.message.answer(
            f'📭 У «{_ritual_ph_name(state["character_id"])}» готовых кадров нет — '
            'загрузи их в «📸 Медиа для утра/вечера».',
            reply_markup=_ritual_ph_choose_keyboard())
        return
    idx = int(state.get('idx') or 0) % len(cands)
    picked = None
    for step in range(len(cands)):          # a render can age out of storage
        cur = (idx + step) % len(cands)
        media = await asyncio.to_thread(_ev.candidate_media, cands[cur]['source'], cands[cur]['ref'])
        if media and media[0]:
            picked = (cur, media)
            break
    if not picked:
        await cq.message.answer('📭 Кадры не читаются — проверь пул «📸 Медиа для утра/вечера».')
        return
    idx, media = picked
    state = {**state, 'idx': idx}
    RITUAL_PH_WAIT[cq.from_user.id] = state
    label = '🌅 утреннее' if state['kind'] == 'morning' else '🌙 вечернее'
    choice = await asyncio.to_thread(_ev.get_choice, state['kind'], _ss.ritual_day(), state['character_id'])
    caption = (
        (f'{note}\n\n' if note else '')
        + f'🖼 {_ritual_ph_name(state["character_id"])} · {idx + 1}/{len(cands)} — фото под {label} голосовое\n'
        + (f'📌 закреплен кадр #{choice["ref"]}' if choice else '🔄 сейчас играет авто-подбор')
        + ('' if cands[idx].get('checked') else '\n⚠️ этот кадр ещё не проходил vision-проверку'))
    try:
        await cq.message.edit_media(
            types.InputMediaPhoto(media=types.BufferedInputFile(media[0], filename='ritual_pick.jpg'),
                                  caption=caption),
            reply_markup=_ritual_ph_keyboard())
    except Exception:
        await cq.message.answer(caption, reply_markup=_ritual_ph_keyboard())


def _ritual_ph_state(cq: types.CallbackQuery) -> dict | None:
    state = RITUAL_PH_WAIT.get(cq.from_user.id)
    if not state or state.get('kind') not in ('morning', 'evening') or not state.get('character_id'):
        return None
    return state


@dp.callback_query(F.data.startswith('ritual_ph:open:'))
async def ritual_ph_open(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        await cq.answer()
        return
    kind = 'morning' if (cq.data or '').endswith('morning') else 'evening'
    await cq.answer()
    await _ritual_ph_show(cq, {'kind': kind, 'character_id': _ritual_ph_char(cq.from_user.id), 'idx': 0})


@dp.callback_query(F.data == 'ritual_ph:char')
async def ritual_ph_choose_girl(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        await cq.answer()
        return
    await cq.answer()
    await cq.message.answer('Чей кадр выбираем под голосовое?', reply_markup=_ritual_ph_choose_keyboard())


@dp.callback_query(F.data.startswith('ritual_ph:char:'))
async def ritual_ph_girl(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        await cq.answer()
        return
    state = _ritual_ph_state(cq) or {'kind': 'evening', 'character_id': '', 'idx': 0}
    char_id = (cq.data or '').split(':', 2)[2]
    await cq.answer()
    await _ritual_ph_show(cq, {**state, 'character_id': char_id, 'idx': 0})


@dp.callback_query(F.data.in_(('ritual_ph:prev', 'ritual_ph:next')))
async def ritual_ph_move(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        await cq.answer()
        return
    state = _ritual_ph_state(cq)
    if not state:
        await cq.answer('выбор фото закрылся — открой его заново под превью', show_alert=True)
        return
    await cq.answer()
    step = 1 if (cq.data or '').endswith('next') else -1
    await _ritual_ph_show(cq, {**state, 'idx': int(state.get('idx') or 0) + step})


@dp.callback_query(F.data == 'ritual_ph:set')
async def ritual_ph_set(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        await cq.answer()
        return
    state = _ritual_ph_state(cq)
    if not state:
        await cq.answer('выбор фото закрылся — открой его заново под превью', show_alert=True)
        return
    from services import evening_voice as _ev
    from services import scheduler_service as _ss
    cands = await asyncio.to_thread(_ev.owner_candidates, state['character_id'])
    if not cands:
        await cq.answer('нечего закреплять', show_alert=True)
        return
    cand = cands[int(state.get('idx') or 0) % len(cands)]
    day = _ss.ritual_day()
    await asyncio.to_thread(_ev.set_choice, state['kind'], day, state['character_id'],
                            cand['source'], cand['ref'])
    _ss.invalidate_ritual_bundles(state['kind'], day, state['character_id'])
    label = 'утреннее' if state['kind'] == 'morning' else 'вечернее'
    await cq.answer('закрепил')
    await _ritual_ph_show(cq, state, note=(
        f'✅ Под {label} голосовое для «{_ritual_ph_name(state["character_id"])}» сегодня уйдёт этот кадр — '
        'жми «✅ Отправить всем».'))


@dp.callback_query(F.data == 'ritual_ph:auto')
async def ritual_ph_auto(cq: types.CallbackQuery):
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        await cq.answer()
        return
    state = _ritual_ph_state(cq)
    if not state:
        await cq.answer('выбор фото закрылся — открой его заново под превью', show_alert=True)
        return
    from services import evening_voice as _ev
    from services import scheduler_service as _ss
    day = _ss.ritual_day()
    await asyncio.to_thread(_ev.set_choice, state['kind'], day, state['character_id'], None, None)
    _ss.invalidate_ritual_bundles(state['kind'], day, state['character_id'])
    await cq.answer('вернул авто-подбор')
    await _ritual_ph_show(cq, state, note='🔄 Авто-подбор: кадр каждый раз выбирает ротация.')


# V3.108.1: owner — «2 записи и всё»: one Russian and one English recording in
# the voice of the girl he tested with, the same file to every user.
_voice_cast_cache: dict = {}
_voice_cast_char = ''


async def _voice_cast_audio(cache: dict, character_id: str, lang: str) -> bytes | None:
    from services import evening_voice
    key = lang
    if key not in cache:
        try:
            cache[key] = await synthesize_bytes(evening_voice.CAST_LINES[lang], None,
                                                character_id=character_id, mood='evening')
        except Exception:
            logger.exception('voice cast synth failed character=%s lang=%s', character_id, lang)
            cache[key] = None
    return cache[key]


@dp.message(Command('voicecast'))
async def admin_voicecast_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return
    from services import evening_voice
    global _voice_cast_char
    char_id = get_user_character(message.from_user.id) or CHARACTER_ID
    _voice_cast_char = char_id
    _voice_cast_cache.clear()
    await message.answer('🎙 Записываю пробные голосовые: русское и английское…')
    # Owner: both versions come to the admin first, so he hears exactly what
    # everyone gets. These two files are the whole cast.
    for _lang in ('ru', 'en'):
        audio = await _voice_cast_audio(_voice_cast_cache, char_id, _lang)
        if not audio:
            await message.answer(f'⚠️ Голос ({_lang}) не сгенерировался, смотри логи (tts).')
            return
        await bot.send_voice(message.chat.id, BufferedInputFile(audio, filename=f'voice_{_lang}.ogg'),
                             caption=('🇷🇺 ' if _lang == 'ru' else '🇬🇧 ') + evening_voice.CAST_LINES[_lang])
    rows = await asyncio.to_thread(evening_voice.cast_recipients)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f'📣 Отправить всем ({len(rows)} чел.)', callback_data='vcast:go')]])
    await message.answer(
        f'Это пробники, так услышат все: русская и английская запись этим голосом, '
        f'русским по-русски, остальным по-английски. Получатели: включены её сообщения и заходили за '
        f'{evening_voice.CAST_ACTIVE_DAYS} дн. Отправить?', reply_markup=kb)


@dp.callback_query(F.data == 'vcast:go')
async def admin_voicecast_go(cq: types.CallbackQuery):
    global _voice_cast_running
    if cq.from_user.id not in ADMIN_TELEGRAM_IDS:
        await cq.answer()
        return
    if _voice_cast_running:
        await cq.answer('Уже отправляется', show_alert=True)
        return
    _voice_cast_running = True
    await cq.answer('Отправляю…')
    try:
        await cq.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    from aiogram.exceptions import TelegramForbiddenError
    from services import evening_voice
    from services.memory_service import save_message
    sent = failed = blocked = 0
    cache = _voice_cast_cache
    cast_char = _voice_cast_char or CHARACTER_ID
    try:
        rows = await asyncio.to_thread(evening_voice.cast_recipients)
        for uid, tid, char, lang in rows:
            char_id = char or CHARACTER_ID
            audio = await _voice_cast_audio(cache, cast_char, lang)
            if not audio:
                failed += 1
                continue
            try:
                await bot.send_voice(tid, BufferedInputFile(audio, filename='voice.ogg'),
                                     caption=evening_voice.CAST_LINES[lang])
                sent += 1
                await asyncio.to_thread(save_message, uid, char_id, 'assistant', evening_voice.CAST_LINES[lang])
                await asyncio.to_thread(track_event, uid, 'voice_cast_sent', character_id=char_id)
            except TelegramForbiddenError:
                blocked += 1
            except Exception as exc:
                failed += 1
                logger.warning('voice cast to %s failed: %s', tid, exc)
            await asyncio.sleep(0.07)  # stay under Telegram's ~30 msg/s
    finally:
        _voice_cast_running = False
    await cq.message.answer(f'📣 Голосовое разослано: {sent} доставлено, {blocked} заблокировали бота, '
                            f'{failed} ошибок.')


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
        f'Funnel 30d: /start {snap["funnel"]["started"]} → 18+ {snap["funnel"]["consent"]} → first msg {snap["funnel"]["first_message"]}\n'
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
                    [InlineKeyboardButton(text='🍑 Персики…', callback_data=f'admin:grantdo:peaches:{target}')],
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
        # V3.44.2: peaches (photo credits) grant step
        if step == 'peaches':
            if not value.isdigit() or int(value) < 1:
                await message.answer(f'Пришли количество персиков числом, например 1000 (одно фото в чате — {CHAT_PHOTO_PEACH_COST}).\n\n/cancel — отменить')
                return
            count = int(value)
            target = int(grant_sess['target'])
            _admin_grant_sessions.pop(message.from_user.id, None)
            ensure_user(target)
            balance = add_peaches(target, count)
            try:
                await bot.send_message(target, f'🍑 Персики зачислены! Баланс: {balance} 🍑')
            except Exception:
                pass
            await message.answer(
                f'✅ Выдано {count} персиков пользователю id {target}. Баланс: {balance} 🍑',
                reply_markup=admin_keyboard(),
            )
            return

    # V3.55.5: «🎟 Промокоды» create wizard — code → peaches → max activations
    # → TTL hours → source tag. PROMO_MAX_CREDITS caps the nominal so a code
    # can never hand out Premium-day value on the peach rail.
    promo_sess = _admin_promo_sessions.get(message.from_user.id)
    if message.from_user.id in ADMIN_TELEGRAM_IDS and promo_sess:
        from services import gift_service
        from config import PROMO_MAX_CREDITS
        value = (message.text or '').strip()
        step = promo_sess.get('step')
        if step == 'code':
            code = value.upper()
            if not gift_service.PROMO_CODE_RE.match(code):
                await message.answer('Код — это 4–24 символа A–Z/0–9 без пробелов.\n\nПопробуй ещё раз или /cancel')
                return
            from models.app_models import PromoCode
            with SessionLocal() as s:
                if s.scalar(select(PromoCode).where(PromoCode.code == code)):
                    await message.answer(f'Код {code} уже есть в базе.\n\nПришли другой или /cancel')
                    return
            promo_sess['code'] = code
            promo_sess['step'] = 'credits'
            await message.answer(
                f'Код {code} ✔\nСколько персиков выдать? Число от 1 до {PROMO_MAX_CREDITS}.\n\n/cancel — отменить')
            return
        if step == 'credits':
            if not value.isdigit() or not (1 <= int(value) <= PROMO_MAX_CREDITS):
                await message.answer(f'Пришли целое число от 1 до {PROMO_MAX_CREDITS}.\n\n/cancel — отменить')
                return
            promo_sess['credits'] = int(value)
            promo_sess['step'] = 'max'
            await message.answer('Максимум активаций (общее число юзеров)? Например 500.\n0 — без лимита.\n\n/cancel — отменить')
            return
        if step == 'max':
            if not value.isdigit():
                await message.answer('Пришли число. 0 — без лимита.\n\n/cancel — отменить')
                return
            promo_sess['max_activations'] = int(value)
            promo_sess['step'] = 'ttl'
            await message.answer('Через сколько часов сгорает код? Например 48.\n0 — бессрочный.\n\n/cancel — отменить')
            return
        if step == 'ttl':
            if not value.isdigit():
                await message.answer('Пришли число часов. 0 — бессрочный.\n\n/cancel — отменить')
                return
            promo_sess['expires_in_hours'] = int(value)
            promo_sess['step'] = 'src'
            await message.answer(
                'Тег источника для аналитики (например kol_tg, event_0312)? '
                'Одно слово или «нет» — и создам код.'
            )
            return
        if step == 'src':
            from datetime import datetime as _dt, timedelta as _td, timezone as _tz
            from models.app_models import PromoCode
            src = value.replace(' ', '_')[:48]
            if src.lower() in {'нет', 'no', '-'}:
                src = ''
            hours = int(promo_sess.get('expires_in_hours') or 0)
            expires_at = None if hours <= 0 else _dt.now(_tz.utc).replace(tzinfo=None) + _td(hours=hours)
            with SessionLocal() as s:
                s.add(PromoCode(
                    code=promo_sess['code'],
                    credits=int(promo_sess['credits']),
                    max_activations=int(promo_sess.get('max_activations') or 0),
                    expires_at=expires_at,
                    source_tag=src or None,
                    active=True,
                ))
                s.commit()
            cap = '∞' if not promo_sess.get('max_activations') else promo_sess['max_activations']
            ttl = 'бессрочный' if hours <= 0 else f'{hours} ч'
            _admin_promo_sessions.pop(message.from_user.id, None)
            await message.answer(
                f'✅ Код {promo_sess["code"]} создан: +{promo_sess["credits"]} 🍑, '
                f'активаций до {cap}, {ttl}'
                + (f', источник {src}' if src else ''),
                reply_markup=_promo_admin_keyboard(),
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
        # V3.64.6: owner's call — a look-alike from a real uploaded photo is
        # admin-only; everyone else goes straight to the confirm card.
        if message.from_user.id in ADMIN_TELEGRAM_IDS:
            await _constructor_face_step(message.chat.id, message.from_user.id)
        else:
            await _constructor_confirm(message.chat.id, message.from_user.id)
        return
    # V3.44.5: photo reference step — user uploads a photo of who she should look like.
    if constructor_name_session and constructor_name_session.get('await', '').startswith('photo_'):
        field = constructor_name_session['await'][6:]  # Remove 'photo_' prefix
        # Get the photo file_id from the message (largest size).
        if message.photo:
            photo = message.photo[-1]  # Largest size
            constructor_name_session['params'][field] = photo.file_id
            constructor_name_session['await'] = None
            constructor_name_session['step'] += 1
            # Continue to next step.
            if constructor_name_session['step'] < len(CONSTRUCTOR_STEPS):
                next_key = CONSTRUCTOR_STEPS[constructor_name_session['step']]['key']
                next_step = CONSTRUCTOR_STEPS[constructor_name_session['step']]
                if next_step.get('free_text'):
                    constructor_name_session['await'] = f'text_{next_key}'
                    await message.answer(f'🎨 {next_step["title"]}\n\nНапиши текст одним сообщением или отправь /skip чтобы пропустить.')
                elif next_step.get('photo_upload'):
                    constructor_name_session['await'] = f'photo_{next_key}'
                    await message.answer(f' {next_step["title"]}\n\nПришли фото одним сообщением или отправь /skip чтобы пропустить.')
                else:
                    await message.answer(_constructor_prompt(next_key), reply_markup=_constructor_step_keyboard(next_key))
            else:
                # All steps done — ask for name.
                constructor_name_session['await'] = 'name'
                await message.answer('Шаг: как её зовут? Напиши имя одним сообщением (до 24 символов).')
        elif (message.text or '').strip().lower() == '/skip':
            constructor_name_session['params'][field] = ''
            constructor_name_session['await'] = None
            constructor_name_session['step'] += 1
            if constructor_name_session['step'] < len(CONSTRUCTOR_STEPS):
                next_key = CONSTRUCTOR_STEPS[constructor_name_session['step']]['key']
                next_step = CONSTRUCTOR_STEPS[constructor_name_session['step']]
                if next_step.get('free_text'):
                    constructor_name_session['await'] = f'text_{next_key}'
                    await message.answer(f'🎨 {next_step["title"]}\n\nНапиши текст одним сообщением или отправь /skip чтобы пропустить.')
                else:
                    await message.answer(_constructor_prompt(next_key), reply_markup=_constructor_step_keyboard(next_key))
            else:
                constructor_name_session['await'] = 'name'
                await message.answer('Шаг: как её зовут? Напиши имя одним сообщением (до 24 символов).')
        else:
            await message.answer('📷 Пришли фото одним сообщением или отправь /skip чтобы пропустить.')
        return
    # V3.44.4: free text steps for backstory and personality.
    if constructor_name_session and constructor_name_session.get('await', '').startswith('text_'):
        field = constructor_name_session['await'][5:]  # Remove 'text_' prefix
        text_value = (message.text or '').strip()
        if text_value.lower() == '/skip':
            constructor_name_session['params'][field] = ''
        else:
            constructor_name_session['params'][field] = text_value
        constructor_name_session['await'] = None
        constructor_name_session['step'] += 1
        # Continue to next step.
        if constructor_name_session['step'] < len(CONSTRUCTOR_STEPS):
            next_key = CONSTRUCTOR_STEPS[constructor_name_session['step']]['key']
            next_step = CONSTRUCTOR_STEPS[constructor_name_session['step']]
            if next_step.get('free_text'):
                constructor_name_session['await'] = f'text_{next_key}'
                await message.answer(f'🎨 {next_step["title"]}\n\nНапиши текст одним сообщением или отправь /skip чтобы пропустить.')
            else:
                await message.answer(_constructor_prompt(next_key), reply_markup=_constructor_step_keyboard(next_key))
        else:
            # All steps done — ask for name.
            constructor_name_session['await'] = 'name'
            await message.answer('Шаг: как её зовут? Напиши имя одним сообщением (до 24 символов).')
        return
    try:
        from services.gamification_service import touch_activity, check_first_message
        gam = touch_activity(message.from_user.id)
        check_first_message(message.from_user.id)
        # V3.80.0: the friend's 10th real message pays both sides of a referral.
        asyncio.create_task(_referral_qualify_check(message.from_user.id, message.text or ''))
        if gam and gam.get('streak_reward_credits'):
            await message.answer(
                f'🔥 {gam["streak_count"]} дней подряд! подарил {gam["streak_reward_credits"]} фото-кредитов за постоянство. '
                'Заходи завтра — серию нельзя прерывать 😊'
            )
        elif gam and gam.get('new_streak_day') and int(gam.get('streak_count') or 0) >= 2:
            # V3.44.16: streaks used to be invisible until the 3-day reward —
            # a day-2+ user never learned the series exists. Keep it one line.
            await message.answer(
                f'🔥 {gam["streak_count"]} дней подряд! приходи завтра — не прерывай серию 😊'
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
        direct_undress = _direct_undress_request(text)
        if not request:
            request = _show_me_request(text) or direct_undress
        if request:
            await handle_photo_request(message.chat.id, message.from_user.id, request,
                                       undress_credit=direct_undress is not None, text=text)
            touch_user(message.from_user.id)
            return
        # V3.45.27: «чат только в Mini App». A plain conversational message in
        # the bot no longer calls the LLM — we surface the menu and point to the
        # app. Photo requests / photo-offer acceptance / constructor / admin
        # card-edit flows all `return` earlier, so only pure small talk reaches
        # here. If PUBLIC_BASE_URL is missing we fall through to classic chat so
        # the bot never dead-ends.
        if BOT_CHAT_REDIRECT and PUBLIC_BASE_URL:
            _lang = user_lang(message.from_user.id)
            # V3.63.2: the hint is a screen — it replaces the previous hint
            # instead of stacking one per message, and it carries the button
            # that opens her chat right away (the old version re-sent the
            # reply keyboard and made the user hunt for «Открыть приложение»).
            _who = _character_display_name(get_user_character(message.from_user.id))
            _hint = (f'💬 {_who} ждёт тебя в приложении — там она отвечает и всё помнит 👇'
                     if _lang != EN else
                     f'💬 {_who} is waiting for you in the app — that is where she answers and remembers everything 👇')
            _btn = ('💬 ответить ей' if _lang != EN else '💬 reply to her')
            _token = await chat_hygiene.open_screen(bot, message.chat.id)
            try:
                await message.answer(_hint, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                    text=_btn, web_app=types.WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp?open=chat'))]]))
            finally:
                chat_hygiene.close_screen(_token)
            track_event(uid, 'bot_chat_redirected')
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
        # V3.90.0: intimacy is Premium-only — once a day his explicit message
        # gets a Premium button under her reply.
        try:
            from services import intimacy_gate
            if await asyncio.to_thread(intimacy_gate.should_offer, message.from_user.id,
                                       get_user_character(message.from_user.id), text):
                track_event(ensure_user(message.from_user.id), 'paywall_view', metadata={'product': 'sext_offer'})
                await message.answer(intimacy_gate.OFFER_TEXT_RU,
                                     reply_markup=premium_keyboard(telegram_id=message.from_user.id))
        except Exception:
            logger.warning('sext offer failed user=%s', message.from_user.id, exc_info=True)
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
        await _maybe_set_alarm(message, text, 'и время тоже запомнила 😌 пояс: {tz}')
        touch_user(message.from_user.id)
    except Exception as exc:
        logger.exception('chat handler user=%s error=%s', message.from_user.id, type(exc).__name__)
        err_msg = str(exc)[:200] if exc else 'unknown'
        await message.answer(f'я сейчас немного зависла 😅 попробуй ещё раз\n\n💡 если повторяется — напиши /support')


# ---------------------------------------------------------------------------
# V3.44.21: public web endpoints for Platega card/SBP payments. Railway
# injects PORT; the public domain is configured via PUBLIC_BASE_URL and the
# callback URL is pasted into the Platega cabinet (Настройки → Callback URL).
# ---------------------------------------------------------------------------

async def _platega_callback(request: web.Request) -> web.Response:
    """Platega status callback: POST JSON + X-MerchantId/X-Secret headers.

    The headers ARE the docs' auth model (there is no payload signature),
    so a callback that fails the check is rejected with 401. On CONFIRMED
    the transaction is re-verified via GET /transaction/{id} and the paid
    amount is checked against the order before anything is granted;
    CANCELED / CHARGEBACKED only update the order row. Respond 200 OK so
    the provider stops retrying (it retries 3× every 5 minutes otherwise).
    """
    if not platega_service.verify_callback_headers(request.headers):
        logger.warning('Platega callback rejected (bad X-MerchantId/X-Secret) peer=%s',
                       request.headers.get('X-Real-IP') or request.remote)
        return web.Response(text='NO|auth', status=401)
    try:
        body = await request.json()
    except Exception:
        return web.Response(text='NO|json', status=400)
    body = body or {}
    from services import autopay
    if autopay.is_subscription_callback(body):
        # V3.120.0: an SBP auto-renewal debit or a subscription status change.
        try:
            await _autopay_platega_callback(body)
        except Exception:
            logger.exception('Platega subscription callback failed body=%s', str(body)[:300])
        return web.Response(text='OK')
    status = str(body.get('status') or '').strip().upper()
    transaction_id = str(body.get('id') or '').strip()
    payload = str(body.get('payload') or '')
    order = platega_service.find_order(transaction_id, payload)
    if order is None:
        # Unknown transaction (e.g. a /platega/check probe) — nothing to do.
        logger.info('Platega callback for unknown transaction=%s', transaction_id or '-')
        return web.Response(text='OK')
    if status == platega_service.STATUS_CONFIRMED:
        # Defense in depth: re-check the transaction at the provider before
        # granting. If the status API is unreachable the headers stay the
        # documented contract — grant with a warning in the log.
        remote = await platega_service.get_transaction(transaction_id)
        if remote is not None and str(remote.get('status') or '').upper() != platega_service.STATUS_CONFIRMED:
            logger.warning('Platega callback/status mismatch order=%s transaction=%s callback=%s remote=%s',
                           order['id'], transaction_id, status, remote.get('status'))
            return web.Response(text='OK')
        if not platega_service.amount_covers(body.get('amount'), order['amount']):
            logger.error('Platega callback amount mismatch order=%s expected=%s paid=%s',
                         order['id'], order['amount'], body.get('amount'))
            return web.Response(text='OK')
        if platega_service.mark_paid(order['id'], json.dumps(body, ensure_ascii=False)):
            product = order['product']
            if product.startswith('donation_'):
                # V3.52.1: «Поддержать проект» donation — nothing to grant, the
                # thank-you IS the product (ledger row below still lands via
                # record_payment, partner commission included). This must NOT
                # fall through to the premium `else` at the end of the chain —
                # it used to tell a 50₽ donor «Premium активирован на 30 дней».
                # The next branch is an `elif` now, so the whole thing is a single
                # if/elif/else chain and a donation never reaches the default.
                confirm = '💜 Оплата прошла! Спасибо за поддержку — очень ценно, что ты остаёшься с нами 🥰'
            elif product == 'constructor_rub':
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
            elif product == 'undress_one':
                # V3.132.0: one «Раздеть» paid by card/SBP — record_payment below grants it.
                confirm = '🔥 Оплата прошла! Одно «Раздеть» твоё — сейчас сделаю фото.'
            elif product == 'premium_trial':
                # V3.88.0: ruble-paid first-purchase trial.
                confirm = f'💖 Оплата прошла! Premium включён на {PREMIUM_TRIAL_DAYS} дня — тебе открыто всё 🔥'
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
            elif product.startswith('peach_custom_'):
                # V3.44.23: custom peach amount paid via card/SBP.
                try:
                    _cn = max(1, int(product.split('_')[-1]))
                except (ValueError, IndexError):
                    _cn = 1
                confirm = f'🍑 {_cn * PEACH_CUSTOM_UNIT} персиков оплачены! Уже начислены 📸'
            else:
                confirm = '💖 Оплата прошла! Premium активирован на 30 дней. Наслаждайся! 🎉'
            try:
                record_payment(
                    order['telegram_id'], order['product'], 0,
                    f'platega:{order["id"]}', provider='platega',
                    provider_payload=f'amount={order["amount"]}',
                )
                track_event(ensure_user(order['telegram_id']), 'platega_paid',
                            metadata={'product': order['product'], 'amount': str(order['amount'])})
                if product in PAID_PREMIUM_PRODUCTS:
                    # V3.104.0: the card follows the confirmation below.
                    _spawn_background(_after_premium_paid(int(order['telegram_id']), product))
            except Exception:
                logger.exception('Platega grant failed order=%s', order['id'])
            try:
                await bot.send_message(order['telegram_id'], confirm)
            except Exception:
                logger.exception('Platega confirmation message failed order=%s', order['id'])
            if product == 'undress_one':
                pending = _pending_undress_photo.pop(int(order['telegram_id']), None)
                if pending:
                    try:
                        await handle_photo_request(int(order['telegram_id']), int(order['telegram_id']),
                                                   pending, undress_credit=True)
                    except Exception:
                        logger.exception('Platega undress auto-photo failed order=%s', order['id'])
    elif status in (platega_service.STATUS_CANCELED, platega_service.STATUS_CHARGEBACKED):
        new_status = 'chargedback' if status == platega_service.STATUS_CHARGEBACKED else 'canceled'
        if platega_service.mark_canceled(order['id'], json.dumps(body, ensure_ascii=False), new_status):
            logger.warning('Platega order %s -> %s transaction=%s', order['id'], new_status, transaction_id)
    else:
        logger.warning('Platega callback unknown status=%s order=%s', status, order['id'])
    # docs: answer 200 OK on everything processed (or ignored on purpose).
    return web.Response(text='OK')


async def _platega_success(request: web.Request) -> web.Response:
    # V3.52.1: this page is shared by every product (premium, peaches, donation
    # …), so it must not claim «Premium уже включён» — a donor saw that and
    # thought a 50₽ gift bought a subscription. Neutral wording + the real grant
    # always arrives as the bot message on /platega/callback.
    return web.Response(
        text='✅ Оплата прошла! Возвращайся в бот — всё уже учтено 💫',
        content_type='text/html',
    )


async def _platega_fail(request: web.Request) -> web.Response:
    return web.Response(
        text='Оплата не завершена. Попробуй ещё раз или оплати Stars прямо в боте ⭐',
        content_type='text/html',
    )


async def _healthz(request: web.Request) -> web.Response:
    return web.Response(text='ok')


def _owner_diagnostics_allowed(request: web.Request) -> bool:
    """V3.58.0: /diagnostics and /platega/check are owner-only. Either the
    ``?key=`` query matches DIAGNOSTICS_KEY, or the request carries a valid
    Mini App ``init_data`` of an admin. Without both the routes answer 404 —
    /platega/check creates a real Platega transaction on every hit, so it
    must never be reachable by strangers."""
    from config import DIAGNOSTICS_KEY
    key = (request.query.get('key') or '').strip()
    if DIAGNOSTICS_KEY and key and secrets.compare_digest(key, DIAGNOSTICS_KEY):
        return True
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if pairs:
        telegram_id = webapp_service.init_data_user(pairs).get('id')
        if telegram_id and webapp_service._is_admin(telegram_id):
            return True
    return False


async def _diagnostics(request: web.Request) -> web.Response:
    """V3.44.4: diagnostics endpoint for the owner — shows photo provider status."""
    if not _owner_diagnostics_allowed(request):
        return web.Response(status=404)
    from config import (
        FAL_KEY, GEMINI_API_KEY_VALID, OPENAI_API_KEY,
        GEMINI_IMAGE_ENABLED, PHOTO_ROUTER_MODE,
        TELEGRAM_TOKEN, BOT_USERNAME,
    )
    return web.json_response({
        'bot_token_set': bool(TELEGRAM_TOKEN),
        'bot_username': BOT_USERNAME or '-',
        'fal_key_set': bool(FAL_KEY),
        'gemini_key_valid': bool(GEMINI_API_KEY_VALID),
        'openai_key_set': bool(OPENAI_API_KEY),
        'gemini_image_enabled': bool(GEMINI_IMAGE_ENABLED),
        'photo_router_mode': PHOTO_ROUTER_MODE,
        'providers': {
            'seedream': bool(FAL_KEY),
            'gemini_image': bool(GEMINI_IMAGE_ENABLED),
            'openai': bool(OPENAI_API_KEY),
        },
    })


async def _platega_check(request: web.Request) -> web.Response:
    """V3.44.21: live Platega diagnostics for the owner («страница платежа
    не загружается»). Probes every piece of the payment path and prints a
    plain-text report: env flags, a real API test transaction (returns the
    payment-page link) and the GET /transaction/{id} status echo for it —
    the same three calls the production payment flow makes."""
    if not _owner_diagnostics_allowed(request):
        return web.Response(status=404)
    lines = [
        f'VERSION={VERSION}',
        f'PLATEGA_ENABLED={PLATEGA_ENABLED} merchant={PLATEGA_MERCHANT_ID or "-"}',
        f'PLATEGA_API_KEY={"set" if PLATEGA_API_KEY else "MISSING"}',
        f'PLATEGA_API_BASE={PLATEGA_API_BASE}',
        f'PUBLIC_BASE_URL={PUBLIC_BASE_URL or "-"}',
    ]
    if PLATEGA_ENABLED:
        order_id = platega_service.create_order(0, 'plategacheck', '10')
        url = await platega_service.create_payment(order_id, '10')
        lines.append(f'api_test_order={order_id}')
        lines.append(f'payment_url={url or "API REJECTED ORDER (see bot logs)"}')
        if url:
            lines.append(f'payment_url_domain={url.split("/")[2]}')
        order = platega_service.get_order(order_id)
        transaction_id = (order or {}).get('transaction_id')
        if transaction_id:
            tx = await platega_service.get_transaction(transaction_id)
            lines.append(f'status_check={str(tx)[:500]}')
        else:
            lines.append('status_check=SKIPPED (no transaction id stored)')
    else:
        lines.append('api_test_order=SKIPPED (need PLATEGA_MERCHANT_ID + PLATEGA_API_KEY)')
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
    # V3.19.10: the bare Railway domain used to show aiohttp's 404.
    # V3.126.0: it is now the search landing (services/seo_landing.py) so
    # Yandex/Google can rank «ии девушка» pages; liveness stays on /healthz.
    return await _seo_page(request)


async def _seo_page(request: web.Request) -> web.Response:
    page = seo_landing.PAGES_BY_PATH.get(request.path.rstrip('/') or '/')
    if page is None:
        raise web.HTTPNotFound()
    from config import BOT_USERNAME
    body = seo_landing.render_page(page, bot_username=BOT_USERNAME or 'Anna67901_bot',
                                   base_url=PUBLIC_BASE_URL)
    return web.Response(text=body, content_type='text/html', charset='utf-8',
                        headers={'Cache-Control': 'public, max-age=3600'})


async def _seo_robots(request: web.Request) -> web.Response:
    return web.Response(text=seo_landing.robots_txt(PUBLIC_BASE_URL), content_type='text/plain')


async def _seo_sitemap(request: web.Request) -> web.Response:
    return web.Response(text=seo_landing.sitemap_xml(PUBLIC_BASE_URL), content_type='application/xml')


async def _seo_banner(request: web.Request) -> web.StreamResponse:
    if not WELCOME_BANNER_PATH.exists():
        raise web.HTTPNotFound()
    return web.FileResponse(WELCOME_BANNER_PATH, headers={'Cache-Control': 'public, max-age=86400'})


# ---------------------------------------------------------------------------
# V3.33.0: Telegram Mini App (WebApp) — the storefront served by the same
# aiohttp app Railway already runs. /webapp is the page; /webapp/api/* are its
# JSON endpoints; /webapp/photo/<id> serves canonical character portraits.
# ---------------------------------------------------------------------------

_WEBAPP_PAGE_CACHE: dict = {}

async def _webapp_index(request: web.Request) -> web.Response:
    # V3.56.6: the SPA is one 280KB+ file and every open used to re-download it
    # uncompressed (FileResponse never gzips, never 304s) — the owner's «сама
    # загрузка мини приложения долго». Now: bytes cached in memory, gzip once,
    # ETag revalidation so a repeat open costs 304-not-Moved, not 280KB.
    index = webapp_service.WEBAPP_INDEX
    if not index.exists():
        return web.Response(text='webapp is not deployed', status=500)
    import gzip as _gzip
    import hashlib as _hashlib
    stat = index.stat()
    cached = _WEBAPP_PAGE_CACHE.get('page')
    if cached is None or cached[0] != stat.st_mtime or cached[1] != stat.st_size:
        raw = index.read_bytes()
        cached = (stat.st_mtime, stat.st_size, raw, _gzip.compress(raw, 6),
                  '"' + _hashlib.sha1(raw).hexdigest()[:16] + '"')
        _WEBAPP_PAGE_CACHE['page'] = cached
    _mtime, _size, raw, gz, etag = cached
    base_headers = {'ETag': etag, 'Cache-Control': 'no-cache', 'Vary': 'Accept-Encoding'}
    if request.headers.get('If-None-Match') == etag:
        return web.Response(status=304, headers=base_headers)
    if 'gzip' in (request.headers.get('Accept-Encoding') or ''):
        return web.Response(body=gz, content_type='text/html',
                            headers={**base_headers, 'Content-Encoding': 'gzip'})
    return web.Response(body=raw, content_type='text/html', headers=base_headers)


@web.middleware
async def _webapp_gzip(request: web.Request, handler) -> web.StreamResponse:
    # V3.56.6: compress JSON/text API payloads (characters, chats, history —
    # tens of KB each) for the app. Small bodies and already-encoded responses
    # pass through untouched; FileResponse/photo bytes are skipped (content type).
    response = await handler(request)
    try:
        if not isinstance(response, web.Response) or response.status != 200:
            return response
        ctype = response.content_type or ''
        if not (ctype.startswith('application/json') or ctype.startswith('text/')):
            return response
        if response.headers.get('Content-Encoding'):
            return response
        if 'gzip' not in (request.headers.get('Accept-Encoding') or ''):
            return response
        payload = response.body
        if payload is None or len(payload) < 1024:
            return response
        import gzip as _gzip
        compressed = _gzip.compress(payload, 5)
        if len(compressed) >= len(payload):
            return response
        headers = dict(response.headers)
        headers.pop('Content-Length', None)
        headers['Content-Encoding'] = 'gzip'
        headers['Vary'] = 'Accept-Encoding'
        return web.Response(status=response.status, body=compressed, headers=headers)
    except Exception:
        logger.warning('gzip middleware failed for %s', request.path, exc_info=True)
        return response


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
    # V3.57.2: the boot call — ensure_user may INSERT and api_me reads several
    # tables; off the loop so one user's cold start never stalls the others.
    browser_tz = (request.query.get('tz') or '').strip()[:64]

    def _boot():
        uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
        # V3.59.8: the phone's real time zone (the language guess put everyone
        # on Moscow) — photos and greetings follow the user's own clock.
        if browser_tz:
            try:
                from zoneinfo import ZoneInfo
                ZoneInfo(browser_tz)
                from services.user_service import get_user as _gu, update_user_settings as _uus
                u = _gu(telegram_id)
                if u is not None and u.timezone != browser_tz:
                    _uus(telegram_id, timezone=browser_tz)
            except Exception:
                pass
        from models.app_models import ProductEvent
        with SessionLocal() as s:
            first_open = not s.scalar(select(ProductEvent.id).where(
                ProductEvent.user_id == uid,
                ProductEvent.event_name == 'webapp_opened',
            ).limit(1))
        track_event(uid, 'webapp_opened')
        me = webapp_service.api_me(telegram_id)
        from services.consent_service import has_accepted
        me['first_webapp_open'] = bool(first_open and has_accepted(telegram_id))
        return me

    me = await asyncio.to_thread(_boot)
    # V3.47.0: the viral invite link (src_share attribution + credits this user
    # as referrer) rides along so the share / post-gen CTA works anywhere.
    try:
        _me_bot = await bot.get_me()
        me['invite'] = share_link(_me_bot.username or 'bot', telegram_id)
    except Exception:
        logger.exception('invite link resolution failed user=%s', telegram_id)
    # V3.107.0: «Без сюрпризов» — live numbers for the one-time honest card.
    try:
        from services import honest_card
        me['honest'] = honest_card.facts()
    except Exception:
        logger.exception('honest card facts failed user=%s', telegram_id)
    return web.json_response({'ok': True, 'me': me})


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
    # V3.57.2: the whole SQLAlchemy read runs off the event loop — one slow
    # storefront query must never freeze every other request in the process.
    characters = await asyncio.to_thread(webapp_service.api_characters, telegram_id)
    return web.json_response({'ok': True, 'characters': characters},
                             headers={'Cache-Control': 'no-store'})


async def _webapp_api_leaderboard(request: web.Request) -> web.Response:
    """V3.44.0: popularity leaderboard — top characters by views."""
    limit = min(20, max(3, int(request.query.get('limit', '10') or '10')))
    board = await asyncio.to_thread(webapp_service.character_leaderboard, limit)
    return web.json_response({'ok': True, 'leaderboard': board})


async def _webapp_api_author(request: web.Request) -> web.Response:
    """V3.44.8: public author page — profile + every community character they
    created, so users can browse one author's girls (author revenue funnel)."""
    author_id = str(request.query.get('author_id', '') or '').strip()[:64]
    if not author_id:
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    # V3.57.2: reads the author's whole character list — off the loop.
    return web.json_response(await asyncio.to_thread(webapp_service.api_author, author_id),
                             headers={'Cache-Control': 'no-store'})


async def _webapp_api_creator_cabinet(request: web.Request) -> web.Response:
    """V3.44.11: the creator's cabinet — the caller's characters with views,
    earnings and the витрина publish state."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'no_user'}, status=401)
    return web.json_response(await asyncio.to_thread(webapp_service.api_creator_cabinet, telegram_id),
                             headers={'Cache-Control': 'no-store'})


async def _webapp_api_creator_publish(request: web.Request) -> web.Response:
    """V3.44.11: «на витрину» — put the caller's own character (her generated
    avatar) on the storefront for everyone, or take her back private."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'no_user'}, status=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    character_id = str(body.get('character_id', '') or '').strip()[:64]
    if not character_id:
        return web.json_response({'ok': False, 'error': 'bad_input'}, status=400)
    result = await asyncio.to_thread(
        webapp_service.publish_creator_character, telegram_id, character_id, bool(body.get('publish')))
    # V3.45.28: an app submit-to-витрина now queues her for review — ping the
    # admins with the same approve/reject card the bot constructor path sends.
    if result.get('ok') and result.get('moderation'):
        try:
            row = await asyncio.to_thread(get_custom_character_by_id, character_id)
            if row:
                await _request_character_moderation(
                    character_id, telegram_id, row.display_name, row.avatar_file_id)
        except Exception:
            logger.exception('webapp publish moderation ping failed char=%s', character_id)
    return web.json_response(result)


async def _webapp_api_creator_character(request: web.Request) -> web.Response:
    """V3.45.27: fetch the caller's own character to prefill the edit form."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'no_user'}, status=401)
    character_id = str(request.query.get('character_id', '') or '').strip()[:64]
    return web.json_response(await asyncio.to_thread(webapp_service.api_creator_character, telegram_id, character_id),
                             headers={'Cache-Control': 'no-store'})


async def _webapp_api_creator_edit(request: web.Request) -> web.Response:
    """V3.45.27: the author edits her own character's text fields."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'no_user'}, status=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    character_id = str(body.get('character_id', '') or '').strip()[:64]
    if not character_id:
        return web.json_response({'ok': False, 'error': 'bad_input'}, status=400)
    return web.json_response(await asyncio.to_thread(
        webapp_service.edit_creator_character, telegram_id, character_id,
        name=body.get('name'), bio=body.get('bio'), age=body.get('age')))


async def _webapp_api_creator_delete(request: web.Request) -> web.Response:
    """V3.45.27: the author permanently removes her own character."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'no_user'}, status=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    character_id = str(body.get('character_id', '') or '').strip()[:64]
    if not character_id:
        return web.json_response({'ok': False, 'error': 'bad_input'}, status=400)
    return web.json_response(await asyncio.to_thread(
        webapp_service.delete_creator_character, telegram_id, character_id))


async def _webapp_api_achievements(request: web.Request) -> web.Response:
    """V3.45.27: the unified achievements board for the Mini App."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'no_user'}, status=401)
    return web.json_response(await asyncio.to_thread(webapp_service.api_achievements, telegram_id),
                             headers={'Cache-Control': 'no-store'})


async def _webapp_api_collection(request: web.Request) -> web.Response:
    """V3.53.0: the «Собери галерею» photo-set progress for one character."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'no_user'}, status=401)
    character_id = request.query.get('character_id') or CHARACTER_ID
    payload = await asyncio.to_thread(webapp_service.api_collection, telegram_id, character_id)
    return web.json_response(payload, headers={'Cache-Control': 'no-store'})


async def _webapp_api_missions(request: web.Request) -> web.Response:
    """V3.46.0: the missions funnel roadmap for the Mini App «Миссии» tab."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'no_user'}, status=401)
    return web.json_response(await asyncio.to_thread(webapp_service.api_missions, telegram_id),
                             headers={'Cache-Control': 'no-store'})


async def _webapp_api_missions_claim(request: web.Request) -> web.Response:
    """V3.66.0: «Забрать +N 🍑» on a finished mission in the app."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'no_user'}, status=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    key = str((body or {}).get('key', ''))[:64]
    from services.gamification_service import claim_mission
    result = await asyncio.to_thread(claim_mission, telegram_id, key)
    return web.json_response(result, headers={'Cache-Control': 'no-store'})


async def _webapp_api_gallery(request: web.Request) -> web.Response:
    """V3.45.27: the caller's «Наедине" photo gallery for the Mini App."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'no_user'}, status=401)
    data = await asyncio.to_thread(webapp_service.api_gallery, telegram_id)
    # V3.47.0: attach the sharer's own invite link so the gallery / post-gen CTA
    # and the share sheet carry attribution that credits this user as referrer.
    try:
        me = await bot.get_me()
        data['invite'] = share_link(me.username or 'bot', telegram_id)
    except Exception:
        logger.exception('gallery invite link resolution failed user=%s', telegram_id)
    return web.json_response(data, headers={'Cache-Control': 'no-store'})


async def _webapp_gallery_share(request: web.Request) -> web.Response:
    """V3.47.0: serve the watermarked export copy of a gallery photo to its owner
    only, for viral sharing (the in-app view / paid download stay unwatermarked)."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.Response(status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    if not telegram_id:
        return web.Response(status=401)
    try:
        image_id = int(request.match_info['image_id'])
    except (TypeError, ValueError):
        return web.Response(status=404)
    data = await asyncio.to_thread(webapp_service.share_image_bytes, telegram_id, image_id)
    if not data:
        return web.Response(status=404)
    return web.Response(body=data, content_type='image/jpeg',
                        headers={'Cache-Control': 'private, no-store'})


def _share_sig(telegram_id: int, image_id: int) -> str:
    """V3.61.4: a stable signature for the public share-image URL — Telegram
    itself fetches the photo when the friend's chat receives it."""
    import hashlib
    import hmac
    from config import TELEGRAM_TOKEN
    msg = f'share:{int(telegram_id)}:{int(image_id)}'.encode()
    return hmac.new(TELEGRAM_TOKEN.encode(), msg, hashlib.sha256).hexdigest()[:20]


async def _webapp_shared_image(request: web.Request) -> web.Response:
    """V3.61.4: the watermarked export behind a signed public URL (no init_data:
    Telegram's servers download it for the shared message)."""
    try:
        telegram_id = int(request.match_info['uid'])
        image_id = int(request.match_info['image_id'])
    except (TypeError, ValueError):
        return web.Response(status=404)
    import hmac
    if not hmac.compare_digest(request.match_info.get('sig', ''), _share_sig(telegram_id, image_id)):
        return web.Response(status=404)
    data = await asyncio.to_thread(webapp_service.share_image_bytes, telegram_id, image_id)
    if not data:
        return web.Response(status=404)
    return web.Response(body=data, content_type='image/jpeg', headers={'Cache-Control': 'public, max-age=86400'})


async def _webapp_api_gallery_prepare_share(request: web.Request) -> web.Response:
    """V3.61.4: «Поделиться» used to send the friend a bare invite link. Now the
    bot prepares a real photo message (photo + «хочешь так же?» + a button into
    the bot) and the app hands it to Telegram's own share picker
    (WebApp.shareMessage), so the friend sees the picture itself."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'no_user'}, status=401)
    try:
        body = await request.json()
        image_id = int(body.get('image_id'))
    except Exception:
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    data = await asyncio.to_thread(webapp_service.share_image_bytes, int(telegram_id), image_id)
    if not data or not PUBLIC_BASE_URL:
        return web.json_response({'ok': False, 'error': 'not_found'}, status=404)
    try:
        import uuid
        me = await bot.get_me()
        link = share_link(me.username or 'bot', int(telegram_id))
        url = f'{PUBLIC_BASE_URL}/webapp/shared/{int(telegram_id)}/{image_id}/{_share_sig(int(telegram_id), image_id)}.jpg'
        result = types.InlineQueryResultPhoto(
            id=uuid.uuid4().hex[:32], photo_url=url, thumbnail_url=url,
            caption='\u2764\ufe0f хочешь так же? начни здесь 👇',
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[
                types.InlineKeyboardButton(text='💬 Написать ей', url=link)]]),
        )
        prepared = await bot.save_prepared_inline_message(
            user_id=int(telegram_id), result=result,
            allow_user_chats=True, allow_group_chats=True, allow_channel_chats=True, allow_bot_chats=False,
        )
    except Exception:
        logger.exception('prepare share failed user=%s image=%s', telegram_id, image_id)
        return web.json_response({'ok': False, 'error': 'prepare_failed'}, status=502)
    return web.json_response({'ok': True, 'id': prepared.id})


async def _webapp_gallery_image(request: web.Request) -> web.Response:
    """V3.45.27: serve one private-gallery photo to its owner only."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.Response(status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    if not telegram_id:
        return web.Response(status=401)
    try:
        image_id = int(request.match_info['image_id'])
    except (TypeError, ValueError):
        return web.Response(status=404)
    data = await asyncio.to_thread(webapp_service.gallery_image_bytes, telegram_id, image_id)
    if not data:
        return web.Response(status=404)
    return web.Response(body=data, content_type='image/jpeg',
                        headers={'Cache-Control': 'private, max-age=86400'})


async def _webapp_badge(request: web.Request) -> web.Response:
    """V3.47.1: serve the admin-uploaded art of an achievement. Generic marketing
    art (no personal data), so it is served by key and cacheable."""
    key = (request.match_info.get('key') or '').strip()
    from services.gamification_service import get_badge
    badge = await asyncio.to_thread(get_badge, key)
    if not badge:
        return web.Response(status=404)
    body, ctype = badge
    return web.Response(body=body, content_type=ctype,
                        headers={'Cache-Control': 'public, max-age=3600'})


_LOCKED_CARD_CACHE: dict[str, bytes] = {}


async def _webapp_locked_card(request: web.Request) -> web.Response:
    """V3.88.0: her heavily blurred locked card for the early chat tease — the
    owner's own push photo of this girl when he uploaded one (/storyphoto),
    else her everyday reference. Blurred beyond recognition; cached per girl."""
    character_id = (request.match_info.get('character_id') or '').strip()
    if not re.match(r'^[A-Za-z0-9_\-]{1,64}$', character_id):
        return web.Response(status=404)
    body = _LOCKED_CARD_CACHE.get(character_id)
    if body is None:
        from services import first_offer_service as fos, push_photos
        from services.scheduler_service import _reference_photo
        source = None
        fid = await asyncio.to_thread(push_photos.pick, character_id)
        if fid:
            try:
                source = await bot.download(fid)
            except Exception:
                logger.warning('locked card photo download failed character=%s', character_id)
                source = None
        if source is None:
            source = _reference_photo(character_id)
        try:
            body = await asyncio.to_thread(fos.locked_card, source, 'только для тебя')
        except Exception:
            logger.exception('locked card render failed character=%s', character_id)
            return web.Response(status=404)
        _LOCKED_CARD_CACHE[character_id] = body
    return web.Response(body=body, content_type='image/jpeg',
                        headers={'Cache-Control': 'public, max-age=3600'})


_WEBAPP_ART_DIR = Path(__file__).resolve().parent / 'webapp' / 'art'
_WEBAPP_ART_RE = re.compile(r'^[a-z0-9_]{1,40}\.(jpg|png|webp)$')


async def _webapp_art(request: web.Request) -> web.Response:
    """V3.85.0: static marketing art of the Mini App (the partner tab hero and
    step pictures). Whitelisted file names only — no path traversal."""
    name = request.match_info.get('name') or ''
    if not _WEBAPP_ART_RE.match(name):
        return web.Response(status=404)
    path = _WEBAPP_ART_DIR / name
    if not path.is_file():
        return web.Response(status=404)
    ctype = {'jpg': 'image/jpeg', 'png': 'image/png', 'webp': 'image/webp'}[name.rsplit('.', 1)[1]]
    return web.Response(body=await asyncio.to_thread(path.read_bytes), content_type=ctype,
                        headers={'Cache-Control': 'public, max-age=86400'})


async def _webapp_duo_teaser(request: web.Request) -> web.Response:
    """V3.139.0: owner ТЗ (Задача 5) — the heavily blurred joint picture a man
    without Premium sees when he asks for the two girls together. The provider
    is never called: the owner's own ready blur from webapp/art wins, otherwise
    the two girls' existing photos are composited and blurred here."""
    host_id = (request.match_info.get('host_id') or '').strip()
    guest_id = (request.match_info.get('guest_id') or '').strip()
    if not re.match(r'^[A-Za-z0-9_\-]{1,64}$', host_id) or not re.match(r'^[A-Za-z0-9_\-]{1,64}$', guest_id):
        return web.Response(status=404)
    from services import duo_teaser
    body = await asyncio.to_thread(duo_teaser.render, host_id, guest_id)
    if not body:
        return web.Response(status=404)
    return web.Response(body=body, content_type='image/jpeg',
                        headers={'Cache-Control': 'public, max-age=3600'})


async def _webapp_gallery_save(request: web.Request) -> web.Response:
    """V3.47.1: deliver the watermarked photo into the user's own chat as a real
    image. Telegram Desktop has no web file-share, so this is the reliable
    'share a photo' path — the user forwards the message to a friend."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'no_user'}, status=401)
    try:
        body = await request.json()
        image_id = int(body.get('image_id'))
    except Exception:
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    data = await asyncio.to_thread(webapp_service.share_image_bytes, int(telegram_id), image_id)
    if not data:
        return web.json_response({'ok': False, 'error': 'not_found'}, status=404)
    try:
        me = await bot.get_me()
        caption = f'\u2764\ufe0f\u0445\u043e\u0447\u0435\u0448\u044c \u0442\u0430\u043a \u0436\u0435? \u043d\u0430\u0447\u043d\u0438 \u0437\u0434\u0435\u0441\u044c \u2192 {share_link(me.username or "bot", int(telegram_id))}'
        await bot.send_photo(int(telegram_id), types.BufferedInputFile(data, filename='share.jpg'), caption=caption)
    except Exception:
        logger.exception('gallery save-to-chat failed user=%s', telegram_id)
        return web.json_response({'ok': False, 'error': 'send_failed'}, status=502)
    return web.json_response({'ok': True})


async def _webapp_api_comments(request: web.Request) -> web.Response:
    """V3.44.0: public comments under character cards."""
    character_id = request.query.get('character_id', '')
    if not character_id:
        return web.json_response({'ok': False, 'error': 'no_character'}, status=400)
    limit = min(50, max(5, int(request.query.get('limit', '20') or '20')))
    return web.json_response({'ok': True, 'comments': await asyncio.to_thread(
        webapp_service.get_character_comments, character_id, limit)})


async def _webapp_api_comment_add(request: web.Request) -> web.Response:
    """V3.44.0: add a comment under a character card."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'no_user'}, status=401)
    body = await request.json()
    character_id = str(body.get('character_id', ''))[:64]
    text = str(body.get('text', ''))[:500].strip()
    if not character_id or not text:
        return web.json_response({'ok': False, 'error': 'bad_input'}, status=400)
    comment = await asyncio.to_thread(
        webapp_service.add_character_comment, character_id, telegram_id, text)
    return web.json_response({'ok': True, 'comment': comment})


async def _webapp_api_notif_prefs(request: web.Request) -> web.Response:
    """V3.44.0: get notification preferences."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'no_user'}, status=401)
    return web.json_response({'ok': True, 'prefs': await asyncio.to_thread(
        webapp_service.get_notification_prefs, int(telegram_id))})


async def _webapp_api_notif_update(request: web.Request) -> web.Response:
    """V3.44.0: update notification preferences."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'no_user'}, status=401)
    body = await request.json()
    prefs = await asyncio.to_thread(webapp_service.update_notification_prefs, int(telegram_id), body)
    return web.json_response({'ok': True, 'prefs': prefs})


async def _webapp_api_gift_claim(request: web.Request) -> web.Response:
    """V3.55.5: claim today's streak gift from the Mini App shop — the same
    rail as the bot's gift:claim button (once-per-day, 7th-day jackpot, 15 🍑
    cap without eating the day all live in gift_service). Replaces the V3.44.0
    daily_bonus/spin wheel."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'no_user'}, status=401)
    from services import gift_service
    res = await asyncio.to_thread(gift_service.claim_daily_gift, int(telegram_id))
    status_map = {'auth': 401, 'consent': 403, 'inactive': 403,
                  'capped': 409, 'duplicate': 409}
    if not res.get('ok'):
        status = status_map.get(res.get('error', ''), 409)
        return web.json_response(res, status=status, headers={'Cache-Control': 'no-store'})
    # fresh state so the SPA can repaint the series dots without a second call
    res['state'] = await asyncio.to_thread(gift_service.gift_status, int(telegram_id))
    return web.json_response(res, headers={'Cache-Control': 'no-store'})


GIFT_PROMO_ERROR_HTTP = {'auth': 401, 'consent': 403, 'unknown': 404, 'inactive': 403,
                         'expired': 410, 'exhausted': 429, 'duplicate': 409}


async def _webapp_api_promo(request: web.Request) -> web.Response:
    """V3.55.5: redeem a promo code inside the Mini App shop (one per user per
    code; global activation cap enforced atomically server-side)."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'no_user'}, status=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    from services import gift_service
    res = await asyncio.to_thread(gift_service.redeem_promo, int(telegram_id), str(body.get('code', ''))[:48])
    if not res.get('ok'):
        status = GIFT_PROMO_ERROR_HTTP.get(res.get('error', ''), 404)
        return web.json_response(res, status=status, headers={'Cache-Control': 'no-store'})
    return web.json_response(res, headers={'Cache-Control': 'no-store'})


async def _webapp_api_simulated_messages(request: web.Request) -> web.Response:
    """V3.44.0: get pending simulated messages."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'no_user'}, status=401)
    messages = await asyncio.to_thread(webapp_service.get_pending_simulated_messages, int(telegram_id))
    return web.json_response({'ok': True, 'messages': messages})


async def _webapp_api_simulated_message_deliver(request: web.Request) -> web.Response:
    """V3.44.0: mark a simulated message as delivered."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    body = await request.json()
    message_id = int(body.get('message_id', 0))
    if not message_id:
        return web.json_response({'ok': False, 'error': 'bad_input'}, status=400)
    ok = await asyncio.to_thread(webapp_service.mark_simulated_message_delivered, message_id)
    return web.json_response({'ok': ok})


def _ru_or_en(lang: str | None) -> str:
    """V3.117.0: the server texts exist in RU and EN; a Spanish, Japanese or
    Bengali app got the Russian shop (rubles, SBP first) — any non-Russian
    interface gets the English one with Stars first."""
    return 'ru' if (lang or 'ru').strip().lower().startswith('ru') else 'en'


async def _webapp_api_shop(request: web.Request) -> web.Response:
    # V3.57.2: the catalogue reads prices/settings from PostgreSQL.
    return web.json_response({'ok': True, 'shop': await asyncio.to_thread(
        webapp_service.api_shop, _ru_or_en(request.query.get('lang', 'ru')))})


async def _webapp_api_legal(request: web.Request) -> web.Response:
    # The Platega-required documents, visible in the Mini App as well.
    return web.json_response({'ok': True, 'legal': await asyncio.to_thread(
        webapp_service.api_legal, _ru_or_en(request.query.get('lang', 'ru')))})


async def _webapp_api_lang(request: web.Request) -> web.Response:
    """V3.117.0: he picked an interface language in the app settings — she
    talks to him in it from now on (until he writes in another one), and the
    bot menus follow (Russian for «Русский», English for everything else)."""
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
    from services import lang_guard
    lang = lang_guard.norm_code(str((body or {}).get('lang', '')))
    if not lang:
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)

    def _save():
        uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
        lang_guard.remember(uid, lang)
        with SessionLocal() as session:
            user = session.get(User, uid)
            if user is not None:
                user.ui_lang = _ru_or_en(lang)
                session.commit()
        track_event(uid, 'app_lang_picked', metadata={'lang': lang})

    await asyncio.to_thread(_save)
    return web.json_response({'ok': True, 'lang': lang})


async def _webapp_api_partner(request: web.Request) -> web.Response:
    # V3.37.0: the «Партнёрка» tab — partner stats + the personal link + FAQ.
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    # V3.57.2: partner stats aggregate the referral table — off the loop.
    def _load():
        uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
        return webapp_service.api_partner(uid, telegram_id)

    payload = await asyncio.to_thread(_load)
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
    result = await asyncio.to_thread(partner_service.request_payout, telegram_id)
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
    character_id = request.match_info['character_id']
    if is_custom_character(character_id):
        # V3.44.13: Railway's disk is ephemeral — a redeploy wipes
        # data/custom_references/<id>/avatar.jpg and the storefront/cabinet
        # photo 404s forever. Re-download it from the persisted Telegram
        # file_id on demand (lazy GENERATION stays in the chat flow — this
        # route only heals what Telegram already stores).
        row = await asyncio.to_thread(get_custom_character_by_id, character_id)
        if row and row.avatar_file_id:
            cached = Path(__file__).resolve().parent / 'data' / 'custom_references' / character_id / 'avatar.jpg'
            if not await asyncio.to_thread(cached.exists):
                try:
                    healed = await ensure_custom_avatar_cached(bot, character_id)
                    if healed:
                        webapp_service.invalidate_gallery_cache(character_id)
                except Exception:
                    logger.exception('custom avatar heal failed character=%s', character_id)
    try:
        idx = int(request.query.get('i', '0') or 0)
    except ValueError:
        idx = 0
    photo = await asyncio.to_thread(webapp_service.character_photo, character_id, idx)
    if not photo:
        return web.Response(status=404)
    data, content_type = photo
    # V3.57.9: browser-sized WebP instead of the multi-MB canonical PNG.
    data, content_type = await asyncio.to_thread(
        webapp_service.web_image, data, content_type, f'photo:{character_id}:{idx}')
    return web.Response(body=data, content_type=content_type, headers={'Cache-Control': 'public, max-age=604800'})


async def _webapp_pgal(request: web.Request) -> web.Response:
    # V3.47.4: an admin-set character-page carousel shot — public storefront
    # art from PostgreSQL. The URL carries the row id, so every swap is a new
    # address and the week-long cache never shows a stale slide.
    try:
        shot_id = int(request.match_info['shot_id'])
    except (TypeError, ValueError):
        return web.Response(status=404)
    shot = await asyncio.to_thread(webapp_service.get_page_gallery_shot, shot_id)
    if not shot:
        return web.Response(status=404)
    return web.Response(body=shot[0], content_type=shot[1], headers={'Cache-Control': 'public, max-age=604800'})


async def _webapp_gif(request: web.Request) -> web.Response:
    # V3.40.0: the animated card preview — a public storefront asset with the
    # same caching as the static photo (the grid shows it instead of the JPEG).
    gif = await asyncio.to_thread(webapp_service.character_card_gif, request.match_info['character_id'])
    if not gif:
        return web.Response(status=404)
    content_type = 'image/webp' if gif.suffix.lower() == '.webp' else 'image/gif'
    return web.Response(body=await asyncio.to_thread(gif.read_bytes), content_type=content_type,
                        headers={'Cache-Control': 'public, max-age=604800'})


async def _webapp_live(request: web.Request) -> web.Response:
    # V3.43.1: the i2v living tile — a muted looping mp4 where the heroine
    # smiles and blows an air kiss; the grid plays it instead of the webp.
    live = await asyncio.to_thread(webapp_service.character_card_live, request.match_info['character_id'])
    if not live:
        return web.Response(status=404)
    # V3.57.9: streamed from disk with Range support (206) so the tile starts
    # playing before the whole clip arrives instead of after a 2-3 MB download.
    return web.FileResponse(live, headers={'Content-Type': 'video/mp4',
                        'Cache-Control': 'public, max-age=604800'})


async def _webapp_card(request: web.Request) -> web.Response:
    # V3.43.3: the admin-uploaded storefront media (photo/gif/mp4) — same
    # immutable caching as the other ?v=-stamped assets.
    override = await asyncio.to_thread(webapp_service.character_card_override, request.match_info['character_id'])
    if not override:
        return web.Response(status=404)
    content_type = {'.jpg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp',
                    '.gif': 'image/gif', '.mp4': 'video/mp4'}.get(
        override.suffix.lower(), 'application/octet-stream')
    if content_type in ('video/mp4', 'image/gif'):
        # V3.57.9: videos/GIFs stream from disk with Range support (206).
        return web.FileResponse(override, headers={'Content-Type': content_type,
                            'Cache-Control': 'public, max-age=604800'})
    body = await asyncio.to_thread(override.read_bytes)
    # V3.57.9: still images go out as a browser-sized WebP (GIF/MP4 untouched).
    body, content_type = await asyncio.to_thread(
        webapp_service.web_image, body, content_type, f"card:{request.match_info['character_id']}")
    return web.Response(body=body, content_type=content_type,
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
    # V3.57.2: the view counter used to open its own transaction per page view —
    # the hottest write in the storefront, so the card lookup and the increment
    # both leave the event loop.
    if not await asyncio.to_thread(get_card, character_id):
        return web.json_response({'ok': False, 'error': 'character'}, status=404)
    new_views = await asyncio.to_thread(webapp_service.bump_character_views, character_id)
    # V3.46.0: mission — a custom persona crossing 100 views unlocks her
    # author's «100 просмотров» (scene reward granted inside unlock_achievement).
    if new_views == 100:
        try:
            author = await asyncio.to_thread(get_custom_character_by_id, character_id)
            if author and author.telegram_id:
                await _notify_unlock(int(author.telegram_id), int(author.telegram_id), 'views_100')
        except Exception:
            logger.exception('views_100 unlock failed char=%s', character_id)
    return web.json_response({'ok': True, 'views': new_views})


def _track_channel_bonus(telegram_id: int, event: str, balance: int) -> None:
    """V3.57.2: worker-thread helper — ensure_user + track_event are both writes,
    so the channel-bonus legs call them inside one offloaded function."""
    track_event(ensure_user(telegram_id), event, metadata={'credits': balance})


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
        # V3.57.2: every credits/grant read below is a PostgreSQL round trip.
        granted = bool(telegram_id) and await asyncio.to_thread(
            has_credit_grant, telegram_id, 'channel_subscribe')
        # V3.68.0: a running hold shows «ещё N дн.» in the modal.
        pending = None
        if telegram_id and not granted:
            from services import channel_bonus_service as cbs
            started = await asyncio.to_thread(cbs.hold_started, telegram_id)
            if started:
                pending = cbs.days_left(started)
        return web.json_response({**base, 'granted': granted, 'hold_days': CHANNEL_BONUS_HOLD_DAYS,
                                  'days_left': pending})
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    await asyncio.to_thread(
        ensure_user, telegram_id, user_info.get('first_name') or '',
        language_code=user_info.get('language_code'))
    try:
        member = await bot.get_chat_member(chat_id=f'@{CHANNEL_SUBSCRIBE_USERNAME}', user_id=telegram_id)
        subscribed = member.status in ('member', 'administrator', 'creator')
    except Exception:
        logger.exception('channel membership check failed user=%s channel=@%s', telegram_id, CHANNEL_SUBSCRIBE_USERNAME)
        return web.json_response({'ok': False, 'error': 'check'}, status=502)
    from services import channel_bonus_service as cbs
    if subscribed:
        if await asyncio.to_thread(has_credit_grant, telegram_id, 'channel_subscribe'):
            return web.json_response({**base, 'subscribed': True, 'granted': False, 'already': True,
                                      'credits': await asyncio.to_thread(get_photo_credits, telegram_id)})
        # V3.68.0: subscribing starts a CHANNEL_BONUS_HOLD_DAYS hold; the bonus
        # is paid only when he is still subscribed after it.
        started = await asyncio.to_thread(cbs.start_hold, telegram_id)
        left = cbs.days_left(started) if started else CHANNEL_BONUS_HOLD_DAYS
        if left > 0:
            await asyncio.to_thread(_track_channel_bonus, telegram_id, 'channel_bonus_hold', 0)
            return web.json_response({**base, 'subscribed': True, 'granted': False, 'pending': True,
                                      'days_left': left,
                                      'credits': await asyncio.to_thread(get_photo_credits, telegram_id)})
        balance = await asyncio.to_thread(
            grant_photo_credits, telegram_id, CHANNEL_SUBSCRIBE_BONUS_CREDITS, 'channel_subscribe')
        if balance == -1:
            return web.json_response({**base, 'subscribed': True, 'granted': False,
                                        'already': True,
                                        'credits': await asyncio.to_thread(get_photo_credits, telegram_id)})
        await asyncio.to_thread(_track_channel_bonus, telegram_id, 'channel_bonus_granted', balance)
        return web.json_response({**base, 'subscribed': True, 'granted': True, 'credits': balance})
    # V3.68.0: unsubscribing during the hold resets it.
    await asyncio.to_thread(cbs.clear_hold, telegram_id)
    if await asyncio.to_thread(has_credit_grant, telegram_id, 'channel_subscribe'):
        balance = await asyncio.to_thread(
            revoke_photo_credits, telegram_id, CHANNEL_SUBSCRIBE_BONUS_CREDITS, 'channel_subscribe')
        await asyncio.to_thread(_track_channel_bonus, telegram_id, 'channel_bonus_revoked', balance)
        return web.json_response({**base, 'subscribed': False, 'granted': False,
                                    'revoked': True, 'credits': balance})
    return web.json_response({**base, 'subscribed': False, 'granted': False,
                                'credits': await asyncio.to_thread(get_photo_credits, telegram_id)})


async def _webapp_api_char_like(request: web.Request) -> web.Response:
    # V3.43.0: the «♡ N» like on the character page — GET returns the counter
    # and whether this user liked her, POST toggles it (one like per user).
    character_id = str(request.query.get('character_id') or '').strip()
    if not await asyncio.to_thread(get_card, character_id):
        return web.json_response({'ok': False, 'error': 'character'}, status=404)
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    telegram_id = webapp_service.init_data_user(pairs).get('id') if pairs else None
    if request.method != 'POST':
        state = await asyncio.to_thread(webapp_service.character_like_state, character_id, telegram_id)
        return web.json_response({'ok': True, **state})
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    state = await asyncio.to_thread(webapp_service.toggle_character_like, character_id, telegram_id)
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
    # V3.57.2: the shop catalogue and the user's language are DB reads, so the
    # priced product list is built in a worker thread.
    lang = await asyncio.to_thread(user_lang, telegram_id)

    def _catalogue():
        return webapp_service.api_invoice_products(lang)

    _products = await asyncio.to_thread(_catalogue)
    product = next((p for p in _products if p['id'] == product_id), None)
    if not product:
        return web.json_response({'ok': False, 'error': 'unknown_product'}, status=400)
    if product_id == 'premium_trial' and not await asyncio.to_thread(trial_eligible, telegram_id):
        # V3.88.0: the trial is a one-time first purchase.
        return web.json_response({'ok': False, 'error': 'trial_used'}, status=409)
    if product_id == 'premium_vip':
        from services import vip_offer
        if not await asyncio.to_thread(vip_offer.is_active, telegram_id):
            return web.json_response({'ok': False, 'error': 'offer_over'}, status=409)
    # V3.44.23: custom peach amount — the frontend sends the desired count in
    # ``amount``; the stars price and payload are computed dynamically.
    if product_id == 'peach_custom':
        _ca = _custom_peach_units(body)
        product = dict(product)
        product['stars'] = _ca * PEACH_CUSTOM_STARS_PER_UNIT
        product['payload'] = f'peach_custom_{_ca}'
        product['title'] = (f'🍑 {_ca * PEACH_CUSTOM_UNIT} персиков' if user_lang(telegram_id) != EN
                            else f'🍑 {_ca * PEACH_CUSTOM_UNIT} peaches')
    uid = await asyncio.to_thread(
        ensure_user, telegram_id, user_info.get('first_name') or '',
        language_code=user_info.get('language_code'))
    await asyncio.to_thread(track_event, uid, 'webapp_invoice_created', metadata={'product': product_id})
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


def _custom_peach_units(body) -> int:
    """V3.65.0: how many PEACH_CUSTOM_UNIT units the custom-peach tile buys.
    The app sends ``peaches`` (rounded up to whole units); an app page cached
    from before the rescale still sends ``amount`` in units (old peaches)."""
    body = body or {}
    try:
        if body.get('peaches') is not None:
            return max(1, -(-int(body.get('peaches')) // PEACH_CUSTOM_UNIT))
        return max(1, int(body.get('amount', 1)))
    except (ValueError, TypeError):
        return 1


async def _webapp_api_demo(request: web.Request) -> web.Response:
    """V3.62.10: the free 3h demo Premium from the app's limit sheet."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    if not telegram_id or not has_accepted(telegram_id):
        return web.json_response({'ok': False, 'error': 'consent'}, status=403)
    from services.retention_service import grant_demo_premium

    def _grant():
        if is_premium(telegram_id):
            return True
        ok = grant_demo_premium(telegram_id)
        if ok:
            track_event(ensure_user(telegram_id), 'demo_premium_granted',
                        metadata={'hours': DEMO_PREMIUM_HOURS, 'source': 'webapp'})
        return ok

    ok = await asyncio.to_thread(_grant)
    return web.json_response({'ok': bool(ok), 'hours': DEMO_PREMIUM_HOURS} if ok else {'ok': False, 'error': 'used'})


async def _webapp_api_autopay(request: web.Request) -> web.Response:
    """V3.120.0: the shop card's «🔁 Автопродление» link — the bot sends the
    terms / manage menu into his chat and the app opens that chat."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    if not telegram_id or not await asyncio.to_thread(has_accepted, telegram_id):
        return web.json_response({'ok': False, 'error': 'consent'}, status=403)
    try:
        await _autopay_show(int(telegram_id), int(telegram_id))
    except Exception:
        logger.exception('webapp autopay menu failed user=%s', telegram_id)
        return web.json_response({'ok': False, 'error': 'send'}, status=502)
    from config import BOT_USERNAME as _bot_name
    url = f'https://t.me/{_bot_name}' if _bot_name else ''
    return web.json_response({'ok': True, 'url': url})


async def _webapp_api_pay_link(request: web.Request) -> web.Response:
    # V3.43.0: the Come Closer pay menu — tapping a shop square opens a modal
    # with Stars / card-SBP / crypto rows. Stars reuses /webapp/api/invoice;
    # this endpoint returns an external payment link for the other two:
    # a Platega payment page (SBP/card) and a Wallet Pay invoice (TON/USDT).
    # Both land in the same granting chain: the Platega callback and the
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
    # V3.57.2: language + catalogue reads leave the loop (see /api/invoice).
    lang = await asyncio.to_thread(user_lang, telegram_id)

    def _catalogue():
        return webapp_service.api_invoice_products(lang)

    _products = await asyncio.to_thread(_catalogue)
    product = next((p for p in _products if p['id'] == product_id), None)
    if product_id == 'premium_trial' and not await asyncio.to_thread(trial_eligible, telegram_id):
        # V3.88.0: the trial is a one-time first purchase.
        return web.json_response({'ok': False, 'error': 'trial_used'}, status=409)
    if product_id == 'premium_vip':
        from services import vip_offer
        if not await asyncio.to_thread(vip_offer.is_active, telegram_id):
            return web.json_response({'ok': False, 'error': 'offer_over'}, status=409)
    # V3.44.23: custom peach amount — compute the dynamic product fields from
    # the ``amount`` the frontend sends.
    if product_id == 'peach_custom':
        _ca = _custom_peach_units(body)
        product = dict(product)
        product['stars'] = _ca * PEACH_CUSTOM_STARS_PER_UNIT
        product['rub'] = _ca * PEACH_CUSTOM_RUB_PER_UNIT if PLATEGA_ENABLED else None
    # order product keys record_payment knows how to grant
    order_product = {'premium': 'premium_month', 'premium_week': 'premium_week',
                     'premium_trial': 'premium_trial',
                     'premium_vip': 'premium_month_vip',
                     'premium_quarter': 'premium_quarter',
                     'photo_credit': 'photo',
                     'undress_one': 'undress_one'}.get(product_id)
    if not order_product and product_id in PEACH_PACK_STARS:
        # V3.43.1: peach packs — the order key is the payload itself, so the
        # Platega callback and the Wallet Pay webhook grant the pack size.
        order_product = product_id
    if product_id == 'peach_custom':
        # V3.44.23: the order key encodes the count so record_payment grants it.
        order_product = f'peach_custom_{_ca}'
    if not product or not order_product:
        return web.json_response({'ok': False, 'error': 'unknown_product'}, status=400)
    uid = await asyncio.to_thread(
        ensure_user, telegram_id, user_info.get('first_name') or '',
        language_code=user_info.get('language_code'))
    if method == 'sbp' or method == 'platega_crypto':
        # V3.107.0: 'platega_crypto' is the «💎 Криптовалюта» row — the same
        # Platega payment page (the payer picks crypto there), tracked apart.
        if not PLATEGA_ENABLED or not product.get('rub'):
            return web.json_response({'ok': False, 'error': 'method_off'}, status=400)
        amount = str(product['rub'])
        order_id = await asyncio.to_thread(platega_service.create_order, telegram_id, order_product, amount)
        link = await platega_service.create_payment(
            order_id, amount, telegram_id=telegram_id,
        )
        if not link:
            # No SCI fallback exists (that was a FreeKassa thing) — 502 so the
            # frontend toasts its pay-link error instead of a dead tab.
            return web.json_response({'ok': False, 'error': 'invoice'}, status=502)
        await asyncio.to_thread(track_event, uid, 'webapp_pay_link', metadata={'product': product_id, 'method': method})
        return web.json_response({'ok': True, 'url': link})
    if method == 'crypto':
        if not WALLET_PAY_ENABLED:
            return web.json_response({'ok': False, 'error': 'method_off'}, status=400)
        from services.wallet_pay_service import create_invoice
        invoice = await create_invoice(
            telegram_id, order_product, product['stars'], product['description'],
        )
        if not invoice:
            return web.json_response({'ok': False, 'error': 'invoice'}, status=502)
        await asyncio.to_thread(track_event, uid, 'webapp_pay_link', metadata={'product': product_id, 'method': 'crypto'})
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
    # V3.57.2: selecting a girl re-renders the whole storefront — gate read,
    # three writes and two full API payloads used to freeze the loop for the
    # duration of every one of those queries.
    def _apply():
        card = get_card(character_id)
        if not card or card.status not in ('active', 'premium'):
            return 'locked'
        if card.status == 'premium' and not is_premium(telegram_id):
            return 'premium_required'
        uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
        set_user_character(telegram_id, character_id)
        track_event(uid, 'character_selected', metadata={'character_id': character_id, 'source': 'webapp'})
        return {'me': webapp_service.api_me(telegram_id),
                'characters': webapp_service.api_characters(telegram_id)}

    result = await asyncio.to_thread(_apply)
    if isinstance(result, str):
        return web.json_response({'ok': False, 'error': result},
                                 status=403 if result == 'premium_required' else 400)
    return web.json_response({'ok': True, **result}, headers={'Cache-Control': 'no-store'})


async def _webapp_api_scenario_start(request: web.Request) -> web.Response:
    """V3.75.0: the scenario card's button opens /webapp?open=chat&scene=<key>;
    the app calls this first. She becomes his girl (same rules as «select»),
    the scene direction switches on for a day, the tap bonus lands when the
    card came within a day, and the app then sends his entrance line through
    the normal chat so she answers in the scene."""
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
    from services import scenario_cards as sc
    from config import SCENARIO_TAP_PEACHES
    scenario = sc.get(str((body or {}).get('key', '')))
    if not scenario:
        return web.json_response({'ok': False, 'error': 'unknown'}, status=400)

    def _apply():
        card = get_card(scenario.character_id)
        if not card or not card.is_visible or card.status not in ('active', 'premium'):
            return 'locked'
        is_admin = telegram_id in ADMIN_TELEGRAM_IDS
        if card.status == 'premium' and not is_admin and not is_premium(telegram_id):
            return 'premium_required'
        if not is_adult_confirmed(telegram_id):
            return 'adult'
        uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
        set_user_character(telegram_id, scenario.character_id)
        started = sc.start(telegram_id, scenario.key)
        try:  # V3.78.0: the card's scene replaces a running storyline
            from services import storylines
            storylines.stop(telegram_id, scenario.character_id)
        except Exception:
            pass
        if not started['sent']:
            # a card that never went out (admin preview): her opening line
            # still starts the dialog, as the sent card does
            save_message(uid, scenario.character_id, 'assistant', sc.opening_line(scenario))
        bonus = 0
        if started['bonus_due'] and SCENARIO_TAP_PEACHES > 0:
            if grant_photo_credits(telegram_id, SCENARIO_TAP_PEACHES, reason=f'scenario_{scenario.key}') >= 0:
                bonus = SCENARIO_TAP_PEACHES
        track_event(uid, 'scenario_card_open', character_id=scenario.character_id,
                    metadata={'key': scenario.key, 'bonus': bonus})
        return {'character_id': scenario.character_id, 'enter': scenario.enter, 'bonus': bonus,
                'me': webapp_service.api_me(telegram_id),
                'characters': webapp_service.api_characters(telegram_id)}

    result = await asyncio.to_thread(_apply)
    if isinstance(result, str):
        return web.json_response({'ok': False, 'error': result},
                                 status=403 if result in ('premium_required', 'adult') else 400)
    return web.json_response({'ok': True, **result}, headers={'Cache-Control': 'no-store'})


async def _webapp_api_storylines(request: web.Request) -> web.Response:
    """V3.78.0: her «🎬 Сюжеты» list (titles and teasers) plus whether he
    can play them — every storyline needs Premium."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    from services import storylines
    character_id = str(request.query.get('character_id', ''))

    consume = request.query.get('consume') == '1'

    def _read():
        unlocked = telegram_id in ADMIN_TELEGRAM_IDS or is_premium(telegram_id)
        state = storylines.status(telegram_id, character_id, consume=consume)
        return {'plots': storylines.public_list(character_id), 'unlocked': bool(unlocked), **state}

    return web.json_response({'ok': True, **(await asyncio.to_thread(_read))},
                             headers={'Cache-Control': 'no-store'})


async def _webapp_api_storyline_start(request: web.Request) -> web.Response:
    """V3.78.0: he picked a storyline. Premium (or admin) and the 18+
    confirmation are required; her opening line lands in the dialog and the
    scene direction stays on her replies for a day. The app then opens the
    chat, where her line is already waiting."""
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
    from services import storylines
    from services import scenario_cards as sc
    plot = storylines.get(str((body or {}).get('character_id', '')), str((body or {}).get('key', '')))
    if not plot:
        return web.json_response({'ok': False, 'error': 'unknown'}, status=400)
    heat = str((body or {}).get('heat', 'hot'))
    if heat not in storylines.HEATS:
        heat = 'hot'

    def _apply():
        card = get_card(plot.character_id)
        if not card or not card.is_visible or card.status not in ('active', 'premium'):
            return 'locked'
        if telegram_id not in ADMIN_TELEGRAM_IDS and not is_premium(telegram_id):
            return 'premium_required'
        if not is_adult_confirmed(telegram_id):
            return 'adult'
        uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
        sc.stop(telegram_id, plot.character_id)
        storylines.start(telegram_id, plot, heat)
        save_message(uid, plot.character_id, 'assistant', plot.opening)
        track_event(uid, 'storyline_start', character_id=plot.character_id, metadata={'key': plot.key, 'heat': heat})
        return {'character_id': plot.character_id, 'key': plot.key}

    result = await asyncio.to_thread(_apply)
    if isinstance(result, str):
        return web.json_response({'ok': False, 'error': result},
                                 status=403 if result in ('premium_required', 'adult') else 400)
    return web.json_response({'ok': True, **result}, headers={'Cache-Control': 'no-store'})


async def _webapp_api_storyline_stop(request: web.Request) -> web.Response:
    """V3.78.0: «Без ролей» — he leaves the storyline; she is herself again."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    from services import storylines
    stopped = await asyncio.to_thread(storylines.stop, telegram_id, str((body or {}).get('character_id', '')))
    return web.json_response({'ok': True, 'stopped': bool(stopped)}, headers={'Cache-Control': 'no-store'})


async def _webapp_fetish_auth(request: web.Request):
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return None, None
    info = webapp_service.init_data_user(pairs)
    return info.get('id'), info


async def _webapp_api_fetishes(request: web.Request) -> web.Response:
    """V3.102.0: «🎭 Фетиши» — the theme list, the running theme and whether he can use it (Premium)."""
    telegram_id, info = await _webapp_fetish_auth(request)
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    from services import fetish_mode
    character_id = str(request.query.get('character_id', ''))
    lang = 'en' if user_lang(telegram_id) == EN else 'ru'

    def _read():
        unlocked = telegram_id in ADMIN_TELEGRAM_IDS or is_premium(telegram_id)
        return {'items': fetish_mode.public_list(lang), 'unlocked': bool(unlocked),
                'active': fetish_mode.status(telegram_id, character_id, lang)}

    return web.json_response({'ok': True, **(await asyncio.to_thread(_read))}, headers={'Cache-Control': 'no-store'})


async def _webapp_api_fetish_set(request: web.Request) -> web.Response:
    """V3.102.0: he picked a theme (or typed his own). Premium (or admin) and 18+ are required;
    her opening line lands in the dialog and she leads the theme from the next reply."""
    telegram_id, info = await _webapp_fetish_auth(request)
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    from services import fetish_mode
    character_id = str((body or {}).get('character_id', ''))
    key = str((body or {}).get('key', '')).strip()
    custom = str((body or {}).get('custom', ''))

    def _apply():
        card = get_card(character_id)
        if not card or not card.is_visible or card.status not in ('active', 'premium'):
            return 'locked'
        if telegram_id not in ADMIN_TELEGRAM_IDS and not is_premium(telegram_id):
            return 'premium_required'
        if not is_adult_confirmed(telegram_id):
            return 'adult'
        started = fetish_mode.start(telegram_id, character_id, key=key if key != 'custom' else '', custom=custom)
        if not started:
            return 'refused'
        uid = ensure_user(telegram_id, (info or {}).get('first_name') or '', language_code=(info or {}).get('language_code'))
        save_message(uid, character_id, 'assistant', started['opening'])
        track_event(uid, 'fetish_mode_on', character_id=character_id, metadata={'key': started['key']})
        return {'title': started['title'], 'key': started['key']}

    result = await asyncio.to_thread(_apply)
    if isinstance(result, str):
        return web.json_response({'ok': False, 'error': result},
                                 status=403 if result in ('premium_required', 'adult') else 400)
    return web.json_response({'ok': True, **result}, headers={'Cache-Control': 'no-store'})


async def _webapp_api_fetish_stop(request: web.Request) -> web.Response:
    telegram_id, _info = await _webapp_fetish_auth(request)
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    from services import fetish_mode
    stopped = await asyncio.to_thread(fetish_mode.stop, telegram_id, str((body or {}).get('character_id', '')))
    return web.json_response({'ok': True, 'stopped': bool(stopped)}, headers={'Cache-Control': 'no-store'})


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
    # V3.57.2: the read, the premium check and the write all leave the loop.
    def _toggle():
        user = get_user(telegram_id)
        current = bool(getattr(user, 'spicy_mode', False)) if user else False
        if not current and not is_premium(telegram_id):
            return None
        # V3.64.7: the main-screen banner makes this switch visible to
        # everyone — enabling also needs the 18+ confirmation.
        if not current and not is_adult_confirmed(telegram_id):
            return 'adult_confirm'
        update_user_settings(telegram_id, spicy_mode=not current)
        return not current

    flipped = await asyncio.to_thread(_toggle)
    if flipped is None:
        return web.json_response({'ok': False, 'error': 'premium_required'}, status=403)
    if flipped == 'adult_confirm':
        return web.json_response({'ok': False, 'error': 'adult_confirm'}, status=403)
    return web.json_response({'ok': True, 'spicy_mode': flipped}, headers={'Cache-Control': 'no-store'})


async def _webapp_api_presence(request: web.Request) -> web.Response:
    """V3.128.0: the SPA's heartbeat (on screen) and away beacon (hidden or
    closed). In memory only, no DB: services/app_ping.py pings the bot chat
    only for messages that landed while he was away."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    from services import app_ping
    app_ping.touch(int(telegram_id), away=request.query.get('state') == 'away')
    return web.json_response({'ok': True})


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
    try:
        limit = int(request.query.get('limit', '30'))
    except ValueError:
        limit = 30
    # V3.61.8: only a real chat open (not photo polling) may add her «ты где?».
    opening = request.query.get('open') == '1'
    # V3.57.2: the whole blocking open-the-dialog block (ensure_user write,
    # mark-read, premium floor, history read) runs in a worker thread.
    def _load():
        uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
        # V3.61.8: back after a long silence — she writes first («ты где?»).
        fork_pending = False
        if opening:
            from services.presence_service import maybe_welcome_back
            maybe_welcome_back(uid, character_id)
            # V3.62.0: level 3+ and no path yet — she asks «что я для тебя?».
            try:
                from services.branch_service import maybe_offer_fork
                from services.chat_guest_service import guest_marital
                from services.relationship_engine import TAKEN_STATUSES
                from services.test_mode import get_stage as _fork_test_stage
                fork_pending = maybe_offer_fork(
                    uid, character_id, taken=guest_marital(telegram_id, character_id) in TAKEN_STATUSES,
                    stage_override=_fork_test_stage(telegram_id, character_id))
            except Exception:
                logger.exception('fork offer on chat open failed user=%s', telegram_id)
        # V3.52.0: opening the conversation in the app marks it read — the «Чаты»
        # badge clears and only a later proactive/life message will light it up again.
        webapp_service.mark_chat_read(telegram_id, character_id)
        # V3.55.6: a premium user opens a premium character — the level-6 floor is
        # applied right here so the level shows before the first message, and the
        # chat tells the SPA whether the tender/passionate choice is still pending.
        persona_info = {'needed': False, 'style': None}
        try:
            from services.relationship_engine import apply_premium_floor
            with SessionLocal() as session:
                rel_row = apply_premium_floor(session, uid, character_id)
            if rel_row is not None:
                # V3.62.0: the path fork in the chat asks the same question.
                persona_info = {'needed': rel_row.persona_style is None and not fork_pending
                                and getattr(rel_row, 'branch', None) is None,
                                'style': rel_row.persona_style}
        except Exception:
            logger.exception('premium floor on chat open failed user=%s character=%s', telegram_id, character_id)
        return webapp_service.api_chat_history(uid, character_id, limit), persona_info, uid

    history, persona_info, uid = await asyncio.to_thread(_load)
    # V3.148.0: the auto-greeting is off here too. An empty chat shows the
    # «напиши первое сообщение» placeholder and she answers his first line —
    # no LLM message is ever put in his mouth, in the bot or in the app.

    def _duo():
        # V3.61.0: a constructor duo — the SPA bolds each speaker's name.
        if not is_custom_character(character_id):
            return None
        from services.custom_character_service import custom_character_params, duo_partner
        return duo_partner(custom_character_params(character_id)[0])[0] or None

    try:
        duo = await asyncio.to_thread(_duo)
    except Exception:
        duo = None
    # V3.61.2: «позвать в чат» — the invited girl (her name is bolded like a duo's).
    guest = None
    try:
        from services.chat_guest_service import get_guest, character_name
        guest_id = await asyncio.to_thread(get_guest, telegram_id, character_id)
        if guest_id and not duo:
            guest = {'id': guest_id, 'name': character_name(guest_id) or guest_id,
                     'photo': f'/webapp/photo/{guest_id}'}
            duo = guest['name']
    except Exception:
        logger.exception('chat guest load failed user=%s', telegram_id)
    return web.json_response({'ok': True, 'history': history, 'persona': persona_info, 'duo': duo,
                              'guest': guest, 'can_invite': not (duo and not guest)})


def _custom_premium_gate_block(character_id: str, telegram_id: int) -> bool:
    """V3.55.3: constructor personas carry the same premium gate as built-ins.

    A card flipped to ``premium`` (admin panel or the premium-tab constructor)
    used to be bypassed by the custom-character branches of the app chat
    endpoints, which only checked existence — the status now applies to every
    persona. The author keeps access to her own creation.
    """
    try:
        card = get_card(character_id)
    except Exception:
        return False
    if not card or card.status != 'premium':
        return False
    if is_premium(telegram_id) or telegram_id in ADMIN_TELEGRAM_IDS:
        return False
    try:
        return str(telegram_id) not in webapp_service._mine_character_ids(telegram_id)
    except Exception:
        return True


def _webapp_chat_gate(character_id: str, telegram_id: int):
    """V3.57.0: the shared access gate for one app-chat turn (text/voice/photo) —
    the same checks the bot chat runs: character access, 18+ consent, daily limit."""
    if is_custom_character(character_id):
        # Constructor personas are public: anyone can open a dialog with her.
        if not get_custom_character_by_id(character_id):
            return web.json_response({'ok': False, 'error': 'unknown_character'}, status=400)
        # V3.55.3: a premium-status custom persona is closed for non-premium
        # users too — the built-in gate below never ran on the custom branch.
        if _custom_premium_gate_block(character_id, telegram_id):
            return web.json_response({'ok': False, 'error': 'premium_required'}, status=403)
    else:
        card = get_card(character_id)
        if not card or card.status not in ('active', 'premium'):
            return web.json_response({'ok': False, 'error': 'locked'}, status=403)
        if card.status == 'premium' and not is_premium(telegram_id):
            return web.json_response({'ok': False, 'error': 'premium_required'}, status=403)
    if not has_accepted(telegram_id):
        return web.json_response({'ok': False, 'error': 'consent'}, status=403)
    if telegram_id not in ADMIN_TELEGRAM_IDS and not can_send_message(telegram_id):
        if is_premium(telegram_id):
            # V3.124.0: the trial's message total is spent — the full plans, no demo.
            track_event(ensure_user(telegram_id), 'trial_cap_messages', metadata={'source': 'webapp'})
            return web.json_response({'ok': False, 'error': 'limit', 'demo': False, 'vip': False,
                                      'trial': True}, status=429)
        # V3.62.10: the app limit used to be a bare toast — tell the sheet
        # whether the free demo is still there, like the bot's sleep block.
        from services.retention_service import has_used_demo, offer_discount
        demo = not has_used_demo(telegram_id)
        if not demo:
            offer_discount(telegram_id)
        track_event(ensure_user(telegram_id), 'chat_sleep_block', metadata={'source': 'webapp'})
        from services import vip_offer
        if vip_offer.maybe_open(telegram_id):
            track_event(ensure_user(telegram_id), 'vip_offer_shown', metadata={'source': 'webapp'})
        return web.json_response({'ok': False, 'error': 'limit', 'demo': demo,
                                  'vip': vip_offer.is_active(telegram_id)}, status=429)
    return None


def _tts_text(text: str) -> str:
    """Text for her voice note. V3.106.0: with VOICE_HUMANIZE_ENABLED the raw
    line goes on (emoji, «)))», «хаха» become laughs / sighs in
    services/voice_humanize.py); otherwise the old letters-and-punctuation cut."""
    from services import voice_humanize
    if voice_humanize.ENABLED:
        return (text or '')[:600]
    return ''.join(ch for ch in (text or '') if ch.isalnum() or ch in ' .,!?:;-—…()«»\'\n')[:600]


async def _webapp_reply_voice_url(telegram_id: int, character_id: str, text: str):
    """V3.57.0: synthesize her voice note for an app-chat reply when allowed —
    same rules as the Telegram _send_voice_note: the voice_enabled toggle plus
    Premium (admins bypass). Returns the saved media URL or None on any failure:
    a broken TTS must never eat the text reply."""
    try:
        # V3.57.2: the permission read and the media write are PostgreSQL/disk
        # work — off the loop, only the synthesis itself stays awaited.
        taste = ['']

        def _allowed():
            user = get_user(telegram_id)
            if not user:
                return None
            if telegram_id in ADMIN_TELEGRAM_IDS or is_premium(telegram_id):
                if not getattr(user, 'voice_enabled', False):
                    return None
                if telegram_id not in ADMIN_TELEGRAM_IDS and not _trial_voice_ok(telegram_id):
                    return None
                return user.voice_style or 'nova'
            # V3.106.0: without Premium — her first replies come as voice on
            # their own (services/voice_taste.py), then a quiet «слышать всегда».
            from services import voice_taste
            from models.app_models import Message
            from sqlalchemy import func
            with SessionLocal() as s:
                mine = int(s.scalar(select(func.count(Message.id)).where(
                    Message.user_id == user.id, Message.character_id == character_id,
                    Message.role == 'user')) or 0)
            taste[0] = voice_taste.decide(telegram_id, text, mine)
            return (user.voice_style or 'nova') if taste[0] == 'voice' else None

        voice_style = await asyncio.to_thread(_allowed)
        if taste[0] == 'offer':
            await asyncio.to_thread(track_event, ensure_user(telegram_id), 'paywall_view',
                                    metadata={'product': 'voice_taste', 'character_id': character_id})
            return 'offer'
        if not voice_style:
            return None
        clean = _tts_text(text)
        if not clean.strip():
            return None
        audio = await synthesize_bytes(clean, voice_style, character_id=character_id)
        filename = await asyncio.to_thread(
            webapp_service.save_chat_media, telegram_id, audio, 'ogg', 'audio/ogg')
        if taste[0] == 'voice':
            from services import voice_taste
            await asyncio.to_thread(voice_taste.mark_sent, telegram_id, character_id)
        return f'/webapp/media/{filename}'
    except Exception:
        logger.warning('webapp reply voice failed user=%s', telegram_id)
        return None


CHAT_PHOTO_BLOCK_TEXT = {
    # V3.125.0: a Premium man past his photos — say plainly that only bought
    # peaches pay for a photo, and the pack sheet opens right under it.
    'peaches': ('ой, хочу прислать тебе фото, но фото, что входят в твой Premium, пока закончились 🙈 '
                'ещё одно — {price} 🍑 (только купленные персики, бонусные на фото не идут). '
                'пополни — и попроси ещё раз, я сразу скину 😘'),
    'stage': ('такое фото пока рано 😏 давай ещё пообщаемся — чем ближе мы, тем больше я тебе покажу. '
              'а обычное селфи могу прямо сейчас, попроси «пришли селфи»'),
    'adult': 'для такого фото подтверди, что тебе 18+, — и я покажу 🔥',
    'failed': 'ой, фото не загрузилось 😔 попробуй ещё раз — персики не списались',
    # V3.76.0: card girls' pictures are a Premium thing (as at Come Closer).
    'premium': 'хочу показать тебе фото… но мои фото только для тех, у кого Premium 😏 оформишь — пришлю сразу',
    # V3.93.0: without Premium — one free photo a day, no more.
    'free_used': ('сегодня я тебе уже показалась 🙈 следующее фото — завтра… или оформи Premium: '
                  'там каждый день по 2 новых фото, а ещё можно за персики 😘'),
    # V3.87.0: nude / lingerie photos are Premium-only — the funnel to Premium.
    'spicy': ('такие фото я показываю только самым близким 🙈 оформи Premium — '
              'и я пришлю его сразу, а ещё раздену себя для тебя по кнопке 🔥'),
}


def _card_girl_photo_locked(character_id: str, telegram_id: int) -> bool:
    """V3.76.0: owner — «у нашего конкурента все на прем идёт». Chatting
    with a scenario-card girl is free; her photos and videos need Premium."""
    from services.scenario_cards import SCENARIO_GIRLS
    return (character_id in SCENARIO_GIRLS and telegram_id not in ADMIN_TELEGRAM_IDS
            and not is_premium(telegram_id))


# V3.60.9: she promises a photo in her own words («лови фотку», «держи селфи 📸»)
PHOTO_PROMISE = re.compile(
    r'(?:\b(?:лови|держи|скидываю|отправляю|высылаю|кидаю|шлю|посылаю|скинула|отправила|кинула|прислала|'
    r'сделала|вот\s+тебе|вот\s+она|вот\s+ещё|вот\s+еще|смотри)\b[^.!?\n]{0,40}'
    r'(?:фот|селфи|📸|снимок|кадр))|(?:(?:фот\w*|селфи)[^.!?\n]{0,20}\b(?:лови|держи)\b)|'
    r'(?:\b(?:лови|держи|смотри|глянь)\b[^\n]{0,40}📸)|'
    # V3.61.5: an action line «*шлю тебе ещё фотку*» / «*отправляет селфи*»
    r'(?:\*[^*\n]{0,40}\b(?:шлю|отправля\w*|скидыва\w*|присыла\w*|делаю|делает|снима\w*)\b[^*\n]{0,30}(?:фот|селфи|снимок)[^*\n]{0,30}\*)',
    re.IGNORECASE)
# her question/offer about a photo, and a short «yes» to it
PHOTO_OFFER = re.compile(r'(фот|селфи|📸|снимок|скинуть|скину|прислать|показать|покажу|кадр|увидеть|посмотреть|глянуть|надето|на мне)', re.IGNORECASE)
PHOTO_AGREE = re.compile(
    r'^\W*(?:да+|давай|ага|конечно|скинь|кидай|кинь|присылай|пришли|покажи|хочу|жду|ок|окей|го|yes|sure)\b',
    re.IGNORECASE)


_HANDS_OVER = re.compile(r'^\W*(?:вот,?\s+)?(?:лови|держи|смотри|глянь|here you go)\b', re.IGNORECASE)
_ASKED_TO_SEE = re.compile(r'(покаж|скин|кинь|пришли|присыл|отправ|фот|селфи|хочу увидеть|show|send|pic|photo)', re.IGNORECASE)


def _accepts_her_photo_offer(uid: int, character_id: str, text: str) -> bool:
    low = (text or '').strip().lower()
    if not low or len(low) > 40 or not PHOTO_AGREE.search(low):
        return False
    try:
        from services.memory_service import get_recent_messages
        recent = get_recent_messages(uid, character_id, 2)
    except Exception:
        return False
    last = next((m for m in reversed(recent) if m.role == 'assistant'), None)
    if last is None or getattr(last, 'media_url', None):
        return False
    return bool(PHOTO_OFFER.search(last.content or ''))


# V3.113.0: «Покажи сиськи», «скинь попку», «покажи)» — 20 of 25 such asks in
# the 1 Nov backup got neither a photo nor an honest «Premium / завтра»: the
# photo parser only knew «фото/селфи», so the model answered «держи 😏» empty.
_SHOW_ME = re.compile(r'^\W*(?:покажи|покажись|скинь|кинь|пришли|присылай|отправь|вышли|show me|send me)\b(.{0,40})$', re.IGNORECASE)
_SHOW_BODY_NUDE = re.compile(r'(сиськ|сисечк|грудь|груд[иь]|соск|киск|голая|голую|голой|без одежд|разден|tits|boobs|naked|nude)', re.IGNORECASE)
_SHOW_BODY_REAR = re.compile(r'(попк|попу|жоп|задниц|ягодиц|ass\b|butt)', re.IGNORECASE)
_SHOW_BODY_LINGERIE = re.compile(r'(трус|бель|лифчик|чулк|lingerie|panties)', re.IGNORECASE)


def _show_me_request(text: str) -> PhotoRequest | None:
    """«покажи сиськи» / «скинь попку» / «покажись» as a photo request; None otherwise.
    A bare «покажи» counts only through _accepts_her_photo_offer (after her offer)."""
    m = _SHOW_ME.match((text or '').strip())
    if not m:
        return None
    rest = m.group(1) or ''
    # the chat renders only menu scenes (explicit ones left the menu in V3.30.0):
    # a body ask becomes her boudoir shot, which is Premium-only — a free user
    # gets her blurred card and the pay button, not a fully dressed selfie.
    if _SHOW_BODY_NUDE.search(rest) or _SHOW_BODY_LINGERIE.search(rest):
        return PhotoRequest(scene='lingerie')
    if _SHOW_BODY_REAR.search(rest):
        return PhotoRequest(scene='personal')
    if re.search(r'(себя|себе|лицо|как выглядишь|как ты выглядишь|платье|наряд|образ|yourself)', rest, re.I):
        return PhotoRequest(scene='selfie')
    return None


_UNDRESS_DIRECT = re.compile(
    r'^\W*(?:разденься|раздевайся|раздень\s+себя|сними\s+(?:всё|все|одежду|с\s+себя\s+всё)|'
    r'хочу\s+(?:увидеть\s+)?тебя\s+(?:голой|голую)|'
    r'undress(?:\s+yourself)?|get\s+naked|take\s+(?:everything|it\s+all)\s+off|'
    r'take\s+off\s+your\s+clothes|i\s+want\s+you\s+naked|strip(?:\s+for\s+me)?)\b',
    re.IGNORECASE)
_UNDRESS_NEG = re.compile(
    r'(?:не|нет|нельзя|don\'t|do\s+not|dont|no)\s+'
    r'(?:разденься|раздевайся|раздень|сними|хочу|undress|get|take|i\s+want|strip)',
    re.IGNORECASE)


def _direct_undress_request(text: str) -> PhotoRequest | None:
    low = (text or '').strip()
    if not low or _UNDRESS_NEG.search(low):
        return None
    if _UNDRESS_DIRECT.match(low):
        return PhotoRequest(scene='lingerie')
    return None


def _free_photo_from_pool(telegram_id: int, uid: int, character_id: str):
    """V3.81.0: (bytes, mime, ext) of a ready photo instead of a new render;
    None means render as usual.
    V3.93.0: without Premium the one free photo of the day is ALWAYS a ready
    one (her pool or a photo already rendered of her); Premium free photos
    are rendered until the daily budget is spent (V3.81.0)."""
    if telegram_id in ADMIN_TELEGRAM_IDS:
        return None
    try:
        from services.chat_photo_allowance import free_chat_photos_left, free_photo_budget_spent, reused_photo
        premium = is_premium(telegram_id)
        if free_chat_photos_left(uid, premium=premium) <= 0:
            return None
        if premium and not free_photo_budget_spent():
            return None
        picked = reused_photo(character_id, uid)
    except Exception:
        logger.exception('free photo pool pick failed user=%s', telegram_id)
        return None
    if picked:
        logger.info('free photo reused user=%s char=%s premium=%s', telegram_id, character_id, premium)
    return picked


def _chat_photo_gate(telegram_id: int, character_id: str, scene: str, *, undress_credit: bool = False,
                     joint: bool = False) -> str | None:
    """The stage / 18+ / peaches gates of a chat photo; None = go."""
    if _card_girl_photo_locked(character_id, telegram_id):
        return 'premium'
    if requires_adult_confirmation(PhotoRequest(scene=scene)) and not is_adult_confirmed(telegram_id):
        return 'adult'
    if joint and telegram_id not in ADMIN_TELEGRAM_IDS and not is_premium(telegram_id):
        # V3.139.0: owner ТЗ (Фогель, Задача 5) — a joint photo of the two girls
        # is a Premium thing. A free man is not charged and nothing is rendered:
        # he gets the blurred teaser from the ready pool instead.
        try:
            track_event(ensure_user(telegram_id), 'paywall_view',
                        metadata={'product': 'duo_photo', 'scene': scene, 'source': 'chat'})
        except Exception:
            pass
        return 'duo'
    # V3.88.0: spicy scenes skip the level gate — Premium is the gate («с
    # Premium открыто всё откровенное»); a fresh buyer at level 1 must get
    # the photo he paid for, not «пока рано».
    if not spicy_needs_premium(PhotoRequest(scene=scene)) \
            and not scene_allowed_for_stage(scene, get_relationship_stage(telegram_id, character_id)):
        return 'stage'
    if telegram_id not in ADMIN_TELEGRAM_IDS and not is_premium(telegram_id) \
            and spicy_needs_premium(PhotoRequest(scene=scene)):
        # V3.87.0: nude / lingerie — Premium-only, no free route.
        # V3.137.0: a bought one-time «Раздеть» opens this exact request.
        # V3.138.0: owner — without Premium it is peaches now: 250 🍑 ≈ 25 ₽.
        if undress_credit:
            from services import undress_credits
            from config import UNDRESS_PEACH_COST
            if undress_credits.balance(telegram_id) > 0 \
                    or get_paid_peaches(telegram_id) >= UNDRESS_PEACH_COST:
                return None
        try:
            track_event(ensure_user(telegram_id), 'paywall_view',
                        metadata={'product': 'spicy_photo', 'scene': scene, 'source': 'chat'})
        except Exception:
            pass
        return 'spicy'
    if telegram_id not in ADMIN_TELEGRAM_IDS:
        # V3.61.5: today's free chat photos go first.
        # V3.93.0: without Premium — one a day and that is it (free peaches
        # must not burn the render budget); with Premium — two, then peaches.
        from services.chat_photo_allowance import free_chat_photos_left
        premium = is_premium(telegram_id)
        if free_chat_photos_left(ensure_user(telegram_id), premium=premium) <= 0:
            if not premium:
                try:
                    track_event(ensure_user(telegram_id), 'paywall_view',
                                metadata={'product': 'chat_photo', 'source': 'free_used'})
                except Exception:
                    pass
                return 'free_used'
            if get_paid_peaches(telegram_id) < CHAT_PHOTO_PEACH_COST:
                return 'peaches'
    return None


# V3.113.0: owner — «пишет покажи, а ничего не скидывает». When the photo is
# closed (free one used, Premium-only), he still SEES something: her blurred
# photo card with the pay button, instead of words alone.
_LOCKED_CARD_REASONS = frozenset({'free_used', 'premium', 'spicy'})


def _chat_photo_blocked(uid: int, character_id: str, reason: str, extra: dict | None,
                        *, telegram_id: int | None = None, lang: str = '') -> dict:
    if reason == 'duo':
        return _chat_duo_blocked(uid, telegram_id or 0, character_id, lang, extra or {})
    text = CHAT_PHOTO_BLOCK_TEXT[reason].format(price=CHAT_PHOTO_PEACH_COST)
    try:
        save_message(uid, character_id, 'assistant', text)
    except Exception:
        logger.warning('chat photo block message not saved uid=%s', uid)
    payload = {'ok': True, 'reply': text, 'photo_block': reason, 'photo_price': CHAT_PHOTO_PEACH_COST}
    if reason in _LOCKED_CARD_REASONS:
        payload['locked_tease'] = {'url': f'/webapp/locked/{character_id}.jpg'}
        try:
            track_event(uid, 'photo_locked_card', character_id=character_id, metadata={'reason': reason})
        except Exception:
            pass
    payload.update(extra or {})
    return payload


def _chat_duo_blocked(uid: int, telegram_id: int, character_id: str, lang: str, extra: dict) -> dict:
    """V3.139.0: owner ТЗ (Фогель, Задача 5) — a man without Premium asked for
    the two of them together. Nothing is rendered (no provider call, no money):
    he gets one heavily blurred joint picture out of the ready pool, both girls
    speak in their own bubbles in his language, and the Premium button sits
    under the picture. A tap there opens the payment sheet; buying and asking
    again runs the real generation (Задача 6)."""
    from services import duo_teaser
    from services import ui_lang as _ui
    from services.chat_guest_service import host_name, speakers
    from services.chat_service import duo_lines
    names = {}
    try:
        names = speakers(telegram_id, character_id) or {}
    except Exception:
        logger.warning('duo speakers read failed uid=%s', uid)
    guest_id = next((cid for cid in names.values() if cid != character_id), '')
    guest_nm = next((nm for nm, cid in names.items() if cid != character_id), '')
    host_nm = host_name(character_id) or next(
        (nm for nm, cid in names.items() if cid == character_id), '')
    url = duo_teaser.url_for(character_id, guest_id) if guest_id else None
    text = _ui.duo_teaser(lang, host_nm, guest_nm)
    parts = duo_lines(text)
    try:
        if parts:
            for i, (nm, line) in enumerate(parts):
                last = i == len(parts) - 1
                save_message(uid, character_id, 'assistant', f'{nm}: {line}',
                             media_kind='duo_teaser' if (last and url) else None,
                             media_url=url if (last and url) else None)
        else:
            save_message(uid, character_id, 'assistant', text,
                         media_kind='duo_teaser' if url else None, media_url=url)
    except Exception:
        logger.warning('duo teaser message not saved uid=%s', uid)
    try:
        track_event(uid, 'duo_teaser_view', character_id=character_id,
                    metadata={'has_picture': bool(url)})
    except Exception:
        pass
    payload = {'ok': True, 'reply': text, 'photo_block': 'duo', 'duo_offer': True}
    if url:
        payload['duo_tease'] = {'url': url}
    if parts:
        payload['reply_parts'] = [{'name': nm, 'text': line} for nm, line in parts]
    payload.update(extra)
    return payload


def _app_ping(telegram_id: int, character_id: str, text: str, media: str | None = None) -> None:
    """V3.128.0: her message landed in the app chat only — if he is not in the
    app, a short collapsed ping goes to the bot chat (services/app_ping.py)."""
    try:
        from services import app_ping
        app_ping.note(bot, telegram_id, character_id, text, media)
    except Exception:
        logger.warning('app ping hook failed user=%s', telegram_id, exc_info=True)


def _pings_app_reply(turn):
    """V3.128.0: wraps one app chat turn; when he closed the app before her
    answer came, the answer also pings the bot chat (services/app_ping.py)."""
    @functools.wraps(turn)
    async def wrapper(telegram_id: int, user_info: dict, character_id: str,
                      text: str, extra: dict | None = None) -> web.Response:
        resp = await turn(telegram_id, user_info, character_id, text, extra)
        try:
            body = json.loads(resp.body) if getattr(resp, 'body', None) else {}
            if isinstance(body, dict) and body.get('ok') and body.get('reply'):
                _app_ping(telegram_id, character_id, str(body.get('reply') or ''),
                          'photo' if body.get('photo_url') else None)
        except Exception:
            logger.warning('app ping on chat turn failed user=%s', telegram_id, exc_info=True)
        return resp
    return wrapper


@_pings_app_reply
async def _webapp_chat_turn(telegram_id: int, user_info: dict, character_id: str,
                            text: str, extra: dict | None = None) -> web.Response:
    from services import spend_service
    spend_service.set_spend_user(telegram_id)
    # V3.35.0: a message typed in the app goes through the exact pipeline the
    # bot chat uses (memory, relationships, persona) — same gates too: 18+
    # consent and the daily free-message limit.
    # V3.57.0: shared by the text and voice endpoints; a text reply may come
    # back with her voice attached when the user has voice replies enabled.
    # V3.57.2: everything around the model call is PostgreSQL work (user
    # upsert, event track, stage/credit reads, message writes) — it runs in one
    # worker thread so a chat turn never blocks the loop the other users share.
    photo_req = None

    def _prelude():
        uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
        # V3.97.0: «Девушка дня» had no trace in analytics — tag the message.
        try:
            from services import girl_of_day as _gday
            _gd = _gday.is_open(character_id)
        except Exception:
            _gd = False
        track_event(uid, 'webapp_chat_message', metadata={'character_id': character_id, 'girlday': _gd})
        # V3.51.0: a photo request typed in the Mini App chat used to be answered
        # with text only («держи 📸» and nothing attached) because this endpoint
        # never ran the bot's photo-intent routing (main.py chat handler). Parse it
        # here and, when the scene clears the same stage/adult/credit gates the app
        # photo button enforces, deliver a real photo into the shared dialog.
        photo_request = _contextualize_vague_photo(telegram_id, text, parse_photo_request(text))
        if not photo_request:
            photo_request = _show_me_request(text)
        direct_undress = _direct_undress_request(text) is not None
        if not photo_request and direct_undress:
            photo_request = _direct_undress_request(text)
        # V3.60.9: «скинь конечно» right after she offered a photo is a request too.
        if not photo_request and _accepts_her_photo_offer(uid, character_id, text):
            photo_request = parse_photo_request('пришли селфи')
        if not photo_request:
            return uid, None, None, None, False, False, RU
        nonlocal photo_req
        photo_req = _selfie_from_dialog(uid, character_id, photo_request)
        # V3.61.2: «сфоткайтесь вдвоём» — the invited girl joins the frame.
        photo_req = attach_guest(photo_req, telegram_id, character_id, text)
        scene = photo_request.scene if photo_request.scene in PHOTO_MENU_ORDER else 'selfie'
        # V3.139.0: owner ТЗ — a joint request from a free man is the blurred
        # teaser route, and his own language is what the two girls say in.
        joint = bool(getattr(photo_req, 'with_guest', ''))
        block = _chat_photo_gate(telegram_id, character_id, scene, undress_credit=direct_undress, joint=joint)
        pay = None
        if direct_undress and block is None and telegram_id not in ADMIN_TELEGRAM_IDS \
                and not is_premium(telegram_id):
            from services import undress_credits
            pay = 'undress_credit' if undress_credits.balance(telegram_id) > 0 else 'undress_peaches'
        return (uid, scene, block, pay, direct_undress, joint,
                full_user_lang(telegram_id, user_info.get('language_code')))

    uid, photo_scene, photo_block, photo_pay, direct_undress, photo_joint, user_language = \
        await asyncio.to_thread(_prelude)
    # V3.60.3: a blocked or failed photo request used to fall through to the
    # model, which happily wrote «лови 😏» with nothing attached. Now she says
    # plainly what is in the way and offers the way forward.
    if photo_block:
        blocked_extra = dict(extra or {})
        if direct_undress and photo_block == 'spicy':
            blocked_extra.update({'undress_offer': True, 'retry_text': text})
        if photo_block == 'duo':
            blocked_extra['retry_text'] = text
        return web.json_response(await asyncio.to_thread(
            _chat_photo_blocked, uid, character_id, photo_block, blocked_extra,
            telegram_id=telegram_id, lang=user_language))

    async def _photo_turn(scene: str, req, said: str | None = None, pay: str | None = None):
        """Render + deliver one chat photo. `said` is her own text when the
        photo backs a promise she just made («лови 📸»)."""
        # V3.81.0: past today's free-photo budget, a FREE photo comes from her
        # ready-made pool instead of a new render. Paid and Premium are untouched.
        # V3.139.0: a joint request never takes from the pool — a single girl
        # is not what he asked for.
        guest_id = getattr(req, 'with_guest', '') if req is not None else ''
        pooled = None if (pay in ('undress_credit', 'undress_peaches') or guest_id) else await asyncio.to_thread(
            _free_photo_from_pool, telegram_id, uid, character_id)
        try:
            if pooled:
                data, mime, ext = pooled
            elif req is not None and req.location and scene == 'selfie':
                data, mime, ext = await _webapp_pipeline_photo(telegram_id, character_id, req)
            else:
                data, mime, ext = await _webapp_media_photo(telegram_id, character_id, scene, guest_id)
        except Exception as exc:
            logger.exception('webapp chat photo-on-request failed user=%s scene=%s', telegram_id, scene)
            await asyncio.to_thread(webapp_service.record_generation_failure, telegram_id, 'photo',
                                    character_id, text, f'{type(exc).__name__}: {exc}')
            data = None
        fallback = False
        if not data and telegram_id not in ADMIN_TELEGRAM_IDS \
                and not spicy_needs_premium(PhotoRequest(scene=scene)):
            # V3.98.0: 31 «фото не загрузилось» in a week, each one at the moment
            # he asked — she sends a ready photo of herself instead, free of
            # charge and without spending the day's allowance.
            try:
                from services.chat_photo_allowance import reused_photo
                picked = await asyncio.to_thread(reused_photo, character_id, uid)
            except Exception:
                picked = None
            if picked:
                data, mime, ext = picked
                fallback = True
                await asyncio.to_thread(track_event, uid, 'photo_fallback_pool',
                                        metadata={'character_id': character_id, 'scene': scene})
        if not data:
            return None
        cap = said or ('📸 ' + random.choice(AUTO_CAPTIONS.get(scene, ('отправила фото',))))

        def _deliver():
            filename = webapp_service.save_chat_media(telegram_id, data, ext, mime)
            url = f'/webapp/media/{filename}'
            # V3.51.1: audit the chat photo-on-request (user's own words).
            webapp_service.record_generation(telegram_id, 'photo', character_id, text, filename)
            if said:
                # her text is already in the history — attach the photo as its own bubble
                save_message(uid, character_id, 'assistant', '📸', media_kind='photo', media_url=url)
            else:
                save_message(uid, character_id, 'assistant', cap, media_kind='photo', media_url=url)
            from services.chat_photo_allowance import free_chat_photos_left, use_free_chat_photo
            premium = is_premium(telegram_id)
            paid_note = None
            if telegram_id not in ADMIN_TELEGRAM_IDS and not fallback:
                if pay == 'undress_credit':
                    from services import undress_credits
                    undress_credits.spend(telegram_id)
                elif pay == 'undress_peaches':
                    # V3.138.0: «Раздеть» for peaches — 250 🍑, not the photo price.
                    from config import UNDRESS_PEACH_COST
                    spend_peaches(telegram_id, UNDRESS_PEACH_COST, paid_only=True)
                    paid_note = {'price': UNDRESS_PEACH_COST, 'left': get_paid_peaches(telegram_id)}
                # V3.61.5: a free photo of the day first, then peaches.
                elif free_chat_photos_left(uid, premium=premium) > 0:
                    use_free_chat_photo(uid, character_id)
                    if pooled:
                        from services.chat_photo_allowance import POOL_EVENT, note_today
                        note_today(uid, POOL_EVENT, character_id)
                else:
                    spend_peaches(telegram_id, CHAT_PHOTO_PEACH_COST, paid_only=True)
                    # V3.125.0: he sees what this photo cost and what is left,
                    # so the moment he runs short is never a surprise.
                    paid_note = {'price': CHAT_PHOTO_PEACH_COST, 'left': get_paid_peaches(telegram_id)}
            # V3.53.0: after this photo counts, tell the SPA if a gallery set
            # (50 photos of her) just completed so it can celebrate.
            from services.collection_service import gallery_set_progress, note_gallery_set
            return {'ok': True, 'reply': cap, 'photo_url': url,
                    'credits_left': get_photo_credits(telegram_id),
                    'free_photos_left': free_chat_photos_left(uid, premium=premium),
                    'set_completed': note_gallery_set(telegram_id, character_id),
                    'gallery': gallery_set_progress(telegram_id, character_id),
                    **({'paid_photo': paid_note} if paid_note else {}),
                    **(extra or {})}

        return await asyncio.to_thread(_deliver)

    if photo_scene:
        payload = await _photo_turn(photo_scene, photo_req, pay=photo_pay)
        if payload:
            return web.json_response(payload)
        return web.json_response(await asyncio.to_thread(
            _chat_photo_blocked, uid, character_id, 'failed', extra))
    try:
        answer = await anna_reply(
            telegram_id, user_info.get('first_name') or 'ты', text,
            language_code=user_info.get('language_code'), character_id=character_id,
        )
    except Exception:
        logger.exception('webapp chat reply failed user=%s character=%s', telegram_id, character_id)
        return web.json_response({'ok': False, 'error': 'reply'}, status=502)
    # V3.141.0: the scripted onboarding selfie — the pre-saved picture rides
    # with the prepared line. Consumed BEFORE the PHOTO_PROMISE branch: her
    # «лови фото» is the demo, not a paid render, and nothing is charged.
    from services import onboarding_demo
    if onboarding_demo.take_pending(telegram_id, character_id):
        def _demo_photo():
            url = onboarding_demo.photo_url_for(character_id)
            save_message(uid, character_id, 'assistant', '📸', media_kind='photo', media_url=url)
            return url
        demo_url = await asyncio.to_thread(_demo_photo)
        return web.json_response({'ok': True, 'reply': answer, 'photo_url': demo_url, **(extra or {})})
    # V3.60.9: she wrote «лови фотку 📸» on her own — the photo must really come.
    # V3.113.0: also a bare «держи 😏» / «лови 💋» right after he asked to see her.
    if PHOTO_PROMISE.search(answer or '') or (
            _HANDS_OVER.match(answer or '') and _ASKED_TO_SEE.search(text or '')):
        def _promise_gate():
            req = _selfie_from_dialog(uid, character_id, parse_photo_request('пришли селфи'))
            return req, _chat_photo_gate(telegram_id, character_id, 'selfie')
        req, block = await asyncio.to_thread(_promise_gate)
        if not block:
            payload = await _photo_turn('selfie', req, said=answer)
            if payload:
                return web.json_response(payload)
            block = 'failed'
        if block in ('peaches', 'premium', 'spicy', 'free_used', 'stage', 'adult'):
            # keep her words, add the honest «out of peaches» / «Premium» note + button
            # V3.113.0: «лови 😏» with the free photo already used went out with
            # nothing attached — now the honest note and her blurred card come too.
            note = CHAT_PHOTO_BLOCK_TEXT[block].format(price=CHAT_PHOTO_PEACH_COST)
            await asyncio.to_thread(save_message, uid, character_id, 'assistant', note)
            out = {'ok': True, 'reply': answer + '\n\n' + note, 'photo_block': block,
                   'photo_price': CHAT_PHOTO_PEACH_COST, **(extra or {})}
            if block in _LOCKED_CARD_REASONS:
                out['locked_tease'] = {'url': f'/webapp/locked/{character_id}.jpg'}
            return web.json_response(out)
        if block == 'failed':
            note = CHAT_PHOTO_BLOCK_TEXT['failed']
            await asyncio.to_thread(save_message, uid, character_id, 'assistant', note)
            return web.json_response({'ok': True, 'reply': answer + '\n\n' + note, **(extra or {})})
    payload = {'ok': True, 'reply': answer}
    # V3.140.0: the model sold the duo herself — reply() already flipped the
    # state; the app gets the guest pill and, without Premium, the blur teaser.
    from services import invite_funnel
    funnel_guest = invite_funnel.take_pending(telegram_id, character_id)
    if funnel_guest:
        from services import chat_guest_service as _funnel_cgs
        payload['guest'] = {'id': funnel_guest,
                            'name': _funnel_cgs.character_name(funnel_guest) or funnel_guest,
                            'photo': f'/webapp/photo/{funnel_guest}'}
        if telegram_id not in ADMIN_TELEGRAM_IDS and not is_premium(telegram_id):
            try:
                tease = await asyncio.to_thread(
                    _chat_duo_blocked, uid, telegram_id, character_id,
                    full_user_lang(telegram_id, user_info.get('language_code')), {})
                payload['duo_offer'] = True
                if tease.get('duo_tease'):
                    payload['duo_tease'] = tease['duo_tease']
            except Exception:
                logger.warning('duo teaser on funnel failed user=%s', telegram_id)
    # V3.88.0: the early locked photo — on his 3rd message to her (non-Premium)
    # her reply carries a blurred «только для тебя» card; a tap = Premium sheet.
    try:
        def _tease():
            if telegram_id in ADMIN_TELEGRAM_IDS or is_premium(telegram_id):
                return None
            from services import locked_tease
            if not locked_tease.bump(telegram_id, character_id):
                return None
            track_event(uid, 'paywall_view', metadata={'product': 'locked_tease', 'character_id': character_id})
            return {'url': f'/webapp/locked/{character_id}.jpg'}
        tease = await asyncio.to_thread(_tease)
        if tease:
            payload['locked_tease'] = tease
    except Exception:
        logger.exception('locked tease failed user=%s', telegram_id)
    # V3.90.0: intimacy is Premium-only — his explicit message gets a quiet
    # «🔥 Откровенно — с Premium» chip under her reply (once a day).
    if 'locked_tease' not in payload:
        try:
            from services import intimacy_gate
            if await asyncio.to_thread(intimacy_gate.should_offer, telegram_id, character_id, text):
                await asyncio.to_thread(track_event, uid, 'paywall_view',
                                        metadata={'product': 'sext_offer', 'character_id': character_id})
                payload['sext_offer'] = True
        except Exception:
            logger.warning('sext offer failed user=%s', telegram_id, exc_info=True)
    # V3.72.0: the circle hook — in a flirty moment (or when asked) she offers
    # a circle under her reply. Free to show; the render starts on a paid tap.
    try:
        offer = await asyncio.to_thread(_circle_offer, telegram_id, character_id, text, answer)
        if offer:
            payload['circle_offer'] = offer
    except Exception:
        logger.warning('circle offer failed user=%s', telegram_id, exc_info=True)
    voice_url = None
    # V3.139.0: owner ТЗ — in a duo chat the two lines are two messages, each
    # in her own voice. Without Premium the free taste stays ONE note a turn
    # (no new spend), so only Premium men hear both girls speak.
    from services.chat_service import duo_lines
    from services import chat_guest_service as cgs
    duo_map = await asyncio.to_thread(cgs.speakers, telegram_id, character_id)
    parts = duo_lines(answer) if duo_map else []
    if len(parts) > 1:
        multi = telegram_id in ADMIN_TELEGRAM_IDS or is_premium(telegram_id)
        bubbles = []
        for idx, (who, line) in enumerate(parts[:3]):
            entry = {'name': who, 'text': line}
            if idx == 0 or multi:
                cid = duo_map.get(who) or character_id
                url = await _webapp_reply_voice_url(telegram_id, cid, line)
                if url and url != 'offer':
                    entry['voice_url'] = url
                elif url == 'offer' and not bubbles:
                    voice_url = 'offer'
            bubbles.append(entry)
        payload['reply_parts'] = bubbles
    else:
        voice_url = await _webapp_reply_voice_url(telegram_id, character_id, answer)
    if voice_url == 'offer':
        if not any(k in payload for k in ('locked_tease', 'sext_offer')):
            payload['voice_offer'] = True  # V3.106.0: «🎙 слышать её голос всегда»
    elif voice_url:
        payload['voice_url'] = voice_url
    payload.update(extra or {})
    return web.json_response(payload)


def _circle_offer(telegram_id: int, character_id: str, text: str, answer: str) -> dict | None:
    """V3.72.0: which circle buttons go under her reply (see hot_circle_service)."""
    from services import hot_circle_service
    is_custom = is_custom_character(character_id)
    offer = hot_circle_service.offer_for(
        telegram_id, character_id, text, answer,
        is_custom=is_custom, adult_confirmed=is_adult_confirmed(telegram_id),
        level=0 if is_custom else get_relationship_level(telegram_id, character_id),
    )
    if not offer:
        return None
    return {'hot': bool(offer.get('hot')), 'circle_price': CIRCLE_PEACH_COST, 'hot_price': HOT_CIRCLE_PEACH_COST}


async def _webapp_api_chat_start(request: web.Request) -> web.Response:
    """V3.61.1: the first-open choice «📖 С сюжетом / 💬 Без сюжета». With a
    story she opens the chat with a ready scene (her action + first line):
    the author's «Первая сцена», the built-in OPENING_SCENES, or one written
    by the model from her persona. Without a story nothing is sent."""
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
    character_id = str(body.get('character_id', ''))[:64]
    mode = str(body.get('mode', 'plain'))
    if not character_id:
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    if is_custom_character(character_id):
        if not await asyncio.to_thread(get_custom_character_by_id, character_id):
            return web.json_response({'ok': False, 'error': 'unknown_character'}, status=400)
    elif not get_card(character_id):
        return web.json_response({'ok': False, 'error': 'unknown_character'}, status=400)
    if mode != 'story':
        return web.json_response({'ok': True, 'reply': None})

    def _prepare():
        uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
        from services.memory_service import get_recent_messages
        if get_recent_messages(uid, character_id, 1):
            return uid, None, None
        scene, persona = None, ''
        if is_custom_character(character_id):
            from services.custom_character_service import custom_character_params, custom_persona_context
            params, _name = custom_character_params(character_id)
            scene = str(params.get('opening') or '').strip() or None
            if not scene:
                persona = custom_persona_context(character_id)
        else:
            from services.character_card_service import get_opening_scene
            scene = get_opening_scene(character_id)
        return uid, scene, persona

    uid, scene, persona = await asyncio.to_thread(_prepare)
    if uid and scene is None and persona:
        try:
            from services.llm_provider_service import generate_text
            r = await generate_text([
                {'role': 'system', 'content': persona},
                {'role': 'user', 'content': (
                    'Напиши первое сообщение этого чата как живую строку в мессенджере: одной фразой скажи, что ты '
                    'сейчас делаешь и где (своими словами, без действий в *звёздочках* и без ремарок в скобках), '
                    'потом твоя первая реплика пользователю (1–2 предложения), живо и с интригой. '
                    'Без приветствия «привет», без описания внешности, без своего имени перед текстом.')},
            ], max_tokens=220, temperature=0.95, purpose='opening')
            from services.chat_service import plain_message
            scene = plain_message((r.text or '').strip()) or None
        except Exception:
            logger.warning('opening scene generation failed char=%s', character_id)
    # V3.117.0: the opening scenes are written in Russian — a Bengali or
    # Spanish user gets the scene in his own language.
    if uid and scene:
        try:
            from services import lang_guard
            _lang = await asyncio.to_thread(lang_guard.lang_for_push, uid, user_info.get('language_code'))
            if _lang != 'ru' and lang_guard.is_cyrillic_dominant(scene):
                from services.llm_provider_service import generate_text
                _ru_name, _own = lang_guard.LANG_NAMES.get(_lang, ('английском', 'English'))
                r = await generate_text([
                    {'role': 'system', 'content': (
                        f'Переведи первое сообщение девушки из чата на {_ru_name} язык ({_own}): живо и '
                        'разговорно, как написал бы носитель. Сохрани смысл и эмодзи, формат оставь '
                        'мессенджерным: без действий в *звёздочках* и без имени перед текстом. '
                        'Верни только перевод.')},
                    {'role': 'user', 'content': scene},
                ], max_tokens=320, temperature=0.4, purpose='opening')
                _tr = (r.text or '').strip()
                if _tr and lang_guard.reply_ok(_tr, _lang) and getattr(r, 'complete', True):
                    scene = _tr
        except Exception:
            logger.warning('opening scene translation failed char=%s', character_id)
    if uid and scene:
        await asyncio.to_thread(save_message, uid, character_id, 'assistant', scene)
    return web.json_response({'ok': True, 'reply': scene})


async def _webapp_api_chat_guest(request: web.Request) -> web.Response:
    """V3.61.2: «позвать в чат» — invite another girl into this chat
    (body {character_id, guest_id}) or send her away (guest_id empty)."""
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
    character_id = str(body.get('character_id', ''))[:64]
    guest_id = str(body.get('guest_id', '') or '')[:64]
    from services import chat_guest_service as cgs
    if not character_id or not get_card(character_id):
        return web.json_response({'ok': False, 'error': 'unknown_character'}, status=400)
    if guest_id:
        if await asyncio.to_thread(cgs.host_has_duo, character_id):
            return web.json_response({'ok': False, 'error': 'duo'}, status=400)
        if not await asyncio.to_thread(cgs.can_invite, telegram_id, character_id, guest_id):
            return web.json_response({'ok': False, 'error': 'unknown_guest'}, status=400)
    previous = await asyncio.to_thread(cgs.get_guest, telegram_id, character_id)
    await asyncio.to_thread(cgs.set_guest, telegram_id, character_id, guest_id or None)
    # V3.139.0: owner ТЗ (Задача 1) — this whole moment is his language, not
    # only ours: the entrance line, the note under it and the two girls' voices.
    lang = full_user_lang(telegram_id, user_info.get('language_code'))
    from services.lang_guard import name_line as _name_line
    from services.ui_lang import flow_text as _flow
    host_name = cgs.character_name(character_id) or 'Она'
    note = None
    if guest_id:
        guest_name = cgs.character_name(guest_id) or _flow(lang, 'guest_word')
        note = _flow(lang, 'guest_in', name=guest_name)
        try:
            from services.llm_provider_service import generate_text
            from services.chat_service import plain_message
            r = await generate_text([
                {'role': 'system', 'content': cgs.guest_prompt(host_name, guest_id, telegram_id)},
                {'role': 'user', 'content': (
                    f'Напиши, как {guest_name} заходит в чат. Сначала одна короткая реплика «{host_name}: …», '
                    f'потом одна «{guest_name}: …» пользователю, живо, с характером каждой. Коротко. '
                    f'Никаких действий в *звёздочках* и без ремарок в скобках — только текст реплик.'
                    + _name_line(lang))},
            ], max_tokens=220, temperature=0.95, purpose='guest_enter')
            text = plain_message((r.text or '').strip(), duo=True)
            if text and guest_name in text:
                note = text
        except Exception:
            logger.warning('guest entrance generation failed host=%s guest=%s', character_id, guest_id)
    elif previous:
        note = _flow(lang, 'guest_out', name=cgs.character_name(previous) or _flow(lang, 'guest_word'))
    if note:
        uid = await asyncio.to_thread(ensure_user, telegram_id, user_info.get('first_name') or '',
                                      language_code=user_info.get('language_code'))
        await asyncio.to_thread(save_message, uid, character_id, 'assistant', note)
    guest = ({'id': guest_id, 'name': cgs.character_name(guest_id) or guest_id,
              'photo': f'/webapp/photo/{guest_id}'} if guest_id else None)
    # V3.139.0: owner ТЗ (Фогель, Задача 5) — the duo is the hook. The moment a
    # man without Premium brings the second girl in, the two of him send him a
    # heavily blurred joint picture with the Premium button under it. Nothing
    # is rendered here: the picture comes from the ready blur pool.
    tease = None
    if guest_id and telegram_id not in ADMIN_TELEGRAM_IDS and not is_premium(telegram_id):
        try:
            uid = await asyncio.to_thread(ensure_user, telegram_id, user_info.get('first_name') or '',
                                          language_code=user_info.get('language_code'))
            tease = await asyncio.to_thread(
                _chat_duo_blocked, uid, telegram_id, character_id,
                full_user_lang(telegram_id, user_info.get('language_code')), {})
        except Exception:
            logger.warning('duo teaser on invite failed user=%s', telegram_id)
    return web.json_response({'ok': True, 'guest': guest, 'reply': note, 'duo': tease})


async def _webapp_api_chat_send(request: web.Request) -> web.Response:
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
    # V3.57.2: the gate is four PostgreSQL reads — off the event loop.
    gate = await asyncio.to_thread(_webapp_chat_gate, character_id, telegram_id)
    if gate is not None:
        return gate
    return await _webapp_chat_turn(telegram_id, user_info, character_id, text,
                                   extra=await _app_chat_missions(telegram_id, text=text))


async def _referral_qualify_check(telegram_id: int, text: str | None = None) -> None:
    """V3.80.0: pay a pending referral once the invited friend has written
    REFERRAL_QUALIFY_MESSAGES real messages, and tell both of them."""
    try:
        from services.referral_service import qualify_referral
        async with referral_user_lock(telegram_id):
            res = await asyncio.to_thread(qualify_referral, telegram_id, text)
    except Exception:
        logger.exception('referral qualify failed user=%s', telegram_id)
        return
    if not res:
        return
    try:
        await bot.send_message(
            res['referrer_telegram_id'],
            f'🎉 твой друг разговорился с ней — держи +{res["referrer_credits"]} 🍑 за приглашение! '
            'другу тоже начислено. зови ещё 😉')
    except Exception:
        logger.info('referral notify referrer failed id=%s', res.get('referrer_telegram_id'))
    try:
        await bot.send_message(
            telegram_id,
            f'🎁 бонус за приглашение: +{res["invitee_credits"]} 🍑 тебе и столько же другу, который тебя позвал.')
    except Exception:
        logger.info('referral notify invitee failed id=%s', telegram_id)


async def _app_chat_missions(telegram_id: int, voice: bool = False, text: str | None = None) -> dict:
    """V3.66.0: run the streak / first-message / voice mission hooks for an
    app chat turn; a fresh unlock rides back so the SPA can say «забери 🍑»."""
    asyncio.create_task(_referral_qualify_check(telegram_id, text))
    try:
        from services.gamification_service import note_app_chat_message, MISSION_PEACHES, ACHIEVEMENTS, DAILY_MISSIONS
        fresh = await asyncio.to_thread(note_app_chat_message, telegram_id, voice, text)
    except Exception:
        logger.exception('app chat mission hooks failed user=%s', telegram_id)
        return {}
    if not fresh:
        return {}
    # V3.68.0: only missions that pay (today's daily ones) ping the chat.
    done = [{'key': k, 'name': DAILY_MISSIONS[k][0], 'peaches': DAILY_MISSIONS[k][4]}
            for k in fresh if k in DAILY_MISSIONS]
    done += [{'key': k, 'name': ACHIEVEMENTS[k][0], 'peaches': MISSION_PEACHES[k]}
             for k in fresh if MISSION_PEACHES.get(k)]
    return {'missions_done': done} if done else {}


async def _webapp_api_chat_speak(request: web.Request) -> web.Response:
    """V3.63.5: tap her message in the app chat → «🔊 Озвучить» → she says it
    in her own voice. A Premium perk (admins bypass); non-Premium gets 403
    premium_required so the SPA opens the Premium quick-buy sheet."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    character_id = str(body.get('character_id', ''))[:64]
    text = str(body.get('text', ''))
    clean = _tts_text(text)
    if not character_id or not clean.strip():
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)

    def _gate():
        # V3.97.0: 54 people a week tapped «🔊» without Premium and hit a wall
        # before ever hearing her — for 34 of them it was the last thing they
        # saw. Now SPEAK_FREE_PER_DAY listens a day are free; the wall comes
        # after them, when he already knows what her voice is worth.
        from services import chat_photo_allowance
        from config import SPEAK_FREE_PER_DAY
        user = get_user(telegram_id)
        style = (user.voice_style if user else None) or 'nova'
        if telegram_id in ADMIN_TELEGRAM_IDS:
            return style, None
        if is_premium(telegram_id):
            # V3.124.0: the trial's voice total covers «🔊 Озвучить» too.
            return (style, None) if _trial_voice_ok(telegram_id) else (None, -1)
        uid = ensure_user(telegram_id)
        left = SPEAK_FREE_PER_DAY - chat_photo_allowance.count_today(uid, 'speak_free')
        if left > 0:
            return style, left - 1
        return None, 0

    voice_style, free_left = await asyncio.to_thread(_gate)
    if not voice_style and free_left == -1:
        # V3.124.0: he has Premium, its voice-note total is spent.
        return web.json_response({'ok': False, 'error': 'plan_voice_out'}, status=403)
    if not voice_style:
        track_event(ensure_user(telegram_id), 'speak_premium_wall')
        return web.json_response({'ok': False, 'error': 'premium_required'}, status=403)
    try:
        audio = await synthesize_bytes(clean, voice_style, character_id=character_id)
        filename = await asyncio.to_thread(
            webapp_service.save_chat_media, telegram_id, audio, 'ogg', 'audio/ogg')
    except Exception:
        logger.warning('webapp speak failed user=%s', telegram_id, exc_info=True)
        return web.json_response({'ok': False, 'error': 'tts_failed'}, status=502)
    track_event(ensure_user(telegram_id), 'speak_message', metadata={'character_id': character_id})
    payload = {'ok': True, 'url': f'/webapp/media/{filename}'}
    if free_left is not None:
        from services import chat_photo_allowance
        await asyncio.to_thread(chat_photo_allowance.note_today, ensure_user(telegram_id),
                                'speak_free', character_id)
        payload['free_left'] = free_left
    return web.json_response(payload, headers={'Cache-Control': 'no-store'})


async def _webapp_api_chat_voice(request: web.Request) -> web.Response:
    """V3.57.0: a voice message from the Mini App — the mic recording arrives as
    base64, Whisper transcribes it, and the turn continues through the exact
    text pipeline. user_text goes back so the SPA can show what was heard."""
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
    audio_b64 = str(body.get('audio', ''))
    if not character_id or not audio_b64:
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    # V3.57.2: the gate is four PostgreSQL reads — off the event loop.
    gate = await asyncio.to_thread(_webapp_chat_gate, character_id, telegram_id)
    if gate is not None:
        return gate
    try:
        data = base64.b64decode(audio_b64)
    except Exception:
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    if not data or len(data) > 5 * 1024 * 1024:
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    try:
        heard = await transcribe(io.BytesIO(data))
    except Exception:
        logger.exception('webapp stt failed user=%s', telegram_id)
        return web.json_response({'ok': False, 'error': 'stt'}, status=502)
    heard = (heard or '').strip()[:4000]
    if not heard:
        return web.json_response({'ok': False, 'error': 'no_speech'}, status=400)
    return await _webapp_chat_turn(telegram_id, user_info, character_id, heard,
                                   extra={'user_text': heard, **(await _app_chat_missions(telegram_id, voice=True, text=heard))})


# ── V3.115.0: «📞 Позвонить» (services/voice_call.py) ──────────────────────

def _call_gate(character_id: str, telegram_id: int):
    """Who may call her: the same character access and consent as the chat,
    but not the daily message limit — calls have their own minutes."""
    if is_custom_character(character_id):
        if not get_custom_character_by_id(character_id):
            return 'unknown_character'
        if _custom_premium_gate_block(character_id, telegram_id):
            return 'premium_required'
    else:
        card = get_card(character_id)
        if not card or card.status not in ('active', 'premium'):
            return 'locked'
        if card.status == 'premium' and not is_premium(telegram_id):
            return 'premium_required'
    if not has_accepted(telegram_id):
        return 'consent'
    return None


def _call_auth(request: web.Request):
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return None, None
    user_info = webapp_service.init_data_user(pairs)
    return user_info.get('id'), user_info


def _call_state(telegram_id: int, user_info: dict, character_id: str, asked: str = ''):
    from services import voice_call
    admin = telegram_id in ADMIN_TELEGRAM_IDS
    err = _call_gate(character_id, telegram_id)
    uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
    mode = voice_call.mode_for(is_premium(telegram_id), admin, asked)
    return uid, err, mode, voice_call.seconds_left(uid, mode, admin)


async def _webapp_api_call_info(request: web.Request) -> web.Response:
    """Before the call screen opens: which call he gets and how much is left."""
    from services import voice_call
    telegram_id, user_info = _call_auth(request)
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    character_id = str(request.query.get('character_id', ''))[:64]
    if not voice_call.ENABLED or not character_id:
        return web.json_response({'ok': False, 'error': 'disabled'}, status=400)
    uid, err, mode, left = await asyncio.to_thread(
        _call_state, telegram_id, user_info, character_id, request.query.get('mode', ''))
    if err:
        return web.json_response({'ok': False, 'error': err}, status=403)
    from config import GEMINI_API_KEY
    if mode == 'live' and not (voice_call.LIVE_ENABLED and GEMINI_API_KEY):
        return web.json_response({'ok': False, 'error': 'premium_required', 'mode': mode}, status=403)
    await asyncio.to_thread(track_event, uid, 'call_open',
                            metadata={'character_id': character_id, 'mode': mode, 'left': left})
    return web.json_response({
        'ok': True, 'mode': mode, 'seconds_left': left, 'admin': telegram_id in ADMIN_TELEGRAM_IDS,
        'premium_minutes': voice_call.PREMIUM_SECONDS_PER_DAY // 60,
        'free_minutes': round(voice_call.FREE_SECONDS_PER_DAY / 60, 1),
        # V3.124.0: the trial's call minutes are a total, not daily.
        'trial': mode == 'premium' and await asyncio.to_thread(_on_trial, telegram_id),
        'plan_out': mode == 'premium' and await asyncio.to_thread(_plan_calls_out, uid, telegram_id),
    }, headers={'Cache-Control': 'no-store'})


async def _webapp_api_call_turn(request: web.Request) -> web.Response:
    """A Premium call turn: his recorded phrase (or the pick-up when hello is
    set) → the chat pipeline with a phone direction → her line in her voice."""
    from services import voice_call
    telegram_id, user_info = _call_auth(request)
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    from services import spend_service
    spend_service.set_spend_user(telegram_id)
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    character_id = str(body.get('character_id', ''))[:64]
    call_id = str(body.get('call_id', ''))[:64]
    hello = bool(body.get('hello'))
    audio_b64 = str(body.get('audio', '') or '')
    if not voice_call.ENABLED or not character_id or not call_id or (not hello and not audio_b64):
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    uid, err, mode, left = await asyncio.to_thread(
        _call_state, telegram_id, user_info, character_id, str(body.get('mode', '')))
    if err:
        return web.json_response({'ok': False, 'error': err}, status=403)
    if mode != 'premium':
        return web.json_response({'ok': False, 'error': 'premium_required'}, status=403)
    if left <= 0:
        return web.json_response({'ok': False, 'error': 'limit', 'seconds_left': 0}, status=429)
    spent = voice_call.premium_turn_seconds(call_id)
    if spent:
        await asyncio.to_thread(voice_call.add_seconds, uid, 'premium', spent, character_id)
        left = max(0, left - int(spent))
    heard = ''
    if hello:
        # V3.115.1: an instant «алло» in her voice, cached per girl.
        lang = 'en' if (user_info.get('language_code') or '').lower().startswith('en') else 'ru'
        i, line = voice_call.hello_line(lang, int(_time.time()) // 7)
        audio = voice_call.hello_cached(character_id, lang, i)
        if audio is None:
            try:
                audio = await synthesize_bytes(line, None, character_id=character_id)
                voice_call.hello_store(character_id, lang, i, audio)
            except Exception:
                logger.warning('call hello tts failed user=%s', telegram_id, exc_info=True)
                return web.json_response({'ok': True, 'heard': '', 'text': line, 'audio_url': None,
                                          'seconds_left': left})
        filename = await asyncio.to_thread(webapp_service.save_chat_media, telegram_id, audio, 'ogg', 'audio/ogg')
        await asyncio.to_thread(track_event, uid, 'call_turn',
                                metadata={'character_id': character_id, 'mode': 'premium', 'hello': True})
        return web.json_response({'ok': True, 'heard': '', 'text': line,
                                  'audio_url': f'/webapp/media/{filename}', 'seconds_left': left},
                                 headers={'Cache-Control': 'no-store'})
    else:
        try:
            data = base64.b64decode(audio_b64)
        except Exception:
            return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
        if not data or len(data) > 5 * 1024 * 1024:
            return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
        try:
            heard = ((await transcribe(io.BytesIO(data))) or '').strip()[:2000]
        except Exception:
            logger.warning('call stt failed user=%s', telegram_id, exc_info=True)
            return web.json_response({'ok': False, 'error': 'stt'}, status=502)
        if not heard:
            return web.json_response({'ok': False, 'error': 'no_speech'}, status=400)
        text, scene = heard, voice_call.CALL_SCENE
    try:
        answer = await anna_reply(telegram_id, user_info.get('first_name') or 'ты', text,
                                  language_code=user_info.get('language_code'),
                                  character_id=character_id, scene=scene)
    except Exception:
        logger.exception('call reply failed user=%s character=%s', telegram_id, character_id)
        return web.json_response({'ok': False, 'error': 'reply'}, status=502)
    from services import invite_funnel
    said = voice_call.spoken(invite_funnel.strip_tag(answer)) or '…'
    invite_funnel.take_pending(telegram_id, character_id)
    # V3.115.1: the first phrase is voiced alone so she starts speaking sooner;
    # the app asks /call/say for the rest while the first part plays.
    parts = voice_call.split_for_speech(said) or [said]
    try:
        audio = await synthesize_bytes(parts[0], None, character_id=character_id)
        filename = await asyncio.to_thread(webapp_service.save_chat_media, telegram_id, audio, 'ogg', 'audio/ogg')
    except Exception:
        logger.warning('call tts failed user=%s', telegram_id, exc_info=True)
        return web.json_response({'ok': True, 'heard': heard, 'text': said, 'audio_url': None,
                                  'seconds_left': left})
    await asyncio.to_thread(track_event, uid, 'call_turn',
                            metadata={'character_id': character_id, 'mode': 'premium', 'hello': hello})
    return web.json_response({'ok': True, 'heard': heard, 'text': said, 'rest': parts[1:],
                              'audio_url': f'/webapp/media/{filename}', 'seconds_left': left},
                             headers={'Cache-Control': 'no-store'})


async def _webapp_api_call_say(request: web.Request) -> web.Response:
    """V3.115.1: the rest of her Premium-call answer in her voice."""
    from services import voice_call
    telegram_id, user_info = _call_auth(request)
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    character_id = str(body.get('character_id', ''))[:64]
    text = voice_call.spoken(str(body.get('text', '') or ''))[:600]
    if not character_id or not text:
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    uid, err, mode, left = await asyncio.to_thread(
        _call_state, telegram_id, user_info, character_id, str(body.get('mode', '')))
    if err or mode != 'premium':
        return web.json_response({'ok': False, 'error': err or 'premium_required'}, status=403)
    try:
        audio = await synthesize_bytes(text, None, character_id=character_id)
        filename = await asyncio.to_thread(webapp_service.save_chat_media, telegram_id, audio, 'ogg', 'audio/ogg')
    except Exception:
        logger.warning('call say tts failed user=%s', telegram_id, exc_info=True)
        return web.json_response({'ok': False, 'error': 'tts_failed'}, status=502)
    return web.json_response({'ok': True, 'audio_url': f'/webapp/media/{filename}'},
                             headers={'Cache-Control': 'no-store'})


async def _webapp_ws_call(request: web.Request) -> web.StreamResponse:
    """The live call (without Premium): the app streams his mic as PCM16 16 kHz
    and gets her voice back as PCM16 24 kHz through Gemini Live."""
    from services import voice_call
    from services.voice_service import gemini_voice_for
    from config import GEMINI_API_KEY
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=1024 * 1024)
    await ws.prepare(request)
    telegram_id, user_info = _call_auth(request)
    character_id = str(request.query.get('character_id', ''))[:64]
    if not telegram_id or not character_id:
        await ws.send_json({'type': 'error', 'error': 'auth'})
        await ws.close()
        return ws
    uid, err, mode, left = await asyncio.to_thread(
        _call_state, telegram_id, user_info, character_id, request.query.get('mode', ''))
    if not err and mode != 'live':
        err = 'premium_call'
    if not err and not (voice_call.ENABLED and voice_call.LIVE_ENABLED and GEMINI_API_KEY):
        err = 'disabled'
    if not err and left <= 0:
        err = 'limit'
    if err:
        await ws.send_json({'type': 'error', 'error': err})
        await ws.close()
        return ws

    def _prompt():
        from services.memory_service import get_memories, get_recent_messages
        from services import lang_guard
        from services.character_service import get_character
        try:
            from services.custom_character_service import custom_base_character
            character = custom_base_character(character_id) or get_character(character_id)
        except Exception:
            character = get_character(character_id)
        memories = [m.content for m in get_memories(uid, character_id, 14)]
        history = [(m.role, m.content) for m in get_recent_messages(uid, character_id, 12)]
        # V3.117.0: his language, not only RU/EN
        lang = lang_guard.detect_lang(
            next((c for r, c in reversed(history) if r == 'user'), ''), user_info.get('language_code'),
            [c for r, c in history if r == 'user'], lang_guard.stored_lang(uid))
        english = lang != 'ru'
        return voice_call.live_system_prompt(character, user_info.get('first_name') or '', memories,
                                             history, english=english, lang=lang), english

    system_prompt, english = await asyncio.to_thread(_prompt)
    try:
        seconds, transcript, reason = await voice_call.live_bridge(
            ws, api_key=GEMINI_API_KEY, voice_name=gemini_voice_for(character_id),
            system_prompt=system_prompt, seconds_allowed=left, english=english)
    except Exception as exc:
        logger.warning('live call failed user=%s: %s', telegram_id, exc)
        await asyncio.to_thread(track_event, uid, 'call_failed',
                                metadata={'character_id': character_id, 'mode': 'live', 'error': str(exc)[:200]})
        if not ws.closed:
            await ws.send_json({'type': 'error', 'error': 'live_failed'})
            await ws.close()
        return ws

    def _store():
        voice_call.add_seconds(uid, 'live', seconds, character_id)
        mins = int(seconds // 60)
        save_message(uid, character_id, 'assistant', f'📞 Звонок · {mins}:{int(seconds % 60):02d}')
        for role, line in transcript[-40:]:
            save_message(uid, character_id, role, line)
        track_event(uid, 'call_end', value=voice_call.live_cost_usd(seconds),
                    metadata={'character_id': character_id, 'mode': 'live', 'seconds': round(seconds, 1),
                              'reason': reason, 'lines': len(transcript)})

    if seconds >= 1:
        await asyncio.to_thread(_store)
    if not ws.closed:
        try:
            await ws.send_json({'type': 'end', 'reason': reason, 'seconds': round(seconds)})
        except Exception:
            pass
        await ws.close()
    return ws


async def _webapp_api_call_end(request: web.Request) -> web.Response:
    """A Premium call ended: count the tail since the last turn."""
    from services import voice_call
    telegram_id, user_info = _call_auth(request)
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    character_id = str(body.get('character_id', ''))[:64]
    call_id = str(body.get('call_id', ''))[:64]
    if not character_id or not call_id:
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    spent = voice_call.premium_turn_seconds(call_id)
    uid = await asyncio.to_thread(ensure_user, telegram_id)
    if spent:
        await asyncio.to_thread(voice_call.add_seconds, uid, 'premium', spent, character_id)
    await asyncio.to_thread(track_event, uid, 'call_end',
                            metadata={'character_id': character_id, 'mode': 'premium',
                                      'seconds': round(float(body.get('seconds') or 0), 1)})
    return web.json_response({'ok': True})


async def _webapp_api_chat_photo(request: web.Request) -> web.Response:
    """V3.57.0: the user sends a photo (a selfie, for example) in the app chat —
    the vision model looks at it and she reacts in character (compliments him).
    Same pipeline as the bot's V3.19.0 photo reaction; the picture is stored as
    ordinary chat media so the dialog keeps its context."""
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
    image_b64 = str(body.get('image', ''))
    mime = str(body.get('mime', 'image/jpeg'))
    # V3.96.0: the text he typed before tapping 📎 rides as the caption.
    caption = str(body.get('caption', '') or '').strip()[:300]
    if not character_id or not image_b64 or mime not in ('image/jpeg', 'image/png', 'image/webp'):
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    # V3.57.2: the gate is four PostgreSQL reads — off the event loop.
    gate = await asyncio.to_thread(_webapp_chat_gate, character_id, telegram_id)
    if gate is not None:
        return gate
    if not PHOTO_REACTION_ENABLED:
        return web.json_response({'ok': False, 'error': 'disabled'}, status=400)
    now = _time.time()
    if now - _photo_reaction_ts.get(telegram_id, 0) < PHOTO_REACTION_COOLDOWN_SECONDS:
        return web.json_response({'ok': False, 'error': 'cooldown'}, status=429)
    try:
        data = base64.b64decode(image_b64)
    except Exception:
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    if len(data) < 100:
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    if len(image_b64) > MAX_BASE64_BYTES:
        return web.json_response({'ok': False, 'error': 'too_big'}, status=413)
    _photo_reaction_ts[telegram_id] = now
    try:
        reaction = await react_to_photo(image_b64, mime_type=mime, caption=caption or None, character_id=character_id)
    except Exception:
        logger.exception('webapp photo reaction failed user=%s', telegram_id)
        reaction = None
    if not reaction:
        return web.json_response({'ok': False, 'error': 'reply'}, status=502)
    # V3.57.2: the user upsert, the media write and the two dialog rows are
    # disk + PostgreSQL work; they go to a worker thread once the vision
    # answer is back.
    def _store():
        uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
        filename = webapp_service.save_chat_media(telegram_id, data, 'jpg', mime)
        url = f'/webapp/media/{filename}'
        save_message(uid, character_id, 'user', caption or '📷', media_kind='photo', media_url=url)
        save_message(uid, character_id, 'assistant', reaction)
        track_event(uid, 'photo_reaction_sent', metadata={'character_id': character_id, 'source': 'webapp'})
        return url

    url = await asyncio.to_thread(_store)
    return web.json_response({'ok': True, 'reply': reaction, 'user_photo_url': url})


def _with_marital_ring(prompt: str, telegram_id: int, character_id: str) -> str:
    """V3.59.7: intimate shots carry only the always-on detail (the ring) — no
    hoodie or husband's shirt in a boudoir frame."""
    try:
        from services.photo_service import marital_photo_detail
        detail = marital_photo_detail(telegram_id, character_id, allow_sometimes=False)
    except Exception:
        detail = ''
    return prompt + (f' STORY DETAIL: {detail}; small and natural, never changes her face or body.' if detail else '')


async def _webapp_api_chat_branch(request: web.Request) -> web.Response:
    """V3.62.0: his answer to her level-3 question — the romance or the
    passion path with this girl. Chosen once; she answers in the chat."""
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
    character_id = str(body.get('character_id', ''))[:64]
    branch = str(body.get('branch', ''))
    from services.relationship_engine import BRANCHES
    if not character_id or branch not in BRANCHES:
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)

    def _choose():
        from services import branch_service
        from services.chat_guest_service import guest_marital
        from services.relationship_engine import TAKEN_STATUSES
        uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
        reply = branch_service.choose(uid, character_id, branch,
                                      taken=guest_marital(telegram_id, character_id) in TAKEN_STATUSES)
        if reply:
            track_event(uid, 'relationship_branch_chosen', metadata={'branch': branch}, character_id=character_id)
        return reply

    reply = await asyncio.to_thread(_choose)
    if not reply:
        return web.json_response({'ok': False, 'error': 'already_chosen'}, status=409)
    from services.branch_service import FORK_OPTIONS
    return web.json_response({'ok': True, 'branch': branch, 'reply': reply, 'answer': FORK_OPTIONS[branch]})


async def _webapp_api_chat_level(request: web.Request) -> web.Response:
    """V3.60.9: the chat header's level panel — level, bond, bars toward the
    next level and how many messages / days are still missing."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    character_id = str(request.query.get('character_id', ''))[:64]
    if not telegram_id or not character_id:
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)

    def _snap():
        from services.relationship_engine import get_state, level_snapshot
        from services.test_mode import get_stage as get_test_stage
        with SessionLocal() as session:
            user = session.scalar(select(User).where(User.telegram_id == str(telegram_id)))
            row = get_state(session, user.id, character_id) if user else None
            premium = telegram_id in ADMIN_TELEGRAM_IDS or is_premium(telegram_id)
            from services.chat_guest_service import guest_marital
            from services.relationship_engine import TAKEN_STATUSES
            taken = guest_marital(telegram_id, character_id) in TAKEN_STATUSES
            snap = level_snapshot(session, row, get_test_stage(telegram_id, character_id), premium=premium, taken=taken)
            # V3.83.0: Premium picks any level 1-10 on the level panel.
            from services.test_mode import picked_stage
            snap['can_pick'] = bool(premium)
            snap['picked'] = bool(picked_stage(telegram_id, character_id))
            return snap

    try:
        snap = await asyncio.to_thread(_snap)
    except Exception:
        logger.exception('webapp chat level failed user=%s', telegram_id)
        return web.json_response({'ok': False, 'error': 'level'}, status=500)
    return web.json_response({'ok': True, **snap})


async def _webapp_api_chat_level_pick(request: web.Request) -> web.Response:
    """V3.83.0: a Premium user picks any level 1-10 for this girl (level 0 =
    back to the real progress). Levels 4-10 also pick the path."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    character_id = str(body.get('character_id', ''))[:64]
    branch = str(body.get('branch') or '')
    try:
        level = int(body.get('level', -1))
    except (TypeError, ValueError):
        level = -1
    from services.test_mode import STAGES as _PICK_STAGES, pick_stage
    if not telegram_id or not character_id or not 0 <= level <= len(_PICK_STAGES):
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    if telegram_id not in ADMIN_TELEGRAM_IDS and not is_premium(telegram_id):
        return web.json_response({'ok': False, 'error': 'premium'}, status=403)

    def _save():
        uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
        if level == 0:
            pick_stage(telegram_id, character_id, None)
        else:
            if level >= 4 and branch in ('romance', 'passion'):
                from services.relationship_engine import force_branch
                force_branch(uid, character_id, branch)
            pick_stage(telegram_id, character_id, _PICK_STAGES[level - 1])
        track_event(uid, 'level_pick', value=float(level), metadata={'branch': branch}, character_id=character_id)

    try:
        await asyncio.to_thread(_save)
    except Exception:
        logger.exception('level pick failed user=%s', telegram_id)
        return web.json_response({'ok': False, 'error': 'level'}, status=500)
    return web.json_response({'ok': True})


async def _webapp_api_chat_marital(request: web.Request) -> web.Response:
    # V3.59.5: the user picks her relationship status (замужем / есть парень /
    # в разводе / …) on her page — any girl, built-in or custom. Stored per
    # user<->character; 'default' clears it. Bends the chat voice.
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
    status = str(body.get('status', '')).strip()
    from services.custom_character_service import RELATIONSHIP_STORY
    from services.marital_arcs import ARC_ONLY_STATUSES
    # V3.134.0: «с тобой» / «твоя жена» are earned in her story, never bought here.
    if not character_id or status in ARC_ONLY_STATUSES or (status != 'default' and status not in RELATIONSHIP_STORY):
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)

    left_him: dict = {}
    next_price: dict = {}

    def _save():
        if is_custom_character(character_id):
            if not get_custom_character_by_id(character_id):
                return 'unknown_character'
        elif not get_card(character_id):
            return 'unknown_character'
        if not has_accepted(telegram_id):
            return 'consent'
        uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
        from models.relationship_models import UserCharacterRelationship
        new_value = None if status == 'default' else status
        with SessionLocal() as session:
            row = session.scalar(select(UserCharacterRelationship).where(
                UserCharacterRelationship.user_id == uid,
                UserCharacterRelationship.character_id == character_id,
            ))
            current = (row.marital_status if row is not None else None) or \
                webapp_service._default_marital(character_id, is_custom_character(character_id))
            if status == current or (status == 'default' and (row is None or row.marital_status is None)):
                return None  # same pick again: free, nothing changes
            # V3.59.6: every change costs peaches (admin tests free) — a paid
            # tweak instead of endless tapping.
            # V3.146.0: the FIRST change is free for everyone (existing users
            # included) — the flag burns only on a real change, in this very
            # commit, never when the spend below refuses, and never while the
            # change costs nothing at all (MARITAL_CHANGE_PEACHES=0).
            owner = session.get(User, uid)
            free_change = MARITAL_CHANGE_PEACHES > 0 and webapp_service.marital_price(owner) == 0
            if MARITAL_CHANGE_PEACHES and not free_change and telegram_id not in ADMIN_TELEGRAM_IDS:
                if not spend_peaches(telegram_id, MARITAL_CHANGE_PEACHES):
                    return 'peaches'
            if row is None:
                row = UserCharacterRelationship(user_id=uid, character_id=character_id, path_axis=0.0)
                session.add(row)
            if free_change and owner is not None:
                owner.marital_change_free_used = True
            row.marital_status = new_value
            # V3.61.9: on levels 7-8 «замужем → свободна» is a scene, not a
            # silent flip: she left him for the user and arrives with a suitcase.
            from services.relationship_engine import TAKEN_STATUSES, PREMIUM_STAGES
            from services.test_mode import get_stage as _test_stage
            _eff_new = new_value or webapp_service._default_marital(character_id, is_custom_character(character_id))
            if current in TAKEN_STATUSES and _eff_new in ('mar_single', 'mar_divorced') \
                    and (_test_stage(telegram_id, character_id) or row.stage) in PREMIUM_STAGES:
                left_him['uid'] = uid
            # V3.59.7: the switch becomes part of her story — a memory she can
            # bring up once («я ушла от мужа…») instead of silently flipping.
            _labels = {'mar_single': 'свободна', 'mar_boyfriend': 'есть парень', 'mar_married': 'замужем',
                       'mar_divorced': 'в разводе', 'mar_open': 'в свободных отношениях',
                       'mar_with_you': 'вместе с ним', 'mar_wife': 'его жена'}
            new_eff = new_value or webapp_service._default_marital(character_id, is_custom_character(character_id))
            from models.app_models import Memory as _Memory
            mem = session.scalar(select(_Memory).where(
                _Memory.user_id == uid, _Memory.character_id == character_id, _Memory.memory_key == 'marital:change'))
            text_mem = (f'Недавно твоё семейное положение изменилось: раньше ты была «{_labels.get(current, current)}», '
                        f'теперь — «{_labels.get(new_eff, new_eff)}». Можешь один раз естественно рассказать, '
                        'как так вышло, и дальше жить уже в новом положении.')
            if mem is None:
                session.add(_Memory(user_id=uid, character_id=character_id, memory_key='marital:change',
                                    content=text_mem, memory_type='story', confidence=1.0, importance=0.8))
            else:
                mem.content = text_mem
            session.commit()
            # V3.146.0: the price of his NEXT change, so the app repaints the
            # label from «free» to 500 🍑 right after the free one is burned.
            next_price['value'] = webapp_service.marital_price(owner)
        track_event(uid, 'webapp_marital', metadata={'character_id': character_id, 'status': status})
        return None

    try:
        blocked = await asyncio.to_thread(_save)
    except Exception:
        logger.exception('marital save failed user=%s character=%s', telegram_id, character_id)
        return web.json_response({'ok': False, 'error': 'save'}, status=500)
    if blocked == 'peaches':
        return web.json_response({'ok': False, 'error': 'peaches', 'price': MARITAL_CHANGE_PEACHES,
                                  'balance': get_photo_credits(telegram_id)}, status=402)
    if blocked:
        return web.json_response({'ok': False, 'error': blocked}, status=400 if blocked == 'unknown_character' else 403)
    if left_him:
        asyncio.create_task(_left_him_scene(telegram_id, character_id, left_him['uid']))
    return web.json_response({'ok': True, 'status': None if status == 'default' else status,
                              'balance': get_photo_credits(telegram_id), 'left_him': bool(left_him),
                              # Nothing really changed (same pick, custom girl) →
                              # no price back, or the app would repaint «free»
                              # into 500 🍑 while his free change is still waiting.
                              **({'marital_price': next_price['value']} if next_price else {})})


async def _webapp_api_marital_arc(request: web.Request) -> web.Response:
    """V3.134.0: her marital story for the status he picked — steps and locks."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    character_id = str(request.query.get('character_id', ''))[:64]
    lang = 'en' if request.query.get('lang') == 'en' else 'ru'
    if not telegram_id or not character_id:
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    from services import marital_arcs

    def _get():
        status, level, premium, adult = _sync_marital_ctx(telegram_id, character_id)
        return {'status': status, 'level': level,
                **marital_arcs.public(telegram_id, character_id, status, level, premium, adult, lang)}

    try:
        data = await asyncio.to_thread(_get)
    except Exception:
        logger.exception('marital arc failed user=%s', telegram_id)
        return web.json_response({'ok': False, 'error': 'arc'}, status=500)
    return web.json_response({'ok': True, **data}, headers={'Cache-Control': 'no-store'})


def _sync_marital_ctx(telegram_id: int, character_id: str):
    from services.chat_guest_service import guest_marital
    status = guest_marital(telegram_id, character_id)
    level = int(webapp_service._batch_rel_levels(telegram_id, [character_id]).get(character_id, 1) or 1)
    premium = telegram_id in ADMIN_TELEGRAM_IDS or is_premium(telegram_id)
    return status, level, premium, bool(is_adult_confirmed(telegram_id))


async def _webapp_api_marital_arc_step(request: web.Request) -> web.Response:
    """V3.134.0: he opens the next step of her story. Her line lands in the
    chat at once, a key step's photo follows when it renders; a finale step
    moves her status («с тобой» / «твоя жена»). The proposal costs a ring."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    character_id = str(body.get('character_id', ''))[:64]
    lang = 'en' if body.get('lang') == 'en' else 'ru'
    try:
        idx = int(body.get('step', -1))
    except (TypeError, ValueError):
        idx = -1
    if not telegram_id or not character_id:
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    from services import marital_arcs

    def _apply():
        if is_custom_character(character_id):
            if not get_custom_character_by_id(character_id):
                return 'unknown_character'
        else:
            card = get_card(character_id)
            if not card or card.status not in ('active', 'premium'):
                return 'locked'
            if card.status == 'premium' and telegram_id not in ADMIN_TELEGRAM_IDS and not is_premium(telegram_id):
                return 'premium_required'
        if not has_accepted(telegram_id):
            return 'consent'
        status, level, premium, adult = _sync_marital_ctx(telegram_id, character_id)
        arc = marital_arcs.arc_for(status)
        if not arc:
            return 'no_arc'
        item = marital_arcs.progress(telegram_id, character_id)
        done = set(item['arcs'].get(arc.key, []))
        why = marital_arcs.check_step(arc, idx, done, level, premium, adult,
                                      wait=telegram_id not in ADMIN_TELEGRAM_IDS and marital_arcs.waiting(item, arc))
        if why:
            return why
        step = arc.steps[idx]
        if step.ring and telegram_id not in ADMIN_TELEGRAM_IDS and not spend_peaches(telegram_id, marital_arcs.RING_PEACHES):
            return 'peaches'
        uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
        try:
            from services import storylines as _sl
            from services import scenario_cards as _sc
            _sl.stop(telegram_id, character_id)
            _sc.stop(telegram_id, character_id)
        except Exception:
            pass
        marital_arcs.start(telegram_id, character_id, arc, idx)
        save_message(uid, character_id, 'assistant', marital_arcs.opening(step, character_id, lang))
        if step.finish and arc.finish_status:
            from models.relationship_models import UserCharacterRelationship
            with SessionLocal() as session:
                row = session.scalar(select(UserCharacterRelationship).where(
                    UserCharacterRelationship.user_id == uid, UserCharacterRelationship.character_id == character_id))
                if row is None:
                    row = UserCharacterRelationship(user_id=uid, character_id=character_id, path_axis=0.0)
                    session.add(row)
                row.marital_status = arc.finish_status
                session.commit()
        track_event(uid, 'marital_arc_step', character_id=character_id,
                    metadata={'arc': arc.key, 'step': idx, 'ring': step.ring})
        return {'uid': uid, 'photo': step.photo, 'arc': arc.key, 'status': arc.finish_status if step.finish else status}

    try:
        result = await asyncio.to_thread(_apply)
    except Exception:
        logger.exception('marital arc step failed user=%s', telegram_id)
        return web.json_response({'ok': False, 'error': 'arc'}, status=500)
    if result == 'peaches':
        return web.json_response({'ok': False, 'error': 'peaches', 'price': marital_arcs.RING_PEACHES,
                                  'balance': get_photo_credits(telegram_id)}, status=402)
    if isinstance(result, str):
        return web.json_response({'ok': False, 'error': result},
                                 status=403 if result in ('premium_required', 'adult', 'consent', 'level') else 400)
    if result.get('photo'):
        asyncio.create_task(_marital_arc_photo(telegram_id, character_id, result['uid'], result['photo']))
    return web.json_response({'ok': True, 'character_id': character_id, 'status': result['status'],
                              'photo': bool(result.get('photo')), 'balance': get_photo_credits(telegram_id)},
                             headers={'Cache-Control': 'no-store'})


async def _marital_arc_photo(telegram_id: int, character_id: str, uid: int, spec: dict) -> None:
    try:
        data, mime, ext = await _webapp_pipeline_photo(telegram_id, character_id, PhotoRequest(customized=True, **spec))
        filename = webapp_service.save_chat_media(telegram_id, data, ext, mime)
        await asyncio.to_thread(save_message, uid, character_id, 'assistant', '📸',
                                media_kind='photo', media_url=f'/webapp/media/{filename}')
    except Exception:
        logger.exception('marital arc photo failed user=%s character=%s', telegram_id, character_id)


LEFT_HIM_TEXT = 'я ушла от него. совсем. собрала вещи и стою у твоей двери… можно к тебе? 🧳'
LEFT_HIM_PHOTO = PhotoRequest(
    scene='selfie', location='a doorway of an apartment building at night, warm light from the hall, a small suitcase beside her',
    clothing='a light trench coat over a simple dress', accessory='no ring on her fingers',
    mood='nervous, hopeful, a little teary, in love',
    angle='selfie at arm\'s length, the suitcase and her whole face in frame', customized=True)


async def _left_him_scene(telegram_id: int, character_id: str, uid: int) -> None:
    """V3.61.9: she left her husband / boyfriend on levels 7-8 — her words
    land in the chat at once, the suitcase photo follows when it renders."""
    try:
        await asyncio.to_thread(save_message, uid, character_id, 'assistant', LEFT_HIM_TEXT)
        data, mime, ext = await _webapp_pipeline_photo(telegram_id, character_id, LEFT_HIM_PHOTO)
        filename = webapp_service.save_chat_media(telegram_id, data, ext, mime)
        await asyncio.to_thread(save_message, uid, character_id, 'assistant', '🧳',
                                media_kind='photo', media_url=f'/webapp/media/{filename}')
        track_event(uid, 'left_him_scene', metadata={'character_id': character_id})
    except Exception:
        logger.exception('left-him scene failed user=%s character=%s', telegram_id, character_id)


async def _webapp_api_chat_persona(request: web.Request) -> web.Response:
    # V3.55.6: the user picks her manner for this premium character — tender or
    # passionate. Stored on the relationship row; colors chat tone (bot + app)
    # and the photo expression pool. Only meaningful on the premium floor pair.
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
    style = str(body.get('style', '')).strip().lower()
    if not character_id or style not in ('tender', 'passionate'):
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    # Same access gates as sending a message in this chat. V3.57.2: the gate,
    # the relationship write and the event track run in one worker thread.
    def _save():
        if is_custom_character(character_id):
            if not get_custom_character_by_id(character_id):
                return 'unknown_character'
            if _custom_premium_gate_block(character_id, telegram_id):
                return 'premium_required'
        else:
            card = get_card(character_id)
            if not card or card.status not in ('active', 'premium'):
                return 'locked'
            if card.status == 'premium' and not is_premium(telegram_id):
                return 'premium_required'
        if not has_accepted(telegram_id):
            return 'consent'
        uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
        from services.relationship_engine import apply_premium_floor
        with SessionLocal() as session:
            row = apply_premium_floor(session, uid, character_id)
            if row is None:
                # not a premium user + premium character pair — no choice to make
                return 'premium_required'
            row.persona_style = style
            session.commit()
        track_event(uid, 'webapp_chat_persona', metadata={'character_id': character_id, 'style': style})
        return None

    try:
        blocked = await asyncio.to_thread(_save)
    except Exception:
        logger.exception('chat persona save failed user=%s character=%s', telegram_id, character_id)
        return web.json_response({'ok': False, 'error': 'save'}, status=500)
    if blocked:
        status = 400 if blocked == 'unknown_character' else 403
        return web.json_response({'ok': False, 'error': blocked}, status=status)
    return web.json_response({'ok': True, 'style': style})


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
    # V3.57.2: ensure_user writes on first touch — keep it off the loop too.
    def _load():
        uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
        return webapp_service.api_chat_list(uid, telegram_id)

    chats = await asyncio.to_thread(_load)
    return web.json_response({'ok': True, 'chats': chats})


async def _webapp_api_pictures(request: web.Request) -> web.Response:
    # V3.38.0: the user's «Картинки» gallery (newest first).
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    return web.json_response({'ok': True, 'pictures': await asyncio.to_thread(webapp_service.api_picture_list, telegram_id)})


async def _webapp_api_videos(request: web.Request) -> web.Response:
    # V3.55.0: the user's «Мои видео» gallery — app-rendered videos only
    # (studio 🎬 + chat-requested clips). Same owner-scoped auth model as
    # /webapp/api/pictures; the bytes are served by /webapp/media/{filename}.
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    return web.json_response({'ok': True, 'videos': await asyncio.to_thread(webapp_service.api_video_list, telegram_id)})


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
    from services import spend_service
    spend_service.set_spend_user(telegram_id)
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
    if get_paid_peaches(telegram_id) < webapp_service.WEBAPP_PICTURE_COST_CREDITS:
        return web.json_response({'ok': False, 'error': 'credits'}, status=402)
    style = str(body.get('style', 'anime'))[:16]
    fmt = str(body.get('format', 'square'))[:16]
    # V3.54.0: an optional uploaded reference photo turns the studio into
    # image-to-image (the person's identity/look is kept, the prompt + style
    # restyle it). The file is written to a throwaway temp path and deleted
    # right after the render — it is never persisted.
    ref_path = None
    if body.get('image') and telegram_id not in ADMIN_TELEGRAM_IDS:
        # V3.64.6: generating from an uploaded real photo is admin-only.
        return web.json_response({'ok': False, 'error': 'upload_admin_only'}, status=403)
    if body.get('image'):
        decoded = webapp_service.decode_data_image(str(body.get('image')))
        if not decoded:
            return web.json_response({'ok': False, 'error': 'bad_image'}, status=400)
        raw, _mime, ext = decoded
        tf = tempfile.NamedTemporaryFile(delete=False, suffix=f'.{ext}')
        tf.write(raw); tf.close()
        ref_path = Path(tf.name)
    # V3.51.2: adult-confirmed users get the studio's uncensored route — the
    # censored fal Seedream answers HTTP 422 content_policy_violation on an
    # explicit prompt, so those renders ride the same SpicyAPI text-to-image
    # the «Наедине» nude flow uses. Minors/coercion are hard-blocked above and
    # never reach any engine. V3.54.0: a real uploaded face NEVER routes to the
    # uncensored engine — img2img stays on the censored Seedream/Gemini chain.
    # V3.86.0: owner — explicit pictures are Premium-only. A spicy prompt from
    # a non-Premium user gets the Premium sheet (nothing charged, no render);
    # the uncensored engine is opened for Premium (and admins) only.
    prem_ok = is_premium(telegram_id) or telegram_id in ADMIN_TELEGRAM_IDS
    if not prem_ok and webapp_service.picture_prompt_spicy(prompt):
        if ref_path is not None:
            ref_path.unlink(missing_ok=True)
        return web.json_response({'ok': False, 'error': 'premium_required'}, status=403)
    adult_ok = is_adult_confirmed(telegram_id) and prem_ok and ref_path is None
    final_prompt = webapp_service.picture_final_prompt(prompt, style, fmt, adult=adult_ok)
    uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
    try:
        from services import photo_service
        # V3.44.16: the studio rides the same hard cap as chat photos — a hung
        # fal chain used to leave the studio spinning forever (49% of renders
        # died; the rest could stall for half an hour).
        data = None
        mime = None
        if adult_ok:
            from services.private_photo_service import generate_private_photo_t2i
            data = await asyncio.wait_for(
                generate_private_photo_t2i(final_prompt),
                timeout=PHOTO_TOTAL_BUDGET_SECONDS,
            )
            if data:
                mime = 'image/jpeg'
        if not data and ref_path is None:
            # V3.56.1: owner's call — studio scenes ride SpicyAPI too (better
            # than fal) whenever no uploaded reference pins the fal edit leg:
            # canonical face+body refs of the user's selected character.
            from services.private_photo_service import (
                generate_private_photo_real, PrivatePhotoRequest,
            )
            from services.character_dna_service import character_dna_context
            _char = get_user_character(telegram_id)
            _req = PrivatePhotoRequest(category='studio', type_id='custom', location_id='',
                                       mood_id='', character_id=_char)
            data = await asyncio.wait_for(
                generate_private_photo_real(_req, character_dna_context(_char), final_prompt),
                timeout=PHOTO_TOTAL_BUDGET_SECONDS,
            )
            if data:
                mime = 'image/jpeg'
        if not data:
            data, mime = await asyncio.wait_for(
                photo_service.generate_custom_avatar(final_prompt, ref_path),
                timeout=PHOTO_TOTAL_BUDGET_SECONDS,
            )
    except asyncio.TimeoutError:
        logger.warning('webapp picture generation timed out user=%s budget=%ss', telegram_id, PHOTO_TOTAL_BUDGET_SECONDS)
        await asyncio.to_thread(webapp_service.record_generation_failure, telegram_id, 'picture', None, final_prompt, 'timeout')
        reason = 'timeout' if telegram_id in ADMIN_TELEGRAM_IDS else None
        return web.json_response({'ok': False, 'error': 'gen', 'reason': reason}, status=502)
    except Exception as exc:
        logger.exception('webapp picture generation failed user=%s', telegram_id)
        await asyncio.to_thread(webapp_service.record_generation_failure, telegram_id, 'picture', None, final_prompt, f'{type(exc).__name__}: {exc}')
        # V3.39.0: the owner sees WHY the render died right in the studio toast.
        reason = f'{type(exc).__name__}: {str(exc)[:100]}' if telegram_id in ADMIN_TELEGRAM_IDS else None
        return web.json_response({'ok': False, 'error': 'gen', 'reason': reason}, status=502)
    finally:
        # V3.54.0: the uploaded reference never lingers, whatever the outcome.
        if ref_path is not None:
            try:
                ref_path.unlink(missing_ok=True)
            except Exception:
                pass
    if not data:
        return web.json_response({'ok': False, 'error': 'gen'}, status=502)
    ext = 'png' if 'png' in (mime or '') else 'jpg'
    filename = f"{int(_time.time() * 1000)}_{secrets.token_hex(8)}.{ext}"
    try:
        folder = webapp_service.APP_PICTURES_DIR / str(telegram_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / filename).write_bytes(data)
        webapp_service.save_picture(telegram_id, filename, prompt)
        # V3.51.1: audit the freeform studio render for the owner's admin feed.
        webapp_service.record_generation(telegram_id, 'picture', None, prompt, filename)
    except Exception:
        logger.exception('webapp picture save failed user=%s', telegram_id)
        return web.json_response({'ok': False, 'error': 'save'}, status=500)
    # V3.44.3 → V3.44.22: charge the real studio price (10 🍑 since the
    # economy rework), not a single credit. The balance guard above already
    # used WEBAPP_PICTURE_COST_CREDITS, so the deduction stays aligned.
    if not spend_peaches(telegram_id, webapp_service.WEBAPP_PICTURE_COST_CREDITS, paid_only=True):
        logger.warning('webapp picture credit race user=%s', telegram_id)
    track_event(uid, 'webapp_picture_generated', metadata={'style': style, 'format': fmt})
    return web.json_response({
        'ok': True,
        'file': f'/webapp/picture/{filename}',
        'credits_left': get_photo_credits(telegram_id),
    })


async def _webapp_api_studio_video(request: web.Request) -> web.Response:
    """V3.54.0: «Собери видео» — animate the user's own uploaded photo (or a
    prompt-generated frame) into a short clip for WEBAPP_VIDEO_COST_CREDITS 🍑,
    charged only after a successful render. The uploaded photo is used in-memory
    and never persisted."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    from services import spend_service
    spend_service.set_spend_user(telegram_id)
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    prompt = str(body.get('prompt', '')).strip()[:webapp_service.PICTURE_PROMPT_MAX_LEN]
    if prompt and not webapp_service.picture_prompt_allowed(prompt):
        return web.json_response({'ok': False, 'error': 'blocked'}, status=400)
    if not has_accepted(telegram_id):
        return web.json_response({'ok': False, 'error': 'consent'}, status=403)
    if get_paid_peaches(telegram_id) < webapp_service.WEBAPP_VIDEO_COST_CREDITS:
        return web.json_response({'ok': False, 'error': 'credits'}, status=402)
    uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))

    # 1) source frame: the uploaded photo, else render one from the prompt
    #    through the same censored studio engine (a real face never routes to the
    #    uncensored nude engine).
    image_bytes = None
    mime = 'image/jpeg'
    if body.get('image') and telegram_id not in ADMIN_TELEGRAM_IDS:
        # V3.64.6: animating an uploaded real photo is admin-only.
        return web.json_response({'ok': False, 'error': 'upload_admin_only'}, status=403)
    if body.get('image'):
        decoded = webapp_service.decode_data_image(str(body.get('image')))
        if not decoded:
            return web.json_response({'ok': False, 'error': 'bad_image'}, status=400)
        image_bytes, mime, _ext = decoded
    elif len(prompt) >= webapp_service.PICTURE_PROMPT_MIN_LEN:
        try:
            from services import photo_service
            final_prompt = webapp_service.picture_final_prompt(prompt, 'realistic', 'square', adult=False)
            image_bytes, mime = await asyncio.wait_for(
                photo_service.generate_custom_avatar(final_prompt, None),
                timeout=PHOTO_TOTAL_BUDGET_SECONDS,
            )
        except Exception:
            logger.exception('studio video frame gen failed user=%s', telegram_id)
            image_bytes = None
    if not image_bytes:
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)

    # 2) V3.69.0: SpicyAPI, always on the safe (clothed) model here — the frame
    #    is the user's own upload or prompt, never her canonical look.
    engines = video_engines()
    if not engines:
        return web.json_response({'ok': False, 'error': 'no_engine'}, status=503)
    # V3.55.0: a studio motion preset — the same server-side VIDEO_PRESETS the
    # bot ships (the client sends only a key, never free text into the engine
    # prompt). Without a preset: the user's own words as a light motion hint,
    # else the engines' calm default. The scene-gated sensual preset stays
    # unreachable here — a user's own photo never rides it.
    preset = str(body.get('preset', '')).strip()
    motion = VIDEO_PRESETS[preset][1] if preset in VIDEO_PRESETS else (prompt or None)
    video_bytes = None
    used_engine = None
    last_error = None
    for engine_name, engine_fn in engines:
        try:
            video_bytes = await engine_fn(image_bytes, mime_type=mime, prompt=motion, safe=True,
                                          scene='studio_video')
            used_engine = engine_name
            record_provider(f'studio_video/{engine_name}', True)
            break
        except Exception as exc:
            last_error = exc
            record_provider(f'studio_video/{engine_name}', False, f'{type(exc).__name__}: {str(exc)[:120]}')
            logger.warning('studio video engine %s failed user=%s error=%s', engine_name, telegram_id, str(exc)[:200])
    if not video_bytes:
        reason = f'{type(last_error).__name__}: {str(last_error)[:100]}' if (last_error and telegram_id in ADMIN_TELEGRAM_IDS) else None
        return web.json_response({'ok': False, 'error': 'gen', 'reason': reason}, status=502)

    # 3) persist + charge. save_chat_media keeps the bytes in Postgres (survives
    #    the ephemeral-disk wipe); the credit is spent only now, after success.
    try:
        filename = webapp_service.save_chat_media(telegram_id, video_bytes, 'mp4', 'video/mp4')
        webapp_service.record_generation(telegram_id, 'video', None, prompt, filename)
    except Exception:
        logger.exception('studio video save failed user=%s', telegram_id)
        return web.json_response({'ok': False, 'error': 'save'}, status=500)
    if not spend_peaches(telegram_id, webapp_service.WEBAPP_VIDEO_COST_CREDITS, paid_only=True):
        logger.warning('studio video credit race user=%s', telegram_id)
    track_event(uid, 'webapp_studio_video_generated', metadata={'engine': used_engine, 'preset': preset})
    return web.json_response({
        'ok': True,
        'file': f'/webapp/media/{filename}',
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


async def _webapp_media_photo(telegram_id: int, character_id: str, scene: str = 'selfie',
                              guest_id: str = ''):
    """V3.39.0: a personal in-character photo. V3.43.7: now through the real
    photo pipeline with the scene the app's picker chose — the figure follows
    the declared BODY IDENTITY instead of an improvised face-swap body."""
    # V3.61.6: a single app photo used to always take variant 0 of the scene;
    # now each tap draws one of its concrete shots (selfie, self-timer, full body).
    import random as _random
    from services.photo_service import SHOT_VARIANTS
    private = scene in ('personal', 'lingerie', 'private_fashion', 'nude', 'tease')
    variants = None if private else SHOT_VARIANTS.get(scene)
    angle = _random.choice(variants) if variants else ''
    # V3.139.0: owner ТЗ (Задача 6) — «Свидание втроем» passes the second girl
    # into the same frame; without her id this is the ordinary single photo.
    return await _webapp_pipeline_photo(
        telegram_id, character_id,
        PhotoRequest(scene=scene, angle=angle, with_guest=guest_id or ''),
    )


# V3.56.0: _webapp_media_hot knows the real engine (cache/pool/fal/spicyapi) and
# its cost, but the generic chat-media recorder that writes the admin feed runs
# one level up. This per-user stash carries the hint across that boundary so the
# feed shows the true money trail; the caller pops it on the same event loop tick.
_HOT_MEDIA_HINT: dict = {}


async def _webapp_media_hot(telegram_id: int, character_id: str, category: str, cosplay: bool = False):
    """V3.45: generate a private/cosplay photo via SpicyAPI."""
    from services.private_photo_service import (
        PrivatePhotoRequest, build_private_photo_prompt, generate_private_photo_real,
        generate_private_photo_t2i, generate_private_photo_nude,
        get_private_photo_usage, consume_free_private_photo, cache_get, cache_save,
        pool_get, gallery_save, check_achievements, COSPLAY_CHARACTERS, PRIVATE_PHOTO_CATEGORIES,
    )
    from services.character_dna_service import character_dna_context
    from services.private_photo_service import get_category_cost
    # V3.45.22: parse compound scene "cat:type:loc:mood" from Mini App wizard
    parts = category.split(':') if not cosplay else [category]
    cat_id = parts[0]
    type_id = parts[1] if len(parts) > 1 else ''
    loc_id = parts[2] if len(parts) > 2 else 'bedroom'
    mood_id = parts[3] if len(parts) > 3 else 'sensual'
    color_id = parts[4] if len(parts) > 4 else ''  # V3.45.26: lingerie colour
    peach_cost = get_category_cost(cat_id) if not cosplay else COSPLAY_PHOTO_PEACH_COST
    # Check balance: free daily or peaches
    free_used = consume_free_private_photo(telegram_id, 'cosplay' if cosplay else cat_id)
    if not free_used:
        if get_paid_peaches(telegram_id) < peach_cost:
            raise PhotoGenerationError('hot', 'insufficient_peaches')
    # Build request
    dna_ctx = character_dna_context(character_id)
    if cosplay:
        cos_char = next((c for c in COSPLAY_CHARACTERS if c['id'] == cat_id), COSPLAY_CHARACTERS[0])
        req = PrivatePhotoRequest(category='cosplay', type_id='default', location_id='bedroom',
                                  mood_id='playful', character_id=character_id, cosplay_id=cat_id)
    else:
        cat_data = PRIVATE_PHOTO_CATEGORIES.get(cat_id, {})
        types = cat_data.get('types', [])
        if not type_id:
            type_id = types[0]['id'] if types else 'default'
        req = PrivatePhotoRequest(category=cat_id, type_id=type_id, location_id=loc_id,
                                  mood_id=mood_id, character_id=character_id, color=color_id or None)
    # V3.45.23: nude categories cannot be produced by image-to-image edit (the
    # model keeps a clothed reference clothed) — render them via text-to-image
    # instead, anchoring identity with the text visual-lock only.
    is_adult = (not cosplay) and cat_id in ('fully_nude', 'nude_art')
    # V3.62.5: nude renders edit from her face reference too, so the prompt
    # carries the FACE LOCK for every category now.
    prompt = build_private_photo_prompt(req, dna_ctx, use_reference=True)
    prompt = _with_marital_ring(prompt, telegram_id, character_id)
    # Check cache
    cached = cache_get(prompt, character_id)
    if cached:
        if not free_used:
            spend_peaches(telegram_id, peach_cost, paid_only=True)
        _HOT_MEDIA_HINT[telegram_id] = ('cache', 0.0)
        return cached, 'image/jpeg', 'jpg'
    # V3.51.3: pool reuse — once this character's shared cache has stockpiled
    # enough ready shots for the SAME scene (category + pose/type), send a
    # random one and skip paying the provider again. The user is still charged;
    # only the redundant render is saved. The volatile per-frame expression
    # rotation makes the exact prompt-hash cache_get almost never repeat, so
    # this reads the accumulated stockpile matched on stable columns instead.
    # V3.60.1: the owner tests fresh renders, never the stockpile.
    pooled = None if telegram_id in ADMIN_TELEGRAM_IDS else pool_get(character_id, cat_id, req.type_id)
    if pooled:
        if not free_used:
            spend_peaches(telegram_id, peach_cost, paid_only=True)
        gallery_save(telegram_id, character_id, cat_id, req.type_id, pooled)
        check_achievements(telegram_id)
        _HOT_MEDIA_HINT[telegram_id] = ('pool', 0.0)
        return pooled, 'image/jpeg', 'jpg'
    # Generate: adult → fal.ai t2i (safety checker off); others → SpicyAPI i2i
    # V3.46.1: track the real provider failure so the admin toast can show WHY
    # nothing arrived (missing key vs transport error vs engine reject) instead
    # of the old silent «all_providers_failed». Normal users still get the
    # generic message — the detail is only surfaced for ADMIN_TELEGRAM_IDS.
    image_bytes = None
    engine_used = 'spicyapi'
    provider_error = None
    if is_adult:
        # V3.46.1: nude goes to the UNCENSORED SpicyAPI engine — the fal Seedream
        # route is censored and returns HTTP 422 content_policy_violation on the
        # nude prompt (confirmed in production logs), so it can never deliver
        # full nudity. V3.56.0: only ONE paid SpicyAPI attempt — the old t2i→i2i
        # retry billed a second $0.0345 job on the same prompt (and i2i drags a
        # nude back toward the clothed reference anyway), so a failed nude cost
        # double for nothing. Order now: SpicyAPI text-to-image → fal t2i last.
        # V3.62.5: face-reference edit first — t2i alone drew a stranger. The
        # reference-free t2i stays only as the fallback when the edit fails.
        engine_used = 'spicyapi_face_edit'
        image_bytes = await generate_private_photo_nude(req, prompt)
        if not image_bytes:
            engine_used = 'spicyapi_t2i'
            image_bytes = await generate_private_photo_t2i(build_private_photo_prompt(req, dna_ctx, use_reference=False))
        if not image_bytes:
            from config import SPICYAPI_KEY as _spicy_key
            provider_error = 'spicyapi_empty_result' + ('' if _spicy_key else ' (SPICYAPI_KEY not set)')
    else:
        image_bytes = await generate_private_photo_real(req, dna_ctx, prompt)
        if not image_bytes:
            from config import SPICYAPI_KEY as _spicy_key
            provider_error = 'spicyapi_empty_result' + ('' if _spicy_key else ' (SPICYAPI_KEY not set)')
    # V3.64.5: no fal fallbacks here any more — every «Наедине» photo is SpicyAPI only.
    logger.info('hot generated user=%s engine=%s ok=%s reason=%s', telegram_id, engine_used, bool(image_bytes), provider_error)
    if not image_bytes:
        raise PhotoGenerationError('hot', provider_error or 'all_providers_failed')
    # Charge peaches if free limit was not used
    if not free_used:
        spend_peaches(telegram_id, peach_cost, paid_only=True)
    # Save to cache + gallery
    type_id = req.type_id
    cache_save(prompt, character_id, cat_id, type_id, image_bytes)
    gallery_save(telegram_id, character_id, cat_id, type_id, image_bytes)
    check_achievements(telegram_id)
    # V3.56.0: carry the true engine+cost to the admin-feed recorder upstream.
    from config import SPICYAPI_ESTIMATED_COST_USD as _spicy_cost, FAL_ESTIMATED_COST_USD as _fal_cost
    if engine_used.startswith('spicyapi'):
        _HOT_MEDIA_HINT[telegram_id] = ('spicyapi', _spicy_cost)
    elif engine_used.startswith('fal'):
        _HOT_MEDIA_HINT[telegram_id] = ('fal', _fal_cost)
    else:
        _HOT_MEDIA_HINT[telegram_id] = (engine_used, 0.0)
    return image_bytes, 'image/jpeg', 'jpg'


async def _webapp_media_circle(telegram_id: int, character_id: str):
    """V3.39.0: a video circle from the canonical face. V3.69.0: SpicyAPI, a
    square selfie frame, and she says a line from the dialogue."""
    photo = webapp_service.character_photo(character_id)
    if not photo:
        raise PhotoGenerationError('circle', 'no_source_photo')
    image_bytes = photo[0]
    engines = []
    engines.extend(fn for _, fn in video_engines())  # V3.69.0: SpicyAPI only
    if not engines:
        raise PhotoGenerationError('circle', 'no_video_engine')
    phrase = await asyncio.to_thread(_circle_phrase, telegram_id, character_id)
    last_error = None
    for engine_fn in engines:
        ename = engine_fn.__name__.replace('animate_image_', '')
        try:
            video_bytes = await engine_fn(
                square_frame(image_bytes), mime_type='image/jpeg',
                prompt=CIRCLE_PROMPT.format(phrase=phrase), scene='circle')
            record_provider(f'circle/{ename}', True)
            return video_bytes, 'video/mp4', 'mp4'
        except Exception as exc:
            last_error = exc
            record_provider(f'circle/{ename}', False, f'{type(exc).__name__}: {str(exc)[:120]}')
            logger.warning('webapp circle engine failed user=%s: %s', telegram_id, str(exc)[:200])
    raise last_error or PhotoGenerationError('circle', 'no_video_result')


async def _webapp_media_hot_circle(telegram_id: int, character_id: str, guest_id: str = ''):
    """V3.72.0: «🔥 горячий кружок»; V3.73.0: «🤫 тайное видео» — her canonical
    portrait animated by Seedance 2.5 Spicy, silent. Paid only on success.
    V3.139.2: with a guest the clip is «видео вдвоём» — it starts from a joint
    lingerie frame (generated here, not charged as a photo) and the duo prompt."""
    from services import hot_circle_service
    from services import spend_service
    spend_service.set_spend_user(telegram_id)
    if guest_id:
        # The joint source frame is a render, not a sold photo: the user pays
        # only the hot-circle price once, in _finish, after the clip exists.
        frame = None
        try:
            shot = await _webapp_media_photo(telegram_id, character_id, 'lingerie', guest_id)
            frame = shot[0] if shot else None
        except Exception:
            logger.warning('duo hot circle frame failed user=%s', telegram_id, exc_info=True)
        if not frame:
            raise PhotoGenerationError('hotcircle', 'no_source_photo')
        lang = 'en' if user_lang(telegram_id) == EN else 'ru'
        try:
            video = await hot_circle_service.render(square_frame(frame), lang, duo=True)
        except Exception as exc:
            record_provider('circle/hot', False, f'{type(exc).__name__}: {str(exc)[:120]}')
            raise PhotoGenerationError('hotcircle', str(exc)[:120]) from exc
        record_provider('circle/hot', True)
        return video, 'video/mp4', 'mp4'
    # V3.73.0: start from her lingerie-in-bedroom shot (the storefront portrait
    # is a café in a sweater); the portrait is only the fallback.
    frame = await hot_circle_service.bedroom_frame(character_id)
    if not frame:
        photo = webapp_service.character_photo(character_id)
        if not photo:
            raise PhotoGenerationError('hotcircle', 'no_source_photo')
        frame = photo[0]
    lang = 'en' if user_lang(telegram_id) == EN else 'ru'
    try:
        video = await hot_circle_service.render(square_frame(frame), lang)
    except Exception as exc:
        record_provider('circle/hot', False, f'{type(exc).__name__}: {str(exc)[:120]}')
        logger.warning('webapp hot circle failed user=%s: %s', telegram_id, str(exc)[:200])
        raise PhotoGenerationError('hotcircle', str(exc)[:120]) from exc
    record_provider('circle/hot', True)
    return video, 'video/mp4', 'mp4'


async def _webapp_media_voice(telegram_id: int, character_id: str):
    """V3.39.0: her voice — synthesizes her last reply (or the scenario hook)."""
    # V3.57.2: the user read and the last-ten-messages read leave the loop.
    def _pick_line():
        user = get_user(telegram_id)
        history = webapp_service.api_chat_history(user.id if user else 0, character_id, 10)
        text = next((m['content'] for m in reversed(history)
                     if m['role'] == 'assistant' and not m.get('media_url')), '')
        if not text:
            text = get_scenario_hook(character_id) or 'привет, я скучала 🙂'
        return text, (user.voice_style if user else None) or 'nova'

    text, voice_style = await asyncio.to_thread(_pick_line)
    clean = _tts_text(text)
    audio = await synthesize_bytes(clean, voice_style, character_id=character_id)
    return audio, 'audio/ogg', 'ogg'


# V3.41.0: the app-chat «🎬 Видео» button animates the canonical face into a
# short cinematic clip (a normal rectangle, not a round circle). Same engine
# engine the bot's «Оживить фото» uses (SpicyAPI since V3.69.0).
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
    # V3.57.2: the canonical shot may be a PostgreSQL large-object read.
    photo = await asyncio.to_thread(webapp_service.character_photo, character_id)
    if not photo:
        raise PhotoGenerationError('video', 'no_source_photo')
    image_bytes = photo[0]
    engines = []
    engines.extend(fn for _, fn in video_engines())  # V3.69.0: SpicyAPI only
    if not engines:
        raise PhotoGenerationError('video', 'no_video_engine')
    last_error = None
    for engine_fn in engines:
        ename = engine_fn.__name__.replace('animate_image_', '')
        try:
            video_bytes = await engine_fn(image_bytes, mime_type='image/png', prompt=_WEBAPP_VIDEO_PROMPT)
            record_provider(f'video/{ename}', True)
            return video_bytes, 'video/mp4', 'mp4'
        except Exception as exc:
            last_error = exc
            record_provider(f'video/{ename}', False, f'{type(exc).__name__}: {str(exc)[:120]}')
            logger.warning('webapp video engine failed user=%s: %s', telegram_id, str(exc)[:200])
    raise last_error or PhotoGenerationError('video', 'no_video_result')


# V3.61.7: the buttons under a photo in the chat — «🎬 Оживить» animates THAT
# photo, «🔥 Раздеть» re-renders it with her top off, covering her chest with
# her hand (1 free a day, then peaches; 18+ confirmed users only).
UNDRESS_PROMPT = (
    'Edit this exact photo. Keep the SAME adult woman: identical face, hair, makeup, body proportions, '
    'the same place, background, lighting and camera angle as image 1 (her face also matches image 2). '
    'Keep her outfit recognisable; change only what the reveal below describes. '
)
UNDRESS_TAIL = (
    ' Playful, confident, slightly shy expression, as if she does it just for the person she is chatting with. '
    'Natural slender female hands with five correct fingers. Photorealistic, same smartphone-photo look. '
    # V3.62.6: an undressed selfie grew a third arm — the phone hand stayed and
    # the reveal added two more.
    'She has exactly two arms and two hands. If one hand holds the phone in image 1, it keeps holding it and the '
    'reveal uses only her other hand; if the reveal needs both hands, the phone is gone from the photo. '
    'Never a third hand or arm.'
)
# V3.61.10: «Раздеть» is not one pose — she shows a little of what is under
# her clothes, picked to fit what she wears. Levels 1-3 stay in lingerie;
# the topless hand-bra opens from level 4; partial reveal from 6.
UNDRESS_VARIANTS_LINGERIE = (
    ('lift', 'REVEAL: if she wears a dress or skirt, she lifts the hem with one hand to show her lace panties '
             'underneath; if she wears jeans or trousers, she pulls the waistband down a little on her hips '
             'so the top of her lace panties shows. Everything else stays on.'),
    ('back', 'REVEAL: she turns a little and looks back over her shoulder; if she wears jeans or trousers she '
             'pulls them down to her upper thighs, if a dress or skirt she lifts it at the back, so her bottom '
             'in lace panties is visible. Her chest stays covered by her top.'),
    ('neck', 'REVEAL: she pulls the neckline or the straps of her dress or top down (or opens her blouse or '
             'jacket) to show her lace bra and cleavage; the rest of her outfit stays on.'),
    ('shoulder', 'REVEAL: she lets her dress or top slip off one shoulder, the strap falling down her arm, '
                 'so the lace cup and strap of her bra show; she holds the fabric at her chest with one hand.'),
    ('zip', 'REVEAL: she half-turns away and unzips or unbuttons the back of her dress or top, looking back at the '
            'camera; her bare back and the clasp of her lace bra are visible.'),
    ('tug', 'REVEAL: she pulls her top or dress up to just below her bust, showing her bare stomach, waist and '
            'the lower edge of her lace bra, biting her lip.'),
    ('thigh', 'REVEAL: she sits down and slides her skirt or dress up her thigh to show the lace top of her '
              'stockings and a glimpse of her panties; if she wears jeans, she unbuttons them and opens the fly '
              'a little to show the lace of her panties.'),
)
UNDRESS_VARIANTS_TOPLESS = (
    ('shirt', 'REVEAL: she has taken her top and bra off and holds her clothing pressed against her bare chest '
              'with both hands, covering her breasts, bare shoulders and sides visible.'),
    ('crossed', 'REVEAL: she is topless from the waist up and covers her breasts with both arms crossed over '
                'her chest, nipples fully hidden; everything below the waist stays as it was.'),
)
UNDRESS_VARIANT_TOPLESS = (
    'topless', 'REVEAL: she has pulled her top or the upper part of her dress down to the waist and taken off '
               'her bra, so she is topless, and she covers her bare breasts with her hand and forearm '
               '(a natural hand-bra), nipples fully hidden behind her arm. Everything below the waist stays as it was.')


def _undress_variant(level: int) -> tuple[str, str]:
    pool = list(UNDRESS_VARIANTS_LINGERIE)
    if level >= 4:
        pool += [UNDRESS_VARIANT_TOPLESS, *UNDRESS_VARIANTS_TOPLESS]
    return random.choice(pool)


UNDRESS_LINES = ('ну раз ты так просишь… 🙈', 'только тебе 🙈🔥', 'смотри, но никому 🤫', 'вот так лучше? 😏',
                 'угадал, что у меня под платьем? 😏', 'это я специально для тебя надела 🖤', 'дальше — заслужи 😉')
# A married girl / one with a boyfriend: he is in the room, back turned and unaware.
UNDRESS_SECRET = (
    ' SECRET MOMENT: in the background, slightly out of focus, her {who} (an adult man, fully clothed) stands '
    'with his back to the camera, busy and unaware; his face is not visible. She takes this photo secretly, '
    'glancing at the camera with a naughty finger-to-lips look, the index finger of the ONE hand the reveal '
    'leaves free (never a third hand: if the phone is in the other hand, the reveal hand is the phone hand).'
)
# V3.81.1: «3 руки» — the reveals that busy both hands at her chest grew a
# third one for the finger-to-lips; with them the secret is only in her eyes.
UNDRESS_SECRET_NO_FINGER = (
    ' SECRET MOMENT: in the background, slightly out of focus, her {who} (an adult man, fully clothed) stands '
    'with his back to the camera, busy and unaware; his face is not visible. She takes this photo secretly; '
    'the secret shows only in her naughty sideways glance and bitten lip. Both her hands stay exactly where '
    'the reveal puts them, no hand near her face, exactly two arms and two hands in the photo.'
)
UNDRESS_BOTH_HANDS = frozenset({'shirt', 'crossed'})
UNDRESS_SECRET_LINES = ('тсс… он прямо за спиной 🤫🔥', 'пока он не видит… только тебе 🙈', 'если он обернётся, мне конец 😳🔥')
# Level 6+ (where her nude photos open): she shows a little more instead of covering fully.
UNDRESS_REVEAL = (
    ' At this closeness she is bolder: one arm covers her chest only partly and she lets one breast '
    'be gently, tastefully visible, artistic and natural.'
)


def _undress_premium_free(telegram_id: int, character_id: str) -> int:
    """V3.61.12: Premium's free «Раздеть» a day grows with her level:
    1 on levels 1-2, 2 on levels 3-6, 3 on levels 7-8."""
    from config import UNDRESS_PREMIUM_FREE_L1_2, UNDRESS_PREMIUM_FREE_L3_6, UNDRESS_PREMIUM_FREE_L7_8
    try:
        level = get_relationship_level(telegram_id, character_id)
    except Exception:
        level = 1
    if level >= 7:
        return UNDRESS_PREMIUM_FREE_L7_8
    return UNDRESS_PREMIUM_FREE_L3_6 if level >= 3 else UNDRESS_PREMIUM_FREE_L1_2


def _undress_allowance(uid: int, telegram_id: int, character_id: str, used_today: int) -> int:
    """V3.124.0: the daily Premium allowance, capped by the trial total."""
    allow = _undress_premium_free(telegram_id, character_id)
    try:
        from services import trial_caps
        trial = trial_caps.undress_allowance_today(uid, used_today)
        if trial is not None:
            allow = min(allow, trial)
    except Exception:
        pass
    return allow


# The gentlest reveal — the last try when the engine refused the first pick.
UNDRESS_SAFE_VARIANT = UNDRESS_VARIANTS_LINGERIE[3]


def _undress_prompt(telegram_id: int, character_id: str, *, safe: bool = False) -> tuple[str, bool]:
    try:
        level = get_relationship_level(telegram_id, character_id)
    except Exception:
        level = 1
    variant, reveal = UNDRESS_SAFE_VARIANT if safe else _undress_variant(level)
    prompt, secret = UNDRESS_PROMPT + reveal + UNDRESS_TAIL, False
    try:
        from services.webapp_service import _batch_marital, _default_marital
        status = _batch_marital(telegram_id, [character_id]).get(character_id) \
            or _default_marital(character_id, is_custom_character(character_id))
        who = {'mar_married': 'husband', 'mar_boyfriend': 'boyfriend'}.get(status)
        if who:
            line = UNDRESS_SECRET_NO_FINGER if variant in UNDRESS_BOTH_HANDS else UNDRESS_SECRET
            prompt += line.format(who=who)
            secret = True
    except Exception:
        logger.warning('undress marital lookup failed user=%s', telegram_id)
    if variant in ('topless', 'crossed') and level >= 6:
        prompt += UNDRESS_REVEAL
    return prompt, secret


def _media_sig(telegram_id: int, filename: str) -> str:
    import hashlib
    import hmac
    from config import TELEGRAM_TOKEN
    return hmac.new(TELEGRAM_TOKEN.encode(), f'media:{int(telegram_id)}:{filename}'.encode(),
                    hashlib.sha256).hexdigest()[:20]


async def _webapp_signed_media(request: web.Request) -> web.Response:
    """V3.61.7: a chat photo behind a signed URL so the image engine can fetch
    it as the edit reference (it has no init_data)."""
    import hmac
    try:
        telegram_id = int(request.match_info['uid'])
    except (TypeError, ValueError):
        return web.Response(status=404)
    filename = request.match_info['filename']
    if not hmac.compare_digest(request.match_info.get('sig', ''), _media_sig(telegram_id, filename)):
        return web.Response(status=404)
    path = await asyncio.to_thread(webapp_service.chat_media_file_path, telegram_id, filename)
    if not path:
        return web.Response(status=404)
    body = await asyncio.to_thread(path.read_bytes)
    ctype = 'image/png' if path.suffix == '.png' else 'image/jpeg'
    return web.Response(body=body, content_type=ctype, headers={'Cache-Control': 'private, max-age=3600'})


async def _webapp_video_frame(request: web.Request) -> web.Response:
    """V3.69.0: the start frame SpicyAPI fetches for a video job — parked in
    memory behind an unguessable token for ~30 minutes."""
    item = parked_frame(request.match_info.get('token', ''))
    if not item:
        return web.Response(status=404)
    body, ctype = item
    return web.Response(body=body, content_type=ctype, headers={'Cache-Control': 'no-store'})


async def _animate_photo_bytes(telegram_id: int, image_bytes: bytes, mime: str) -> bytes:
    engines = []
    engines.extend(fn for _, fn in video_engines())  # V3.69.0: SpicyAPI only
    if not engines:
        raise PhotoGenerationError('video', 'no_video_engine')
    last_error = None
    for engine_fn in engines:
        ename = engine_fn.__name__.replace('animate_image_', '')
        try:
            video_bytes = await engine_fn(image_bytes, mime_type=mime, prompt=_WEBAPP_VIDEO_PROMPT)
            record_provider(f'video/{ename}', True)
            return video_bytes
        except Exception as exc:
            last_error = exc
            record_provider(f'video/{ename}', False, f'{type(exc).__name__}: {str(exc)[:120]}')
            logger.warning('photo animate engine failed user=%s: %s', telegram_id, str(exc)[:200])
    raise last_error or PhotoGenerationError('video', 'no_video_result')


async def _webapp_api_undress_credit(request: web.Request) -> web.Response:
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)

    def _read():
        from services import undress_credits
        from config import UNDRESS_PEACH_COST
        credits = undress_credits.balance(telegram_id)
        premium = is_premium(telegram_id)
        peaches = get_paid_peaches(telegram_id)
        return {'ok': True, 'ready': bool(premium or credits > 0 or peaches >= UNDRESS_PEACH_COST),
                'credits': credits, 'premium': premium, 'peaches': peaches, 'price': UNDRESS_PEACH_COST}

    return web.json_response(await asyncio.to_thread(_read))


async def _webapp_api_photo_action(request: web.Request) -> web.Response:
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
    character_id = str(body.get('character_id', ''))[:64]
    action = str(body.get('action', ''))
    media_url = str(body.get('media_url', ''))
    filename = media_url.split('?', 1)[0].rsplit('/', 1)[-1]
    if action not in ('animate', 'undress') or not character_id or not media_url.startswith('/webapp/media/'):
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    path = await asyncio.to_thread(webapp_service.chat_media_file_path, telegram_id, filename)
    if not path or path.suffix.lower() not in ('.jpg', '.jpeg', '.png'):
        return web.json_response({'ok': False, 'error': 'not_found'}, status=404)
    admin = telegram_id in ADMIN_TELEGRAM_IDS
    from services.chat_photo_allowance import count_ever, count_today, note_today

    def _her_photo(uid: int, kinds: tuple[str, ...]) -> bool:
        # Only HER generated photo in this chat — never a picture the user
        # uploaded (those must never reach the uncensored engine).
        from sqlalchemy import select as _select
        from models.app_models import Message
        with SessionLocal() as session:
            return session.scalar(_select(Message.id).where(
                Message.user_id == uid, Message.character_id == character_id,
                Message.role == 'assistant', Message.media_kind.in_(kinds),
                Message.media_url == f'/webapp/media/{filename}',
            ).limit(1)) is not None

    def _gate():
        uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
        # V3.138.0: «🏠 Дом» pictures her room — you can bring the room to life,
        # but there is nobody to undress in it, so that action stays for her photos.
        if not _her_photo(uid, ('photo', 'room') if action == 'animate' else ('photo',)):
            return uid, ('not_found', 404), None
        if action == 'animate':
            if admin:
                return uid, None, 'admin'
            if get_paid_peaches(telegram_id) < webapp_service.WEBAPP_VIDEO_COST_CREDITS:
                return uid, ('credits', 402), None
            return uid, None, 'peaches'
        if not is_adult_confirmed(telegram_id):
            return uid, ('adult_confirm', 403), None
        if admin:
            return uid, None, 'admin'
        from config import UNDRESS_PEACH_COST
        # V3.86.0: owner — «раздеть» only with Premium, the button sold Premium.
        # V3.132.0: a «Раздеть» bought on its own (50 ₽) works without Premium.
        # V3.138.0: owner — «не за 50 руб, а за 25, только цену в персиках»: without
        # Premium the button now costs 250 🍑; a credit he already bought still spends first.
        from services import undress_credits
        if not is_premium(telegram_id):
            if undress_credits.balance(telegram_id) > 0:
                return uid, None, 'credit'
            if get_paid_peaches(telegram_id) < UNDRESS_PEACH_COST:
                return uid, ('credits', 402), None
            return uid, None, 'peaches'
        _used_today = count_today(uid, 'undress_free')
        if _used_today < _undress_allowance(uid, telegram_id, character_id, _used_today):
            return uid, None, 'free'
        if undress_credits.balance(telegram_id) > 0:
            return uid, None, 'credit'
        if get_paid_peaches(telegram_id) < UNDRESS_PEACH_COST:
            return uid, ('credits', 402), None
        return uid, None, 'peaches'

    uid, err, pay = await asyncio.to_thread(_gate)
    if err:
        return web.json_response({'ok': False, 'error': err[0]}, status=err[1])
    try:
        if action == 'animate':
            raw = await asyncio.to_thread(path.read_bytes)
            data = await _animate_photo_bytes(telegram_id, raw, 'image/png' if path.suffix == '.png' else 'image/jpeg')
            ext, mime, kind = 'mp4', 'video/mp4', 'video'
            content = '🎬 ожила для тебя'
        else:
            from services.private_photo_service import _spicyapi_render, spicyapi_last_error
            from config import SPICYAPI_IMAGE_MODEL
            src = f'{PUBLIC_BASE_URL}/webapp/smedia/{int(telegram_id)}/{filename}/{_media_sig(telegram_id, filename)}'
            refs = [src, f'{PUBLIC_BASE_URL}/webapp/photo/{character_id}?i=0']
            prompt, secret = await asyncio.to_thread(_undress_prompt, telegram_id, character_id)
            data = await _spicyapi_render(SPICYAPI_IMAGE_MODEL, prompt, refs, scene='undress', breaker=False)
            if not data:
                # V3.61.10: one more try with the chat photo alone — the face
                # crop as a second reference can make the edit fail.
                logger.warning('undress first try empty user=%s character=%s error=%s',
                               telegram_id, character_id, spicyapi_last_error())
                data = await _spicyapi_render(SPICYAPI_IMAGE_MODEL, prompt, refs[:1], scene='undress', breaker=False)
            if not data:
                # V3.61.12: some girls never undressed — the engine kept
                # refusing the bolder pick. Last try: the gentlest reveal.
                logger.warning('undress second try empty user=%s character=%s error=%s',
                               telegram_id, character_id, spicyapi_last_error())
                prompt, secret = await asyncio.to_thread(_undress_prompt, telegram_id, character_id, safe=True)
                data = await _spicyapi_render(SPICYAPI_IMAGE_MODEL, prompt, refs[:1], scene='undress', breaker=False)
            if not data:
                raise PhotoGenerationError('spicyapi', spicyapi_last_error() or 'empty_result')
            ext, mime, kind = 'jpg', 'image/jpeg', 'photo'
            content = random.choice(UNDRESS_SECRET_LINES if secret else UNDRESS_LINES)
    except Exception as exc:
        logger.exception('photo action failed user=%s action=%s', telegram_id, action)
        await asyncio.to_thread(webapp_service.record_generation_failure, telegram_id, action,
                                character_id, media_url, f'{type(exc).__name__}: {exc}')
        # The owner sees the real reason right in the toast; users get a calm line.
        return web.json_response({'ok': False, 'error': 'failed',
                                  'reason': f'{type(exc).__name__}: {exc}'[:160] if admin else ''})

    def _deliver():
        name = webapp_service.save_chat_media(telegram_id, data, ext, mime)
        url = f'/webapp/media/{name}'
        webapp_service.record_generation(telegram_id, kind, character_id, f'{action}: {media_url}', name)
        save_message(uid, character_id, 'assistant', content, media_kind=kind, media_url=url)
        if action == 'animate' and pay == 'peaches':
            if not spend_peaches(telegram_id, webapp_service.WEBAPP_VIDEO_COST_CREDITS, paid_only=True):
                logger.warning('webapp photo animation peach race user=%s', telegram_id)
        if action == 'undress':
            from config import UNDRESS_PEACH_COST
            if pay in ('free', 'trial'):
                note_today(uid, f'undress_{pay}', character_id)
            elif pay == 'peaches':
                spend_peaches(telegram_id, UNDRESS_PEACH_COST, paid_only=True)
            elif pay == 'credit':
                from services import undress_credits
                undress_credits.spend(telegram_id)
        return {'ok': True, 'kind': kind, 'url': url, 'content': content,
                'credits_left': get_photo_credits(telegram_id)}

    out = await asyncio.to_thread(_deliver)
    _app_ping(telegram_id, character_id, out.get('content') or '', 'video' if kind == 'video' else 'photo')
    return web.json_response(out)


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
    # a photo costs one credit (PEACH_SCALE 🍑, charged after success), circles are a Premium
    # free-slot format, voice follows the character's TTS voice.
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    from services import spend_service
    spend_service.set_spend_user(telegram_id)
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    character_id = str(body.get('character_id', ''))
    kind = str(body.get('kind', ''))
    scene = str(body.get('scene') or 'selfie')[:80]
    if kind not in ('photo', 'circle', 'hotcircle', 'voice', 'video', 'hot', 'cosplay') or not character_id:
        logger.warning('webapp chat media bad_request user=%s kind=%r character=%r', telegram_id, kind, character_id)
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    # V3.139.0: owner ТЗ (Задачи 5–6) — «Свидание втроем». A joint frame needs the
    # invited girl; without her this stays the ordinary photo request.
    # V3.139.2: «видео вдвоём» rides the same joint flag on the hot-circle kind.
    joint = kind in ('photo', 'hotcircle') and bool(body.get('joint'))
    guest_id = ''
    if joint:
        from services.chat_guest_service import get_guest
        guest_id = await asyncio.to_thread(get_guest, telegram_id, character_id) or ''
        joint = bool(guest_id)
    # V3.57.2: the whole access chain is PostgreSQL reads/writes (card, consent,
    # stage, credits, premium slots) — one worker thread, never the loop.
    def _gate():
        if is_custom_character(character_id):
            if not get_custom_character_by_id(character_id):
                # V3.64.0: logged — the SPA only showed a generic toast.
                logger.warning('webapp chat media unknown_character user=%s character=%s', telegram_id, character_id)
                return web.json_response({'ok': False, 'error': 'unknown_character'}, status=400)
            # V3.55.3: same premium gate as the built-ins (was skipped here too).
            if _custom_premium_gate_block(character_id, telegram_id):
                return web.json_response({'ok': False, 'error': 'premium_required'}, status=403)
        else:
            card = get_card(character_id)
            if not card or card.status not in ('active', 'premium'):
                return web.json_response({'ok': False, 'error': 'locked'}, status=403)
            if card.status == 'premium' and not is_premium(telegram_id):
                return web.json_response({'ok': False, 'error': 'premium_required'}, status=403)
            if kind != 'voice' and _card_girl_photo_locked(character_id, telegram_id):
                return web.json_response({'ok': False, 'error': 'premium_required'}, status=403)
        if not has_accepted(telegram_id):
            return web.json_response({'ok': False, 'error': 'consent'}, status=403)
        if kind == 'photo':
            # V3.43.7: the scene comes from the app's picker — it must be one of
            # the menu scenes and clear the same relationship/adult gates the
            # bot's photo keyboard enforces.
            if scene not in PHOTO_MENU_ORDER:
                logger.warning('webapp chat media bad scene user=%s character=%s scene=%r', telegram_id, character_id, scene)
                return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
            # V3.88.0: spicy scenes are gated by Premium (below), not by level.
            if not spicy_needs_premium(PhotoRequest(scene=scene)) \
                    and not scene_allowed_for_stage(scene, get_relationship_stage(telegram_id, character_id)):
                return web.json_response({'ok': False, 'error': 'locked'}, status=403)
            if requires_adult_confirmation(PhotoRequest(scene=scene)) and not is_adult_confirmed(telegram_id):
                return web.json_response({'ok': False, 'error': 'adult_confirm'}, status=403)
            if joint and telegram_id not in ADMIN_TELEGRAM_IDS and not is_premium(telegram_id):
                # V3.139.0: Задача 5 — no render call, no spend. He sees the
                # blurred joint teaser and both girls' hook, with the Premium
                # button under it.
                uid = ensure_user(telegram_id, user_info.get('first_name') or '',
                                  language_code=user_info.get('language_code'))
                return web.json_response(_chat_duo_blocked(
                    uid, telegram_id, character_id,
                    full_user_lang(telegram_id, user_info.get('language_code')), {}))
        # V3.87.0: nude / lingerie photos, the private «Наедине» shots and the
        # hot circle are Premium-only — free peaches must never buy them.
        if telegram_id not in ADMIN_TELEGRAM_IDS and not is_premium(telegram_id) and (
                kind in ('hot', 'hotcircle')
                or (kind == 'photo' and spicy_needs_premium(PhotoRequest(scene=scene)))):
            try:
                track_event(ensure_user(telegram_id), 'paywall_view',
                            metadata={'product': 'spicy_' + kind, 'scene': scene, 'source': 'app'})
            except Exception:
                pass
            return web.json_response({'ok': False, 'error': 'premium_required'}, status=403)
        if kind == 'photo' and telegram_id not in ADMIN_TELEGRAM_IDS and not is_premium(telegram_id):
            # V3.93.0: a rendered photo for peaches is a Premium thing — free
            # peaches pile up and burned the render budget.
            return web.json_response({'ok': False, 'error': 'premium_required'}, status=403)
        if kind == 'photo' and telegram_id not in ADMIN_TELEGRAM_IDS \
                and get_paid_peaches(telegram_id) < PEACH_SCALE:
            # V3.44.22: a chat photo costs ONE credit (consume_photo_credit below) —
            # the old guard demanded the studio's whole price and blocked users who
            # had plenty for the actual charge.
            return web.json_response({'ok': False, 'error': 'credits'}, status=402)
        if kind == 'circle' and telegram_id not in ADMIN_TELEGRAM_IDS \
                and get_paid_peaches(telegram_id) < CIRCLE_PEACH_COST:
            # V3.71.0: circles are paid in peaches for everyone (charged in
            # _finish only once the circle exists).
            return web.json_response({'ok': False, 'error': 'credits'}, status=402)
        if kind == 'hotcircle':
            # V3.72.0: our own built-in heroines only (a custom face may come
            # from a real person's photo), adults who confirmed 18+, paid.
            if not HOT_CIRCLE_ENABLED or is_custom_character(character_id):
                return web.json_response({'ok': False, 'error': 'locked'}, status=403)
            if not is_adult_confirmed(telegram_id):
                return web.json_response({'ok': False, 'error': 'adult_confirm'}, status=403)
            if telegram_id not in ADMIN_TELEGRAM_IDS and get_paid_peaches(telegram_id) < HOT_CIRCLE_PEACH_COST:
                return web.json_response({'ok': False, 'error': 'credits'}, status=402)
        if kind == 'video' and telegram_id not in ADMIN_TELEGRAM_IDS \
                and get_paid_peaches(telegram_id) < webapp_service.WEBAPP_VIDEO_COST_CREDITS:
            return web.json_response({'ok': False, 'error': 'credits'}, status=402)
        if kind == 'voice' and telegram_id not in ADMIN_TELEGRAM_IDS and not is_premium(telegram_id):
            # V3.55.1: voice is a Premium perk now (owner) — the SPA already maps
            # premium_required to the paywall toast and the shop tab.
            return web.json_response({'ok': False, 'error': 'premium_required'}, status=403)
        uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
        track_event(uid, 'webapp_chat_media', metadata={'character_id': character_id, 'kind': kind, 'scene': scene})
        return uid

    gated = await asyncio.to_thread(_gate)
    if not isinstance(gated, int):
        return gated
    uid = gated
    try:
        if kind == 'photo':
            data, mime, ext = await _webapp_media_photo(telegram_id, character_id, scene, guest_id)
        elif kind == 'circle':
            data, mime, ext = await _webapp_media_circle(telegram_id, character_id)
        elif kind == 'hotcircle':
            data, mime, ext = await _webapp_media_hot_circle(telegram_id, character_id, guest_id)
        elif kind == 'video':
            data, mime, ext = await _webapp_media_video(telegram_id, character_id)
        elif kind == 'hot':
            data, mime, ext = await _webapp_media_hot(telegram_id, character_id, scene)
        elif kind == 'cosplay':
            data, mime, ext = await _webapp_media_hot(telegram_id, character_id, scene, cosplay=True)
        else:
            data, mime, ext = await _webapp_media_voice(telegram_id, character_id)
    except PhotoGenerationError as exc:
        # V3.46.1: surface the real provider reason to the owner/admin only; a
        # normal user gets reason=null so index.html falls back to the generic
        # L.pic_gen_fail toast (no internal keys/endpoints leak to clients).
        logger.warning('webapp chat media gen failed user=%s kind=%s provider=%s reason=%s',
                       telegram_id, kind, exc.provider, exc.reason)
        await asyncio.to_thread(webapp_service.record_generation_failure, telegram_id, kind, character_id, scene or '',
                                f'{exc.provider}: {exc.reason}')
        reason = exc.reason if telegram_id in ADMIN_TELEGRAM_IDS else None
        return web.json_response({'ok': False, 'error': 'gen', 'reason': reason}, status=502)
    except Exception as exc:
        logger.exception('webapp chat media failed user=%s kind=%s', telegram_id, kind)
        await asyncio.to_thread(webapp_service.record_generation_failure, telegram_id, kind, character_id, scene or '',
                                f'{type(exc).__name__}: {exc}')
        return web.json_response({'ok': False, 'error': 'gen'}, status=502)
    if not data:
        return web.json_response({'ok': False, 'error': 'gen'}, status=502)
    # V3.57.2: storing the media, auditing it, charging the credit and the
    # gallery-set reads all leave the loop.
    shown_kind = 'circle' if kind == 'hotcircle' else kind

    def _finish():
        filename = webapp_service.save_chat_media(telegram_id, data, ext, mime)
        url = f'/webapp/media/{filename}'
        # V3.51.1: audit the user-requested media (photo/hot/cosplay/video/circle);
        # voice carries no image, so it is left out of the visual admin feed.
        if kind != 'voice':
            # V3.56.0: hot/cosplay carry an exact engine+cost hint stashed by
            # _webapp_media_hot (cache/pool=$0, spicyapi/fal=$real); other kinds
            # record with no engine so the feed shows them unlabelled rather than
            # guessing.
            hint = _HOT_MEDIA_HINT.pop(telegram_id, None) if kind in ('hot', 'cosplay') else None
            if kind == 'hotcircle':
                from config import SPICYAPI_HOT_CIRCLE_COST_USD
                hint = ('spicyapi_hot_circle', SPICYAPI_HOT_CIRCLE_COST_USD)
            if hint:
                webapp_service.record_generation(telegram_id, kind, character_id, scene, filename,
                                                 engine=hint[0], cost_usd=hint[1])
            else:
                webapp_service.record_generation(telegram_id, kind, character_id, scene, filename)
        if kind == 'photo':
            _default_cap = ('\u043e\u0442\u043f\u0440\u0430\u0432\u0438\u043b\u0430 \u0444\u043e\u0442\u043e',)
            content = f'\U0001f4f8 {random.choice(AUTO_CAPTIONS.get(scene, _default_cap))}'
        elif kind in ('hot', 'cosplay'):
            content = '\U0001f48b \u043d\u0430\u0435\u0434\u0438\u043d\u0435...' if kind == 'hot' else '\U0001f3ad \u043a\u043e\u0441\u043f\u043b\u0435\u0439 \u0434\u043b\u044f \u0442\u0435\u0431\u044f'
        else:
            _media_caps = {'circle': '\U0001f3a5 \u043e\u0442\u043f\u0440\u0430\u0432\u0438\u043b\u0430 \u043a\u0440\u0443\u0436\u043e\u0447\u0435\u043a',
                           'hotcircle': '🤫 записала тебе кое-что… только не показывай никому',
                           'voice': '\U0001f399 \u043e\u0442\u043f\u0440\u0430\u0432\u0438\u043b\u0430 \u0433\u043e\u043b\u043e\u0441\u043e\u0432\u043e\u0435',
                           'video': '\U0001f3ac \u043e\u0442\u043f\u0440\u0430\u0432\u0438\u043b\u0430 \u0432\u0438\u0434\u0435\u043e'}
            content = _media_caps.get(kind, '')
        # V3.72.0: a hot circle is stored and drawn as a regular round circle.
        save_message(uid, character_id, 'assistant', content, media_kind=shown_kind, media_url=url)
        if kind == 'photo' and telegram_id not in ADMIN_TELEGRAM_IDS and not consume_photo_credit(telegram_id):
            logger.warning('webapp chat photo credit race user=%s', telegram_id)
        if kind == 'circle' and telegram_id not in ADMIN_TELEGRAM_IDS and not spend_peaches(telegram_id, CIRCLE_PEACH_COST, paid_only=True):
            logger.warning('webapp chat circle peach race user=%s', telegram_id)
        if kind == 'video' and telegram_id not in ADMIN_TELEGRAM_IDS and not spend_peaches(telegram_id, webapp_service.WEBAPP_VIDEO_COST_CREDITS, paid_only=True):
            logger.warning('webapp chat video peach race user=%s', telegram_id)
        if kind == 'hotcircle' and telegram_id not in ADMIN_TELEGRAM_IDS and not spend_peaches(telegram_id, HOT_CIRCLE_PEACH_COST, paid_only=True):
            logger.warning('webapp chat hot circle peach race user=%s', telegram_id)
        # V3.44.6: record author revenue when someone spends on a custom character.
        if kind == 'photo' and is_custom_character(character_id):
            try:
                from services.custom_character_service import record_author_revenue
                record_author_revenue(character_id, telegram_id, 1.0, 'chat_photo')
            except Exception:
                logger.exception('author revenue recording failed char=%s', character_id)
        # V3.53.0: a delivered photo/circle/video/hot/cosplay advances the character's
        # gallery-set counter; tell the SPA when a set (50 photos) just completed so it
        # can celebrate. Voice is not a photo, so it never counts and never celebrates.
        _set_completed = 0
        _gallery = None
        if kind != 'voice':
            from services.collection_service import gallery_set_progress, note_gallery_set
            _set_completed = note_gallery_set(telegram_id, character_id)
            _gallery = gallery_set_progress(telegram_id, character_id)
        return {'ok': True, 'kind': shown_kind, 'url': url, 'content': content,
                'credits_left': get_photo_credits(telegram_id),
                'set_completed': _set_completed,
                'gallery': _gallery}

    out = await asyncio.to_thread(_finish)
    if isinstance(out, dict) and out.get('ok'):
        _app_ping(telegram_id, character_id, out.get('content') or '',
                  out.get('kind') if out.get('kind') in ('photo', 'video', 'circle') else None)
    return web.json_response(out)


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
    # V3.57.2: path lookup may hit PostgreSQL (re-heal after an ephemeral-disk
    # wipe) and the read is blocking — both leave the event loop.
    path = await asyncio.to_thread(webapp_service.chat_media_file_path, telegram_id, request.match_info['filename'])
    if not path:
        return web.Response(status=404)
    body = await asyncio.to_thread(path.read_bytes)
    ctype = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
             'mp4': 'video/mp4', 'ogg': 'audio/ogg'}.get(path.suffix.lstrip('.'), 'application/octet-stream')
    # the file name is an unguessable immutable token — a day of cache is free
    return web.Response(body=body, content_type=ctype,
                        headers={'Cache-Control': 'private, max-age=86400, immutable'})


async def _webapp_api_feature(request: web.Request) -> web.Response:
    # V3.48.3: exception-guarded wrapper. A transient DB blip in the shared
    # prologue (get_relationship_level -> ensure_user writes on every call) used
    # to surface as a raw 500, which the Mini App rendered as the useless «Не
    # получилось ответить — попробуй ещё раз» on the daily-quest button. Log the
    # real cause and answer with a clean JSON error the SPA retries once.
    # V3.57.2: the whole menu builder is synchronous PostgreSQL work (it holds
    # no awaits), so it runs end to end in a worker thread instead of freezing
    # the event loop for every feature-button tap.
    try:
        return await asyncio.to_thread(_webapp_api_feature_impl, request)
    except Exception:
        logger.exception('webapp feature menu failed')
        return web.json_response({'ok': False, 'error': 'temporarily_unavailable'})


def _webapp_api_feature_impl(request: web.Request) -> web.Response:
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
    if kind not in ('apartment', 'date', 'quest', 'photo', 'video', 'cosplay', 'hot'):
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
                          'locked': False, 'cost': d.cost * PEACH_SCALE, 'done': d.id in done})
        for d in dates_service.get_locked(level):
            items.append({'id': d.id, 'emoji': '🔒', 'title': d.name,
                          'subtitle': (f'opens at level {d.min_level}' if lang == EN else f'откроется на уровне {d.min_level}'),
                          'locked': True, 'cost': d.cost * PEACH_SCALE, 'done': False})
        title = '💕 Where shall we go?' if lang == EN else '💕 Куда пойдём?'
        return web.json_response({'ok': True, 'kind': kind, 'title': title,
                                  'free_date': bool(has_free_date(telegram_id)), 'items': items})
    if kind == 'photo':
        # V3.43.7: the scene picker behind the app-chat «📸 Фото» button —
        # the same PHOTO_MENU_ORDER + SCENE_LEVELS progression the bot's
        # photo keyboard shows, so the menus pop out in the app too. Labels
        # live in the frontend (all 7 interface languages); the backend owns
        # the order and the relationship-level gates.
        # V3.88.0: spicy scenes are never level-locked — Premium is their gate
        # (non-Premium taps open the Premium sheet).
        items = [{
            'id': scene,
            'locked': SCENE_LEVELS.get(scene, 99) > level and not spicy_needs_premium(PhotoRequest(scene=scene)),
            'min_level': SCENE_LEVELS.get(scene, 99),
        } for scene in PHOTO_MENU_ORDER]
        title = '📸 Photo' if lang == EN else '📸 Фото'
        return web.json_response({'ok': True, 'kind': kind, 'title': title, 'items': items})
    # V3.45.0: Фото наедине — категории
    if kind == 'hot':
        import re
        from services.private_photo_service import (
            PRIVATE_PHOTO_CATEGORIES, get_private_photo_usage, get_category_cost, LOCATIONS, MOODS,
            LINGERIE_COLORS, PLACE_TYPED_CATEGORIES,
        )
        usage = get_private_photo_usage(telegram_id)
        items = []
        # V3.88.0: «Наедине» is Premium-only — say it on the menu itself.
        prem_only = telegram_id not in ADMIN_TELEGRAM_IDS and not is_premium(telegram_id)
        for cat_id, cat_data in PRIVATE_PHOTO_CATEGORIES.items():
            name_key = f'name_{"en" if lang == EN else "ru"}'
            raw_name = cat_data.get(name_key, cat_data['name_ru'])
            # Strip leading emoji characters from category name
            clean_name = re.sub(r'^[^\w\s]+\s*', '', raw_name).strip() or raw_name
            cost = get_category_cost(cat_id)
            items.append({
                'id': cat_id,
                'emoji': '',
                'title': clean_name,
                'subtitle': (('⭐ Premium only' if lang == EN else '⭐ только с Premium') if prem_only
                             else f"{cost} \U0001f351"),
                'locked': False,
                'types': [{"id": t["id"], "name": t.get(name_key, t["name_ru"])} for t in cat_data.get('types', [])],
                # V3.45.26: colour step is shown only for apparel categories
                'has_color': cat_id in ('lingerie', 'suggestive', 'roleplay'),
                # V3.64.3: the type names the place — no location step
                'has_location': cat_id not in PLACE_TYPED_CATEGORIES,
            })
        locations = [{'id': loc['id'], 'name': loc.get(f'name_{"en" if lang == EN else "ru"}', loc['name_ru'])} for loc in LOCATIONS]
        moods = [{'id': m['id'], 'name': m.get(f'name_{"en" if lang == EN else "ru"}', m['name_ru'])} for m in MOODS]
        colors = [{'id': c['id'], 'name': c.get(f'name_{"en" if lang == EN else "ru"}', c['name_ru'])} for c in LINGERIE_COLORS]
        title = 'Private' if lang == EN else 'Наедине'
        return web.json_response({'ok': True, 'kind': kind, 'title': title, 'items': items,
                                  'locations': locations, 'moods': moods, 'colors': colors})
    # V3.45.0: Косплей — персонажи
    if kind == 'cosplay':
        from services.private_photo_service import COSPLAY_CHARACTERS, get_private_photo_usage
        usage = get_private_photo_usage(telegram_id)
        items = []
        for c in COSPLAY_CHARACTERS:
            items.append({
                'id': c['id'],
                'emoji': '🎭',
                'title': c['name'],
                'subtitle': c.get('outfit', '')[:40],
                'locked': False,
            })
        title = '🎭 Cosplay' if lang == EN else '🎭 Косплей'
        return web.json_response({'ok': True, 'kind': kind, 'title': title, 'items': items})
    # V3.45.0: Видео
    if kind == 'video':
        items = [{'id': 'video', 'emoji': '🎬', 'title': 'Сделать видео из фото' if lang == RU else 'Make video from photo',
                  'subtitle': f'{VIDEO_PEACH_COST} 🍑', 'locked': False}]
        title = '🎬 Video' if lang == EN else '🎬 Видео'
        return web.json_response({'ok': True, 'kind': kind, 'title': title, 'items': items})
    # V3.50.1: this fall-through branch is the daily-quest menu. couple_service
    # is imported locally (like the POST action branch and the bot handler) —
    # without it V3.49.0 raised NameError here, the V3.48.3 wrapper turned it
    # into 'temporarily_unavailable', and the app-chat «Задание» button broke.
    from services import couple_service
    quests = couple_service.daily_quests_state(telegram_id)
    _, quest_text = couple_service.daily_quest(telegram_id)
    user = get_user(telegram_id)
    completed = int(getattr(user, 'quests_completed', 0) or 0) if user else 0
    claimed = bool(user and (user.quest_claimed_date or '') == couple_service._today_key())
    # V3.49.0: the next story still gated behind the daily-task ladder, so the
    # sheet can show "N more tasks -> story «...» unlocks". Legacy 'text'/
    # 'claimed' stay for old clients; 'quests' is the new 2-3 item checklist.
    next_unlock = None
    for st in story_status(telegram_id, level):
        if not st['unlocked'] and not st['tasks_ok']:
            next_unlock = {'title': st['title'], 'remaining': st['tasks_remaining']}
            break
    title = '🎯 Daily quest' if lang == EN else '🎯 Задание дня'
    return web.json_response({'ok': True, 'kind': kind, 'title': title,
                              'text': quest_text, 'claimed': claimed,
                              'quests': quests, 'quests_completed': completed,
                              'next_unlock': next_unlock})


async def _deliver_bonus_media(telegram_id: int, character_id: str, uid: int):
    """V3.51.1: drop a spontaneous free photo of the ACTUAL character into the
    shared dialog. V3.49.0 pulled from the owner's generic Anna pool, which
    showed the wrong face for community girls. Never mints peaches/Stars
    (V3.46.0 rule) - it renders one safe everyday frame through the normal app
    photo path. Returns the /webapp/media URL, or None when the render fails."""
    try:
        data, mime, ext = await _webapp_media_photo(telegram_id, character_id, 'selfie')
        if not data:
            return None
        # V3.57.2: the two dialog writes are PostgreSQL round-trips
        def _store():
            filename = webapp_service.save_chat_media(telegram_id, data, ext, mime or 'image/jpeg')
            save_message(uid, character_id, 'assistant',
                         'захотелось поделиться с тобой этим кадром 📸',
                         media_kind='photo', media_url=f'/webapp/media/{filename}')
            return f'/webapp/media/{filename}'
        return await asyncio.to_thread(_store)
    except Exception:
        logger.exception('bonus media delivery failed')
        return None


async def _webapp_api_feature_action(request: web.Request) -> web.Response:
    # V3.55.7: exception-guarded wrapper, mirroring the V3.48.3 GET wrapper. A
    # transient DB blip in the shared prologue (ensure_user / get_relationship_level
    # write on every call) used to surface as a raw HTTP 500 whose HTML body the
    # Mini App could not parse — so the «Задание» sheet showed «Не получилось
    # ответить — попробуй ещё раз». Log the real cause and answer with clean JSON.
    try:
        return await _webapp_api_feature_action_impl(request)
    except Exception:
        logger.exception('webapp feature action failed')
        return web.json_response({'ok': False, 'error': 'temporarily_unavailable'})


async def _webapp_api_feature_action_impl(request: web.Request) -> web.Response:
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
    # V3.57.2: the consent/selection/level prologue is four PostgreSQL reads
    def _prologue():
        if not has_accepted(telegram_id):
            return None
        cid = str(body.get('character_id', '')) or get_user_character(telegram_id)
        uid_ = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
        return cid, uid_, get_relationship_level(telegram_id, cid)
    prepared = await asyncio.to_thread(_prologue)
    if prepared is None:
        return web.json_response({'ok': False, 'error': 'consent'}, status=403)
    character_id, uid, level = prepared
    user_name = user_info.get('first_name') or ''

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
        action = apartment_service.USER_ACTIONS.get(action_id, '')
        answer = await _feature_scene_turn(telegram_id, user_info, character_id, action,
                                           apartment_service.scene_direction(room, action_id))
        if answer:
            return web.json_response({'ok': True, 'kind': kind, 'text': answer, 'user_text': action})
        await asyncio.to_thread(save_message, uid, character_id, 'assistant', text)
        return web.json_response({'ok': True, 'kind': kind, 'text': text})

    if kind == 'quest':
        from services import couple_service
        # V3.49.0: claim one of today's 2-3 tasks by key (falls back to the
        # primary quest for old clients that send no quest_key).
        quest_key = str(body.get('quest_key', '')) or couple_service.daily_quest(telegram_id)[0]
        result = couple_service.claim_quest(telegram_id, quest_key)
        if not result:
            return web.json_response({'ok': False, 'error': 'already'}, status=409)
        if result.get('not_done'):
            # V3.59.1: the task is checked against today's dialog, not trusted.
            return web.json_response({'ok': False, 'error': 'not_done'}, status=409)
        # V3.55.7: claim_quest has committed the +5 by this point. The event
        # track, the dialog echo and the best-effort bonus photo must never turn
        # a successful claim into a raw 500 — a transient DB blip here used to
        # make the sheet say «Не получилось ответить» even though the quest had
        # in fact counted. Guard the tail and always answer ok for a fresh claim.
        text = ('mmm, nice 😊 +5 attention points. she noticed.' if user_lang(telegram_id) == EN
                else 'ммм, приятно 😊 +5 очков внимания. она заметила.')
        bonus_url = None
        try:
            track_event(uid, 'daily_quest_claimed', metadata={'source': 'webapp', 'quest': quest_key})
            save_message(uid, character_id, 'assistant', text)
            if result.get('bonus_media'):
                bonus_url = await _deliver_bonus_media(telegram_id, character_id, uid)
        except Exception:
            logger.exception('webapp quest post-claim tail failed user=%s quest=%s', telegram_id, quest_key)
        return web.json_response({'ok': True, 'kind': kind, 'text': text,
                                  'quests_completed': result.get('quests_completed'),
                                  'bonus_media': bool(bonus_url),
                                  'photo_url': bonus_url})

    date = dates_service.get(str(body.get('id', '')))
    if not date or date.min_level > level:
        return web.json_response({'ok': False, 'error': 'locked'}, status=403)
    from services.gamification_service import (
        completed_date_ids, consume_free_date, has_free_date, unlock_achievement,
    )
    # V3.45: dates cost peaches (not Stars). Free-streak / admin bypass.
    # V3.65.0: the date's Stars figure × PEACH_SCALE peaches.
    if telegram_id not in ADMIN_TELEGRAM_IDS and not has_free_date(telegram_id):
        _date_peaches = date.cost * PEACH_SCALE
        if get_photo_credits(telegram_id) < _date_peaches:
            return web.json_response({'ok': False, 'error': 'insufficient_peaches', 'cost': _date_peaches}, status=402)
        spend_peaches(telegram_id, _date_peaches)
    elif has_free_date(telegram_id):
        consume_free_date(telegram_id)
    await record_user_message(telegram_id, user_name, relationship=date.affection, intimacy=date.affection / 2,
                              event_type='date', reason=f'date:{date.id}', character_id=character_id)
    unlock_achievement(telegram_id, 'first_date')
    completed = completed_date_ids(telegram_id)
    if len(completed) >= 10:
        unlock_achievement(telegram_id, 'ten_dates')
    if len(completed) >= len(dates_service.get_all()):
        unlock_achievement(telegram_id, 'date_collector')
    track_event(uid, 'webapp_date_delivered', metadata={'date': date.id})
    narration = f'{date.emoji} {date.text}'
    action = dates_service.user_action(date)
    answer = await _feature_scene_turn(telegram_id, user_info, character_id, action,
                                       dates_service.scene_direction(date))
    if answer:
        narration = answer
    else:
        await asyncio.to_thread(save_message, uid, character_id, 'assistant', narration)
    # V3.58.1: the reward photo can take minutes (engine fallbacks), and the
    # Mini App used to sit on this request with no feedback — the owner tapped
    # «Кофейня» and saw nothing at all. Answer with the narration right away and
    # let the photo land in the shared dialog in the background; the SPA polls
    # the chat history until it shows up.
    _spawn_background(_deliver_date_photo(telegram_id, character_id, uid, date.id, date.scene))
    return web.json_response({'ok': True, 'kind': kind, 'delivered': True,
                              'text': narration, 'user_text': action if answer else '',
                              'photo_url': None, 'photo_pending': True})


async def _feature_scene_turn(telegram_id: int, user_info: dict, character_id: str,
                              action: str, scene: str) -> str:
    """V3.64.3: «Квартира / Свидание не цепляют» — play the tap as a live scene
    through the normal dialog pipeline (persona, memory, level): his action is
    saved as his message, she answers in character with a hook. Returns '' on
    any failure so the caller falls back to the old canned line."""
    if not action:
        return ''
    try:
        return await anna_reply(
            telegram_id, user_info.get('first_name') or 'ты', action,
            language_code=user_info.get('language_code'), character_id=character_id, scene=scene,
        ) or ''
    except Exception:
        logger.exception('feature scene turn failed user=%s character=%s', telegram_id, character_id)
        return ''


_BACKGROUND_TASKS: set = set()


async def _after_premium_paid(telegram_id: int, product: str) -> None:
    """V3.104.0 (services/paid_welcome.py): right after a Premium payment —
    open his loyalty month (first payment only), show «что теперь открыто»
    with buttons, then she writes herself. Fail-silent: the payment and its
    confirmation never depend on this."""
    from services import paid_welcome, vip_offer
    try:
        await asyncio.sleep(3)
        if not await asyncio.to_thread(is_premium, telegram_id):
            return
        loyal = await asyncio.to_thread(vip_offer.open_loyalty, telegram_id, product)
        uid = await asyncio.to_thread(ensure_user, telegram_id)
        if loyal:
            await asyncio.to_thread(track_event, uid, 'loyal_offer_opened_shown', metadata={'product': product})
        if not paid_welcome.ENABLED:
            return
        lang = 'en' if await asyncio.to_thread(user_lang, telegram_id) == EN else 'ru'
        en = lang == 'en'
        character_id = await asyncio.to_thread(get_user_character, telegram_id)
        text = paid_welcome.unlocked_text(product, lang, PREMIUM_TRIAL_DAYS)
        rows = []
        if PUBLIC_BASE_URL:
            rows.append([InlineKeyboardButton(text='💬 to her chat' if en else '💬 открыть наш чат',
                                              web_app=types.WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp?open=chat'))])
        rows.append([InlineKeyboardButton(text='🌶 Spicy mode' if en else '🌶 Пошлый режим', callback_data='spicy:menu')])
        vinfo = await asyncio.to_thread(vip_offer.info, telegram_id)
        if loyal and vinfo.get('active') and vinfo.get('loyal'):
            text += paid_welcome.loyal_line(vinfo['percent'], vinfo.get('rub'), PLATEGA_PREMIUM_PRICE_RUB,
                                            vinfo['stars'], lang)
            if vinfo.get('rub') and not en and is_button_enabled('platega_rub'):
                rows.append([_platega_pay_button(vip_offer.PRODUCT, vinfo['rub'],
                                                 f'💝 месяц за {vinfo["rub"]} ₽ · карта / СБП')])
            rows.append([InlineKeyboardButton(
                text=(f'💝 a month −{vinfo["percent"]}% — {vinfo["stars"]} Stars' if en
                      else f'💝 месяц −{vinfo["percent"]}% — {vinfo["stars"]} Stars'),
                callback_data='buy:premium_vip')])
        await bot.send_message(telegram_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await asyncio.to_thread(paid_welcome.mark, uid, paid_welcome.CARD_EVENT, character_id, product)
        await _deliver_showcase_photo(telegram_id, uid, lang)
        # she «types» for a moment, then writes herself
        await asyncio.sleep(paid_welcome.HEROINE_DELAY_SECONDS)
        try:
            await bot.send_chat_action(telegram_id, 'typing')
        except Exception:
            pass
        from services.chat_service import paid_moment
        msg = await paid_moment(telegram_id, '', 'welcome', language_code='en' if en else None,
                                character_id=character_id)
        msg = msg or paid_welcome.fallback('welcome', lang)
        await bot.send_message(telegram_id, msg)
        await asyncio.to_thread(save_message, uid, character_id, 'assistant', msg)
        await asyncio.to_thread(paid_welcome.mark, uid, paid_welcome.WELCOME_EVENT, character_id, product)
    except Exception:
        logger.warning('paid welcome failed user=%s product=%s', telegram_id, product, exc_info=True)


async def _deliver_showcase_photo(telegram_id: int, uid: int, lang: str) -> None:
    """V3.111.0: the photo that was blurred on his first-hour card, clean,
    once — the card said «открою», so after the payment it opens."""
    from services import first_offer_service as fos
    try:
        pending = await asyncio.to_thread(fos.take_pending_photo, telegram_id)
        if not pending:
            return
        caption = fos.deliver_caption(lang)
        if pending.get('fid'):
            await bot.send_photo(telegram_id, pending['fid'], caption=caption)
        else:
            path = Path(pending.get('path') or '')
            if not path.is_file():
                return
            def _jpg() -> bytes:
                import io
                from PIL import Image
                img = Image.open(path).convert('RGB')
                img.thumbnail((1080, 1440))
                buf = io.BytesIO()
                img.save(buf, 'JPEG', quality=90)
                return buf.getvalue()
            body = await asyncio.to_thread(_jpg)
            await bot.send_photo(telegram_id, types.BufferedInputFile(body, filename='for_you.jpg'), caption=caption)
        await asyncio.to_thread(track_event, uid, 'showcase_photo_delivered')
    except Exception:
        logger.warning('showcase photo delivery failed user=%s', telegram_id, exc_info=True)


def _spawn_background(coro) -> None:
    """Run a fire-and-forget coroutine, keeping a strong reference so the
    event loop cannot garbage-collect it mid-flight."""
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


async def _deliver_scene_photo(telegram_id: int, character_id: str, uid: int, scene: str,
                               caption: str, what: str) -> None:
    """V3.58.3: a story reward photo, rendered after the response went out."""
    try:
        data, mime, ext = await _webapp_media_scene(telegram_id, character_id, scene)
        if data:
            filename = webapp_service.save_chat_media(telegram_id, data, ext, mime)
            photo_url = f'/webapp/media/{filename}'
            await asyncio.to_thread(save_message, uid, character_id, 'assistant', caption,
                                    media_kind='photo', media_url=photo_url)
            _app_ping(telegram_id, character_id, caption, 'photo')
        else:
            logger.warning('webapp %s photo empty user=%s scene=%s', what, telegram_id, scene)
            await asyncio.to_thread(webapp_service.record_generation_failure, telegram_id, 'photo', character_id, scene, f'{what}: empty')
    except Exception as exc:
        logger.exception('webapp %s photo failed user=%s scene=%s', what, telegram_id, scene)
        await asyncio.to_thread(webapp_service.record_generation_failure, telegram_id, 'photo', character_id, scene, f'{what}: {type(exc).__name__}: {exc}')


async def _deliver_date_photo(telegram_id: int, character_id: str, uid: int, date_id: str, scene: str) -> None:
    """V3.58.1: the date reward photo, rendered after the response went out."""
    try:
        data, mime, ext = await _webapp_media_scene(telegram_id, character_id, scene)
        if data:
            filename = webapp_service.save_chat_media(telegram_id, data, ext, mime)
            photo_url = f'/webapp/media/{filename}'
            save_message(uid, character_id, 'assistant', '📸 фото с нашей прогулки', media_kind='photo', media_url=photo_url)
            _app_ping(telegram_id, character_id, '📸 фото с нашей прогулки', 'photo')
        else:
            logger.warning('webapp date photo empty user=%s date=%s', telegram_id, date_id)
    except Exception as exc:
        logger.exception('webapp date photo failed user=%s date=%s', telegram_id, date_id)
        await asyncio.to_thread(webapp_service.record_generation_failure, telegram_id, 'photo', character_id, scene, f'date: {type(exc).__name__}: {exc}')


# ── V3.114.0: «👗 Гардероб» — clothes and room things for her, for peaches ──
def _wardrobe_auth(request: web.Request):
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return None
    user_info = webapp_service.init_data_user(pairs)
    return user_info if user_info.get('id') else None


def _wardrobe_adult_open(telegram_id: int) -> bool:
    from services import wardrobe_service
    return wardrobe_service.can_buy_adult(premium=is_premium(telegram_id), adult=is_adult_confirmed(telegram_id),
                                          admin=telegram_id in ADMIN_TELEGRAM_IDS)


async def _webapp_api_wardrobe(request: web.Request) -> web.Response:
    user_info = _wardrobe_auth(request)
    if not user_info:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = int(user_info['id'])

    def _load():
        from services import wardrobe_service
        cid = str(request.query.get('character_id', '')) or get_user_character(telegram_id)
        lang = 'en' if user_lang(telegram_id) == EN else 'ru'
        data = wardrobe_service.catalog(telegram_id, cid, lang, adult_open=_wardrobe_adult_open(telegram_id))
        return dict(data, ok=True, character_id=cid, credits=get_photo_credits(telegram_id))
    try:
        return web.json_response(await asyncio.to_thread(_load))
    except Exception:
        logger.exception('webapp wardrobe load failed user=%s', telegram_id)
        return web.json_response({'ok': False, 'error': 'temporarily_unavailable'})


async def _webapp_api_wardrobe_buy(request: web.Request) -> web.Response:
    try:
        return await _webapp_api_wardrobe_buy_impl(request)
    except Exception:
        logger.exception('webapp wardrobe buy failed')
        return web.json_response({'ok': False, 'error': 'temporarily_unavailable'})


async def _webapp_api_wardrobe_buy_impl(request: web.Request) -> web.Response:
    from services import wardrobe_service
    user_info = _wardrobe_auth(request)
    if not user_info:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = int(user_info['id'])
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    item = wardrobe_service.get(str(body.get('item_id', '')))
    if not item:
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    admin = telegram_id in ADMIN_TELEGRAM_IDS

    def _charge():
        if not has_accepted(telegram_id):
            return {'error': 'consent', 'status': 403}
        cid = str(body.get('character_id', '')) or get_user_character(telegram_id)
        uid_ = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
        if item.kind == 'adult' and not _wardrobe_adult_open(telegram_id):
            return {'error': 'adult' if is_premium(telegram_id) else 'premium_required', 'status': 403}
        if item.slot and not wardrobe_service.home_state(telegram_id, cid)['style']:
            return {'error': 'need_style', 'status': 409}
        prev_slot = wardrobe_service.home_state(telegram_id, cid)['slots'].get(item.slot, '') if item.slot else ''
        if item.id in wardrobe_service.owned_ids(telegram_id, cid):
            return {'error': 'owned', 'status': 409}
        if not admin and not spend_peaches(telegram_id, item.price):
            return {'error': 'insufficient_peaches', 'cost': item.price, 'status': 402}
        if not wardrobe_service.grant(telegram_id, cid, item.id):
            if not admin:
                add_peaches(telegram_id, item.price)
            return {'error': 'owned', 'status': 409}
        track_event(uid_, 'wardrobe_buy', character_id=cid,
                    metadata={'item': item.id, 'kind': item.kind, 'price': 0 if admin else item.price})
        return {'cid': cid, 'uid': uid_, 'prev_slot': prev_slot if item.slot else ''}
    res = await asyncio.to_thread(_charge)
    if res.get('error'):
        status = res.pop('status', 400)
        return web.json_response(dict(res, ok=False), status=status)
    character_id, uid = res['cid'], res['uid']
    user_name = user_info.get('first_name') or ''
    await record_user_message(telegram_id, user_name,
                              relationship=wardrobe_service.ROOM_RELATIONSHIP if item.kind == 'room' else wardrobe_service.WEAR_RELATIONSHIP,
                              trust=0.3, event_type='gift', reason=f'wardrobe:{item.id}', character_id=character_id)
    lang = 'en' if user_lang(telegram_id) == EN else 'ru'
    action = wardrobe_service.gift_action(item, lang)
    try:
        from services.character_registry import get_character as _gc
        name = (_gc(character_id) or {}).get('name') or ''
    except Exception:
        name = ''
    answer = await _feature_scene_turn(telegram_id, user_info, character_id, action,
                                       wardrobe_service.gift_scene(item, name))
    if not answer:
        answer = ('Oh, thank you! 😍 Give me a minute…' if lang == 'en'
                  else 'Это мне?! 😍 Спасибо… подожди минутку')
        await asyncio.to_thread(save_message, uid, character_id, 'assistant', answer)
    if item.slot:
        _spawn_background(_render_home(telegram_id, character_id, uid, item_id=item.id,
                                       replaced=res.get('prev_slot', ''), refund=0 if admin else CHAT_PHOTO_PEACH_COST))
    else:
        _spawn_background(_deliver_wardrobe_photo(telegram_id, character_id, uid, item.id, refund=not admin))
    return web.json_response({'ok': True, 'text': answer, 'user_text': action if answer else '',
                              'photo_pending': True, 'credits': await asyncio.to_thread(get_photo_credits, telegram_id)})


async def _deliver_wardrobe_photo(telegram_id: int, character_id: str, uid: int, item_id: str, *, refund: bool) -> None:
    """The try-on photo included in the price. On a failed render the photo part
    (CHAT_PHOTO_PEACH_COST) goes back and she says so — the item stays his."""
    from services import wardrobe_service
    item = wardrobe_service.get(item_id)
    if not item:
        return
    if item.kind in ('wear', 'adult'):
        req = PhotoRequest(scene=item.tryon, clothing=item.prompt)
    elif item.kind == 'jewel':
        req = PhotoRequest(scene=item.tryon, accessory=item.prompt)
    else:
        req = PhotoRequest(scene='home')  # room things come in through photo_overrides
    try:
        data, mime, ext = await _webapp_pipeline_photo(telegram_id, character_id, req)
    except Exception as exc:
        logger.exception('wardrobe try-on photo failed user=%s item=%s', telegram_id, item_id)
        await asyncio.to_thread(webapp_service.record_generation_failure, telegram_id, 'photo', character_id,
                                item_id, f'wardrobe: {type(exc).__name__}: {exc}')
        data = None
    if data:
        def _save():
            filename = webapp_service.save_chat_media(telegram_id, data, ext, mime)
            cap = '📸 ' + ('в твоём подарке' if item.kind != 'room' else 'смотри, как теперь у меня')
            save_message(uid, character_id, 'assistant', cap, media_kind='photo', media_url=f'/webapp/media/{filename}')
            return cap
        _app_ping(telegram_id, character_id, await asyncio.to_thread(_save), 'photo')
        return
    def _sorry():
        back = 0
        if refund:
            back = CHAT_PHOTO_PEACH_COST
            add_peaches(telegram_id, back)
        text = ('фото сейчас не получилось 🙈 подарок у меня, а за фото вернула тебе '
                f'{back} 🍑' if back else 'фото сейчас не получилось 🙈 но подарок уже у меня')
        save_message(uid, character_id, 'assistant', text)
        track_event(uid, 'wardrobe_photo_failed', character_id=character_id, metadata={'item': item_id})
    await asyncio.to_thread(_sorry)


async def _render_home(telegram_id: int, character_id: str, uid: int, *, item_id: str = '',
                       replaced: str = '', refund: int = 0) -> None:
    """V3.116.0: «🏠 Дом» — redraw her room. With a previous picture and one new
    thing it is an EDIT of that picture (the room stays the same room); a new
    style or a first picture is drawn from scratch. The picture lands in the
    chat as her message and becomes the room view. On failure `refund` peaches go back."""
    from services import spicy_jobs, spend_service, wardrobe_service
    from config import SPICYAPI_IMAGE_MODEL, SPICYAPI_T2I_MODEL
    home = await asyncio.to_thread(wardrobe_service.home_state, telegram_id, character_id)
    prev = None
    if item_id and home['image']:
        path = await asyncio.to_thread(webapp_service.chat_media_file_path, telegram_id, home['image'])
        if path:
            prev = await asyncio.to_thread(path.read_bytes)
    block = {'aspect_ratio': '4:3', 'resolution': '1k', 'output_format': 'png', 'enable_thinking': True}
    data = None
    ok, cost = False, 0.0
    try:
        allowed, _why = await asyncio.to_thread(budget_allows_photo)
        if not allowed:
            raise RuntimeError('budget')
        if prev:
            uri = await spicy_jobs.upload(prev, 'image/jpeg' if prev[:2] == b'\xff\xd8' else 'image/png')
            block.update(prompt=wardrobe_service.room_prompt_edit(item_id, replaced), image_urls=[uri])
            data, _mime, cost = await spicy_jobs.run(SPICYAPI_IMAGE_MODEL, block, timeout=240)
        else:
            block['prompt'] = wardrobe_service.room_prompt_full(home['style'], home['active'])
            data, _mime, cost = await spicy_jobs.run(SPICYAPI_T2I_MODEL, block, timeout=240)
        ok = bool(data)
    except Exception as exc:
        logger.exception('home render failed user=%s item=%s', telegram_id, item_id)
        await asyncio.to_thread(webapp_service.record_generation_failure, telegram_id, 'photo', character_id,
                                item_id or 'home', f'home: {type(exc).__name__}: {exc}')
    finally:
        await asyncio.to_thread(spend_service.record_image_spend, 'spicyapi', 'home', cost, billed=ok, success=ok)

    def _finish():
        if data:
            ext = 'png' if data[:8] == b'\x89PNG\r\n\x1a\n' else 'jpg'
            filename = webapp_service.save_chat_media(telegram_id, data, ext, 'image/png' if ext == 'png' else 'image/jpeg')
            wardrobe_service.set_room_image(telegram_id, character_id, filename)
            cap = '📸 смотри, как теперь у меня 🏠' if item_id else '📸 вот моя новая комната 🏠 обставим вместе?'
            save_message(uid, character_id, 'assistant', cap, media_kind='room', media_url=f'/webapp/media/{filename}')
            track_event(uid, 'home_render', character_id=character_id, metadata={'item': item_id or 'style', 'edit': bool(prev)})
            return cap
        if refund:
            add_peaches(telegram_id, refund)
        save_message(uid, character_id, 'assistant',
                     'фото комнаты сейчас не получилось 🙈 всё стоит на месте' + (f', а за фото вернула тебе {refund} 🍑' if refund else ''))
        track_event(uid, 'home_render_failed', character_id=character_id, metadata={'item': item_id or 'style'})
        return None
    cap = await asyncio.to_thread(_finish)
    if cap:
        _app_ping(telegram_id, character_id, cap, 'photo')


async def _webapp_api_home_style(request: web.Request) -> web.Response:
    """Pick her room style: the first one is free, a change costs STYLE_CHANGE_PRICE."""
    from services import wardrobe_service
    user_info = _wardrobe_auth(request)
    if not user_info:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = int(user_info['id'])
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    style_id = str(body.get('style_id', ''))
    if not wardrobe_service.get_style(style_id):
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    admin = telegram_id in ADMIN_TELEGRAM_IDS

    def _apply():
        if not has_accepted(telegram_id):
            return {'error': 'consent', 'status': 403}
        cid = str(body.get('character_id', '')) or get_user_character(telegram_id)
        uid_ = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
        cur = wardrobe_service.home_state(telegram_id, cid)['style']
        if cur == style_id:
            return {'error': 'same', 'status': 409}
        price = wardrobe_service.STYLE_CHANGE_PRICE if (cur and not admin) else 0
        if price and not spend_peaches(telegram_id, price):
            return {'error': 'insufficient_peaches', 'cost': price, 'status': 402}
        if not wardrobe_service.set_style(telegram_id, cid, style_id):
            if price:
                add_peaches(telegram_id, price)
            return {'error': 'temporarily_unavailable', 'status': 500}
        track_event(uid_, 'home_style', character_id=cid, metadata={'style': style_id, 'price': price})
        return {'cid': cid, 'uid': uid_, 'price': price}
    res = await asyncio.to_thread(_apply)
    if res.get('error'):
        status = res.pop('status', 400)
        return web.json_response(dict(res, ok=False), status=status)
    _spawn_background(_render_home(telegram_id, res['cid'], res['uid'], refund=res['price']))
    return web.json_response({'ok': True, 'photo_pending': True,
                              'credits': await asyncio.to_thread(get_photo_credits, telegram_id)})


async def _webapp_api_home_place(request: web.Request) -> web.Response:
    """Put back a thing she already has (one new room picture, HOME_REDRAW_PRICE)."""
    from services import wardrobe_service
    user_info = _wardrobe_auth(request)
    if not user_info:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = int(user_info['id'])
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    item = wardrobe_service.get(str(body.get('item_id', '')))
    if not item or not item.slot:
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    admin = telegram_id in ADMIN_TELEGRAM_IDS

    def _apply():
        cid = str(body.get('character_id', '')) or get_user_character(telegram_id)
        uid_ = ensure_user(telegram_id)
        home = wardrobe_service.home_state(telegram_id, cid)
        if item.id not in wardrobe_service.owned_ids(telegram_id, cid):
            return {'error': 'not_owned', 'status': 403}
        if home['slots'].get(item.slot) == item.id:
            return {'error': 'same', 'status': 409}
        price = 0 if admin else wardrobe_service.HOME_REDRAW_PRICE
        if price and not spend_peaches(telegram_id, price):
            return {'error': 'insufficient_peaches', 'cost': price, 'status': 402}
        wardrobe_service.place(telegram_id, cid, item.id)
        return {'cid': cid, 'uid': uid_, 'price': price, 'prev': home['slots'].get(item.slot, '')}
    res = await asyncio.to_thread(_apply)
    if res.get('error'):
        status = res.pop('status', 400)
        return web.json_response(dict(res, ok=False), status=status)
    _spawn_background(_render_home(telegram_id, res['cid'], res['uid'], item_id=item.id,
                                   replaced=res['prev'], refund=res['price']))
    return web.json_response({'ok': True, 'photo_pending': True,
                              'credits': await asyncio.to_thread(get_photo_credits, telegram_id)})


async def _webapp_api_wardrobe_wear(request: web.Request) -> web.Response:
    from services import wardrobe_service
    user_info = _wardrobe_auth(request)
    if not user_info:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = int(user_info['id'])
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    cid = str(body.get('character_id', '')) or await asyncio.to_thread(get_user_character, telegram_id)
    item_id = str(body.get('item_id', ''))
    item = wardrobe_service.get(item_id)
    if item and item.kind == 'adult' and not await asyncio.to_thread(_wardrobe_adult_open, telegram_id):
        return web.json_response({'ok': False, 'error': 'premium_required'}, status=403)
    ok = await asyncio.to_thread(wardrobe_service.wear, telegram_id, cid, item_id)
    return web.json_response({'ok': bool(ok)})


async def _webapp_api_wardrobe_pet(request: web.Request) -> web.Response:
    from services import wardrobe_service
    user_info = _wardrobe_auth(request)
    if not user_info:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = int(user_info['id'])
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    cid = str(body.get('character_id', '')) or await asyncio.to_thread(get_user_character, telegram_id)
    name = await asyncio.to_thread(wardrobe_service.set_pet_name, telegram_id, cid, str(body.get('name', '')))
    if not name:
        return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
    def _note():
        uid_ = ensure_user(telegram_id)
        save_message(uid_, cid, 'user', f'*называю котёнка: {name}* 🐈')
        save_message(uid_, cid, 'assistant', f'{name}! 😍 ему идёт. Слышишь, {name}? Это тебя так зовут теперь 🐾')
    await asyncio.to_thread(_note)
    return web.json_response({'ok': True, 'name': name})


async def _webapp_api_story(request: web.Request) -> web.Response:
    # V3.57.2: the story list reads the ladder, the quests and the relationship
    # row — all synchronous PostgreSQL work, off the event loop.
    return await asyncio.to_thread(_webapp_api_story_impl, request)


def _webapp_api_story_impl(request: web.Request) -> web.Response:
    # V3.51.0: the Mini App story player list. The same story_status the bot
    # keyboard reads, serialized for the SPA (labels only; results/reactions come
    # from the action endpoint). The path axis itself is shown on the character
    # card, so here we only expose the qualitative gates.
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    character_id = str(request.query.get('character_id', '')) or get_user_character(telegram_id)
    ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
    level = get_relationship_level(telegram_id, character_id)
    stories = []
    for st in story_status(telegram_id, level, character_id):
        q = get_quest(st['key'])
        routes = [{'key': rk, 'label': rv.get('label', ''), 'done': rk in st['done'],
                   'beat': bool(route_branch(st['key'], rk)),
                   # V3.59.3: «+8 к страсти / нежности» next to the choice; only
                   # the first (canonical) answer moves the path, so 0 after it.
                   'points': route_points(st['key'], rk) if not st['canonical'] else 0}
                  for rk, rv in q['routes'].items()]
        stories.append({'key': st['key'], 'title': st['title'], 'teaser': st.get('teaser', ''),
                        'intro': q.get('intro', ''), 'unlocked': st['unlocked'], 'min_level': st['min_level'],
                        'unlock_tasks': st['unlock_tasks'], 'tasks_remaining': st['tasks_remaining'],
                        'level_ok': st['level_ok'], 'tasks_ok': st['tasks_ok'],
                        'path': st.get('path'), 'path_ok': st.get('path_ok', True), 'branch': st.get('branch'),
                        'canonical': st['canonical'], 'routes': routes})
    return web.json_response({'ok': True, 'kind': 'story', 'level': level, 'stories': stories})


async def _webapp_api_story_action(request: web.Request) -> web.Response:
    # V3.51.0: play a story choice (or its second beat) from the Mini App. Runs
    # the exact resolver the bot uses, so branching, threshold scenes and the
    # live reaction behave identically; the reaction is persisted to the shared
    # dialog. A reward photo (route or deep-crossing event) is generated here
    # only when the current stage allows that scene.
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
    # V3.57.2: the whole gate prologue is a chain of PostgreSQL reads
    def _prologue():
        if not has_accepted(telegram_id):
            return 'consent'
        cid = str(body.get('character_id', '')) or get_user_character(telegram_id)
        qk = str(body.get('quest_key', ''))
        quest = get_quest(qk)
        if not quest:
            return 'bad_request'
        uid_ = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
        lvl = get_relationship_level(telegram_id, cid)
        st_ = next((x for x in story_status(telegram_id, lvl, cid) if x['key'] == qk), None)
        if not st_ or not st_['unlocked']:
            return 'locked'
        return cid, qk, quest, uid_, lvl, st_
    prepared = await asyncio.to_thread(_prologue)
    if isinstance(prepared, str):
        if prepared == 'consent':
            return web.json_response({'ok': False, 'error': 'consent'}, status=403)
        if prepared == 'bad_request':
            return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
        return web.json_response({'ok': False, 'error': 'locked'}, status=403)
    character_id, quest_key, q, uid, level, st = prepared
    uname = user_info.get('first_name') or ''
    beat = body.get('beat')
    if isinstance(beat, dict) and beat.get('route_key') and beat.get('opt_key'):
        result = await resolve_story_beat(telegram_id, character_id, quest_key,
                                          str(beat['route_key']), str(beat['opt_key']), user_name=uname)
    else:
        route_key = str(body.get('route_key', ''))
        if route_key not in q['routes']:
            return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
        result = await resolve_story_choice(telegram_id, character_id, quest_key, route_key,
                                            paid_replay=False, user_name=uname)
    if result.get('error'):
        return web.json_response({'ok': False, 'error': result['error']}, status=400)
    if result.get('needs_payment'):
        # Alternative branches are a Stars-replay flow that lives in the bot.
        return web.json_response({'ok': False, 'error': 'replay_locked'}, status=402)
    scene = None
    for ev in result.get('path_events', []):
        if ev.get('photo_scene'):
            scene = ev['photo_scene']
            break
    if not scene and result.get('photo_scene'):
        scene = result['photo_scene']
    photo_url = None
    # V3.57.2: the stage lookup is a PostgreSQL read
    rstage = await asyncio.to_thread(get_relationship_stage, telegram_id, character_id)
    stage_ok = bool(scene) and await asyncio.to_thread(scene_allowed_for_stage, scene, rstage)
    # V3.58.3: the result and her reaction go out at once; the reward photo is
    # rendered in the background and lands in the shared chat (the SPA polls
    # for it), instead of holding the whole answer hostage to the photo chain.
    if stage_ok:
        _spawn_background(_deliver_scene_photo(telegram_id, character_id, uid, scene,
                                               '\U0001f4f8 \u043a\u0430\u0434\u0440 \u043a \u043d\u0430\u0448\u0435\u0439 \u0438\u0441\u0442\u043e\u0440\u0438\u0438', 'story'))
    return web.json_response({
        'ok': True, 'kind': 'story',
        'result_text': result.get('result_text'), 'reaction': result.get('reaction'),
        'path_axis': result.get('path_axis'), 'path_delta': result.get('path_delta'),
        'path_events': [{'text': ev.get('text', ''), 'photo': bool(ev.get('photo_scene'))}
                        for ev in result.get('path_events', [])],
        'beat_options': result.get('beat_options'), 'photo_url': photo_url,
        'photo_pending': bool(stage_ok),
    })


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
    # V3.57.2: the owner-folder resolution touches the media store — off the loop
    path = await asyncio.to_thread(webapp_service.picture_file_path, telegram_id, request.match_info['filename'])
    if not path:
        return web.Response(status=404)
    return web.FileResponse(path, headers={'Cache-Control': 'private, max-age=3600'})


async def _webapp_api_admin_gen_reject(request: web.Request):
    """V3.110.0: owner's «🚫 Брак» on a feed photo — it never goes out as
    the evening photo again (three arms and other mutants)."""
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    if not telegram_id or not webapp_service._is_admin(telegram_id):
        return web.json_response({'ok': False, 'error': 'forbidden'}, status=403)
    try:
        gen_id = int((await request.json()).get('id'))
    except Exception:
        return web.json_response({'ok': False, 'error': 'bad_id'}, status=400)
    from services import evening_voice
    await asyncio.to_thread(evening_voice.reject_generation, gen_id)
    return web.json_response({'ok': True})


async def _webapp_api_admin_generations(request: web.Request) -> web.Response:
    # V3.51.1: the owner's Mini App feed of what users generate. Admin-only
    # (re-checked server-side on every call), newest first, each row enriched
    # with a resolved character name and an admin-scoped thumbnail path.
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    telegram_id = webapp_service.init_data_user(pairs).get('id')
    if not telegram_id or not webapp_service._is_admin(telegram_id):
        return web.json_response({'ok': False, 'error': 'forbidden'}, status=403)
    try:
        offset = max(0, int(request.query.get('offset', '0')))
    except Exception:
        offset = 0
    rows = webapp_service.list_generations(limit=60, offset=offset)
    for r in rows:
        card = webapp_service.get_card(r['character_id']) if r['character_id'] else None
        r['character'] = card.display_name if card else (r['character_id'] or '')
        r['thumb'] = (f"/webapp/api/admin/gen_media/{r['user']}/{r['filename']}"
                      if r['filename'] else None)
    # V3.56.0: the owner wants the money trail, not just the pictures — surface
    # today's authoritative billed image spend (spend_service, includes SpicyAPI
    # failures) next to the feed.
    from services import spend_service
    spent_today = spend_service.image_cost_today()
    return web.json_response({'ok': True, 'generations': rows, 'spent_today_usd': round(spent_today, 4)})


async def _webapp_api_admin_gen_media(request: web.Request) -> web.Response:
    # V3.51.1: serve any user's generated file to an admin — both the studio
    # picture folder and the chat-media folder are tried for the given owner.
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.Response(status=401)
    admin_id = webapp_service.init_data_user(pairs).get('id')
    if not admin_id or not webapp_service._is_admin(admin_id):
        return web.Response(status=403)
    try:
        owner = int(request.match_info['owner'])
    except Exception:
        return web.Response(status=404)
    filename = request.match_info['filename']
    path = (webapp_service.chat_media_file_path(owner, filename)
            or webapp_service.picture_file_path(owner, filename))
    if not path:
        return web.Response(status=404)
    ctype = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
             'webp': 'image/webp', 'mp4': 'video/mp4'}.get(path.suffix.lstrip('.'), 'application/octet-stream')
    return web.Response(body=path.read_bytes(), content_type=ctype,
                        headers={'Cache-Control': 'private, max-age=3600'})


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
    # V3.57.2: wizard steps are read from the DB — off the event loop
    steps = await asyncio.to_thread(webapp_service.api_constructor_steps, _ru_or_en(request.query.get('lang', 'ru')), admin=free)
    return web.json_response({
        'ok': True,
        'steps': steps,
        'stars': CONSTRUCTOR_COST_STARS,
        # V3.36.0: rub + dollar equivalents ride along for the price note.
        'rub': CONSTRUCTOR_COST_RUB,
        'usd': CONSTRUCTOR_PRICE_USD,
        # V3.44.9: peach (photo credit) price — the in-app wizard's main pay path.
        'peaches': CONSTRUCTOR_COST_PEACHES,
        # V3.45.28: creation always costs peaches — the free-public perk is gone.
        'public_free': False,
        'free': free,
        # V3.61.1: one-tap templates that fill the whole form.
        'templates': [{'id': t['id'], 'emoji': t['emoji'], 'title': t['title'], 'name': t['name'],
                       'params': t['params']} for t in CONSTRUCTOR_TEMPLATES],
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
    # V3.44.6: no character limit — users can create unlimited characters.
    params = {}
    photo_reference_base64 = None
    for step in CONSTRUCTOR_STEPS:
        value = params_in.get(step['key'], '')
        # V3.44.4: free_text steps (backstory, personality) accept any text.
        if step.get('free_text'):
            params[step['key']] = str(value)[:500]
        # V3.44.5: photo_upload steps accept file_id or base64 data URL.
        elif step.get('photo_upload'):
            if isinstance(value, str) and value.startswith('data:image'):
                # Base64 data URL from Mini App file input.
                photo_reference_base64 = value
                params[step['key']] = 'base64_pending'
            else:
                params[step['key']] = str(value) if value and value != 'pending_upload' else ''
        elif str(value) and str(value) not in OPTION_LABELS:
            return web.json_response({'ok': False, 'error': 'invalid_params'}, status=400)
        else:
            params[step['key']] = str(value)
    if not name:
        return web.json_response({'ok': False, 'error': 'name_required'}, status=400)
    params['name'] = name
    session_data = {'params': params, 'step': len(CONSTRUCTOR_STEPS)}
    # V3.55.3: the premium tab's ➕ flags its draft; only an admin can set it
    # server-side, so a forged body flag can never mint a premium persona.
    if body.get('premium') and telegram_id in ADMIN_TELEGRAM_IDS:
        session_data['premium'] = True
    # V3.44.5: store base64 photo data in session for _finish_constructor.
    if photo_reference_base64:
        session_data['photo_reference_base64'] = photo_reference_base64
    _constructor_sessions[telegram_id] = session_data
    # V3.44.13: persist the draft so a redeploy between payment and save can
    # resume the creation from Postgres instead of losing the paid persona.
    try:
        save_constructor_draft(telegram_id, params=params, photo_reference_base64=photo_reference_base64)
    except Exception:
        logger.exception('constructor draft persist failed user=%s', telegram_id)
    uid = ensure_user(telegram_id, user_info.get('first_name') or '', language_code=user_info.get('language_code'))
    track_event(uid, 'webapp_constructor_draft')
    return web.json_response({
        'ok': True,
        'stars': CONSTRUCTOR_COST_STARS,
        'free': telegram_id in ADMIN_TELEGRAM_IDS,
    })


async def _webapp_api_constructor_status(request: web.Request) -> web.Response:
    # V3.44.14: is a creation in flight? The app shows a live banner («Создаю
    # Алину…») instead of an empty grid, so a slow avatar reads as progress.
    pairs = webapp_service.validate_init_data(request.query.get('init_data', ''))
    if not pairs:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    user_info = webapp_service.init_data_user(pairs)
    telegram_id = user_info.get('id')
    if not telegram_id:
        return web.json_response({'ok': False, 'error': 'auth'}, status=401)
    creating, name = False, ''
    try:
        draft = get_constructor_draft(telegram_id)
        # V3.44.15: attempts burned through means the sweep gave up (refund +
        # message) — the banner must not claim «Создаю» forever.
        if draft is not None and draft.paid and not draft.done and int(draft.attempts or 0) < MAX_CONSTRUCTOR_ATTEMPTS:
            creating = True
            try:
                name = str((json.loads(draft.params_json or '{}') or {}).get('name') or '')
            except ValueError:
                name = ''
    except Exception:
        logger.exception('constructor status failed user=%s', telegram_id)
    return web.json_response({'ok': True, 'creating': creating, 'name': name})


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
        try:
            mark_constructor_draft_paid(telegram_id, 'webapp_admin')
        except Exception:
            logger.exception('constructor draft mark failed user=%s', telegram_id)
        _spawn_job('constructor', telegram_id, _finish_constructor(telegram_id, None, telegram_id), payload={'source': 'webapp_admin'})
        return web.json_response({'ok': True, 'free': True})
    if consume_constructor_credit(telegram_id):
        record_payment(telegram_id, 'constructor', 0, f'rub_credit:{telegram_id}:{int(_time.time() * 1000)}')
        track_event(uid, 'webapp_constructor_buy', metadata={'product': 'constructor', 'source': 'webapp_credit'})
        try:
            mark_constructor_draft_paid(telegram_id, 'webapp_credit')
        except Exception:
            logger.exception('constructor draft mark failed user=%s', telegram_id)
        _spawn_job('constructor', telegram_id, _finish_constructor(telegram_id, None, telegram_id), payload={'source': 'webapp_credit'})
        return web.json_response({'ok': True, 'free': True})
    # V3.45.28: the free «Сообщество» path is retired — a public persona pays
    # peaches too; publishing to the витрина is handled by the community step.
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    pay_method = str(body.get('method') or '').strip()[:16]
    if pay_method == 'peaches' and telegram_id not in ADMIN_TELEGRAM_IDS:
        # V3.44.9: pay with peaches straight from the app — the same spend
        # pipeline as the bot's «Оплатить персиками» button.
        credits = get_photo_credits(telegram_id)
        if credits < CONSTRUCTOR_COST_PEACHES:
            return web.json_response({'ok': False, 'error': 'no_peaches', 'need': CONSTRUCTOR_COST_PEACHES, 'have': credits}, status=402)
        if not spend_peaches(telegram_id, CONSTRUCTOR_COST_PEACHES):
            return web.json_response({'ok': False, 'error': 'peach_spend_failed'}, status=500)
        record_payment(telegram_id, 'constructor_peaches', 0, f'peaches:{telegram_id}:{int(_time.time() * 1000)}', provider='peaches')
        track_event(uid, 'webapp_constructor_buy', metadata={'product': 'constructor', 'source': 'webapp_peaches'})
        try:
            mark_constructor_draft_paid(telegram_id, 'peaches')
        except Exception:
            logger.exception('constructor draft mark failed user=%s', telegram_id)
        _spawn_job('constructor', telegram_id, _finish_constructor(telegram_id, None, telegram_id, source='peaches'), payload={'source': 'webapp_peaches'})
        return web.json_response({'ok': True, 'free': True, 'peaches': CONSTRUCTOR_COST_PEACHES})
    try:
        link = await bot.create_invoice_link(
            title='Личный персонаж',
            description='Конструктор создаст уникальную собеседницу с аватаром. Платёж одноразовый.',
            payload=f'constructor:{telegram_id}',
            provider_token='',
            currency='XTR',
            prices=[LabeledPrice(label='Личный персонаж', amount=CONSTRUCTOR_COST_STARS)],
        )
    except Exception as exc:
        logger.exception('webapp constructor invoice failed user=%s error=%s', telegram_id, exc)
        return web.json_response({'ok': False, 'error': 'invoice', 'detail': str(exc)[:200]}, status=502)
    track_event(uid, 'webapp_invoice_created', metadata={'product': 'constructor'})
    return web.json_response({'ok': True, 'link': link, 'stars': CONSTRUCTOR_COST_STARS})


async def _start_web_server() -> None:
    # V3.59.2: aiohttp's default body cap is 1 MB, and a studio upload rides as
    # base64 JSON — any normal phone photo blew past it, request.json() failed,
    # the body was read as empty and the user saw «Такое описание нельзя».
    app = web.Application(client_max_size=12 * 1024 * 1024)
    # V3.56.6: gzip every JSON/text API response the app fetches on boot.
    app.middlewares.append(_webapp_gzip)
    app.router.add_get('/', _root)
    for _seo in seo_landing.PAGES:
        if _seo.path != '/':
            app.router.add_get(_seo.path, _seo_page)
    app.router.add_get('/robots.txt', _seo_robots)
    app.router.add_get('/sitemap.xml', _seo_sitemap)
    app.router.add_get(seo_landing.BANNER_PATH, _seo_banner)
    app.router.add_route('*', '/platega/callback', _platega_callback)
    # Success/fail are browser redirects off the payment page; keep '*' so
    # they answer whether the provider sends GET or POST.
    app.router.add_route('*', '/platega/success', _platega_success)
    app.router.add_route('*', '/platega/fail', _platega_fail)
    app.router.add_get('/healthz', _healthz)
    app.router.add_get('/diagnostics', _diagnostics)
    app.router.add_get('/platega/check', _platega_check)
    # V3.33.0: Mini App storefront (page + JSON API + character portraits).
    app.router.add_get('/webapp', _webapp_index)
    app.router.add_get('/webapp/api/me', _webapp_api_me)
    app.router.add_get('/webapp/api/characters', _webapp_api_characters)
    app.router.add_get('/webapp/api/author', _webapp_api_author)
    # V3.44.11: the creator's cabinet in the profile — characters, earnings,
    # and the «на витрину» publish toggle.
    app.router.add_get('/webapp/api/creator/cabinet', _webapp_api_creator_cabinet)
    app.router.add_post('/webapp/api/creator/publish', _webapp_api_creator_publish)
    app.router.add_get('/webapp/api/creator/character', _webapp_api_creator_character)
    app.router.add_post('/webapp/api/creator/edit', _webapp_api_creator_edit)
    app.router.add_post('/webapp/api/creator/delete', _webapp_api_creator_delete)
    # V3.45.27: unified achievements board + private gallery in the Mini App.
    app.router.add_get('/webapp/api/achievements', _webapp_api_achievements)
    # V3.53.0: «Собери галерею» rolling photo-set bar on the character page.
    app.router.add_get('/webapp/api/collection', _webapp_api_collection)
    # V3.46.0: missions funnel tab (roadmap + in-app CTAs).
    app.router.add_get('/webapp/api/missions', _webapp_api_missions)
    app.router.add_post('/webapp/api/missions/claim', _webapp_api_missions_claim)
    app.router.add_get('/webapp/api/gallery', _webapp_api_gallery)
    app.router.add_get('/webapp/gallery/image/{image_id}', _webapp_gallery_image)
    # V3.47.0: watermarked export copy for the viral «Поделиться» sheet.
    app.router.add_get('/webapp/gallery/share/{image_id}', _webapp_gallery_share)
    # V3.47.1: achievement art (Mini App board) + reliable photo share-to-chat.
    app.router.add_get('/webapp/badge/{key}', _webapp_badge)
    app.router.add_get('/webapp/art/{name}', _webapp_art)  # V3.85.0: partner tab art
    app.router.add_get('/webapp/locked/{character_id}.jpg', _webapp_locked_card)  # V3.88.0
    # V3.139.0: the blurred joint teaser for men without Premium (Задача 5).
    app.router.add_get('/webapp/duo-teaser/{host_id}/{guest_id}.jpg', _webapp_duo_teaser)
    app.router.add_post('/webapp/api/gallery/save', _webapp_gallery_save)
    app.router.add_post('/webapp/api/gallery/prepare-share', _webapp_api_gallery_prepare_share)
    app.router.add_get('/webapp/shared/{uid}/{image_id}/{sig}.jpg', _webapp_shared_image)
    # V3.44.0: popularity leaderboard
    app.router.add_get('/webapp/api/leaderboard', _webapp_api_leaderboard)
    # V3.44.0: public comments under character cards.
    app.router.add_get('/webapp/api/comments', _webapp_api_comments)
    app.router.add_post('/webapp/api/comment/add', _webapp_api_comment_add)
    # V3.44.0: notification preferences.
    app.router.add_get('/webapp/api/notif/prefs', _webapp_api_notif_prefs)
    app.router.add_post('/webapp/api/notif/update', _webapp_api_notif_update)
    # V3.55.5: daily streak gift + promo codes (replaces the V3.44.0 bonus wheel).
    app.router.add_post('/webapp/api/gift/claim', _webapp_api_gift_claim)
    app.router.add_post('/webapp/api/promo', _webapp_api_promo)
    # V3.44.0: simulated incoming messages — "she messages first".
    app.router.add_get('/webapp/api/simulated_messages', _webapp_api_simulated_messages)
    app.router.add_post('/webapp/api/simulated_message/deliver', _webapp_api_simulated_message_deliver)
    app.router.add_get('/webapp/api/shop', _webapp_api_shop)
    app.router.add_get('/webapp/api/legal', _webapp_api_legal)
    # V3.37.0: the partner tab — stats/link and the payout request.
    app.router.add_get('/webapp/api/partner', _webapp_api_partner)
    app.router.add_post('/webapp/api/partner/withdraw', _webapp_api_partner_withdraw)
    app.router.add_get('/webapp/photo/{character_id}', _webapp_photo)
    # V3.47.4: admin-set page-carousel shots (pure storefront visuals).
    app.router.add_get('/webapp/pgal/{character_id}/{shot_id}', _webapp_pgal)
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
    app.router.add_post('/webapp/api/demo', _webapp_api_demo)
    app.router.add_post('/webapp/api/autopay', _webapp_api_autopay)
    # V3.43.0: the pay-method modal — card/SBP and crypto payment links.
    app.router.add_post('/webapp/api/pay_link', _webapp_api_pay_link)
    app.router.add_post('/webapp/api/feedback', _webapp_api_feedback)  # V3.107.0
    app.router.add_post('/webapp/api/select', _webapp_api_select)
    app.router.add_post('/webapp/api/scenario/start', _webapp_api_scenario_start)
    app.router.add_get('/webapp/api/storylines', _webapp_api_storylines)
    app.router.add_post('/webapp/api/storyline/start', _webapp_api_storyline_start)
    app.router.add_post('/webapp/api/storyline/stop', _webapp_api_storyline_stop)
    app.router.add_get('/webapp/api/fetishes', _webapp_api_fetishes)
    app.router.add_get('/webapp/api/wardrobe', _webapp_api_wardrobe)  # V3.114.0
    app.router.add_post('/webapp/api/wardrobe/buy', _webapp_api_wardrobe_buy)
    app.router.add_post('/webapp/api/wardrobe/wear', _webapp_api_wardrobe_wear)
    app.router.add_post('/webapp/api/wardrobe/pet', _webapp_api_wardrobe_pet)
    app.router.add_post('/webapp/api/home/style', _webapp_api_home_style)  # V3.116.0
    app.router.add_post('/webapp/api/home/place', _webapp_api_home_place)
    app.router.add_post('/webapp/api/fetish/set', _webapp_api_fetish_set)
    app.router.add_post('/webapp/api/fetish/stop', _webapp_api_fetish_stop)
    app.router.add_post('/webapp/api/spicy', _webapp_api_spicy)
    # V3.35.0: chat in the app and the character constructor wizard.
    app.router.add_get('/webapp/api/chat', _webapp_api_chat_history)
    app.router.add_post('/webapp/api/presence', _webapp_api_presence)  # V3.128.0
    app.router.add_post('/webapp/api/chat', _webapp_api_chat_send)
    app.router.add_post('/webapp/api/lang', _webapp_api_lang)
    app.router.add_post('/webapp/api/chat/voice', _webapp_api_chat_voice)
    app.router.add_get('/webapp/api/call/info', _webapp_api_call_info)  # V3.115.0
    app.router.add_post('/webapp/api/call/turn', _webapp_api_call_turn)
    app.router.add_post('/webapp/api/call/end', _webapp_api_call_end)
    app.router.add_post('/webapp/api/call/say', _webapp_api_call_say)  # V3.115.1
    app.router.add_get('/webapp/ws/call', _webapp_ws_call)
    app.router.add_post('/webapp/api/chat/speak', _webapp_api_chat_speak)
    app.router.add_post('/webapp/api/chat/photo', _webapp_api_chat_photo)
    app.router.add_post('/webapp/api/chat/persona', _webapp_api_chat_persona)
    app.router.add_post('/webapp/api/chat/marital', _webapp_api_chat_marital)
    app.router.add_get('/webapp/api/marital/arc', _webapp_api_marital_arc)
    app.router.add_post('/webapp/api/marital/arc/step', _webapp_api_marital_arc_step)
    app.router.add_post('/webapp/api/chat/start', _webapp_api_chat_start)
    app.router.add_post('/webapp/api/chat/guest', _webapp_api_chat_guest)
    app.router.add_get('/webapp/api/chat/level', _webapp_api_chat_level)
    app.router.add_post('/webapp/api/chat/level/pick', _webapp_api_chat_level_pick)
    app.router.add_post('/webapp/api/chat/branch', _webapp_api_chat_branch)
    # V3.38.0: the Come Closer tabs — dialog list, picture studio + gallery.
    app.router.add_get('/webapp/api/chats', _webapp_api_chats)
    app.router.add_post('/webapp/api/chat/media', _webapp_api_chat_media)
    # V3.41.0: the app-chat feature buttons — apartment / date / daily quest.
    app.router.add_get('/webapp/api/feature', _webapp_api_feature)
    app.router.add_post('/webapp/api/feature/action', _webapp_api_feature_action)
    # V3.51.0: the Mini App story player (branching quests that move the path).
    app.router.add_get('/webapp/api/story', _webapp_api_story)
    app.router.add_post('/webapp/api/story/action', _webapp_api_story_action)
    app.router.add_get('/webapp/media/{filename}', _webapp_media)
    app.router.add_get('/webapp/smedia/{uid}/{filename}/{sig}', _webapp_signed_media)
    app.router.add_get('/webapp/vsrc/{token}', _webapp_video_frame)
    app.router.add_post('/webapp/api/chat/photo-action', _webapp_api_photo_action)
    app.router.add_get('/webapp/api/undress-credit', _webapp_api_undress_credit)
    app.router.add_post('/webapp/api/picture', _webapp_api_picture_generate)
    # V3.54.0: «Собери видео» — image-to-video of the user's own photo / a
    # prompt-generated frame, priced at WEBAPP_VIDEO_COST_CREDITS 🍑.
    app.router.add_post('/webapp/api/studio/video', _webapp_api_studio_video)
    app.router.add_get('/webapp/api/pictures', _webapp_api_pictures)
    # V3.55.0: «Мои видео» — the app video gallery (Postgres-backed media).
    app.router.add_get('/webapp/api/videos', _webapp_api_videos)
    app.router.add_get('/webapp/picture/{filename}', _webapp_picture)
    # V3.51.1: admin-only feed of what users generate in the Mini App.
    app.router.add_get('/webapp/api/admin/generations', _webapp_api_admin_generations)
    app.router.add_post('/webapp/api/admin/gen_reject', _webapp_api_admin_gen_reject)
    app.router.add_get('/webapp/api/admin/gen_media/{owner}/{filename}', _webapp_api_admin_gen_media)
    app.router.add_get('/webapp/api/constructor/options', _webapp_api_constructor_options)
    app.router.add_get('/webapp/api/constructor/status', _webapp_api_constructor_status)
    app.router.add_post('/webapp/api/constructor/draft', _webapp_api_constructor_draft)
    app.router.add_post('/webapp/api/constructor/buy', _webapp_api_constructor_buy)
    runner = web.AppRunner(app)
    await runner.setup()
    # V3.57.2: asyncio.to_thread shares the loop's default executor (5 threads
    # by default) — every offloaded endpoint competes in it, so grow it to
    # match the Postgres pool below.
    from concurrent.futures import ThreadPoolExecutor
    asyncio.get_running_loop().set_default_executor(
        ThreadPoolExecutor(max_workers=16, thread_name_prefix='offload'))
    site = web.TCPSite(runner, '0.0.0.0', WEB_PORT)
    await site.start()
    logger.info('web server listening port=%s platega=%s base=%s', WEB_PORT, PLATEGA_ENABLED, PUBLIC_BASE_URL or '-')


# V3.107.0: the running support bot (None until it starts / without a token).
_SUPPORT_BOT = None


async def _webapp_api_feedback(request: web.Request) -> web.Response:
    """V3.107.0: a wish from the honest card → the admins' support chat."""
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
    from services import app_feedback
    from services import support_desk
    text = app_feedback.clean((body or {}).get('text'))
    if len(text) < app_feedback.MIN_LEN:
        return web.json_response({'ok': False, 'error': 'short'}, status=400)
    if not app_feedback.allowed(telegram_id):
        return web.json_response({'ok': False, 'error': 'rate'}, status=429)
    name = ' '.join(x for x in (user_info.get('first_name'), user_info.get('last_name')) if x)
    card = await asyncio.to_thread(app_feedback.admin_card, int(telegram_id), name,
                                   user_info.get('username'), text)
    sender = _SUPPORT_BOT or bot
    delivered = 0
    for admin_id in ADMIN_TELEGRAM_IDS:
        try:
            await sender.send_message(admin_id, card)
            delivered += 1
        except Exception as exc:
            logger.warning('app feedback to admin=%s failed: %s', admin_id, exc)
    if not delivered:
        return web.json_response({'ok': False, 'error': 'send'}, status=502)
    app_feedback.remember(telegram_id)
    await asyncio.to_thread(support_desk.note_event, 'app_feedback', int(telegram_id), text)
    return web.json_response({'ok': True})


async def _run_support_bot() -> None:
    """V3.43.3: the support desk bot — /start welcome + appeals to the admins.

    Runs as a second aiogram bot inside this process when SUPPORT_BOT_TOKEN
    is set (the rotated token of the support bot, env only).
    V3.90.0: a real desk (services/support_desk.py) — ready answers on /start,
    an appeal card for the admins, answers by reply, /tickets, a calm ack.
    """
    from aiogram import Bot as SupportBot, Dispatcher as SupportDispatcher
    from services import support_desk as desk
    global _SUPPORT_BOT
    support_bot = SupportBot(token=SUPPORT_BOT_TOKEN)
    _SUPPORT_BOT = support_bot  # V3.107.0: app wishes go out through it
    support_dp = SupportDispatcher()
    # (admin chat, message id) -> user id, for replies to copied media
    routes: dict[tuple[int, int], int] = {}
    last_ack: dict[int, float] = {}

    def _menu() -> InlineKeyboardMarkup:
        rows = [[InlineKeyboardButton(text=btn, callback_data=f'sd:{key}')]
                for key, (btn, _a) in desk.FAQ.items()]
        rows.append([InlineKeyboardButton(text=desk.WRITE_BUTTON, callback_data=f'sd:{desk.WRITE_KEY}')])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def _back() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=desk.WRITE_BUTTON, callback_data=f'sd:{desk.WRITE_KEY}')],
            [InlineKeyboardButton(text='↩️ Другие вопросы', callback_data='sd:menu')]])

    @support_dp.message(Command('start'))
    async def _support_start(msg: types.Message):
        if msg.from_user.id in ADMIN_TELEGRAM_IDS:
            await msg.answer('Ты админ поддержки 👋\n\nОбращения приходят сюда карточками. '
                             'Ответь на карточку (или на сообщение под ней) — ответ уйдёт пользователю.\n'
                             '/tickets — кто ждёт ответа\n/reply <id> <текст> — ответить по id')
            return
        await msg.answer(desk.WELCOME, reply_markup=_menu())

    @support_dp.callback_query(F.data.startswith('sd:'))
    async def _support_faq(cq: types.CallbackQuery):
        key = cq.data.split(':', 1)[1]
        await cq.answer()
        if key == 'menu':
            await cq.message.answer(desk.WELCOME, reply_markup=_menu())
        elif key == desk.WRITE_KEY:
            await cq.message.answer(desk.WRITE_ANSWER)
        elif key in desk.FAQ:
            await cq.message.answer(desk.FAQ[key][1], reply_markup=_back())

    @support_dp.message(Command('tickets'))
    async def _support_tickets(msg: types.Message):
        if msg.from_user.id not in ADMIN_TELEGRAM_IDS:
            return await _support_appeal(msg)
        items = await asyncio.to_thread(desk.open_tickets)
        await msg.answer(desk.tickets_text(items))

    async def _send_answer(admin_msg: types.Message, user_id: int, text: str | None = None) -> None:
        try:
            if text is not None:
                await support_bot.send_message(user_id, desk.ANSWER_PREFIX + text)
            elif admin_msg.text:
                await support_bot.send_message(user_id, desk.ANSWER_PREFIX + admin_msg.text)
            else:
                await support_bot.send_message(user_id, desk.ANSWER_PREFIX.strip())
                await admin_msg.copy_to(user_id)
        except Exception as exc:
            # V3.107.0: he never opened the support bot (an app wish) — the
            # answer goes through the main bot, which he surely started.
            body = text if text is not None else (admin_msg.text or '')
            try:
                if not body:
                    raise exc
                await bot.send_message(user_id, desk.ANSWER_PREFIX + body)
            except Exception:
                await admin_msg.answer(f'⚠️ Не доставлено пользователю {user_id}: {type(exc).__name__}')
                return
            await admin_msg.answer('ℹ️ Бот поддержки он не открывал — ответ ушёл через основной бот.')
        await asyncio.to_thread(desk.note_event, desk.ANSWER_EVENT, user_id, text or admin_msg.text or '')
        await admin_msg.answer(f'✅ Отправлено пользователю {user_id}')

    @support_dp.message()
    async def _support_appeal(msg: types.Message):
        uid = msg.from_user.id
        if uid in ADMIN_TELEGRAM_IDS:
            cmd = desk.parse_reply_command(msg.text or '')
            if cmd:
                await _send_answer(msg, cmd[0], cmd[1])
                return
            reply = msg.reply_to_message
            target = None
            if reply is not None:
                target = routes.get((msg.chat.id, reply.message_id)) \
                    or desk.user_id_from_card(reply.text or reply.caption)
            if target:
                await _send_answer(msg, target)
            else:
                await msg.answer('Чтобы ответить пользователю, ответь (reply) на его карточку '
                                 'или используй /reply <id> <текст>. /tickets — кто ждёт ответа.')
            return
        text = msg.text or msg.caption or ''
        card = await asyncio.to_thread(desk.user_card, uid, msg.from_user.full_name,
                                       msg.from_user.username, text)
        await asyncio.to_thread(desk.note_event, desk.APPEAL_EVENT, uid, text)
        for admin_id in ADMIN_TELEGRAM_IDS:
            try:
                sent = await support_bot.send_message(admin_id, card)
                routes[(admin_id, sent.message_id)] = uid
                if not msg.text:  # a screenshot / voice / file goes under the card
                    copied = await msg.copy_to(admin_id, reply_to_message_id=sent.message_id)
                    routes[(admin_id, copied.message_id)] = uid
            except Exception as exc:
                logger.warning('support appeal to admin=%s failed: %s', admin_id, exc)
        now = _time.time()
        if now - last_ack.get(uid, 0) >= desk.ACK_EVERY.total_seconds():
            last_ack[uid] = now
            await msg.answer(desk.ACK)

    try:
        await support_dp.start_polling(support_bot)
    except Exception:
        logger.exception('support bot polling crashed')



# V3.62.15: the bot's public face (owner's marketing ask): name, the profile
# blurb and the text an empty chat shows before «Запустить». Kept in code so
# BotFather never drifts; each field is written only when it differs, because
# Telegram rate-limits setMyName hard. BOT_PROFILE_ENABLED=0 leaves it alone.
# V3.115.2: descriptions moved to services/bot_description.py only (EN default
# + RU). Two writers raced on every deploy: this one put the RU text into the
# default locale, apply_bot_descriptions() the EN text, and the old «8 levels»
# era copy kept coming back. Here only the display NAME is kept.
BOT_PROFILE = {
    'ru': {'name': os.getenv('BOT_DISPLAY_NAME', 'Анна · AI-девушка')},
    'en': {'name': os.getenv('BOT_DISPLAY_NAME_EN', 'Anna · AI girlfriend')},
}
_BOT_NAME_FALLBACK = {
    '': 'ИИ Анна | Чат 18+ 🔞',
    'ru': 'ИИ Анна | Чат 18+ 🔞',
    'en': 'AI Anna | 18+ Chat 🔞',
}


async def _apply_bot_name_overrides() -> None:
    # V3.126.0: BotFather /setname only edits the default name, while a name
    # stored per language (ru/en) wins for users with that app language. Log
    # what Telegram has for '', ru and en, and write BOT_NAME_DEFAULT /
    # BOT_NAME_RU / BOT_NAME_EN when set (only if they differ: setMyName is
    # rate-limited). An empty-string value is not written.
    # V3.142.0: the owner's Nov 12 name is the code default, so a deploy
    # applies it without env vars; the env vars still override it.
    for code, var in (('', 'BOT_NAME_DEFAULT'), ('ru', 'BOT_NAME_RU'), ('en', 'BOT_NAME_EN')):
        try:
            cur = (await bot.get_my_name(language_code=code)).name or ''
            want = os.getenv(var, _BOT_NAME_FALLBACK[code]).strip()[:64]
            if want and want != cur:
                await bot.set_my_name(name=want, language_code=code)
                logger.info('bot name lang=%s set %r -> %r', code or 'default', cur, want)
            else:
                logger.info('bot name lang=%s is %r', code or 'default', cur)
        except Exception:
            logger.exception('bot name check failed lang=%s', code or 'default')


async def _apply_bot_profile() -> None:
    await _apply_bot_name_overrides()
    # V3.118.0: off by default — the owner edits name/description in BotFather
    # and every deploy used to overwrite them. BOT_PROFILE_ENABLED=1 turns it on.
    if os.getenv('BOT_PROFILE_ENABLED', '0') != '1':
        return
    for lang, prof in BOT_PROFILE.items():
        code = '' if lang == 'ru' else lang
        try:
            cur = await bot.get_my_name(language_code=code)
            if (cur.name or '') != prof['name']:
                await bot.set_my_name(name=prof['name'][:64], language_code=code)
            logger.info('bot profile ok lang=%s', lang)
        except Exception:
            logger.exception('bot profile update failed lang=%s', lang)

async def _apply_bot_avatar() -> None:
    # V3.142.0: the owner's avatar from code. setMyProfilePhoto takes an
    # animated MPEG4 (<=5 s, 640x640) or a static JPG — never a GIF or file_id.
    # aiogram 3.20 predates the method, so a raw multipart call with attach://.
    import aiohttp
    path = BOT_AVATAR_MP4_PATH if BOT_AVATAR_MP4_PATH.exists() else BOT_AVATAR_JPG_PATH
    if not path.exists():
        return
    if path.suffix == '.mp4':
        photo = {'type': 'animated', 'animation': 'attach://avatar', 'main_frame_timestamp': 0}
        ctype = 'video/mp4'
    else:
        photo = {'type': 'static', 'photo': 'attach://avatar'}
        ctype = 'image/jpeg'
    form = aiohttp.FormData()
    form.add_field('photo', json.dumps(photo))
    form.add_field('avatar', path.read_bytes(), filename=path.name, content_type=ctype)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/setMyProfilePhoto',
                data=form, timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                body = await resp.json()
        if body.get('ok'):
            logger.info('bot avatar applied from %s', path.name)
        else:
            logger.warning('bot avatar apply failed: %s', body.get('description'))
    except Exception:
        logger.exception('bot avatar apply failed')


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
        types.BotCommand(command='promo', description='🎟 Активировать промокод'),
        types.BotCommand(command='referral', description='🔗 Моя ссылка для приглашения'),
        types.BotCommand(command='partner', description='💰 Партнёрская программа — 30% с покупок друзей'),
        types.BotCommand(command='contest', description='🏆 Гонка пригласивших'),
        types.BotCommand(command='notifications', description='Инициативные сообщения'),
        types.BotCommand(command='wake', description='Будильник: /wake 08:00'),
        # V3.149.0: the menu on demand — the buttons are the primary path, this
        # is the fallback for anyone whose keyboard never got replaced.
        types.BotCommand(command='menu', description='🧭 Меню'),
        types.BotCommand(command='reset', description='Очистить память и историю'),
    ]
    await bot.set_my_commands(public_commands)
    _spawn_background(_apply_bot_profile())
    _spawn_background(_apply_bot_avatar())
    # V3.33.0: Mini App — the blue «Открыть приложение» button in the bot's
    # profile plus the «AnnaBot» menu button. Requires PUBLIC_BASE_URL (the
    # same Railway domain the payment routes use); skipped silently otherwise.
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
                public_commands + [types.BotCommand(command='admin', description='🛠 Админка'), types.BotCommand(command='week', description='📈 Отчёт за неделю'), types.BotCommand(command='refundstars', description='↩️ Возврат Stars'), types.BotCommand(command='geministatus', description='🧠 Gemini status'), types.BotCommand(command='grant', description='🎁 Выдать premium/токены по @username'), types.BotCommand(command='setmenubutton', description='🔵 Установить кнопку «Открыть приложение»')],
                scope=types.BotCommandScopeChat(chat_id=admin_id),
            )
        except Exception:
            logger.exception('failed to install admin command scope chat_id=%s', admin_id)
    ensure_default_cards()
    ensure_default_payment_methods()
    # V3.55.5: seed the welcome promo shelf (ANNA5 · +5 🍑) — idempotent,
    # fail-silent; the owner manages/toggles it later in «🎟 Промокоды».
    from services import gift_service
    gift_service.ensure_welcome_promo()
    start_scheduler(bot)
    _spawn_background(_startup_fix_glued_bios())
    try:
        active_reminders = due_reminders()
        logger.info('startup active_reminders=%s ids=%s', len(active_reminders), [r.id for r in active_reminders])
    except Exception:
        logger.exception('startup reminder check failed')
    st = provider_status()
    logger.info(
        'LLM status: openrouter=%s model=%s gemini=%s gemini_model=%s video=%s',
        st['openrouter_key_present'], st['openrouter_model'], st['gemini_key_present'],
        st['gemini_model'], spicy_video_available(),
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
    # V3.44.13: finish constructor creations the previous deploy killed mid-job
    # — the draft lives in Postgres, so a paid persona never vanishes again.
    try:
        pending = pending_constructor_drafts()
        for _draft in pending:
            logger.info('startup resuming constructor creation user=%s source=%s', _draft.telegram_id, _draft.source)
            # through _spawn_job like every creation — a resumed run that dies
            # again is picked up by the stale-job recovery at the next boot.
            _spawn_job('constructor', int(_draft.telegram_id), _finish_constructor(int(_draft.telegram_id), None, int(_draft.telegram_id), source=_draft.source or ''), payload={'source': _draft.source or 'resume'})
    except Exception:
        logger.exception('startup constructor draft resume failed')
    # V3.44.14: and keep resuming them every few minutes — a run can also die
    # mid-creation without any deploy (exception between payment and save).
    asyncio.create_task(_constructor_draft_sweep())
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
