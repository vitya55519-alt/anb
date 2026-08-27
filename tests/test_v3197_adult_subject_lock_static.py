"""Static + runtime regression tests for v3.19.7/v3.19.8: adult-subject lock.

v3.19.7 added the HARD SUBJECT LOCK (adult woman 20+, never minors) to every
provider prompt. Its compact-prompt experiment for Pollinations degraded the
free provider's photo quality, so v3.19.8 restored the rich full prompt and
simply prepends the lock first, with a generous 4000-char URL cap (the
endpoint accepts ~9KB URLs; flattening to one line is mandatory).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')


def test_adult_only_lock_constant_defined():
    assert 'ADULT_ONLY_LOCK = (' in PHOTO
    assert 'HARD SUBJECT LOCK' in PHOTO
    assert 'no children' in PHOTO
    assert 'adult woman in her twenties' in PHOTO
    assert 'POLLINATIONS_MAX_PROMPT_CHARS = 4000' in PHOTO


def test_full_prompt_includes_subject_lock_before_scene():
    from services.photo_service import PhotoRequest, _build_prompt
    request = PhotoRequest(scene='fashion', clothing='an elegant fitted dress')
    prompt = _build_prompt(request, 0, seedream=False, relationship_level=3, character_id='anna_01')
    assert 'HARD SUBJECT LOCK' in prompt
    assert 'no children' in prompt
    # The lock must sit right after the identity block, before scene details.
    assert prompt.index('HARD SUBJECT LOCK') < prompt.index('SCENE:')


def test_pollinations_keeps_rich_full_prompt_with_lock_first():
    block = PHOTO[PHOTO.index('async def _pollinations_one_frame'):PHOTO.index('async def _run_pollinations_set')]
    # V3.19.8: full rich prompt restored, lock prepended at the very start.
    assert "prompt = ADULT_ONLY_LOCK + ' ' + _build_prompt(" in block
    assert 'FREE PROVIDER ORDINARY-PHOTO RULE' in block
    # Flattening before quoting (newlines -> 404 on this endpoint).
    assert block.index("prompt.split('\\n')") < block.index('quote(prompt)')
    # Generous cap after flattening; the lock leads so a cut keeps the subject.
    assert block.index('POLLINATIONS_MAX_PROMPT_CHARS') < block.index('quote(prompt)')
    # The compact experiment is gone.
    assert 'compact=True' not in block
