import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent

raw_db = os.getenv("DATABASE_URL") or os.getenv("MYSQL_URL")
if raw_db:
    if raw_db.startswith("postgres://"):
        raw_db = "postgresql+psycopg://" + raw_db[len("postgres://"):]
    elif raw_db.startswith("postgresql://") and "+" not in raw_db.split("://", 1)[0]:
        raw_db = "postgresql+psycopg://" + raw_db[len("postgresql://"):]
    DATABASE_URL = raw_db
else:
    DATABASE_URL = f"sqlite:///{(BASE_DIR / 'annabot.db').as_posix()}"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
TELEGRAM_BOT_NAME = os.getenv("TELEGRAM_BOT_NAME", "Anna")

# ── OpenRouter (primary chat / memory / adaptation provider) ──────────────
# Support both correct spelling and legacy typo (OPENEROUTER_API_KEY)
OPENROUTER_API_KEY = (
    os.getenv("OPENROUTER_API_KEY")
    or os.getenv("OPENEROUTER_API_KEY")
    or ""
).strip()
OPENROUTER_BASE_URL = (
    os.getenv("OPENROUTER_BASE_URL")
    or os.getenv("OPENEROUTER_BASE_URL")
    or "https://openrouter.ai/api/v1"
).strip().rstrip("/")
OPENROUTER_MODEL = (
    os.getenv("OPENROUTER_MODEL")
    or os.getenv("OPENEROUTER_MODEL")
    or "minimax/minimax-m3"
).strip()

# Legacy OpenAI key — kept ONLY for optional TTS/Whisper/moderation.
# No longer required for chat or image generation.
AI_KEY = (os.getenv("OPENAI_API_KEY") or os.getenv("AI_KEY") or "").strip()
AI_MODEL = os.getenv("AI_MODEL", OPENROUTER_MODEL)
AI_BASE_URL = os.getenv("AI_BASE_URL", OPENROUTER_BASE_URL if OPENROUTER_API_KEY else None)

# Dialogue provider chain: OpenRouter primary → Gemini fallback.
# Legacy provider-switching env vars were removed; the chain is hard-wired
# in services/llm_provider_service.py for stability.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.5-flash").strip()
GEMINI_OPENAI_BASE_URL = os.getenv(
    "GEMINI_OPENAI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta/openai/",
).strip()
GEMINI_THINKING_LEVEL = os.getenv("GEMINI_THINKING_LEVEL", "minimal").strip().lower()

