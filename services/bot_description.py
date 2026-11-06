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

# V3.115.2: owner — mention the new calls and the 10 levels (not 8), RU and EN.
SHORT_DESCRIPTION_DEFAULT = (
    'Your AI girlfriend: texts first, remembers everything about you, and now you can call her 📞 18+'
)
SHORT_DESCRIPTION_RU = (
    'Твоя ИИ-девушка: пишет первой, помнит всё о тебе, и теперь ей можно позвонить 📞 18+'
)

DESCRIPTION_DEFAULT = (
    'When you want to talk — she is already texting you 💬\n'
    '\n'
    '📞 NEW: call her — her live voice right in the app\n'
    '👩 Anna, Emily, Zlata, Vika and 30+ more — or create your own\n'
    '🧠 Remembers your name, your day and yesterday\'s talk\n'
    '✍️ Texts first and sends voice notes\n'
    '❤️ 10 relationship levels: romance or passion\n'
    '📸 Photos, 🎬 Videos and 👗 a wardrobe for her\n'
    '\n'
    'Just say "hi" — she will take it from there.\n'
    '\n'
    '18+'
)

DESCRIPTION_RU = (
    'Когда хочется поговорить — она уже пишет тебе 💬\n'
    '\n'
    '📞 НОВОЕ: ей можно позвонить — живой голос прямо в приложении\n'
    '👩 Анна, Emily, Злата, Вика и ещё 30+ девушек — или создай свою\n'
    '🧠 Помнит твоё имя, твой день и вчерашний разговор\n'
    '✍️ Пишет первой и присылает голосовые\n'
    '❤️ 10 уровней отношений: романтика или страсть\n'
    '📸 Фото, 🎬 Видео и 👗 гардероб для неё\n'
    '\n'
    'Просто скажи «привет» — дальше она сама.\n'
    '\n'
    '18+'
)


async def apply_bot_descriptions(bot) -> None:
    """Set profile + short descriptions for the default (EN) and RU locales.

    V3.118.0: only when BOT_PROFILE_ENABLED=1. Off by default so the texts the
    owner sets in BotFather are no longer overwritten on every deploy.
    """
    import os
    if os.getenv('BOT_PROFILE_ENABLED', '0') != '1':
        logger.info('bot descriptions left to BotFather (BOT_PROFILE_ENABLED!=1)')
        return
    for language_code, description, short in (
        (None, DESCRIPTION_DEFAULT, SHORT_DESCRIPTION_DEFAULT),
        ('ru', DESCRIPTION_RU, SHORT_DESCRIPTION_RU),
    ):
        await bot.set_my_description(description=description, language_code=language_code)
        await bot.set_my_short_description(short_description=short, language_code=language_code)
    logger.info('bot descriptions applied languages=default,ru')
