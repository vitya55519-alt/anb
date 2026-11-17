"""Focused delivery regressions. Run with DATABASE_URL pointing to temp SQLite."""
import asyncio
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import sessionmaker

from models.app_models import Message, ProductEvent, User
from models.waifu_models import Base
from services import app_ping as P, db, life_backlog as B, memory_service as M
from services import scheduler_service as S, webapp_service as W

CHAR = 'anna_01'
TG = 915001


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + (tmp_path / 'events.sqlite').as_posix(),
                           connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    original = db.SessionLocal
    for module in list(sys.modules.values()):
        if getattr(module, '__name__', '').startswith('services.') and getattr(module, 'SessionLocal', None) is original:
            monkeypatch.setattr(module, 'SessionLocal', sessions)
    monkeypatch.setattr(db, 'engine', engine)
    monkeypatch.setattr(W, 'APP_MEDIA_DIR', tmp_path / 'media')
    for state in (P._presence, P._pending, P._last_ping, P._day_count, P._seen, P._armed, P._sending,
                  B._denial_memo):
        state.clear()
    monkeypatch.setattr(P, '_arm', lambda *args: None)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with sessions() as s:
        user = User(telegram_id=str(TG), name='Test', selected_character=CHAR,
                    timezone='UTC', proactive_enabled=True, notify_rituals=True,
                    created_at=now - timedelta(days=10), last_active_at=now - timedelta(hours=6))
        s.add(user)
        s.commit()
        uid = user.id
    try:
        yield SimpleNamespace(uid=uid, sessions=sessions, now=now, engine=engine)
    finally:
        # Undo recorded patches first, then catch aliases imported during the test.
        # Otherwise later monkeypatch teardown can put the temporary factory back.
        monkeypatch.undo()
        for name, module in list(sys.modules.items()):
            if (name.startswith('services.') or name == 'main') and getattr(module, 'SessionLocal', None) is sessions:
                module.SessionLocal = original
        engine.dispose()


@pytest.mark.parametrize('source', ['delivery', 'actions'])
def test_database_fixtures_restore_late_imports(tmp_path, source):
    """A fresh interpreter must exercise the imports that collection can mask."""
    import os
    from pathlib import Path
    import subprocess

    nodes = ['tests/test_v31674_silence_ladder.py::test_a_gift_frame_goes_through_the_shared_free_cap']
    if source == 'delivery':
        nodes[:0] = [
            'tests/test_app_event_delivery.py::test_pool_denials_are_recorded_once_without_generating[0-life]',
            # The leaked delivery DB contains user 1; a second user exposes the split.
            'tests/test_v31674_silence_ladder.py::test_a_gift_needs_something_to_give',
        ]
    else:
        nodes.insert(0, 'tests/test_app_event_actions.py::test_action_api_uses_stored_reply_not_client_payload')
    env = {k: v for k, v in os.environ.items() if 'proxy' not in k.lower()}
    env.update(DATABASE_URL='sqlite:///' + (tmp_path / 'baseline.sqlite').as_posix(),
               TELEGRAM_TOKEN='123456:test-only-token', MINIMAX_API_KEY='test-local-only',
               GEMINI_API_KEY='test-local-only', PYTHON_DOTENV_DISABLED='1',
               PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    script = '''
import sys
import pytest
from services import db
db.init_db()
result = pytest.main(['-q', '--tb=short', '-p', 'no:cacheprovider', *sys.argv[1:]])
assert result == 0
stale = [name for name, module in list(sys.modules.items())
         if (name.startswith('services.') or name == 'main')
         and hasattr(module, 'SessionLocal') and module.SessionLocal is not db.SessionLocal]
assert not stale, stale
'''
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', script,
                             '--basetemp=' + str(tmp_path / 'ordered'), *nodes],
                            cwd=Path(__file__).resolve().parents[1], env=env,
                            capture_output=True, text=True, encoding='utf-8', timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr


