import asyncio
import json
import sys
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from models.app_models import Base, Message, User
from services import daily_limit, db, memory_service, story_hooks


@pytest.fixture
def store(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + (tmp_path / 'actions.db').as_posix(),
                           connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    original = db.SessionLocal
    monkeypatch.setattr(db, 'SessionLocal', factory)
    monkeypatch.setattr(memory_service, 'SessionLocal', factory)
    with factory() as session:
        session.add_all([User(id=1, telegram_id='991001'), User(id=2, telegram_id='991002')])
        session.commit()
    try:
        yield factory
    finally:
        # api imports main after db is patched, so its services can capture factory.
        # Restore explicit patches first (including main.SessionLocal), then aliases.
        monkeypatch.undo()
        for name, module in list(sys.modules.items()):
            if (name.startswith('services.') or name == 'main') and getattr(module, 'SessionLocal', None) is factory:
                module.SessionLocal = original
        engine.dispose()


def seed_story(key='confession'):
    story = story_hooks.get(key)
    return memory_service.save_message(1, 'anna_01', 'assistant', story.text_ru,
        actions=[{'type': 'story_hook', 'label': story.a.label_ru,
                  'story_key': story.key, 'choice': 'a'}])


def test_story_choice_saves_both_lines_and_consumes_once(store):
    mid = seed_story()
    out = story_hooks.choose_in_app(1, 'anna_01', mid, 0, 'ru')
    assert out['ok'] and out['reply'] == story_hooks.get('confession').a.reply_ru
    with store() as session:
        messages = session.scalars(select(Message).order_by(Message.id)).all()
        assert [m.role for m in messages] == ['assistant', 'user', 'assistant']
        assert messages[0].actions_json is None
        assert messages[1].content == out['user_text']
        assert session.get(User, 1).chat_used == 1
    assert story_hooks.choose_in_app(1, 'anna_01', mid, 0, 'ru')['error'] == 'not_found'


@pytest.mark.parametrize('uid,cid,index', [(2, 'anna_01', 0), (1, 'maria', 0),
                                          (1, 'anna_01', -1), (1, 'anna_01', 9)])
def test_story_action_cannot_cross_owner_character_or_index(store, uid, cid, index):
    mid = seed_story()
    assert not story_hooks.choose_in_app(uid, cid, mid, index, 'ru')['ok']
    with store() as session:
        assert len(session.scalars(select(Message)).all()) == 1
        assert session.get(Message, mid).actions_json


def test_last_daily_turn_cannot_be_spent_twice(store, monkeypatch):
    monkeypatch.setattr(daily_limit, 'DAILY_CAP', 30)
    monkeypatch.setattr(daily_limit, 'CHAT_MSGS_PER_DAY', 30)
    with store() as session:
        user = session.get(User, 1)
        user.chat_day = daily_limit.msk_today()
        user.chat_used = 29
        session.commit()
    first, second = seed_story(), seed_story('rain')
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda mid: story_hooks.choose_in_app(1, 'anna_01', mid, 0, 'ru'),
                                 [first, second]))
    assert sum(out['ok'] for out in outcomes) == 1
    assert [out['error'] for out in outcomes if not out['ok']] == ['limit']
    with store() as session:
        assert session.get(User, 1).chat_used == 30


def test_story_double_click_only_saves_one_pair(store):
    mid = seed_story()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: story_hooks.choose_in_app(1, 'anna_01', mid, 0, 'ru'), range(2)))
    assert sum(result['ok'] for result in results) == 1
    with store() as session:
        assert len(session.scalars(select(Message)).all()) == 3


def test_outfit_choice_offers_payment_without_unlocking_media(store):
    mid = seed_story('outfit')
    result = story_hooks.choose_in_app(1, 'anna_01', mid, 0, 'en')
    assert result['story_offer']
    assert result['reply'] == story_hooks.get('outfit').a.reply_en
    assert not result.get('photo_url')
    with store() as session:
        assert not any(row.media_url for row in session.scalars(select(Message)))
        assert session.get(User, 1).photo_credits == 0


