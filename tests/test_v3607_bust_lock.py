"""V3.60.7: the bust size stops jumping between photos."""
from pathlib import Path

from services import photo_service as ps
from services import private_photo_service as pps

PRIVATE = Path('services/private_photo_service.py').read_text(encoding='utf-8')


def test_bust_lock_uses_declared_cup():
    assert 'C cup' in ps.bust_lock_line('zlata_01')
    assert 'D cup' in ps.bust_lock_line('veronika_01')
    assert 'E cup' in ps.bust_lock_line('anna_01')
    assert 'not bigger, not smaller' in ps.bust_lock_line('zlata_01')


def test_regular_prompt_ends_with_bust_lock():
    req = ps.parse_photo_request('селфи в кафе')
    prompt = ps._build_prompt(req, 0, seedream=True, relationship_level=3, character_id='zlata_01')
    assert prompt.rstrip().splitlines()[-1].startswith('BUST LOCK: her bust is exactly C cup')


def test_no_push_up_in_random_pools():
    assert 'push-up' not in ' '.join(pps.BRA_CUT_POOL)
    assert 'classic padded bra and briefs' not in ps.UNDERWEAR_STYLE_POOL
    assert 'push-up bra and matching briefs' not in ps.UNDERWEAR_STYLE_POOL
    assert 'squeezing her own breasts' not in PRIVATE


def test_private_prompt_has_bust_lock():
    assert 'parts.append(bust_lock)' in PRIVATE


def test_private_bust_lock_sits_right_before_face_lock():
    req = pps.PrivatePhotoRequest(category='lingerie', type_id='lace', location_id='bedroom', mood_id='', character_id='zlata_01')
    lines = pps.build_private_photo_prompt(req, 'x').strip().splitlines()
    assert lines[-1].startswith('FACE LOCK')
    assert any(l.startswith('BUST LOCK: her bust is exactly C cup') for l in lines)
