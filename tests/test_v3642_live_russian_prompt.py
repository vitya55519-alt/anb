"""V3.64.2: «общаешься как с переводом, с болванчиком».

The dialog prompt opened with a broken «который переписывается с пареньей»,
taught a girl masculine forms («я так устал», «я тут подумал») and therapist
calques («звучит, как будто тебе грустно»). Now every example agrees with her
gender, calques are named as forbidden and a «ЦЕПЛЯЙ» block asks for a hook.
"""
from services.character_service import build_system_prompt, get_character


def _prompt(cid='alisa_01'):
    return build_system_prompt(get_character(cid), 'REL', [], character_id=cid)


def test_opening_line_is_correct_russian():
    t = _prompt()
    assert 'Живая девушка, которая переписывается в Telegram с парнем.' in t
    assert 'пареньей' not in t and 'пареньам' not in t


def test_girl_examples_are_feminine():
    t = _prompt()
    assert 'я так устала сегодня' in t and 'я так устал сегодня' not in t
    assert 'я тут подумала' in t
    assert 'звучит, как будто тебе грустно' not in t


def test_live_russian_and_hook_blocks_present():
    t = _prompt()
    assert 'ЖИВОЙ РУССКИЙ, НЕ ПЕРЕВОД' in t
    assert 'ЦЕПЛЯЙ' in t
