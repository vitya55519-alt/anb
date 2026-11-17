"""Dispatcher regressions for the app-only conversation boundary.

Run with a disposable DATABASE_URL, fake TELEGRAM_TOKEN and
PYTHON_DOTENV_DISABLED=1, as with the other main-importing integration tests.
Telegram requests are captured; providers, downloads and spending are forbidden.
"""
import asyncio
import ast
import inspect
import itertools
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from aiogram import types
from sqlalchemy import func, select

import main
from models.app_models import Message, ProductEvent
from services import couple_service, draft_service, live_situation_service, silence_ladder
from services.db import SessionLocal


_IDS = itertools.count(887100000)
CALLBACKS = (
    'thought:show:1', 'thought:hide:1', 'thought:show:bad',
    'story:hook:left', 'quest:route:intro:left', 'quest:beat:intro:0',
    'quest:list', 'quest:view:intro', 'quest:locked:intro', 'quest:done',
    'qte:pick:event:1', 'draft:unlock:42', 'live:unlock:42',
    'life:cafe', 'questday:claim:walk', 'photo:selfie', 'photo_menu:open',
    'photo_feedback:42:like', 'retry_photo:selfie', 'locked:lingerie',
    'video:animate:42', 'video:animate_last', 'video:circle',
    'videopreset:42:wave', 'libvideo:42', 'gallery:view:42',
    'gallery:dl:42', 'gallery:animate:42', 'gallery:page:1',
    'cosplay:start', 'cosplay:maid', 'custom:start', 'custom:place:cafe',
    'private_photo:start', 'private_photo:go:cat:type:loc:mood',
    'private_photo:hotpass:day', 'private_cosplay:start',
    'private_cosplay:go:maid:bed', 'private_voice:go:cat:type:loc:mood',
    'private_gallery:view', 'room:bedroom', 'room_locked:bedroom',
    'apt_action:bedroom:talk', 'date:walk', 'date_locked:dinner',
    'gift:flowers', 'spicy:set:one', 'spicy:gift:one', 'spicy:fantasy',
    'onboard:meet',
)


def _message(tid, **fields):
    return types.Message.model_validate({
        'message_id': 1, 'date': 1700000000,
        'chat': {'id': tid, 'type': 'private'},
        'from': {'id': tid, 'is_bot': False, 'first_name': 'Tester', 'language_code': 'ru'},
        **fields,
    })


@pytest.fixture
def bot_env(monkeypatch):
    tid, owner = next(_IDS), next(_IDS)
    for user_id in (tid, owner):
        main.ensure_user(user_id, 'Tester', language_code='ru')
        main.accept_consent(user_id)
        main.set_user_character(user_id, 'selected_girl')
    monkeypatch.setattr(main, 'ADMIN_TELEGRAM_IDS', {owner})
    monkeypatch.setattr(main, 'PUBLIC_BASE_URL', 'https://app.example.test/')
    monkeypatch.setattr(main, 'BOT_CHAT_REDIRECT', False)  # no legacy opt-out
    sent = []

    async def request(bot, method, **kwargs):
        sent.append(method)
        name = type(method).__name__
        assert name in {'SendMessage', 'AnswerCallbackQuery', 'EditMessageText',
                        'EditMessageReplyMarkup', 'DeleteMessage'}, name
        if name in {'SendMessage', 'EditMessageText'}:
            return _message(int(method.chat_id), text=method.text)
        return True

    monkeypatch.setattr(main.bot.session, 'make_request', request)
    forbidden = []

    def deny(*args, **kwargs):
        forbidden.append((args, kwargs))
        raise AssertionError('Conversation/provider/charge path reached')

    for name in ('anna_reply', 'transcribe', 'synthesize_bytes', 'react_to_photo',
                 'handle_photo_request', '_start_photo_background', '_react_to_user_photo',
                 '_handle_fantasy_input', '_feature_scene_turn', '_tap_her_button'):
        monkeypatch.setattr(main, name, AsyncMock(side_effect=deny))
    for name in ('spend_peaches', 'spend_photo_peaches', 'consume_photo_credit',
                 'consume_offer', 'can_send_message', 'save_message', 'cancel_active_wake'):
        monkeypatch.setattr(main, name, Mock(side_effect=deny))
    monkeypatch.setattr(main.bot, 'download', AsyncMock(side_effect=deny))
    monkeypatch.setattr(couple_service, 'check_anniversary', Mock(side_effect=deny))
    monkeypatch.setattr(draft_service, 'unlock', Mock(side_effect=deny))
    monkeypatch.setattr(live_situation_service, 'unlock_photo', AsyncMock(side_effect=deny))

    async def feed(user_id=tid, callback=None, **fields):
        msg = _message(user_id, **fields)
        if callback is None:
            update = types.Update(update_id=1, message=msg)
        else:
            # The callback message is authored by the BOT, never the tapper.
            bot_msg = msg.model_copy(update={
                'from_user': types.User(id=999001, is_bot=True, first_name='Bot')})
            update = types.Update(update_id=1, callback_query=types.CallbackQuery(
                id='callback', from_user=msg.from_user, chat_instance='test',
                data=callback, message=bot_msg))
        await main.dp.feed_update(main.bot, update)

    yield SimpleNamespace(tid=tid, owner=owner, sent=sent, feed=feed)
    assert not forbidden, 'A forbidden call was swallowed by a legacy handler'


