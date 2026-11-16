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


def test_toggle_switches_the_same_message():
    tid = _user()
    key = main._thought_register(tid, NAME, THOUGHT)
    edits = []
    answers = []

    async def edit_text(text, **kw):
        edits.append({'text': text, **kw})

    async def answer(text='', **kw):
        answers.append(text)

    cq = SimpleNamespace(
        data=f'thought:show:{key}', from_user=SimpleNamespace(id=tid),
        message=SimpleNamespace(edit_text=edit_text), answer=answer)
    asyncio.run(main._thought_toggle(cq))
    assert THOUGHT in edits[0]['text']
    assert edits[0]['reply_markup'].inline_keyboard[0][0].callback_data == f'thought:hide:{key}'

    cq.data = f'thought:hide:{key}'
    asyncio.run(main._thought_toggle(cq))
    assert THOUGHT not in edits[1]['text']
    assert edits[1]['reply_markup'].inline_keyboard[0][0].callback_data == f'thought:show:{key}'
    assert answers == ['', '']


def test_foreign_and_stale_taps_are_harmless():
    tid = _user()
    key = main._thought_register(tid, NAME, THOUGHT)
    answers = []

    async def edit_text(text, **kw):
        raise AssertionError('чужой тап не должен править карточку')

    async def answer(text='', **kw):
        answers.append(text)

    other = SimpleNamespace(data=f'thought:show:{key}', from_user=SimpleNamespace(id=777001),
                            message=SimpleNamespace(edit_text=edit_text), answer=answer)
    asyncio.run(main._thought_toggle(other))
    assert answers and 'не твои' in answers[0]

    missing = SimpleNamespace(data='thought:show:999999', from_user=SimpleNamespace(id=tid),
                              message=SimpleNamespace(edit_text=edit_text), answer=answer)
    asyncio.run(main._thought_toggle(missing))
    assert 'не здесь' in answers[1]


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


def test_mini_app_window_is_collapsed_and_tappable():
    assert 'class="thcard min"' in WEBAPP
    assert "e.target.closest('.thcard')" in WEBAPP
    assert "card.classList.toggle('min')" in WEBAPP
    assert '-webkit-line-clamp: 1' in WEBAPP
    assert "th_more: 'развернуть', th_less: 'свернуть'" in WEBAPP
    assert "th_more: 'tap to read', th_less: 'hide'" in WEBAPP
