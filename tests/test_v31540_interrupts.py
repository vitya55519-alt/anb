"""V3.154.0: owner ТЗ (Фогель, Модуль 2) — «Перебивки» (QTE).

Что проверяем:
1. события привязаны к её положению: у занятой — ключ и видеозвонок, у мачехи —
   отец на лестнице, у свободной — свет и курьер; «с тобой» и «жена» — тишина;
2. у каждого события ровно три хода, и третий (самый смелый) — за персики;
   подписи кнопок и его действие — без звёздочек и без ремарок;
3. счётчик: не раньше INTERRUPT_MIN_LEVEL, раз в 10–15 его живых сообщений, не
   чаще INTERRUPT_MAX_PER_DAY раз в сутки на пару; карточка читается один раз;
4. ответить можно только на последнее событие пары (плашку нельзя оплатить
   дважды), старая плашка отказывает;
5. доставка: Telegram и Mini App берут карточку из одного pending-слона, Premium
   не видит цены, пустой ответ возвращает персики;
6. блок [EVENT ACTIVE] держит её в сцене и запрещает упоминать кнопки.
"""
import random
import time
from pathlib import Path

from config import (INTERRUPTS_ENABLED, INTERRUPT_EVERY_MAX, INTERRUPT_EVERY_MIN,
                    INTERRUPT_MAX_PER_DAY, INTERRUPT_MIN_LEVEL,
                    INTERRUPT_PEACH_COST)
from models.app_models import Base
from services import interrupt_service as qz
from services.db import engine

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
APP = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def _uid():
    Base.metadata.create_all(engine)
    return random.randint(4_000_000_000, 4_999_999_999)


# ── 1. события по её положению ────────────────────────────────────────────

def test_pools_follow_her_situation():
    assert set(qz.POOLS) == {'taken', 'stepmom', 'free'}
    assert [e.id for e in qz.POOLS['taken']] == ['key', 'call']
    assert [e.id for e in qz.POOLS['stepmom']] == ['stairs']
    assert [e.id for e in qz.POOLS['free']] == ['lights', 'courier']
    # a married/boyfriend girl can be caught, a single one cannot
    assert qz.TAKEN == ('mar_married', 'mar_boyfriend', 'mar_open')
    assert qz.FREE == ('mar_single', 'mar_divorced')
    # «with you» / «wife»: there is nobody to fear — the event would break the story
    assert qz.SILENT == ('mar_with_you', 'mar_wife')


def test_the_taken_events_name_the_partner():
    for event in qz.POOLS['taken']:
        assert '{partner}' in event.ru
        assert '{partner}' in event.en
    for event in list(qz.POOLS['stepmom']) + list(qz.POOLS['free']):
        assert '{partner}' not in event.ru


# ── 2. три хода, третий — платный ─────────────────────────────────────────

def test_every_event_offers_three_choices_and_prices_the_bold_one():
    for event in [e for pool in qz.POOLS.values() for e in pool]:
        assert len(event.choices) == 3, event.id
        assert [c.paid for c in event.choices] == [False, False, True], event.id
        for c in event.choices:
            assert c.ru and c.en and c.act_ru and c.act_en
            # the owner's anti-RP rule: his action is plain first person, no stage directions
            assert '*' not in c.ru and '*' not in c.act_ru
            assert '*' not in c.en and '*' not in c.act_en
            assert not c.act_ru.startswith('(') and not c.act_en.startswith('(')
    assert qz.PAID_CHOICE == 2


def test_button_labels_fit_telegram():
    """Telegram cuts a button at 64 characters — and the price suffix rides on
    the end of the boldest one, so the labels have to leave room for it."""
    for event in [e for pool in qz.POOLS.values() for e in pool]:
        for c in event.choices:
            for label in (c.ru, c.en):
                assert len(label) + 12 <= 64, label


def test_choice_lookup_refuses_nonsense():
    assert qz.choice_of('key', 0) is not None
    assert qz.choice_of('key', 3) is None
    assert qz.choice_of('key', -1) is None
    assert qz.choice_of('nope', 0) is None
    assert qz.action_text('key', 'x') == ''
    assert qz.get('nope') is None


