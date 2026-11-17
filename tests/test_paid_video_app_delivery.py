"""Paid animation delivery regressions; use fake credentials and a temp DATABASE_URL.

Run with PYTHON_DOTENV_DISABLED=1. All Telegram/provider calls are mocked and
all database/media writes are redirected to pytest's temporary directory.
"""
import asyncio
import inspect
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import main
from models.app_models import Achievement, ChatMedia, Message, User, UserGeneration
from models.photo_models import PhotoDelivery
from models.waifu_models import Base
from services import app_ping, db, gamification_service, webapp_service


TG = 915802
CHAT = 915803
SOURCE_CHAR = 'anna_01'
SELECTED_CHAR = 'maria_01'
IMAGE = b'original telegram image'
SQUARE = b'squared original telegram image'
VIDEO = b'generated mp4 bytes'
PHRASE = 'The source character dialogue.'


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + (tmp_path / 'paid-video.sqlite').as_posix(),
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
        user = User(telegram_id=str(TG), name='Test', selected_character=SELECTED_CHAR)
        session.add(user)
        session.flush()
        photo = PhotoDelivery(user_id=user.id, character_id=SOURCE_CHAR, scene='lingerie',
                              delivery_type='paid', telegram_file_id='source-file',
                              full_resolution_bytes=b'not the existing Telegram source')
        session.add(photo)
        session.commit()
        uid, delivery_id = user.id, photo.id

    bot = SimpleNamespace(**{name: AsyncMock() for name in (
        'send_message', 'send_chat_action', 'send_photo', 'send_animation',
        'send_video', 'send_video_note', 'refund_star_payment', 'download_file', 'get_file')})
    bot.get_file.return_value = SimpleNamespace(file_path='photos/source.jpg')

    async def download(path, destination):
        assert path == 'photos/source.jpg'
        destination.write(IMAGE)

    bot.download_file.side_effect = download
    monkeypatch.setattr(main, 'bot', bot)
    monkeypatch.setattr(main, 'logger', Mock())
    monkeypatch.setattr(main, 'ADMIN_TELEGRAM_IDS', set())
    monkeypatch.setattr(main, '_video_jobs', {TG: object()})
    provider = AsyncMock(return_value=VIDEO)
    monkeypatch.setattr(main, 'video_engines', Mock(return_value=[('test-engine', provider)]))
    monkeypatch.setattr(main, 'square_frame', Mock(return_value=SQUARE))
    monkeypatch.setattr(main, '_circle_phrase', Mock(return_value=PHRASE))
    monkeypatch.setattr(main, '_her_label', Mock(return_value='Her: '))
    for name in ('track_event', 'record_provider', 'record_refund', 'add_peaches'):
        monkeypatch.setattr(main, name, Mock())
    monkeypatch.setattr(main, 'spend_peaches', Mock(side_effect=AssertionError('must not charge again')))
    monkeypatch.setattr(main, '_notify_unlock', AsyncMock(wraps=main._notify_unlock))
    monkeypatch.setattr(gamification_service, 'try_unlock', Mock(wraps=gamification_service.try_unlock))
    monkeypatch.setattr(webapp_service, 'save_chat_media', Mock(wraps=webapp_service.save_chat_media))
    monkeypatch.setattr(webapp_service, 'record_generation', Mock(wraps=webapp_service.record_generation))
    monkeypatch.setattr(main, 'save_message', Mock(wraps=main.save_message))

    def note(*args, **kwargs):
        # The real generic hook must only run after the media and chat row exist.
        with sessions() as session:
            assert len(session.scalars(select(ChatMedia)).all()) == 1
            assert len(session.scalars(select(Message)).all()) == 1
        assert args == (bot, TG, SOURCE_CHAR, '')
        assert kwargs == {'generic': True}

    monkeypatch.setattr(app_ping, 'note', Mock(side_effect=note))
    try:
        yield SimpleNamespace(bot=bot, provider=provider, sessions=sessions,
                              uid=uid, delivery_id=delivery_id)
    finally:
        monkeypatch.undo()
        # Restore DB aliases imported by achievement helpers during the test.
        for name, module in list(sys.modules.items()):
            if (name.startswith('services.') or name == 'main') and getattr(module, 'SessionLocal', None) is sessions:
                module.SessionLocal = original
        engine.dispose()


