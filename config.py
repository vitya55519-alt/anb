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
# V3.19.3: a key pasted with non-ASCII characters (Cyrillic lookalikes, NBSP)
# or embedded whitespace breaks every Gemini call with an opaque auth error.
# Treat such a key as absent so photo/video engines fall back to the next
# provider instead of failing, and the owner sees a clear startup warning.
GEMINI_API_KEY_VALID = bool(GEMINI_API_KEY) and GEMINI_API_KEY.isascii() and not any(ch.isspace() for ch in GEMINI_API_KEY)
if GEMINI_API_KEY and not GEMINI_API_KEY_VALID:
    print(
        'CONFIG WARNING: GEMINI_API_KEY contains non-ASCII or whitespace characters - '
        'Gemini chat/image/video disabled until the key is re-pasted cleanly on Railway',
        flush=True,
    )
GEMINI_CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.5-flash").strip()
GEMINI_OPENAI_BASE_URL = os.getenv(
    "GEMINI_OPENAI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta/openai/",
).strip()
GEMINI_THINKING_LEVEL = os.getenv("GEMINI_THINKING_LEVEL", "minimal").strip().lower()

# Gemini/Veo image-to-video — the PRIMARY video engine again (V3.19.5 owner
# decision; it was briefly removed in V3.19.4). "auto" (default) means: enabled
# whenever a VALID GEMINI_API_KEY is present (the V3.19.3 key gate keeps a
# dirty-pasted key from poisoning the chain — the job then falls back to
# Replicate). Set GEMINI_VIDEO_ENABLED=false to force the Replicate route only.
_GEMINI_VIDEO_FLAG = os.getenv("GEMINI_VIDEO_ENABLED", "auto").strip().lower()
GEMINI_VIDEO_ENABLED = bool(GEMINI_API_KEY_VALID) and _GEMINI_VIDEO_FLAG not in {"0", "false", "no", "off"}
GEMINI_VIDEO_MODEL = os.getenv("GEMINI_VIDEO_MODEL", "veo-3.1-lite-generate-preview").strip()
GEMINI_VIDEO_BASE_URL = os.getenv("GEMINI_VIDEO_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
GEMINI_VIDEO_DURATION_SECONDS = max(4, min(8, int(os.getenv("GEMINI_VIDEO_DURATION_SECONDS", "8"))))
GEMINI_VIDEO_RESOLUTION = os.getenv("GEMINI_VIDEO_RESOLUTION", "720p").strip()
GEMINI_VIDEO_ASPECT_RATIO = os.getenv("GEMINI_VIDEO_ASPECT_RATIO", "9:16").strip()
GEMINI_VIDEO_TIMEOUT_SECONDS = max(60, min(420, int(os.getenv("GEMINI_VIDEO_TIMEOUT_SECONDS", "360"))))
VIDEO_COST_STARS = max(1, int(os.getenv("VIDEO_COST_STARS", "5")))
# Paid gallery download: the user re-sends their own uncompressed photo as a
# Telegram document (full resolution). Kept low to encourage repeat use.
GALLERY_DOWNLOAD_STARS = max(1, int(os.getenv("GALLERY_DOWNLOAD_STARS", "30")))
# Premium perk: this many photo animations per day are free for Premium users;
# any extra animation on the same day is sold for VIDEO_COST_STARS Stars.
VIDEO_PREMIUM_FREE_DAILY = max(0, int(os.getenv("VIDEO_PREMIUM_FREE_DAILY", "1")))

# Community photo pool: AI-generated photos are shared between users requesting
# the same character+scene. New photos are generated only when the pool has no
# unseen content for that user. This saves API cost and gives every user a
# varied experience without redundant generations.
COMMUNITY_POOL_ENABLED = os.getenv("COMMUNITY_POOL_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}

# When enabled, free/story photo sets are served from the community pool first
# (other users' AI generations for the same character+scene); fresh AI
# generation runs only when the pool has no full unseen set for this user.
# Paid credit sets always generate fresh AI photos regardless of this flag.
COMMUNITY_POOL_FIRST = os.getenv("COMMUNITY_POOL_FIRST", "true").strip().lower() in {"1", "true", "yes", "on"}

# Relationship pulse: every N-th user message the chat LLM scores the recent
# excerpt (warmth/trust/intimacy 0-3 + events) and applies a small extra
# delta, so quality conversations without keyword hits still grow the bond.
RELATIONSHIP_PULSE_ENABLED = os.getenv("RELATIONSHIP_PULSE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}

# Gemini native image generation / Nano Banana 2.
# Ordinary fully-clothed scenes can use the same GEMINI_API_KEY as chat.
# If the model/tier is unavailable, photo_service falls back to GPT Image 2.
GEMINI_IMAGE_ENABLED = (
    os.getenv("GEMINI_IMAGE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    and bool(GEMINI_API_KEY_VALID)
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
HF_VIDEO_SPACE = os.getenv("HF_VIDEO_SPACE", "Wan-AI/Wan2.2-I2V-A14B").strip()
# Public spaces die or overload often, so the video job walks this list in
# order until one space actually returns a video (main space goes first).
# Only image-to-video spaces belong here; the client probes each space API
# schema for an endpoint that accepts an image parameter.
HF_VIDEO_FALLBACK_SPACES = tuple(
    s.strip() for s in os.getenv(
        "HF_VIDEO_FALLBACK_SPACES",
        "fffiloni/lumalabs-dream-machine, hysts/LTX-Video, Wan-AI/Wan2.1",
    ).split(",") if s.strip()
)
HF_VIDEO_TIMEOUT_SECONDS = max(120, min(1800, int(os.getenv("HF_VIDEO_TIMEOUT_SECONDS", "600"))))

# Public cloud image-to-video alternatives for when HF spaces die.
# Both offer a free tier / free credits after sign-up and expose a stable API,
# unlike the constantly-breaking Gradio spaces. The key is the only required
# config — when present, the engine is used; without it, it is skipped.
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN", "").strip()
# V3.19.4: primary video model. Hailuo 2.3 Fast (MiniMax) is tuned for
# realistic human motion + expressive faces, which fits the kiss/hug/dance
# animation presets, and accepts the same first_frame_image input the code
# already sends. Override via env to any other Replicate image-to-video model.
REPLICATE_VIDEO_MODEL = os.getenv(
    "REPLICATE_VIDEO_MODEL",
    "minimax/hailuo-2.3-fast",
).strip()
REPLICATE_VIDEO_TIMEOUT_SECONDS = max(120, min(900, int(os.getenv("REPLICATE_VIDEO_TIMEOUT_SECONDS", "600"))))

# V3.19.6: FreeKassa card/SBP payments — the external (non-Telegram) scenario;
# Stars stay the in-Telegram method per Telegram policy. All three secrets are
# required, otherwise the card button and webhook endpoints stay off.
FREEKASSA_MERCHANT_ID = os.getenv("FREEKASSA_MERCHANT_ID", "").strip()
FREEKASSA_SECRET1 = os.getenv("FREEKASSA_SECRET1", "").strip()
FREEKASSA_SECRET2 = os.getenv("FREEKASSA_SECRET2", "").strip()
FREEKASSA_ENABLED = bool(FREEKASSA_MERCHANT_ID and FREEKASSA_SECRET1 and FREEKASSA_SECRET2)
FREEKASSA_PREMIUM_PRICE_RUB = max(1, int(os.getenv("FREEKASSA_PREMIUM_PRICE_RUB", "299")))
# Public base URL of this Railway service (generated domain). Used in the
# FreeKassa merchant form (notify/success/fail URLs).
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
WEB_PORT = int(os.getenv("PORT", "8080"))

FAL_KEY = os.getenv("FAL_KEY", "").strip()
FAL_VIDEO_ENDPOINT = os.getenv("FAL_VIDEO_ENDPOINT", "fal-ai/wan2.2/image-to-video").strip()
FAL_VIDEO_TIMEOUT_SECONDS = max(120, min(900, int(os.getenv("FAL_VIDEO_TIMEOUT_SECONDS", "600"))))

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

# V3.19.0: personal character constructor — one-time Stars payment that builds
# a private chat persona (appearance + personality + relationship role) with a
# generated avatar. Optional user face photo enables face-swap identity.
CONSTRUCTOR_COST_STARS = max(1, int(os.getenv("CONSTRUCTOR_COST_STARS", "50")))

# V3.19.0: vision reactions — the character comments on photos users send in
# chat (selfies, pets, food, gym...) via the multimodal chat provider.
PHOTO_REACTION_ENABLED = os.getenv("PHOTO_REACTION_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
PHOTO_REACTION_COOLDOWN_SECONDS = max(0, int(os.getenv("PHOTO_REACTION_COOLDOWN_SECONDS", "15")))

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

# Streak reward credits granted once when a streak reaches a milestone.
# Keys are the streak day count; values are bonus photo credits.
STREAK_REWARDS = {
    3: int(os.getenv('STREAK_REWARD_3', '1')),
    7: int(os.getenv('STREAK_REWARD_7', '2')),
    14: int(os.getenv('STREAK_REWARD_14', '3')),
    30: int(os.getenv('STREAK_REWARD_30', '5')),
}

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
