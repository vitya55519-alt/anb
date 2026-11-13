"""V3.149.0 — owner ТЗ of 12 Nov 2026: «Динамическое меню (Admin/User) и FSM-ввод».

1. The main menu is drawn per role. A plain user gets EXACTLY four rows — the two
   doors into the Mini App plus the two chat utilities. His whole kitchen (peach
   balance, Premium, the picture studio, partner program, promo codes, profile,
   admin panel) renders only when the id sits in ADMIN_TELEGRAM_IDS, in its own
   rows below the block.
2. ⏰ and 📝 are callback buttons that arm a state machine; the next plain text
   message is the answer («08:00», «8 утра», «в 14:30 купить цветы»), so nobody
   ever has to type /wake 08:00 again. The state lives in dialog_sessions, so a
   redeploy cannot drop a user mid-sentence, and 15 minutes of silence expires it
   back to the ordinary roleplay chat.
"""
import asyncio
import datetime as dt
import os
from pathlib import Path

os.environ.setdefault('TELEGRAM_TOKEN', '123456:test-fake-token-for-static-tests-only')
os.environ.setdefault('GEMINI_API_KEY', 'x')

import pytest
from aiogram import types
from models.app_models import Base, Reminder, User
from services.db import SessionLocal, engine

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
UI = (ROOT / 'services' / 'ui_lang.py').read_text(encoding='utf-8')
REMINDER_SRC = (ROOT / 'services' / 'reminder_service.py').read_text(encoding='utf-8')
APP = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')

APP_BASE = 'https://example.test'
APP_URL = f'{APP_BASE}/webapp'
ADMIN_ID = 914900001
USER_ID = 914900002


def _main(monkeypatch):
    import main
    monkeypatch.setattr(main, 'PUBLIC_BASE_URL', APP_BASE)
    monkeypatch.setattr(main, 'ADMIN_TELEGRAM_IDS', {ADMIN_ID})
    return main


def _user_row(tid: int) -> int:
    """Idempotent: the whole file shares one sqlite table."""
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        if not s.query(User).filter_by(telegram_id=str(tid)).first():
            s.add(User(telegram_id=str(tid), name='t'))
            s.commit()
    return tid


def _message(main, text: str, tid: int = USER_ID) -> types.Message:
    user = types.User(id=tid, is_bot=False, first_name='Test', language_code='ru')
    chat = types.Chat(id=tid, type='private')
    return types.Message(message_id=1, date=dt.datetime.now(dt.timezone.utc), chat=chat,
                        from_user=user, text=text)


def _callback(main, data: str, tid: int = USER_ID) -> types.CallbackQuery:
    msg = _message(main, '🧭 меню 👇', tid)
    user = types.User(id=tid, is_bot=False, first_name='Test', language_code='ru')
    return types.CallbackQuery(id='1', from_user=user, chat_instance='x', message=msg, data=data)


@pytest.fixture
def sent(monkeypatch):
    """Every bot bubble of the test lands in a list instead of Telegram."""
    out = []

    async def _answer(self, text=None, *a, **k):
        out.append(text)
        return None

    async def _noop(self, *a, **k):
        return None

    monkeypatch.setattr(types.Message, 'answer', _answer)
    monkeypatch.setattr(types.CallbackQuery, 'answer', _noop)
    return out


@pytest.fixture(autouse=True)
def _clean_state():
    """The wait lives in dialog_sessions and the scheduled rows in reminders.
    Only my own users get cleaned — the rest of the suite shares this database."""
    import main
    from sqlalchemy import select as _select
    for tid in (USER_ID, ADMIN_ID):
        main._UTILITY_WAIT.pop(tid, None)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        mine = _select(User.id).where(User.telegram_id.in_([str(USER_ID), str(ADMIN_ID)]))
        s.query(Reminder).filter(Reminder.user_id.in_(mine)).delete(synchronize_session=False)
        s.commit()
    yield
    for tid in (USER_ID, ADMIN_ID):
        main._UTILITY_WAIT.pop(tid, None)
    with SessionLocal() as s:
        mine = _select(User.id).where(User.telegram_id.in_([str(USER_ID), str(ADMIN_ID)]))
        s.query(Reminder).filter(Reminder.user_id.in_(mine)).delete(synchronize_session=False)
        s.commit()


