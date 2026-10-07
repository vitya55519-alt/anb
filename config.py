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

# ── MiniMax (V3.45: primary chat provider, замена OpenRouter) ──────────────
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "").strip()
MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.io/v1").strip().rstrip("/")
MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-M3").strip()

# ── SpicyAPI (V3.45: uncensored Seedream для фото «наедине» и «косплей») ──
SPICYAPI_KEY = os.getenv("SPICYAPI_KEY", "").strip()
# V3.46.1: this is the base the photo engine actually calls. It was previously
# hardcoded in private_photo_service (…/api/v1) while this config value (…/v1)
# was dead and pointed at the wrong path — so the endpoint could not be
# overridden from the environment. The real (working) path is now the default
# and remains overridable via SPICYAPI_BASE_URL without a code change.
SPICYAPI_BASE_URL = os.getenv("SPICYAPI_BASE_URL", "https://api.spicyapi.ai/api/v1").strip().rstrip("/")

# ── V3.45: Фото «наедине» и «Косплей» — монетизация через персики ──────────
# Бесплатные лимиты (1 наедине + 1 косплей = 2 всего в день)
PRIVATE_PHOTO_FREE_DAILY = max(0, int(os.getenv("PRIVATE_PHOTO_FREE_DAILY", "1")))
COSPLAY_PHOTO_FREE_DAILY = max(0, int(os.getenv("COSPLAY_PHOTO_FREE_DAILY", "1")))
# Цена после бесплатного лимита (в персиках)
PRIVATE_PHOTO_PEACH_COST = max(1, int(os.getenv("PRIVATE_PHOTO_PEACH_COST", "2")))
COSPLAY_PHOTO_PEACH_COST = max(1, int(os.getenv("COSPLAY_PHOTO_PEACH_COST", "2")))
# Hot Pass — безлимитная подписка на фото «наедине» и «косплей»
HOT_PASS_DAY_PEACHES = max(1, int(os.getenv("HOT_PASS_DAY_PEACHES", "5")))
HOT_PASS_WEEK_PEACHES = max(1, int(os.getenv("HOT_PASS_WEEK_PEACHES", "25")))
HOT_PASS_MONTH_PEACHES = max(1, int(os.getenv("HOT_PASS_MONTH_PEACHES", "80")))
# Видео за персики — ЕДИНАЯ цена видео-продукта на персиковом рельсе:
# студия Mini App (webapp_service.WEBAPP_VIDEO_COST_CREDITS читает её).
# V3.55.5: 5 -> 20 🍑 — клип сжигает картинковый рендер + видео-движок.
# Звёздный/токеновый рельсы бота (VIDEO_COST_STARS/VIDEO_TOKEN_COST) — свои.
VIDEO_PEACH_COST = max(1, int(os.getenv("VIDEO_PEACH_COST", "20")))
# Голос + фото комбо
VOICE_PHOTO_PEACH_COST = max(1, int(os.getenv("VOICE_PHOTO_PEACH_COST", "3")))
# Серия фото (3-5 штук в одном образе)
PHOTO_SERIES_PEACH_COST = max(1, int(os.getenv("PHOTO_SERIES_PEACH_COST", "5")))
# SpicyAPI модель для uncensored генерации
SPICYAPI_IMAGE_MODEL = os.getenv("SPICYAPI_IMAGE_MODEL", "bytedance/seedream-5.0-lite/edit").strip()
# V3.46.1: the nude «Наедине» categories must render text-to-image (no clothed
# reference — i2i keeps a clothed subject clothed, V3.45.23) on the UNCENSORED
# SpicyAPI engine, because the fal Seedream route is censored and refuses full
# nudity. The exact t2i model id is provider-specific, so it is env-overridable;
# if the default is wrong the admin toast now shows the real SpicyAPI error and
# this can be corrected from Railway without a redeploy.
SPICYAPI_T2I_MODEL = os.getenv("SPICYAPI_T2I_MODEL", "bytedance/seedream-5.0-lite/text-to-image").strip()
SPICYAPI_IMAGE_TIMEOUT = max(30, min(180, int(os.getenv("SPICYAPI_IMAGE_TIMEOUT", "90"))))

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
# V3.20.1: Gemini 2.5 TTS — natural human-like voices for voice messages
# (edge-tts stays as the free fallback). Same key/base URL as the video chain.
GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts").strip()
GEMINI_TTS_ENABLED = bool(GEMINI_API_KEY_VALID)
GEMINI_VIDEO_BASE_URL = os.getenv("GEMINI_VIDEO_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
GEMINI_VIDEO_DURATION_SECONDS = max(4, min(8, int(os.getenv("GEMINI_VIDEO_DURATION_SECONDS", "8"))))
GEMINI_VIDEO_RESOLUTION = os.getenv("GEMINI_VIDEO_RESOLUTION", "720p").strip()
GEMINI_VIDEO_ASPECT_RATIO = os.getenv("GEMINI_VIDEO_ASPECT_RATIO", "9:16").strip()
GEMINI_VIDEO_TIMEOUT_SECONDS = max(60, min(420, int(os.getenv("GEMINI_VIDEO_TIMEOUT_SECONDS", "360"))))
VIDEO_COST_STARS = max(1, int(os.getenv("VIDEO_COST_STARS", "50")))
# Paid gallery download: the user re-sends their own uncompressed photo as a
# Telegram document (full resolution). Kept low to encourage repeat use.
GALLERY_DOWNLOAD_STARS = max(1, int(os.getenv("GALLERY_DOWNLOAD_STARS", "30")))
# Premium perk: this many photo animations per day are free for Premium users;
# any extra animation on the same day is sold for VIDEO_COST_STARS Stars.
VIDEO_PREMIUM_FREE_DAILY = max(0, int(os.getenv("VIDEO_PREMIUM_FREE_DAILY", "2")))
# V3.53.0: «Собери галерею» — every GALLERY_SET_SIZE delivered photos of one
# character (bot chat + Mini App chat/private/circle/video) completes a gallery
# set («quest done»), then the next set begins. One rolling counter per character.
GALLERY_SET_SIZE = max(1, int(os.getenv("GALLERY_SET_SIZE", "50")))

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
if "/" in GEMINI_IMAGE_MODEL:
    # V3.44.19: OpenRouter-style ids (google/gemini-…) are rejected by the
    # native Google endpoint with 404 — that is how the ordinary-scene leg died
    # silently while the bill landed on the chat account. The fal-only default
    # route ignores this leg, so this is a warning, not a refusal.
    print(
        f'CONFIG WARNING: GEMINI_IMAGE_MODEL="{GEMINI_IMAGE_MODEL}" contains "/" — '
        'the native Google endpoint needs a bare model name like gemini-3.1-flash-image. '
        'The fal-only photo route (V3.44.19) does not use this leg.',
        flush=True,
    )
GEMINI_IMAGE_TIMEOUT_SECONDS = max(30, min(240, int(os.getenv("GEMINI_IMAGE_TIMEOUT_SECONDS", "120"))))
GEMINI_IMAGE_ESTIMATED_COST_USD = float(os.getenv("GEMINI_IMAGE_ESTIMATED_COST_USD", "0.02"))
GEMINI_IMAGE_ASPECT_RATIO = os.getenv("GEMINI_IMAGE_ASPECT_RATIO", "3:4").strip()
GEMINI_IMAGE_SIZE = os.getenv("GEMINI_IMAGE_SIZE", "1K").strip()

CHARACTER_ID = os.getenv("CHARACTER_ID", "anna_01")
CHARACTER_DIR = Path(os.getenv("CHARACTER_DIR", str(BASE_DIR / "data" / "characters")))
CHARACTER_FILE = os.getenv("CHARACTER_FILE", str(CHARACTER_DIR / "anna.json"))

# ── Image generation: fal/Seedream only (V3.44.19); OpenAI leg optional ─────
# V3.44.19 owner rule: «фото через fal.ai, OpenRouter — только общение».
# IMAGE_BASE_URL used to fall back to AI_BASE_URL, which itself defaults to the
# OpenRouter URL whenever OPENROUTER_API_KEY is set — so a pasted OpenAI/IMAGE
# key silently billed images on the chat account (the google/gemini-…-image
# charges in his OpenRouter activity). The image leg no longer inherits the
# OpenRouter URL and refuses to start when one is set explicitly.
IMAGE_API_KEY = (os.getenv("IMAGE_API_KEY") or AI_KEY).strip()
_non_or_image_base = AI_BASE_URL if (AI_BASE_URL and "openrouter" not in AI_BASE_URL.lower()) else None
IMAGE_BASE_URL = os.getenv("IMAGE_BASE_URL") or _non_or_image_base
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-2")
IMAGE_SIZE = os.getenv("IMAGE_SIZE", "1024x1536")
IMAGE_QUALITY = os.getenv("IMAGE_QUALITY", "medium")
OPENAI_IMAGE_ESTIMATED_COST_USD = float(os.getenv("OPENAI_IMAGE_ESTIMATED_COST_USD", "0"))
IMAGE_REFERENCE_MODE = os.getenv("IMAGE_REFERENCE_MODE", "edit").lower()
OPENAI_IMAGE_AVAILABLE = bool(AI_KEY) and os.getenv("OPENAI_IMAGE_AVAILABLE", "false").strip().lower() in {"1", "true", "yes", "on"}
if OPENAI_IMAGE_AVAILABLE and IMAGE_BASE_URL and "openrouter" in IMAGE_BASE_URL.lower():
    OPENAI_IMAGE_AVAILABLE = False
    print(
        'CONFIG WARNING: IMAGE_BASE_URL points at OpenRouter — the OpenAI image leg is '
        'DISABLED (photos must never bill the chat account; V3.44.19 owner decision). '
        'Point IMAGE_BASE_URL at the official OpenAI endpoint or unset it.',
        flush=True,
    )

# fal.ai / Seedream is the ONLY photo engine by default (V3.44.19). Keep the
# key server-side in Railway.
FAL_KEY = os.getenv("FAL_KEY", "").strip()
# V3.44.20: the default is the PROVEN partner route bytedance/seedream/v5/pro/edit
# (fal.run answers 401 "exists, needs auth" for it). The fal.ai SANDBOX id
# d96lp9cregjb2a5jepag (fal.ai/sandbox?models=d96lp9cregjb2a5jepag&op=
# image.edit_image) is a playground-internal id — fal.run answers 404 for it,
# so it CANNOT be the API route (that 404/reset is what killed every photo
# right after V3.44.19 shipped it as the default). When the owner finds the
# real registry id behind that sandbox model (the "API" tab on its model
# page), it can be set here via the FAL_MODEL env var; the request chain walks
# v5/pro -> v5/lite -> v4.5 on 404s and transport failures either way.
FAL_MODEL = os.getenv("FAL_MODEL", "bytedance/seedream/v5/pro/edit").strip()
# V3.43.1: the edit endpoint rejects empty image_urls (HTTP 422), so freeform
# studio prompts go to the dedicated text-to-image endpoint instead.
# V3.44.3: the "/v5.0/" route does not exist on fal (HTTP 404) and v5 Pro is a
# Partner model that may need separate API access — the proven t2i default
# stays on v4.5; adult scenes go through the edit endpoint above.
FAL_MODEL_T2I = os.getenv("FAL_MODEL_T2I", "fal-ai/bytedance/seedream/v4.5/text-to-image").strip()
FAL_IMAGE_SIZE = os.getenv("FAL_IMAGE_SIZE", "portrait_4_3").strip()
FAL_TIMEOUT_SECONDS = int(os.getenv("FAL_TIMEOUT_SECONDS", "210"))
FAL_CONNECT_TIMEOUT_SECONDS = int(os.getenv("FAL_CONNECT_TIMEOUT_SECONDS", "20"))
FAL_WRITE_TIMEOUT_SECONDS = int(os.getenv("FAL_WRITE_TIMEOUT_SECONDS", "60"))
FAL_POOL_TIMEOUT_SECONDS = int(os.getenv("FAL_POOL_TIMEOUT_SECONDS", "30"))
FAL_RETRIES = max(0, min(3, int(os.getenv("FAL_RETRIES", "2"))))
FAL_RETRY_BACKOFF_SECONDS = float(os.getenv("FAL_RETRY_BACKOFF_SECONDS", "2"))
FAL_ESTIMATED_COST_USD = float(os.getenv("FAL_ESTIMATED_COST_USD", "0.04"))
# V3.44.19: default 'fal' — every photo (ordinary and intimate alike) renders
# on fal.ai, the account the owner actually watches; a fal failure refunds
# instead of quietly spending on someone else's engine. 'hybrid' (Gemini
# native for ordinary scenes + cross-engine fallbacks) and 'gemini'/'openai'
# remain available via env for anyone who wants them back.
PHOTO_ROUTER_MODE = os.getenv("PHOTO_ROUTER_MODE", "fal").strip().lower()
SEEDREAM_RELATIONSHIP_LEVEL = int(os.getenv("SEEDREAM_RELATIONSHIP_LEVEL", "5"))
PHOTO_SET_SIZE = max(1, min(3, int(os.getenv("PHOTO_SET_SIZE", "1"))))
# V3.44.15: hard cap for one whole photo delivery (all engines + fallbacks).
# fal's worst-case silent chain (3 routes x 3 retries x 210s read timeout)
# could grind ~30 minutes — she said «смотри на меня» and nothing arrived.
# The cap lands in the failure branch: refund + honest retry message.
PHOTO_TOTAL_BUDGET_SECONDS = max(60, int(os.getenv("PHOTO_TOTAL_BUDGET_SECONDS", "300")))

# ── V3.44.18: money telemetry and daily brakes ──────────────────────────────
# The owner billed $14 in five days with only 46 chat messages a day, and the
# bot could not say where a single cent went: generate_text discarded the
# provider usage block, photo cost existed only for DELIVERED images, and the
# main photo engine (Gemini image) carried a unit price of 0 — so «себестоимость
# фото: $0.00» in /stats was structurally blind, not true.
# Per-million-token prices used to estimate cost when the provider does not
# return one (OpenRouter returns usage.cost when asked, Gemini does not).
LLM_USD_PER_M_INPUT = float(os.getenv("LLM_USD_PER_M_INPUT", "0.23"))
LLM_USD_PER_M_OUTPUT = float(os.getenv("LLM_USD_PER_M_OUTPUT", "0.96"))
GEMINI_LLM_USD_PER_M_INPUT = float(os.getenv("GEMINI_LLM_USD_PER_M_INPUT", "0.10"))
GEMINI_LLM_USD_PER_M_OUTPUT = float(os.getenv("GEMINI_LLM_USD_PER_M_OUTPUT", "0.40"))
# Ask OpenRouter to bill-report every completion (usage.include). Costs nothing
# extra; it is the only way to see real spend without opening the dashboard.
LLM_REPORT_USAGE = os.getenv("LLM_REPORT_USAGE", "true").strip().lower() in {"1", "true", "yes", "on"}
# Daily brakes, 0 = brake off. Only AUXILIARY LLM work is throttled (memory
# extraction, style adaptation, relationship pulse, photo ideas/reactions and
# the humanizer rewrite) — the visible chat reply is never blocked. When the
# image brake trips, generation is refused BEFORE any provider call and the
# existing refund path returns the money the user already paid.
SPEND_LLM_DAILY_BUDGET_USD = max(0.0, float(os.getenv("SPEND_LLM_DAILY_BUDGET_USD", "1.0")))
SPEND_IMAGE_DAILY_BUDGET_USD = max(0.0, float(os.getenv("SPEND_IMAGE_DAILY_BUDGET_USD", "2.0")))

# V3.19.9: Pollinations.ai was removed (repeated http_500 + wrong-subject
# renders). Photo providers are now Gemini Image -> OpenAI -> fal/Seedream.

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

# V3.44.21: Platega card/SBP payments (platega.io) — the external (non-Telegram)
# scenario; Stars stay the in-Telegram method per Telegram policy. Platega
# replaced FreeKassa end to end. The MerchantId + API key come from the cabinet
# (my.platega.io → Настройки → Интеграция и API); both are required, otherwise
# the card button and the webhook endpoints stay off.
PLATEGA_MERCHANT_ID = os.getenv("PLATEGA_MERCHANT_ID", "").strip()
PLATEGA_API_KEY = os.getenv("PLATEGA_API_KEY", "").strip()
PLATEGA_ENABLED = bool(PLATEGA_MERCHANT_ID and PLATEGA_API_KEY)
# docs.platega.io «Начало работы»: базовый URL — https://app.platega.io/
# (verified live: POST /v2/transaction/process returns the payment link,
# GET /transaction/{id} the status). Override only if Platega moves.
PLATEGA_API_BASE = os.getenv("PLATEGA_API_BASE", "https://app.platega.io").strip().rstrip("/")
# V3.55.0: owner repriced the monthly plan 899 → 699 ₽ (Come Closer benchmark
# was 899; the cut is a conversion bet for the RU audience).
PLATEGA_PREMIUM_PRICE_RUB = max(1, int(os.getenv("PLATEGA_PREMIUM_PRICE_RUB", "699")))
# V3.34.1: card/SBP price of the weekly plan (rub next to the Stars price).
# V3.43.0: owner benchmarked Come Closer and asked to take their prices —
# week 299₽ / month 899₽ / 3 months 1799₽.
# V3.55.0: weekly repriced 299 → 199 ₽.
PLATEGA_PREMIUM_WEEKLY_PRICE_RUB = max(1, int(os.getenv("PLATEGA_PREMIUM_WEEKLY_PRICE_RUB", "199")))
# V3.43.0: the 3-month plan the competitor card shows (−50% vs buying monthly).
PLATEGA_PREMIUM_QUARTERLY_PRICE_RUB = max(1, int(os.getenv("PLATEGA_PREMIUM_QUARTERLY_PRICE_RUB", "1799")))
# Display-only dollar equivalent of the monthly plan. V3.20.1 charged it for
# real through the FreeKassa multi-currency kassa; Platega invoices in rubles
# (the payer picks SBP/card/crypto on its page), so this is now just a price tag.
# V3.55.0: price tag raised $5 → $8 (round marketing number, not an FX quote).
PREMIUM_PRICE_USD = max(1, int(os.getenv("PREMIUM_PRICE_USD", "8")))
# Public base URL of this Railway service (generated domain). Used in the
# Platega payment redirects (return/failedUrl) and every Mini App entry
# point (menu button, /app command, inline buttons).
# V3.35.0: when the variable is not set explicitly, fall back to Railway's
# generated public domain so the «Открыть приложение» button cannot silently
# disappear just because PUBLIC_BASE_URL was forgotten in a fresh deploy.
_PUBLIC_BASE_URL_RAW = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
if not _PUBLIC_BASE_URL_RAW:
    _railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip().rstrip("/")
    if _railway_domain:
        _PUBLIC_BASE_URL_RAW = (
            _railway_domain if _railway_domain.startswith("http")
            else f"https://{_railway_domain}"
        )
PUBLIC_BASE_URL = _PUBLIC_BASE_URL_RAW
WEB_PORT = int(os.getenv("PORT", "8080"))

# V3.45.27: «чат только в Mini App». When true a plain conversational message
# typed at the BOT no longer calls the LLM — the bot shows the menu and points
# to the app instead (structured buttons/photo/constructor keep working). It is
# auto-disabled if PUBLIC_BASE_URL is missing so the bot never dead-ends.
BOT_CHAT_REDIRECT = os.getenv("BOT_CHAT_REDIRECT", "1").strip() not in ("0", "false", "no", "off")

FAL_KEY = os.getenv("FAL_KEY", "").strip()
FAL_VIDEO_ENDPOINT = os.getenv("FAL_VIDEO_ENDPOINT", "fal-ai/wan2.2/image-to-video").strip()
FAL_VIDEO_TIMEOUT_SECONDS = max(120, min(900, int(os.getenv("FAL_VIDEO_TIMEOUT_SECONDS", "600"))))

# Per-user adaptive communication profile. The model never rewrites its own code/prompt;
# it only learns bounded style signals and recurring expressions into PostgreSQL.
ADAPTATION_ENABLED = os.getenv("ADAPTATION_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
ADAPTATION_ANALYZE_EVERY = max(3, min(20, int(os.getenv("ADAPTATION_ANALYZE_EVERY", "5"))))
ADAPTATION_MAX_EXPRESSIONS = max(3, min(20, int(os.getenv("ADAPTATION_MAX_EXPRESSIONS", "12"))))

# V3.55.1: owner tightened the free tier 50 → 30 messages/day for non-premium
# (Premium's «безлимит сообщений» must actually bite). The new-user 24h
# unlimited window below stays the activation lever.
FREE_MESSAGES_PER_DAY = int(os.getenv("FREE_MESSAGES_PER_DAY", "30"))
# V3.47.2: a brand-new user gets unlimited TEXT messages for this many hours
# after registration (activation lever, mirrors the benchmark's «первые 24 часа
# текст бесплатно»). Photo/video gates are untouched — text only.
NEW_USER_UNLIMITED_HOURS = max(0, int(os.getenv("NEW_USER_UNLIMITED_HOURS", "24")))
FREE_PHOTOS_LEVEL_1_2 = int(os.getenv("FREE_PHOTOS_LEVEL_1_2", "1"))
FREE_PHOTOS_LEVEL_3_6 = int(os.getenv("FREE_PHOTOS_LEVEL_3_6", "2"))
PREMIUM_MONTHLY_STARS = int(os.getenv("PREMIUM_MONTHLY_STARS", "500"))
PREMIUM_MONTHLY_PHOTO_CREDITS = int(os.getenv("PREMIUM_MONTHLY_PHOTO_CREDITS", "12"))
# V3.34.1: the short Premium plan — a week for the undecided. Priced per day
# slightly above the monthly plan so the month stays the better deal.
PREMIUM_WEEKLY_STARS = int(os.getenv("PREMIUM_WEEKLY_STARS", "150"))
PREMIUM_WEEKLY_PHOTO_CREDITS = int(os.getenv("PREMIUM_WEEKLY_PHOTO_CREDITS", "3"))
# V3.43.0: the 3-month plan (three monthly credit shares, priced below 3×month).
PREMIUM_QUARTERLY_STARS = int(os.getenv("PREMIUM_QUARTERLY_STARS", "1200"))
PREMIUM_QUARTERLY_PHOTO_CREDITS = int(os.getenv("PREMIUM_QUARTERLY_PHOTO_CREDITS", "36"))
PHOTO_COST_STARS = int(os.getenv("PHOTO_COST_STARS", "25"))
# V3.43.1 → V3.44.22: the peach pack ladder. The star prices used to inherit
# PHOTO_COST_STARS * N (250/675/1875 ★ — the 100-pack cost more Stars than
# three months of Premium) and the ruble side was a ladder guess. Now every
# pack carries explicit round ₽ + ★ prices that read as one story with the
# Premium plans: 50★/99₽ · 125★/249₽ · 350★/699₽ next to Premium 500★ (699₽
# after the V3.55.0 repricing — the 100-pack and a Premium month now cost the
# same in rubles, which pushes regulars toward Premium: perks on top).
# One peach lands at ~9.9/8.3/7.0 ₽ — a studio picture (10 🍑) costs about a
# custom chat photo, not a month of Premium.
PEACH_PACK_10_STARS = int(os.getenv("PEACH_PACK_10_STARS", "50"))
PEACH_PACK_30_STARS = int(os.getenv("PEACH_PACK_30_STARS", "125"))
PEACH_PACK_100_STARS = int(os.getenv("PEACH_PACK_100_STARS", "350"))
PEACH_PACK_STARS = {"peach_pack_10": PEACH_PACK_10_STARS, "peach_pack_30": PEACH_PACK_30_STARS, "peach_pack_100": PEACH_PACK_100_STARS}
# V3.44.22: the REAL Platega charge for each pack (was a ladder guess).
PEACH_PACK_10_RUB = max(1, int(os.getenv("PEACH_PACK_10_RUB", "99")))
PEACH_PACK_30_RUB = max(1, int(os.getenv("PEACH_PACK_30_RUB", "249")))
PEACH_PACK_100_RUB = max(1, int(os.getenv("PEACH_PACK_100_RUB", "699")))
PEACH_PACK_RUB = {"peach_pack_10": PEACH_PACK_10_RUB, "peach_pack_30": PEACH_PACK_30_RUB, "peach_pack_100": PEACH_PACK_100_RUB}
PEACH_PACK_CREDITS = {"peach_pack_10": 10, "peach_pack_30": 30, "peach_pack_100": 100}
# V3.44.23: the custom-peach tile — the user types how many peaches they want,
# and pays at the small-pack per-unit rate (no bulk discount).
PEACH_CUSTOM_STARS_PER_UNIT = max(1, PEACH_PACK_10_STARS // 10)
PEACH_CUSTOM_RUB_PER_UNIT = max(1, PEACH_PACK_10_RUB // 10)
CHAT_PHOTO_OFFER_STARS = int(os.getenv("CHAT_PHOTO_OFFER_STARS", "5"))
CUSTOM_PHOTO_COST_STARS = int(os.getenv("CUSTOM_PHOTO_COST_STARS", "40"))
QUEST_REPLAY_STARS = int(os.getenv("QUEST_REPLAY_STARS", "10"))
PREMIUM_MONTHLY_QUEST_REPLAYS = int(os.getenv("PREMIUM_MONTHLY_QUEST_REPLAYS", "2"))

# V3.20.0 retention & monetization pack.
# Demo premium: a one-time free taste granted when the user hits the daily
# chat limit — losing it converts stronger than never having it.
DEMO_PREMIUM_HOURS = max(1, min(72, int(os.getenv("DEMO_PREMIUM_HOURS", "3"))))
# One-time 24h premium discount offered after the demo is used; the deadline
# creates urgency in the paywall button.
PREMIUM_DISCOUNT_PERCENT = max(0, min(90, int(os.getenv("PREMIUM_DISCOUNT_PERCENT", "30"))))
PREMIUM_DISCOUNT_STARS = max(1, int(PREMIUM_MONTHLY_STARS * (100 - PREMIUM_DISCOUNT_PERCENT) // 100))
PREMIUM_DISCOUNT_HOURS = max(1, int(os.getenv("PREMIUM_DISCOUNT_HOURS", "24")))
# Proactive emotional pushes: static miss/jealousy texts fire after this many
# hours of silence (cheap, no LLM), the LLM-crafted nudge still fires after
# PROACTIVE_MIN_HOURS.
RETENTION_REMINDER_HOURS = max(6, min(48, int(os.getenv("RETENTION_REMINDER_HOURS", "24"))))
# V3.44.16: recurring retention nudges. The old guard allowed exactly ONE
# push per user lifetime (last_nudge_at >= last_active_at skipped forever),
# so D7 collapsed to 1% — now nudges repeat while the user stays away.
RETENTION_NUDGE_INTERVAL_HOURS = max(6, min(48, int(os.getenv("RETENTION_NUDGE_INTERVAL_HOURS", "24"))))
RETENTION_MAX_NUDGES = max(1, min(10, int(os.getenv("RETENTION_MAX_NUDGES", "5"))))
# V3.55.9: ghost window — a user silent longer than this is churned: no more
# retention/LLM pushes at all (a real return re-arms the ladder). Before this,
# every failed send (user blocked the bot) left the user eligible again the
# next hour, so the hourly scan re-burned the proactive LLM budget on ghosts.
PROACTIVE_MAX_INACTIVE_DAYS = max(3, min(30, int(os.getenv("PROACTIVE_MAX_INACTIVE_DAYS", "10"))))
# The day-1 hook: a special "your bonus wheel is waiting" push for YOUNG
# accounts that went silent — D1 was 5%, the wheel gives a concrete reason
# to open the app on day 2.
DAY1_HOOK_MAX_ACCOUNT_HOURS = max(24, int(os.getenv("DAY1_HOOK_MAX_ACCOUNT_HOURS", "72")))
DAY1_HOOK_MIN_INACTIVE_HOURS = max(6, int(os.getenv("DAY1_HOOK_MIN_INACTIVE_HOURS", "18")))
# Morning/evening rituals: she writes first in the user's local time windows.
RITUALS_ENABLED = os.getenv("RITUALS_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
RITUAL_MORNING_START_HOUR = max(0, min(23, int(os.getenv("RITUAL_MORNING_START_HOUR", "7"))))
RITUAL_MORNING_END_HOUR = max(0, min(23, int(os.getenv("RITUAL_MORNING_END_HOUR", "10"))))
RITUAL_EVENING_START_HOUR = max(0, min(23, int(os.getenv("RITUAL_EVENING_START_HOUR", "21"))))
RITUAL_EVENING_END_HOUR = max(0, min(23, int(os.getenv("RITUAL_EVENING_END_HOUR", "23"))))
RITUAL_MAX_INACTIVE_DAYS = max(1, int(os.getenv("RITUAL_MAX_INACTIVE_DAYS", "7")))

# V3.52.0: «Жизнь без тебя» — proactive, personality-grounded life moments she
# sends on her own (a slice of her day, a memory callback, an open loop), for the
# character the user actually selected. This is a curiosity hook, NOT a guilt
# nudge: it only targets recently-active, opted-in users. Photos come from the
# existing media pool only (never a fresh provider render) → near-zero extra cost.
LIFE_EVENTS_ENABLED = os.getenv("LIFE_EVENTS_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
LIFE_EVENTS_MAX_PER_DAY = max(0, min(4, int(os.getenv("LIFE_EVENTS_MAX_PER_DAY", "2"))))
LIFE_EVENTS_SCAN_MINUTES = max(10, min(120, int(os.getenv("LIFE_EVENTS_SCAN_MINUTES", "20"))))
# Only users active within this window get life events (reward showing up, not
# chasing the churned — that path is _proactive/retention).
LIFE_EVENTS_ACTIVE_WINDOW_DAYS = max(1, int(os.getenv("LIFE_EVENTS_ACTIVE_WINDOW_DAYS", "7")))
# Never write during the user's local quiet hours [start, end) (wrap-aware).
LIFE_EVENTS_QUIET_START_HOUR = max(0, min(23, int(os.getenv("LIFE_EVENTS_QUIET_START_HOUR", "23"))))
LIFE_EVENTS_QUIET_END_HOUR = max(0, min(23, int(os.getenv("LIFE_EVENTS_QUIET_END_HOUR", "7"))))
# Probability of attaching a pool photo to a life moment (0 disables).
LIFE_EVENTS_PHOTO_CHANCE = max(0.0, min(1.0, float(os.getenv("LIFE_EVENTS_PHOTO_CHANCE", "0.25"))))

# V3.19.0: personal character constructor — one-time Stars payment that builds
# a private chat persona (appearance + personality + relationship role) with a
# generated avatar. Optional user face photo enables face-swap identity.
CONSTRUCTOR_COST_STARS = max(1, int(os.getenv("CONSTRUCTOR_COST_STARS", "50")))
# V3.44.2 → V3.44.22 → V3.45.28: creating a character always costs peaches.
# The «public is free» perk is retired — every avatar is drawn on our GPU bill,
# so a flat peach price funds it and throttles spam. Publishing to the
# «Сообщество» витрина is a separate step (moderation comes next release).
CONSTRUCTOR_COST_PEACHES = max(1, int(os.getenv("CONSTRUCTOR_COST_PEACHES", "20")))
# V3.27.0: ruble side of the shop (FreeKassa): character constructor price,
# token price/pack (1 token = TOKEN_PRICE_RUB) and the animation token cost.
CONSTRUCTOR_COST_RUB = max(1, int(os.getenv("CONSTRUCTOR_COST_RUB", "200")))
TOKEN_PRICE_RUB = max(1, int(os.getenv("TOKEN_PRICE_RUB", "10")))
TOKEN_PACK_SIZE = max(1, int(os.getenv("TOKEN_PACK_SIZE", "5")))
VIDEO_TOKEN_COST = max(1, int(os.getenv("VIDEO_TOKEN_COST", "5")))
# V3.30.0: cosplay photoshoot price in tokens (costume picker in photo menu).
COSPLAY_TOKEN_COST = max(1, int(os.getenv("COSPLAY_TOKEN_COST", "10")))

# V3.36.0: fiat equivalents next to every Stars price (owner request:
# «напротив каждой цены звездочек добавь цену в рублях и долларах»).
# Premium and the constructor reuse their REAL charges — the card prices
# FreeKassa actually bills (rub + the $8 price tag since V3.55.0); every
# other product shows the ladder below, which is roughly what the Stars
# themselves cost to top up inside Telegram. Dollars are round marketing
# numbers, not FX quotes.
STARS_FIAT_RUB: dict[int, int] = {
    5: 15, 10: 25, 15: 39, 20: 49, 25: 59, 30: 69, 40: 89, 50: 99,
}
STARS_FIAT_USD: dict[int, float] = {
    5: 0.2, 10: 0.3, 15: 0.5, 20: 0.6, 25: 0.75, 30: 0.85, 40: 1.0, 50: 1.2,
}
# The monthly plan's dollars are PREMIUM_PRICE_USD (display-only since the
# FreeKassa multi-currency kassa retired); the week has no USD price tag.
PREMIUM_WEEKLY_PRICE_USD = float(os.getenv("PREMIUM_WEEKLY_PRICE_USD", "1.5"))
CONSTRUCTOR_PRICE_USD = float(os.getenv("CONSTRUCTOR_PRICE_USD", "2.5"))


def usd_str(value: float) -> str:
    """'$6' / '$1.5' / '$0.75' — dollars without trailing zeros."""
    return '$' + f'{value:g}'


def fiat_values(stars: int) -> tuple[int | None, float | None]:
    """Ladder (rub, usd) for a star count — None when no pretty number exists."""
    return STARS_FIAT_RUB.get(stars), STARS_FIAT_USD.get(stars)


def fiat_suffix(stars: int, rub: int | None = None, usd: float | None = None,
                rub_enabled: bool = True) -> str:
    """' · 59 ₽ · $0.75' — the fiat line shown next to a Stars price.

    Explicit ``rub``/``usd`` override the ladder (premium and the constructor
    pass their real card prices); ``rub_enabled=False`` hides only the rub
    part — a real charge that is currently off; the dollar equivalent still
    shows. Star counts outside the ladder fall back to ~2 ₽ / ~$0.024 per Star.
    """
    if rub is None:
        rub = STARS_FIAT_RUB.get(stars)
        if rub is None:
            rub = max(1, stars * 2)
    if usd is None:
        usd = STARS_FIAT_USD.get(stars)
        if usd is None:
            usd = round(stars * 0.024, 2)
    parts = []
    if rub_enabled:
        parts.append(f'{rub} ₽')
    parts.append(usd_str(usd))
    return ' · ' + ' · '.join(parts)

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

# V3.55.5: daily streak gift — days 1..6 pay DAY_AMOUNT, every JACKPOT_DAY-th
# day pays JACKPOT_AMOUNT (cycle restarts after it). A missed day resets the
# streak to 1. If the balance is at or above BALANCE_CAP the grant is skipped
# WITHOUT consuming the day (the user spends, then claims). Day boundary is
# 03:00 MSK == 00:00 UTC (no DST), so key = now_utc.date().
# PROMO_MAX_CREDITS caps the nominal
# of an admin-created promo code (no Premium-day grants on this rail).
DAILY_GIFT_ENABLED = os.getenv("DAILY_GIFT_ENABLED", "1") == "1"
DAILY_GIFT_DAY_AMOUNT = int(os.getenv("DAILY_GIFT_DAY_AMOUNT", "1"))
DAILY_GIFT_JACKPOT_DAY = int(os.getenv("DAILY_GIFT_JACKPOT_DAY", "7"))
DAILY_GIFT_JACKPOT_AMOUNT = int(os.getenv("DAILY_GIFT_JACKPOT_AMOUNT", "3"))
DAILY_GIFT_BALANCE_CAP = int(os.getenv("DAILY_GIFT_BALANCE_CAP", "15"))
PROMO_MAX_CREDITS = int(os.getenv("PROMO_MAX_CREDITS", "20"))
# V3.55.5: полка welcome — сеется на старте, чтобы новых юзеров хватало на
# самое дешёвое платное действие: копилка стрика 15 🍑 + 5 🍑 за код = 20 🍑
# студийного видео. Отключается PROMO_WELCOME_ENABLED=0.
PROMO_WELCOME_ENABLED = os.getenv("PROMO_WELCOME_ENABLED", "1") == "1"
PROMO_WELCOME_CODE = (os.getenv("PROMO_WELCOME_CODE", "ANNA5").strip().upper() or "ANNA5")
PROMO_WELCOME_CREDITS = max(1, min(PROMO_MAX_CREDITS, int(os.getenv("PROMO_WELCOME_CREDITS", "5"))))
PROMO_WELCOME_CAP = max(0, int(os.getenv("PROMO_WELCOME_CAP", "1000")))

# V3.37.0: the affiliate (partner) program — money commission with every
# purchase a referred user ever makes, paid out on request. The percent and
# the payout threshold are env-tunable so the owner can run promos.
PARTNER_ENABLED = os.getenv("PARTNER_ENABLED", "1") == "1"
REFERRAL_COMMISSION_PCT = float(os.getenv("REFERRAL_COMMISSION_PCT", "30"))
PARTNER_MIN_PAYOUT_RUB = int(os.getenv("PARTNER_MIN_PAYOUT_RUB", "500"))
# V3.47.0: referral bonus tiers — a one-time reward the moment a referrer
# crosses an invite count. Format "count:credits:premium_days,..." So 3 invites
# → +10 🍑; 10 → +30 🍑 and 7 days Premium; 25 → +100 🍑 and 30 days Premium.
# Each tier is granted at most once per user (guarded by a marker event). Empty
# string disables the whole ladder.
REFERRAL_BONUS_TIERS_RAW = os.getenv(
    "REFERRAL_BONUS_TIERS", "3:10:0,10:30:7,25:100:30").strip()


def _parse_referral_tiers(raw: str) -> list[tuple[int, int, int]]:
    tiers: list[tuple[int, int, int]] = []
    for chunk in raw.split(","):
        parts = chunk.strip().split(":")
        if len(parts) != 3:
            continue
        try:
            tiers.append((int(parts[0]), int(parts[1]), int(parts[2])))
        except (TypeError, ValueError):
            continue
    return sorted(tiers, key=lambda t: t[0])


REFERRAL_BONUS_TIERS = _parse_referral_tiers(REFERRAL_BONUS_TIERS_RAW)
# V3.43.0: support moved to a DEDICATED bot the owner reads personally
# (@Anna67901support_bot). Only the public username is configured here — the
# support bot's token never belongs in this service. «Поддержка» buttons hand
# the user a t.me link to it instead of arming an in-bot ticket.
SUPPORT_BOT_USERNAME = os.getenv("SUPPORT_BOT_USERNAME", "Anna67901support_bot").strip().lstrip('@')
# V3.44.21: THIS bot's own public @username (optional). /diagnostics shows it,
# and the Platega payment redirects fall back to a t.me deep link when
# PUBLIC_BASE_URL is not set. Empty default keeps every consumer optional.
BOT_USERNAME = os.getenv("BOT_USERNAME", "Anna67901_bot").strip().lstrip('@')
# V3.43.3: the support bot lives in this process too — when the (rotated)
# token is set in the host env, a second aiogram bot polls it, answers /start
# with SUPPORT_WELCOME_TEXT and forwards every appeal to the admins. The
# token stays in env only, exactly like TELEGRAM_TOKEN — never in the repo.
SUPPORT_BOT_TOKEN = os.getenv("SUPPORT_BOT_TOKEN", "").strip()
SUPPORT_WELCOME_TEXT = os.getenv(
    "SUPPORT_WELCOME_TEXT",
    "Привет! Ваше сообщение для нас важно ❤️\n"
    "Напишите ваше обращение и менеджер с вами свяжется.",
).strip()
# V3.43.0: «Бесплатные 🍑 за подписку на канал» — the owner's channel and the
# one-time peach bonus for being a member (checked via getChatMember).
# V3.55.0: owner repriced the funnel hook 30 → 20 🍑 (a 10🍑 picture/video is
# now exactly two subscriptions deep, so the free taste stays generous without
# giving away a full render per sign-up).
CHANNEL_SUBSCRIBE_USERNAME = os.getenv("CHANNEL_SUBSCRIBE_USERNAME", "Anna634212").strip().lstrip('@')
CHANNEL_SUBSCRIBE_BONUS_CREDITS = int(os.getenv("CHANNEL_SUBSCRIBE_BONUS_CREDITS", "20"))
# V3.43.0: how long a Telegram WebApp initData stays acceptable. The 24h
# default broke users who reopen the Mini App from the client's recents —
# the hash is still verified, only the replay window is wider now.
WEBAPP_INIT_DATA_MAX_AGE = int(os.getenv("WEBAPP_INIT_DATA_MAX_AGE", "604800"))
# Shown in the partner FAQ — the payout rails the owner actually supports.
PARTNER_PAYOUT_METHODS = os.getenv("PARTNER_PAYOUT_METHODS", "карта РФ, СБП, крипта (USDT)")

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

# ── Support-the-project donation (CloudTips) ────────────────────────────
# V3.31.3: an optional donation link shown to every new user right after the
# welcome, then reminded to active users about once a week. The owner can
# change the link or switch the weekly reminder off via Railway env vars.
DONATION_LINK = os.getenv("DONATION_LINK", "https://pay.cloudtips.ru/p/7afc7b16").strip()
# V3.44.22: the «Поддержать проект» button opens an in-bot amount chooser and
# pays through Platega; the CloudTips link stays as the fallback button shown
# while Platega is disabled.
DONATION_AMOUNTS_RUB = tuple(
    max(1, int(x)) for x in os.getenv("DONATION_AMOUNTS_RUB", "50,100,500").replace(" ", "").split(",")
    if x.strip().isdigit()
) or (50, 100, 500)
DONATION_REMINDER_ENABLED = os.getenv("DONATION_REMINDER_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
DONATION_REMINDER_INTERVAL_DAYS = max(1, int(os.getenv("DONATION_REMINDER_INTERVAL_DAYS", "7")))
DONATION_REMINDER_ACTIVE_DAYS = max(1, int(os.getenv("DONATION_REMINDER_ACTIVE_DAYS", "30")))

ADMIN_TELEGRAM_IDS = {int(x.strip()) for x in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",") if x.strip().isdigit()}

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN is not configured")
_has_llm = bool(OPENROUTER_API_KEY or GEMINI_API_KEY or AI_KEY)
if not _has_llm:
    raise RuntimeError(
        "No LLM provider configured. Set OPENEROUTER_API_KEY, GEMINI_API_KEY, or OPENAI_API_KEY."
    )
