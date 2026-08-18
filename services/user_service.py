from datetime import datetime, timezone
from sqlalchemy import select
from services.db import SessionLocal
from models.app_models import User, CharacterState
from config import CHARACTER_ID, DEFAULT_TIMEZONE, LANG_TZ_DEFAULTS

def now(): return datetime.now(timezone.utc).replace(tzinfo=None)

def _timezone_from_language(language_code: str | None) -> str:
    if not language_code:
        return DEFAULT_TIMEZONE
    lang = language_code.lower().split('-')[0].split('_')[0]
    return LANG_TZ_DEFAULTS.get(lang, DEFAULT_TIMEZONE)

def ensure_user(telegram_id: int, name: str | None = None, language_code: str | None = None) -> int:
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            tz = _timezone_from_language(language_code)
            user = User(telegram_id=str(telegram_id), name=name or "", timezone=tz)
            s.add(user); s.flush()
        elif name:
            user.name = name
        # If the user still has the default UTC, try to auto-detect from language on any contact.
        if user.timezone == DEFAULT_TIMEZONE and language_code:
            detected = _timezone_from_language(language_code)
            if detected != DEFAULT_TIMEZONE:
                user.timezone = detected
        state = s.scalar(select(CharacterState).where(CharacterState.user_id == user.id, CharacterState.character_id == CHARACTER_ID))
        if not state:
            s.add(CharacterState(user_id=user.id, character_id=CHARACTER_ID))
        s.commit(); return user.id

def get_user(telegram_id: int):
    with SessionLocal() as s:
        return s.scalar(select(User).where(User.telegram_id == str(telegram_id)))

def touch_user(telegram_id: int):
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if user:
            user.last_active_at = now(); s.commit()

def get_state(telegram_id: int):
    uid = ensure_user(telegram_id)
    with SessionLocal() as s:
        return s.scalar(select(CharacterState).where(CharacterState.user_id == uid, CharacterState.character_id == CHARACTER_ID))

def update_user_settings(telegram_id: int, **kwargs):
    uid = ensure_user(telegram_id)
    with SessionLocal() as s:
        user = s.get(User, uid)
        for k,v in kwargs.items():
            if hasattr(user,k): setattr(user,k,v)
        s.commit()

def update_state(telegram_id: int, **kwargs):
    uid = ensure_user(telegram_id)
    with SessionLocal() as s:
        state = s.scalar(select(CharacterState).where(CharacterState.user_id == uid, CharacterState.character_id == CHARACTER_ID))
        for k,v in kwargs.items():
            if hasattr(state,k): setattr(state,k,v)
        s.commit()


def set_adult_confirmed(telegram_id: int, confirmed: bool = True):
    update_user_settings(telegram_id, adult_confirmed=bool(confirmed))

def is_adult_confirmed(telegram_id: int) -> bool:
    u = get_user(telegram_id)
    return bool(u and getattr(u, 'adult_confirmed', False))
