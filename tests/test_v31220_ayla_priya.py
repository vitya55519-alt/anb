"""V3.122.0: Айла and Прия, new roster girls, and rear-view framings."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDS = ('ayla_01', 'priya_01')


def test_personas_and_references():
    for cid in IDS:
        f = cid.split('_')[0]
        p = json.loads((ROOT / 'data' / 'characters' / f'{cid}.json').read_text(encoding='utf-8'))
        assert p['is_adult'] and p['age'] >= 21
        assert 'art_style' not in p['visual_identity']
        for name in p['visual_identity']['reference_assets']:
            assert (ROOT / 'data' / 'references' / f / name).is_file(), name
        assert f'02_{f}_canonical_back.png' in p['visual_identity']['reference_assets']


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
    for cid, voice in (('ayla_01', 'Aoede'), ('priya_01', 'Leda')):
        assert f"'{cid}': '{voice}'" in text
        assert f"'{voice}'" in pool


def test_everyday_packs_include_a_rear_view():
    from services import photo_service as ps
    rear = [k for k, v in ps.SHOT_VARIANTS.items() if any('over her shoulder' in s and 'from behind' in s or 'back half-turned' in s or 'three-quarters away' in s for s in v)]
    for scene in ('park', 'mirror', 'outfit', 'gym', 'embankment'):
        assert scene in rear, scene
    assert any('three-quarters away' in p for p in ps.POSE_POOL)
