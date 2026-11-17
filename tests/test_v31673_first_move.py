"""V3.167.3 (ТЗ Фогеля §3 «вернуть первый ход», владелец 16.11): первый ход
живёт в Mini App, в бот от него приходит только «вам написали».

Открыл чат — она пишет первой (работает с V3.165.0, выключается одним флагом
AUTO_OPENING_ENABLED). Молчит 90 с — она дописывает сама, текстом и под те же
чипы, без кадра и без списаний, не больше двух строк на открытие. Сидит в
приложении — видит строку на экране; вышел — об ней говорит записка
``services/app_ping``, и больше ничего в Telegram.

Живые проверки ходят по чистой БД, статические пиляют main, SPA и конфиг как
текст.
"""
import asyncio
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault('TELEGRAM_TOKEN', '123456:test-fake-token-for-static-tests-only')
os.environ.setdefault('GEMINI_API_KEY', 'x')

from sqlalchemy import select

import config
from models.app_models import Base, Message, User
from services import opening_nudge
from services.db import SessionLocal, engine

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CFG = (ROOT / 'config.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
NUDGE = (ROOT / 'services' / 'opening_nudge.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')

TG = 916700001
CHAR = 'anna_01'
KEY = (TG, CHAR)


def _app():
    """main собирает OpenAI-клиенты при импорте, а windows-NO_PROXY со «[::1]»
    внутри ломает httpx. Прокси снимаем только на время импорта."""
    saved = {k: os.environ.pop(k) for k in ('NO_PROXY', 'no_proxy') if k in os.environ}
    try:
        import main
        return main
    finally:
        os.environ.update(saved)


def _start() -> str:
    return MAIN[MAIN.index('async def _webapp_api_chat_start'):MAIN.index('def _chat_opening_spicy')]


def _fresh_user() -> int:
    Base.metadata.create_all(engine)
    tid = str(int(f'96{datetime.now().strftime("%H%M%S%f")}'))
    with SessionLocal() as s:
        s.add(User(telegram_id=tid, name='t', timezone='UTC'))
        s.commit()
        return int(s.scalar(select(User.id).where(User.telegram_id == tid)))


def _episode(uid: int, **over) -> dict:
    ep = {'uid': uid, 'chips': ['Приду за мандаринами', 'Какая гирлянда?'], 'lang': 'ru',
          'count': 0, 'start': datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=2),
          'at': time.monotonic()}
    ep.update(over)
    opening_nudge._episodes[KEY] = ep
    return ep


def _dialog(uid: int) -> list[Message]:
    with SessionLocal() as s:
        return list(s.scalars(select(Message).where(Message.user_id == uid,
                                                    Message.character_id == CHAR)
                              .order_by(Message.id)))


def _quiet_ping(monkeypatch) -> list:
    """app_ping — единственное, что этот релиз отдаёт в Telegram."""
    import services.app_ping as ap
    notes: list = []
    monkeypatch.setattr(ap, 'note', lambda bot, tg, char, text, media=None, **kw:
                        notes.append((tg, char, text, kw)))
    return notes


# ── 1. один флаг на весь первый ход ───────────────────────────────────────
def test_the_opener_is_one_flag():
    assert 'AUTO_OPENING_ENABLED = os.getenv("AUTO_OPENING_ENABLED", "true")' in CFG
    start = _start()
    assert 'if not AUTO_OPENING_ENABLED:' in start
    # выключенная открывашка отвечает пустым ok: чат остаётся обычным
    assert "return web.json_response({'ok': True})" in start[start.index('AUTO_OPENING_ENABLED'):]
    # и гаснет ДО заготовки — ни строки, ни записки, ни очереди
    assert start.index('if not AUTO_OPENING_ENABLED') < start.index('greeting_service.opening(')
    assert 'AUTO_OPENING_ENABLED' in NUDGE          # без флага и очередь не ставится


