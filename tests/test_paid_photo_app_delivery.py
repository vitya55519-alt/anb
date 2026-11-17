import asyncio
import io
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from models.app_models import User
from models.photo_models import PhotoDailyUsage, PhotoDelivery
from models.waifu_models import Base
from services import db, gift_shop_service, photo_service as ps, wardrobe_service


TG = 915901
CHAR = 'anna_01'
PNG = b'\x89PNG\r\n\x1a\nexact provider bytes'
JPEG = b'\xff\xd8\xffexact library bytes'
WEBP = b'RIFF\x00\x00\x00\x00WEBPexact provider bytes'


@pytest.fixture
def env(monkeypatch):
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    original = db.SessionLocal
    for name, module in list(sys.modules.items()):
        if name.startswith('services.') and getattr(module, 'SessionLocal', None) is original:
            monkeypatch.setattr(module, 'SessionLocal', sessions)
    monkeypatch.setattr(db, 'engine', engine)
    monkeypatch.setattr(ps, 'PHOTO_SET_SIZE', 3)
    monkeypatch.setattr(ps, 'get_relationship_stage', Mock(return_value='close'))
    monkeypatch.setattr(ps, 'get_relationship_level', Mock(return_value=3))
    monkeypatch.setattr(ps, 'scene_allowed_for_stage', Mock(return_value=True))
    monkeypatch.setattr(ps, 'requires_adult_confirmation', Mock(return_value=False))
    monkeypatch.setattr(ps, 'is_adult_confirmed', Mock(return_value=True))
    monkeypatch.setattr(ps, 'has_free_photo', Mock(return_value=True))
    monkeypatch.setattr(ps, 'COMMUNITY_POOL_ENABLED', False)
    monkeypatch.setattr(ps, 'COMMUNITY_POOL_FIRST', False)
    monkeypatch.setattr(wardrobe_service, 'worn_today', Mock(return_value=None))
    monkeypatch.setattr(gift_shop_service, 'photo_overrides', Mock(return_value={}))
    for name in ('track_event', 'mark_pack_seen', 'mark_items_seen'):
        monkeypatch.setattr(ps, name, Mock())
    monkeypatch.setattr(ps, 'choose_fallback_pack', Mock(return_value=None))
    monkeypatch.setattr(ps, '_her', lambda text, character_id: text)
    monkeypatch.setattr(ps, '_photo_action_markup', Mock(side_effect=AssertionError('Telegram keyboard')))
    uid = ps.ensure_user(TG)
    with sessions() as session:
        user = session.get(User, uid)
        user.photo_credits = 10 * ps.PEACH_SCALE
        user.bonus_peaches = 2 * ps.PEACH_SCALE
        session.commit()

    bot = SimpleNamespace(**{name: AsyncMock(side_effect=AssertionError(name)) for name in (
        'send_photo', 'send_message', 'send_chat_action', 'send_document', 'send_media_group',
        'send_animation', 'send_video', 'send_video_note', 'get_file', 'download_file', 'download')})
    received = []

    async def app_delivery(data, mime, delivery_id, caption):
        with sessions() as session:
            row = session.get(PhotoDelivery, delivery_id)
            assert row is not None
            assert row.user_id == uid and row.character_id == CHAR
            assert row.full_resolution_bytes == data
            assert row.telegram_file_id is None
        media = ps.get_photo_delivery_for_user(TG, delivery_id)
        assert media['media_bytes'] == data and media['mime_type'] == mime
        received.append((data, mime, delivery_id, caption))

    callback = AsyncMock(side_effect=app_delivery)
    try:
        yield SimpleNamespace(sessions=sessions, uid=uid, bot=bot, callback=callback, received=received)
    finally:
        monkeypatch.undo()
        for name, module in list(sys.modules.items()):
            if name.startswith('services.') and getattr(module, 'SessionLocal', None) is sessions:
                module.SessionLocal = original
        engine.dispose()