# Optional Gemini/Veo image-to-video. Kept disabled by default because Veo
# requires a paid Gemini API tier and each generation has a real per-second cost.
GEMINI_VIDEO_ENABLED = (
    os.getenv("GEMINI_VIDEO_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    and bool(GEMINI_API_KEY)
)
GEMINI_VIDEO_MODEL = os.getenv("GEMINI_VIDEO_MODEL", "veo-3.1-lite-generate-preview").strip()
GEMINI_VIDEO_BASE_URL = os.getenv("GEMINI_VIDEO_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
GEMINI_VIDEO_DURATION_SECONDS = max(4, min(8, int(os.getenv("GEMINI_VIDEO_DURATION_SECONDS", "8"))))
GEMINI_VIDEO_RESOLUTION = os.getenv("GEMINI_VIDEO_RESOLUTION", "720p").strip()
GEMINI_VIDEO_ASPECT_RATIO = os.getenv("GEMINI_VIDEO_ASPECT_RATIO", "9:16").strip()
GEMINI_VIDEO_TIMEOUT_SECONDS = max(60, min(420, int(os.getenv("GEMINI_VIDEO_TIMEOUT_SECONDS", "360"))))
VIDEO_COST_STARS = max(1, int(os.getenv("VIDEO_COST_STARS", "5")))
# Premium perk: this many photo animations per day are free for Premium users;
# any extra animation on the same day is sold for VIDEO_COST_STARS Stars.
VIDEO_PREMIUM_FREE_DAILY = max(0, int(os.getenv("VIDEO_PREMIUM_FREE_DAILY", "1")))

# Gemini native image generation / Nano Banana 2.
# Ordinary fully-clothed scenes can use the same GEMINI_API_KEY as chat.
# If the model/tier is unavailable, photo_service falls back to GPT Image 2.
GEMINI_IMAGE_ENABLED = (
    os.getenv("GEMINI_IMAGE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    and bool(GEMINI_API_KEY)
)
GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image").strip()
GEMINI_IMAGE_TIMEOUT_SECONDS = max(30, min(240, int(os.getenv("GEMINI_IMAGE_TIMEOUT_SECONDS", "120"))))
GEMINI_IMAGE_ESTIMATED_COST_USD = float(os.getenv("GEMINI_IMAGE_ESTIMATED_COST_USD", "0"))
GEMINI_IMAGE_ASPECT_RATIO = os.getenv("GEMINI_IMAGE_ASPECT_RATIO", "3:4").strip()
GEMINI_IMAGE_SIZE = os.getenv("GEMINI_IMAGE_SIZE", "1K").strip()

CHARACTER_ID = os.getenv("CHARACTER_ID", "anna_01")
CHARACTER_DIR = Path(os.getenv("CHARACTER_DIR", str(BASE_DIR / "data" / "characters")))
CHARACTER_FILE = os.getenv("CHARACTER_FILE", str(CHARACTER_DIR / "anna.json"))

# ── Image generation: Gemini primary, Seedream for intimate, OpenAI removed ─
IMAGE_API_KEY = (os.getenv("IMAGE_API_KEY") or AI_KEY).strip()
IMAGE_BASE_URL = os.getenv("IMAGE_BASE_URL") or AI_BASE_URL
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-2")
IMAGE_SIZE = os.getenv("IMAGE_SIZE", "1024x1536")
IMAGE_QUALITY = os.getenv("IMAGE_QUALITY", "medium")
OPENAI_IMAGE_ESTIMATED_COST_USD = float(os.getenv("OPENAI_IMAGE_ESTIMATED_COST_USD", "0"))
IMAGE_REFERENCE_MODE = os.getenv("IMAGE_REFERENCE_MODE", "edit").lower()
OPENAI_IMAGE_AVAILABLE = bool(AI_KEY) and os.getenv("OPENAI_IMAGE_AVAILABLE", "false").strip().lower() in {"1", "true", "yes", "on"}

# fal.ai / Seedream 4.5 is used by the hybrid photo router for higher-intimacy,
# still non-explicit fashion edits. Keep the key server-side in Railway.
FAL_KEY = os.getenv("FAL_KEY", "").strip()
FAL_MODEL = os.getenv("FAL_MODEL", "fal-ai/bytedance/seedream/v4.5/edit").strip()
FAL_IMAGE_SIZE = os.getenv("FAL_IMAGE_SIZE", "portrait_4_3").strip()
FAL_TIMEOUT_SECONDS = int(os.getenv("FAL_TIMEOUT_SECONDS", "210"))
FAL_CONNECT_TIMEOUT_SECONDS = int(os.getenv("FAL_CONNECT_TIMEOUT_SECONDS", "20"))
FAL_WRITE_TIMEOUT_SECONDS = int(os.getenv("FAL_WRITE_TIMEOUT_SECONDS", "60"))
FAL_POOL_TIMEOUT_SECONDS = int(os.getenv("FAL_POOL_TIMEOUT_SECONDS", "30"))
FAL_RETRIES = max(0, min(3, int(os.getenv("FAL_RETRIES", "2"))))
FAL_RETRY_BACKOFF_SECONDS = float(os.getenv("FAL_RETRY_BACKOFF_SECONDS", "2"))
FAL_ESTIMATED_COST_USD = float(os.getenv("FAL_ESTIMATED_COST_USD", "0.04"))
PHOTO_ROUTER_MODE = os.getenv("PHOTO_ROUTER_MODE", "hybrid").strip().lower()
SEEDREAM_RELATIONSHIP_LEVEL = int(os.getenv("SEEDREAM_RELATIONSHIP_LEVEL", "5"))
PHOTO_SET_SIZE = max(1, min(3, int(os.getenv("PHOTO_SET_SIZE", "1"))))

# Pollinations.ai — free last-resort photo provider, no API key required.
# It is only used as the final fallback for ordinary fully-clothed photos when
# the primary providers (Gemini/OpenAI/Seedream) fail or are not configured.
# It does not accept reference uploads, so identity is reinforced by text only.
POLLINATIONS_ENABLED = os.getenv("POLLINATIONS_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
POLLINATIONS_MODEL = os.getenv("POLLINATIONS_MODEL", "flux").strip()
POLLINATIONS_TIMEOUT_SECONDS = max(30, min(240, int(os.getenv("POLLINATIONS_TIMEOUT_SECONDS", "120"))))
POLLINATIONS_WIDTH = max(512, min(2048, int(os.getenv("POLLINATIONS_WIDTH", "1024"))))
POLLINATIONS_HEIGHT = max(512, min(2048, int(os.getenv("POLLINATIONS_HEIGHT", "1280"))))

# Photo idea engine: curated bank (data/photo_ideas.json) + optional LLM variations.
# Fills underspecified ordinary photo requests with fresh location/camera ideas.
PHOTO_IDEAS_ENABLED = os.getenv("PHOTO_IDEAS_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
PHOTO_IDEA_LLM_CHANCE = max(0.0, min(1.0, float(os.getenv("PHOTO_IDEA_LLM_CHANCE", "0.25"))))

# Paid video generation via a public Hugging Face Gradio space.
# The backend itself is free, but the feature is sold for VIDEO_COST_STARS;
# requests queue on public GPU servers, so generation typically takes 1–3 minutes.
# Gemini/Veo stays the paid premium route when enabled.
HF_VIDEO_ENABLED = os.getenv("HF_VIDEO_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
HF_VIDEO_SPACE = os.getenv("HF_VIDEO_SPACE", "Wan-AI/Wan2.1").strip()
HF_VIDEO_TIMEOUT_SECONDS = max(120, min(1800, int(os.getenv("HF_VIDEO_TIMEOUT_SECONDS", "600"))))

# Per-user adaptive communication profile. The model never rewrites its own code/prompt;
# it only learns bounded style signals and recurring expressions into PostgreSQL.
ADAPTATION_ENABLED = os.getenv("ADAPTATION_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
ADAPTATION_ANALYZE_EVERY = max(3, min(20, int(os.getenv("ADAPTATION_ANALYZE_EVERY", "5"))))
ADAPTATION_MAX_EXPRESSIONS = max(3, min(20, int(os.getenv("ADAPTATION_MAX_EXPRESSIONS", "12"))))

FREE_MESSAGES_PER_DAY = int(os.getenv("FREE_MESSAGES_PER_DAY", "80"))
FREE_PHOTOS_LEVEL_1_2 = int(os.getenv("FREE_PHOTOS_LEVEL_1_2", "1"))
FREE_PHOTOS_LEVEL_3_6 = int(os.getenv("FREE_PHOTOS_LEVEL_3_6", "2"))
PREMIUM_MONTHLY_STARS = int(os.getenv("PREMIUM_MONTHLY_STARS", "500"))
PREMIUM_MONTHLY_PHOTO_CREDITS = int(os.getenv("PREMIUM_MONTHLY_PHOTO_CREDITS", "12"))
PHOTO_COST_STARS = int(os.getenv("PHOTO_COST_STARS", "25"))
CHAT_PHOTO_OFFER_STARS = int(os.getenv("CHAT_PHOTO_OFFER_STARS", "5"))
CUSTOM_PHOTO_COST_STARS = int(os.getenv("CUSTOM_PHOTO_COST_STARS", "40"))
QUEST_REPLAY_STARS = int(os.getenv("QUEST_REPLAY_STARS", "10"))
PREMIUM_MONTHLY_QUEST_REPLAYS = int(os.getenv("PREMIUM_MONTHLY_QUEST_REPLAYS", "2"))

# Referral & first-start "wow" bonuses. Both sides receive photo credits.
# 0 disables a bonus.
REFERRAL_REFERRER_CREDITS = int(os.getenv("REFERRAL_REFERRER_CREDITS", "3"))
REFERRAL_INVITEE_CREDITS = int(os.getenv("REFERRAL_INVITEE_CREDITS", "3"))
FIRST_START_BONUS_CREDITS = int(os.getenv("FIRST_START_BONUS_CREDITS", "2"))
# A short Premium taste granted to brand-new users so they can sample premium
# photo routes on day one. 0 disables. Days, not stars.
FIRST_START_PREMIUM_TRIAL_DAYS = int(os.getenv("FIRST_START_PREMIUM_TRIAL_DAYS", "0"))

# Video animation guardrails.
VIDEO_PROGRESS_NOTIFY_SECONDS = float(os.getenv("VIDEO_PROGRESS_NOTIFY_SECONDS", "45"))
VIDEO_STATUS_TEXT = os.getenv("VIDEO_STATUS_TEXT", "🎬 видео создаётся, обычно это занимает 1–3 минуты. я напишу, как будет готово — или верну Stars, если что-то пойдёт не так.")

# Commercial guardrails. 0 disables a guard; set real values in Railway for beta.
DAILY_IMAGE_BUDGET_USD = float(os.getenv("DAILY_IMAGE_BUDGET_USD", "0"))
MONTHLY_IMAGE_BUDGET_USD = float(os.getenv("MONTHLY_IMAGE_BUDGET_USD", "0"))
PHOTO_PROGRESS_MESSAGE_DELAY_SECONDS = float(os.getenv("PHOTO_PROGRESS_MESSAGE_DELAY_SECONDS", "18"))

# Free multimodal moderation guard for pre-generated library uploads.
# It blocks photos flagged as sexual before their Telegram file_id is saved.
# Moderation: disabled by default when OpenAI key is absent.
LIBRARY_MODERATION_ENABLED = (
    os.getenv("LIBRARY_MODERATION_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
    and bool(AI_KEY)
)
LIBRARY_MODERATION_MODEL = os.getenv("LIBRARY_MODERATION_MODEL", "omni-moderation-latest").strip()

# Voice: use OpenAI TTS/Whisper only if key is present; otherwise edge-tts + Gemini STT.
TTS_API_KEY = (os.getenv("TTS_API_KEY") or AI_KEY).strip()
TTS_MODEL = os.getenv("TTS_MODEL", "tts-1")
TTS_VOICE = os.getenv("TTS_VOICE", "nova")
OPENAI_VOICE_AVAILABLE = bool(TTS_API_KEY)

PROACTIVE_MIN_HOURS = int(os.getenv("PROACTIVE_MIN_HOURS", "48"))
DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "UTC")

# Language → timezone defaults for users who haven't set /timezone explicitly.
# Prevents Russian speakers from getting UTC-based greetings and late alarms.
LANG_TZ_DEFAULTS = {
    'ru': 'Europe/Moscow',
    'uk': 'Europe/Kyiv',
    'be': 'Europe/Moscow',
    'kk': 'Asia/Almaty',
    'en': 'America/New_York',
    'es': 'Europe/Madrid',
    'de': 'Europe/Berlin',
    'fr': 'Europe/Paris',
    'it': 'Europe/Rome',
    'pt': 'Europe/Lisbon',
    'zh': 'Asia/Shanghai',
    'ja': 'Asia/Tokyo',
    'ko': 'Asia/Seoul',
}
# ── Telegram Wallet Pay (crypto + card on-ramp through Wallet) ────────────
WALLET_PAY_TOKEN = os.getenv("WALLET_PAY_TOKEN", "").strip()
WALLET_PAY_ENABLED = bool(WALLET_PAY_TOKEN)
WALLET_PAY_API_URL = os.getenv("WALLET_PAY_API_URL", "https://pay.wallet.tg/wpay").strip().rstrip("/")
WALLET_PAY_WEBHOOK_URL = os.getenv("WALLET_PAY_WEBHOOK_URL", "").strip()
WALLET_PAY_TIMEOUT_SECONDS = max(10, min(120, int(os.getenv("WALLET_PAY_TIMEOUT_SECONDS", "30"))))
# Fallback conversion: 1 Star ≈ 0.02 USD, used to show fiat price in Wallet Pay invoices.
STARS_TO_USD = float(os.getenv("STARS_TO_USD", "0.02"))

ADMIN_TELEGRAM_IDS = {int(x.strip()) for x in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",") if x.strip().isdigit()}

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN is not configured")
_has_llm = bool(OPENROUTER_API_KEY or GEMINI_API_KEY or AI_KEY)
if not _has_llm:
    raise RuntimeError(
        "No LLM provider configured. Set OPENEROUTER_API_KEY, GEMINI_API_KEY, or OPENAI_API_KEY."
    )