def test_the_opener_ends_with_the_stamp_and_the_followup():
    # диалог по-прежнему открывается один раз (V3.165.0), а на аккаунте первый
    # ход помнится колонкой — «повторно открывашка не приходит»
    start = _start()
    assert 'if get_recent_messages(uid, character_id, 1):' in start
    assert start.count('await asyncio.to_thread(_mark_opening_shown, uid)') == 2
    assert start.count('_opening_followup(telegram_id, uid, character_id') == 2
    assert 'opening_shown_at: Mapped[datetime | None]' in MODELS


def test_the_stamp_is_written_once():
    main = _app()
    uid = _fresh_user()
    main._mark_opening_shown(uid)
    with SessionLocal() as s:
        first = s.get(User, uid).opening_shown_at
        assert first is not None
        # второй открытие чата не двигает дату: по ней считается, видел ли он
        # первый ход вообще
        s.get(User, uid).opening_shown_at = first - timedelta(days=1)
        s.commit()
    main._mark_opening_shown(uid)
    with SessionLocal() as s:
        assert s.get(User, uid).opening_shown_at == first - timedelta(days=1)
    main._mark_opening_shown(10 ** 12)          # чужой uid не должен уронить открывашку


# ── 2. в бот от первого хода идёт только «вам написали» ───────────────────
def test_the_opener_leaves_the_bot_a_note_and_a_queue():
    body = MAIN[MAIN.index('def _opening_followup('):MAIN.index('async def _starter_frame_turn')]
    assert '_app_ping(' in body                       # «она написала тебе в приложении»
    assert 'opening_nudge.arm(bot' in body
    assert 'lang_guard.is_cyrillic_dominant' in body  # язык второй строки — по её первой
    assert 'bot.send_message' not in body             # прямого сообщения в Telegram здесь нет


def test_the_second_line_is_words_only():
    for word in ('generate_image', 'seedream', 'spend_peaches', 'get_photo_credits', 'voice'):
        assert word not in NUDGE, word
    assert 'save_message' in NUDGE                    # она говорит — и строка лежит в диалоге


def test_the_clock_and_the_cap():
    assert 'OPENING_NUDGE_SECONDS", "90"' in CFG and 'OPENING_NUDGE_MAX", "2"' in CFG
    assert config.OPENING_NUDGE_SECONDS == 90 and config.OPENING_NUDGE_MAX == 2
    assert "while episode['count'] < OPENING_NUDGE_MAX" in NUDGE


# ── 3. живая очередь: молчит — дописывает, ответил — молчит ───────────────
def test_silence_writes_her_second_line_and_notes_it(monkeypatch):
    uid = _fresh_user()
    notes = _quiet_ping(monkeypatch)
    opening_nudge._reset()
    ep = _episode(uid)
    assert asyncio.run(opening_nudge._write(None, KEY, ep)) is True
    lines = _dialog(uid)
    assert len(lines) == 1 and lines[0].role == 'assistant'
    assert notes == [(TG, CHAR, '', {'generic': True})]
    assert opening_nudge.take(*KEY)[0]['text'] == lines[0].content


def test_the_line_is_handed_to_the_client_once(monkeypatch):
    uid = _fresh_user()
    _quiet_ping(monkeypatch)
    opening_nudge._reset()
    ep = _episode(uid, lang='en')
    asyncio.run(opening_nudge._write(None, KEY, ep))
    got = opening_nudge.take(*KEY)
    assert len(got) == 1 and got[0]['chips'] == ep['chips']
    assert got[0]['text'] in opening_nudge._FIRST_EN
    assert opening_nudge.take(*KEY) == []


def test_his_answer_ends_the_episode(monkeypatch):
    uid = _fresh_user()
    from services.memory_service import save_message
    save_message(uid, CHAR, 'assistant', 'Привет 🙂')
    save_message(uid, CHAR, 'user', 'Привет')
    notes = _quiet_ping(monkeypatch)
    opening_nudge._reset()
    assert asyncio.run(opening_nudge._write(None, KEY, _episode(uid))) is False
    assert opening_nudge.take(*KEY) == [] and notes == []
    assert len(_dialog(uid)) == 2                     # ни одной её строки сверх уже написанных


