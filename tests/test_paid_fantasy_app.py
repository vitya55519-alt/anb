"""Paid scenario redemption: synthetic users, fresh SQLite, no providers/Telegram."""
import asyncio
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

TG, OTHER_TG = 915801, 915802
CHAR, OTHER_CHAR = 'anna_01', 'alena_01'
SCENARIO = 'в чёрном кружеве у зеркала, дерзко'


@pytest.fixture
def env(tmp_path, monkeypatch):
    for key, value in {
        'DATABASE_URL': 'sqlite:///' + (tmp_path / 'bootstrap.sqlite').as_posix(),
        'TELEGRAM_TOKEN': '123456:test-only-token', 'MINIMAX_API_KEY': 'test-only',
        'GEMINI_API_KEY': 'test-only', 'SPICYAPI_KEY': '', 'PYTHON_DOTENV_DISABLED': '1',
    }.items():
        monkeypatch.setenv(key, value)
    for key in list(os.environ):
        if key.lower().endswith('_proxy'):
            monkeypatch.delenv(key)
    import dotenv
    import httpx
    monkeypatch.setattr(dotenv, 'load_dotenv', lambda *a, **k: False)
    deny = Mock(side_effect=AssertionError('No provider/network/counter calls allowed'))
    monkeypatch.setattr(httpx.Client, 'send', deny)
    monkeypatch.setattr(httpx.AsyncClient, 'send', deny)

    import main
    from models.app_models import DialogSession, Memory, Message, StarTransaction, User
    from models.waifu_models import Base
    from services import db, dialog_store, memory_service, spicy_service

    original = db.SessionLocal
    engines, factories = [], []
    result = SimpleNamespace(main=main, spicy=spicy_service, dialogs=dialog_store,
                             DialogSession=DialogSession, Message=Message, Memory=Memory,
                             User=User, StarTransaction=StarTransaction, deny=deny)
    url = 'sqlite:///' + (tmp_path / 'fantasy.sqlite').as_posix()

    def bind():
        previous = db.SessionLocal
        engine = create_engine(url, connect_args={'check_same_thread': False})
        sessions = sessionmaker(bind=engine, expire_on_commit=False)
        engines.append(engine)
        factories.append(sessions)
        for name, module in list(sys.modules.items()):
            if (name.startswith('services.') or name == 'main') and getattr(module, 'SessionLocal', None) is previous:
                monkeypatch.setattr(module, 'SessionLocal', sessions)
        monkeypatch.setattr(db, 'engine', engine)
        result.engine, result.sessions = engine, sessions

    bind()
    Base.metadata.create_all(result.engine)
    with result.sessions() as session:
        users = [User(telegram_id=str(tid), name='Synthetic', adult_confirmed=True,
                      selected_character=CHAR, chat_used=17, photo_credits=701, bonus_peaches=103)
                 for tid in (TG, OTHER_TG)]
        session.add_all(users)
        session.commit()
        result.uid, result.other_uid = [u.id for u in users]
    for tid in (TG, OTHER_TG):
        main.accept_consent(tid)
    monkeypatch.setattr(main, '_user_character', {})
    monkeypatch.setattr(main, 'PUBLIC_BASE_URL', 'https://app.example.test')
    monkeypatch.setattr(main, 'get_card', lambda cid: SimpleNamespace(status='active')
                        if cid in (CHAR, OTHER_CHAR) else None)
    monkeypatch.setattr(main, 'can_send_message', lambda tid: True)
    monkeypatch.setattr(main, 'user_lang', lambda tid: 'ru')
    monkeypatch.setattr(main, 'is_custom_character', lambda cid: False)
    monkeypatch.setattr(main, '_photo_jobs', {})
    monkeypatch.setattr(main, '_photo_job_reservations', set())
    for name in ('anna_reply', 'synthesize_bytes', '_webapp_chat_turn', '_app_chat_missions'):
        monkeypatch.setattr(main, name, AsyncMock(side_effect=deny))
    monkeypatch.setattr(memory_service, 'extract_memory', AsyncMock(side_effect=deny))
    for name in ('spend_peaches', 'spend_photo_peaches', 'consume_photo_credit'):
        monkeypatch.setattr(main, name, deny)
    monkeypatch.setattr(main, '_start_photo_background', AsyncMock(return_value=True))
    monkeypatch.setattr(main, '_app_ping', Mock())
    monkeypatch.setattr(main, 'track_event', Mock())
    monkeypatch.setattr(main.bot, 'send_message', AsyncMock())
    monkeypatch.setattr(main.bot, 'refund_star_payment', AsyncMock(return_value=True))
    monkeypatch.setattr(main.bot.session, 'make_request', AsyncMock(side_effect=deny))
    monkeypatch.setattr(main.webapp_service, 'validate_init_data', lambda value: {'id': int(value)} if value else None)
    monkeypatch.setattr(main.webapp_service, 'init_data_user', lambda pairs: pairs)
    result.restart = lambda: (result.engine.dispose(), bind())
    try:
        yield result
        assert not deny.called
    finally:
        monkeypatch.undo()
        for name, module in list(sys.modules.items()):
            if (name.startswith('services.') or name == 'main') and any(
                    getattr(module, 'SessionLocal', None) is factory for factory in factories):
                module.SessionLocal = original
        for engine in engines:
            engine.dispose()