def test_the_paid_price_is_configured_and_peaches_are_bought_only():
    assert qz.price() == INTERRUPT_PEACH_COST == 50
    # main.py charges bought peaches only, like every other peach product
    assert 'spend_peaches, tid, interrupt_service.price(), paid_only=True' in MAIN
    assert 'spend_peaches(telegram_id, interrupt_service.price(), paid_only=True)' in MAIN


# ── 3. счётчик ────────────────────────────────────────────────────────────

def test_the_counter_needs_level_status_a_wait_and_a_slot(monkeypatch):
    Base.metadata.create_all(engine)
    tid, cid = _uid(), 'anna'
    monkeypatch.setattr(qz, 'INTERRUPTS_ENABLED', True)
    monkeypatch.setattr(qz, 'INTERRUPT_MIN_LEVEL', 3)
    monkeypatch.setattr(qz, 'INTERRUPT_EVERY_MIN', 3)
    monkeypatch.setattr(qz, 'INTERRUPT_EVERY_MAX', 3)
    monkeypatch.setattr(qz, 'INTERRUPT_MAX_PER_DAY', 1)
    monkeypatch.setattr(qz, 'status_group', lambda *a, **k: 'taken')
    # below the level gate she is not «secret» yet — no event
    assert qz.note_turn(tid, cid, 2) is None
    fired = [qz.note_turn(tid, cid, 5) for _ in range(3)]
    assert fired[:2] == [None, None]
    assert fired[2] in ('key', 'call')
    assert qz.take_pending(tid, cid) == fired[2]
    # the card is read once: the bot and the app must not both draw it
    assert qz.take_pending(tid, cid) == ''
    # today's slot is spent — the next window re-rolls without firing
    for _ in range(3):
        assert qz.note_turn(tid, cid, 5) is None


def test_a_disabled_module_and_a_silent_status_never_fire(monkeypatch):
    Base.metadata.create_all(engine)
    tid, cid = _uid(), 'anna'
    monkeypatch.setattr(qz, 'INTERRUPTS_ENABLED', False)
    monkeypatch.setattr(qz, 'status_group', lambda *a, **k: 'taken')
    monkeypatch.setattr(qz, 'INTERRUPT_EVERY_MIN', 1)
    monkeypatch.setattr(qz, 'INTERRUPT_EVERY_MAX', 1)
    assert all(qz.note_turn(tid, cid, 9) is None for _ in range(4))
    monkeypatch.setattr(qz, 'INTERRUPTS_ENABLED', True)
    monkeypatch.setattr(qz, 'status_group', lambda *a, **k: '')
    assert all(qz.note_turn(tid, cid, 9) is None for _ in range(4))


def test_the_daily_cap_and_the_wait_come_from_config():
    assert INTERRUPTS_ENABLED is True
    assert 1 <= INTERRUPT_MIN_LEVEL <= 10
    assert 2 <= INTERRUPT_EVERY_MIN <= INTERRUPT_EVERY_MAX <= 50
    assert 1 <= INTERRUPT_MAX_PER_DAY <= 5


def test_a_stale_card_is_not_delivered(monkeypatch):
    Base.metadata.create_all(engine)
    tid, cid = _uid(), 'anna'
    qz._pending[(tid, cid)] = {'id': 'key', 'at': time.monotonic() - qz._PENDING_TTL_SECONDS - 1}
    assert qz.take_pending(tid, cid) == ''


# ── 4. ответить можно только на последнее событие ─────────────────────────

def test_a_pair_answers_its_newest_event_once(monkeypatch):
    Base.metadata.create_all(engine)
    tid, cid = _uid(), 'anna'
    monkeypatch.setattr(qz, 'INTERRUPT_EVERY_MIN', 1)
    monkeypatch.setattr(qz, 'INTERRUPT_EVERY_MAX', 1)
    monkeypatch.setattr(qz, 'INTERRUPT_MAX_PER_DAY', 5)
    monkeypatch.setattr(qz, 'status_group', lambda *a, **k: 'taken')
    first = qz.note_turn(tid, cid, 9)
    assert first
    assert qz.can_pick(tid, cid, first) is True
    # a plate of an event this pair never got is not answerable
    assert qz.can_pick(tid, cid, 'lights') is False
    qz.mark_resolved(tid, cid, first)
    # a second tap on the same plate is refused
    assert qz.can_pick(tid, cid, first) is False
    second = qz.note_turn(tid, cid, 9)
    assert second
    assert qz.can_pick(tid, cid, second) is True