def _redirect(env, char='selected_girl', *, english=False):
    messages = [m for m in env.sent if type(m).__name__ == 'SendMessage']
    assert len(messages) == 1
    msg = messages[0]
    assert msg.text == ('Chat is in the app.' if english else 'Общение — в приложении.')
    button = msg.reply_markup.inline_keyboard[0][0]
    assert button.callback_data is None
    url = urlsplit(button.web_app.url)
    assert url.scheme == 'https' and url.netloc == 'app.example.test'
    assert url.path == '/webapp'
    assert parse_qs(url.query) == {'open': ['chat'], 'char': [char]}
    assert not any(type(m).__name__.startswith('Edit') for m in env.sent)


def _counts(tid):
    uid = main.ensure_user(tid)
    with SessionLocal() as session:
        return tuple(session.scalar(select(func.count()).select_from(model).where(model.user_id == uid))
                     for model in (Message, ProductEvent))


@pytest.mark.parametrize('owner', [False, True])
@pytest.mark.parametrize('fields', [
    {'text': 'расскажи дальше'}, {'text': 'пришли фото'}, {'text': 'давай'},
    {'voice': {'file_id': 'voice', 'file_unique_id': 'voice', 'duration': 4}},
    {'photo': [{'file_id': 'photo', 'file_unique_id': 'photo', 'width': 20, 'height': 20}]},
    {'video': {'file_id': 'video', 'file_unique_id': 'video', 'width': 20, 'height': 20, 'duration': 1}},
    {'document': {'file_id': 'doc', 'file_unique_id': 'doc', 'mime_type': 'image/png'}},
])
def test_dialogue_does_not_generate_download_or_count(bot_env, owner, fields):
    tid = bot_env.owner if owner else bot_env.tid
    main._photo_offer_pending[tid] = 9999999999
    before = _counts(tid)
    asyncio.run(bot_env.feed(tid, **fields))
    _redirect(bot_env)
    assert _counts(tid) == before


@pytest.mark.parametrize('owner', [False, True])
@pytest.mark.parametrize('callback', CALLBACKS)
def test_old_callbacks_redirect_before_side_effects(bot_env, owner, callback):
    tid = bot_env.owner if owner else bot_env.tid
    main._thought_cards[1] = (tid, 'Girl', 'SECRET THOUGHT MUST NOT LEAK')
    before = _counts(tid)
    asyncio.run(bot_env.feed(tid, callback=callback))
    _redirect(bot_env)
    assert _counts(tid) == before
    assert sum(type(m).__name__ == 'AnswerCallbackQuery' for m in bot_env.sent) == 1


