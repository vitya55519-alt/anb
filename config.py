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

FREE_MESSAGES_PER_DAY = int(os.getenv("FREE_MESSAGES_PER_DAY", "80"))
FREE_PHOTOS_PER_DAY = int(os.getenv("FREE_PHOTOS_PER_DAY", "1"))
PREMIUM_PHOTOS_PER_DAY = int(os.getenv("PREMIUM_PHOTOS_PER_DAY", "4"))
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