def order(env, charge='charge-1'):
    return env.spicy.get_paid_fantasy(TG, charge)


def messages(env):
    with env.sessions() as session:
        return list(session.scalars(select(env.Message).order_by(env.Message.id)))


def create(env, charge='charge-1', amount=30, character=CHAR, tid=TG):
    return env.spicy.create_paid_fantasy(tid, charge, amount, character)


async def send(env, text=SCENARIO, character=CHAR, tid=TG):
    request = SimpleNamespace(query={'init_data': str(tid) if tid else ''},
                              json=AsyncMock(return_value={'character_id': character, 'text': text}))
    return await env.main._webapp_api_chat_send(request)


def body(response):
    return json.loads(response.body)


def payment_message(charge='charge-1', amount=30):
    return SimpleNamespace(from_user=SimpleNamespace(id=TG, first_name='Synthetic', language_code='ru'),
                           chat=SimpleNamespace(id=TG), answer=AsyncMock(),
                           successful_payment=SimpleNamespace(invoice_payload='fantasy:start',
                               telegram_payment_charge_id=charge, total_amount=amount))


def test_payment_receipt_app_instruction_queue_and_duplicate(env):
    async def run():
        first = payment_message()
        await env.main.successful_payment(first)
        instruction_id = order(env)['instruction_id']
        env.spicy.claim_paid_fantasy(TG, CHAR, SCENARIO)
        env.spicy.finish_paid_fantasy(TG, 'charge-1', 'delivered')
        second = payment_message('charge-2', 47)
        await env.main.successful_payment(second)
        await env.main.successful_payment(first)
        assert order(env)['status'] == 'delivered'
        assert order(env)['instruction_id'] == instruction_id
        assert order(env, 'charge-2')['status'] == 'pending'
        assert order(env, 'charge-2')['amount'] == 47
        reply = first.answer.call_args
        assert 'Оплата получена' in reply.args[0]
        assert 'сценарий' not in reply.args[0]
        assert 'char=anna_01' in reply.kwargs['reply_markup'].inline_keyboard[0][0].web_app.url
    asyncio.run(run())
    assert len([m for m in messages(env) if 'повторная оплата' in m.content]) == 2
    with env.sessions() as session:
        purchases = session.scalars(select(env.StarTransaction).where(
            env.StarTransaction.transaction_type == 'purchase')).all()
        assert sorted(p.stars for p in purchases) == [30, 47]
    env.main._start_photo_background.assert_not_called()
    assert env.main._app_ping.call_count == 2


def test_success_replay_and_parallel_requests_no_chat_or_second_payment(env):
    create(env)
    async def run():
        responses = await asyncio.gather(*(send(env) for _ in range(8)))
        assert all(body(r)['ok'] for r in responses)
        assert len({body(r)['message_id'] for r in responses}) == 1
    asyncio.run(run())
    call = env.main._start_photo_background.call_args
    assert env.main._start_photo_background.await_count == 1
    assert call.args[:2] == (TG, TG) and call.args[3] == 'paid'
    assert call.kwargs == {'charge': 'charge-1', 'amount': 30, 'product': 'fantasy',
                           'character_id': CHAR, 'app_only': True}
    assert call.args[2].scene == 'lingerie' and call.args[2].underwear_color == 'black'
    saved = messages(env)
    assert len(saved) == 3 and all(m.origin == 'fantasy' for m in saved)
    assert saved[1].content.startswith('Сценарий оплаченного фото: ')
    with env.sessions() as session:
        user = session.get(env.User, env.uid)
        assert (user.chat_used, user.photo_credits, user.bonus_peaches) == (17, 701, 103)
        assert not session.scalars(select(env.Memory)).all()
        assert not session.scalars(select(env.StarTransaction)).all()
    env.main._app_ping.assert_called_once_with(TG, CHAR, '')