def lines(env):
    with env.sessions() as s:
        return list(s.scalars(select(Message).where(Message.user_id == env.uid).order_by(Message.id)))


def add_line(env, role, content, days, origin=None):
    with env.sessions() as s:
        row = Message(user_id=env.uid, character_id=CHAR, role=role, content=content,
                      origin=origin, created_at=env.now - timedelta(days=days))
        s.add(row)
        s.commit()
        return row.id


def backlog(env, returned=False):
    add_line(env, 'user', 'left', 8)
    add_line(env, 'assistant', 'first private event', 7, B.LIFE_ORIGIN)
    add_line(env, 'assistant', 'second private event', 6, B.LIFE_ORIGIN)
    if returned:
        add_line(env, 'user', 'returned', 0.1)


def fake_bot():
    return SimpleNamespace(send_message=AsyncMock(), send_photo=AsyncMock(), send_video=AsyncMock(),
                           send_animation=AsyncMock(), download=AsyncMock())


def ping_context(monkeypatch, env):
    monkeypatch.setattr(P, '_user_ctx', lambda tg: {'uid': env.uid, 'lang': 'en', 'tz': 'UTC'})
    monkeypatch.setattr(P, '_character_name', lambda cid: 'Anna')
    monkeypatch.setattr(P, '_quiet_now', lambda tz: False)
    monkeypatch.setattr(P, '_read_since', lambda *args: False)
    monkeypatch.setattr('config.PUBLIC_BASE_URL', 'https://example.test')


def test_existing_table_actions_migration_is_additive_and_idempotent(fresh_db, monkeypatch, tmp_path):
    engine = create_engine('sqlite:///' + (tmp_path / 'legacy.sqlite').as_posix())
    legacy = Base.metadata.tables['messages'].to_metadata(__import__('sqlalchemy').MetaData())
    legacy._columns.remove(legacy.c.actions_json)
    legacy.create(engine)
    with engine.begin() as conn:
        conn.execute(legacy.insert().values(id=1, user_id=1, character_id=CHAR,
                                            role='assistant', content='preserved'))
    monkeypatch.setattr(db, 'engine', engine)
    assert db._auto_migrate_all_tables() == {'messages': ['actions_json']}
    assert db._auto_migrate_all_tables() == {}
    assert next(c for c in inspect(engine).get_columns('messages') if c['name'] == 'actions_json')['nullable']
    with engine.connect() as conn:
        assert conn.execute(text('SELECT content, actions_json FROM messages')).one() == ('preserved', None)
        assert conn.execute(text("SELECT COUNT(*) FROM app_migrations WHERE name = 'schema:messages:actions_json'")).scalar() == 1
    engine.dispose()


def test_actions_roundtrip_and_locked_fields_do_not_leak(fresh_db):
    from services import story_hooks
    story = story_hooks.pick_unused(TG)
    actions = [{'type': 'reply', 'label': 'Reply', 'text': 'Tell me more', 'callback_data': 'bad'},
               {'type': 'story_hook', 'label': 'Choice', 'story_key': story.key, 'choice': 'a'},
               {'type': 'callback', 'label': 'Unsafe', 'callback_data': 'admin:pay'},
               {'type': 'story_hook', 'label': 'Invalid', 'story_key': story.key, 'choice': 'x'}]
    mid = M.save_message(fresh_db.uid, CHAR, 'assistant', 'visible', origin=B.LIFE_ORIGIN,
                         actions=actions, draft_text='secret draft', image_prompt='secret image scene')
    row = W.api_chat_history(fresh_db.uid, CHAR)[0]
    assert row['id'] == mid and row['origin'] == 'life'
    assert len(row['actions']) == 2
    assert 'callback_data' not in json.dumps(row)
    assert 'secret' not in json.dumps(row)
    assert row['draft']['paid'] is False and row['live']['paid'] is False
    assert M.message_actions('invalid json') == []


