"""V3.109.0: Джина and Лана, two new roster girls."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDS = ('jina_01', 'lana_01')


def test_personas_and_references():
    for cid in IDS:
        f = cid.split('_')[0]
        p = json.loads((ROOT / 'data' / 'characters' / f'{cid}.json').read_text(encoding='utf-8'))
        assert p['is_adult'] and p['age'] >= 21
        assert 'art_style' not in p['visual_identity']
        for name in (f'00_{f}_canonical_face.png', f'01_{f}_canonical_look.png'):
            assert (ROOT / 'data' / 'references' / f / name).is_file(), name


def test_every_touchpoint_wired():
    files = ['services/character_card_service.py', 'services/webapp_service.py', 'services/relationship_engine.py',
             'services/photo_service.py', 'services/voice_service.py', 'services/voice_samples.py',
             'services/daily_life.py', 'services/retention_features_service.py', 'services/storylines_data.py',
             'services/custom_character_service.py']
    for path in files:
        text = (ROOT / path).read_text(encoding='utf-8')
        for cid in IDS:
            assert cid in text, (path, cid)


def test_voices_are_real_gemini_voices():
    text = (ROOT / 'services' / 'voice_service.py').read_text(encoding='utf-8')
    pool = text.split('GEMINI_FEMALE_VOICES = (', 1)[1].split(')', 1)[0]
    for cid, voice in (('jina_01', 'Autonoe'), ('lana_01', 'Sulafat')):
        assert f"'{cid}': '{voice}'" in text
        assert f"'{voice}'" in pool
