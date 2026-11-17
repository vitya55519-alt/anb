import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

import main
from models.app_models import ChatMedia, Message, User
from models.relationship_models import UserCharacterRelationship
from models.waifu_models import Base
from services import couple_service, db, gamification_service, webapp_service

TG = 915907
CHAR = 'anna_01'


@pytest.fixture
def store(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + (tmp_path / 'rewards.sqlite').as_posix(),
                           connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    original = db.SessionLocal
    for name, module in list(sys.modules.items()):
        if (name.startswith('services.') or name == 'main') and getattr(module, 'SessionLocal', None) is original:
            monkeypatch.setattr(module, 'SessionLocal', sessions)
    monkeypatch.setattr(db, 'engine', engine)
    monkeypatch.setattr(webapp_service, 'APP_MEDIA_DIR', tmp_path / 'media')
    with sessions() as session:
        user = User(telegram_id=str(TG), name='Test', selected_character='maria',
                    voice_enabled=True, voice_style='test', ui_lang='ru')
        session.add(user)
        session.flush()
        uid = user.id
        session.add(UserCharacterRelationship(user_id=uid, character_id=CHAR,
                    first_interaction_at=datetime.utcnow() - timedelta(days=8)))
        session.commit()
    monkeypatch.setattr(main, 'bot', SimpleNamespace(send_message=AsyncMock(), send_voice=AsyncMock()))
    monkeypatch.setattr(main, '_app_ping', Mock())
    monkeypatch.setattr(main, 'synthesize_bytes', AsyncMock(return_value=b'test voice'))
    monkeypatch.setattr(main, '_start_photo_background', AsyncMock(return_value=True))
    monkeypatch.setattr(main, 'record_user_message', AsyncMock())
    monkeypatch.setattr(main, 'track_event', Mock())
    monkeypatch.setattr(main, 'user_lang', lambda tid: 'ru')
    try:
        yield SimpleNamespace(sessions=sessions, uid=uid, engine=engine)
    finally:
        monkeypatch.undo()
        for name, module in list(sys.modules.items()):
            if (name.startswith('services.') or name == 'main') and getattr(module, 'SessionLocal', None) is sessions:
                module.SessionLocal = original
        engine.dispose()


def rows(store, model):
    with store.sessions() as session:
        return list(session.scalars(select(model)))


@pytest.mark.parametrize('voice', ['enabled', 'disabled', 'failed'])
def test_paid_narration_is_one_app_row_even_without_voice(store, voice):
    if voice == 'disabled':
        with store.sessions() as session:
            session.get(User, store.uid).voice_enabled = False
            session.commit()
    if voice == 'failed':
        main.synthesize_bytes.side_effect = RuntimeError('test provider unavailable')
    asyncio.run(main._send_voice_note(TG, TG, 'Test reward', app_only=True, character_id=CHAR))
    message, = rows(store, Message)
    assert message.character_id == CHAR and message.content == 'Test reward'
    assert message.media_kind == ('voice' if voice == 'enabled' else None)
    assert len(rows(store, ChatMedia)) == int(voice == 'enabled')
    if voice == 'enabled':
        media, = rows(store, ChatMedia)
        assert media.data == b'test voice'
        assert message.media_url == '/webapp/media/' + media.filename
    main.bot.send_message.assert_not_called()
    main.bot.send_voice.assert_not_called()
    main._app_ping.assert_called_once_with(TG, CHAR, 'Test reward')
    assert main.synthesize_bytes.await_count == int(voice != 'disabled')


def test_photo_background_saves_each_frame_once_without_legacy_mirror(store, monkeypatch):
    data = b'test png bytes'
    async def deliver(bot, chat_id, tid, request, delivery_type, **kwargs):
        assert delivery_type == 'paid' and kwargs['character_id'] == CHAR
        for delivery_id in (11, 12):
            await kwargs['app_delivery'](data + bytes([delivery_id]), 'image/png', delivery_id, 'Test photo')
        return [11, 12]
    monkeypatch.setattr(main, 'deliver_photo', AsyncMock(side_effect=deliver))
    monkeypatch.setattr(main, 'is_custom_character', lambda _: False)
    monkeypatch.setattr(main, 'get_relationship_level', lambda *args: 3)
    monkeypatch.setattr(main, '_mirror_delivery_to_chat_history', AsyncMock())
    monkeypatch.setattr(main, '_photo_progress_ping', AsyncMock())
    monkeypatch.setattr(couple_service, 'add_album_milestone', Mock())
    monkeypatch.setattr(main, '_photo_jobs', {TG: object()})
    asyncio.run(main._run_photo_background(TG, TG, main.PhotoRequest(scene='cafe'), 'paid',
                                          character_id=CHAR, app_only=True))
    assert len(rows(store, Message)) == len(rows(store, ChatMedia)) == 2
    assert all(row.character_id == CHAR for row in rows(store, Message))
    assert [row.data for row in rows(store, ChatMedia)] == [data + b'\x0b', data + b'\x0c']
    couple_service.add_album_milestone.assert_called_once_with(store.uid, 3, 12)
    main._mirror_delivery_to_chat_history.assert_not_called()
    main._photo_progress_ping.assert_not_called()
    main.bot.send_message.assert_not_called()
    assert TG not in main._photo_jobs


def test_date_reward_keeps_relationship_and_app_photo_destination(store, monkeypatch):
    monkeypatch.setattr(main, 'get_user_character', lambda tid: CHAR)
    monkeypatch.setattr(gamification_service, 'completed_date_ids', lambda tid: [])
    unlock = Mock()
    monkeypatch.setattr(gamification_service, 'unlock_achievement', unlock)
    date = SimpleNamespace(id='walk', affection=2, text='Test date', scene='cafe')
    asyncio.run(main._deliver_date_reward(TG, TG, 'Test', date))
    message, = rows(store, Message)
    assert message.character_id == CHAR and message.content == date.text
    main.record_user_message.assert_awaited_once_with(TG, 'Test', relationship=2, intimacy=1,
        event_type='date', reason='date:walk', character_id=CHAR)
    unlock.assert_called_once_with(TG, 'first_date')
    call = main._start_photo_background.await_args
    assert call.args[:2] == (TG, TG) and call.args[3] == 'story'
    assert call.args[2].scene == 'cafe'
    assert call.kwargs == {'character_id': CHAR, 'app_only': True}
    main.bot.send_message.assert_not_called()
    main.bot.send_voice.assert_not_called()


@pytest.mark.parametrize('special_scene', [False, True])
@pytest.mark.parametrize('save_fails', [False, True])
def test_level_ceremony_saves_before_ping_and_keeps_photo_in_app(store, monkeypatch, special_scene, save_fails):
    from services import branch_service, chat_guest_service

    monkeypatch.setattr(main.asyncio, 'sleep', AsyncMock())
    monkeypatch.setattr(chat_guest_service, 'guest_marital', Mock(return_value='single'))
    monkeypatch.setattr(main, '_relationship_branch', Mock(return_value=None))
    monkeypatch.setattr(main, '_level_up_line', Mock(return_value='Test level'))
    photo = main.PhotoRequest(scene='cafe', mood='romantic')
    monkeypatch.setattr(main, '_level_up_scene', Mock(
        return_value=('Test celebration', photo) if special_scene else None))
    monkeypatch.setattr(couple_service, 'assign_pet_name', Mock(return_value='Test nickname'))
    monkeypatch.setattr(branch_service, 'maybe_offer_fork', Mock())
    monkeypatch.setattr(branch_service, 'mark_left_him', Mock())

    def ping(tid, character, text):
        entry, = rows(store, Message)
        assert (tid, character) == (TG, CHAR)
        assert (entry.user_id, entry.character_id, entry.content) == (store.uid, CHAR, text)

    main._app_ping.side_effect = ping
    if save_fails:
        monkeypatch.setattr(main, 'save_message', Mock(side_effect=RuntimeError('test storage unavailable')))
    asyncio.run(main._on_relationship_stage_up(TG, 'acquaintance', 'close', CHAR))
    main.bot.send_message.assert_not_called()
    main.bot.send_voice.assert_not_called()
    chat_guest_service.guest_marital.assert_called_once_with(TG, CHAR)
    main._relationship_branch.assert_called_once_with(TG, CHAR)
    couple_service.assign_pet_name.assert_called_once_with(TG)
    branch_service.mark_left_him.assert_not_called()
    if save_fails:
        assert rows(store, Message) == []
        main._app_ping.assert_not_called()
        main._start_photo_background.assert_not_called()
        branch_service.maybe_offer_fork.assert_not_called()
        main.track_event.assert_not_called()
        return
    entry, = rows(store, Message)
    assert 'Test level' in entry.content and 'Test nickname' in entry.content
    main._app_ping.assert_called_once_with(TG, CHAR, entry.content)
    branch_service.maybe_offer_fork.assert_called_once_with(store.uid, CHAR, taken=False)
    main.track_event.assert_called_once_with(store.uid, 'relationship_ceremony_sent',
                                            metadata={'level': 3}, character_id=CHAR)
    main._start_photo_background.assert_awaited_once()
    call = main._start_photo_background.await_args
    assert call.args[:2] == (TG, TG) and call.args[3] == 'story'
    assert call.kwargs == {'character_id': CHAR, 'app_only': True}
    if special_scene:
        assert call.args[2] is photo and 'Test celebration' in entry.content
    else:
        assert call.args[2].scene == 'selfie' and call.args[2].mood == 'romantic'


def payment_message(payload):
    return SimpleNamespace(from_user=SimpleNamespace(id=TG, first_name='Test'),
        chat=SimpleNamespace(id=TG), answer=AsyncMock(),
        successful_payment=SimpleNamespace(invoice_payload=payload, total_amount=30,
                                          telegram_payment_charge_id='test-paid-charge'))


@pytest.mark.parametrize('payload,product', [('gift:test', 'gift'), ('spicy:test', 'spicy_set'),
                                            ('pgift:test', 'private_gift'), ('date:test', 'date')])
def test_paid_rewards_save_app_narration_without_bot_dialogue(store, monkeypatch, payload, product):
    item = SimpleNamespace(id='test', affection=2, text='Test reward', text_en='Test reward',
                           reaction='Test reward', scene='cafe', mood='warm')
    monkeypatch.setattr(main.gifts_service, 'get', lambda _: item)
    monkeypatch.setattr(main.spicy_service, 'get_spicy_set', lambda _: item)
    monkeypatch.setattr(main.spicy_service, 'get_private_gift', lambda _: item)
    monkeypatch.setattr(main.dates_service, 'get', lambda _: item)
    monkeypatch.setattr(gamification_service, 'completed_date_ids', lambda _: [])
    monkeypatch.setattr(gamification_service, 'unlock_achievement', Mock())
    monkeypatch.setattr(main, 'record_payment', Mock())
    message = payment_message(payload)
    asyncio.run(main.successful_payment(message))
    main.record_payment.assert_called_once_with(TG, product, 30, 'test-paid-charge')
    entry, = rows(store, Message)
    assert entry.character_id == 'maria' and entry.content == 'Test reward'
    assert entry.media_kind == 'voice'
    message.answer.assert_not_called()
    main.bot.send_message.assert_not_called()
    main.bot.send_voice.assert_not_called()
    if product != 'gift':
        assert main._start_photo_background.await_args.kwargs['app_only'] is True
        assert main._start_photo_background.await_args.kwargs['character_id'] == 'maria'
        if product != 'date':
            assert main._start_photo_background.await_args.kwargs['charge'] == 'test-paid-charge'
            assert main._start_photo_background.await_args.args[3] == 'paid'


def test_paid_gallery_uses_exact_original_and_source_character(store, monkeypatch):
    from models.photo_models import PhotoDelivery
    original = b'\x89PNG\r\n\x1a\noriginal paid gallery bytes'
    with store.sessions() as session:
        photo = PhotoDelivery(user_id=store.uid, character_id=CHAR, scene='cafe',
                              delivery_type='paid', full_resolution_bytes=original)
        session.add(photo)
        session.commit()
        delivery_id = photo.id
    monkeypatch.setattr(main, 'record_payment', Mock())
    message = payment_message(f'gallery_dl:{delivery_id}')
    asyncio.run(main.successful_payment(message))
    entry, = rows(store, Message)
    media, = rows(store, ChatMedia)
    assert entry.character_id == CHAR and entry.media_kind == 'photo'
    assert entry.media_url == '/webapp/media/' + media.filename
    assert media.data == original and media.content_type == 'image/png'
    message.answer.assert_not_called()
    main.bot.send_message.assert_not_called()
    main._start_photo_background.assert_not_called()
    main.synthesize_bytes.assert_not_called()


def test_paid_undress_keeps_grant_for_app_without_automatic_bot_generation(store, monkeypatch):
    from services import undress_credits
    monkeypatch.setattr(main, 'handle_photo_request', AsyncMock())
    main._pending_undress_photo[TG] = main.PhotoRequest(scene='lingerie')
    message = payment_message('undress_one')
    asyncio.run(main.successful_payment(message))
    assert undress_credits.balance(TG) == 1
    assert TG not in main._pending_undress_photo
    main.handle_photo_request.assert_not_called()
    main._start_photo_background.assert_not_called()
    assert 'приложении' in message.answer.await_args.args[0]


def test_media_database_failure_cannot_report_durable_success(store, monkeypatch):
    def fail_commit(session):
        raise RuntimeError('test database unavailable')
    event.listen(store.sessions, 'before_commit', fail_commit)
    try:
        with pytest.raises(RuntimeError, match='database unavailable'):
            webapp_service.save_chat_media(TG, b'paid content', 'jpg', 'image/jpeg')
        assert rows(store, ChatMedia) == []
    finally:
        event.remove(store.sessions, 'before_commit', fail_commit)


def test_anniversary_is_atomic_and_not_duplicated_by_parallel_replies(store):
    with ThreadPoolExecutor(max_workers=4) as pool:
        result = list(pool.map(lambda _: couple_service.check_anniversary(store.uid, CHAR), range(4)))
    assert result.count(7) == 1 and result.count(None) == 3
    message, = rows(store, Message)
    assert message.character_id == CHAR and message.origin == 'anniversary'
    assert '7 дней' in message.content
    with store.sessions() as session:
        assert session.get(User, store.uid).anniversaries == '7'
        assert session.get(User, store.uid).chat_used == 0


def test_anniversary_does_not_use_another_characters_start_date(store):
    assert couple_service.check_anniversary(store.uid, 'maria') is None
    assert rows(store, Message) == []
    assert couple_service.check_anniversary(store.uid, CHAR, 'en') == 7
    assert rows(store, Message)[0].content.startswith('We have been together for 7 days.')


def test_anniversary_storage_failure_does_not_consume_milestone(store):
    def fail_commit(session):
        raise RuntimeError('test write failure')
    event.listen(store.sessions, 'before_commit', fail_commit)
    try:
        with pytest.raises(RuntimeError):
            couple_service.check_anniversary(store.uid, CHAR)
        assert rows(store, Message) == []
        with store.sessions() as session:
            assert not session.get(User, store.uid).anniversaries
    finally:
        event.remove(store.sessions, 'before_commit', fail_commit)
    assert couple_service.check_anniversary(store.uid, CHAR) == 7


def test_anniversary_wrapper_schedules_only_success_and_pings_after_save(store, monkeypatch):
    from aiohttp import web
    monkeypatch.setattr(main.asyncio, 'sleep', AsyncMock())
    unlock = Mock()
    monkeypatch.setattr(gamification_service, 'unlock_achievement', unlock)
    pending = []
    monkeypatch.setattr(main, '_spawn_background', pending.append)
    turn = AsyncMock(return_value=web.json_response({'ok': True, 'reply': 'Test reply'}))

    async def run():
        await main._pings_app_reply(turn)(TG, {}, CHAR, 'hello')
        assert len(pending) == 1
        main._app_ping.reset_mock()
        def ping(tid, cid, text):
            message, = rows(store, Message)
            assert message.character_id == cid == CHAR
        main._app_ping.side_effect = ping
        await pending.pop()
        main._app_ping.assert_called_once_with(TG, CHAR, '')
        turn.return_value = web.json_response({'ok': False, 'error': 'limit'}, status=429)
        await main._pings_app_reply(turn)(TG, {}, CHAR, 'hello')
        assert not pending
    asyncio.run(run())
    unlock.assert_called_once_with(TG, 'anniv_7')
    main.bot.send_message.assert_not_called()
    main.track_event.assert_called_once_with(store.uid, 'anniversary_celebrated', metadata={'days': 7})