@pytest.mark.parametrize('origin,channel', [(B.LIFE_ORIGIN, 'life'), (B.PUSH_ORIGIN, 'default'),
                                           (B.DIGEST_ORIGIN, 'default')])
def test_save_precedes_generic_notification_and_correct_channel(fresh_db, monkeypatch, origin, channel):
    def note(*args, **kwargs):
        assert lines(fresh_db)[-1].content == 'private text'
        assert args[4:] == () and args[3] == ''
        assert kwargs == {'channel': channel, 'generic': True}
        raise RuntimeError('notification unavailable')
    monkeypatch.setattr(P, 'note', note)
    assert S._app_delivery(fake_bot(), fresh_db.uid, TG, CHAR, 'private text', origin=origin)
    assert len(lines(fresh_db)) == 1


def test_no_notification_after_failed_save(fresh_db, monkeypatch):
    monkeypatch.setattr(M, 'save_message', Mock(side_effect=RuntimeError('db unavailable')))
    notify = Mock()
    monkeypatch.setattr(P, 'note', notify)
    assert S._app_delivery(fake_bot(), fresh_db.uid, TG, CHAR, 'private') is None
    notify.assert_not_called()


def test_life_ping_counter_independent_of_six_normal_notifications(fresh_db, monkeypatch):
    ping_context(monkeypatch, fresh_db)
    bot = fake_bot()
    P._day_count[TG] = (P._today(), 6)
    P._count_ping(TG)
    assert P.note(bot, TG, CHAR, 'hidden one', channel='life')
    assert P.note(bot, TG, CHAR, 'hidden two', channel='life')
    assert P.note(bot, TG, CHAR, 'normal')
    assert asyncio.run(P._deliver(bot, TG)) == 'capped'
    assert asyncio.run(P._deliver(bot, (TG, 'life'))) == 'sent'
    assert P._day_count[(TG, 'life')][1] == 1
    assert P._day_count[TG][1] == 7
    args, kwargs = bot.send_message.call_args
    assert args[0] == TG and 'hidden' not in args[1] and '+1 more' in args[1]
    assert kwargs['reply_markup'].inline_keyboard[0][0].web_app.url.endswith('char=anna_01')
    with fresh_db.sessions() as s:
        assert s.scalar(select(func.count(ProductEvent.id)).where(ProductEvent.event_name == 'life_event_sent')) == 0


def test_life_cap_does_not_consume_normal_counter(fresh_db, monkeypatch):
    ping_context(monkeypatch, fresh_db)
    bot = fake_bot()
    P._day_count[(TG, 'life')] = (P._today(), 4)
    P.note(bot, TG, CHAR, 'life', channel='life')
    P.note(bot, TG, CHAR, 'ordinary')
    assert asyncio.run(P._deliver(bot, (TG, 'life'))) == 'capped'
    assert asyncio.run(P._deliver(bot, TG)) == 'sent'
    assert P._day_count[TG][1] == 1


@pytest.mark.parametrize('guard', ['presence', 'read', 'seen', 'optout', 'quiet'])
def test_life_notifications_preserve_delivery_guards(fresh_db, monkeypatch, guard):
    ping_context(monkeypatch, fresh_db)
    bot = fake_bot()
    P.note(bot, TG, CHAR, 'private', channel='life')
    if guard == 'presence':
        P.touch(TG)
    elif guard == 'read':
        monkeypatch.setattr(P, '_read_since', lambda *args: True)
    elif guard == 'seen':
        P.seen(TG, CHAR)
    elif guard == 'optout':
        monkeypatch.setattr(P, '_user_ctx', lambda tg: None)
    else:
        monkeypatch.setattr(P, '_quiet_now', lambda tz: True)
    result = asyncio.run(P._deliver(bot, (TG, 'life')))
    if guard == 'quiet':
        assert result == 'sent' and bot.send_message.call_args.kwargs['disable_notification'] is True
    else:
        bot.send_message.assert_not_called()


