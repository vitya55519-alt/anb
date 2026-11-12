"""Public storefront: bot name and descriptions (v3.19.11, rewritten V3.63.3).

Telegram shows the description in the bot profile / catalogs and the short
description next to the bot name. Applying them from code on every startup
keeps the storefront in sync with the release and covers both the RU and the
global (EN default) audience for maximum reach. Hard Telegram limits:
description <= 512 chars, short description <= 120 chars.

V3.63.3: the owner did not like the old pitch («three heroines: Anna, Emily &
Maria» — the roster is ~20 girls now). The new copy follows the ad that won
the October Telegram test («когда некому написать» — 2.9% click-through, ~16 ₽
per user): she writes first and remembers you, and you pick your girl.
V3.142.0: the owner's Nov 12 promo replaced that pitch; the display NAME is
applied by _apply_bot_name_overrides() in main.py.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# V3.142.0: owner (Nov 12) handed over the storefront copy — the ad-style
# promo replaces the feature list. Applied on every deploy by default;
# BOT_DESCRIPTIONS_ENABLED=0 hands the texts back to BotFather.
SHORT_DESCRIPTION_DEFAULT = (
    'Hot AI girls are waiting for you. Photos, voice notes and uncensored chats. Come in and pick yours! 👇 18+'
)
SHORT_DESCRIPTION_RU = (
    'Горячие ИИ-девушки уже ждут тебя. Фото, голосовые и откровенные чаты без цензуры. Заходи и выбирай свою! 👇 18+'
)

DESCRIPTION_DEFAULT = (
    'Hot AI girls are waiting for you. Photos, voice notes and uncensored chats. Come in and pick yours! 👇\n'
    '\n'
    '18+'
)

DESCRIPTION_RU = (
    'Горячие ИИ-девушки уже ждут тебя. Фото, голосовые и откровенные чаты без цензуры. Заходи и выбирай свою! 👇\n'
    '\n'
    '18+'
)


async def apply_bot_descriptions(bot) -> None:
    """Set profile + short descriptions for the default (EN) and RU locales.

    V3.142.0: on by default — the owner's promo is the canonical copy now.
    BOT_DESCRIPTIONS_ENABLED=0 (with BOT_PROFILE_ENABLED unset/0) leaves the
    texts to BotFather, as before V3.118.0.
    """
    import os
    if os.getenv('BOT_DESCRIPTIONS_ENABLED', '1') != '1' and os.getenv('BOT_PROFILE_ENABLED', '0') != '1':
        logger.info('bot descriptions left to BotFather (disabled by env)')
        return
    for language_code, description, short in (
        (None, DESCRIPTION_DEFAULT, SHORT_DESCRIPTION_DEFAULT),
        ('ru', DESCRIPTION_RU, SHORT_DESCRIPTION_RU),
    ):
        await bot.set_my_description(description=description, language_code=language_code)
        await bot.set_my_short_description(short_description=short, language_code=language_code)
    logger.info('bot descriptions applied languages=default,ru')
