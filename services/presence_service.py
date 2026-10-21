"""V3.61.8: she notices he is back.

When the user opens her chat in the Mini App after a long silence, the newest
line in the dialog is hers — «ты где пропадал?» — instead of the last thing he
said himself hours ago. Static lines, no LLM: opening a chat must stay instant.
"""
from __future__ import annotations

import logging
import os
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from models.app_models import Message
from services.db import SessionLocal

logger = logging.getLogger(__name__)

WELCOME_BACK_HOURS = max(1.0, float(os.getenv('WELCOME_BACK_HOURS', '3') or 3))

# She already wrote first and he did not answer — now he is here.
BACK_AFTER_HER = (
    'наконец-то ты тут 🥺 я уже заждалась',
    'о, ты пришёл 😊 а я как раз о тебе думала',
    'ну наконец-то! я тебе писала, а ты молчишь 😤 рассказывай, как ты?',
    'ты вернулся 💛 я скучала, правда',
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def welcome_back_line(last_role: str, character_id: str) -> str:
    if last_role == 'assistant':
        return random.choice(BACK_AFTER_HER)
    from services import retention_features_service
    return retention_features_service.tidy_fixed_text(retention_features_service.get_character_miss(character_id))


def maybe_welcome_back(user_id: int, character_id: str, now: datetime | None = None) -> str | None:
    """Add her «ты где?» line when the dialog went quiet for WELCOME_BACK_HOURS.
    Returns the line it wrote, or None. Fail-silent."""
    now = now or _now()
    try:
        with SessionLocal() as s:
            last = s.scalar(select(Message).where(
                Message.user_id == user_id, Message.character_id == character_id,
            ).order_by(Message.created_at.desc()).limit(1))
            if last is None or last.created_at is None:
                return None  # a brand-new chat opens with her greeting, not this
            if now - last.created_at < timedelta(hours=WELCOME_BACK_HOURS):
                return None
            line = welcome_back_line(last.role, character_id)
            s.add(Message(user_id=user_id, character_id=character_id, role='assistant', content=line))
            s.commit()
        try:
            from services.analytics_service import track_event
            track_event(user_id, 'welcome_back_shown', metadata={'character_id': character_id})
        except Exception:
            pass
        return line
    except Exception:
        logger.exception('welcome back failed user=%s character=%s', user_id, character_id)
        return None
