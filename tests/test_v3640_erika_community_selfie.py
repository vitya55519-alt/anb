"""V3.64.0: Erika dresses modern; a community persona with empty params still
gets a photo profile instead of FileNotFoundError on every selfie."""
import json
import os
from pathlib import Path

os.environ.setdefault('TELEGRAM_TOKEN', '123456:TEST_TOKEN')
os.environ.setdefault('GEMINI_API_KEY', 'test-key')

ROOT = Path(__file__).resolve().parents[1]
ERIKA = json.loads((ROOT / 'data' / 'characters' / 'erika_01.json').read_text(encoding='utf-8'))


def test_erika_wardrobe_is_modern_and_exclusive():
    style = ERIKA['visual_identity']['photo_style']
    assert style.get('wardrobe_exclusive') is True
    text = json.dumps(style['wardrobe']).lower()
    for old in ('turtleneck', 'cashmere', 'taupe', 'warm gray', 'chocolate brown'):
        assert old not in text, old
    assert 'tortoiseshell' not in json.dumps(style['hairstyles']).lower()
    assert not any('cashmere' in x for x in ERIKA['visual_identity']['preserve_identity'])


def test_exclusive_wardrobe_skips_generic_pool():
    from services.photo_service import _wardrobe_pool
    pool = _wardrobe_pool('selfie', 2, 'autumn', character_id='erika_01')
    assert pool == ERIKA['visual_identity']['photo_style']['wardrobe']['day_casual']


def test_empty_params_persona_resolves(tmp_path):
    from services.db import init_db
    init_db()
    from services.custom_character_service import save_custom_character, custom_persona_context
    from services.photo_service import resolve_character
    row = save_custom_character(777000111, display_name='Лиза', params={})
    profile = resolve_character(row.character_id)
    assert profile['name'] == 'Лиза'
    assert profile['visual_identity']['reference_folder'].endswith(row.character_id)
    assert 'Лиза' in custom_persona_context(row.character_id)