def generate(monkeypatch, count=3, data=PNG):
    frames = [ps.GeneratedPhoto(data=data + bytes([i]), provider='seedream45', estimated_cost_usd=0.04)
              for i in range(count)]
    resolved = ps.PhotoRequest(scene='cafe', clothing='linen', hairstyle='loose', pack_outfits=('linen',))

    async def fake_generate(telegram_id, request, on_frame, *, character_id):
        assert telegram_id == TG and character_id == CHAR
        for i, frame in enumerate(frames):
            await on_frame(frame, i)
        return frames, resolved

    fake = AsyncMock(side_effect=fake_generate)
    monkeypatch.setattr(ps, 'generate_photo_set', fake)
    return fake, frames


def deliver(env, delivery_type='credit', **kwargs):
    kwargs.setdefault('app_delivery', env.callback)
    return asyncio.run(ps.deliver_photo(env.bot, TG, TG, ps.PhotoRequest(scene='cafe'),
                                       delivery_type, caption='character caption', character_id=CHAR, **kwargs))


def deliveries(env):
    with env.sessions() as session:
        return list(session.scalars(select(PhotoDelivery).where(PhotoDelivery.user_id == env.uid)
                                    .order_by(PhotoDelivery.id)))


def accounting(env):
    with env.sessions() as session:
        user = session.get(User, env.uid)
        usage = session.scalar(select(PhotoDailyUsage).where(PhotoDailyUsage.user_id == env.uid))
        return user.photo_credits, user.bonus_peaches, usage.free_used if usage else 0, usage.paid_used if usage else 0


def no_telegram_output(env, *, downloads=0):
    for name, method in vars(env.bot).items():
        if name == 'download':
            assert method.await_count == downloads
        else:
            method.assert_not_called()
    ps._photo_action_markup.assert_not_called()


def library_pack(count=3):
    return SimpleNamespace(id=77, scene='cafe', pack_key='ready-cafe', relationship_level=2,
                           photos=[SimpleNamespace(file_id=f'library-{i}', item_id=100 + i) for i in range(count)])


def enable_library(env, monkeypatch):
    pack = library_pack()
    ps.choose_fallback_pack.return_value = pack
    env.bot.download.side_effect = lambda file_id: io.BytesIO(JPEG + file_id.encode())
    return pack


@pytest.mark.parametrize('delivery_type', ['credit', 'paid', 'free', 'story', 'admin'])
@pytest.mark.parametrize('count', [1, 2, 3])
def test_app_complete_and_partial_accounting(env, monkeypatch, delivery_type, count):
    fake, frames = generate(monkeypatch, count)
    result = deliver(env, delivery_type)
    rows = deliveries(env)
    assert result == [r.id for r in rows] == [item[2] for item in env.received]
    assert len(result) == count
    assert [item[0] for item in env.received] == [frame.data for frame in frames]
    assert [item[1] for item in env.received] == ['image/png'] * count
    assert [item[3] for item in env.received] == ['character caption'] + [''] * (count - 1)
    assert all(r.provider == 'seedream45' and r.estimated_cost_usd == 0.04 for r in rows)
    assert all(r.delivery_type == delivery_type and r.community_shared for r in rows)
    spent = ps.PEACH_SCALE if delivery_type == 'credit' and count == 3 else 0
    free = int(delivery_type == 'free' and count >= 2)
    paid = int(delivery_type in {'credit', 'paid'} and count == 3)
    assert accounting(env) == (10 * ps.PEACH_SCALE - spent, 2 * ps.PEACH_SCALE, free, paid)
    assert ps.get_state(TG).outfit == 'linen'
    fake.assert_awaited_once()
    no_telegram_output(env)


