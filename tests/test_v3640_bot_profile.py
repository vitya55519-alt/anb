"""V3.62.15: bot name set from code. V3.115.2: descriptions live only in
services/bot_description.py (two writers raced on every deploy)."""
from pathlib import Path

MAIN = (Path(__file__).resolve().parents[1] / 'main.py').read_text(encoding='utf-8')


def test_profile_sets_only_the_name_when_changed():
    assert '_spawn_background(_apply_bot_profile())' in MAIN
    fn = MAIN[MAIN.index('async def _apply_bot_profile('):]
    fn = fn[:fn.index('\n\n')]
    assert 'set_my_name' in fn and fn.count('!= prof[') == 1
    assert 'set_my_description' not in fn and 'set_my_short_description' not in fn
    assert "BOT_PROFILE_ENABLED" in fn


def test_descriptions_match_owner_promo():
    from services import bot_description as bd
    assert bd.DESCRIPTION_RU.startswith('Горячие ИИ-девушки уже ждут тебя.')
    assert bd.SHORT_DESCRIPTION_RU.startswith('Горячие ИИ-девушки уже ждут тебя.')
    assert bd.DESCRIPTION_DEFAULT.startswith('Hot AI girls are waiting for you.')
    assert bd.SHORT_DESCRIPTION_DEFAULT.startswith('Hot AI girls are waiting for you.')


def test_descriptions_on_by_default_name_profile_off():
    """V3.142.0: the owner handed the storefront copy to code — descriptions
    apply on every deploy unless BOT_DESCRIPTIONS_ENABLED=0; the legacy
    BOT_PROFILE name writer stays off by default."""
    fn = MAIN[MAIN.index('async def _apply_bot_profile('):]
    assert "os.getenv('BOT_PROFILE_ENABLED', '0') != '1'" in fn[:fn.index('\n\n')]
    src = (Path(__file__).resolve().parents[1] / 'services' / 'bot_description.py').read_text(encoding='utf-8')
    assert "os.getenv('BOT_DESCRIPTIONS_ENABLED', '1') != '1'" in src