def test_actual_optout_context_applies_to_both_rails(fresh_db, monkeypatch):
    monkeypatch.setattr(W, 'get_notification_prefs', lambda tg: {'enabled': True, 'new_messages': False})
    assert P._user_ctx(TG) is None
    monkeypatch.setattr(W, 'get_notification_prefs', lambda tg: {'enabled': True, 'new_messages': True})
    assert P._user_ctx(TG)['uid'] == fresh_db.uid
    with fresh_db.sessions() as s:
        s.get(User, fresh_db.uid).proactive_enabled = False
        s.commit()
    assert P._user_ctx(TG) is None


def test_collapse_cannot_expose_transferred_text(fresh_db, monkeypatch):
    ping_context(monkeypatch, fresh_db)
    bot = fake_bot()
    P.note(bot, TG, CHAR, 'transferred', generic=True)
    P.note(bot, TG, CHAR, 'later normal preview')
    assert asyncio.run(P._deliver(bot, TG)) == 'sent'
    assert 'preview' not in bot.send_message.call_args.args[1]
    assert 'transferred' not in bot.send_message.call_args.args[1]


def test_return_open_only_persists_one_digest_without_fake_turn(fresh_db):
    backlog(fresh_db)
    assert len(W.api_chat_history(fresh_db.uid, CHAR)) == 3
    assert B.due(fresh_db.uid, CHAR) == ''
    assert B.due(fresh_db.uid, CHAR, on_open=True)
    with fresh_db.sessions() as s:
        activity = s.get(User, fresh_db.uid).last_active_at
    history = W.api_chat_history(fresh_db.uid, CHAR, opened=True)
    assert len(history) == 4 and history[-1]['origin'] == B.DIGEST_ORIGIN
    assert B.digest_on_open(fresh_db.uid, TG, CHAR) is None
    assert len(W.api_chat_history(fresh_db.uid, CHAR, opened=True)) == 4
    assert len([row for row in lines(fresh_db) if row.role == 'user']) == 1
    with fresh_db.sessions() as s:
        assert s.get(User, fresh_db.uid).last_active_at == activity
    assert P._pending == {}


def test_open_helper_concurrent_requests_dedupe(fresh_db):
    from concurrent.futures import ThreadPoolExecutor
    backlog(fresh_db)
    with ThreadPoolExecutor(max_workers=3) as pool:
        ids = list(pool.map(lambda _: B.digest_on_open(fresh_db.uid, TG, CHAR), range(3)))
    assert sum(mid is not None for mid in ids) == 1
    assert len(lines(fresh_db)) == 4


def test_digest_does_not_expose_old_hidden_blocks(fresh_db):
    add_line(fresh_db, 'user', 'left', 8)
    add_line(fresh_db, 'assistant', 'THOUGHT: private inner block MESSAGE: Walked home', 7, B.LIFE_ORIGIN)
    add_line(fresh_db, 'assistant', 'DRAFT: private paid block MESSAGE: Made tea', 6, B.LIFE_ORIGIN)
    history = W.api_chat_history(fresh_db.uid, CHAR, opened=True)
    summary = history[-1]
    assert summary['origin'] == B.DIGEST_ORIGIN
    assert 'Walked home' in summary['content'] and 'Made tea' in summary['content']
    assert 'private' not in json.dumps(history)
    cards = W.api_chat_list(fresh_db.uid, TG)
    assert 'private' not in json.dumps(cards)


