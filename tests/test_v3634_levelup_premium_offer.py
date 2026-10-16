"""V3.62.9: the first level-up opens the one-time −30% Premium window with
a button, once per user, never for Premium users or admins."""
import asyncio

import main


def test_offer_sent_once(monkeypatch):
    sent = []

    async def fake_send(chat_id, text, **kw):
        sent.append((text, kw.get('reply_markup')))

    monkeypatch.setattr(main.bot, 'send_message', fake_send)
    tid = 5550222
    main.ensure_user(tid)
    asyncio.run(main._maybe_level_up_premium_offer(tid, 2))
    asyncio.run(main._maybe_level_up_premium_offer(tid, 3))
    assert len(sent) == 1
    text, kb = sent[0]
    assert '−30%' in text and kb.inline_keyboard[0][0].callback_data == 'retention:premium'


def test_no_offer_on_level_one(monkeypatch):
    sent = []

    async def fake_send(*a, **kw):
        sent.append(a)

    monkeypatch.setattr(main.bot, 'send_message', fake_send)
    main.ensure_user(5550223)
    asyncio.run(main._maybe_level_up_premium_offer(5550223, 1))
    assert not sent


def test_pay_funnel_in_snapshot():
    from services.analytics_service import admin_snapshot
    pf = admin_snapshot()['pay_funnel']
    assert set(pf) == {'offer', 'invoice', 'paid'}