@pytest.mark.parametrize(('callback', 'char'), [
    ('life_reply:milana_01:tell_more', 'milana_01'),
    ('life_reply:girl&open=shop:tell_more', 'girl&open=shop'),
    ('mychar:chat:custom_123', 'custom_123'),
    ('character:view:amira_01', 'amira_01'),
    ('onboard:character:ayla_01', 'ayla_01'),
    ('character:anna', 'anna_01'), ('character:alena_soon', 'alena_01'),
])
def test_callback_character_is_not_the_selected_character(bot_env, callback, char):
    asyncio.run(bot_env.feed(callback=callback))
    _redirect(bot_env, char)
    assert main.get_user_character(bot_env.tid) == 'selected_girl'


def test_ladder_destination_survives_old_store(bot_env):
    silence_ladder.note_chips(bot_env.tid, 'ladder_girl', ['Continue'])
    asyncio.run(bot_env.feed(callback='ladder_chip:0'))
    _redirect(bot_env, 'ladder_girl')


@pytest.mark.parametrize('callback', ['ladder_chip:999', 'ladder_chip:bad', 'life_reply:'])
def test_missing_legacy_destination_falls_back_safely(bot_env, callback):
    asyncio.run(bot_env.feed(callback=callback))
    _redirect(bot_env)


@pytest.mark.parametrize('key', ['chat', 'photo', 'stories', 'apartment', 'gift', 'date',
                                 'video', 'circle', 'quest', 'characters'])
def test_reply_keyboard_routes_to_app(bot_env, key):
    asyncio.run(bot_env.feed(text=main.kb_pair(key)[0]))
    _redirect(bot_env)


@pytest.mark.parametrize('command', ['/plans', '/today', '/photo', '/selfie', '/stories',
                                     '/quests', '/gallery', '/photos'])
def test_conversational_commands_route_to_app(bot_env, command):
    asyncio.run(bot_env.feed(text=command, entities=[{'type': 'bot_command', 'offset': 0, 'length': len(command)}]))
    _redirect(bot_env)


def test_missing_public_url_never_falls_back_to_chat(bot_env, monkeypatch):
    monkeypatch.setattr(main, 'PUBLIC_BASE_URL', '')
    asyncio.run(bot_env.feed(text='hello'))
    msg = bot_env.sent[0]
    assert msg.text.startswith('Общение — в приложении.')
    assert msg.reply_markup is None


def test_english_and_url_encoding(bot_env):
    main.update_user_settings(bot_env.tid, ui_lang='en')
    main.set_user_character(bot_env.tid, 'girl /?&=')
    asyncio.run(bot_env.feed(text='hello'))
    _redirect(bot_env, 'girl /?&=', english=True)


def test_owner_kitchen_text_keeps_fsm_priority(bot_env, monkeypatch):
    sess = {'mode': 'add', 'step': 'display_name', 'draft': {}}
    monkeypatch.setitem(main._character_card_edit_sessions, bot_env.owner, sess)
    # Even a stale paid fantasy must not steal a kitchen input.
    main._fantasy_pending[bot_env.owner] = ('paid-charge', 100)
    asyncio.run(bot_env.feed(bot_env.owner, text='New name'))
    assert sess['draft']['display_name'] == 'New name'
    assert sess['step'] == 'gender'
    assert 'Шаг 3/5' in bot_env.sent[-1].text


def test_owner_qr_photo_is_a_service_input(bot_env, monkeypatch):
    monkeypatch.setitem(main._payment_method_edit_sessions, bot_env.owner,
                        {'mode': 'edit', 'field': 'qr', 'method_id': 123})
    save = Mock()
    monkeypatch.setattr(main, 'update_payment_method', save)
    monkeypatch.setattr(main, '_admin_payment_summary', lambda _: 'summary')
    monkeypatch.setattr(main, 'admin_payment_keyboard', lambda _: None)
    asyncio.run(bot_env.feed(bot_env.owner, photo=[
        {'file_id': 'qr', 'file_unique_id': 'qr', 'width': 20, 'height': 20}]))
    save.assert_called_once_with(123, qr_photo_file_id='qr')
    assert 'QR сохранён' in bot_env.sent[-1].text


