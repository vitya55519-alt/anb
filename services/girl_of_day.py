"""V3.92.0: owner — «одну девушку любую на день открывать, чтобы все
пообщались. И как раз будет пост для канала».

Every day (00:00 UTC = 03:00 MSK, like the daily missions) one built-in
roster girl is «🔥 Девушка дня»: her chat is open to every confirmed adult
without Premium — the explicit chat that V3.90 keeps for Premium. Her
nude/undress media stay Premium-only. The girls rotate in a fixed order;
an admin can switch today's girl (/girlday). At the turn of the day the
admins get a ready channel post with a «📣 В канал» button.
"""
from __future__ import annotations

import datetime as dt
import time

from services import dialog_store

# 2026-10-29: the owner opened it right after Агата shipped — she goes first.
ANCHOR_DATE = dt.date(2026, 10, 29)
ANCHOR_GIRL = 'agata_01'
DEEP_LINK_PREFIX = 'src_girlday_'

_override = dialog_store.DialogStore('girl_of_day')
_OVERRIDE_KEY = 0
_CACHE_SECONDS = 300
_cache: dict = {}  # {'day': date, 'at': monotonic, 'id': str | None}


def today(now: dt.datetime | None = None) -> dt.date:
    return (now or dt.datetime.utcnow()).date()


def pool() -> list[str]:
    """Built-in, visible, non-Premium-status roster girls (no constructor
    girls, no hidden scenario-card girls)."""
    from services.character_card_service import list_cards
    from services.custom_character_service import is_custom_character
    try:
        from services.scenario_cards import SCENARIO_GIRLS
    except Exception:
        SCENARIO_GIRLS = set()
    return sorted(c.character_id for c in list_cards(visible_only=True)
                  if c.status == 'active' and not is_custom_character(c.character_id)
                  and c.character_id not in SCENARIO_GIRLS)


def rotation_pick(day: dt.date, girls: list[str]) -> str | None:
    if not girls:
        return None
    start = girls.index(ANCHOR_GIRL) if ANCHOR_GIRL in girls else 0
    return girls[(start + (day - ANCHOR_DATE).days) % len(girls)]


def current(now: dt.datetime | None = None) -> str | None:
    day = today(now)
    if now is None and _cache.get('day') == day and time.monotonic() - _cache.get('at', 0) < _CACHE_SECONDS:
        return _cache.get('id')
    picked = _resolve(day)
    if now is None:
        _cache.update(day=day, at=time.monotonic(), id=picked)
    return picked


def _resolve(day: dt.date) -> str | None:
    try:
        ov = _override.get(_OVERRIDE_KEY) or {}
        if ov.get('date') == day.isoformat() and ov.get('id'):
            return ov['id']
    except Exception:
        pass
    try:
        return rotation_pick(day, pool())
    except Exception:
        return None


def set_today(character_id: str) -> None:
    _override[_OVERRIDE_KEY] = {'date': today().isoformat(), 'id': character_id}
    _cache.clear()


def is_open(character_id: str | None) -> bool:
    return bool(character_id) and character_id == current()


def girl_from_payload(args: str | None) -> str | None:
    a = (args or '').strip().lower()
    if not a.startswith(DEEP_LINK_PREFIX):
        return None
    cid = a[len(DEEP_LINK_PREFIX):]
    return cid if cid in pool() else None


def post_caption(name: str, age, bio: str) -> str:
    return (f'🔥 Девушка дня — {name}, {age}\n\n'
            f'{bio}\n\n'
            'Только сегодня до 03:00 МСК она открыта для всех: без Premium и без уровней. '
            'Пиши ей что хочешь, она ответит так же откровенно 😏\n\n'
            '18+')


def build_post(character_id: str) -> tuple[bytes | None, str]:
    """The channel post: her storefront look shot as JPEG + the caption."""
    from services.character_card_service import get_card
    card = get_card(character_id)
    name = card.display_name if card else character_id
    caption = post_caption(name, card.age if card else '', (card.short_bio if card else '') or '')
    photo = None
    try:
        import io
        from PIL import Image
        from services import webapp_service
        got = webapp_service.character_photo(character_id, 1) or webapp_service.character_photo(character_id, 0)
        if got:
            img = Image.open(io.BytesIO(got[0])).convert('RGB')
            img.thumbnail((1280, 1280))
            buf = io.BytesIO()
            img.save(buf, 'JPEG', quality=88)
            photo = buf.getvalue()
    except Exception:
        photo = None
    return photo, caption


def deep_link(character_id: str) -> str:
    from config import BOT_USERNAME
    return f'https://t.me/{BOT_USERNAME}?start={DEEP_LINK_PREFIX}{character_id}'


def name_of(character_id: str) -> str:
    try:
        from services.character_card_service import get_card
        card = get_card(character_id)
        return card.display_name if card else character_id
    except Exception:
        return character_id


def post_markup(character_id: str):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=f'💬 Написать {name_of(character_id)}', url=deep_link(character_id))]])


def admin_markup(character_id: str):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f'💬 Написать {name_of(character_id)}', url=deep_link(character_id))],
        [InlineKeyboardButton(text='📣 Опубликовать в канал', callback_data=f'gday:post:{character_id}')],
        [InlineKeyboardButton(text='🔄 Другая девушка сегодня', callback_data='gday:next')],
    ])


async def send_admin_preview(bot, chat_id: int, character_id: str | None = None) -> None:
    import asyncio
    from aiogram.types import BufferedInputFile
    cid = character_id or await asyncio.to_thread(current)
    if not cid:
        await bot.send_message(chat_id, '🔥 Девушка дня: в ротации нет подходящих девушек.')
        return
    photo, caption = await asyncio.to_thread(build_post, cid)
    head = '🔥 Девушка дня на сегодня. Так будет выглядеть пост в канале:\n\n'
    if photo:
        await bot.send_photo(chat_id, BufferedInputFile(photo, filename=f'{cid}.jpg'),
                             caption=(head + caption)[:1024], reply_markup=admin_markup(cid))
    else:
        await bot.send_message(chat_id, head + caption, reply_markup=admin_markup(cid))


async def publish(bot, channel: str, character_id: str) -> None:
    import asyncio
    from aiogram.types import BufferedInputFile
    photo, caption = await asyncio.to_thread(build_post, character_id)
    if photo:
        await bot.send_photo(channel, BufferedInputFile(photo, filename=f'{character_id}.jpg'),
                             caption=caption[:1024], reply_markup=post_markup(character_id))
    else:
        await bot.send_message(channel, caption, reply_markup=post_markup(character_id))
