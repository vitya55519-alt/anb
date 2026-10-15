"""V3.62.0: the level-3 fork — «романтика или страсть».

When a pair reaches level 3 and no path is chosen yet, she asks him in the
app chat what they are to each other; the message carries two answers the
SPA draws as buttons (media_kind='fork'). His tap picks the path for this
girl only, and she answers in the voice of the chosen path.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from services.db import SessionLocal

logger = logging.getLogger(__name__)

FORK_KIND = 'fork'
FORK_TEXT = ('можно честно? я не понимаю, что между нами… '
             'ты мне пишешь, я жду твоих сообщений, и мне уже мало просто болтать. что я для тебя? 🙈')
FORK_TEXT_TAKEN = ('можно честно? у меня есть он… а я весь день думаю о тебе. '
                   'я запуталась. что я для тебя? 🙈')
FORK_OPTIONS = {
    'romance': '❤️ Ты мне правда нравишься. Хочу узнать тебя по-настоящему',
    'passion': '🔥 Я думаю о тебе совсем не по-дружески 😏',
}
CHOSEN_REPLY = {
    'romance': 'правда? 🥺 у меня сердце сейчас выпрыгнет… тогда давай не торопиться. я хочу, чтобы у нас было по-настоящему ❤️',
    'passion': 'ммм… я надеялась, что ты это скажешь 😏 тогда держись, я больше не буду притворяться приличной 🔥',
}
CHOSEN_REPLY_TAKEN = {
    'romance': 'тогда это наша тайна… я не знаю, к чему это приведёт, но я хочу быть с тобой ❤️🤫',
    'passion': 'тогда это будет наш секрет… он ничего не узнает 🤫🔥',
}


def _pair_state(uid: int, character_id: str):
    from services.relationship_engine import STAGE_ORDER, FORK_STAGE, branch_of, get_state
    with SessionLocal() as session:
        row = get_state(session, uid, character_id)
        if row is None:
            return None, False
        stage = row.stage or 'stranger'
        reached = stage in STAGE_ORDER and STAGE_ORDER.index(stage) >= STAGE_ORDER.index(FORK_STAGE)
        return branch_of(row), reached


def _fork_offered(uid: int, character_id: str) -> bool:
    from models.app_models import Message
    with SessionLocal() as session:
        return session.scalar(select(Message.id).where(
            Message.user_id == uid, Message.character_id == character_id,
            Message.media_kind == FORK_KIND).limit(1)) is not None


def maybe_offer_fork(uid: int, character_id: str, *, taken: bool = False, stage_override: str | None = None) -> bool:
    """Save her fork question into the chat once. Returns True while the
    choice is pending (offered now or earlier, not answered yet)."""
    try:
        from services.relationship_engine import STAGE_ORDER, FORK_STAGE
        branch, reached = _pair_state(uid, character_id)
        if stage_override in STAGE_ORDER:
            reached = STAGE_ORDER.index(stage_override) >= STAGE_ORDER.index(FORK_STAGE)
        if branch or not reached:
            return False
        if _fork_offered(uid, character_id):
            return True
        from services.memory_service import save_message
        save_message(uid, character_id, 'assistant', FORK_TEXT_TAKEN if taken else FORK_TEXT, media_kind=FORK_KIND)
        return True
    except Exception:
        logger.exception('fork offer failed user=%s character=%s', uid, character_id)
        return False


def choose(uid: int, character_id: str, branch: str, *, taken: bool = False) -> str | None:
    """Store his answer and save her reply. None when it was already chosen
    (or the pair has no relationship yet)."""
    from services.relationship_engine import set_branch
    from services.memory_service import save_message
    if not set_branch(uid, character_id, branch):
        return None
    reply = (CHOSEN_REPLY_TAKEN if taken else CHOSEN_REPLY)[branch]
    try:
        save_message(uid, character_id, 'user', FORK_OPTIONS[branch])
        save_message(uid, character_id, 'assistant', reply)
    except Exception:
        logger.exception('fork answer save failed user=%s character=%s', uid, character_id)
    return reply


def mark_left_him(uid: int, character_id: str) -> None:
    """Romance path, level 10, she was married: she left him — from now on
    she is free in the chat voice and in photos."""
    from services.relationship_engine import get_state
    try:
        with SessionLocal() as session:
            row = get_state(session, uid, character_id)
            if row is not None:
                row.marital_status = 'mar_divorced'
                session.commit()
    except Exception:
        logger.exception('left-him status failed user=%s character=%s', uid, character_id)