# ── 5. карточка ───────────────────────────────────────────────────────────

def test_the_card_carries_only_canned_text_and_a_price_for_the_bold_one():
    Base.metadata.create_all(engine)
    tid, cid = _uid(), 'anna'
    card = qz.card(tid, cid, 'key', 'ru')
    assert card['id'] == 'key' and card['emoji']
    assert 'ВНЕЗАПНО' in card['text'] and '{' not in card['text']
    assert [c['paid'] for c in card['choices']] == [False, False, True]
    assert [c['price'] for c in card['choices']] == [0, 0, INTERRUPT_PEACH_COST]
    assert [c['n'] for c in card['choices']] == [0, 1, 2]
    en = qz.card(tid, cid, 'key', 'en')
    assert 'SUDDENLY' in en['text']
    # any other UI language takes the English event text (wardrobe/gifts rule)
    assert 'SUDDENLY' in qz.card(tid, cid, 'key', 'es')['text']
    assert qz.card(tid, cid, 'nope', 'ru') == {}


def test_the_scene_note_keeps_her_inside_the_scene():
    note = qz.scene_note('key', 2, 'anna', 'ru')
    assert note.startswith('[EVENT ACTIVE]')
    assert 'Его ответ на событие' in note
    assert 'Оставайся в сцене' in note
    assert 'не упоминай кнопки' in note
    # his chosen action rides in the note, in Russian
    assert qz.action_text('key', 2, 'ru') in note
    en = qz.scene_note('key', 2, 'anna', 'en')
    assert en.startswith('[EVENT ACTIVE]') and 'Stay inside the scene' in en
    assert qz.scene_note('nope', 0, 'anna', 'ru') == ''


# ── 6. доставка в обоих слоях ─────────────────────────────────────────────

def test_only_her_live_replies_spending_the_counter():
    block = CHAT[CHAT.index("from services import interrupt_service") - 200:]
    block = block[:block.index('def ', block.index('interrupt_service'))]
    assert 'if not scene and (r.text or \'\').strip():' in CHAT
    assert 'interrupt_service.note_turn' in block
    # the purchase reaction / a push must not eat what he just paid for
    assert 'gift_shop_service.tick(user_id, character_id)' in CHAT


def test_both_layers_draw_the_card_and_refund_an_empty_scene():
    tg = MAIN[MAIN.index('async def send_answer'):]
    tg = tg[:tg.index('async def _send_draft_plate')]
    assert 'interrupt_service.take_pending' in tg
    assert '_send_interrupt_card(message, qte)' in tg
    app = MAIN[MAIN.index("payload = {'ok': True, 'reply': answer}"):]
    app = app[:app.index('# V3.140.0')]
    assert "payload['interrupt'] = qte" in app
    assert "qte['free'] = telegram_id in ADMIN_TELEGRAM_IDS or is_premium(telegram_id)" in app
    # one event, one answer — the buttons go away on the tap
    assert "F.data.startswith('qte:pick:')" in MAIN
    assert "'/webapp/api/chat/interrupt', _webapp_api_chat_interrupt" in MAIN
    # the paid plate is silent until she actually answers
    assert MAIN.count('add_peaches, tid, interrupt_service.price()') == 1
    assert MAIN.count('add_peaches, telegram_id, interrupt_service.price()') == 1


def test_the_app_renders_the_plate_and_sends_his_choice():
    assert 'function interruptPlate(q)' in APP
    assert "async function pickInterrupt(id, n, btn)" in APP
    assert "'/webapp/api/chat/interrupt?init_data='" in APP
    assert 'data-qte=' in APP and 'data-qn=' in APP
    assert "j.interrupt && j.interrupt.id" in APP
    # his tap is not lost: his action goes into the dialog as his bubble
    assert "if (j.user_text) box.insertAdjacentHTML('beforeend', chatBubble({ role: 'user'" in APP
    # a Premium man never sees a price tag he does not pay
    assert "const paid = !!c.paid && !q.free && Number(c.price) > 0;" in APP
    assert 'r.status === 402' in APP[APP.index('async function pickInterrupt'):]