@pytest.mark.parametrize('raw,visible', [
    ('THOUGHT: secret MESSAGE: Visible text', 'Visible text'),
    ('DRAFT: secret MESSAGE: Visible text', 'Visible text'),
    ('THOUGHT: secret', ''),
])
def test_history_and_list_only_serve_visible_assistant_text(fresh_db, raw, visible):
    M.save_message(fresh_db.uid, CHAR, 'user', 'THOUGHT: user literal text')
    M.save_message(fresh_db.uid, CHAR, 'assistant', raw)
    history = W.api_chat_history(fresh_db.uid, CHAR)
    assert history[0]['content'] == 'THOUGHT: user literal text'
    assert history[1]['content'] == visible
    cards = W.api_chat_list(fresh_db.uid, TG)
    assert cards[0]['last_message'] == visible
    assert 'secret' not in json.dumps(history) + json.dumps(cards)


def test_separate_processes_dedupe_digest(fresh_db):
    import os
    import subprocess
    from concurrent.futures import ThreadPoolExecutor
    backlog(fresh_db)
    env = {k: v for k, v in os.environ.items() if not k.lower().endswith('_proxy')}
    env.update(DATABASE_URL=str(fresh_db.engine.url), MINIMAX_API_KEY='test-local-only',
               TELEGRAM_TOKEN='123456:test-only-token', PYTHON_DOTENV_DISABLED='1')
    script = ('from services.life_backlog import digest_on_open; '
              f'print(digest_on_open({fresh_db.uid}, {TG}, {CHAR!r}))')
    def run(_):
        return subprocess.run([sys.executable, '-c', script], env=env,
                              capture_output=True, text=True, timeout=40, check=True).stdout.strip()
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(run, range(3)))
    assert sum(result.isdigit() for result in results) == 1, results
    assert results.count('None') == 2
    assert len([row for row in lines(fresh_db) if row.origin == B.DIGEST_ORIGIN]) == 1


@pytest.mark.parametrize('ctype,ext', [('image/png', 'png'), ('image/webp', 'webp')])
def test_original_image_format_is_served_only_to_owner(fresh_db, ctype, ext):
    mid = S._to_app_chat(fresh_db.uid, TG, CHAR, 'Photo', (b'original bytes', ctype, 'photo'))
    assert mid
    row = W.api_chat_history(fresh_db.uid, CHAR)[0]
    filename = row['media_url'].rsplit('/', 1)[1]
    assert filename.endswith('.' + ext)
    assert W.chat_media_file_path(TG, filename).read_bytes() == b'original bytes'
    assert W.chat_media_file_path(TG + 1, filename) is None


@pytest.mark.parametrize('rail', ['life', 'proactive'])
@pytest.mark.parametrize('remaining', [0, 1])
def test_pool_denials_are_recorded_once_without_generating(fresh_db, monkeypatch, rail, remaining):
    from services import chat_photo_allowance as A, life_event_service as L
    from services import retention_features_service as R, silence_ladder as SL
    monkeypatch.setattr(A, 'frames_left', lambda uid: remaining)
    reserve = Mock(return_value=False)
    pick = Mock(return_value=(b'image', 'image/jpeg', 'photo'))
    monkeypatch.setattr(A, 'use_push_frame', reserve)
    monkeypatch.setattr(R, 'random_proactive_photo', pick)
    for _ in range(2):
        result = L._pool_photo(CHAR, fresh_db.uid) if rail == 'life' else SL._gift_frame(TG, CHAR)
        assert result is None
    if remaining == 0:
        reserve.assert_not_called()
        pick.assert_not_called()
    with fresh_db.sessions() as s:
        events = s.scalars(select(ProductEvent).where(ProductEvent.event_name == 'push_denied')).all()
        assert len(events) == 1
        assert json.loads(events[0].metadata_json) == {'rail': rail, 'reason': 'photo_cap'}


def test_digest_saved_and_deduped_even_if_notification_raises(fresh_db, monkeypatch):
    backlog(fresh_db, returned=True)
    monkeypatch.setattr(P, 'note', Mock(side_effect=RuntimeError('offline')))
    assert asyncio.run(B.maybe_digest(fake_bot(), fresh_db.uid, TG, CHAR)) is True
    assert asyncio.run(B.maybe_digest(fake_bot(), fresh_db.uid, TG, CHAR)) is True
    assert len([row for row in lines(fresh_db) if row.origin == B.DIGEST_ORIGIN]) == 1
    P.note.assert_called_once()


