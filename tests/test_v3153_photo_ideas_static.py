import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
IDEA_SERVICE = (ROOT / 'services' / 'photo_idea_service.py').read_text(encoding='utf-8')
IDEAS_PATH = ROOT / 'data' / 'photo_ideas.json'

_SCENES_BLOCK = PHOTO[PHOTO.index('SCENES = {'):PHOTO.index('}', PHOTO.index('SCENES = {'))]
SCENE_KEYS = set(re.findall(r"'(\w+)':", _SCENES_BLOCK))


def test_photo_ideas_config_exists():
    assert 'PHOTO_IDEAS_ENABLED' in CONFIG
    assert 'PHOTO_IDEA_LLM_CHANCE' in CONFIG


def test_idea_bank_is_valid():
    bank = json.loads(IDEAS_PATH.read_text(encoding='utf-8'))
    assert isinstance(bank, list) and len(bank) >= 30
    for idea in bank:
        assert idea.get('scene') in SCENE_KEYS, f"unknown scene: {idea.get('scene')}"
        assert idea.get('location') and idea.get('angle')
        # Bank wording must stay mainstream: no intimate/sexual tokens.
        text = f"{idea['location']} {idea['angle']}".lower()
        for token in ('lingerie', 'sexy', 'nude', 'boudoir', 'bed '):
            assert token not in text, f"intimate token {token!r} in idea {idea}"


def test_idea_service_surface():
    assert 'def pick_idea(' in IDEA_SERVICE
    assert 'async def enrich_request_with_idea(' in IDEA_SERVICE
    assert 'async def _llm_variation(' in IDEA_SERVICE
    assert 'photo_ideas.json' in IDEA_SERVICE
    # Private scenes are never rewritten by the idea engine.
    assert "'personal', 'lingerie', 'private_fashion'" in IDEA_SERVICE
    # LLM failures must degrade to the curated bank, never break generation.
    assert 'except Exception' in IDEA_SERVICE


def test_generate_photo_set_applies_ideas():
    block = PHOTO[PHOTO.index('async def generate_photo_set'):PHOTO.index('async def generate_photo(')]
    assert 'enrich_request_with_idea' in block
    # Enrichment happens before the request is resolved into a prompt.
    assert block.index('enrich_request_with_idea') < block.index('_resolve_request')
    assert 'photo_idea_applied' in block
