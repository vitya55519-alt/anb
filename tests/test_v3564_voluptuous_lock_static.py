"""V3.56.4 static checks: the house figure is voluptuous, not a fitness torso.

The owner's screenshot: Veronika rendered in white lingerie with visible
abdominal muscles and a modest bust — the BODY_SPECS opened with 'slim
athletic', and Seedream built a gym model, treating the declared E cup as an
afterthought. Fix: every spec now leads with 'voluptuous', hips are explicitly
wide, and the BODY IDENTITY override carries a softness clause (no abs, no
boyish frame, bust reads large under every outfit) that rides into «Наедине»
too, because the private pipeline delegates to the canonical identity lock.

Pins:
1. no built-in body spec opens with 'slim' any more — all are 'voluptuous';
2. the BODY IDENTITY override carries the soft-torso clause;
3. the spicy scene trailer keeps the figure lock and adds the no-abs wording.
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
            assert "'a voluptuous" in line, line
    assert "'a slim" not in DEFAULT_SPEC
    assert "'a voluptuous athletic feminine hourglass build" in DEFAULT_SPEC
    # the house bust tail survived the rewrite (V3.43.3 pins depend on it)
    assert 'and a full bust (silicone, Russian size 5, E cup)' in DEFAULT_SPEC


def test_identity_override_carries_softness_clause():
    assert 'Her torso stays soft and feminine — never render visible abdominal muscles' in PHOTO
    assert 'her bust reads large and heavy under every outfit' in PHOTO


def test_spicy_trailer_locks_the_soft_voluptuous_figure():
    assert 'soft feminine torso with no visible abs' in SPICY_SET
    assert 'Her figure is locked for this entire shoot' in SPICY_SET
