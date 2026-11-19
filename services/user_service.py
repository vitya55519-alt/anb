from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from services.db import SessionLocal
from models.app_models import User, CharacterState
from config import CHARACTER_ID, DEFAULT_TIMEZONE, LANG_TZ_DEFAULTS
from services.ui_lang import detect_lang

def now(): return datetime.now(timezone.utc).replace(tzinfo=None)

def _timezone_from_language(language_code: str | None) -> str:
    if not language_code:
        return DEFAULT_TIMEZONE
    lang = language_code.lower().split('-')[0].split('_')[0]
    return LANG_TZ_DEFAULTS.get(lang, DEFAULT_TIMEZONE)

def _ensure_character_state(session, user_id: int, character_id: str):
    query = select(CharacterState).where(
        CharacterState.user_id == user_id, CharacterState.character_id == character_id)
    state = session.scalar(query)
    if state is None:
        try:
            # A concurrent request may create this pair after our SELECT.
            with session.begin_nested():
                state = CharacterState(user_id=user_id, character_id=character_id)
                session.add(state)
                session.flush()
        except IntegrityError:
            state = session.scalar(query)
            if state is None:
                raise
    return state


def ensure_user(telegram_id: int, name: str | None = None, language_code: str | None = None,
                username: str | None = None) -> int:
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            tz = _timezone_from_language(language_code)
            try:
                with s.begin_nested():
                    user = User(telegram_id=str(telegram_id), name=name or "", timezone=tz, ui_lang=detect_lang(language_code))
                    s.add(user)
                    s.flush()
            except IntegrityError:
                user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
                if user is None:
                    raise
        elif name:
            user.name = name
        # V3.31.0: keep the last seen @username so the owner can grant
        # premium/tokens manually by username (off-bot payment flow).
        if username and user.username != username:
            user.username = username
        # If the user still has the default UTC, try to auto-detect from language on any contact.
        if user.timezone == DEFAULT_TIMEZONE and language_code:
            detected = _timezone_from_language(language_code)
            if detected != DEFAULT_TIMEZONE:
                user.timezone = detected
        # V3.22.0: detect the interface language once for legacy users.
        if language_code and not (user.ui_lang or '').strip():
            user.ui_lang = detect_lang(language_code)
        _ensure_character_state(s, user.id, CHARACTER_ID)
        s.commit(); return user.id

def get_user(telegram_id: int):
    with SessionLocal() as s:
        return s.scalar(select(User).where(User.telegram_id == str(telegram_id)))


def find_user_by_username(username: str) -> int | None:
    """V3.31.0: resolve a Telegram @username to a telegram_id from our own
    users table (the Bot API cannot look users up by username)."""
    clean = (username or '').strip().lstrip('@').lower()
    if not clean:
        return None
    with SessionLocal() as s:
        from sqlalchemy import func
        row = s.scalar(select(User).where(func.lower(User.username) == clean))
        return int(row.telegram_id) if row else None

def touch_user(telegram_id: int):
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if user:
            user.last_active_at = now(); s.commit()

def get_state(telegram_id: int, character_id: str | None = None):
    uid = ensure_user(telegram_id)
    with SessionLocal() as s:
        state = _ensure_character_state(s, uid, character_id or CHARACTER_ID)
        s.commit()
        return state

def update_user_settings(telegram_id: int, **kwargs):
    uid = ensure_user(telegram_id)
    with SessionLocal() as s:
        user = s.get(User, uid)
        for k,v in kwargs.items():
            if hasattr(user,k): setattr(user,k,v)
        s.commit()

def update_state(telegram_id: int, character_id: str | None = None, **kwargs):
    uid = ensure_user(telegram_id)
    with SessionLocal() as s:
        state = _ensure_character_state(s, uid, character_id or CHARACTER_ID)
        for k,v in kwargs.items():
            if hasattr(state,k): setattr(state,k,v)
        s.commit()


def set_adult_confirmed(telegram_id: int, confirmed: bool = True):
    update_user_settings(telegram_id, adult_confirmed=bool(confirmed))

def is_adult_confirmed(telegram_id: int) -> bool:
    u = get_user(telegram_id)
    return bool(u and getattr(u, 'adult_confirmed', False))
