"""V3.167.14 этап 8: тесты ростa уровня раскрепощённости и её подключения в промпт."""
import asyncio
import logging
from pathlib import Path

import pytest
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


@pytest.fixture
def _force_mode(monkeypatch):
    def set_mode(on: bool):
        monkeypatch.setattr(spicy_confidence, 'is_adult_mode', lambda tid: on)
    return set_mode


@pytest.fixture
def _force_premium(monkeypatch):
    import services.access_service as acc

    def set_premium(on: bool):
        monkeypatch.setattr(acc, 'is_premium', lambda tid: on)
    return set_premium


def test_thresholds_map_progress_to_level(_force_mode, _force_premium):
    _force_mode(True)
    _force_premium(False)
    for points, expected in ((0, 1), (15, 2), (40, 3), (70, 4), (110, 5), (160, 6),
                             (220, 7), (300, 8), (400, 9), (550, 10)):
        _seed(2100 + expected, level=1, progress=points)
        lvl = spicy_confidence.apply_progress(2100 + expected, 'anna_01', kind='message')
        assert lvl == expected, (points, lvl, expected)


def test_photo_delta_is_three(_force_mode, _force_premium):
    _force_mode(True)
    _force_premium(False)
    _seed(2200, level=1, progress=0)
    spicy_confidence.apply_progress(2200, 'anna_01', kind='photo')
    _, progress = _read(2200)
    assert progress == 3


def test_level_never_decreases(_force_mode, _force_premium):
    _force_mode(True)
    _force_premium(False)
    _seed(2300, level=9, progress=500)
    lvl = spicy_confidence.apply_progress(2300, 'anna_01', kind='message')
    assert lvl == 9
    # Откатим progress — уровень всё равно не должен упасть ниже текущего.
    _seed(2300, level=9, progress=0)
    lvl = spicy_confidence.apply_progress(2300, 'anna_01', kind='message')
    assert lvl == 9


def test_premium_jumps_to_ten(_force_mode, _force_premium):
    _force_mode(True)
    _force_premium(True)
    _seed(2400, level=3, progress=0)
    lvl = spicy_confidence.apply_progress(2400, 'anna_01', kind='message')
    assert lvl == 10
    _force_premium(False)


def test_mode_off_returns_zero(_force_mode):
    _force_mode(False)
    _seed(2500, level=7, progress=200)
    assert spicy_confidence.current_level(2500, 'anna_01') == 0
    assert spicy_confidence.apply_progress(2500, 'anna_01', kind='message') == 0
    # Прогресс не изменился.
    assert _read(2500) == (7, 200)


def test_current_level_reads_without_write(_force_mode):
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
    # V3.167.17: уровни раскрепощённости применяются ко ВСЕМ сценам в режиме 18+.
    assert "spicy_level = spicy_confidence.current_level(telegram_id, character_id)" in PHOTO_SRC
    # Explicit outfits are pinned only for ordinary photos; private scenes still bypass spicy styling.
    assert "ordinary_style = _ordinary_style_request(request, get_relationship_level(telegram_id, character_id))" in PHOTO_SRC
    assert "pinned_outfit = bool(ordinary_style and (request.clothing or request.pack_outfits))" in PHOTO_SRC
    assert "if spicy_level > 0 and spicy_level <= 10 and not pinned_outfit:" in PHOTO_SRC


def test_build_system_prompt_has_spicy_blocks():
    assert "spicy_level: int = 0" in CHAR_SRC
    # Речь и названия уровней живут в одном месте — services/spicy_confidence.py.
    assert "from services import spicy_confidence" in CHAR_SRC
    assert "spicy_confidence.level_speech(spicy_level)" in CHAR_SRC


