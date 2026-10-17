"""V3.62.15: bot name, short description and description set from code."""
from pathlib import Path

MAIN = (Path(__file__).resolve().parents[1] / 'main.py').read_text(encoding='utf-8')


def test_profile_applied_on_startup_and_only_when_changed():
    assert '_spawn_background(_apply_bot_profile())' in MAIN
    fn = MAIN[MAIN.index('async def _apply_bot_profile('):]
    fn = fn[:fn.index('\n\n\n')]
    for call in ('set_my_name', 'set_my_short_description', 'set_my_description'):
        assert call in fn
    assert fn.count('!= prof[') == 3
    assert "BOT_PROFILE_ENABLED" in fn


def test_texts_fit_telegram_limits():
    import ast
    src = MAIN[MAIN.index('BOT_PROFILE = {'):MAIN.index('async def _apply_bot_profile(')]
    assert '18+' in src and 'пишет первой' in src
    for line in src.splitlines():
        if "'short':" in line:
            text = ast.literal_eval(line.split("'short':", 1)[1].strip().rstrip(','))
            assert len(text) <= 120