@pytest.mark.parametrize('delivery_type', ['free', 'story'])
def test_library_topup_delivers_only_missing_items(env, monkeypatch, delivery_type):
    fake, frames = generate(monkeypatch, 1)
    pack = enable_library(env, monkeypatch)
    result = deliver(env, delivery_type)
    rows = deliveries(env)
    assert len(result) == len(rows) == 3
    assert [r.provider for r in rows] == ['seedream45', 'telegram_library_topup', 'telegram_library_topup']
    assert [r.estimated_cost_usd for r in rows] == [0.04, 0.0, 0.0]
    assert [item[0] for item in env.received] == [frames[0].data, JPEG + b'library-0', JPEG + b'library-1']
    ps.mark_items_seen.assert_called_once_with(TG, [100, 101])
    ps.mark_pack_seen.assert_not_called()
    assert pack.id == 77
    assert accounting(env) == (10 * ps.PEACH_SCALE, 2 * ps.PEACH_SCALE, int(delivery_type == 'free'), 0)
    fake.assert_awaited_once()
    no_telegram_output(env, downloads=2)


@pytest.mark.parametrize('delivery_type', ['free', 'story'])
def test_library_generation_failure_fallback_keeps_existing_free_charge(env, monkeypatch, delivery_type):
    generation = AsyncMock(side_effect=ps.PhotoGenerationError('seedream45', 'unavailable'))
    monkeypatch.setattr(ps, 'generate_photo_set', generation)
    pack = enable_library(env, monkeypatch)
    result = deliver(env, delivery_type)
    rows = deliveries(env)
    assert result == [r.id for r in rows] and len(rows) == 3
    assert all(r.provider == 'telegram_library_fallback' and r.delivery_type == 'free'
               and r.estimated_cost_usd == 0.0 for r in rows)
    assert all(item[1] == 'image/jpeg' for item in env.received)
    ps.mark_pack_seen.assert_called_once_with(TG, pack.id)
    assert accounting(env) == (10 * ps.PEACH_SCALE, 2 * ps.PEACH_SCALE, 1, 0)
    generation.assert_awaited_once()
    no_telegram_output(env, downloads=3)


def seed_community(env, count, *, telegram=False):
    source_user = TG + 1
    return [ps._insert_delivery_row(source_user, 'cafe', 'free', character_id=CHAR,
                                   provider='seedream45', community_shared=True,
                                   file_id=f'legacy-{i}' if telegram else None,
                                   full_bytes=None if telegram else PNG + bytes([i]))
            for i in range(count)]


@pytest.mark.parametrize('first,count', [(True, 3), (False, 2)])
@pytest.mark.parametrize('telegram', [False, True])
def test_community_app_reuse_and_fallback_without_new_generation(env, monkeypatch, first, count, telegram):
    monkeypatch.setattr(ps, 'COMMUNITY_POOL_ENABLED', True)
    monkeypatch.setattr(ps, 'COMMUNITY_POOL_FIRST', first)
    source_ids = seed_community(env, count, telegram=telegram)
    generation = AsyncMock(side_effect=ps.PhotoGenerationError('seedream45', 'unavailable'))
    monkeypatch.setattr(ps, 'generate_photo_set', generation)
    env.bot.download.side_effect = lambda file_id: io.BytesIO(JPEG + file_id.encode())
    result = deliver(env, 'free')
    rows = deliveries(env)
    assert result == [r.id for r in rows] and len(rows) == count
    assert {r.source_delivery_id for r in rows} == set(source_ids)
    assert all(r.telegram_file_id is None and r.full_resolution_bytes for r in rows)
    assert all(r.estimated_cost_usd == 0.0 for r in rows)
    assert not ps.query_community_photos(TG, CHAR, 'cafe', 3, count=3, include_app=True)
    assert accounting(env) == (10 * ps.PEACH_SCALE, 2 * ps.PEACH_SCALE, 1, 0)
    assert generation.await_count == int(not first)
    no_telegram_output(env, downloads=count if telegram else 0)