def run(env, kind, charge='test-star-charge', **kwargs):
    fn = main._run_video_background if kind == 'video' else main._run_circle_background
    asyncio.run(fn(CHAT, TG, env.delivery_id, charge, **kwargs))
    assert TG not in main._video_jobs
    main.spend_peaches.assert_not_called()


def rows(env, model):
    with env.sessions() as session:
        return list(session.scalars(select(model)))


def no_bot_media(env):
    for name in ('send_video', 'send_video_note', 'send_photo', 'send_animation', 'send_chat_action'):
        getattr(env.bot, name).assert_not_called()


def no_app_delivery(env):
    assert rows(env, Message) == rows(env, ChatMedia) == rows(env, UserGeneration) == []
    main.save_message.assert_not_called()
    webapp_service.save_chat_media.assert_not_called()
    webapp_service.record_generation.assert_not_called()
    app_ping.note.assert_not_called()


@pytest.mark.parametrize('kind', ['video', 'circle'])
@pytest.mark.parametrize('fallback', [False, True])
def test_app_only_saves_once_to_source_character_without_telegram_media(env, kind, fallback):
    failing = AsyncMock(side_effect=main.CloudVideoError('first engine failed'))
    if fallback:
        main.video_engines.return_value.insert(0, ('failed-engine', failing))
    kwargs = {'app_only': True}
    if kind == 'video':
        preset = next(iter(main.VIDEO_PRESETS))
        kwargs['motion_preset'] = preset
    run(env, kind, **kwargs)

    no_bot_media(env)
    env.bot.send_message.assert_not_called()
    main._notify_unlock.assert_not_called()
    gamification_service.try_unlock.assert_called_once_with(TG, 'first_video')
    assert [a.achievement_key for a in rows(env, Achievement)] == ['first_video']
    main._her_label.assert_not_called()
    env.bot.get_file.assert_awaited_once_with('source-file')
    env.bot.download_file.assert_awaited_once()
    if kind == 'video':
        prompt = main.VIDEO_PRESETS[preset][1]
        expected = call(IMAGE, mime_type='image/jpeg', prompt=prompt)
        main.square_frame.assert_not_called()
    else:
        prompt = main.CIRCLE_PROMPT.format(phrase=PHRASE)
        expected = call(SQUARE, mime_type='image/jpeg', prompt=prompt, scene='circle')
        main._circle_phrase.assert_called_once_with(TG, SOURCE_CHAR)
        assert main.square_frame.call_args_list == [call(IMAGE)] * (2 if fallback else 1)
    assert env.provider.await_args_list == [expected]
    if fallback:
        assert failing.await_args_list == [expected]
    main.video_engines.assert_called_once_with()

    message, = rows(env, Message)
    media, = rows(env, ChatMedia)
    generation, = rows(env, UserGeneration)
    assert message.user_id == env.uid and message.character_id == SOURCE_CHAR
    assert message.role == 'assistant' and message.media_kind == kind
    assert message.content == ('вот \U0001f60c\U0001f3ac' if kind == 'video' else '')
    assert message.media_url == '/webapp/media/' + media.filename
    assert media.data == VIDEO and media.content_type == 'video/mp4'
    assert media.telegram_id == str(TG)
    assert webapp_service.chat_media_file_path(TG, media.filename).read_bytes() == VIDEO
    webapp_service.save_chat_media.assert_called_once_with(TG, VIDEO, 'mp4', 'video/mp4')
    main.save_message.assert_called_once_with(env.uid, SOURCE_CHAR, 'assistant', message.content,
                                             media_kind=kind, media_url=message.media_url)
    webapp_service.record_generation.assert_called_once_with(
        TG, kind, SOURCE_CHAR, prompt, media.filename, engine='test-engine')
    assert generation.character_id == SOURCE_CHAR and generation.kind == kind
    assert generation.filename == media.filename and generation.engine == 'test-engine'
    gallery = webapp_service.api_video_list(TG)
    assert [item['file'] for item in gallery] == ([message.media_url] if kind == 'video' else [])
    app_ping.note.assert_called_once()
    env.bot.refund_star_payment.assert_not_called()
    main.record_refund.assert_not_called()
    main.add_peaches.assert_not_called()
    assert main.record_provider.call_args_list[-1] == call(f'{kind}/test-engine', True)
    event = 'test-engine_video_delivered' if kind == 'video' else 'circle_delivered'
    assert main.track_event.call_args.args == (env.uid, event)
    assert main.track_event.call_args.kwargs['metadata']['source_delivery_id'] == env.delivery_id
    assert main.track_event.call_args.kwargs['metadata']['charge_id'] == 'test-star-charge'


