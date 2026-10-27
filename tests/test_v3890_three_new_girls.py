"""V3.89.0: Юля, Лиза, Кира — three roster girls from the owner's AI model shots."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDS = ('yulya_01', 'liza_01', 'kira_01')


def test_personas_and_references():
    for cid in IDS:
        f = cid.split('_')[0]
        p = json.loads((ROOT / 'data' / 'characters' / f'{cid}.json').read_text(encoding='utf-8'))
        assert p['is_adult'] and p['age'] >= 21
        assert 'art_style' not in p['visual_identity']  # photographed, like the roster
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
