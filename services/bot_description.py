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

# V3.127.0: owner (Nov 7) — the pitch is about many girls, not one «Анна»,
# and it carries the search words people type («ИИ девушка», «чат с ИИ
# девушкой», «бесплатно»), Wordstat: «ии девушка» ~214k searches a month.
SHORT_DESCRIPTION_DEFAULT = (
    'AI girlfriends on Telegram: 18+ chat, photos, voice. Pick a girl: she texts first, remembers you, you can call her 📞'
)
SHORT_DESCRIPTION_RU = (
    'ИИ девушки в Telegram: чат 18+, фото и голосовые. Пишут первыми, помнят тебя, им можно позвонить 📞'
)

DESCRIPTION_DEFAULT = (
    'AI girlfriends who text you first 💬\n'
    '\n'
    'Chat with an AI girlfriend right in Telegram — no apps to install.\n'
    '\n'
    '👩 Anna, Emily, Zlata, Vika and 30+ more girls — pick yours or create your own\n'
    '🧠 They remember your name, your day and yesterday\'s talk\n'
    '📸 Photos, 🎬 Videos and voice notes\n'
    '📞 You can call her — a live voice in the app\n'
    '❤️ 10 relationship levels: romance or passion\n'
    '\n'
    'Free to start: just say "hi".\n'
    '\n'
    '18+'
)

DESCRIPTION_RU = (
    'ИИ девушки, которые пишут тебе первыми 💬\n'
    '\n'
    'Чат с ИИ девушкой на русском прямо в Telegram — без сайтов и приложений.\n'
    '\n'
    '👩 Анна, Emily, Злата, Вика и ещё 30+ девушек — выбери свою или создай\n'
    '🧠 Помнят твоё имя, твой день и вчерашний разговор\n'
    '📸 Фото, 🎬 Видео и голосовые\n'
    '📞 Можно позвонить — живой голос в приложении\n'
    '❤️ 10 уровней отношений: романтика или страсть\n'
    '\n'
    'Начать бесплатно: просто напиши «привет».\n'
    '\n'
    '18+'
)


async def apply_bot_descriptions(bot) -> None:
    """Set profile + short descriptions for the default (EN) and RU locales.

    V3.118.0: only when BOT_PROFILE_ENABLED=1. Off by default so the texts the
    owner sets in BotFather are no longer overwritten on every deploy.
    """
    import os
    # V3.127.0: BOT_DESCRIPTIONS_ENABLED=1 writes only the descriptions (the
    # name is handled by BOT_NAME_* in main.py), BOT_PROFILE_ENABLED=1 as before.
    if os.getenv('BOT_PROFILE_ENABLED', '0') != '1' and os.getenv('BOT_DESCRIPTIONS_ENABLED', '0') != '1':
        logger.info('bot descriptions left to BotFather (BOT_PROFILE_ENABLED!=1)')
        return
    for language_code, description, short in (
        (None, DESCRIPTION_DEFAULT, SHORT_DESCRIPTION_DEFAULT),
        ('ru', DESCRIPTION_RU, SHORT_DESCRIPTION_RU),
    ):
        await bot.set_my_description(description=description, language_code=language_code)
        await bot.set_my_short_description(short_description=short, language_code=language_code)
    logger.info('bot descriptions applied languages=default,ru')
