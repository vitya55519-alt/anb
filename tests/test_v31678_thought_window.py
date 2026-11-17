"""V3.167.8 (владелец, скрин 16.11): «сделай в чате с моделью чтобы мысли
приходили свёрнутым окном — нажал и посмотрел, нажал свернул».

В боте карточка «💭 Мысли …» приходила полным полотном текста поверх её
ответа. Теперь она приходит свёрнутой: под ней одна кнопка, тап раскрывает,
тап же прячет. В Mini App то же окно — свёрнуто до одной строки, разворачивается
тапом по шапке.

Что держат эти тесты:
* в свёрнутом тексте мыслей нет — они не светятся в уведомлении;
* кнопка ведёт себя как переключатель show/hide и правит то же сообщение;
* чужой тап и тап после рестарта не ломают карточку;
* хранилище карточек ограничено, диалог не растит память бесконечно;
* её реплики и голос в этом окне никуда не переезжают.
"""
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import main
from services.user_service import ensure_user

logging.getLogger('services.llm_provider_service').setLevel(logging.CRITICAL)

WEBAPP = (Path(main.__file__).parent / 'webapp' / 'index.html').read_text(encoding='utf-8')

TID = 559101
THOUGHT = 'он снова пишет прямо и грубо — мне нравится, что он не боится'
NAME = 'Милана'


def _user() -> int:
    return ensure_user(TID, 'thoughts', language_code='ru')


def _fake_message(tid: int):
    sent = []

    async def answer(text, **kw):
        sent.append({'text': text, **kw})
        return SimpleNamespace(message_id=1000 + len(sent))

    return SimpleNamespace(from_user=SimpleNamespace(id=tid), chat=SimpleNamespace(id=tid),
                           answer=answer), sent


def test_collapsed_card_hides_the_thought():
    collapsed = main._thought_card(NAME, THOUGHT)
    assert '💭 <b>Мысли' in collapsed
    assert THOUGHT not in collapsed
    expanded = main._thought_card(NAME, THOUGHT, expanded=True)
    assert THOUGHT in expanded
    en = main._thought_card(NAME, THOUGHT, lang='en')
    assert "thoughts</b>" in en and THOUGHT not in en


def test_card_is_html_safe():
    card = main._thought_card('<img src=x>', 'a < b')
    assert '<img' not in card and 'a &lt; b' in main._thought_card(NAME, 'a < b', expanded=True)


def test_legacy_toggle_redirects_instead_of_revealing(monkeypatch):
    from unittest.mock import AsyncMock
    tid = _user()
    key = main._thought_register(tid, NAME, THOUGHT)
    redirect = AsyncMock()
    monkeypatch.setattr(main, '_redirect_bot_chat', redirect)
    edit = AsyncMock(side_effect=AssertionError('Telegram must not reveal thoughts'))
    cq = SimpleNamespace(
        data=f'thought:show:{key}', from_user=SimpleNamespace(id=tid),
        message=SimpleNamespace(edit_text=edit), answer=AsyncMock())
    asyncio.run(main._thought_toggle(cq))
    redirect.assert_awaited_once_with(cq.message, cq.from_user, None)
    cq.data = f'thought:hide:{key}'
    asyncio.run(main._thought_toggle(cq))
    assert redirect.await_count == 2
    edit.assert_not_awaited()


def test_foreign_and_stale_taps_redirect_without_reading_store(monkeypatch):
    from unittest.mock import AsyncMock
    class ForbiddenStore(dict):
        def get(self, *args):
            raise AssertionError('A legacy tap must not read any thought')
    monkeypatch.setattr(main, '_thought_cards', ForbiddenStore())
    redirect = AsyncMock()
    monkeypatch.setattr(main, '_redirect_bot_chat', redirect)
    for tid, data in ((777001, 'thought:show:1'), (TID, 'thought:show:999999')):
        cq = SimpleNamespace(data=data, from_user=SimpleNamespace(id=tid),
                             message=SimpleNamespace(), answer=AsyncMock())
        asyncio.run(main._thought_toggle(cq))
        redirect.assert_awaited_with(cq.message, cq.from_user, None)
    assert redirect.await_count == 2


def test_store_is_bounded():
    start = len(main._thought_cards)
    for i in range(600):
        main._thought_register(559000 + i, NAME, f'мысль {i}')
    assert len(main._thought_cards) <= 400
    assert len(main._thought_cards) >= start


def test_novel_answer_sends_the_window_with_a_button():
    tid = _user()
    msg, sent = _fake_message(tid)
    asyncio.run(main._send_novel_answer(msg, THOUGHT, 'да, и очень хочу 🙈', None, voice=False))
    kb = sent[0]['reply_markup'].inline_keyboard[0][0]
    assert kb.callback_data.startswith('thought:show:')
    assert THOUGHT not in sent[0]['text']
    assert sent[1]['text'] == 'да, и очень хочу 🙈'


def test_mini_app_message_is_not_collapsible():
    assert '.msg.bot.thcard' in WEBAPP
    assert 'class="thcard min"' not in WEBAPP
    assert "e.target.closest('.thcard')" not in WEBAPP
    assert "card.classList.toggle('min')" not in WEBAPP
    assert '.thcard.min' not in WEBAPP and '.thcard .th-t' not in WEBAPP
    card = WEBAPP[WEBAPP.index('function messageCard('):WEBAPP.index('function sameChat(')]
    assert 'esc(nm)' in card and 'L.thoughts' not in card
    assert 'L.th_more' not in card and 'L.th_less' not in card
