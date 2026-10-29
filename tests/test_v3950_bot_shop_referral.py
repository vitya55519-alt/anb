"""V3.95.0: the partner screen opened from an inline button shows the
tapper's own link (not the bot's), and «🍑 Персики» is a shop in the chat."""
import asyncio
import inspect
from types import SimpleNamespace

import main
from config import PEACH_PACK_CREDITS, PEACH_PACK_STARS


def test_partner_open_passes_the_tapper():
    src = inspect.getsource(main.partner_open)
    assert 'referral_cmd(cq.message, cq.from_user)' in src
    body = inspect.getsource(main.referral_cmd)
    assert 'message.from_user.id' not in body
    assert "referral_link(me.username or 'bot', who.id)" in body


def test_referral_link_uses_the_tapper_id(monkeypatch):
    sent = []

    class _Msg:
        from_user = SimpleNamespace(id=999000111, first_name='Bot', language_code='ru', username='the_bot')

        async def answer(self, text, **kw):
            sent.append(text)

    async def _me():
        return SimpleNamespace(username='the_bot')

    monkeypatch.setattr(main.bot, 'get_me', _me)
    who = SimpleNamespace(id=5550222, first_name='Витя', language_code='ru', username=None)
    asyncio.run(main.referral_cmd(_Msg(), who))
    assert sent and 'ref_5550222' in sent[0] and 'ref_999000111' not in sent[0]


def test_peach_shop_keyboard_has_every_pack():
    main.ensure_user(5550333)
    kb = main.peach_shop_keyboard(5550333)
    data = [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data]
    for key in PEACH_PACK_CREDITS:
        assert f'buy:{key}' in data
    assert 'premium:view' in data


def test_buttons_open_the_chat_shop():
    assert '_send_peach_shop(message)' in inspect.getsource(main.credits_button)
    assert '_send_peach_shop(cq.message, cq.from_user)' in inspect.getsource(main.credits_open)
    src = inspect.getsource(main.buy_peach_pack)
    assert 'send_stars_invoice(' in src and 'PEACH_PACK_STARS[key]' in src
    assert set(PEACH_PACK_STARS) == set(PEACH_PACK_CREDITS)
