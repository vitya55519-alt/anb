"""V3.56.4 static checks (re-pinned by V3.56.8): the soft-figure lock.

V3.56.4 history: the specs opened with 'slim athletic' and Seedream built a
dry gym torso — the fix led every girl with 'voluptuous' E cup. V3.56.8
flipside: «у всех персонажей очень большая грудь», so the roster was
diversified to C/D/E per girl. What SURVIVES from V3.56.4: nobody opens with
'slim', the soft-torso clause (no visible abs, no boyish frame) rides in the
BODY IDENTITY override and in the spicy trailer — only the size emphasis left.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')

SPECS = PHOTO[PHOTO.index('BODY_SPECS = {'):PHOTO.index('}\nDEFAULT_FEMALE_BODY_SPEC')]
DEFAULT_SPEC = PHOTO[PHOTO.index('DEFAULT_FEMALE_BODY_SPEC = ('):PHOTO.index('ORDINARY_IDENTITY_LOCK')]
SPICY_SET = PHOTO[PHOTO.index('async def _run_spicy_set('):PHOTO.index('def choose_photo_provider(')]


def test_no_body_spec_leads_with_slim():
    for line in SPECS.splitlines():
        if "': 'a " in line:
            assert "'a slim" not in line, line
            assert 'hourglass build' in line, line
    assert "'a slim" not in DEFAULT_SPEC
    # V3.56.8: the default is a natural D, not the old everybody-E house size
    assert "'a curvy feminine hourglass build" in DEFAULT_SPEC
    assert 'and a natural full bust (silicone, Russian size 4, D cup)' in DEFAULT_SPEC


def test_identity_override_carries_softness_clause():
    assert 'Her torso stays soft and feminine — never render visible abdominal muscles' in PHOTO
    # V3.56.8: the size hyperbole is gone — the declared cup alone anchors it
    assert 'her bust reads large and heavy under every outfit' not in PHOTO


def test_spicy_trailer_locks_the_soft_figure():
    assert 'soft feminine torso with no visible abs' in SPICY_SET
    assert 'Her figure is locked for this entire shoot' in SPICY_SET
    assert 'never draw her bigger, slimmer, flatter or smaller-chested than declared' in SPICY_SET