def test_a_stale_episode_is_not_resurrected(monkeypatch):
    uid = _fresh_user()
    _quiet_ping(monkeypatch)
    opening_nudge._reset()
    ep = _episode(uid, at=time.monotonic() - opening_nudge.EPISODE_TTL_SECONDS - 1)
    assert asyncio.run(opening_nudge._write(None, KEY, ep)) is False
    assert _dialog(uid) == []


def test_a_newer_opening_replaces_the_old_episode(monkeypatch):
    uid = _fresh_user()
    _quiet_ping(monkeypatch)
    opening_nudge._reset()
    stale = _episode(uid)
    _episode(uid, chips=['Другой чип'])
    assert asyncio.run(opening_nudge._write(None, KEY, stale)) is False
    assert opening_nudge.take(*KEY) == []


# ── 4. тексты ─────────────────────────────────────────────────────────────
def test_the_pools_are_short_clean_and_different():
    first = {opening_nudge.followup_text(1, 'ru') for _ in range(30)}
    second = {opening_nudge.followup_text(2, 'ru') for _ in range(30)}
    assert first <= set(opening_nudge._FIRST_RU) and second <= set(opening_nudge._SECOND_RU)
    assert len(first) > 1 and len(second) > 1         # одна и та же строка каждый раз — это шаблон
    assert not (first & second)
    for line in list(opening_nudge._FIRST_RU) + list(opening_nudge._SECOND_RU) \
            + list(opening_nudge._FIRST_EN) + list(opening_nudge._SECOND_EN):
        assert '*' not in line and len(line) < 140
    assert opening_nudge.followup_text(1, 'en') in opening_nudge._FIRST_EN


def test_any_non_russian_dialog_gets_english():
    ru = set(opening_nudge._FIRST_RU) | set(opening_nudge._SECOND_RU)
    en = set(opening_nudge._FIRST_EN) | set(opening_nudge._SECOND_EN)
    assert {opening_nudge.followup_text(s, 'bn') for s in (1, 2)} <= en
    assert {opening_nudge.followup_text(s, 'ru') for s in (1, 2)} <= ru


# ── 5. клиент ─────────────────────────────────────────────────────────────
def test_the_client_watches_for_her_second_line():
    opener = INDEX[INDEX.index('async function requestChatOpener'):INDEX.index('function forkButtons')]
    assert 'if (reply) {' in opener
    assert 'startOpenerFollowPoll(characterId)' in opener
    assert "'/webapp/api/chat/followup?char='" in opener
    assert 'OPENER_UNDRESS = (data && data.undress_price) || 0' in opener
    # её строка — обычный её пузырь, а чипы возвращаются под неё с ценой «Раздеть»
    assert "role: 'assistant'" in opener
    assert 'renderChatHints(last.chips && last.chips.length ? last.chips : null, OPENER_UNDRESS)' in opener


def test_the_client_stops_the_minute_he_answers_or_leaves():
    send = INDEX[INDEX.index('async function sendChat('):INDEX.index('// V3.87.1')]
    assert 'stopOpenerFollowPoll()' in send
    back = INDEX[INDEX.index("document.getElementById('chatBack').addEventListener"):
        INDEX.index("document.getElementById('chatSend').addEventListener")]
    assert 'stopOpenerFollowPoll()' in back
    poll = INDEX[INDEX.index('function startOpenerFollowPoll'):INDEX.index('async function loadChatHistory')]
    assert '++ticks > 24' in poll
    assert "document.visibilityState !== 'visible'" in poll
    assert 'CHAT.id !== characterId' in poll


def test_the_followup_route_exists_and_demands_auth():
    assert "app.router.add_get('/webapp/api/chat/followup', _webapp_api_chat_followup)" in MAIN
    main = _app()

    class _Req:
        query = {}

    assert asyncio.run(main._webapp_api_chat_followup(_Req())).status == 401


def test_the_bot_still_keeps_its_silence_on_start():
    # V3.148.0 не отменялся: из этого релиза в бот не переехало ни автопривета,
    # ни второго сообщения — только записка app_ping.
    for name in ('_deliver_first_hello', '_first_hello_fallback', '_ensure_webapp_first_hello',
                 '_send_welcome_selfie'):
        assert name not in MAIN, name
    assert MAIN.count('asyncio.sleep(120)') == 0