def test_reply_action_is_not_executed_as_story(store):
    mid = memory_service.save_message(1, 'anna_01', 'assistant', 'Test',
        actions=[{'type': 'reply', 'label': 'Answer', 'text': 'Hello'}])
    result = story_hooks.choose_in_app(1, 'anna_01', mid, 0, 'ru')
    assert result['error'] == 'bad_request'
    with store() as session:
        assert json.loads(session.get(Message, mid).actions_json)[0]['text'] == 'Hello'


@pytest.fixture
def api(store, monkeypatch):
    import main
    from aiohttp import web
    calls = []
    monkeypatch.setattr(main, 'SessionLocal', store)
    monkeypatch.setattr(main.webapp_service, 'validate_init_data', lambda value: {'test': 'yes'} if value == 'fake-valid' else None)
    monkeypatch.setattr(main.webapp_service, 'init_data_user', lambda pairs: {'id': 991001, 'language_code': 'ru'})
    monkeypatch.setattr(main, 'get_user', lambda tid: SimpleNamespace(id=1))
    monkeypatch.setattr(main, '_webapp_chat_gate', lambda *args: None)
    monkeypatch.setattr(main, 'is_premium', lambda tid: False)
    monkeypatch.setattr(main, 'ADMIN_TELEGRAM_IDS', set())
    monkeypatch.setattr(main, 'full_user_lang', lambda *args: 'ru')
    monkeypatch.setattr(main, '_remember_character', lambda *args: None)
    monkeypatch.setattr(main, 'track_event', lambda *args, **kwargs: None)

    async def missions(*args, **kwargs):
        return {}

    async def turn(tid, info, cid, text, extra=None):
        calls.append((cid, text))
        return web.json_response({'ok': True, 'reply': 'Test reply'})

    monkeypatch.setattr(main, '_app_chat_missions', missions)
    monkeypatch.setattr(main, '_webapp_chat_turn', turn)
    return main, calls


def request(body, auth='fake-valid'):
    async def read_body():
        return body
    return SimpleNamespace(query={'init_data': auth}, json=read_body)


def test_action_api_uses_stored_reply_not_client_payload(api, store):
    main, calls = api
    mid = memory_service.save_message(1, 'anna_01', 'assistant', 'Test',
        actions=[{'type': 'reply', 'label': 'Answer', 'text': 'Stored choice'}])
    req = request({'character_id': 'anna_01', 'message_id': mid, 'action_index': 0,
                   'text': 'untrusted replacement', 'callback_data': 'admin:delete'})
    response = asyncio.run(main._webapp_api_chat_action(req))
    assert response.status == 200
    assert calls == [('anna_01', 'Stored choice')]
    assert asyncio.run(main._webapp_api_chat_action(req)).status == 404
    assert len(calls) == 1


@pytest.mark.parametrize('body', [[], None, {'message_id': 'bad'},
    {'character_id': 'anna_01', 'message_id': 1, 'action_index': -1}])
def test_action_api_rejects_malformed_requests(api, body):
    main, calls = api
    assert asyncio.run(main._webapp_api_chat_action(request(body))).status == 400
    assert not calls


def test_app_reply_notification_does_not_include_her_text(api, monkeypatch):
    from services import app_ping
    from unittest.mock import Mock
    main, _ = api
    notify = Mock()
    monkeypatch.setattr(app_ping, 'note', notify)
    main._app_ping(991001, 'anna_01', 'private reply', 'photo')
    notify.assert_called_once_with(main.bot, 991001, 'anna_01', '', generic=True)


def test_action_api_rejects_unsigned_requests(api):
    main, calls = api
    assert asyncio.run(main._webapp_api_chat_action(request({}, auth='forged'))).status == 401
    assert not calls


def test_action_api_keeps_the_existing_chat_gate(api, monkeypatch):
    main, calls = api
    from aiohttp import web
    monkeypatch.setattr(main, '_webapp_chat_gate', lambda *args: web.json_response({'ok': False, 'error': 'limit'}, status=429))
    mid = seed_story()
    req = request({'character_id': 'anna_01', 'message_id': mid, 'action_index': 0})
    assert asyncio.run(main._webapp_api_chat_action(req)).status == 429
    assert not calls
