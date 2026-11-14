"""V3.165.0 (задача #101): режим «После полуночи» — флаг аккаунта, и он обязан
доходить до промпта Mini App, а не только до ботовской обработки.

Что проверяют эти тесты — три места, где такой флаг обычно теряется:

* витрина приложения (`api_me`) показывает режим и дневный потолок без Premium;
* тап по карточке пишет флаг и время, поэтому каждый уже начатый диалог
  получает одну тонкую строку «режим изменён», а история не обнуляется;
* счётчик откровенных сообщений тратится только на настоящие откровенные
  реплики, подсказка мягкая, а строка «на сегодня всё» звучит один раз в сутки.

Заодно статикой — что бот больше не требует Premium за режим и что в приложении
не осталось второго переключателя.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from config import EXPLICIT_MSGS_PER_DAY
from models.app_models import Base, Message, User
from services import explicit_mode as xm
from services.db import SessionLocal, engine

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _fresh_user(**cols) -> int:
    Base.metadata.create_all(engine)
    tid = int(f'95{_now().strftime("%H%M%S%f")}')
    with SessionLocal() as s:
        s.add(User(telegram_id=str(tid), name='t', timezone='UTC', **cols))
        s.commit()
    return tid


def _row(tid: int):
    with SessionLocal() as s:
        return s.scalar(select(User).where(User.telegram_id == str(tid)))


def _add_message(db_uid: int, character_id: str, at) -> None:
    with SessionLocal() as s:
        s.add(Message(user_id=db_uid, character_id=character_id, role='user',
                      content='привет', created_at=at))
        s.commit()


def _db_uid(tid: int) -> int:
    with SessionLocal() as s:
        return int(s.scalar(select(User.id).where(User.telegram_id == str(tid))))


# ── флаг и потолок ─────────────────────────────────────────────────────────

def test_mode_is_an_account_flag_and_needs_no_premium():
    tid = _fresh_user()
    assert xm.is_on(_row(tid)) is False
    assert xm.set_mode(tid, True) is True
    user = _row(tid)
    assert xm.is_on(user) is True
    assert user.mode_set_at is not None
    # потолок есть только у не-Premium и только при включённом режиме
    assert xm.cap_left(user, premium=False) == EXPLICIT_MSGS_PER_DAY
    assert xm.cap_left(user, premium=True) is None
    assert xm.cap_left(user, premium=False, mode_on=False) is None
    assert xm.cap_left(_row(tid), premium=False, mode_on=None) == EXPLICIT_MSGS_PER_DAY
    # флаг аккаунта, а не диалога: другой персонаж видит тот же режим
    assert xm.is_on_for(tid) is True


def test_counter_burns_only_explicit_turns():
    tid = _fresh_user(spicy_mode=True)
    uid = _db_uid(tid)
    _add_message(uid, 'anna_01', _now() - timedelta(days=1))
    assert xm.note_reply(tid, user_text='как прошёл твой день?', answer='хорошо, спасибо',
                         mode_on=True, mode_open=True, premium=False) is None
    assert xm.used_today(_row(tid)) == 0
    # 24 сожжённых заранее — следующий откровенный ход даёт 5, то есть мягкую
    # подсказку, а не счётчик после каждого сообщения
    with SessionLocal() as s:
        u = s.scalar(select(User).where(User.telegram_id == str(tid)))
        u.explicit_day = xm.msk_today()
        u.explicit_used = EXPLICIT_MSGS_PER_DAY - 6
        s.commit()
    assert xm.note_reply(tid, user_text='как прошёл твой день?', answer='хорошо',
                         mode_on=True, mode_open=True, premium=False) is None
    assert xm.used_today(_row(tid)) == EXPLICIT_MSGS_PER_DAY - 6
    hint = xm.note_reply(tid, user_text='хочу секс с тобой', answer='расскажи',
                         mode_on=True, mode_open=True, premium=False)
    assert hint and hint['left'] == xm.HINT_AT_LEFT and hint['reached'] is False
    assert 'осталось' in hint['text']
    assert xm.used_today(_row(tid)) == EXPLICIT_MSGS_PER_DAY - 5
    # Premium не тратит счётчик вообще
    assert xm.note_reply(tid, user_text='хочу секс', answer='да',
                         mode_on=True, mode_open=True, premium=True) is None
    assert xm.used_today(_row(tid)) == EXPLICIT_MSGS_PER_DAY - 5


def test_ceiling_line_is_said_once_a_day():
    tid = _fresh_user(spicy_mode=True, explicit_day=xm.msk_today(),
                      explicit_used=EXPLICIT_MSGS_PER_DAY)
    first = xm.note_reply(tid, user_text='хочу секс', answer='милый, сегодня уже всё',
                          mode_on=True, mode_open=False, premium=False)
    assert first and first['reached'] is True and first['left'] == 0
    assert 'использовано' in first['text'] and 'Premium' in first['text']
    assert xm.note_reply(tid, user_text='хочу секс', answer='сегодня потолок',
                         mode_on=True, mode_open=False, premium=False) is None
    # выключенный режим не показывает чужие лимиты
    tid2 = _fresh_user()
    assert xm.note_reply(tid2, user_text='хочу секс', answer='ок',
                         mode_on=False, mode_open=False, premium=False) is None


def test_hint_is_read_once_by_one_surface():
    tid = _fresh_user(spicy_mode=True, explicit_day=xm.msk_today(),
                      explicit_used=EXPLICIT_MSGS_PER_DAY - 1)
    assert xm.note_reply(tid, user_text='хочу секс', answer='да',
                         mode_on=True, mode_open=True, premium=False)['reached'] is True
    got = xm.take_hint(tid)
    assert got and got['reached'] is True
    assert xm.take_hint(tid) is None


# ── «режим изменён» в уже начатых диалогах ────────────────────────────────

def test_mode_notice_only_for_dialogs_older_than_the_tap():
    tid = _fresh_user()
    uid = _db_uid(tid)
    old = _now() - timedelta(minutes=5)
    _add_message(uid, 'anna_01', old)
    _add_message(uid, 'alena_01', old)
    # пока он не менял режим — строк нет ни в одном диалоге
    assert xm.mode_notice(tid, uid, 'anna_01') is None
    xm.set_mode(tid, True)
    line = xm.mode_notice(tid, uid, 'anna_01')
    assert line and 'режим изменён' in line and xm.MODE_NAME_RU in line
    # пустой диалог — тоже
    assert xm.mode_notice(tid, uid, 'masha_01') is None
    # его новое сообщение снимает строку: история не переписывается, строка выводится
    _add_message(uid, 'anna_01', _now())
    assert xm.mode_notice(tid, uid, 'anna_01') is None
    # у другой девушки, где он ещё не писал после тапа, строка остаётся
    assert xm.mode_notice(tid, uid, 'alena_01') == line
    # выключил — строка про обычный режим (тап снова свежее последнего сообщения)
    xm.set_mode(tid, False)
    off = xm.mode_notice(tid, uid, 'anna_01')
    assert off and 'обычный режим' in off and xm.MODE_NAME_RU not in off
    en = xm.mode_notice(tid, uid, 'anna_01', 'en')
    assert en and en.startswith('mode changed') and 'ordinary mode' in en


# ── витрина приложения ─────────────────────────────────────────────────────

def test_api_me_shows_mode_and_ceiling_without_premium(monkeypatch):
    tid = _fresh_user(spicy_mode=True)
    import services.webapp_service as ws
    monkeypatch.setattr(ws, 'is_premium', lambda *a, **k: False)
    me = ws.api_me(tid)
    assert me['premium'] is False
    assert me['spicy_mode'] is True
    assert me['explicit_left'] == EXPLICIT_MSGS_PER_DAY
    monkeypatch.setattr(ws, 'is_premium', lambda *a, **k: True)
    assert ws.api_me(tid)['explicit_left'] is None
    # выключенный режим — потолка нет и он не нужен
    tid2 = _fresh_user()
    assert ws.api_me(tid2)['spicy_mode'] is False
    assert ws.api_me(tid2)['explicit_left'] is None


# ── статика: где флаг обязан быть виден ────────────────────────────────────

def _span(text: str, start_marker: str, end_marker: str) -> str:
    """Тело функции от маркера до следующего маркера. Поиск конца — строго
    после найденного начала, иначе '@dp.message(Command' окажётся внутри
    собственного маркера и срез выйдет пустым."""
    i = text.index(start_marker)
    return text[i:text.index(end_marker, i + len(start_marker))]


def test_entry_endpoint_takes_the_tapped_value_not_premium():
    body = _span(MAIN, 'async def _webapp_api_spicy', 'async def _webapp_api_presence')
    assert 'explicit_mode.set_mode' in body
    assert "'spicy'" in body
    assert 'is_premium' not in body, 'режим больше не покупается Premium'
    assert 'is_adult_confirmed' in body, '18+ остаётся условием включения'


def test_app_chat_carries_the_notice_and_the_counter():
    hist = _span(MAIN, 'async def _webapp_api_chat_history', 'def _custom_premium_gate_block')
    assert 'explicit_mode.mode_notice' in hist
    assert "'mode_notice'" in hist
    turn = _span(MAIN, 'async def _webapp_chat_turn', 'async def _webapp_api_chat_start')
    assert 'explicit_mode.take_hint' in turn or '_xm.take_hint' in turn
    assert "'explicit_hint'" in turn
    # в режиме ему не продают Premium за то, что режим уже даёт бесплатно
    assert '_xm.is_on_for' in turn


def test_bot_stops_selling_the_mode_and_only_shows_it():
    settings = _span(MAIN, "@dp.message(Command('settings'))", '@dp.message(Command(')
    assert "callback_data='toggle:spicy'" not in settings
    assert 'Пошлый режим' not in settings
    assert 'explicit_mode' in settings and 'cap_left' in settings
    handler = _span(MAIN, "@dp.callback_query(F.data == 'toggle:spicy')",
                    '# V3.19.0: per-user cooldown')
    assert 'update_user_settings' not in handler, 'старый тап в боте не должен флипать флаг'
    assert 'webapp?mode=1' in handler


def test_the_internal_flag_keeps_its_name():
    # переименован только режим на экране; колонка, коллбэк и аналитика — старые
    models = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
    assert 'spicy_mode: Mapped[bool]' in models
    assert 'explicit_day' in models and 'explicit_used' in models and 'mode_set_at' in models
    assert xm.MODE_NAME_RU == 'После полуночи'