# ── 1. the role split ──────────────────────────────────────────────────────
def test_a_plain_user_gets_the_doors_and_the_command_rows(monkeypatch):
    # V3.163.0: the four doors, then what the hidden slash commands used to
    # open — stories, collection, features, support and the donation post.
    main = _main(monkeypatch)
    rows = main.menu_markup(USER_ID).inline_keyboard
    assert [r[0].text for r in rows] == ['📱 Открыть приложение', '👯‍♀️ Галерея персонажей',
                                       '⏰ Будильник', '📝 Напоминание',
                                       '🎯 Истории', '✨ Возможности', '💖 Поддержать проект']
    assert [b.text for r in rows for b in r].count('🖼 Коллекция') == 1
    assert [b.text for r in rows for b in r].count('👥 Поддержка') == 1


def test_the_two_app_rows_are_mini_app_deep_links(monkeypatch):
    main = _main(monkeypatch)
    rows = main.menu_markup(USER_ID).inline_keyboard
    assert rows[0][0].web_app.url == APP_URL
    # the gallery must land on the character tab, not the chat tab
    assert rows[1][0].web_app.url == f'{APP_URL}?open=characters'
    assert "sp.get('open') === 'characters'" in APP


def test_the_utilities_are_callback_rows(monkeypatch):
    main = _main(monkeypatch)
    rows = main.menu_markup(USER_ID).inline_keyboard
    assert rows[2][0].callback_data == 'menu:alarm'
    assert rows[3][0].callback_data == 'menu:reminder'


def test_the_owner_kitchen_appears_only_for_his_id(monkeypatch):
    main = _main(monkeypatch)
    from services.ui_lang import menu_rows
    user = main.menu_markup(USER_ID).inline_keyboard
    user_keys = {b.text for r in user for b in r}
    admin_rows = main.menu_markup(ADMIN_ID).inline_keyboard
    admin_keys = [r[0].text for r in admin_rows]
    for kitchen in ('💰 Партнёрская программа', '🍳 Рецепт', '🎫 Концерт', '🎟 Промо', '👤 Профиль'):
        assert kitchen in admin_keys, kitchen
        assert kitchen not in user_keys, kitchen
    # the kitchen is split off below the block, in its own rows
    n = len(menu_rows(False))
    assert admin_rows[:n] == user
    assert len(admin_rows) > n


def test_the_reply_keyboard_uses_the_same_role_split(monkeypatch):
    main = _main(monkeypatch)
    user_rows = main.main_keyboard(False, USER_ID).keyboard
    assert [r[0].text for r in user_rows] == ['📱 Открыть приложение', '👯‍♀️ Галерея персонажей',
                                        '⏰ Будильник', '📝 Напоминание',
                                        '🎯 Истории', '✨ Возможности', '💖 Поддержать проект']
    admin_rows = main.main_keyboard(True, ADMIN_ID).keyboard
    assert len(admin_rows) > len(user_rows)


def test_no_menu_row_is_a_dead_button():
    """Every key of the menu resolves: a web_app route, or a handler that answers
    the label — the owner's kitchen must never fall into her roleplay brain."""
    from services.ui_lang import KB_LABELS, menu_rows
    routes = MAIN[MAIN.index('MENU_APP_ROUTES ='):MAIN.index('def _menu_button(')]
    callbacks = MAIN[MAIN.index('MENU_CALLBACK_ROUTES ='):MAIN.index('def _menu_button(')]
    for row in menu_rows(True) + menu_rows(False):
        for key in row:
            assert f"'{key}'" in routes or f"'{key}':" in callbacks, key
            assert key in KB_LABELS, key


# ── 2. the FSM ─────────────────────────────────────────────────────────────
def test_the_alarm_tap_arms_the_state(monkeypatch, sent):
    main = _main(monkeypatch)
    _user_row(USER_ID)
    monkeypatch.setattr(main, 'is_premium', lambda tid: True)
    asyncio.run(main.menu_alarm_cb(_callback(main, 'menu:alarm')))
    assert sent[-1].startswith('⏰ На какое время')
    assert main._utility_wait_of(USER_ID) == main.ALARM_WAIT
    assert not _pending_reminders(USER_ID), 'a tap must not create anything yet'


def test_the_next_plain_text_sets_the_alarm(monkeypatch, sent):
    main = _main(monkeypatch)
    _user_row(USER_ID)
    monkeypatch.setattr(main, 'is_premium', lambda tid: True)
    asyncio.run(main.menu_alarm_cb(_callback(main, 'menu:alarm')))
    before = len(sent)
    asyncio.run(main.utility_wait_answer(_message(main, '08:00')))
    assert sent[-1] == '🔔 Готово! Разбужу в 08:00.'
    assert len(sent) == before + 1
    assert main._utility_wait_of(USER_ID) == ''
    with SessionLocal() as s:
        row = s.query(Reminder).filter_by(active=True).order_by(Reminder.id.desc()).first()
        assert row.reminder_type == 'wake'
        assert (row.due_at_utc - dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)).total_seconds() > 0


