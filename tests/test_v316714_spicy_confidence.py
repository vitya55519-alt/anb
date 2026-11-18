"""V3.167.14 этап 8: тесты ростa уровня раскрепощённости и её подключения в промпт."""
import asyncio
import logging
from pathlib import Path

from sqlalchemy import select

from services.db import SessionLocal, init_db
from models.app_models import User
from models.relationship_models import UserCharacterRelationship
from services import spicy_confidence
from services.user_service import ensure_user

logging.getLogger('services.db').setLevel(logging.CRITICAL)

ROOT = Path(__file__).resolve().parents[1]
PHOTO_SRC = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
CHAT_SRC = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
CHAR_SRC = (ROOT / 'services' / 'character_service.py').read_text(encoding='utf-8')


def _seed(telegram_id: int, character_id: str = 'anna_01', level: int = 1, progress: int = 0):
    with SessionLocal() as s:
        u = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not u:
            u = User(telegram_id=str(telegram_id), name='Tester')
            s.add(u)
            s.flush()
        rel = s.scalar(select(UserCharacterRelationship).where(
            UserCharacterRelationship.user_id == u.id,
            UserCharacterRelationship.character_id == character_id,
        ))
        if not rel:
            rel = UserCharacterRelationship(user_id=u.id, character_id=character_id)
            s.add(rel)
        rel.spicy_confidence_level = level
        rel.spicy_confidence_progress = progress
        s.commit()


def _read(telegram_id: int, character_id: str = 'anna_01'):
    uid = ensure_user(telegram_id)
    with SessionLocal() as s:
        rel = s.scalar(select(UserCharacterRelationship).where(
            UserCharacterRelationship.user_id == uid,
            UserCharacterRelationship.character_id == character_id,
        ))
        return (rel.spicy_confidence_level, rel.spicy_confidence_progress) if rel else (None, None)


def _force_mode(on: bool):
    spicy_confidence.is_adult_mode = lambda tid: on


def _force_premium(on: bool):
    import services.access_service as acc
    acc.is_premium = lambda tid: on


def test_thresholds_map_progress_to_level():
    _force_mode(True)
    _force_premium(False)
    for points, expected in ((0, 1), (15, 2), (40, 3), (70, 4), (110, 5), (160, 6),
                             (220, 7), (300, 8), (400, 9), (550, 10)):
        _seed(2100 + expected, level=1, progress=points)
        lvl = spicy_confidence.apply_progress(2100 + expected, 'anna_01', kind='message')
        assert lvl == expected, (points, lvl, expected)


def test_photo_delta_is_three():
    _force_mode(True)
    _force_premium(False)
    _seed(2200, level=1, progress=0)
    spicy_confidence.apply_progress(2200, 'anna_01', kind='photo')
    _, progress = _read(2200)
    assert progress == 3


def test_level_never_decreases():
    _force_mode(True)
    _force_premium(False)
    _seed(2300, level=9, progress=500)
    lvl = spicy_confidence.apply_progress(2300, 'anna_01', kind='message')
    assert lvl == 9
    # Откатим progress — уровень всё равно не должен упасть ниже текущего.
    _seed(2300, level=9, progress=0)
    lvl = spicy_confidence.apply_progress(2300, 'anna_01', kind='message')
    assert lvl == 9


def test_premium_jumps_to_ten():
    _force_mode(True)
    _force_premium(True)
    _seed(2400, level=3, progress=0)
    lvl = spicy_confidence.apply_progress(2400, 'anna_01', kind='message')
    assert lvl == 10
    _force_premium(False)


def test_mode_off_returns_zero():
    _force_mode(False)
    _seed(2500, level=7, progress=200)
    assert spicy_confidence.current_level(2500, 'anna_01') == 0
    assert spicy_confidence.apply_progress(2500, 'anna_01', kind='message') == 0
    # Прогресс не изменился.
    assert _read(2500) == (7, 200)


def test_current_level_reads_without_write():
    _force_mode(True)
    _seed(2600, level=4, progress=100)
    assert spicy_confidence.current_level(2600, 'anna_01') == 4
    assert _read(2600) == (4, 100)


def test_chat_service_wires_message_delta():
    assert "from services import spicy_confidence" in CHAT_SRC
    assert "kind='message'" in CHAT_SRC
    assert "spicy_level=spicy_confidence.current_level(user_id, character_id)" in CHAT_SRC


def test_photo_service_wires_photo_delta_and_home_bypass():
    assert "from services import spicy_confidence" in PHOTO_SRC
    assert "kind='photo'" in PHOTO_SRC
    # Дом и «Раздеть» идут мимо SPICY_OUTFIT_LEVELS.
    assert "PRIVATE_SCENES = SEEDREAM_ADULT_SCENES | {'selfie'}" in PHOTO_SRC
    assert "if request.scene in PRIVATE_SCENES:" in PHOTO_SRC


def test_build_system_prompt_has_spicy_blocks():
    assert "spicy_level: int = 0" in CHAR_SRC
    for marker in ("ИГРИВАЯ РАСКРЕПОЩЁННОСТЬ", "ОТКРОВЕННАЯ РАСКРЕПОЩЁННОСТЬ",
                   "ГОРЯЧАЯ РАСКРЕПОЩЁННОСТЬ", "ПОЛНАЯ РАСКРЕПОЩЁННОСТЬ"):
        assert marker in CHAR_SRC, marker


def test_build_system_prompt_selects_block_by_level():
    from services.character_service import build_system_prompt, get_character
    char = get_character('anna_01')
    variants = {}
    for lvl in (1, 5, 8, 10):
        prompt = build_system_prompt(char, '', [], character_id='anna_01',
                                     spicy_level=lvl, explicit_mode=True)
        for marker in ("ИГРИВАЯ", "ОТКРОВЕННАЯ", "ГОРЯЧАЯ", "ПОЛНАЯ"):
            if marker in prompt:
                variants[lvl] = marker
                break
    assert variants == {1: "ИГРИВАЯ", 5: "ОТКРОВЕННАЯ", 8: "ГОРЯЧАЯ", 10: "ПОЛНАЯ"}
    # Уровень 0 (18+ выключен) не должен тащить спайси-маркеры.
    plain = build_system_prompt(char, '', [], character_id='anna_01')
    assert "РАСКРЕПОЩЁННОСТЬ" not in plain
