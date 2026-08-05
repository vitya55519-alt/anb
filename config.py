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

AI_KEY = (os.getenv("OPENAI_API_KEY") or os.getenv("AI_KEY") or "").strip()
AI_MODEL = os.getenv("AI_MODEL", "gpt-4.1-mini")
AI_BASE_URL = os.getenv("AI_BASE_URL") or None

CHARACTER_ID = os.getenv("CHARACTER_ID", "anna_01")
CHARACTER_DIR = Path(os.getenv("CHARACTER_DIR", str(BASE_DIR / "data" / "characters")))
CHARACTER_FILE = os.getenv("CHARACTER_FILE", str(CHARACTER_DIR / "anna.json"))

IMAGE_API_KEY = (os.getenv("IMAGE_API_KEY") or AI_KEY).strip()
IMAGE_BASE_URL = os.getenv("IMAGE_BASE_URL") or AI_BASE_URL
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-2")
IMAGE_SIZE = os.getenv("IMAGE_SIZE", "1024x1536")
IMAGE_QUALITY = os.getenv("IMAGE_QUALITY", "medium")
IMAGE_REFERENCE_MODE = os.getenv("IMAGE_REFERENCE_MODE", "edit").lower()

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
PHOTO_SET_SIZE = max(1, min(3, int(os.getenv("PHOTO_SET_SIZE", "3"))))

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
CUSTOM_PHOTO_COST_STARS = int(os.getenv("CUSTOM_PHOTO_COST_STARS", "40"))

TTS_API_KEY = (os.getenv("TTS_API_KEY") or AI_KEY).strip()
TTS_MODEL = os.getenv("TTS_MODEL", "tts-1")
TTS_VOICE = os.getenv("TTS_VOICE", "nova")

PROACTIVE_MIN_HOURS = int(os.getenv("PROACTIVE_MIN_HOURS", "48"))
DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "UTC")
ADMIN_TELEGRAM_IDS = {int(x.strip()) for x in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",") if x.strip().isdigit()}

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN is not configured")
if not AI_KEY:
    raise RuntimeError("OPENAI_API_KEY (or AI_KEY) is not configured")
