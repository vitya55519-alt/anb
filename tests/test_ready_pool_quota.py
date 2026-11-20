"""Shared ready-frame cap, using fresh SQLite only and fake delivery/providers."""
import ast
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import random
import secrets
import subprocess
import sys
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import web
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]


def load_function(path, name, scope):
    """Run production route bodies without importing main/startup/providers."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    node = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == name)
    node.decorator_list = []
    future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
    module = ast.fix_missing_locations(ast.Module(body=[future, node], type_ignores=[]))
    exec(compile(module, str(path), 'exec'), scope)
    return scope[name]


def stub(monkeypatch, name, **values):
    import services
    mod = SimpleNamespace(**values)
    monkeypatch.setitem(sys.modules, 'services.' + name, mod)
    monkeypatch.setattr(services, name, mod, raising=False)
    return mod


@pytest.fixture
def quota(tmp_path, monkeypatch):
    import dotenv
    monkeypatch.setattr(dotenv, 'load_dotenv', lambda *a, **k: False)
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + (tmp_path / 'unused.db').as_posix())
    monkeypatch.setenv('TELEGRAM_TOKEN', '123456:test-only-token')
    from models.app_models import User, ProductEvent
    from services import chat_photo_allowance as allowance
    database = tmp_path / 'ready-pool.db'
    engine = create_engine('sqlite:///' + database.as_posix(),
                           connect_args={'check_same_thread': False, 'timeout': 20})
    User.__table__.create(engine)
    ProductEvent.__table__.create(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(allowance, 'SessionLocal', sessions)
    monkeypatch.setattr(allowance, 'FREE_FRAMES_PER_DAY', 2)
    monkeypatch.setattr(allowance, 'CHAT_POOL_PHOTOS_PER_DAY', 1)
    with sessions() as session:
        session.add_all([User(id=1, telegram_id='101', selected_character='girl_a', proactive_enabled=True),
                         User(id=2, telegram_id='102', selected_character='girl_b', proactive_enabled=True)])
        session.commit()
    yield SimpleNamespace(A=allowance, sessions=sessions, User=User, Event=ProductEvent,
                          database=database, engine=engine)
    engine.dispose()


def test_concurrent_third_frame_and_chat_subquota(quota):
    A = quota.A
    barrier = Barrier(8)

    def push(i):
        barrier.wait()
        return A.use_push_frame(1, f'girl_{i}')

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(push, range(8)))
    assert results.count(True) == 2
    assert results.count(False) == 6
    assert A.frames_left(1) == 0
    assert A.count_today(1, A.PUSH_EVENT) == 2

    barrier = Barrier(8)

    def chat(i):
        barrier.wait()
        return A.use_pool_photo(2, f'girl_{i}')

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(chat, range(8)))
    assert results.count(True) == 1
    assert A.frames_left(2) == 1
    assert A.use_push_frame(2, 'third_route') is True
    assert A.use_pool_photo(2, 'another_girl') is False


def test_separate_processes_share_database_lock(quota):
    # Separate interpreters defeat an in-process Lock implementation.
    script = '''
import os, sys
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
sys.path.insert(0, sys.argv[1])
import dotenv
dotenv.load_dotenv = lambda *a, **k: False
engine = create_engine(os.environ['DATABASE_URL'], connect_args={'timeout': 20})
sys.modules['services.db'] = SimpleNamespace(SessionLocal=sessionmaker(engine))
from services import chat_photo_allowance as A
A.FREE_FRAMES_PER_DAY = 2
print('ready', flush=True)
sys.stdin.readline()
print(int(A.use_push_frame(1, sys.argv[2])), flush=True)
engine.dispose()
'''
    env = dict(os.environ, DATABASE_URL='sqlite:///' + quota.database.as_posix(),
               TELEGRAM_TOKEN='123456:test-only-token', MINIMAX_API_KEY='test-local-only',
               PYTHON_DOTENV_DISABLED='1')
    workers = [subprocess.Popen([sys.executable, '-c', script, str(ROOT), f'girl_{i}'],
                               env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True) for i in range(5)]
    try:
        for proc in workers:
            assert proc.stdout.readline().strip() == 'ready'
        for proc in workers:
            proc.stdin.write('go\n')
            proc.stdin.flush()
        results = []
        for proc in workers:
            stdout, stderr = proc.communicate(timeout=40)
            assert proc.returncode == 0, stderr
            results.append(int(stdout.strip()))
        assert sum(results) == 2
        assert quota.A.count_today(1, quota.A.PUSH_EVENT) == 2
    finally:
        for proc in workers:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def test_missing_user_and_database_failure_fail_closed(quota, monkeypatch):
    A = quota.A
    assert A.use_pool_photo(999, 'girl') is False
    assert A.use_push_frame(999, 'girl') is False
    assert A.count_today(999, A.PUSH_EVENT) == 0
    monkeypatch.setattr(A, 'SessionLocal', Mock(side_effect=RuntimeError('offline')))
    assert A.use_push_frame(1, 'girl') is False
    assert A.use_pool_photo(1, 'girl') is False


def test_utc_rollover_and_exact_idempotent_release(quota, monkeypatch):
    A = quota.A

    class Clock(datetime):
        value = datetime(2026, 11, 16, 23, 59, 59, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            assert tz == timezone.utc
            return cls.value

    monkeypatch.setattr(A, 'datetime', Clock)
    assert A.use_push_frame(1, 'girl_a', reservation_key='failed-old-day')
    assert A.use_pool_photo(1, 'girl_b', reservation_key='delivered-old-day')
    assert not A.use_push_frame(1, 'girl_c')
    Clock.value += timedelta(seconds=2)
    assert A.frames_left(1) == 2
    assert A.use_push_frame(1, 'girl_c', reservation_key='new-day')
    assert A.release_frame(2, 'failed-old-day') is False
    assert A.release_frame(1, 'failed-old-day') is True
    assert A.release_frame(1, 'failed-old-day') is False
    assert A.frames_left(1) == 1  # yesterday's release did not erase today's frame
    assert A.use_pool_photo(1, 'girl_d')
    assert A.frames_left(1) == 0


def test_generated_paid_and_legacy_events_do_not_spend_ready_cap(quota):
    A = quota.A
    A.use_free_chat_photo(1, 'girl_a')
    for event in ('photo_paid', 'explicit_photo', 'photo_generation_started'):
        A.note_today(1, event, 'girl_b')
    generated = A.free_chat_photos_used(1)
    assert A.frames_left(1) == 2
    assert A.use_pool_photo(1, 'girl_b')
    assert A.use_push_frame(1, 'girl_c')
    assert A.free_chat_photos_used(1) == generated
    assert A.count_today(1, 'photo_paid') == 1
    assert A.use_push_frame(1, 'girl_d') is False
    assert A.count_today(1, A.POOL_EVENT) + A.count_today(1, A.PUSH_EVENT) == 2


@pytest.mark.parametrize('consumer', ['life', 'ladder'])
def test_push_consumers_obey_atomic_denial_after_stale_precheck(quota, monkeypatch, consumer):
    from services import life_event_service, silence_ladder
    A = quota.A
    stub(monkeypatch, 'retention_features_service', random_proactive_photo=lambda *a, **k: (b'photo', 'image/jpeg', 'photo'))
    stub(monkeypatch, 'user_service', ensure_user=lambda *a, **k: 1)
    assert A.use_pool_photo(1, 'chat_girl')
    assert A.use_push_frame(1, 'starter_girl')
    monkeypatch.setattr(A, 'frames_left', lambda uid: 1)  # stale preflight, not authority
    result = (life_event_service._pool_photo('life_girl', 1) if consumer == 'life'
              else silence_ladder._gift_frame(101, 'ladder_girl'))
    assert result is None
    assert A.count_today(1, A.PUSH_EVENT) == 1


def main_scope(quota):
    return dict(asyncio=asyncio, web=web, secrets=secrets, random=random,
                logger=logging.getLogger('ready-test'), AUTO_CAPTIONS={},
                ADMIN_TELEGRAM_IDS=set(), is_premium=lambda tid: False,
                ensure_user=lambda *a, **k: 1, PhotoRequest=lambda **k: SimpleNamespace(**k),
                CHAT_PHOTO_BLOCK_TEXT={'failed': 'not delivered', 'pool_used': 'ready cap'},
                CHAT_PHOTO_PEACH_COST=200, _LOCKED_CARD_REASONS=set(),
                save_message=Mock(return_value=1), track_event=Mock())


def starter_route(quota, monkeypatch, cached=True):
    scope = main_scope(quota)
    provider = AsyncMock(return_value=(b'rendered', 'image/jpeg', 'jpg'))
    stub(monkeypatch, 'greeting_service', take_offer=lambda *a: {
        'greeting_id': 7, 'image_prompt': 'test scene', 'reply_text': 'Here it is'})
    stub(monkeypatch, 'starter_photo_service', pick=lambda *a: 7 if cached else None,
         save=lambda *a: 8)
    stub(monkeypatch, 'analytics_service', track_event=Mock())
    stub(monkeypatch, 'daily_limit', note_message=Mock(), take_hint=lambda tid: None)
    scope.update(is_custom_character=lambda char: False, _chat_opening_spicy=lambda tid: True,
                 _webapp_pipeline_photo=provider, full_user_lang=lambda *a: 'en',
                 webapp_service=SimpleNamespace(record_generation=Mock(), record_generation_failure=Mock()))
    load_function(ROOT / 'main.py', '_chat_photo_blocked', scope)
    route = load_function(ROOT / 'main.py', '_starter_frame_turn', scope)
    return route, scope, provider


def test_cached_starter_shares_cap_across_girls_and_denial_is_handled(quota, monkeypatch):
    route, scope, provider = starter_route(quota, monkeypatch)
    assert quota.A.use_pool_photo(1, 'ordinary_chat_girl')
    first = json.loads(asyncio.run(route(101, {'language_code': 'en'}, 'girl_a', 'show')).body)
    assert first['photo_url'] == '/webapp/starter/7'
    second = json.loads(asyncio.run(route(101, {'language_code': 'en'}, 'girl_b', 'show')).body)
    assert second['ok'] and second['photo_block'] == 'pool_used'
    assert 'photo_url' not in second and 'photo_price' not in second
    provider.assert_not_awaited()
    assert quota.A.count_today(1, quota.A.PUSH_EVENT) == 1
    assert quota.A.free_chat_photos_used(1) == 0


def test_generated_first_starter_counts_against_the_shared_cap(quota, monkeypatch):
    # V3.167.27: a fresh teaser render is spicyapi money — it spends the same
    # daily frame cap and is skipped once the cap is gone.
    route, scope, provider = starter_route(quota, monkeypatch, cached=False)
    assert quota.A.use_push_frame(1, 'girl_a') and quota.A.use_push_frame(1, 'girl_b')
    result = asyncio.run(route(101, {}, 'girl_c', 'show'))
    assert result is None
    provider.assert_not_awaited()
    assert quota.A.count_today(1, quota.A.PUSH_EVENT) == 2


def test_starter_failed_before_photo_releases_without_render_fallback(quota, monkeypatch):
    route, scope, provider = starter_route(quota, monkeypatch)
    scope['save_message'] = Mock(side_effect=RuntimeError('user message unavailable'))
    result = json.loads(asyncio.run(route(101, {}, 'girl_a', 'show')).body)
    assert result['photo_block'] == 'failed'
    assert quota.A.frames_left(1) == 2
    provider.assert_not_awaited()


def app_photo_route(quota, monkeypatch, *, pooled=True):
    scope = main_scope(quota)
    provider = AsyncMock(return_value=(b'rendered', 'image/jpeg', 'jpg'))
    media = SimpleNamespace(save_chat_media=Mock(return_value='frame.jpg'),
                            record_generation=Mock(), record_generation_failure=Mock())
    stub(monkeypatch, 'collection_service', gallery_set_progress=lambda *a: {}, note_gallery_set=lambda *a: False)
    scope.update(uid=1, telegram_id=101, character_id='girl_a', text='show', extra=None,
                 user_language='en', webapp_service=media,
                 _free_photo_from_pool=lambda *a: (b'ready', 'image/jpeg', 'jpg') if pooled else None,
                 _webapp_pipeline_photo=provider, _webapp_media_photo=provider,
                 spicy_needs_premium=lambda req: False, get_photo_credits=lambda tid: 0,
                 spend_peaches=Mock(), get_paid_peaches=lambda tid: 0)
    load_function(ROOT / 'main.py', '_chat_photo_blocked', scope)
    route = load_function(ROOT / 'main.py', '_photo_turn', scope)
    return route, scope, provider, media


def test_app_pool_race_is_blocked_before_persist_or_render(quota, monkeypatch):
    route, scope, provider, media = app_photo_route(quota, monkeypatch)
    assert quota.A.use_push_frame(1, 'life') and quota.A.use_push_frame(1, 'starter')
    result = asyncio.run(route('selfie', None))
    assert result['photo_block'] == 'pool_used'
    media.save_chat_media.assert_not_called()
    provider.assert_not_awaited()
    assert quota.A.count_today(1, quota.A.POOL_EVENT) == 0


def test_render_failure_ready_fallback_also_reserves(quota, monkeypatch):
    route, scope, provider, media = app_photo_route(quota, monkeypatch, pooled=False)
    provider.side_effect = RuntimeError('provider failed')
    monkeypatch.setattr(quota.A, 'reused_photo', lambda *a: (b'ready', 'image/jpeg', 'jpg'))
    assert quota.A.use_push_frame(1, 'life')
    result = asyncio.run(route('selfie', None))
    assert result['photo_url']
    assert quota.A.count_today(1, quota.A.POOL_EVENT) == 1
    assert quota.A.frames_left(1) == 0
    assert quota.A.free_chat_photos_used(1) == 0
    scope['spend_peaches'].assert_not_called()


def test_app_media_failure_releases_but_post_delivery_failure_does_not(quota, monkeypatch):
    route, scope, provider, media = app_photo_route(quota, monkeypatch)
    media.save_chat_media.side_effect = RuntimeError('no media persisted')
    with pytest.raises(RuntimeError):
        asyncio.run(route('selfie', None))
    assert quota.A.frames_left(1) == 2
    provider.assert_not_awaited()
    media.save_chat_media.side_effect = None
    scope['get_photo_credits'] = Mock(side_effect=RuntimeError('after delivery'))
    with pytest.raises(RuntimeError):
        asyncio.run(route('selfie', None))
    assert quota.A.frames_left(1) == 1
    assert any(call.kwargs.get('media_kind') == 'photo' for call in scope['save_message'].call_args_list)


def daily_gift_route(quota, monkeypatch, *, saved=11, prefs=None):
    events = []
    stub(monkeypatch, 'retention_features_service', random_proactive_photo=lambda *a, **k: (b'ready', 'image/jpeg', 'photo'))
    stub(monkeypatch, 'webapp_service', get_notification_prefs=lambda tid: prefs or {}, record_generation=Mock())
    def persist(*args):
        assert quota.A.frames_left(1) < 2
        events.append('save')
        return saved
    stub(monkeypatch, 'scheduler_service', _to_app_chat=persist)
    def notify(*args, **kwargs):
        with quota.sessions() as session:
            assert session.get(quota.User, 1).last_daily_gift_date == datetime.now(timezone.utc).date()
        events.append('ping')
        return False  # disabled/present/quiet notifications do not undo app delivery
    stub(monkeypatch, 'app_ping', note=notify)
    scope = dict(SessionLocal=quota.sessions, User=quota.User, select=select, datetime=datetime,
                 timezone=timezone, ensure_user=lambda tid: 1, CHARACTER_ID='default',
                 logger=logging.getLogger('gift-test'))
    route = load_function(ROOT / 'services/private_photo_service.py', 'send_daily_gift', scope)
    bot = SimpleNamespace(send_photo=AsyncMock(), send_message=AsyncMock())
    return route, bot, events


def test_daily_gift_persists_then_notifies_and_never_sends_telegram_photo(quota, monkeypatch):
    route, bot, events = daily_gift_route(quota, monkeypatch)
    assert asyncio.run(route(101, bot)) is True
    assert events == ['save', 'ping']
    assert quota.A.frames_left(1) == 1
    assert asyncio.run(route(101, bot)) is False
    bot.send_photo.assert_not_awaited()
    bot.send_message.assert_not_awaited()


def test_daily_gift_failed_save_releases_without_stamping_or_ping(quota, monkeypatch):
    route, bot, events = daily_gift_route(quota, monkeypatch, saved=None)
    assert asyncio.run(route(101, bot)) is False
    assert events == ['save']
    assert quota.A.frames_left(1) == 2
    with quota.sessions() as session:
        assert session.get(quota.User, 1).last_daily_gift_date is None
    bot.send_photo.assert_not_awaited()


@pytest.mark.parametrize('pref', ['enabled', 'new_messages', 'daily_bonus'])
def test_daily_gift_respects_notification_preferences(quota, monkeypatch, pref):
    route, bot, events = daily_gift_route(quota, monkeypatch, prefs={pref: False})
    assert asyncio.run(route(101, bot)) is False
    assert not events and quota.A.frames_left(1) == 2


def test_daily_gift_cannot_be_third_frame(quota, monkeypatch):
    route, bot, events = daily_gift_route(quota, monkeypatch)
    assert quota.A.use_pool_photo(1, 'chat') and quota.A.use_push_frame(1, 'starter')
    assert asyncio.run(route(101, bot)) is False
    assert not events
    with quota.sessions() as session:
        assert session.get(quota.User, 1).last_daily_gift_date is None


def bot_photo_route(quota, monkeypatch):
    from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
    from aiogram.types import BufferedInputFile
    stub(monkeypatch, 'spend_service', set_spend_user=Mock())
    monkeypatch.setattr(quota.A, 'reused_photo', lambda *a: (b'ready', 'image/jpeg', 'jpg'))
    scope = main_scope(quota)
    bot = SimpleNamespace(send_photo=AsyncMock(), send_message=AsyncMock())
    provider = AsyncMock()
    scope.update(bot=bot, BufferedInputFile=BufferedInputFile,
                 TelegramBadRequest=TelegramBadRequest, TelegramForbiddenError=TelegramForbiddenError,
                 _start_photo_background=provider, has_accepted=lambda tid: True,
                 observe_photo_preference=Mock(), get_user_character=lambda tid: 'girl_a',
                 get_relationship_stage=lambda *a: 1, spicy_needs_premium=lambda req: False,
                 scene_allowed_for_stage=lambda *a: True, _card_girl_photo_locked=lambda *a: False,
                 requires_adult_confirmation=lambda req: False, attach_guest=lambda req, *a: req,
                 is_custom_request=lambda req: False)
    request = SimpleNamespace(scene='selfie', customized=False, clothing='', hairstyle='', location='')
    route = load_function(ROOT / 'main.py', 'handle_photo_request', scope)
    return route, bot, provider, request


def test_bot_denied_reservation_is_not_delivered_or_rendered(quota, monkeypatch):
    route, bot, provider, request = bot_photo_route(quota, monkeypatch)
    assert quota.A.use_push_frame(1, 'life') and quota.A.use_push_frame(1, 'starter')
    monkeypatch.setattr(quota.A, 'pool_photos_left', lambda uid: 1)  # stale preview
    asyncio.run(route(101, 101, request))
    bot.send_photo.assert_not_awaited()
    bot.send_message.assert_awaited_once()
    provider.assert_not_awaited()
    assert quota.A.free_chat_photos_used(1) == 0


@pytest.mark.parametrize('unknown', [False, True])
def test_bot_release_only_for_confirmed_rejection(quota, monkeypatch, unknown):
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import SendPhoto
    route, bot, provider, request = bot_photo_route(quota, monkeypatch)
    error = TimeoutError('unknown outcome') if unknown else TelegramBadRequest(
        method=SendPhoto(chat_id=101, photo='fake'), message='invalid photo')
    async def send(*a, **k):
        assert quota.A.count_today(1, quota.A.POOL_EVENT) == 1
        raise error
    bot.send_photo.side_effect = send
    with pytest.raises(type(error)):
        asyncio.run(route(101, 101, request))
    assert quota.A.frames_left(1) == (1 if unknown else 2)
    provider.assert_not_awaited()


def test_daily_gift_notification_exception_does_not_refund_delivery(quota, monkeypatch):
    route, bot, events = daily_gift_route(quota, monkeypatch)
    stub(monkeypatch, 'app_ping', note=Mock(side_effect=RuntimeError('notification failed')))
    assert asyncio.run(route(101, bot)) is True
    assert quota.A.frames_left(1) == 1
    assert asyncio.run(route(101, bot)) is False
    assert events == ['save']


def test_duplicate_reservation_key_cannot_deliver_again(quota):
    A = quota.A
    assert A.use_push_frame(1, 'girl_a', reservation_key='same-gift') is True
    assert A.use_push_frame(1, 'girl_b', reservation_key='same-gift') is False
    assert A.frames_left(1) == 1
