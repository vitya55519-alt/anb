import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Database
# Prefer Railway's DATABASE_URL. For local development use SQLite so the bot
# does not try to connect to localhost:3306 unless MySQL is explicitly set.
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("MYSQL_URL")
if not DATABASE_URL:
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_HOST = os.getenv("DB_HOST")
    DB_NAME = os.getenv("DB_NAME")
    if DB_USER and DB_PASSWORD and DB_HOST and DB_NAME:
        DATABASE_URL = f"mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"
    else:
        DATABASE_URL = f"sqlite:///{(BASE_DIR / 'waifubot.db').as_posix()}"
else:
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_HOST = os.getenv("DB_HOST")
    DB_NAME = os.getenv("DB_NAME")

# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_BOT_NAME = os.getenv("TELEGRAM_BOT_NAME", "Anna")

# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------
AI_KEY = os.getenv("AI_KEY") or os.getenv("OPENAI_API_KEY")
AI_MODEL = os.getenv("AI_MODEL", "gpt-4.1-mini")
AI_BASE_URL = os.getenv("AI_BASE_URL") or None

# ---------------------------------------------------------------------------
# Anna character
# ---------------------------------------------------------------------------
CHARACTER_ID = os.getenv("CHARACTER_ID", "anna_01")
CHARACTER_DIR = os.getenv("CHARACTER_DIR", str(BASE_DIR / "data" / "characters"))
CHARACTER_FILE = os.getenv("CHARACTER_FILE", str(Path(CHARACTER_DIR) / f"{CHARACTER_ID}.json"))

# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------
IMAGE_API_KEY = os.getenv("IMAGE_API_KEY") or AI_KEY
IMAGE_BASE_URL = os.getenv("IMAGE_BASE_URL") or AI_BASE_URL
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-1")
IMAGE_REFERENCE_MODE = os.getenv("IMAGE_REFERENCE_MODE", "auto").lower()

PHOTO_COST_STARS = int(os.getenv("PHOTO_COST_STARS", "25"))
PHOTO_DAILY_LIMITS = tuple(int(x.strip()) for x in os.getenv("PHOTO_DAILY_LIMITS", "1,1,2,3,4,5").split(",") if x.strip()) or (1,)

# ---------------------------------------------------------------------------
# Voice / limits / payments
# ---------------------------------------------------------------------------
TTS_API_KEY = os.getenv("TTS_API_KEY") or AI_KEY
TTS_MODEL = os.getenv("TTS_MODEL", "gpt-4o-mini-tts")
TTS_VOICE = os.getenv("TTS_VOICE", "nova")
VOICE_COST_STARS = int(os.getenv("VOICE_COST_STARS", "10"))
FREE_MESSAGES_PER_DAY = int(os.getenv("FREE_MESSAGES_PER_DAY", "100"))
PREMIUM_MONTHLY_STARS = int(os.getenv("PREMIUM_MONTHLY_STARS", "500"))

# ---------------------------------------------------------------------------
# Scheduler / behavior
# ---------------------------------------------------------------------------
KEEP_ALIVE = os.getenv("KEEP_ALIVE", "").lower() == "true"
PROACTIVE_MIN_HOURS = int(os.getenv("PROACTIVE_MIN_HOURS", "12"))
DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "UTC")
ADMIN_TELEGRAM_IDS = {
    int(x.strip()) for x in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",") if x.strip().isdigit()
}