def test_owner_library_import_still_accepts_photos(bot_env, monkeypatch):
    sess = {'photos': [], 'preview': False}
    monkeypatch.setitem(main._library_import_sessions, bot_env.owner, sess)
    monkeypatch.setattr(main, '_library_photo_is_allowed', AsyncMock(return_value=(True, 'disabled')))
    refresh = AsyncMock()
    monkeypatch.setattr(main, '_library_refresh_status', refresh)
    asyncio.run(bot_env.feed(bot_env.owner, photo=[
        {'file_id': 'library', 'file_unique_id': 'library', 'width': 20, 'height': 20}]))
    assert sess['photos'][0]['file_id'] == 'library'
    refresh.assert_awaited_once()


def test_support_pending_takes_priority_over_fantasy(bot_env, monkeypatch):
    main._support_pending[bot_env.tid] = 1
    main._fantasy_pending[bot_env.tid] = ('paid-charge', 100)
    deliver = AsyncMock(return_value=True)
    monkeypatch.setattr(main, '_deliver_support_message', deliver)
    asyncio.run(bot_env.feed(text='Help with payment'))
    assert deliver.await_args.args[1] == 'Help with payment'
    assert bot_env.tid not in main._support_pending
    assert list(main._fantasy_pending[bot_env.tid]) == ['paid-charge', 100]


def test_owner_support_reply_still_delivers(bot_env, monkeypatch):
    deliver = AsyncMock()
    monkeypatch.setattr(main, '_deliver_admin_reply', deliver)
    ticket = _message(bot_env.owner, text='\U0001f6df Support\nuser: 12345')
    asyncio.run(bot_env.feed(bot_env.owner, text='Resolved', reply_to_message=ticket.model_dump()))
    assert deliver.await_args.args[1] == 12345


def test_paid_fantasy_is_not_consumed_or_generated_by_text(bot_env):
    main._fantasy_pending[bot_env.tid] = ('paid-charge', 100)
    asyncio.run(bot_env.feed(text='outfit and place'))
    _redirect(bot_env)
    assert list(main._fantasy_pending[bot_env.tid]) == ['paid-charge', 100]


@pytest.mark.parametrize('kind', ['text', 'voice', 'photo', 'callback'])
def test_consent_gate_is_preserved(bot_env, monkeypatch, kind):
    monkeypatch.setattr(main, 'has_accepted', lambda _: False)
    fields = {
        'text': {'text': 'hi'},
        'voice': {'voice': {'file_id': 'v', 'file_unique_id': 'v', 'duration': 1}},
        'photo': {'photo': [{'file_id': 'p', 'file_unique_id': 'p', 'width': 1, 'height': 1}]},
        'callback': {'callback': 'thought:show:1'},
    }[kind]
    asyncio.run(bot_env.feed(**fields))
    msg = [m for m in bot_env.sent if type(m).__name__ == 'SendMessage'][0]
    assert '/start' in msg.text and '18+' in msg.text
    assert msg.reply_markup == main.consent_keyboard()


def test_consent_acceptance_callback_still_updates_consent(bot_env, monkeypatch):
    tid = next(_IDS)
    main.ensure_user(tid, 'New tester')
    assert not main.has_accepted(tid)
    monkeypatch.setattr(main, 'apply_first_start_bonuses', lambda _: {'credits': 0, 'trial_days': 0})
    asyncio.run(bot_env.feed(tid, callback='consent:accept'))
    assert main.has_accepted(tid)
    assert main.is_adult_confirmed(tid)
    assert any(type(m).__name__ == 'EditMessageText' for m in bot_env.sent)


def test_age_confirmation_does_not_resume_a_paid_photo(bot_env):
    main._pending_adult_photo[bot_env.tid] = main.PhotoRequest(scene='selfie')
    asyncio.run(bot_env.feed(callback='age:yes'))
    assert main.is_adult_confirmed(bot_env.tid)
    assert bot_env.sent[-1].text == 'Общение — в приложении.'