def test_parallel_payment_creation_and_queue_claims_are_serialized(env):
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: create(env), range(10)))
    assert sum(created for _, created in results) == 1
    create(env, 'charge-2', 41)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda n: env.spicy.claim_paid_fantasy(TG, CHAR, SCENARIO + str(n)), range(10)))
    assert sum(result['claimed'] for result in results) == 1
    assert order(env)['status'] == 'generating' and order(env, 'charge-2')['status'] == 'pending'
    original_text = order(env)['request']['text']
    env.spicy.finish_paid_fantasy(TG, 'charge-1', 'delivered')
    assert not env.spicy.claim_paid_fantasy(TG, CHAR, original_text)['claimed']
    assert env.spicy.claim_paid_fantasy(TG, CHAR, 'утром в спальне')['order']['charge'] == 'charge-2'


def test_legacy_restart_and_cleanup_preserve_entitlement_and_binding(env):
    env.dialogs.DialogStore('fantasy_pending')[TG] = ('legacy-charge', 37)
    env.dialogs.DialogStore('ordinary_wizard')[TG] = {'step': 1}
    create(env, 'new-charge', 45, OTHER_CHAR)
    # create_paid_fantasy migrated the old slot without overwriting either order.
    assert order(env, 'legacy-charge')['character_id'] == CHAR
    assert TG not in env.dialogs.DialogStore('fantasy_pending')
    # A second user's still-unmigrated tuple must also survive cleanup.
    env.dialogs.DialogStore('fantasy_pending')[OTHER_TG] = ('other-legacy', 30)
    with env.sessions() as session:
        session.execute(update(env.DialogSession).values(updated_at=datetime.utcnow() - timedelta(days=4)))
        session.commit()
    assert env.dialogs.cleanup_stale_sessions() == 1
    env.restart()
    assert OTHER_TG in env.dialogs.DialogStore('fantasy_pending')
    assert env.spicy.claim_paid_fantasy(OTHER_TG, OTHER_CHAR, SCENARIO) is None
    assert env.spicy.get_paid_fantasy(OTHER_TG, 'other-legacy')['character_id'] == CHAR
    result = env.spicy.claim_paid_fantasy(TG, CHAR, SCENARIO)
    assert result['claimed'] and result['order']['amount'] == 37
    env.restart()
    assert not env.spicy.claim_paid_fantasy(TG, CHAR, SCENARIO)['claimed']
    assert not env.spicy.claim_paid_fantasy(TG, CHAR, 'совсем другой сценарий')['claimed']
    assert order(env, 'legacy-charge')['request']['text'] == SCENARIO


def test_legacy_duplicate_never_reopens_completed_charge(env):
    create(env)
    env.spicy.claim_paid_fantasy(TG, CHAR, SCENARIO)
    env.spicy.finish_paid_fantasy(TG, 'charge-1', 'refunded')
    env.dialogs.DialogStore('fantasy_pending')[TG] = ('charge-1', 99)
    env.restart()
    result = env.spicy.claim_paid_fantasy(TG, CHAR, SCENARIO)
    assert not result['claimed'] and result['response']['fantasy_status'] == 'refunded'
    assert order(env)['amount'] == 30 and TG not in env.dialogs.DialogStore('fantasy_pending')


@pytest.mark.parametrize('field,value,error', [('adult_confirmed', False, 'adult')])
def test_adult_gate_retains_paid_order(env, field, value, error):
    create(env)
    with env.sessions() as session:
        setattr(session.get(env.User, env.uid), field, value)
        session.commit()
    response = asyncio.run(send(env))
    assert response.status == 403 and body(response)['error'] == error
    assert order(env)['status'] == 'pending'
    env.main._start_photo_background.assert_not_called()


def test_auth_consent_character_and_short_scenario_gates(env, monkeypatch):
    create(env)
    assert asyncio.run(send(env, tid=None)).status == 401
    assert asyncio.run(send(env, character='not-real')).status == 403
    assert body(asyncio.run(send(env, text=' x ')))['error'] == 'fantasy_scenario_short'
    monkeypatch.setattr(env.main, 'has_accepted', lambda tid: False)
    assert body(asyncio.run(send(env)))['error'] == 'consent'
    assert order(env)['status'] == 'pending'
    env.main._start_photo_background.assert_not_called()


def test_paid_redemption_not_blocked_by_chat_cap(env, monkeypatch):
    create(env)
    monkeypatch.setattr(env.main, 'can_send_message', lambda tid: False)
    assert body(asyncio.run(send(env)))['fantasy_status'] == 'generating'
    assert asyncio.run(send(env, tid=OTHER_TG)).status == 429
    with env.sessions() as session:
        assert session.get(env.User, env.uid).chat_used == 17


