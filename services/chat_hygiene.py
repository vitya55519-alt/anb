"""V3.63.2: clean chat, Come Closer style.

The owner benchmarked Come Closer: its bot chat stays short — one pinned main
menu, and every menu screen replaces the previous one instead of piling up.
Ours grew into a wall: every tap on a reply-keyboard button left the user's
«🍑 Персики» message plus the bot's answer, every /start a new banner, every
small-talk message in the bot another «chat lives in the app» hint.

Mechanics:
- A *screen* is whatever a menu handler sends in answer to one tap. Handlers
  wrapped with :func:`service_screen` (main.py) delete the user's tap message
  and the previous screen, then every message the bot sends while the handler
  runs is captured (via a request middleware on the bot session) as the new
  screen, to be swept on the next tap.

V3.147.0: the pinned main menu is gone. Pinning cost a «...закрепил(а) главное
меню» service line on the very first screen, which is exactly the noise this
module exists to remove — the app, the balance and the partner program are
reachable through Telegram's own menu button and the reply keyboard.

Conversation messages (her texts, photos, invoices) are never captured: only
code running inside a ``service_screen`` handler is. Message ids live in
memory — after a redeploy the previous screen simply stays, nothing breaks.
Telegram lets a bot delete messages younger than 48h; older ones stay too.
"""
from __future__ import annotations

import contextvars
import logging
from dataclasses import dataclass, field

from aiogram.client.session.middlewares.base import BaseRequestMiddleware

logger = logging.getLogger(__name__)

# Methods whose result is a Message that belongs to the current screen.
_SCREEN_METHODS = {
    'SendMessage', 'SendPhoto', 'SendAnimation', 'SendVideo', 'SendDocument',
    'SendMediaGroup', 'SendSticker',
}
_MAX_TRACKED = 12


@dataclass
class _Capture:
    chat_id: int
    ids: list[int] = field(default_factory=list)
    closed: bool = False


_current: contextvars.ContextVar[_Capture | None] = contextvars.ContextVar('chat_hygiene_capture', default=None)
_screens: dict[int, list[int]] = {}


class ScreenCaptureMiddleware(BaseRequestMiddleware):
    """Records ids of messages sent while a screen capture is open."""

    async def __call__(self, make_request, bot, method):
        result = await make_request(bot, method)
        cap = _current.get()
        if cap is None or cap.closed:
            return result
        try:
            if type(method).__name__ not in _SCREEN_METHODS:
                return result
            if int(getattr(method, 'chat_id', 0) or 0) != cap.chat_id:
                return result
            sent = result if isinstance(result, list) else [result]
            for msg in sent:
                mid = getattr(msg, 'message_id', None)
                if mid:
                    cap.ids.append(int(mid))
        except Exception:
            logger.exception('screen capture failed')
        return result


def install(bot) -> None:
    """Attach the capture middleware to the bot's API session (idempotent)."""
    if getattr(bot, '_chat_hygiene_installed', False):
        return
    bot.session.middleware(ScreenCaptureMiddleware())
    bot._chat_hygiene_installed = True


async def _delete(bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        # Too old (>48h), already gone or not ours — leaving it is fine.
        pass


async def open_screen(bot, chat_id: int, user_message_id: int | None = None) -> contextvars.Token:
    """Sweep the user's tap and the previous screen; start capturing the new one."""
    if user_message_id:
        await _delete(bot, chat_id, int(user_message_id))
    for mid in _screens.pop(chat_id, []):
        await _delete(bot, chat_id, mid)
    return _current.set(_Capture(chat_id=chat_id))


def close_screen(token: contextvars.Token) -> None:
    """Store what was captured as the chat's current screen and stop capturing.

    ``closed`` matters: background tasks spawned inside the handler inherit a
    copy of the context that still points at this capture — once closed, the
    photos they send later are not mistaken for menu screens."""
    cap = _current.get()
    try:
        _current.reset(token)
    except ValueError:
        pass
    if cap is None:
        return
    cap.closed = True
    if cap.ids:
        _screens[cap.chat_id] = cap.ids[-_MAX_TRACKED:]
