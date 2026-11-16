"""V3.167.1, пункт 2 (владелец): «он общается с Миланой, а кадр и пуш приходят
от Анны».

Выбор в Mini App раньше жил только в клиенте: `User.selected_character`
менялась лишь через меню бота, поэтому уровневое фото, кружок и утренний тизер
брали прошлый выбор или дефолт. Теперь каждое место, где приложение называет
героиню (открытие чата, её ход, его фото, тап по кадру, заказ медиа), записывает
её как последнюю активную — а rails читают ровно это.
"""
import asyncio
import logging
from pathlib import Path

import main
import services.chat_service as cs

logging.getLogger('main').setLevel(logging.CRITICAL)

MAIN = open(Path(main.__file__), encoding='utf-8').read()


def _body(marker: str) -> str:
    """Тело функции от её def до следующего top-level def — срезы по точным
    именам в 21-тысячном main.py живут недолго."""
    i = MAIN.index(marker)
    ends = [x for x in (MAIN.find('\nasync def ', i + 1), MAIN.find('\ndef ', i + 1)) if x != -1]
    return MAIN[i:min(ends) if ends else len(MAIN)]


def _tid(offset: int) -> int:
    return 559311 + offset


def _reset(tid: int, name: str) -> None:
    """Чистый старт: selected_character в общей тестовой базе живёт между
    запусками, поэтому перед проверкой её всегда обнуляем."""
    main.ensure_user(tid, name)
    main.update_user_settings(tid, selected_character='')
    main._user_character.pop(tid, None)


def test_the_app_choice_becomes_the_last_active_heroine():
    tid = _tid(1)
    _reset(tid, 'sync')
    assert main.get_user_character(tid) == main.CHARACTER_ID, 'без выбора — дефолт'
    main._remember_character(tid, 'kamila_01')
    assert main.get_user_character(tid) == 'kamila_01'
    # не только в памяти: перезапуск не должен возвращать всех к Анне
    main._user_character.pop(tid, None)
    assert main.get_user_character(tid) == 'kamila_01'


def test_the_same_heroine_does_not_write_the_row_every_turn():
    tid = _tid(2)
    _reset(tid, 'quiet')
    writes = []
    original = main.update_user_settings
    try:
        def counted(*a, **kw):
            writes.append((a, kw))
            return original(*a, **kw)

        main.update_user_settings = counted
        main._remember_character(tid, 'liza_01')
        first = len(writes)
        main._remember_character(tid, 'liza_01')
        main._remember_character(tid, '')
        assert first == 1, 'переключение пишется один раз'
        assert len(writes) == 1, 'тот же выбор и пустая строка — никаких UPDATE'
    finally:
        main.update_user_settings = original


def test_switching_girls_replaces_the_previous_one():
    tid = _tid(3)
    _reset(tid, 'switch')
    main._remember_character(tid, 'kamila_01')
    main._remember_character(tid, 'liza_01')
    main._user_character.pop(tid, None)
    assert main.get_user_character(tid) == 'liza_01'


def test_every_app_entry_point_that_names_her_records_her():
    # открытие чата, её ход (текст и голос идут через _webapp_chat_turn), его
    # фото, тап по кадру и заказ медиа — пять мест, где приложение называет её.
    assert MAIN.count('await asyncio.to_thread(_remember_character') == 5
    assert 'def _remember_character(' in MAIN
    assert '_remember_character' in _body('async def _webapp_chat_turn(')
    assert '_remember_character' in _body('async def _webapp_api_chat_start(')
    assert '_remember_character' in _body('async def _webapp_api_chat_media(')
    assert '_remember_character' in _body('async def _webapp_api_chat_photo(')
    assert '_remember_character' in _body('async def _webapp_api_photo_action(')


def test_photo_rails_take_the_character_of_the_event_not_the_default():
    # V3.167.1: церемония уровня знает, кто в ней участвует, и кадр идёт ей.
    assert 'character_id: str | None = None' in _body('async def _run_photo_background(')
    assert 'character_id = character_id or get_user_character(telegram_id)' in MAIN
    ceremony = ' '.join(_body('async def _on_relationship_stage_up(').split())
    assert "special[1], 'story', character_id=character_id)" in ceremony
    assert "PhotoRequest(scene='selfie', mood='romantic'), 'story', character_id=character_id)" in ceremony
    assert '_run_photo_background(chat_id, telegram_id, request, delivery_type, charge=charge, ' \
           'amount=amount, product=product, spend_undress_credit=spend_undress_credit, ' \
           'spend_explicit_peaches=spend_explicit_peaches, character_id=character_id)' in MAIN