def test_the_reminder_tap_wants_text_and_time(monkeypatch, sent):
    main = _main(monkeypatch)
    _user_row(USER_ID)
    monkeypatch.setattr(main, 'is_premium', lambda tid: True)
    asyncio.run(main.menu_reminder_cb(_callback(main, 'menu:reminder')))
    assert sent[-1].startswith('📝 О чём напомнить')
    assert main._utility_wait_of(USER_ID) == main.REMINDER_WAIT
    asyncio.run(main.utility_wait_answer(_message(main, 'в 14:30 купить цветы')))
    assert sent[-1] == '📝 Готово! Напомню в 14:30: купить цветы'
    with SessionLocal() as s:
        row = s.query(Reminder).order_by(Reminder.id.desc()).first()
        assert row.reminder_type == 'reminder'
        assert row.text == 'купить цветы'


@pytest.mark.parametrize('raw,expected', [
    ('08:00', (8, 0, 0)),
    ('8 утра', (8, 0, 0)),
    ('8 вечера', (20, 0, 0)),
    ('12 ночи', (0, 0, 0)),
    ('полдень', (12, 0, 0)),
    ('завтра в 9', (9, 0, 1)),
    ('8 pm', (20, 0, 0)),
])
def test_the_state_reads_a_plain_time(raw, expected):
    from services.reminder_service import parse_clock_text
    assert parse_clock_text(raw) == expected


def test_the_state_survives_a_redeploy(monkeypatch):
    main = _main(monkeypatch)
    _user_row(USER_ID)
    main._arm_utility_wait(USER_ID, main.ALARM_WAIT)
    # a fresh process only ever gets a new store object — the row is the state
    from services.dialog_store import DialogStore
    monkeypatch.setattr(main, '_UTILITY_WAIT', DialogStore('utility_wait'))
    assert main._utility_wait_of(USER_ID) == main.ALARM_WAIT


def test_silence_expires_the_state(monkeypatch):
    main = _main(monkeypatch)
    main._arm_utility_wait(USER_ID, main.ALARM_WAIT)
    main._UTILITY_WAIT[USER_ID] = {'state': main.ALARM_WAIT, 'asked_at': (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=20)).isoformat()}
    assert main._utility_wait_of(USER_ID) == ''


def test_unparsable_answer_keeps_the_state_and_stays_out_of_chat(monkeypatch, sent):
    main = _main(monkeypatch)
    _user_row(USER_ID)
    monkeypatch.setattr(main, 'is_premium', lambda tid: True)
    asyncio.run(main.menu_alarm_cb(_callback(main, 'menu:alarm')))
    asyncio.run(main.utility_wait_answer(_message(main, 'привет как дела')))
    assert 'не узнаю время' in sent[-1]
    assert main._utility_wait_of(USER_ID) == main.ALARM_WAIT


def test_the_paid_wall_still_gates_the_button(monkeypatch, sent):
    main = _main(monkeypatch)
    _user_row(USER_ID)
    monkeypatch.setattr(main, 'is_premium', lambda tid: False)
    monkeypatch.setattr(main, 'wake_trial_available', lambda tid: False)
    asyncio.run(main.menu_alarm_cb(_callback(main, 'menu:alarm')))
    assert 'Premium-функция' in sent[-1]
    assert main._utility_wait_of(USER_ID) == ''


def test_the_fsm_edge_is_registered_before_her_chat():
    tap = MAIN.index("F.data == 'menu:alarm'")
    fsm = MAIN.index('async def utility_wait_answer(')
    chat = MAIN.index('@dp.message(F.text)\n')
    assert tap < fsm < chat


def test_the_cancel_steps_out_of_the_state(monkeypatch, sent):
    main = _main(monkeypatch)
    _user_row(USER_ID)
    monkeypatch.setattr(main, 'is_premium', lambda tid: True)
    asyncio.run(main.menu_alarm_cb(_callback(main, 'menu:alarm')))
    asyncio.run(main.cancel_admin_edit(_message(main, '/cancel')))
    assert sent[-1] == 'отменил, возвращаюсь в обычный чат'
    assert main._utility_wait_of(USER_ID) == ''


def _pending_reminders(tid: int) -> bool:
    with SessionLocal() as s:
        user = s.query(User).filter_by(telegram_id=str(tid)).first()
        return bool(user and s.query(Reminder).filter_by(user_id=user.id, active=True).count())
