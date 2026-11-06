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


def test_descriptions_mention_calls_and_ten_levels():
    from services import bot_description as bd
    assert '10 уровней' in bd.DESCRIPTION_RU and '10 relationship levels' in bd.DESCRIPTION_DEFAULT
    assert 'позвонить' in bd.DESCRIPTION_RU and 'позвонить' in bd.SHORT_DESCRIPTION_RU
    assert 'call her' in bd.DESCRIPTION_DEFAULT and 'call her' in bd.SHORT_DESCRIPTION_DEFAULT