def test_constructor_service_name_input_is_preserved(bot_env, monkeypatch):
    main._constructor_sessions[bot_env.tid] = {'await': 'name', 'params': {}}
    confirm = AsyncMock()
    monkeypatch.setattr(main, '_constructor_confirm', confirm)
    asyncio.run(bot_env.feed(text='Anna'))
    assert main._constructor_sessions[bot_env.tid]['params']['name'] == 'Anna'
    confirm.assert_awaited_once_with(bot_env.tid, bot_env.tid)


def test_idle_constructor_does_not_block_chat_redirect(bot_env):
    main._constructor_sessions[bot_env.tid] = {'await': None, 'params': {}}
    asyncio.run(bot_env.feed(text='hello'))
    _redirect(bot_env)


def test_payment_pack_still_grants_without_redirect(bot_env, monkeypatch):
    record = Mock()
    monkeypatch.setattr(main, 'record_payment', record)
    payload = next(iter(main.PEACH_PACK_STARS))
    asyncio.run(bot_env.feed(successful_payment={
        'currency': 'XTR', 'total_amount': main.PEACH_PACK_STARS[payload],
        'invoice_payload': payload, 'telegram_payment_charge_id': 'test-charge',
        'provider_payment_charge_id': 'test-provider',
    }))
    record.assert_called_once_with(bot_env.tid, payload, main.PEACH_PACK_STARS[payload], 'test-charge')
    assert 'персиков на счету' in bot_env.sent[-1].text


def test_payment_purchase_button_still_creates_invoice(bot_env, monkeypatch):
    invoice = AsyncMock()
    monkeypatch.setattr(main, 'send_stars_invoice', invoice)
    payload = next(iter(main.PEACH_PACK_STARS))
    asyncio.run(bot_env.feed(callback='buy:' + payload))
    assert invoice.await_args.args[-2:] == (payload, main.PEACH_PACK_STARS[payload])


def test_guard_excludes_service_callbacks(bot_env):
    handler = next(h for h in main.dp.callback_query.handlers if h.callback is main.app_only_callback)

    async def check():
        for data in ('admin:home', 'admin:grant', 'consent:accept', 'consent:privacy',
                     'age:yes', 'gift:claim', 'paymethod:1', 'platega:premium',
                     'walletpay:premium', 'autopay:menu', 'menu:support', 'buy:premium',
                     'constructor:buy', 'cbuild:name:next', 'libimp:save'):
            cq = types.CallbackQuery(id='test', from_user=_message(bot_env.tid).from_user,
                                     chat_instance='test', data=data)
            matched, _ = await handler.check(cq)
            assert not matched, data
    asyncio.run(check())


def test_thought_handler_itself_no_longer_reads_secret_content():
    src = inspect.getsource(main._thought_toggle)
    assert 'await app_only_callback(cq)' in src
    assert '_thought_cards.get' not in src and 'edit_text' not in src


def test_paid_welcome_is_saved_before_generic_notification(bot_env, monkeypatch):
    from services import chat_service, memory_service, paid_welcome, vip_offer

    uid = main.ensure_user(bot_env.tid)
    monkeypatch.setattr(main.asyncio, 'sleep', AsyncMock())
    monkeypatch.setattr(main, 'is_premium', lambda _: True)
    monkeypatch.setattr(vip_offer, 'open_loyalty', lambda *a: False)
    monkeypatch.setattr(vip_offer, 'info', lambda *a: {})
    monkeypatch.setattr(paid_welcome, 'ENABLED', True)
    monkeypatch.setattr(paid_welcome, 'unlocked_text', lambda *a: 'Purchase confirmed')
    monkeypatch.setattr(main, '_deliver_showcase_photo', AsyncMock())
    monkeypatch.setattr(main, 'save_message', memory_service.save_message)
    welcome = AsyncMock(return_value='Synthetic private welcome')
    monkeypatch.setattr(chat_service, 'paid_moment', welcome)
    notices = []

    def note(bot, tid, char, text, **kwargs):
        with SessionLocal() as session:
            rows = session.scalars(select(Message).where(Message.user_id == uid)).all()
            assert [(row.character_id, row.content) for row in rows] == [
                ('selected_girl', 'Synthetic private welcome')]
        notices.append((tid, char, text, kwargs))

    from services import app_ping
    monkeypatch.setattr(app_ping, 'note', note)
    asyncio.run(main._after_premium_paid(bot_env.tid, 'premium'))
    welcome.assert_awaited_once()
    assert notices == [(bot_env.tid, 'selected_girl', '', {'generic': True})]
    assert [method.text for method in bot_env.sent] == ['Purchase confirmed']


