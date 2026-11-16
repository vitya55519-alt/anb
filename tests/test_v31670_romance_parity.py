# V3.167.0 §4 (ТЗ Фогеля, «одна дверь — романтика»).
#
# Режим «Романтика и флирт» был единственным, куда механика готовой карточки
# не дошла: сид писал все строки mode='spicy', поэтому в тёплом режиме
# opening() возвращала None и чат стартовал старой сценой из OPENING_SCENES —
# без чипов, без одного тапа, с платным LLM на старте. Романтика получила свой
# набор: те же 15 бытовых ситуаций, те же два хода под ними, но ни одна строка
# не обещает кадр. Дверь в 18+ остаётся одна — кнопка режима, а не первое
# сообщение.

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from models.app_models import CharacterGreeting
from services import greeting_service as gs
from services.db import SessionLocal

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')

NUDE = ('без белья', 'раздет', 'нюдс', 'секс', 'труси', 'бюстг', 'голый', 'обнаж', 'наг')


@pytest.fixture(autouse=True)
def _clean_table():
    with SessionLocal() as s:
        s.execute(delete(CharacterGreeting))
        s.commit()
    yield
    with SessionLocal() as s:
        s.execute(delete(CharacterGreeting))
        s.commit()


class _NoFlag:
    """Подмена одноразового маркера заливки: тест проверяет саму заливку и её
    защиту по таблице, а не то, успела ли она уже пройти в этом процессе."""

    def get(self, _key):
        return None

    def __setitem__(self, _key, _value):
        pass


def _fill(monkeypatch):
    monkeypatch.setattr(gs, '_romance_done', _NoFlag())
    return gs.sync_romance_seed()


def _rows():
    with SessionLocal() as s:
        return list(s.scalars(select(CharacterGreeting)))


def test_the_warm_set_is_fifteen_cards_of_one_line_and_two_moves():
    assert len(gs.SEED_ROMANCE) == 15
    for text, chips in gs.SEED_ROMANCE:
        assert text.rstrip().endswith('?'), text
        assert 30 <= len(text) <= 300, text
        assert len(chips) == 2, text
        assert all(2 < len(c) <= 32 for c in chips), chips
    assert len({t for t, _ in gs.SEED_ROMANCE}) == 15
    assert len({c for _, ch in gs.SEED_ROMANCE for c in ch}) == 30


def test_no_warm_card_borrows_the_door_to_18():
    blob = ' '.join(f'{t} {" ".join(ch)}' for t, ch in gs.SEED_ROMANCE).casefold()
    for word in NUDE:
        assert word not in blob, word
    # ни один чип не просит кадр: в тёплом режиме тап = обычное сообщение
    for word in ('фото', 'скинь', 'покажи'):
        assert word not in blob, word


def test_the_warm_fill_lands_once_and_only_in_normal_mode(monkeypatch):
    assert _fill(monkeypatch) == 15
    assert gs.sync_romance_seed() == 0            # второй прогон: строки уже есть
    rows = _rows()
    assert len(rows) == 15
    assert all(r.mode == 'normal' and r.character_id == 'all' for r in rows)
    # кадр за ними не стоит: ни скрытого промпта, ни реплики перед кадром
    assert all(not r.image_prompt and not r.reply_text for r in rows)
    assert all(len(json.loads(r.buttons_json)) == 2 for r in rows)


def test_the_warm_fill_never_touches_what_he_wrote(monkeypatch):
    gid = gs.create('anna_01', 'normal', 'Моя тёплая карточка', ['Привет'])
    gs.create('all', 'spicy', 'Его spicy-строка', ['Покажи'], image_prompt='bedroom, lace lingerie')
    assert _fill(monkeypatch) == 15
    rows = _rows()
    assert len(rows) == 17
    assert next(r for r in rows if r.id == gid).message_text == 'Моя тёплая карточка'
    assert next(r for r in rows if r.mode == 'spicy').message_text == 'Его spicy-строка'


def test_the_spicy_resync_leaves_the_warm_rows_alone(monkeypatch):
    _fill(monkeypatch)
    before = {r.id for r in _rows() if r.mode == 'normal'}
    monkeypatch.setattr(gs, '_sync_done', _NoFlag())
    gs.sync_universal_seed()
    assert {r.id for r in _rows() if r.mode == 'normal'} == before
    assert len([r for r in _rows() if r.mode == 'spicy' and r.character_id == 'all']) == 15


def test_a_woman_without_her_own_warm_card_uses_the_universal_one():
    assert gs.ensure_seed() == 36
    warm = asyncio.run(gs.opening('anna_01', spicy=False))
    assert warm and warm['starter'] is False and not warm['reply']
    assert warm['text'].rstrip().endswith('?') and len(warm['buttons']) == 2
    spicy = asyncio.run(gs.opening('anna_01', spicy=True))
    assert 'панорамного окна' in spicy['text'] and spicy['starter'] is False


def test_the_chat_start_stops_selling_the_frame_in_the_warm_mode():
    start = MAIN[MAIN.index('async def _webapp_api_chat_start'):MAIN.index('def _chat_opening_spicy')]
    assert "'undress_price': EXPLICIT_PHOTO_PEACH_COST if _spicy else 0" in start
    # и сам тап по чипу в тёплом режиме не доходит до бесплатного кадра
    tap = MAIN[MAIN.index('async def _starter_frame_turn'):MAIN.index('async def _starter_frame_turn') + 4000]
    assert 'if not _chat_opening_spicy(telegram_id):' in tap


def test_the_adult_safety_block_is_not_baked_into_the_warm_prompt():
    # ADULT_SAFETY живёт только в adult-сцене и в стартовом кадре: одно это
    # присваивание на весь генератор, и стоит оно под тем самым условием.
    # У романтики нет ни adult-сцены, ни старта (её строки без image_prompt),
    # значит кадр рисуется в обычном цензурном конверте.
    assert PHOTO.count('safety = ADULT_SAFETY') == 1
    block = PHOTO[PHOTO.index('if adult_scene or starter:'):]
    assert 'safety = ADULT_SAFETY' in block[:700]
