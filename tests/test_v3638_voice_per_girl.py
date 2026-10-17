"""V3.63.8: every girl speaks with her own voice; custom girls get a valid one."""
import json
from pathlib import Path

from services import voice_service as vs

ROOT = Path(__file__).resolve().parents[1]


def _girls():
    for f in (ROOT / 'data' / 'characters').glob('*.json'):
        cid = json.loads(f.read_text(encoding='utf-8')).get('id')
        if cid and not f.name.endswith('_dna.json'):
            yield cid


def test_every_stock_girl_has_her_own_voice_and_manner():
    for cid in _girls():
        assert cid in vs.GEMINI_TTS_VOICES, cid
        assert cid in vs.GEMINI_TTS_MANNER, cid
        assert vs.GEMINI_TTS_VOICES[cid] in vs.GEMINI_FEMALE_VOICES, cid


def test_custom_girls_get_a_stable_real_voice():
    a = vs.gemini_voice_for('custom_123_abcdef01')
    assert a in vs.GEMINI_FEMALE_VOICES
    assert a == vs.gemini_voice_for('custom_123_abcdef01')
    picks = {vs.gemini_voice_for(f'custom_1_{i:08x}') for i in range(40)}
    assert len(picks) > 5
    assert 'Erin' not in vs.GEMINI_FEMALE_VOICES


def test_alisa_sounds_young_and_customs_skip_the_mature_voice():
    # V3.63.10: «у Алисы голос грубый, как у сорокалетней»
    assert vs.GEMINI_TTS_VOICES['alisa_01'] == 'Autonoe'
    assert 'Vindemiatrix' not in vs.GEMINI_FEMALE_VOICES
    assert 'Gacrux' not in vs._CUSTOM_VOICE_POOL
    assert all(vs.gemini_voice_for(f'custom_9_{i:08x}') != 'Gacrux' for i in range(60))


def test_erika_no_longer_uses_gacrux():
    # V3.63.11: «у Эрики озвучка вообще стрёмная»
    assert vs.GEMINI_TTS_VOICES['erika_01'] == 'Aoede'
    assert 'Gacrux' not in vs.GEMINI_FEMALE_VOICES
