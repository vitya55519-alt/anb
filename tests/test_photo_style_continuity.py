"""Ordinary photo continuity: isolated DB, dummy credentials, no generation."""
import asyncio
import json
import os
import socket
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

# Protect standalone collection as well as the explicit safe test launcher.
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['NO_PROXY'] = '*'
for key in ('OPENAI_API_KEY', 'IMAGE_API_KEY', 'GEMINI_API_KEY', 'MINIMAX_API_KEY',
            'FAL_KEY', 'SPICYAPI_KEY'):
    os.environ[key] = 'test-not-a-real-key'
os.environ['TELEGRAM_TOKEN'] = '123456:test-not-a-real-token'

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from models.app_models import CharacterState
from models.photo_models import PhotoDelivery
from models.waifu_models import Base
from services import db, photo_service as ps, state_service as ss, user_service as us
from services import gift_shop_service, scene_card_service, wardrobe_service


TG = 910001
CID = 'style_test_a'
OTHER = 'style_test_b'


@pytest.fixture
def env(monkeypatch, tmp_path):
    engine = create_engine(f'sqlite:///{(tmp_path / "style.sqlite").as_posix()}',
                           connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    original = db.SessionLocal
    for name, module in list(sys.modules.items()):
        if name.startswith('services.') and getattr(module, 'SessionLocal', None) is original:
            monkeypatch.setattr(module, 'SessionLocal', sessions)
    monkeypatch.setattr(db, 'engine', engine)
    original_connect = socket.socket.connect
    def local_only(sock, address):
        # Windows asyncio builds its internal socketpair over loopback.
        assert address[0] in {'127.0.0.1', '::1'}, 'external network forbidden'
        return original_connect(sock, address)
    monkeypatch.setattr(socket.socket, 'connect', local_only)
    for method in ('_run_spicy_set', '_run_seedream_set', '_run_gemini_set', '_run_openai_set'):
        monkeypatch.setattr(ps, method, AsyncMock(side_effect=AssertionError('generation forbidden')))
    monkeypatch.setattr(ps, 'PHOTO_SET_SIZE', 3)
    monkeypatch.setattr(ps, 'get_relationship_level', lambda *a: 2)
    monkeypatch.setattr(ps.spicy_confidence, 'current_level', lambda *a: 0)
    monkeypatch.setattr(ps, '_path_is_passion', lambda *a: False)
    monkeypatch.setattr(ps, '_path_is_tender', lambda *a: False)
    monkeypatch.setattr(ps, '_persona_style_is_tender', lambda *a: False)
    monkeypatch.setattr(ps, 'marital_photo_detail', lambda *a: '')
    monkeypatch.setattr(ps, 'get_character_preferences', lambda *a: {})
    monkeypatch.setattr(ps, 'get_visual_preferences', lambda *a: {
        'hairstyles': {'history-driven preferred style': 100}, 'colors': {}})
    monkeypatch.setattr(wardrobe_service, 'photo_overrides', lambda *a: {})
    monkeypatch.setattr(gift_shop_service, 'photo_overrides', lambda *a: {})
    monkeypatch.setattr(ps, '_today', lambda: date(2026, 1, 1))
    monkeypatch.setattr(ps, 'resolve_character', lambda cid: {
        'visual_identity': {'preserve_identity': ['dark brown shoulder-length hair']}})
    style = {'hairstyles': ['a side part', 'soft waves', 'a low ponytail'],
             'hair_colors': ['brown', 'blonde']}
    monkeypatch.setattr(ps, '_photo_style', lambda cid: style)
    ps._recent_outfit_colors.clear()
    try:
        yield SimpleNamespace(sessions=sessions, style=style)
    finally:
        monkeypatch.undo()
        for name, module in list(sys.modules.items()):
            if name.startswith('services.') and getattr(module, 'SessionLocal', None) is sessions:
                module.SessionLocal = original
        ps._recent_outfit_colors.clear()
        engine.dispose()


def resolve(request=None, cid=CID, tid=TG):
    return ps._resolve_request(tid, request or ps.PhotoRequest(scene='fashion'), character_id=cid)


def test_same_hair_for_three_utc_days_despite_history_preferences_and_random(env, monkeypatch):
    hairstyles = []
    for day in (1, 2, 3):
        monkeypatch.setattr(ps, '_today', lambda day=day: date(2026, 1, day))
        monkeypatch.setattr(ps.random, 'random', lambda day=day: (day - 1) / 2)
        us.update_state(TG, character_id=CID, hairstyle=env.style['hairstyles'][day - 1],
                        recent_hairstyles_json=json.dumps(env.style['hairstyles'][:day]))
        resolved = resolve()
        hairstyles.append(resolved.hairstyle)
        assert resolved.hair_color == ''  # canonical reference, no automatic dye
    assert len(set(hairstyles)) == 1
    assert hairstyles[0].split(';')[0] in env.style['hairstyles']
    assert resolve(tid=TG + 1).hairstyle == hairstyles[0]


def test_adjacent_periods_change_even_with_duplicate_styles(env, monkeypatch):
    env.style['hairstyles'] = [' a side part ', 'A SIDE PART', '', None, 'soft waves']
    previous = None
    for day in (1, 4, 7, 10, 13):
        monkeypatch.setattr(ps, '_today', lambda day=day: date(2026, 1, day))
        current = resolve().hairstyle
        assert current != previous
        previous = current


def test_explicit_hair_and_color_win(env):
    result = resolve(ps.PhotoRequest(scene='fashion', hairstyle='my requested braid', hair_color='auburn'))
    assert result.hairstyle == 'my requested braid'
    assert result.hair_color == 'auburn'


@pytest.mark.parametrize('styles', [[], None, ['', None], 'not a list', ['single style']])
def test_nonempty_fallback_and_single_style(env, styles):
    env.style['hairstyles'] = styles
    result = resolve()
    assert result.hairstyle.strip()
    assert 'canonical hair length and cut' in result.hairstyle


def test_short_identity_cannot_receive_long_generic_hair(env, monkeypatch):
    monkeypatch.setattr(ps, 'resolve_character', lambda cid: {
        'visual_identity': {'preserve_identity': ['jet black sleek bob']}})
    env.style['hairstyles'] = ['long loose hair', 'high ponytail', 'a long braid']
    result = resolve()
    assert all(word not in result.hairstyle for word in ('long', 'ponytail', 'braid'))
    assert result.hair_color == ''


def test_constructor_fallback_keeps_canonical_color_without_monthly_dye(env, monkeypatch):
    env.style.clear()
    monkeypatch.setattr(ps, 'current_hair_color', Mock(side_effect=AssertionError('automatic dye')))
    result = resolve(cid='custom_style_test')
    assert result.hairstyle and result.hair_color == ''


def test_utc_clock_is_used(monkeypatch):
    # Do not use env's patched _today here.
    class Clock:
        @staticmethod
        def now(tz):
            assert tz is timezone.utc
            return datetime(2026, 1, 4, 0, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(ps, 'datetime', Clock)
    assert ps._today() == date(2026, 1, 4)


def test_character_and_user_pairs_are_isolated_without_copying_legacy(env):
    us.update_state(TG, outfit='legacy shared coat', recent_outfits_json='["legacy"]', mood='shared mood')
    fresh = us.get_state(TG, character_id=CID)
    assert fresh.outfit is None and fresh.recent_outfits_json == '[]'
    us.update_state(TG, character_id=CID, outfit='coat A', hairstyle='hair A', recent_outfits_json='["A"]')
    us.update_state(TG, character_id=OTHER, outfit='coat B', hairstyle='hair B', recent_outfits_json='["B"]')
    assert us.get_state(TG, CID).outfit == 'coat A'
    assert us.get_state(TG, OTHER).recent_outfits_json == '["B"]'
    assert us.get_state(TG + 1, CID).outfit is None
    assert us.get_state(TG).outfit == 'legacy shared coat'
    assert us.get_state(TG, None).mood == 'shared mood'


def test_visual_context_is_scoped_but_mood_and_pending_hook_keep_defaults(env):
    us.update_state(TG, mood='shared mood', pending_hook='shared hook', outfit='legacy coat')
    us.update_state(TG, CID, outfit='coat A', hairstyle='hair A')
    us.update_state(TG, OTHER, outfit='coat B', hairstyle='hair B')
    ss.ensure_life_state(TG)
    us.update_state(TG, mood='shared mood')
    text = ss.state_context(TG, CID)
    assert 'coat A' in text and 'hair A' in text
    assert 'coat B' not in text and 'legacy coat' not in text
    assert 'shared mood' in text and 'shared hook' in text
    assert 'legacy coat' in ss.state_context(TG)


def test_pair_life_location_never_comes_from_another_character(env):
    us.update_state(TG, CID, location='studio A', activity='preparing outfit')
    us.update_state(TG, OTHER, location='studio B', activity='drinking coffee')
    assert 'studio A' in resolve(ps.PhotoRequest(scene='selfie')).location
    assert 'studio B' not in resolve(ps.PhotoRequest(scene='selfie')).location
    assert ss.ensure_life_state(TG, character_id=OTHER).location == 'studio B'


def test_unique_collision_recovers_the_winning_row(env, monkeypatch):
    uid = us.ensure_user(TG)
    winner = us.get_state(TG, CID)
    with env.sessions() as session:
        original_scalar = session.scalar
        calls = 0
        def stale_select(*args, **kwargs):
            nonlocal calls
            calls += 1
            return None if calls == 1 else original_scalar(*args, **kwargs)
        monkeypatch.setattr(session, 'scalar', stale_select)
        # Force the pre-insert SELECT race; INSERT hits a real UNIQUE violation.
        state = us._ensure_character_state(session, uid, CID)
        assert state.id == winner.id
        state.outfit = 'saved after collision'
        session.commit()
    assert us.get_state(TG, CID).outfit == 'saved after collision'


def test_concurrent_first_access_creates_one_pair(env):
    with ThreadPoolExecutor(max_workers=4) as workers:
        ids = list(workers.map(lambda _: us.get_state(TG, CID).id, range(8)))
    assert len(set(ids)) == 1
    uid = us.ensure_user(TG)
    with env.sessions() as session:
        assert session.scalar(select(func.count(CharacterState.id)).where(
            CharacterState.user_id == uid, CharacterState.character_id == CID)) == 1


@pytest.mark.parametrize(('raw', 'expected'), [
    ('  Linen   suit in a Deep Blue color', 'linen suit'),
    ('Linen suit in a ivory tone', 'linen suit'),
    ('Linen suit in a black color, low shoes, stockings', 'linen suit'),
    ('Black blazer, white shirt', 'black blazer, white shirt'),
    ('A dress in a color-block design', 'a dress in a color-block design'),
])
def test_outfit_color_suffix_normalization(raw, expected):
    assert ps._outfit_history_key(raw) == expected


def test_outfit_history_and_picks_compare_base_garments(env, monkeypatch):
    monkeypatch.setattr(ps, '_wardrobe_pool', lambda *a, **k: ['linen suit', 'cotton dress', 'jacket', 'jeans'])
    monkeypatch.setattr(ps.random, 'choice', lambda options: options[0])
    us.update_state(TG, CID, outfit='linen suit in a navy tone, shoes',
                    recent_outfits_json='["linen suit in a black color"]')
    result = ps._choose_progression_outfits(TG, ps.PhotoRequest(scene='fashion'), 'summer', character_id=CID)
    assert [ps._outfit_history_key(x) for x in result] == ['cotton dress', 'jacket', 'jeans']
    other = ps._choose_progression_outfits(TG, ps.PhotoRequest(scene='fashion'), 'summer', character_id=OTHER)
    assert ps._outfit_history_key(other[0]) == 'linen suit'
    assert (TG, CID) in ps._recent_outfit_colors and (TG, OTHER) in ps._recent_outfit_colors


def test_exhausted_outfit_history_still_has_fallback(env, monkeypatch):
    monkeypatch.setattr(ps, '_wardrobe_pool', lambda *a, **k: ['linen suit'])
    us.update_state(TG, CID, recent_outfits_json='["linen suit in a black color"]')
    assert len(resolve().pack_outfits) == 3


@pytest.mark.parametrize('source', ['wardrobe', 'gift', 'custom', 'pack'])
def test_explicit_and_gift_outfits_beat_auto_variations_and_keep_scene_card(env, monkeypatch, source):
    # V3.167.17: at spicy level > 0 the level itself picks the outfit; an explicit
    # outfit is pinned only on the ordinary (level 0) branch, which this test covers.
    monkeypatch.setattr(ps.spicy_confidence, 'current_level', lambda *a: 0)
    monkeypatch.setattr(wardrobe_service, 'photo_overrides', lambda *a: {'clothing': 'wardrobe linen suit'})
    monkeypatch.setattr(gift_shop_service, 'photo_overrides', lambda *a: {'clothing': 'gift cotton dress'})
    scene_card_service.remember(TG, CID, 'где=кафе | рядом=нет | сцена=a cafe by the river')
    request = ps.PhotoRequest(scene='fashion')
    expected = 'wardrobe linen suit'
    if source == 'gift':
        monkeypatch.setattr(wardrobe_service, 'photo_overrides', lambda *a: {})
        expected = 'gift cotton dress'
    elif source == 'custom':
        request = ps.replace(request, clothing='my custom coat', customized=True)
        expected = 'my custom coat'
    elif source == 'pack':
        request = ps.replace(request, pack_outfits=('my first coat', 'my second coat'))
        expected = 'my second coat'
    result = resolve(request)
    assert result.clothing == expected
    assert result.pack_outfits == (request.pack_outfits or (expected,) * 3)
    assert result.location == 'PLACE FROM HER MESSAGE: a cafe by the river'
    if source in {'wardrobe', 'gift'}:
        assert result.gift_outfit
    manual = resolve(ps.replace(request, location='my chosen studio', customized=True))
    assert manual.location == 'my chosen studio'


def test_pose_rotation_counts_only_confirmed_deliveries_for_pair(env):
    uid = us.ensure_user(TG)
    other_uid = us.ensure_user(TG + 1)
    with env.sessions() as session:
        for user_id, cid, file_id, data in (
            (uid, CID, 'confirmed-file', None), (uid, OTHER, 'other-girl', None),
            (other_uid, CID, 'other-user', None), (uid, CID, None, b'attempt-only'),
        ):
            session.add(PhotoDelivery(user_id=user_id, character_id=cid, scene='fashion',
                                      delivery_type='free', telegram_file_id=file_id,
                                      image_url='https://example.invalid/attempt', full_resolution_bytes=data))
        session.commit()
    import random as _r
    order = list(ps.POSE_POOL); _r.Random(f'{uid}:{CID}').shuffle(order)
    assert resolve().pose_rotation[0] == order[1]     # one confirmed delivery for this pair
    order2 = list(ps.POSE_POOL); _r.Random(f'{uid}:new_pair').shuffle(order2)
    assert resolve(cid='new_pair').pose_rotation[0] == order2[0]
    explicit = ('my precise pose', 'my second pose')
    assert resolve(ps.PhotoRequest(scene='fashion', pose_rotation=explicit)).pose_rotation == explicit


def test_app_delivery_stays_successful_if_analytics_lookup_fails(env, monkeypatch):
    received = []

    async def delivered(data, mime, row_id, caption):
        received.append(row_id)
        monkeypatch.setattr(ps, 'ensure_user', Mock(side_effect=RuntimeError('analytics lookup failed')))

    row_id = asyncio.run(ps._deliver_app_photo(
        SimpleNamespace(), TG, 'fashion', 'free', delivered,
        data=b'\xff\xd8\xffsynthetic-image', character_id=CID))
    assert received == [row_id]


def test_app_only_success_advances_pose_but_failed_delivery_does_not(env):
    bot = SimpleNamespace()
    received = []

    def _order(cid=CID):
        import random as _r
        o = list(ps.POSE_POOL); _r.Random(f'{us.ensure_user(TG)}:{cid}').shuffle(o)
        return o

    async def delivered(data, mime, row_id, caption):
        received.append(row_id)

    async def failed(*args):
        raise RuntimeError('synthetic storage failure')

    def send(callback, cid=CID, tid=TG):
        return asyncio.run(ps._deliver_app_photo(
            bot, tid, 'fashion', 'free', callback,
            data=b'\xff\xd8\xffsynthetic-image', character_id=cid))

    assert resolve().pose_rotation[0] == _order()[0]
    with pytest.raises(ps.PhotoAppDeliveryError):
        send(failed)
    assert resolve().pose_rotation[0] == _order()[0]
    for index in (1, 2):
        send(delivered)
        assert resolve().pose_rotation[0] == _order()[index]
    send(delivered, cid=OTHER)
    send(delivered, tid=TG + 1)
    assert resolve().pose_rotation[0] == _order()[2]
    # Telegram replay of the same frame must not count twice.
    ps._attach_delivery_file(received[0], 'synthetic-telegram-file')
    assert resolve().pose_rotation[0] == _order()[2]
    with pytest.raises(ps.PhotoAppDeliveryError):
        send(failed)
    assert resolve().pose_rotation[0] == _order()[2]


@pytest.mark.parametrize('scene', sorted(ps.SEEDREAM_ADULT_SCENES | ps.ADULT_SCENES | {'peek', 'dressing'}))
def test_intimate_scenes_never_enter_new_style_helpers(env, monkeypatch, scene):
    forbidden = Mock(side_effect=AssertionError('ordinary-only helper'))
    monkeypatch.setattr(ps, '_ordinary_hairstyle', forbidden)
    monkeypatch.setattr(ps, '_ordinary_pose_rotation', forbidden)
    monkeypatch.setattr(ps, '_outfit_history_key', forbidden)
    result = resolve(ps.PhotoRequest(scene=scene))
    assert result.hair_color in env.style['hair_colors']
    forbidden.assert_not_called()


@pytest.mark.parametrize('photo_request', [
    ps.PhotoRequest(scene='fashion', clothing='naked'),
    ps.PhotoRequest(scene='fashion', clothing='sheer lingerie'),
    ps.PhotoRequest(scene='fashion', location='an erotic scene'),
    ps.PhotoRequest(scene='selfie', starter_note='scenario'),
    ps.PhotoRequest(scene='fashion', with_guest='other'),
    ps.PhotoRequest(scene='unknown'),
])
def test_nonordinary_requests_are_excluded(photo_request):
    assert not ps._ordinary_style_request(photo_request, 2)


def test_high_level_home_and_auto_spicy_keep_legacy_styling(env, monkeypatch):
    monkeypatch.setattr(ps, 'get_relationship_level', lambda *a: 6)
    monkeypatch.setattr(ps, '_ordinary_hairstyle', Mock(side_effect=AssertionError('ordinary helper')))
    assert resolve(ps.PhotoRequest(scene='selfie')).hair_color in env.style['hair_colors']
    # V3.167.22: 18+ frames follow the same 3-day hairstyle helper as romance.
    monkeypatch.setattr(ps, '_ordinary_hairstyle', Mock(return_value='3-day hair'))
    monkeypatch.setattr(ps.spicy_confidence, 'current_level', lambda *a: 5)
    spicy = resolve()
    assert spicy.hair_color in env.style['hair_colors']
    assert spicy.hairstyle == '3-day hair'


def test_delivered_history_is_written_to_the_resolved_pair(env, monkeypatch):
    us.update_state(TG, outfit='legacy shared coat')
    us.update_state(TG, OTHER, outfit='other coat')
    request = ps.PhotoRequest(scene='fashion', clothing='delivered coat', hairstyle='delivered hair')
    resolved = resolve(request)
    monkeypatch.setattr(ps, 'COMMUNITY_POOL_ENABLED', False)
    monkeypatch.setattr(ps, 'get_relationship_stage', lambda *a: 'close')
    monkeypatch.setattr(ps, 'scene_allowed_for_stage', lambda *a: True)
    monkeypatch.setattr(ps, 'requires_adult_confirmation', lambda *a: False)
    monkeypatch.setattr(ps, 'has_free_photo', lambda *a, **k: True)
    monkeypatch.setattr(wardrobe_service, 'worn_today', lambda *a: None)
    monkeypatch.setattr(ps, 'track_event', Mock())
    monkeypatch.setattr(ps, '_her', lambda text, cid: text)
    async def generate(tid, req, on_frame, **kwargs):
        photos = [ps.GeneratedPhoto(data=b'fake-photo', provider='test') for _ in range(3)]
        for index, photo in enumerate(photos):
            await on_frame(photo, index)
        return photos, resolved
    monkeypatch.setattr(ps, 'generate_photo_set', generate)
    callback = AsyncMock()
    bot = SimpleNamespace(send_photo=AsyncMock(side_effect=AssertionError('Telegram forbidden')))
    asyncio.run(ps.deliver_photo(bot, TG, TG, request, 'free', character_id=CID, app_delivery=callback))
    saved = us.get_state(TG, CID)
    assert saved.outfit == 'delivered coat' and saved.hairstyle == 'delivered hair'
    assert json.loads(saved.recent_outfits_json) == ['delivered coat'] * 3
    assert us.get_state(TG).outfit == 'legacy shared coat'
    assert us.get_state(TG, OTHER).outfit == 'other coat'