@pytest.mark.parametrize('source', ['telegram', 'local'])
def test_paid_showcase_photo_is_delivered_once_in_its_app_chat(bot_env, monkeypatch, tmp_path, source):
    import io
    from services import first_offer_service as fos, memory_service

    uid = main.ensure_user(bot_env.tid)
    body = b'synthetic-photo-original-bytes'
    path = tmp_path / 'showcase.png'
    path.write_bytes(body)
    fos.remember_photo(bot_env.tid, 'showcase_girl', 'owned-file' if source == 'telegram' else '',
                       str(path) if source == 'local' else '')
    monkeypatch.setattr(main.bot, 'download', AsyncMock(return_value=io.BytesIO(body)))
    monkeypatch.setattr(main, 'save_message', memory_service.save_message)
    media = Mock(return_value='saved-photo')
    monkeypatch.setattr(main.webapp_service, 'save_chat_media', media)
    notices = Mock()
    monkeypatch.setattr(main, '_app_ping', notices)
    asyncio.run(main._deliver_showcase_photo(bot_env.tid, uid, 'ru'))
    asyncio.run(main._deliver_showcase_photo(bot_env.tid, uid, 'ru'))
    media.assert_called_once_with(bot_env.tid, body, 'jpg' if source == 'telegram' else 'png',
                                  'image/jpeg' if source == 'telegram' else 'image/png')
    with SessionLocal() as session:
        rows = session.scalars(select(Message).where(Message.user_id == uid)).all()
        assert len(rows) == 1
        assert rows[0].character_id == 'showcase_girl'
        assert rows[0].media_kind == 'photo' and rows[0].media_url == '/webapp/media/saved-photo'
    assert not bot_env.sent
    notices.assert_called_once_with(bot_env.tid, 'showcase_girl', fos.deliver_caption('ru'), 'photo')


def test_paid_showcase_save_failure_keeps_the_owed_photo(bot_env, monkeypatch):
    import io
    from services import first_offer_service as fos

    uid = main.ensure_user(bot_env.tid)
    fos.remember_photo(bot_env.tid, 'showcase_girl', 'owned-file', '')
    monkeypatch.setattr(main.bot, 'download', AsyncMock(return_value=io.BytesIO(b'photo')))
    monkeypatch.setattr(main.webapp_service, 'save_chat_media', Mock(side_effect=OSError('synthetic')))
    notices = Mock()
    monkeypatch.setattr(main, '_app_ping', notices)
    asyncio.run(main._deliver_showcase_photo(bot_env.tid, uid, 'ru'))
    assert fos.take_pending_photo(bot_env.tid) == {'char': 'showcase_girl', 'fid': 'owned-file', 'path': ''}
    assert not bot_env.sent
    notices.assert_not_called()


def test_redirect_boundary_precedes_normal_text_pipeline():
    tree = ast.parse(Path(main.__file__).read_text(encoding='utf-8'))
    text = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'text_message')
    source = ast.get_source_segment(Path(main.__file__).read_text(encoding='utf-8'), text)
    assert '_anniversary_push' not in source
    assert source.index('await _redirect_bot_chat(message)') < source.index('touch_activity(')
    assert "track_event(uid, 'chat_user_message'" not in source
