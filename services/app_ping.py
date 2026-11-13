"""V3.128.0: she wrote in the Mini App — a short ping in the bot chat.

Pushes from the scheduler (rituals, «скучаю», life events, gifts) already go
to Telegram AND into the shared dialog. What never reached Telegram is what
lands in the app chat AFTER he left it: her reply he did not wait for, a photo
that finished rendering a minute later, a wardrobe try-on, a room picture.
He closed the app, the bot chat stayed silent, the message waited unseen.

Now such a message leaves a short note in the bot chat — her name, a preview
and «💬 Ответить» that opens exactly her dialog in the app. Rules, so it never
becomes spam:

- only when he is NOT in the app — and that is decided AFTER the wait, not the
  moment her message lands: the SPA sends a heartbeat every ~20 s while it is on
  screen and an «away» beacon when it is hidden or closed, and a webview that is
  simply killed never gets the beacon out;
- he must still be away after a short wait (APP_PING_DELAY_SECONDS); opening
  her chat in between — in the app or by the «read» stamp in the DB — cancels it;
- V3.164.0: being in the app at that moment no longer throws the ping away, it
  only postpones it. A backgrounded Telegram webview keeps beating for minutes,
  so the old rule silently killed most pings («она ответила, я вышел — а в боте
  тихо»). The messages wait in memory; the «away» beacon delivers them, and the
  only thing that cancels one is proof he actually saw it — the SPA's «seen» ack
  for that dialog or a newer read stamp;
- several messages in a row collapse into ONE ping («и ещё 2»);
- at most one ping per APP_PING_COOLDOWN_MINUTES and APP_PING_MAX_PER_DAY a
  day; the app's «новые сообщения» notification switch and the bot's
  proactive switch (also off for users who blocked the bot) are respected;
- at night (her quiet hours in his timezone) the ping arrives silently.

State is in memory: a redeploy forgets a pending ping, which is the safe way
to fail (no ping rather than a stale one).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(os.getenv(name, str(default)) or default)))
    except ValueError:
        return default


APP_PING_ENABLED = (os.getenv('APP_PING_ENABLED', 'true') or 'true').strip().lower() not in ('0', 'false', 'no', 'off')
# How long after her message we look again before pinging (he may come back).
APP_PING_DELAY_SECONDS = _env_int('APP_PING_DELAY_SECONDS', 60, 5, 1800)
# A heartbeat newer than this means «he is in the app right now».
APP_PRESENCE_SECONDS = _env_int('APP_PRESENCE_SECONDS', 45, 15, 600)
APP_PING_COOLDOWN_MINUTES = _env_int('APP_PING_COOLDOWN_MINUTES', 30, 1, 24 * 60)
APP_PING_MAX_PER_DAY = _env_int('APP_PING_MAX_PER_DAY', 6, 1, 50)
# V3.164.0: how long postponed messages may still wait for him to leave the app.
# Older than this, they are dropped — a «she wrote» note about a half-hour-old
# line reads as a bug, not as a reminder.
APP_PING_PENDING_TTL_SECONDS = _env_int('APP_PING_PENDING_TTL_SECONDS', 1800, 60, 7200)
PREVIEW_CHARS = 110

# telegram_id -> (monotonic time of the last heartbeat, away flag)
_presence: dict[int, tuple[float, bool]] = {}
# telegram_id -> pending ping {char, text, media, count, noted, at}
_pending: dict[int, dict] = {}
# telegram_id -> (character_id, monotonic time) of the last «I am looking at her
# dialog» ack from the SPA (V3.164.0) — the only proof he really read it.
_seen: dict[int, tuple[str, float]] = {}
# telegram_id -> monotonic time of the last ping sent
_last_ping: dict[int, float] = {}
# telegram_id -> (utc date iso, pings sent that day)
_day_count: dict[int, tuple[str, int]] = {}
# users with a live _later task, so a collapsed message never waits unattended
_armed: set[int] = set()
# users whose ping is being sent right now — a flush and the wait must not race
_sending: set[int] = set()
_tasks: set[asyncio.Task] = set()


# ── presence ────────────────────────────────────────────────────────────
def touch(telegram_id: int, away: bool = False, now: float | None = None) -> None:
    """The SPA is on screen (heartbeat) or just went away (beacon)."""
    try:
        _presence[int(telegram_id)] = (time.monotonic() if now is None else now, bool(away))
    except Exception:
        pass


def in_app(telegram_id: int, now: float | None = None) -> bool:
    entry = _presence.get(int(telegram_id))
    if not entry:
        return False
    at, away = entry
    now = time.monotonic() if now is None else now
    return (not away) and (now - at) < APP_PRESENCE_SECONDS


def seen(telegram_id: int, character_id: str) -> None:
    """V3.164.0: the SPA drew her reply while he was looking at that dialog.
    This — not the heartbeat — is what cancels a ping: a webview he minimized
    keeps beating, and then the note he never read is thrown away."""
    try:
        _seen[int(telegram_id)] = (str(character_id), time.monotonic())
    except Exception:
        pass


def _saw_it(telegram_id: int, character_id: str, since: float) -> bool:
    at = _seen.get(int(telegram_id))
    return bool(at and at[0] == str(character_id) and at[1] >= since)


# ── text ────────────────────────────────────────────────────────────────
_ACTION = re.compile(r'\*[^*\n]{0,200}\*')


def preview(text: str, limit: int = PREVIEW_CHARS) -> str:
    """Her words without the *stage directions*, one line, cut on a word."""
    raw = (text or '').strip()
    clean = _ACTION.sub(' ', raw)
    clean = re.sub(r'\s+', ' ', clean).strip(' .,—-')
    if not clean:
        clean = re.sub(r'\s+', ' ', raw.replace('*', '')).strip()
    if len(clean) <= limit:
        return clean
    cut = clean[:limit].rsplit(' ', 1)[0].rstrip(' ,.;:—-')
    return (cut or clean[:limit]) + '…'


def ping_text(name: str, text: str, media: str | None, more: int, lang: str = 'ru') -> str:
    en = lang == 'en'
    who = name or ('She' if en else 'Она')
    line = preview(text)
    if media in ('photo', 'video', 'circle'):
        what = {
            'photo': ('прислала тебе фото', 'sent you a photo'),
            'video': ('прислала тебе видео', 'sent you a video'),
            'circle': ('записала тебе кружочек', 'recorded a video note for you'),
        }[media][1 if en else 0]
        head = f'📸 {who} {what}' + (' in the app' if en else ' в приложении')
        # a bare «📸» caption adds nothing under the headline
        if line and len(preview(line.replace('📸', ''), 200)) > 2:
            head += f'\n«{line}»'
    else:
        head = (f'💬 {who} wrote to you in the app:' if en else f'💬 {who} написала тебе в приложении:')
        head += f'\n«{line}»' if line else ''
    if more > 0:
        head += f'\n(+{more} more)' if en else f'\n(и ещё {more})'
    return head


# ── limits ──────────────────────────────────────────────────────────────
def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def limits_ok(telegram_id: int, now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    last = _last_ping.get(int(telegram_id))
    if last is not None and now - last < APP_PING_COOLDOWN_MINUTES * 60:
        return False
    return not _capped_today(telegram_id)


def _cooldown_left(telegram_id: int, now: float | None = None) -> float:
    """Seconds until the next ping of his is allowed; 0 when it is allowed now."""
    last = _last_ping.get(int(telegram_id))
    if last is None:
        return 0.0
    now = time.monotonic() if now is None else now
    return max(0.0, APP_PING_COOLDOWN_MINUTES * 60 - (now - last))


def _capped_today(telegram_id: int) -> bool:
    day, n = _day_count.get(int(telegram_id), ('', 0))
    return day == _today() and n >= APP_PING_MAX_PER_DAY


def _count_ping(telegram_id: int, now: float | None = None) -> None:
    tg = int(telegram_id)
    _last_ping[tg] = time.monotonic() if now is None else now
    day, n = _day_count.get(tg, ('', 0))
    _day_count[tg] = (_today(), (n + 1) if day == _today() else 1)


def _read_since(telegram_id: int, character_id: str, noted_iso: str) -> bool:
    """He opened her chat in the app after the message landed."""
    try:
        from services import webapp_service
        stamp = webapp_service._chat_reads_map(telegram_id).get(str(character_id))
        return bool(stamp and stamp > noted_iso)
    except Exception:
        return False


def _user_ctx(telegram_id: int) -> dict | None:
    """Everything the ping needs from the DB, or None when it must not go."""
    from sqlalchemy import select
    from models.app_models import User
    from services.db import SessionLocal
    with SessionLocal() as s:
        u = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not u or not getattr(u, 'proactive_enabled', True):
            return None
        ctx = {'uid': u.id, 'lang': 'en' if (u.ui_lang or '').strip().lower() == 'en' else 'ru',
               'tz': u.timezone or 'UTC'}
    try:
        from services import webapp_service
        prefs = webapp_service.get_notification_prefs(int(telegram_id))
        if not prefs.get('enabled', True) or not prefs.get('new_messages', True):
            return None
    except Exception:
        pass
    return ctx


def _quiet_now(tz_name: str) -> bool:
    try:
        from services.scheduler_service import _in_quiet_hours, _user_local_hour_simple
        return _in_quiet_hours(_user_local_hour_simple(tz_name))
    except Exception:
        return False


def _character_name(character_id: str) -> str:
    try:
        from services.chat_guest_service import character_name
        name = character_name(character_id)
        if name:
            return name
    except Exception:
        pass
    try:
        from services.custom_character_service import custom_character_params
        _params, name = custom_character_params(character_id)
        return name or ''
    except Exception:
        return ''


# ── the ping ────────────────────────────────────────────────────────────
def note(bot, telegram_id: int, character_id: str, text: str, media: str | None = None) -> bool:
    """Her message just landed in the app chat and nowhere else. Schedules one
    collapsed ping if he is not in the app. Returns True when one is pending.
    Never raises: a ping is never worth breaking her reply."""
    try:
        if not APP_PING_ENABLED or bot is None or not telegram_id or not character_id:
            return False
        tg = int(telegram_id)
        # V3.164.0: waiting messages are cheap but not free — a user who never
        # comes back would otherwise keep his entry until the next redeploy.
        if len(_pending) > 256:
            cutoff = time.monotonic() - APP_PING_PENDING_TTL_SECONDS
            for stale in [k for k, v in _pending.items() if v.get('at', 0.0) < cutoff]:
                _pending.pop(stale, None)
        # V3.162.0: owner — «она пишет. я выхожу, мне ничего не приходит». The
        # old guard read the presence at the moment her answer landed, and that
        # moment is a second or two after he closed the app: the heartbeat was
        # still fresh, the beacon often never left the webview, and the ping was
        # thrown away before it ever existed (7 pings in 30 days against
        # thousands of app turns). Presence is decided in _deliver, after the
        # wait — there the heartbeat has really stopped.
        pend = _pending.get(tg)
        noted_iso = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        if pend:
            pend['count'] += 1
            # the newest message is the preview; the first one sets «read since»
            pend.update(char=str(character_id), text=text or '', media=media)
            if time.monotonic() - pend.get('at', 0.0) > APP_PING_PENDING_TTL_SECONDS:
                # too old to bundle; this line starts a fresh, short wait
                pend.update(count=1, noted=noted_iso, at=time.monotonic())
            # V3.164.0: messages that are waiting for him to leave must never be
            # left without a waiter — the first one may already have given up.
            if tg not in _armed:
                _arm(bot, tg)
            return True
        _pending[tg] = {'char': str(character_id), 'text': text or '', 'media': media,
                        'count': 1, 'noted': noted_iso, 'at': time.monotonic()}
        _arm(bot, tg)
        return True
    except Exception:
        logger.warning('app ping note failed user=%s', telegram_id, exc_info=True)
        return False


def _arm(bot, tg: int) -> None:
    """One live waiter per user, sleeping APP_PING_DELAY_SECONDS before it looks."""
    _armed.add(tg)
    task = asyncio.get_running_loop().create_task(_later(bot, tg))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def flush(bot, telegram_id: int) -> bool:
    """V3.164.0: the «away» beacon — he left the app, so whatever waited for
    exactly this moment is delivered now instead of never."""
    try:
        tg = int(telegram_id)
        if not APP_PING_ENABLED or bot is None or not _pending.get(tg):
            return False
        task = asyncio.get_running_loop().create_task(_deliver(bot, tg))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        return True
    except Exception:
        logger.warning('app ping flush failed user=%s', telegram_id, exc_info=True)
        return False


async def _later(bot, tg: int) -> None:
    try:
        await asyncio.sleep(APP_PING_DELAY_SECONDS)
        if await _deliver(bot, tg) == 'cooldown':
            # Still in the cooldown after an earlier ping: wait it out once, the
            # messages collapse meanwhile; past the daily cap the ping is dropped.
            wait = _cooldown_left(tg)
            if wait > 0:
                await asyncio.sleep(wait)
                await _deliver(bot, tg)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning('app ping failed user=%s', tg, exc_info=True)
    finally:
        _armed.discard(tg)


async def _deliver(bot, tg: int) -> str:
    """One attempt; returns why the ping did not go, or 'sent'. Only a terminal
    reason clears the waiting messages — «he is in the app» and «still in
    cooldown» leave them for the away beacon."""
    pend = _pending.get(tg)
    if not pend:
        return 'empty'
    if tg in _sending:
        return 'inflight'
    if time.monotonic() - pend.get('at', 0.0) > APP_PING_PENDING_TTL_SECONDS:
        _pending.pop(tg, None)
        logger.info('app ping dropped user=%s reason=stale', tg)
        return 'stale'
    if _capped_today(tg):
        _pending.pop(tg, None)
        logger.info('app ping dropped user=%s reason=day_cap', tg)
        return 'capped'
    if _read_since(tg, pend['char'], pend['noted']) or _saw_it(tg, pend['char'], pend.get('at', 0.0)):
        _pending.pop(tg, None)
        logger.info('app ping cancelled user=%s reason=already_read', tg)
        return 'read'
    if in_app(tg):
        logger.info('app ping waiting user=%s reason=in_app', tg)
        return 'in_app'
    if _cooldown_left(tg) > 0:
        logger.info('app ping waiting user=%s reason=cooldown', tg)
        return 'cooldown'
    _sending.add(tg)
    try:
        ctx = await asyncio.to_thread(_user_ctx, tg)
        if not ctx:
            _pending.pop(tg, None)
            logger.info('app ping dropped user=%s reason=switches_off', tg)
            return 'off'
        name = await asyncio.to_thread(_character_name, pend['char'])
        body = ping_text(name, pend['text'], pend['media'], pend['count'] - 1, ctx['lang'])
        quiet = await asyncio.to_thread(_quiet_now, ctx['tz'])
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
        from config import PUBLIC_BASE_URL
        markup = None
        if PUBLIC_BASE_URL:
            from urllib.parse import quote
            label = '💬 Reply to her' if ctx['lang'] == 'en' else '💬 Ответить'
            url = f'{PUBLIC_BASE_URL}/webapp?open=chat&char={quote(pend["char"])}'
            markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url))]])
        _count_ping(tg)
        _pending.pop(tg, None)
        try:
            await bot.send_message(tg, body, reply_markup=markup, disable_notification=quiet)
        except Exception as exc:
            from aiogram.exceptions import TelegramForbiddenError
            if isinstance(exc, TelegramForbiddenError):
                try:
                    from services.scheduler_service import _mark_blocked
                    await asyncio.to_thread(_mark_blocked, ctx['uid'])
                except Exception:
                    pass
            logger.info('app ping send failed user=%s: %s', tg, exc)
            return 'send_failed'
        try:
            from services.analytics_service import track_event
            await asyncio.to_thread(track_event, ctx['uid'], 'app_ping_sent',
                                    metadata={'character_id': pend['char'], 'count': pend['count'],
                                              'media': pend['media'] or 'text', 'quiet': quiet})
        except Exception:
            pass
        return 'sent'
    finally:
        _sending.discard(tg)
