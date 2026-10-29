"""V3.91.0: Агата — tender goth, dirty from level 1 where intimacy is open
(Premium, or V3.92 «Девушка дня»)."""
import json
from pathlib import Path

from services.chat_service import (DIRTY_FROM_START, EXPLICIT_CHAT_RULE, TENDER_DIRTY_LINE,
                                   TENDER_TEASE_LINE, explicit_chat_line)

ROOT = Path(__file__).resolve().parents[1]
CID = 'agata_01'


def test_persona_and_references():
    p = json.loads((ROOT / 'data' / 'characters' / f'{CID}.json').read_text(encoding='utf-8'))
    assert p['is_adult'] and p['age'] >= 21
    assert 'art_style' not in p['visual_identity']
    for name in ('00_agata_canonical_face.png', '01_agata_canonical_look.png'):
        assert (ROOT / 'data' / 'references' / 'agata' / name).is_file(), name


def test_every_touchpoint_wired():
    files = ['services/character_card_service.py', 'services/webapp_service.py', 'services/relationship_engine.py',
             'services/photo_service.py', 'services/voice_service.py', 'services/voice_samples.py',
             'services/daily_life.py', 'services/retention_features_service.py', 'services/storylines_data.py',
             'services/custom_character_service.py']
    for path in files:
        assert CID in (ROOT / path).read_text(encoding='utf-8'), path


def test_explicit_from_level_one_where_intimacy_is_open():
    assert CID in DIRTY_FROM_START
    for stage in (None, 'stranger', 'acquaintance'):
        assert explicit_chat_line(stage, adult_confirmed=True, premium=True, dirty_start=True) == EXPLICIT_CHAT_RULE
        assert explicit_chat_line(stage, adult_confirmed=True, premium=False, dirty_start=True) == ''
        assert explicit_chat_line(stage, adult_confirmed=False, premium=True, dirty_start=True) == ''
    # the rest of the roster keeps the old ladder
    assert explicit_chat_line('stranger', adult_confirmed=True, premium=True) == ''


def test_tender_lines():
    assert 'с самого первого сообщения' in TENDER_DIRTY_LINE and 'нежн' in TENDER_DIRTY_LINE
    assert 'подробностей не расписывает' in TENDER_TEASE_LINE
