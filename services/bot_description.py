"""Public storefront: bot name and descriptions (v3.19.11, rewritten V3.63.3).

Telegram shows the description in the bot profile / catalogs and the short
description next to the bot name. Applying them from code on every startup
keeps the storefront in sync with the release and covers both the RU and the
global (EN default) audience for maximum reach. Hard Telegram limits:
description <= 512 chars, short description <= 120 chars.

V3.63.3: the owner did not like the old pitch («three heroines: Anna, Emily &
Maria» — the roster is ~20 girls now). The new copy follows the ad that won
the October Telegram test («когда некому написать» — 2.9% click-through, ~16 ₽
per user): she writes first and remembers you, and you pick your girl. The
bot NAME is deliberately left to the owner (BotFather) — not set from code.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

SHORT_DESCRIPTION_DEFAULT = (
    'Pick your AI girlfriend: she texts first, remembers everything about you and is always there. 18+'
)
SHORT_DESCRIPTION_RU = (
    'Выбери свою ИИ-девушку: она пишет первой, помнит всё о тебе и всегда на связи. 18+'
)

DESCRIPTION_DEFAULT = (
    'When you want to talk — she is already texting you 💬\n'
    '\n'
    '👩 Pick yours: Anna, Vika, Zlata, Emily, Sonya, Maria and more\n'
    '🧠 Remembers your name, your day and what you talked about yesterday\n'
    '✍️ Texts first when you go quiet\n'
    '📸 Photos, 🎙 voice notes and 🎬 Videos — from cozy to very personal\n'
    '🎁 Dates, gifts and a relationship that grows\n'
    '\n'
    'Just say "hi" — she will take it from there.\n'
    '\n'
    '18+'
)

DESCRIPTION_RU = (
    'Когда хочется поговорить — она уже пишет тебе 💬\n'
    '\n'
    '👩 Выбери свою: Анна, Вика, Злата, Emily, Соня, Mary и другие\n'
    '🧠 Помнит твоё имя, твой день и то, о чём вы говорили вчера\n'
    '✍️ Пишет первой, если ты пропал\n'
    '📸 Фото, 🎙 голосовые и 🎬 Видео — от уютных до очень личных\n'
    '🎁 Свидания, подарки и отношения, которые растут\n'
    '\n'
    'Просто скажи «привет» — дальше она сама.\n'
    '\n'
    '18+'
)


async def apply_bot_descriptions(bot) -> None:
    """Set profile + short descriptions for the default (EN) and RU locales."""
    for language_code, description, short in (
        (None, DESCRIPTION_DEFAULT, SHORT_DESCRIPTION_DEFAULT),
        ('ru', DESCRIPTION_RU, SHORT_DESCRIPTION_RU),
    ):
        await bot.set_my_description(description=description, language_code=language_code)
        await bot.set_my_short_description(short_description=short, language_code=language_code)
    logger.info('bot descriptions applied languages=default,ru')