def test_credit_never_uses_available_pool_or_library(env, monkeypatch):
    monkeypatch.setattr(ps, 'COMMUNITY_POOL_ENABLED', True)
    monkeypatch.setattr(ps, 'COMMUNITY_POOL_FIRST', True)
    seed_community(env, 3)
    enable_library(env, monkeypatch)
    fake, _ = generate(monkeypatch, 1)
    assert len(deliver(env)) == 1
    assert accounting(env) == (10 * ps.PEACH_SCALE, 2 * ps.PEACH_SCALE, 0, 0)
    ps.choose_fallback_pack.assert_not_called()
    fake.assert_awaited_once()
    no_telegram_output(env)


@pytest.mark.parametrize('delivery_type', ['credit', 'paid'])
def test_paid_generation_failure_propagates_for_refund(env, monkeypatch, delivery_type):
    failure = ps.PhotoGenerationError('seedream45', 'provider_failure')
    monkeypatch.setattr(ps, 'generate_photo_set', AsyncMock(side_effect=failure))
    enable_library(env, monkeypatch)
    with pytest.raises(ps.PhotoGenerationError) as caught:
        deliver(env, delivery_type)
    assert caught.value is failure
    assert not deliveries(env)
    assert accounting(env) == (10 * ps.PEACH_SCALE, 2 * ps.PEACH_SCALE, 0, 0)
    env.callback.assert_not_called()
    ps.choose_fallback_pack.assert_not_called()
    no_telegram_output(env)


@pytest.mark.parametrize('source', ['ai', 'library_fallback', 'library_topup', 'community', 'community_fallback'])
def test_callback_failure_is_not_success_or_a_generation_retry(env, monkeypatch, source):
    generation, _ = generate(monkeypatch)
    delivery_type = 'credit'
    if source != 'ai':
        delivery_type = 'free'
        if source == 'library_topup':
            generation, _ = generate(monkeypatch, 1)
        else:
            generation.side_effect = ps.PhotoGenerationError('seedream45', 'unavailable')
        if source.startswith('library'):
            enable_library(env, monkeypatch)
        else:
            monkeypatch.setattr(ps, 'COMMUNITY_POOL_ENABLED', True)
            monkeypatch.setattr(ps, 'COMMUNITY_POOL_FIRST', source == 'community')
            seed_community(env, 3)
    failure = OSError('app storage unavailable')
    successes = 2 if source == 'ai' else int(source == 'library_topup')
    original_callback = env.callback.side_effect

    async def failing(data, mime, delivery_id, caption):
        if len(env.received) == successes:
            raise failure
        await original_callback(data, mime, delivery_id, caption)

    env.callback.side_effect = failing
    with pytest.raises(ps.PhotoAppDeliveryError) as caught:
        deliver(env, delivery_type)
    assert caught.value.__cause__ is failure
    assert len(env.received) == successes
    assert len(deliveries(env)) == successes + 1
    assert accounting(env) == (10 * ps.PEACH_SCALE, 2 * ps.PEACH_SCALE, 0, 0)
    assert ps.get_state(TG).outfit != 'linen'
    ps.mark_pack_seen.assert_not_called()
    ps.mark_items_seen.assert_not_called()
    assert generation.await_count == int(source != 'community')
    no_telegram_output(env, downloads=int(source.startswith('library')))


