"""V3.141.0: owner ТЗ (Фаза 2, Задача 1) — the scripted onboarding selfie.

On the 5th (fallback: 7th) message of a brand-new non-Premium user's first
dialog the script takes over from the LLM: a prepared line plus ONE quality
unblurred selfie. The picture is pre-saved (her card file_id, the storefront
media or the canonical face), so no generation credits are spent — not per
user, not at all. Once per user, ever; the flag lives in dialog_sessions so a
redeploy keeps it. The delivery layers (bot send_answer, app chat turn)
consume the one-shot pending mark right after the text goes out.
"""
from __future__ import annotations

import logging
import time

from services.dialog_store import DialogStore
from services.memory_service import save_message
from services.ui_lang import flow_text, full_user_lang

logger = logging.getLogger(__name__)

TRIGGER_COUNTS = (5, 7)
_PENDING_TTL = 180.0
_IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.webp')

_done = DialogStore('onboarding_demo_done')
_pending: dict[tuple[int, str], float] = {}


def maybe_intercept(telegram_id: int, db_user_id: int, character_id: str, user_text: str,
                    history, premium: bool, language_code: str | None = None) -> str | None:
    """The scripted line instead of an LLM answer, or None to let the model
    speak. Saves both messages and marks the one-shot photo delivery."""
    try:
        if premium or _done.get(telegram_id):
            return None
        n_user = sum(1 for m in history if m.role == 'user') + 1
        if n_user not in TRIGGER_COUNTS:
            return None
        from services.chat_guest_service import get_guest
        if get_guest(telegram_id, character_id):
            return None
        text = flow_text(full_user_lang(telegram_id, language_code), 'onboarding_demo')
        save_message(db_user_id, character_id, 'user', user_text)
        save_message(db_user_id, character_id, 'assistant', text)
        _done[telegram_id] = True
        _pending[(int(telegram_id), character_id)] = time.monotonic()
        try:
            from services.analytics_service import track_event
            track_event(db_user_id, 'onboarding_demo', character_id=character_id)
        except Exception:
            pass
        return text
    except Exception:
        logger.warning('onboarding demo intercept failed user=%s', telegram_id, exc_info=True)
        return None


def take_pending(telegram_id: int, character_id: str) -> bool:
    """One-shot: True exactly once, right after the scripted reply."""
    stamp = _pending.pop((int(telegram_id), character_id), None)
    return stamp is not None and (time.monotonic() - stamp) <= _PENDING_TTL


def photo_url_for(character_id: str) -> str:
    """The app-facing URL of the pre-saved selfie — never a generation."""
    try:
        from services.webapp_service import character_card_override
        override = character_card_override(character_id)
        if override and override.suffix.lower() in _IMAGE_EXTS:
            return f'/webapp/card/{character_id}'
    except Exception:
        pass
    return f'/webapp/photo/{character_id}?i=0'


async def send_bot_photo(bot, chat_id: int, telegram_id: int, character_id: str) -> None:
    """The bot-facing delivery: her saved card file_id first (zero upload),
    then the storefront picture, then the canonical face. Never generates."""
    from aiogram.types import BufferedInputFile
    caption = flow_text(full_user_lang(telegram_id), 'selfie_caption')
    try:
        from services.character_card_service import get_card
        card = get_card(character_id)
        if card and card.card_photo_file_id:
            await bot.send_photo(chat_id, card.card_photo_file_id, caption=caption)
            return
    except Exception:
        logger.warning('demo card file_id send failed user=%s', telegram_id)
    body = None
    try:
        from services.webapp_service import character_card_override
        override = character_card_override(character_id)
        if override and override.suffix.lower() in _IMAGE_EXTS:
            body = override.read_bytes()
    except Exception:
        pass
    if not body:
        try:
            from services.webapp_service import character_photo
            shot = character_photo(character_id, 0)
            if shot:
                body = shot[0]
        except Exception:
            pass
    if body:
        await bot.send_photo(chat_id, BufferedInputFile(body, filename='demo.jpg'), caption=caption)