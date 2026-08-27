"""Static + runtime pins for v3.19.11: auto-applied storefront descriptions.

The bot profile description and short description are applied from code on
every startup (default EN + localized RU) so catalogs and the bot profile
always show the current pitch. Telegram hard limits: 512 / 120 chars.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def test_descriptions_within_telegram_limits_and_marked_18plus():
    from services import bot_description as bd
    for text in (bd.DESCRIPTION_DEFAULT, bd.DESCRIPTION_RU):
        assert 0 < len(text) <= 512
        assert '18+' in text
    for text in (bd.SHORT_DESCRIPTION_DEFAULT, bd.SHORT_DESCRIPTION_RU):
        assert 0 < len(text) <= 120
        assert '18+' in text


def test_descriptions_pitch_core_features_and_heroines():
    from services import bot_description as bd
    for text in (bd.DESCRIPTION_DEFAULT, bd.DESCRIPTION_RU):
        assert 'Anna' in text and 'Emily' in text and 'Maria' in text
    assert 'Фото' in bd.DESCRIPTION_RU and 'Видео' in bd.DESCRIPTION_RU
    assert 'Photos' in bd.DESCRIPTION_DEFAULT and 'Videos' in bd.DESCRIPTION_DEFAULT


def test_startup_applies_descriptions_before_polling():
    assert 'from services.bot_description import apply_bot_descriptions' in MAIN
    assert 'await apply_bot_descriptions(bot)' in MAIN
    # Non-fatal: a Bot API hiccup must never stop the bot from starting.
    assert 'bot description apply failed' in MAIN
    assert MAIN.index('await apply_bot_descriptions(bot)') < MAIN.index('await dp.start_polling(bot)')