def test_actual_generation_wrapper_does_not_turn_callback_error_into_provider_fallback(env, monkeypatch):
    monkeypatch.setattr(ps, 'resolve_character', Mock(return_value={}))
    monkeypatch.setattr(ps, 'enrich_request_with_idea', AsyncMock(side_effect=lambda tid, req, **kw: (req, None)))
    monkeypatch.setattr(ps, '_resolve_request', lambda tid, req, **kw: req)
    monkeypatch.setattr(ps, 'choose_photo_provider', Mock(return_value='seedream45'))
    monkeypatch.setattr(ps.spend_service, 'image_generation_allowed', Mock(return_value=True))
    monkeypatch.setattr(ps.spend_service, 'set_spend_user', Mock())
    monkeypatch.setattr(ps, 'PHOTO_ROUTER_MODE', 'hybrid')
    monkeypatch.setattr(ps, 'GEMINI_IMAGE_ENABLED', True)
    monkeypatch.setattr(ps, 'GEMINI_API_KEY', 'fake-test-key')
    fallback = AsyncMock(side_effect=AssertionError('new generation after callback failure'))
    monkeypatch.setattr(ps, '_run_gemini_set', fallback)
    monkeypatch.setattr(ps, '_run_openai_set', fallback)
    failure = ps.PhotoGenerationError('app', 'storage_failed')
    env.callback.side_effect = failure

    async def provider(character, telegram_id, resolved, *, on_frame, character_id, frames):
        assert character_id == CHAR
        await on_frame(ps.GeneratedPhoto(data=PNG, provider='seedream45'), 0)
        raise AssertionError('callback failure swallowed')

    engine = AsyncMock(side_effect=provider)
    monkeypatch.setattr(ps, '_run_seedream_set', engine)
    with pytest.raises(ps.PhotoAppDeliveryError) as caught:
        deliver(env, 'free')
    assert caught.value.__cause__ is failure
    engine.assert_awaited_once()
    fallback.assert_not_called()
    ps.choose_fallback_pack.assert_not_called()
    assert accounting(env) == (10 * ps.PEACH_SCALE, 2 * ps.PEACH_SCALE, 0, 0)
    no_telegram_output(env)


@pytest.mark.parametrize('data,mime', [(PNG, 'image/png'), (JPEG, 'image/jpeg'), (WEBP, 'image/webp')])
def test_url_only_provider_downloads_exact_bytes_once(env, monkeypatch, data, mime):
    response = SimpleNamespace(status_code=200, content=data)
    client = AsyncMock()
    client.get.return_value = response
    client.__aenter__.return_value = client
    factory = Mock(return_value=client)
    monkeypatch.setattr(ps.httpx, 'AsyncClient', factory)

    async def generate_url(telegram_id, request, *, on_frame, character_id):
        frame = ps.GeneratedPhoto(url='https://provider.invalid/frame', provider='seedream45')
        await on_frame(frame, 0)
        return [frame], request

    monkeypatch.setattr(ps, 'generate_photo_set', AsyncMock(side_effect=generate_url))
    result = deliver(env)
    assert env.received == [(data, mime, result[0], 'character caption')]
    assert len(deliveries(env)) == 1
    client.get.assert_awaited_once_with('https://provider.invalid/frame')
    no_telegram_output(env)


@pytest.mark.parametrize('source', ['url', 'library'])
def test_empty_download_never_fulfills_or_charges(env, monkeypatch, source):
    if source == 'url':
        monkeypatch.setattr(ps, '_download_result_bytes', AsyncMock(return_value=None))

        async def generate_url(telegram_id, request, *, on_frame, character_id):
            await on_frame(ps.GeneratedPhoto(url='https://provider.invalid/missing'), 0)

        monkeypatch.setattr(ps, 'generate_photo_set', AsyncMock(side_effect=generate_url))
    else:
        monkeypatch.setattr(ps, 'generate_photo_set', AsyncMock(side_effect=ps.PhotoGenerationError('test', 'failed')))
        enable_library(env, monkeypatch)
        env.bot.download.side_effect = lambda file_id: io.BytesIO()
    with pytest.raises(ps.PhotoAppDeliveryError):
        deliver(env, 'free')
    env.callback.assert_not_called()
    assert not deliveries(env)
    assert accounting(env) == (10 * ps.PEACH_SCALE, 2 * ps.PEACH_SCALE, 0, 0)
    no_telegram_output(env, downloads=int(source == 'library'))