def test_build_system_prompt_selects_block_by_level():
    from services.character_service import build_system_prompt, get_character
    from services.spicy_confidence import SPICY_LEVEL_NAMES
    char = get_character('anna_01')
    for lvl in range(1, 11):
        prompt = build_system_prompt(char, '', [], character_id='anna_01',
                                     spicy_level=lvl, explicit_mode=True)
        assert f"РАСКРЕПОЩЁННОСТЬ · УРОВЕНЬ {lvl}/10 · {SPICY_LEVEL_NAMES[lvl]}" in prompt, lvl
        assert "НЕ ломаешься" in prompt or "отказ" in prompt.lower(), lvl
    # Уровень 0 (18+ выключен) не должен тащить спайси-блок.
    plain = build_system_prompt(char, '', [], character_id='anna_01')
    assert "РАСКРЕПОЩЁННОСТЬ" not in plain


def test_level_names_are_the_owners_final_ladder():
    from services.spicy_confidence import SPICY_LEVEL_NAMES
    assert SPICY_LEVEL_NAMES == {
        1: "Игра", 2: "Флирт", 3: "Искушение", 4: "Желание", 5: "Пошлость",
        6: "Грязный разговор", 7: "Без стеснения", 8: "Жар",
        9: "Эксперименты", 10: "Бесстыдство",
    }


def test_first_level_already_leads_to_sex():
    # Владелец 18.11: с 1-го уровня она сама ведёт к сексу и никогда не отказывает.
    from services.spicy_confidence import level_speech
    speech = " ".join(level_speech(1))
    assert "САМА сводишь разговор к сексу" in speech
    assert "НЕ ломаешься" in speech and "НЕ отказываешь" in speech


def test_snapshot_shape_for_the_card(_force_mode, _force_premium):
    _force_mode(True)
    _force_premium(False)
    _seed(2700, level=3, progress=45)
    snap = spicy_confidence.snapshot(2700, 'anna_01')
    assert snap["level"] == 3
    assert snap["name"] == "Искушение"
    assert snap["next_name"] == "Желание"
    assert snap["max_level"] == 10
    assert snap["is_max"] is False
    assert snap["points_left"] == 70 - 45
    # 45 очков из отрезка 40→70 = 17% пройдено.
    assert snap["percent"] == 17
    assert snap["message_delta"] == 1 and snap["photo_delta"] == 3


def test_snapshot_at_max_level_is_full(_force_mode, _force_premium):
    _force_mode(True)
    _force_premium(False)
    _seed(2800, level=10, progress=600)
    snap = spicy_confidence.snapshot(2800, 'anna_01')
    assert snap["is_max"] is True
    assert snap["percent"] == 100
    assert snap["points_left"] == 0
    assert snap["next_name"] is None
    assert snap["name"] == "Бесстыдство"


def test_snapshot_none_when_mode_off(_force_mode):
    _force_mode(False)
    _seed(2900, level=4, progress=50)
    assert spicy_confidence.snapshot(2900, 'anna_01') is None


def test_card_is_wired_in_api_and_frontend():
    main_src = (ROOT / 'main.py').read_text(encoding='utf-8')
    app_src = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
    # API отдаёт снимок вместе с обычной карточкой.
    assert "spicy = spicy_confidence.snapshot(telegram_id, character_id)" in main_src
    assert "snap['spicy'] = spicy" in main_src
    # Фронт в 18+ режиме рисует раскрепощённость и не трогает романскую ветку.
    assert "if (j.spicy) { showLevelSheet(spicySheetHtml(j.spicy)); return; }" in app_src
    assert "function spicySheetHtml(s)" in app_src
    assert "function showLevelSheet(html)" in app_src


def test_spicy_card_has_no_relationship_meters():
    app_src = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
    body = app_src[app_src.index('function spicySheetHtml(s)'):app_src.index('function showLevelSheet(html)')]
    # Полос отношений/доверия/страсти в 18+ карточке быть не должно.
    for banned in ('Отношения', 'Доверие', 'Страсть', 'Сейчас между вами', 'из 100'):
        assert banned not in body, banned

