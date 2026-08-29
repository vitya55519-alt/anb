"""V3.22.0 — RU/EN interface layer.

The bot chat itself always answers in the user's own language (the LLM
context receives ``language_code``). This module translates the UI chrome —
the reply keyboard and top-level menus — so an English speaker can navigate
the bot without knowing Russian.

Rules:
- the interface language is stored on ``User.ui_lang`` ('' = Russian, the
  legacy default). It is detected from the Telegram account language on
  first contact and never forced again afterwards;
- every reply-keyboard label exists as a ``(ru, en)`` pair and the text
  handlers match BOTH variants via ``F.text.in_(kb_pair(key))``;
- unknown/missing ``language_code`` stays Russian — the core audience is
  Russian-speaking.
"""
from __future__ import annotations

from sqlalchemy import select

from models.app_models import User
from services.db import SessionLocal

RU = 'ru'
EN = 'en'

# Main reply keyboard labels: key -> (ru, en). Row layout lives in MAIN_KB_ROWS.
KB_LABELS = {
    'chat': ('💬 Общение', '💬 Chat'),
    'photo': ('📸 Фото', '📸 Photos'),
    'video': ('🎬 Видео', '🎬 Video'),
    'circle': ('🎥 Кружочек', '🎥 Video circle'),
    'quest': ('🎯 Задание дня', '🎯 Daily quest'),
    'date': ('💕 Свидание', '💕 Date'),
    'apartment': ('🏠 Квартира', '🏠 Apartment'),
    'gift': ('🎁 Подарить', '🎁 Gift'),
    'stories': ('🎯 Истории', '🎯 Stories'),
    'collection': ('🖼 Коллекция', '🖼 Collection'),
    'features': ('✨ Возможности', '✨ Features'),
    'premium': ('🚀 Премиум', '🚀 Premium'),
    'alarm': ('⏰ Будильник', '⏰ Alarm'),
    'profile': ('👤 Профиль', '👤 Profile'),
    'settings': ('⚙️ Настройки', '⚙️ Settings'),
    'characters': ('👩 Персонажи', '👩 Characters'),
    'invite': ('🔗 Пригласить', '🔗 Invite'),
    'custom': ('🎨 Мой персонаж', '🎨 My character'),
    'admin': ('🛠 Админка', '🛠 Admin'),
}

# V3.21.0 discovery layout: every feature has a visible first-row button.
MAIN_KB_ROWS = [
    ['chat', 'photo'],
    ['video', 'circle'],
    ['quest', 'date'],
    ['apartment', 'gift'],
    ['stories', 'collection'],
    ['features', 'premium'],
    ['alarm', 'profile'],
    ['settings', 'characters'],
    ['invite', 'custom'],
]

# English names for the 8-level relationship ladder (RU lives in main.py).
LEVEL_NAMES_EN = {
    1: 'Getting to know each other',
    2: 'Attraction',
    3: 'Flirting',
    4: 'Falling in love',
    5: 'Lovers',
    6: 'Our story',
    7: 'Kindred spirits',
    8: 'One whole',
}


def kb_pair(key: str) -> tuple[str, str]:
    """Both label variants — for ``F.text.in_`` handler matching."""
    return KB_LABELS[key]


def kb_label(key: str, lang: str) -> str:
    ru, en = KB_LABELS[key]
    return en if lang == EN else ru


def detect_lang(language_code: str | None) -> str:
    """Telegram account language -> interface language."""
    code = (language_code or '').strip().lower()
    return EN if code and not code.startswith('ru') else RU


def user_lang(telegram_id: int) -> str:
    """Interface language for a user. Unknown users default to Russian."""
    try:
        with SessionLocal() as session:
            user = session.scalar(select(User).where(User.telegram_id == str(telegram_id)))
            lang = (user.ui_lang or '').strip().lower() if user else ''
        return EN if lang == EN else RU
    except Exception:
        return RU
