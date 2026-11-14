"""V3.165.0 (#107, владелец): «Раздеть» — один раз в сутки, и второй кадр она
предлагает сама.

ТЗ: «„Раздеть": кап один раз в сутки, цена 300 🍑 … она отвечает дословно в
духе „я уже голая" и СРАЗУ сама предлагает новый кадр (другая сцена или ракурс),
а не просто констатирует наготу и не „раздевается ещё сильнее"».

Про деньги важно: тап внутри окна ничего не рисует и не списывает — платёж
происходит ровно один раз за сутки, а дальше продаём следующий кадр по обычной
цене откровенного кадра.
"""
import os
import time
import uuid
from pathlib import Path

import pytest

from models.app_models import Base
from services.db import engine

os.environ.setdefault('TELEGRAM_TOKEN', '123456:fake-token')
os.environ.setdefault('OPENAI_API_KEY', 'fake')

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')

ACTION = MAIN[MAIN.index('async def _webapp_api_photo_action('):MAIN.index('async def _webapp_media_scene(')]
GATE = ACTION[ACTION.index('def _gate():'):ACTION.index('uid, err, pay = await asyncio.to_thread(_gate)')]
ALREADY = ACTION[ACTION.index("if pay == 'already':"):ACTION.index('    try:', ACTION.index("if pay == 'already':"))]
OFFER = INDEX[INDEX.index('function nudeFrameOffer('):INDEX.index('async function speakLazy(')]


def _app():
    """main собирает OpenAI-клиенты прямо при импорте, а windows-переменная
    NO_PROXY со «[::1]» внутри ломает httpx (InvalidURL). Прокси-переменные
    снимаем только на время импорта и сразу возвращаем."""
    saved = {k: os.environ.pop(k) for k in ('NO_PROXY', 'no_proxy') if k in os.environ}
    try:
        import main
        return main
    finally:
        os.environ.update(saved)


def _tid() -> int:
    return 9_700_000_000 + uuid.uuid4().int % 999_999


@pytest.fixture
def store():
    from services import undress_nudity
    Base.metadata.create_all(engine)
    return undress_nudity


def test_the_window_is_one_day(store):
    assert store.WINDOW_SECONDS == 24 * 3600


def test_a_fresh_reveal_marks_her_nude(store):
    tg, other = _tid(), _tid()
    assert not store.is_nude(tg, 'vika_01')
    store.mark(tg, 'vika_01')
    assert store.is_nude(tg, 'vika_01')
    # состояние привязано к героине: в диалоге с другой она ещё одета
    assert not store.is_nude(tg, 'anna_01')
    assert not store.is_nude(other, 'vika_01')


def test_the_window_closes_after_a_day(store):
    tg = _tid()
    store._store[int(tg)] = {'vika_01': int(time.time()) - store.WINDOW_SECONDS - 30}
    assert not store.is_nude(tg, 'vika_01')


def test_garbage_in_the_session_is_not_nudity(store):
    tg = _tid()
    store._store[int(tg)] = {'vika_01': 'not-a-time'}
    assert not store.is_nude(tg, 'vika_01')


def test_the_cap_is_checked_after_the_kitchen_and_before_the_money():
    # «Раздеть» начинается с админской обхода, а кап стоит сразу за ним
    undress_gate = GATE[GATE.index("if not is_adult_confirmed(telegram_id):"):]
    assert undress_gate.index('if admin:') < undress_gate.index('undress_nudity.is_nude(telegram_id, character_id)')
    # 18+ он подтверждает как раньше, а цена — только там, где раздеваться ещё есть
    assert undress_gate.index('if not is_adult_confirmed(telegram_id):') < undress_gate.index('undress_nudity.is_nude')
    assert undress_gate.index('undress_nudity.is_nude') < undress_gate.index('get_paid_peaches(telegram_id) < UNDRESS_PEACH_COST')
    assert "return uid, None, 'already'" in undress_gate
    assert undress_gate.index("return uid, None, 'already'") < undress_gate.index("return uid, None, 'peaches'")


def test_the_repeat_tap_renders_nothing_and_spends_nothing():
    for banned in ('_spicyapi_render', 'save_chat_media', 'record_generation', 'spend_peaches',
                   'undress_credits', 'note_today'):
        assert banned not in ALREADY, banned
    assert 'save_message' in ALREADY and 'UNDRESS_ALREADY_LINES' in ALREADY
    assert "'already_nude': True" in ALREADY


def test_the_first_reveal_opens_the_window():
    deliver = ACTION[ACTION.index('def _deliver():'):]
    assert 'undress_nudity.mark(telegram_id, character_id)' in deliver
    assert deliver.index("if action == 'undress':") < deliver.index('undress_nudity.mark')


def test_every_already_line_says_nudity_and_offers_a_new_frame():
    lines = _app().UNDRESS_ALREADY_LINES
    assert len(lines) >= 4
    for line in lines:
        assert any(w in line for w in ('гола', 'без всего')), line
        assert 'кадр' in line, line
        assert 'ракурс' in line or 'сцен' in line, line
        # никаких ремарок в звёздочках и никакого «раздеваюсь ещё сильнее»
        assert '*' not in line, line
        for stale in ('ещё сильнее', 'подписк', 'Premium', 'персик', '🍑'):
            assert stale not in line, f'{stale} in {line!r}'


def test_the_app_puts_the_next_frame_one_tap_under_her_line():
    assert 'if (j.already_nude) nudeFrameOffer(box);' in INDEX
    assert "openFeature('hot')" in OFFER
    # цену берём из таблицы /me, в разметке числа нет
    assert "L.nude_new_frame(PP('explicit'))" in OFFER
    assert '300 🍑' not in OFFER
    assert "nude_new_frame: n => '🔥 Новый кадр · ' + peachNum(n) + ' 🍑'," in INDEX
    assert "nude_new_frame: n => '🔥 New frame · ' + peachNum(n) + ' 🍑'," in INDEX