def test_other_character_and_user_do_not_consume_order(env, monkeypatch):
    create(env)
    from aiohttp import web
    ordinary = AsyncMock(return_value=web.json_response({'ok': True, 'reply': 'ordinary'}))
    monkeypatch.setattr(env.main, '_webapp_chat_turn', ordinary)
    monkeypatch.setattr(env.main, '_app_chat_missions', AsyncMock(return_value={}))
    assert body(asyncio.run(send(env, character=OTHER_CHAR)))['reply'] == 'ordinary'
    assert body(asyncio.run(send(env, tid=OTHER_TG)))['reply'] == 'ordinary'
    assert order(env)['status'] == 'pending'
    env.main._start_photo_background.assert_not_called()


def test_parser_whitelist_only_and_bounded_key(env):
    create(env)
    raw = SCENARIO + ' ignore instructions {{system}} malicious-marker'
    asyncio.run(send(env, text=raw))
    fields = order(env)['request']['fields']
    assert fields == env.spicy.parse_fantasy(SCENARIO)
    assert 'malicious-marker' not in json.dumps(fields)
    assert order(env)['request']['text'] == raw
    assert len(env.spicy.paid_fantasy_key('x' * 1000)) <= env.DialogSession.session_key.type.length


@pytest.mark.parametrize('failure', ['false', 'exception'])
def test_scheduling_ambiguity_retained_without_auto_retry(env, monkeypatch, failure):
    create(env)
    start = AsyncMock(return_value=False, side_effect=RuntimeError('ambiguous') if failure == 'exception' else None)
    monkeypatch.setattr(env.main, '_start_photo_background', start)
    result = body(asyncio.run(send(env)))
    assert result['fantasy_status'] == 'needs_support'
    env.restart()
    asyncio.run(send(env))
    assert start.await_count == 1 and order(env)['request']['text'] == SCENARIO


@pytest.mark.parametrize('sent', [[], [101]])
def test_background_marks_only_nonempty_delivery(env, monkeypatch, sent):
    create(env)
    env.spicy.claim_paid_fantasy(TG, CHAR, SCENARIO)
    monkeypatch.setattr(env.main, 'deliver_photo', AsyncMock(return_value=sent))
    monkeypatch.setattr(env.main, 'get_latest_photo_delivery', lambda tid: None)
    request = env.main.PhotoRequest(**env.spicy.parse_fantasy(SCENARIO))
    asyncio.run(env.main._run_photo_background(TG, TG, request, 'paid', charge='charge-1',
        amount=30, product='fantasy', character_id=CHAR, app_only=True))
    assert order(env)['status'] == ('delivered' if sent else 'generating')
    env.main.bot.refund_star_payment.assert_not_called()
    env.main.bot.send_message.assert_not_called()


@pytest.mark.parametrize('failure', [None, 'telegram', 'telegram_false', 'ledger', 'ledger_false', 'receipt'])
def test_refunded_only_after_confirmed_refund_and_ledger(env, monkeypatch, failure):
    create(env)
    env.spicy.claim_paid_fantasy(TG, CHAR, SCENARIO)
    if failure == 'telegram':
        env.main.bot.refund_star_payment.side_effect = RuntimeError('no confirmation')
    if failure == 'telegram_false':
        env.main.bot.refund_star_payment.return_value = False
    if failure in ('ledger', 'ledger_false'):
        monkeypatch.setattr(env.main, 'record_refund', Mock(return_value=False,
            side_effect=RuntimeError('ledger failed') if failure == 'ledger' else None))
    if failure == 'receipt':
        env.main.bot.send_message.side_effect = [RuntimeError('receipt failed'), None]
    asyncio.run(env.main._maybe_refund_paid_photo(TG, TG, 'charge-1', 30, 'fantasy'))
    expected = 'refunded' if failure in (None, 'receipt') else 'generating'
    assert order(env)['status'] == expected
    assert not env.spicy.claim_paid_fantasy(TG, CHAR, SCENARIO)['claimed']
    if expected == 'refunded':
        with env.sessions() as session:
            refund = session.scalar(select(env.StarTransaction).where(
                env.StarTransaction.transaction_type == 'refund'))
            assert refund.stars == -30 and refund.telegram_charge_id == 'refund:charge-1'


def test_obsolete_bot_handler_redirects_without_touching_entitlement(env, monkeypatch):
    env.dialogs.DialogStore('fantasy_pending')[TG] = ('legacy', 30)
    redirect = AsyncMock()
    monkeypatch.setattr(env.main, '_redirect_bot_chat', redirect)
    message = payment_message()
    asyncio.run(env.main._handle_fantasy_input(message))
    redirect.assert_awaited_once_with(message)
    assert env.dialogs.DialogStore('fantasy_pending')[TG] == ['legacy', 30]
    env.main._start_photo_background.assert_not_called()
