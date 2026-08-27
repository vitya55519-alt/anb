"""Static + runtime regression tests for v3.19.7/v3.19.9: adult-subject lock.

v3.19.7 added the HARD SUBJECT LOCK (adult woman 20+, never minors) to every
provider prompt after a free fallback rendered a child in an industrial zone.
v3.19.9 removed that free provider (Pollinations.ai) entirely on the owner's
request (repeated http_500): the photo chain is now Gemini Image -> OpenAI ->
fal/Seedream only, and the lock stays in every prompt.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')


def test_adult_only_lock_constant_defined():
    assert 'ADULT_ONLY_LOCK = (' in PHOTO
    assert 'HARD SUBJECT LOCK' in PHOTO
    assert 'no children' in PHOTO
    assert 'adult woman in her twenties' in PHOTO


def test_full_prompt_includes_subject_lock_before_scene():
    from services.photo_service import PhotoRequest, _build_prompt
    request = PhotoRequest(scene='fashion', clothing='an elegant fitted dress')
    prompt = _build_prompt(request, 0, seedream=False, relationship_level=3, character_id='anna_01')
    assert 'HARD SUBJECT LOCK' in prompt
    assert 'no children' in prompt
    # The lock must sit right after the identity block, before scene details.
    assert prompt.index('HARD SUBJECT LOCK') < prompt.index('SCENE:')


def test_pollinations_removed_entirely():
    # V3.19.9 owner decision: the free provider is gone from code and config.
    assert 'pollinations' not in PHOTO.lower()
    assert 'POLLINATIONS' not in CONFIG
    assert 'image.pollinations.ai' not in PHOTO
    assert '_run_pollinations_set' not in PHOTO
    # The remaining chain: Gemini -> OpenAI -> Seedream.
    assert 'from=seedream45 to=gemini_image' in PHOTO
    assert 'from=gemini_image to=seedream45' in PHOTO
