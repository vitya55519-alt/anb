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
    # V3.37.0: the money affiliate program — the «пригласить» button grew up
    # into a full partner screen (stats, payouts, FAQ). Kept as its own key so
    # old keyboards still resolve; MAIN_KB_ROWS shows partner instead of invite.
    'partner': ('💰 Партнёрка', '💰 Partner program'),
    'custom': ('🎨 Мой персонаж', '🎨 My character'),
    # V3.38.0: the main menu funnels users into the Mini App (Come Closer
    # layout): one big «open app» row on top, the two app actions (buy
    # photo credits / create a picture) in the middle, partner + support at
    # the bottom. «Поддержка» is now a real ticket flow to the owner (the
    # old «💖 Поддержать проект» donation appeal stays on the legal screen).
    'app': ('📱 Открыть приложение', '📱 Open the app'),
    'credits': ('🍑 Добавить персиков', '🍑 Add peaches'),
    'paint': ('🖼 Создать картинку', '🖼 Create a picture'),
    'support': ('👥 Поддержка', '👥 Support'),
    # V3.32.0: Platega/bank compliance — legal documents must be reachable
    # at all times from the main keyboard, not only via commands.
    'legal': ('📜 Документы', '📜 Documents'),
    'admin': ('🛠 Админка', '🛠 Admin'),
}

# V3.38.0: the Come Closer funnel layout — the Mini App is the product, the
# chat keyboard is its launcher. Old keys stay in KB_LABELS so cached reply
# keyboards from earlier versions keep resolving to their handlers.
# V3.40.0: owner benchmarked the Come Closer main menu (screenshot) — the two
# app actions each get their OWN full-width row instead of sharing one.
# V3.41.0: owner asked to keep terms/privacy reachable from the main menu, so
# the «📜 Документы» (Условия + Privacy) row is pinned at the bottom. Character
# selection is gone from the chat funnel — it lives in the Mini App now.
MAIN_KB_ROWS = [
    ['app'],
    ['credits'],
    ['paint'],
    ['partner', 'support'],
    ['legal'],
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
