"""V3.166.2 (Блок 2 + Блок 3): один жёсткий потолок на весь аккаунт.

Владелец решил 15 ноя: «30 любых сообщений в сутки на весь аккаунт, независимо
от того, в каком режиме или в каком интерфейсе сидит пользователь. После 30-го —
жёсткий блок до полуночи по МСК и экран покупки Premium. Безлимит дается только
платным подписчикам». Плюс: «счётчик общий для Mini App и бота, если лимит
исчерпан — бот тоже шлёт заглушку, чтобы не было дыр в воронке».

Отсюда и проверки:

* счётчик не спрашивает про режим и про платформу, крутится по Москве;
* стена стоит на `can_send_message`, то есть и в боте, и в приложении;
* подсказка «осталось N» появляется, только когда день почти кончился, а строка
  «на сегодня всё» звучит один раз в сутки и читается одним экраном один раз;
* пэйволл — сцена от лица девушки, а не системная ошибка (тексты ТЗ слово в
  слово), и ведёт он ровно в одно место: оплату Premium.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from config import CHAT_MSGS_PER_DAY
from models.app_models import Base, User
from services import daily_limit as dl
from services.access_service import can_send_message
from services.db import SessionLocal, engine

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
GATE = (ROOT / 'services' / 'access_service.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def _fresh_user(**cols) -> int:
    Base.metadata.create_all(engine)
    tid = int(f'96{datetime.now(timezone.utc).strftime("%H%M%S%f")}')
    with SessionLocal() as s:
        s.add(User(telegram_id=str(tid), name='t', timezone='UTC', **cols))
        s.commit()
    return tid


def _row(tid: int):
    with SessionLocal() as s:
        return s.scalar(select(User).where(User.telegram_id == str(tid)))


def _set_used(tid: int, n: int) -> None:
    with SessionLocal() as s:
        u = s.scalar(select(User).where(User.telegram_id == str(tid)))
        u.chat_day = dl.msk_today()
        u.chat_used = n
        s.commit()


# ── сам счётчик ────────────────────────────────────────────────────────────

def test_the_cap_is_one_number_for_the_whole_account():
    assert CHAT_MSGS_PER_DAY == 30
    assert dl.DAILY_CAP == CHAT_MSGS_PER_DAY
    # витрина, legal и стена печатают ровно то, что считает счётчик
    assert 'FREE_MESSAGES_PER_DAY = CHAT_MSGS_PER_DAY' in (ROOT / 'config.py').read_text(encoding='utf-8')


def test_the_wall_rolls_at_moscow_midnight():
    tid = _fresh_user()
    assert dl.msk_today() == datetime.now(dl.MSK).date()
    _set_used(tid, CHAT_MSGS_PER_DAY)
    assert dl.used_today(_row(tid)) == CHAT_MSGS_PER_DAY
    with SessionLocal() as s:
        u = s.scalar(select(User).where(User.telegram_id == str(tid)))
        u.chat_day = dl.msk_today() - timedelta(days=1)
        s.commit()
    assert dl.used_today(_row(tid)) == 0
    assert dl.left(_row(tid), premium=False) == CHAT_MSGS_PER_DAY
    assert dl.has_left(tid) is True


def test_thirty_turns_close_the_gate_for_everybody_but_premium(monkeypatch):
    monkeypatch.setattr('services.access_service.is_premium', lambda *a, **k: False)
    tid = _fresh_user(spicy_mode=True)   # режим включён — потолок тот же
    for _ in range(CHAT_MSGS_PER_DAY - 1):
        assert dl.note_message(tid) is None or True
    assert dl.has_left(tid) is True and can_send_message(tid) is True
    dl.note_message(tid)
    assert dl.used_today(_row(tid)) == CHAT_MSGS_PER_DAY
    assert dl.left(_row(tid), premium=False) == 0
    assert dl.has_left(tid) is False and can_send_message(tid) is False
    # обычный режим — тот же счётчик: он про аккаунт, а не про «После полуночи»
    tid2 = _fresh_user()
    for _ in range(CHAT_MSGS_PER_DAY):
        dl.note_message(tid2)
    assert can_send_message(tid2) is False
    # Premium — единственный, у кого потолка нет
    monkeypatch.setattr('services.access_service.is_premium', lambda *a, **k: True)
    assert can_send_message(tid) is True
    assert dl.left(_row(tid), premium=True) is None


def test_the_owner_can_switch_the_wall_off(monkeypatch):
    monkeypatch.setattr(dl, 'CHAT_MSGS_PER_DAY', 0)
    tid = _fresh_user()
    _set_used(tid, 0)
    assert dl.left(_row(tid), premium=False) is None
    assert dl.has_left(tid) is True
    assert dl.note_message(tid) is None
    assert dl.reached_line('ru') == ''


# ── мягкая строка под её ответом ───────────────────────────────────────────

def test_the_count_only_shows_when_the_day_is_almost_spent():
    tid = _fresh_user()
    _set_used(tid, CHAT_MSGS_PER_DAY - dl.HINT_AT_LEFT - 2)
    assert dl.note_message(tid) is None                     # ещё далеко до стены
    assert dl.used_today(_row(tid)) == CHAT_MSGS_PER_DAY - dl.HINT_AT_LEFT - 1
    hint = dl.note_message(tid, language='ru')               # здесь начинается счёт
    assert hint and hint['left'] == dl.HINT_AT_LEFT and hint['reached'] is False
    assert str(dl.HINT_AT_LEFT) in hint['text']
    for _ in range(dl.HINT_AT_LEFT):                         # добиваем день
        hint = dl.note_message(tid, language='ru')
    assert hint and hint['left'] == 0 and hint['reached'] is True
    assert 'осталось' in dl.hint_line('ru', 3)
    assert dl.hint_line('en', 3).startswith('3 messages')
    assert dl.hint_line('ru', None) == ''                    # без потолка — без строки



def test_the_last_line_is_said_once_a_day_and_read_once():
    tid = _fresh_user()
    _set_used(tid, CHAT_MSGS_PER_DAY - 1)
    first = dl.note_message(tid, language='ru')
    assert first['reached'] is True and 'использовано' in first['text']
    assert 'Premium' in first['text']
    # её читает ровно один экран, и только раз в сутки
    got = dl.take_hint(tid)
    assert got and got['reached'] is True and set(got) == {'left', 'reached', 'text'}
    assert dl.take_hint(tid) is None
    assert dl.note_message(tid, language='ru') is None
    # на следующий день строка снова имеет право звучать
    dl._closed_shown[int(tid)] = dl.msk_today() - timedelta(days=1)
    _set_used(tid, CHAT_MSGS_PER_DAY - 1)
    assert dl.note_message(tid, language='ru')['reached'] is True


def test_a_hint_nobody_read_dies_with_the_reply():
    # её держит память процесса, поэтому непрочитанная строка сгорает по TTL —
    # а стена на следующий день всё равно живёт в БД, а не в этом словаре
    tid = _fresh_user()
    _set_used(tid, CHAT_MSGS_PER_DAY - 1)
    dl.note_message(tid)
    assert int(tid) in dl._pending
    dl._pending[int(tid)]['at'] -= dl._PENDING_TTL_SECONDS + 1
    assert dl.take_hint(tid) is None
    assert dl.has_left(tid) is False


# ── где именно сгорает сообщение ───────────────────────────────────────────

def test_every_live_turn_burns_one_and_only_one():
    # счётчик стоит на единственном пути ответа обеих платформ — в chat_service,
    # а не в каждом вызывающем коде (иначе дыра в воронке неизбежна).
    assert 'daily_limit.note_message' in CHAT
    turn = CHAT[CHAT.index('async def reply('):]
    turn = turn[:turn.index('await asyncio.to_thread(daily_limit.note_message')]
    assert 'if not premium and not caller_scene' in turn
    # он же не считает то, что он не он: её реплика без текста ход не сжигает
    assert "(r.text or '').strip()" in turn
    # и режим на это не влияет — счётика режима больше нет
    assert 'explicit_mode.note_reply' not in CHAT and 'cap_left' not in CHAT


def test_the_gate_is_one_function_asked_by_both_platforms(monkeypatch):
    import ast
    import asyncio
    import json
    from aiohttp import web
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    assert 'daily_limit.has_left' in GATE
    # Execute the real entry points without importing main (bot/network setup).
    # Only Mini App turns ask the shared gate; bot taps are neutral redirects.
    names = ('_webapp_chat_gate', '_webapp_api_chat_send', '_webapp_api_chat_voice',
             '_webapp_api_chat_photo', 'app_only_callback', '_redirect_bot_chat')
    functions = {node.name: node for node in ast.parse(MAIN).body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    nodes = [functions[name] for name in names]
    for node in nodes:
        node.decorator_list = []
    module = ast.parse('from __future__ import annotations')
    module.body.extend(nodes)
    tapper = SimpleNamespace(id=123, first_name='Test', language_code='en')
    markup = object()
    can_send = Mock(return_value=False)
    ensure = Mock(return_value=456)
    ns = {
        'asyncio': asyncio,
        'web': web, 'json': json,
        'spicy_service': SimpleNamespace(claim_paid_fantasy=Mock(return_value=None)),
        'webapp_service': SimpleNamespace(
            validate_init_data=lambda _: {'user': 'test'},
            init_data_user=lambda _: {'id': tapper.id}),
        'is_custom_character': lambda _: False,
        'get_card': lambda _: SimpleNamespace(status='active'),
        'ADMIN_TELEGRAM_IDS': set(), 'can_send_message': can_send,
        'has_accepted': lambda _: True, 'ensure_user': ensure,
        'track_event': Mock(), '_remember_character': Mock(),
        'user_lang': lambda _: 'en', 'EN': 'en',
        '_app_entry_markup': Mock(return_value=markup),
        '_bot_callback_character': Mock(return_value='anna_01'),
    }
    exec(compile(module, str(ROOT / 'main.py'), 'exec'), ns)
    for handler, payload in (
        ('_webapp_api_chat_send', {'text': 'hello'}),
        ('_webapp_api_chat_voice', {'audio': 'dGVzdA=='}),
        ('_webapp_api_chat_photo', {'image': 'dGVzdA=='}),
    ):
        request = SimpleNamespace(query={'init_data': 'test'}, json=AsyncMock(
            return_value={'character_id': 'anna_01', **payload}))
        can_send.reset_mock()
        response = asyncio.run(ns[handler](request))
        assert response.status == 429
        assert json.loads(response.body) == {'ok': False, 'error': 'limit', 'cap': dl.DAILY_CAP}
        can_send.assert_called_once_with(tapper.id)
    ns['spicy_service'].claim_paid_fantasy.assert_called_once_with(tapper.id, 'anna_01', 'hello', 'en')
    can_send.return_value = True
    assert ns['_webapp_chat_gate']('anna_01', tapper.id) is None
    can_send.return_value = False
    ns['ADMIN_TELEGRAM_IDS'].add(tapper.id)
    can_send.reset_mock()
    assert ns['_webapp_chat_gate']('anna_01', tapper.id) is None
    can_send.assert_not_called()

    # The message belongs to the bot, but consent/destination use the tapper.
    note_message = Mock(side_effect=AssertionError('Bot redirects must not consume chat quota'))
    monkeypatch.setattr(dl, 'note_message', note_message)
    ns['track_event'].reset_mock()
    message = SimpleNamespace(from_user=SimpleNamespace(id=999), answer=AsyncMock())
    cq = SimpleNamespace(message=message, from_user=tapper, answer=AsyncMock())
    for admins in (set(), {tapper.id}):
        ns['ADMIN_TELEGRAM_IDS'] = admins
        ensure.reset_mock()
        message.answer.reset_mock()
        cq.answer.reset_mock()
        asyncio.run(ns['app_only_callback'](cq))
        cq.answer.assert_awaited_once_with()
        ensure.assert_called_once_with(tapper.id, tapper.first_name, language_code='en')
        ns['_app_entry_markup'].assert_called_with('en', character_id='anna_01')
        message.answer.assert_awaited_once_with('Chat is in the app.', reply_markup=markup)
        can_send.assert_not_called()
        note_message.assert_not_called()
        ns['track_event'].assert_not_called()


# ── пэйволл: сцена, а не ошибка ────────────────────────────────────────────

def test_the_app_shows_her_card_not_an_error():
    assert 'id="wallmodal"' in INDEX
    assert 'function showLimitWall(retry)' in INDEX
    assert "backdrop-filter: blur" in INDEX
    # тексты ТЗ — слово в слово
    assert "wall_h: 'На самом интересном месте... 💔'" in INDEX
    assert ('wall_t: \'Мне так хочется продолжить, но на сегодня наше время вышло... '
            'Сними ограничения, чтобы мы могли общаться без границ в любом режиме. '
            'Я буду ждать тебя.\'' in INDEX)
    assert "'♾ Полный безлимит в режимах «Романтика» и «18+»'" in INDEX
    assert "'📸 Доступ к заказу откровенных фото'" in INDEX
    assert "'🎙 Приватные голосовые сообщения'" in INDEX
    assert "wall_cta: '🔓 Разблокировать Premium'" in INDEX
    # кнопка ведёт в стандартный флоу оплаты Premium, ✕ оставляет его в диалоге
    assert "quickBuy('limit', retry)" in INDEX
    assert "document.getElementById('wallClose').onclick" in INDEX
    # 429 от стены — это она, а не «не удалось получить ответ»
    assert "if (r.status === 429)" in INDEX
    assert "showLimitWall(() => { const i = document.getElementById('chatText')" in INDEX


def test_the_bot_sends_the_same_scene():
    wall = MAIN[MAIN.index('def _limit_wall_markup('):MAIN.index('# V3.27.0: ruble-shop balances')]
    assert 'Ой... кажется, наш лимит на сегодня исчерпан 🙈' in wall
    assert 'Но я не хочу останавливаться. Заходи сюда, чтобы снять ограничения:' in wall
    assert "else 'Продолжить безлимитно 🔓'" in wall
    assert "'Keep going, no limits 🔓'" in wall
    assert '/webapp?pay=1' in wall
    assert 'premium_keyboard' in wall          # без публичного url — обычный прайс
    assert "sp.get('pay') === '1'" in INDEX     # приложение открывает её же карточку
    # один экран — одна кнопка: демо, VIP-месяц и разовая скидка здесь больше
    # не продаются (в тексте-объяснении они ещё называются, поэтому проверяем
    # именно формы вызова, а не слова)
    for gone in ('retention:demo', 'buy:premium_vip', 'offer_discount', 'discount_info'):
        assert gone not in wall


def test_the_app_gate_answers_limit_without_side_offers():
    gate = MAIN[MAIN.index('def _webapp_chat_gate('):MAIN.index('def _tts_text(')]
    assert "not can_send_message(telegram_id)" in gate
    assert "'error': 'limit'" in gate
    assert "status=429" in gate
    assert "'chat_limit_wall'" in gate
    # ответ стены несёт только потолок — без демо, VIP-месяца и скидки
    assert "'cap'" in gate
    for gone in ('retention:demo', '_webapp_api_demo', 'premium_vip', 'discount_info'):
        assert gone not in gate


def test_the_burn_and_the_wall_never_leave_a_third_path():
    # thin line under her answer, both platforms, and nothing else sells at the wall
    assert "payload['chat_hint'] = chat_hint" in MAIN
    assert 'async def _daily_limit_note(' in MAIN
    assert "if not await _daily_limit_note(message, message.from_user.id):" in MAIN
    assert '_webapp_api_demo' not in MAIN
    assert 'F.data == "retention:demo"' not in MAIN and "'retention:demo'" not in MAIN
    assert '_maybe_level_up_premium_offer' not in MAIN