@pytest.mark.parametrize('scene,prompt_kind', [('lingerie', 'sensual'), ('selfie', 'default')])
def test_video_without_preset_preserves_scene_prompt(env, scene, prompt_kind):
    with env.sessions() as session:
        session.get(PhotoDelivery, env.delivery_id).scene = scene
        session.commit()
    run(env, 'video', app_only=True)
    env.provider.assert_awaited_once_with(
        IMAGE, mime_type='image/jpeg',
        prompt=main.SENSUAL_ANIMATION_PROMPT if prompt_kind == 'sensual' else None)


@pytest.mark.parametrize('kind', ['video', 'circle'])
def test_default_admin_delivery_stays_in_telegram(env, monkeypatch, kind):
    monkeypatch.setattr(main, 'ADMIN_TELEGRAM_IDS', {TG})
    run(env, kind, charge=None)
    no_app_delivery(env)
    main._notify_unlock.assert_awaited_once_with(CHAT, TG, 'first_video')
    gamification_service.try_unlock.assert_called_once_with(TG, 'first_video')
    env.provider.assert_awaited_once()
    if kind == 'video':
        env.bot.send_video.assert_awaited_once()
        sent = env.bot.send_video.await_args
        assert sent.kwargs == {'caption': 'вот \U0001f60c\U0001f3ac', 'supports_streaming': True}
        env.bot.send_video_note.assert_not_called()
    else:
        env.bot.send_video_note.assert_awaited_once()
        sent = env.bot.send_video_note.await_args
        env.bot.send_video.assert_not_called()
        main._circle_phrase.assert_called_once_with(TG)
    assert sent.args[0] == CHAT and sent.args[1].data == VIDEO
    assert env.bot.send_message.await_count >= 1
    env.bot.refund_star_payment.assert_not_called()


def test_default_circle_keeps_telegram_format_fallback(env):
    env.bot.send_video_note.side_effect = RuntimeError('note format rejected')
    run(env, 'circle', charge=None)
    env.bot.send_video_note.assert_awaited_once()
    env.bot.send_video.assert_awaited_once()
    assert env.bot.send_video.await_args.args[1].data == VIDEO
    assert env.bot.send_video.await_args.kwargs['supports_streaming'] is True
    assert env.bot.send_video.await_args.kwargs['caption'].startswith('Her: ')
    main._her_label.assert_called_once_with(TG)
    env.provider.assert_awaited_once()
    env.bot.refund_star_payment.assert_not_called()
    no_app_delivery(env)


@pytest.mark.parametrize('kind,charge', [('video', 'test-star-charge'),
                                         ('circle', 'test-star-charge'), ('circle', 'peaches')])
