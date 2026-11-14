"""V3.165.0 (задача #106): открыл чат в Mini App — она пишет первой.

ТЗ владельца: выбора «сюжет / без сюжета» больше нет. Открыл новый диалог в
приложении — её открывающая сцена приходит сама, а в режиме «После полуночи»
первый кадр «в откровенном наряде»: в первой же строке слышно, что на ней.
В боте тишина до его первого сообщения остаётся (V3.148.0).

Пять тестов статические — пиляют разметку и JS как текст, им не нужны ни
браузер, ни ключи. Два живые: проверяют оба ключа пошлого открывания (флаг
режима + 18+) и то, что при сбое модели остаётся исходная сцена, а не пустой
чат и не отказ.
"""
import asyncio
import os
from datetime import datetime
from pathlib import Path

os.environ.setdefault('TELEGRAM_TOKEN', '123456:test-fake-token-for-static-tests-only')
os.environ.setdefault('GEMINI_API_KEY', 'x')

from models.app_models import Base, User
from services.db import SessionLocal, engine

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def _span(start: str, end: str) -> str:
    return MAIN[MAIN.index(start):MAIN.index(end)]


def _fn(name: str) -> str:
    """Тело функции приложения: от её объявления до следующего объявления."""
    return INDEX[INDEX.index(f'async function {name}('):INDEX.index('async function chooseBranch(')]


def _fresh_user(**cols) -> int:
    Base.metadata.create_all(engine)
    tid = int(f'96{datetime.now().strftime("%H%M%S%f")}')
    with SessionLocal() as s:
        s.add(User(telegram_id=str(tid), name='t', timezone='UTC', **cols))
        s.commit()
    return tid


def _app():
    """main собирает OpenAI-клиенты прямо при импорте, а windows-переменная
    NO_PROXY со «[::1]» внутри ломает httpx (InvalidURL). Прокси-переменные
    снимаем только на время импорта и сразу возвращаем — остальной прогон
    видит их ровно так же, как до этого."""
    saved = {k: os.environ.pop(k) for k in ('NO_PROXY', 'no_proxy') if k in os.environ}
    try:
        import main
        return main
    finally:
        os.environ.update(saved)


# ── 1. выбора нет ──────────────────────────────────────────────────────────
def test_the_start_picker_is_gone():
    for name in ('startSheet', 'openStartSheet', 'startStory', 'startPlain', 'Как начать чат?'):
        assert name not in INDEX, name
    # лист звонков остался: класс жив, убрана только стартовая разметка
    assert 'class="startsheet" id="callPick"' in INDEX
    # и запрос к серверу больше не несёт mode — выбирать не из чего
    opener = _fn('requestChatOpener')
    assert 'JSON.stringify({ character_id: characterId })' in opener
    assert 'mode' not in opener
    assert "if mode != 'story'" not in MAIN


# ── 2. открыл чат — она пишет ──────────────────────────────────────────────
def test_opening_an_empty_dialog_asks_for_her_line():
    hist = INDEX[INDEX.index('async function loadChatHistory('):INDEX.index('function renderChatHints()')]
    branch = hist[hist.index('if (!j.history.length)'):hist.index('else {')]
    assert 'requestChatOpener(characterId)' in branch
    assert 'openStartSheet' not in hist


def test_the_opener_shows_typing_then_her_bubble():
    opener = _fn('requestChatOpener')
    assert "L.typing_now" in opener                        # «печатает…», а не пустой экран
    assert "'/webapp/api/chat/start" in opener
    assert 'chatBubble({ role: \'assistant\'' in opener     # её строка — обычное её сообщение
    assert 'renderChatHints()' in opener                     # подсказки остаются под её строкой
    # сбой сети не оставляют чат пустым: возвращается placeholder
    assert 'L.empty_chat' in opener


def test_the_server_never_opens_the_dialog_twice():
    start = _span('async def _webapp_api_chat_start', 'def _chat_opening_spicy')
    assert 'if get_recent_messages(uid, character_id, 1):' in start
    assert "return web.json_response({'ok': True, 'reply': scene})" in start
    assert "await asyncio.to_thread(save_message, uid, character_id, 'assistant', scene)" in start
    # V3.148.0: тишина бота не вернулась — сюда она не переехала, а осталась в боте
    for name in ('_deliver_first_hello', '_first_hello_fallback', '_ensure_webapp_first_hello',
                 '_send_welcome_selfie'):
        assert name not in MAIN, name


# ── 3. пошлый первый кадр — словами, не генерацией ─────────────────────────
def test_the_reveal_is_words_not_a_frame():
    start = _span('async def _webapp_api_chat_start', 'async def _webapp_api_chat_guest')
    assert '_chat_opening_spicy' in start and '_spicy_opening_line' in start
    # ни кадра, ни списания: откровение в первой строке ничего не стоит
    for word in ('generate_image', 'seedream', 'photo_service', 'peach', 'charge'):
        assert word not in start, word


def test_the_spicy_gate_needs_both_keys():
    main = _app()
    plain = _fresh_user()
    assert main._chat_opening_spicy(plain) is False
    naked_adult = _fresh_user(adult_confirmed=True)
    assert main._chat_opening_spicy(naked_adult) is False
    spicy_minor = _fresh_user(spicy_mode=True)
    assert main._chat_opening_spicy(spicy_minor) is False
    both = _fresh_user(spicy_mode=True, adult_confirmed=True)
    assert main._chat_opening_spicy(both) is True


def test_a_broken_rewrite_keeps_the_original_scene(monkeypatch):
    main = _app()
    import services.llm_provider_service as llm

    class _Boom:
        async def __call__(self, *a, **k):
            raise RuntimeError('no key')

    monkeypatch.setattr(llm, 'generate_text', _Boom())
    assert asyncio.run(main._spicy_opening_line(1, 'anna_01', '*сцена* привет')) == ''

    class _Ok:
        async def __call__(self, *a, **k):
            class _R:
                text = 'Сегодня на мне только этот халатик. Ну что, зайдёшь?'
            return _R()

    monkeypatch.setattr(llm, 'generate_text', _Ok())
    line = asyncio.run(main._spicy_opening_line(1, 'anna_01', '*сцена* привет'))
    assert line == 'Сегодня на мне только этот халатик. Ну что, зайдёшь?'
