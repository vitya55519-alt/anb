"""V3.62.7: her first hello carries three one-tap answers; a tap goes through
the normal chat pipeline as the user's own message."""
import asyncio
import datetime

from aiogram import types

import main


def _cq(data):
    user = types.User(id=5550099, is_bot=False, first_name='Тест')
    bot_user = types.User(id=1, is_bot=True, first_name='bot')
    msg = types.Message(message_id=7, date=datetime.datetime.now(), chat=types.Chat(id=5550099, type='private'),
                        from_user=bot_user, text='привет 😊 я Аня')
    return types.CallbackQuery(id='1', from_user=user, chat_instance='x', message=msg, data=data)


def test_keyboard_has_three_answers():
    kb = main._first_hello_keyboard('ru')
    assert [r[0].text for r in kb.inline_keyboard] == list(main.FIRST_REPLIES_RU)


def test_tap_sends_text_as_user(monkeypatch):
    seen = {}

    async def fake_text_message(m):
        seen['text'], seen['uid'] = m.text, m.from_user.id

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(main, 'text_message', fake_text_message)
    monkeypatch.setattr(types.CallbackQuery, 'answer', noop)
    monkeypatch.setattr(types.Message, 'edit_reply_markup', noop)
    main.ensure_user(5550099)
    asyncio.run(main.first_reply_cb(_cq('first_reply:2')))
    assert seen == {'text': main.FIRST_REPLIES_RU[2], 'uid': 5550099}


def test_consent_hello_uses_keyboard():
    import inspect
    assert 'reply_markup=_first_hello_keyboard(lang)' in inspect.getsource(main.consent_accept)
