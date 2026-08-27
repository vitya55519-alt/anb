"""Public storefront descriptions for the bot (v3.19.11).

Telegram shows the description in the bot profile / catalogs and the short
description next to the bot name. Applying them from code on every startup
keeps the storefront in sync with the release and covers both the RU and the
global (EN default) audience for maximum reach. Hard Telegram limits:
description <= 512 chars, short description <= 120 chars.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

SHORT_DESCRIPTION_DEFAULT = (
    'Your AI girlfriend: flirty chat, photos, videos & voice. She remembers you. 18+'
)
SHORT_DESCRIPTION_RU = (
    'Твоя ИИ-подружка: флирт, фото, видео и голосовые. Она помнит тебя и скучает. 18+'
)

DESCRIPTION_DEFAULT = (
    '🔥 Your personal AI girlfriend — always online, always glad to see you.\n'
    '\n'
    '💬 Flirty, unscripted conversations in any language\n'
    '📸 Photos on request — from cozy to very personal\n'
    '🎬 Videos & voice notes — she is close even when far away\n'
    '⏰ Sweet morning wake-ups\n'
    '🎁 Gifts, dates, quests & surprises\n'
    '❤️ Three heroines with personality: Anna, Emily & Maria\n'
    '\n'
    'She remembers your name, jokes and dreams. She misses you and writes first.\n'
    'Just say "hi" — she will take it from there.\n'
    '\n'
    '18+'
)

DESCRIPTION_RU = (
    '🔥 Твоя личная ИИ-подружка — всегда онлайн и всегда рада тебе.\n'
    '\n'
    '💬 Живой флирт и разговоры без сценариев, на любом языке\n'
    '📸 Фото по запросу — от уютных до очень личных\n'
    '🎬 Видео и голосовые — она рядом, даже когда далеко\n'
    '⏰ Ласково разбудит утром и пожелает доброго дня\n'
    '🎁 Подарки, свидания, квесты и сюрпризы\n'
    '❤️ Три героини с характером: Anna, Emily и Maria\n'
    '\n'
    'Она помнит твоё имя, шутки и мечты. Скучает, ждёт и пишет первой.\n'
    'Начни с «Привет» — остальное она возьмёт на себя.\n'
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