def test_app_queries_are_opt_in_and_owner_scoped(env, monkeypatch):
    legacy_id = ps._insert_delivery_row(TG, 'cafe', 'paid', character_id=CHAR, file_id='legacy-file')
    generate(monkeypatch, 1)
    app_id = deliver(env)[0]
    assert ps.get_latest_photo_delivery(TG)['id'] == legacy_id
    latest = ps.get_latest_photo_delivery(TG, include_app=True)
    assert latest['id'] == app_id and latest['media_bytes'] == PNG + b'\x00'
    assert latest['mime_type'] == 'image/png' and latest['telegram_file_id'] is None
    assert ps.get_gallery_page(TG)['total'] == 1
    assert ps.get_gallery_page(TG, include_app=True)['total'] == 2
    assert ps.get_gallery_item_bytes(TG, app_id)['bytes'] == PNG + b'\x00'
    assert ps.get_photo_delivery_for_user(TG + 1, app_id) is None
    assert ps.get_gallery_item_bytes(TG + 1, app_id) is None
    monkeypatch.setattr(ps, 'COMMUNITY_POOL_ENABLED', True)
    assert not ps.query_community_photos(TG + 1, CHAR, 'cafe', 3)
    pool = ps.query_community_photos(TG + 1, CHAR, 'cafe', 3, include_app=True)
    assert [p['id'] for p in pool] == [app_id]
    assert ps.admin_pool_get(app_id) is None
    no_telegram_output(env)


@pytest.mark.parametrize('gate,reason,delivery_type', [
    ('scene_allowed_for_stage', 'scene_locked', 'credit'),
    ('is_adult_confirmed', 'age_gate', 'credit'),
    ('has_free_photo', 'quota', 'free'),
    ('get_photo_credits', 'no_credit', 'credit'),
])
def test_access_checks_precede_app_delivery(env, monkeypatch, gate, reason, delivery_type):
    generate(monkeypatch)
    monkeypatch.setattr(ps, gate, Mock(return_value=False))
    if gate == 'is_adult_confirmed':
        ps.requires_adult_confirmation.return_value = True
    with pytest.raises(PermissionError, match=reason):
        deliver(env, delivery_type)
    ps.generate_photo_set.assert_not_called()
    env.callback.assert_not_called()
    assert not deliveries(env)
    no_telegram_output(env)


@pytest.mark.parametrize('count', [1, 3])
def test_default_telegram_admin_path_and_credit_semantics_remain(env, monkeypatch, count):
    generate(monkeypatch, count)
    markup = object()
    ps._photo_action_markup.side_effect = None
    ps._photo_action_markup.return_value = markup
    env.bot.send_photo.side_effect = lambda *args, **kwargs: SimpleNamespace(
        photo=[SimpleNamespace(file_id='sent-file')])
    env.bot.send_message.side_effect = None
    messages = deliver(env, app_delivery=None)
    assert len(messages) == count and all(m.photo[0].file_id == 'sent-file' for m in messages)
    assert all(r.telegram_file_id == 'sent-file' for r in deliveries(env))
    assert env.bot.send_photo.await_count == count
    assert env.bot.send_photo.await_args_list[0].kwargs['caption'] == 'character caption'
    assert env.bot.send_photo.await_args_list[0].kwargs['reply_markup'] is markup
    assert env.bot.send_message.await_count == int(count == 1)
    assert accounting(env) == (10 * ps.PEACH_SCALE - (ps.PEACH_SCALE if count == 3 else 0),
                               2 * ps.PEACH_SCALE, 0, int(count == 3))
    env.callback.assert_not_called()


def test_default_admin_delivery_still_sends_telegram(env, monkeypatch):
    generate(monkeypatch)
    ps._photo_action_markup.side_effect = None
    ps._photo_action_markup.return_value = None
    env.bot.send_photo.side_effect = lambda *args, **kwargs: SimpleNamespace(photo=[])
    assert len(deliver(env, 'admin', app_delivery=None)) == 3
    assert env.bot.send_photo.await_count == 3
    assert accounting(env) == (10 * ps.PEACH_SCALE, 2 * ps.PEACH_SCALE, 0, 0)
    env.callback.assert_not_called()
