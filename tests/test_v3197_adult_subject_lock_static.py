"""Static + runtime regression tests for v3.19.7: adult-subject hard lock.

Production incident: the free Pollinations fallback rendered a child in an
industrial zone instead of the character — the huge multi-section prompt made
the model drop the subject entirely. Fix: a HARD SUBJECT LOCK (adult woman
20+, never minors) is injected into every provider prompt right after the
identity block, and Pollinations now gets a compact identity-first prompt
capped at POLLINATIONS_MAX_PROMPT_CHARS so no truncation can lose the subject.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')


def test_adult_only_lock_constant_defined():
    assert 'ADULT_ONLY_LOCK = (' in PHOTO
    assert 'HARD SUBJECT LOCK' in PHOTO
    assert 'no children' in PHOTO
    assert 'adult woman in her twenties' in PHOTO
    assert 'POLLINATIONS_MAX_PROMPT_CHARS = 1600' in PHOTO


def test_full_prompt_includes_subject_lock_before_scene():
    from services.photo_service import PhotoRequest, _build_prompt
    request = PhotoRequest(scene='fashion', clothing='an elegant fitted dress')
    prompt = _build_prompt(request, 0, seedream=False, relationship_level=3, character_id='anna_01')
    assert 'HARD SUBJECT LOCK' in prompt
    assert 'no children' in prompt
    # The lock must sit right after the identity block, before scene details.
    assert prompt.index('HARD SUBJECT LOCK') < prompt.index('SCENE:')


def test_compact_prompt_keeps_identity_and_safety_first():
    from services.photo_service import PhotoRequest, _build_prompt
    request = PhotoRequest(scene='embankment', clothing='a light summer dress')
    prompt = _build_prompt(request, 0, seedream=False, relationship_level=3, character_id='anna_01', compact=True)
    assert 'HARD SUBJECT LOCK' in prompt
    assert 'adult woman in her twenties' in prompt
    assert prompt.index('HARD SUBJECT LOCK') < prompt.index('SCENE:')
    # Single line (URL-safe) and short enough to survive any proxy truncation.
    assert '\n' not in prompt
    assert len(prompt) <= 2200


def test_pollinations_uses_compact_capped_prompt():
    block = PHOTO[PHOTO.index('async def _pollinations_one_frame'):PHOTO.index('async def _run_pollinations_set')]
    assert 'compact=True' in block
    assert 'POLLINATIONS_MAX_PROMPT_CHARS' in block
    # Order: compact build -> flatten -> cap -> quote into the URL.
    assert block.index('compact=True') < block.index("prompt.split('\\n')")
    assert block.index('POLLINATIONS_MAX_PROMPT_CHARS') < block.index('quote(prompt)')