def test_denial_dedup_survives_restart_and_uses_local_day(fresh_db, monkeypatch):
    moment = datetime(2026, 11, 11, 22)
    monkeypatch.setattr(B, '_utcnow', lambda: moment)
    assert B.local_day('Europe/Moscow') == ('2026-11-12', datetime(2026, 11, 11, 21))
    # Persist an earlier-in-the-same-local-day event, including before UTC midnight.
    with fresh_db.sessions() as s:
        s.add(ProductEvent(user_id=fresh_db.uid, event_name='push_denied',
                           metadata_json=json.dumps({'rail': 'life', 'reason': 'night'}),
                           created_at=datetime(2026, 11, 11, 21, 30)))
        s.commit()
    for _ in range(3):
        B._denial_memo.clear()
        B.note_denial(fresh_db.uid, 'life', 'night', 'Europe/Moscow')
    with fresh_db.sessions() as s:
        assert s.scalar(select(func.count(ProductEvent.id))) == 1


def prepare_life(env, monkeypatch):
    from services import consent_service, life_event_service, live_situation_service
    monkeypatch.setattr(consent_service, 'has_accepted', lambda tg: True)
    monkeypatch.setattr(S, 'LIFE_EVENTS_ENABLED', True)
    monkeypatch.setattr(S, '_user_local_hour_simple', lambda tz: 12)
    monkeypatch.setattr(B, 'maybe_digest', AsyncMock(return_value=False))
    monkeypatch.setattr(life_event_service, 'silence_hours', lambda *args: 12)
    monkeypatch.setattr(S.random, 'random', lambda: 0)
    monkeypatch.setattr(S, '_life_events_store', {})
    live = AsyncMock(return_value=None)
    build = AsyncMock(return_value={'text': 'private event', 'photo': (b'owner image', 'image/jpeg', 'photo'),
                                   'options': [('More', f'life_reply:{CHAR}:more')]})
    monkeypatch.setattr(live_situation_service, 'push', live)
    monkeypatch.setattr(life_event_service, 'build_life_moment', build)
    return live, build


@pytest.mark.parametrize('reason', ['night', 'daily', 'unanswered'])
def test_life_denials_are_before_providers_and_do_not_scan_spam(fresh_db, monkeypatch, reason):
    live, build = prepare_life(fresh_db, monkeypatch)
    if reason == 'night':
        monkeypatch.setattr(S, '_user_local_hour_simple', lambda tz: 0)
    elif reason == 'daily':
        S._life_events_store[TG] = {'date': B.local_day('UTC')[0], 'slots': ['morning', 'day', 'evening']}
    else:
        monkeypatch.setattr(B, 'is_capped', lambda *args: True)
    bot = fake_bot()
    for _ in range(2):
        asyncio.run(S._life_events(bot))
    live.assert_not_called()
    build.assert_not_called()
    bot.send_message.assert_not_called()
    with fresh_db.sessions() as s:
        events = list(s.scalars(select(ProductEvent).where(ProductEvent.event_name == 'push_denied')))
        assert len(events) == 1 and json.loads(events[0].metadata_json) == {'rail': 'life', 'reason': reason}


