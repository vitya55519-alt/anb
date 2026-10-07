# -*- coding: utf-8 -*-
"""V3.56.8 static pins: per-girl bust sizes + the lingerie layering lock.

Owner's double complaint: «у всех персонажей очень большая грудь» (the
voluptuous-first rewrite + the hardcoded VERY LARGE E cup in BUST_CONSISTENCY
stacked into cartoon proportions) and «белье выше одежды» (a rooftop shot came
back with the lace bra worn OVER the blouse).

Fixes pinned here:
1. BODY_SPECS carries three declared sizes (C/D/E) and covers every heroine;
2. no prompt text exaggerates the bust any more;
3. every clothed scene injects the LINGERIE LAYERING LOCK, lingerie-as-outfit
   scenes do not.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')

SPECS = PHOTO[PHOTO.index('BODY_SPECS = {'):PHOTO.index('}\nDEFAULT_FEMALE_BODY_SPEC')]
RULE = PHOTO[PHOTO.index('BUST_CONSISTENCY_RULE = ('):PHOTO.index('SEASON_RULES')]
BUILD = PHOTO[PHOTO.index('def _build_prompt('):PHOTO.index('def _extract_openai_many')]


def test_roster_is_size_diverse():
    assert SPECS.count('Russian size 3, C cup') >= 3
    assert SPECS.count('Russian size 4, D cup') >= 4
    assert SPECS.count('Russian size 5, E cup') >= 3
    # every built-in heroine is declared — nobody falls through to the default
    for cid in ('alena_01', 'maria_01', 'erika_01', 'sonya_01', 'vika_01', 'alisa_01', 'mila_01',
                'veronika_01', 'eva_01', 'darina_01', 'kristina_01', 'romina_01',
                'violetta_01', 'zlata_01'):
        assert f"'{cid}':" in SPECS, cid


def test_no_hyperbole_left_in_the_prompt_chain():
    assert 'VERY LARGE' not in PHOTO
    assert 'visibly prominent and heavy' not in RULE
    assert 'her bust reads large and heavy' not in PHOTO
    assert 'very voluptuous hourglass silhouette' not in PHOTO
    # the anti-drift wording is back (v3164/v3438 depend on it)
    assert 'neither larger nor smaller' in RULE


def test_lingerie_layering_lock_rides_every_clothed_scene():
    assert 'LINGERIE_LAYERING_LOCK = (' in PHOTO
    assert 'never draw a bra, lace cups, straps, garters or' in PHOTO
    # wired into the prompt template, skipped for nude/home-lingerie frames
    assert '{"" if (adult_scene or home_lingerie) else LINGERIE_LAYERING_LOCK}' in BUILD
    assert 'UNDER-CLOTHING REALISM' in BUILD