@pytest.mark.parametrize('app_only', [False, True])
def test_provider_failure_preserves_refunds_and_cleanup(env, kind, charge, app_only):
    env.provider.side_effect = main.CloudVideoError('provider unavailable')
    run(env, kind, charge=charge, app_only=app_only)
    no_app_delivery(env)
    env.provider.assert_awaited_once()
    if app_only:
        no_bot_media(env)
        main._notify_unlock.assert_not_called()
        env.bot.send_message.assert_awaited_once()
        assert env.bot.send_message.await_args.args[1].startswith('Не удалось создать ')
    if charge == 'peaches':
        main.add_peaches.assert_called_once_with(TG, main.CIRCLE_PEACH_COST)
        env.bot.refund_star_payment.assert_not_called()
        main.record_refund.assert_not_called()
    else:
        env.bot.refund_star_payment.assert_awaited_once_with(
            user_id=TG, telegram_payment_charge_id=charge)
        main.record_refund.assert_called_once_with(TG, charge, main.VIDEO_COST_STARS, product='video')
        main.add_peaches.assert_not_called()
    main.record_provider.assert_called_once()
    assert main.record_provider.call_args.args[:2] == (f'{kind}/test-engine', False)
    assert main.track_event.call_args.args == (env.uid, 'video_failed')
    assert main.track_event.call_args.kwargs['metadata']['refunded'] is True


@pytest.mark.parametrize('kind', ['video', 'circle'])
def test_app_save_failure_never_falls_back_to_bot_media_or_pings(env, kind):
    main.save_message.side_effect = RuntimeError('message storage unavailable')
    run(env, kind, app_only=True)
    no_bot_media(env)
    assert rows(env, Message) == []
    app_ping.note.assert_not_called()
    webapp_service.record_generation.assert_not_called()
    env.provider.assert_awaited_once()
    env.bot.refund_star_payment.assert_awaited_once()


def test_admin_video_failure_keeps_diagnostics(env, monkeypatch):
    monkeypatch.setattr(main, 'ADMIN_TELEGRAM_IDS', {TG})
    env.provider.side_effect = main.CloudVideoError('provider unavailable')
    run(env, 'video', charge=None)
    texts = [c.args[1] for c in env.bot.send_message.await_args_list]
    assert any('test-engine: CloudVideoError: provider unavailable' in text for text in texts)
    no_app_delivery(env)
    env.bot.refund_star_payment.assert_not_called()


@pytest.mark.parametrize('kind', ['video', 'circle'])
def test_app_stored_photo_can_be_animated_without_telegram(env, kind):
    original = b'\x89PNG\r\n\x1a\noriginal app photo'
    with env.sessions() as session:
        photo = session.get(PhotoDelivery, env.delivery_id)
        photo.telegram_file_id = None
        photo.full_resolution_bytes = original
        session.commit()
    run(env, kind, app_only=True)
    env.bot.get_file.assert_not_called()
    env.bot.download_file.assert_not_called()
    no_bot_media(env)
    message, = rows(env, Message)
    assert message.character_id == SOURCE_CHAR and message.media_kind == kind
    if kind == 'video':
        assert env.provider.await_args.args == (original,)
        assert env.provider.await_args.kwargs['mime_type'] == 'image/png'
    else:
        main.square_frame.assert_called_once_with(original)
    env.bot.refund_star_payment.assert_not_called()


@pytest.mark.parametrize('kind', ['video', 'circle'])
def test_animation_never_uses_another_users_photo(env, kind):
    with env.sessions() as session:
        session.get(PhotoDelivery, env.delivery_id).user_id = env.uid + 1000
        session.commit()
    run(env, kind, app_only=True)
    no_app_delivery(env)
    env.provider.assert_not_called()
    env.bot.get_file.assert_not_called()
    env.bot.refund_star_payment.assert_awaited_once()


def test_app_only_is_an_opt_in_keyword():
    for fn in (main._run_video_background, main._run_circle_background):
        parameter = inspect.signature(fn).parameters['app_only']
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is False