@pytest.mark.parametrize('live_branch', [False, True])
def test_life_delivery_is_app_only_with_one_history_row(fresh_db, monkeypatch, live_branch):
    live, build = prepare_life(fresh_db, monkeypatch)
    if live_branch:
        async def persisted(*args, **kwargs):
            mid = M.save_message(fresh_db.uid, CHAR, 'assistant', 'private live event',
                                 image_prompt='paid scene', origin=B.LIFE_ORIGIN)
            return {'id': mid, 'text': 'private live event', 'price': 300}
        live.side_effect = persisted
    bot = fake_bot()
    asyncio.run(S._life_events(bot))
    assert len(lines(fresh_db)) == 1
    row = W.api_chat_history(fresh_db.uid, CHAR)[0]
    assert row['origin'] == 'life'
    if live_branch:
        build.assert_not_called()
        assert row['live']['paid'] is False
    else:
        assert row['actions'][0]['type'] == 'reply' and row['media_url']
    for method in (bot.send_message, bot.send_photo, bot.send_animation, bot.send_video):
        method.assert_not_called()
    assert (TG, 'life') in P._pending and P._pending[(TG, 'life')]['text'] == ''
    with fresh_db.sessions() as s:
        assert s.scalar(select(func.count(ProductEvent.id)).where(ProductEvent.event_name == 'life_event_sent')) == 1
        assert s.scalar(select(func.count(ProductEvent.id)).where(ProductEvent.event_name == 'life_event_shown')) == 1


def test_ritual_keeps_gate_and_persists_before_generic_ping(fresh_db, monkeypatch):
    from services import push_governor
    gate = Mock(return_value=(False, 'daily'))
    monkeypatch.setattr(push_governor, 'allow_push', gate)
    bot = fake_bot()
    assert not asyncio.run(S._ritual_line_push(bot, fresh_db.uid, TG, CHAR, 'morning', 'UTC'))
    assert lines(fresh_db) == []
    gate.return_value = (True, '')
    assert asyncio.run(S._ritual_line_push(bot, fresh_db.uid, TG, CHAR, 'morning', 'UTC'))
    gate.assert_called_with(fresh_db.uid, 'UTC', 'ritual')
    assert len(lines(fresh_db)) == 1 and TG in P._pending
    bot.send_message.assert_not_called()


@pytest.mark.parametrize('source', ['missing', 'download_failed', 'download', 'owner', 'denied', 'no_photo'])
def test_story_reserves_only_available_media_without_resizing(fresh_db, monkeypatch, tmp_path, source):
    from services import chat_photo_allowance, push_photos, story_hooks
    from dataclasses import replace
    story = replace(story_hooks.pick_unused(TG), photo_ok=source != 'no_photo')
    monkeypatch.setattr(story_hooks, 'pick_unused', lambda tg: story)
    monkeypatch.setattr(story_hooks, 'mark_used', Mock())
    owner = tmp_path / 'owner.png'
    owner.write_bytes(b'original owner bytes unchanged')
    monkeypatch.setattr(S, '_media_pick', lambda *args, **kwargs: owner if source in ('owner', 'no_photo') else None)
    monkeypatch.setattr(S, '_reference_photo', lambda *args: tmp_path / 'missing.png')
    monkeypatch.setattr(push_photos, 'pick', lambda cid: 'telegram-file' if source in ('download_failed', 'download', 'denied') else None)
    reserve = Mock(return_value=source != 'denied')
    monkeypatch.setattr(chat_photo_allowance, 'use_push_frame', reserve)
    bot = fake_bot()
    bot.download.return_value = io.BytesIO(b'original downloaded bytes')
    if source == 'download_failed':
        bot.download.side_effect = RuntimeError('file unavailable')
    assert asyncio.run(S._send_story(bot, fresh_db.uid, TG, CHAR))
    row = W.api_chat_history(fresh_db.uid, CHAR)[0]
    if source in ('missing', 'download_failed', 'no_photo'):
        reserve.assert_not_called()
        assert row['media_url'] is None
    else:
        reserve.assert_called_once_with(fresh_db.uid, CHAR)
        assert bool(row['media_url']) is (source != 'denied')
    if source == 'owner':
        path = W.chat_media_file_path(TG, row['media_url'].rsplit('/', 1)[1])
        assert path.suffix == '.png' and path.read_bytes() == owner.read_bytes()
    assert [action['choice'] for action in row['actions']] == ['a', 'b']
    bot.send_message.assert_not_called()
    bot.send_photo.assert_not_called()


@pytest.mark.parametrize('branch', ['topic', 'personal', 'ladder', 'marital'])
def test_proactive_persists_exactly_once_and_never_sends_content(fresh_db, monkeypatch, branch):
    hours = 72 if branch == 'personal' else 25
    with fresh_db.sessions() as s:
        s.get(User, fresh_db.uid).last_active_at = fresh_db.now - timedelta(hours=hours)
        s.commit()
    monkeypatch.setattr(S, 'PROACTIVE_MIN_HOURS', 48)
    monkeypatch.setattr(S, 'RETENTION_REMINDER_HOURS', 24)
    monkeypatch.setattr(S, 'PROACTIVE_MAX_INACTIVE_DAYS', 14)
    monkeypatch.setattr(S, '_push_ok', lambda *args: True)
    monkeypatch.setattr(S, '_send_story', AsyncMock(return_value=False))
    monkeypatch.setattr(S, '_marital_push', lambda *args: 'private marital' if branch == 'marital' else '')
    monkeypatch.setattr(S.silence_ladder, 'next_step', lambda *args: 2 if branch == 'ladder' else 1)
    monkeypatch.setattr(S.silence_ladder, 'compose', AsyncMock(return_value={'text': 'private ladder', 'chips': ['Continue']}))
    generated = AsyncMock(return_value='private generated')
    monkeypatch.setattr(S, 'proactive_reply', generated)
    bot = fake_bot()
    asyncio.run(S._proactive(bot))
    assert len(lines(fresh_db)) == 1
    assert lines(fresh_db)[0].origin == B.PUSH_ORIGIN
    if branch in ('personal', 'topic'):
        assert generated.call_args.kwargs['persist'] is False
    else:
        generated.assert_not_called()
    assert TG in P._pending and (TG, 'life') not in P._pending
    bot.send_message.assert_not_called()


def test_marketing_still_has_two_per_day_gate(fresh_db, monkeypatch):
    from services import push_governor as G
    monkeypatch.setattr(G, 'local_hour', lambda tz: 12)
    monkeypatch.setattr(G, 'PUSH_MAX_IN_WINDOW', 0)
    monkeypatch.setattr(G, 'PUSH_MAX_PER_DAY', 2)
    assert S._push_ok(fresh_db.uid, 'UTC')
    with fresh_db.sessions() as s:
        for _ in range(2):
            s.add(ProductEvent(user_id=fresh_db.uid, event_name='retention_push_sent'))
        s.commit()
    assert not S._push_ok(fresh_db.uid, 'UTC')


def test_day1_continuation_lands_only_in_app(fresh_db, monkeypatch):
    from services import chat_service, consent_service
    with fresh_db.sessions() as s:
        user = s.get(User, fresh_db.uid)
        user.created_at = fresh_db.now - timedelta(hours=30)
        user.last_active_at = fresh_db.now - timedelta(hours=24)
        s.commit()
    monkeypatch.setattr(S, 'PUBLIC_BASE_URL', 'https://example.test')
    monkeypatch.setattr(S, 'DAY1_HOOK_MAX_ACCOUNT_HOURS', 72)
    monkeypatch.setattr(S, 'DAY1_HOOK_MIN_INACTIVE_HOURS', 18)
    monkeypatch.setattr(S, '_push_ok', lambda *args: True)
    monkeypatch.setattr(consent_service, 'has_accepted', lambda tg: True)
    monkeypatch.setattr(chat_service, 'morning_callback', AsyncMock(return_value='private continuation'))
    bot = fake_bot()
    asyncio.run(S._day1_hook(bot))
    asyncio.run(S._day1_hook(bot))
    assert len(lines(fresh_db)) == 1
    assert TG in P._pending and (TG, 'life') not in P._pending
    bot.send_message.assert_not_called()
