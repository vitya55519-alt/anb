"""Engagement schema regressions; run with DATABASE_URL set to fresh test SQLite."""
from datetime import datetime, timedelta, timezone
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import MetaData, create_engine, event, inspect, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from models.app_models import Message, ProductEvent, User
from services import analytics_service, db, gamification_service as G, payments, series_reward as SR

NOW = datetime(2026, 11, 18, 14, 23, 45, 123456)
OLD = NOW - timedelta(days=9)
TG = 917001
VIEWS = {'life_event_log', 'push_denial_log'}


@pytest.fixture
def fresh_db(monkeypatch, caplog):
    # test_v31671_label_and_cards sets this logger to CRITICAL at collection.
    # caplog restores the previous level at teardown; assertions stay strict.
    caplog.set_level(logging.WARNING, logger=db.logger.name)
    engine = create_engine('sqlite:///:memory:')
    monkeypatch.setattr(db, 'engine', engine)
    yield engine
    engine.dispose()


def _schema(engine, legacy=False):
    users = User.__table__.to_metadata(MetaData())
    if legacy:
        users._columns.remove(users.c.streak_freeze_used_at)
    users.create(engine)
    ProductEvent.__table__.create(engine)
    return users


def _seed(engine, users):
    with engine.begin() as conn:
        conn.execute(users.insert(), [
            {'id': 1, 'telegram_id': '1', 'streak_freeze_week': '2026-W46'},
            {'id': 2, 'telegram_id': '2', 'streak_freeze_week': '2026-W47'},
            {'id': 3, 'telegram_id': '3', 'streak_freeze_week': None},
            {'id': 4, 'telegram_id': '4', 'streak_freeze_week': None},
        ])
        conn.execute(ProductEvent.__table__.insert(), [
            {'user_id': 1, 'event_name': 'streak_freeze', 'created_at': OLD},
            {'user_id': 1, 'event_name': 'streak_freeze', 'created_at': NOW},
            {'user_id': 1, 'event_name': 'series_reward', 'created_at': NOW + timedelta(days=1)},
            {'user_id': 3, 'event_name': 'streak_freeze', 'created_at': NOW},
            {'user_id': 4, 'event_name': 'streak_freeze', 'created_at': OLD},
        ])


def _snapshot(engine, table):
    with engine.connect() as conn:
        return conn.execute(text(f'SELECT * FROM {table} ORDER BY id')).all()


def _timestamps(engine):
    with engine.connect() as conn:
        return conn.execute(select(User.id, User.streak_freeze_used_at).order_by(User.id)).all()


def _marker_count(engine):
    with engine.connect() as conn:
        return conn.execute(text('SELECT COUNT(*) FROM app_migrations WHERE name = :n'),
                            {'n': db._ENGAGEMENT_LOG_MIGRATION}).scalar_one()


def test_fresh_startup_creates_named_views_and_nullable_timestamps(fresh_db):
    db.init_db()
    db.init_db()
    assert set(inspect(fresh_db).get_view_names()) == VIEWS
    columns = {c['name']: c for c in inspect(fresh_db).get_columns('users')}
    assert columns['streak_freeze_used_at']['nullable']
    assert columns['opening_shown_at']['nullable']
    assert _marker_count(fresh_db) == 1
    assert _snapshot(fresh_db, 'product_events') == []


def test_legacy_forward_reverse_forward_preserves_history(fresh_db, caplog):
    users = _schema(fresh_db, legacy=True)
    _seed(fresh_db, users)
    events = _snapshot(fresh_db, 'product_events')
    assert db._auto_migrate_all_tables() == {'users': ['streak_freeze_used_at']}
    assert db._auto_migrate_all_tables() == {}
    with fresh_db.begin() as conn:
        conn.execute(User.__table__.update().where(User.id == 3).values(streak_freeze_used_at=OLD))
    db._migrate_engagement_logs()
    db._migrate_engagement_logs()
    expected = [(1, NOW), (2, None), (3, OLD), (4, OLD)]
    assert _timestamps(fresh_db) == expected
    assert _marker_count(fresh_db) == 1
    assert caplog.text.count('engagement logs applied:') == 1
    assert 'users rows=4 product_events rows=5' in caplog.text
    assert 'freeze timestamps backfilled=2' in caplog.text
    assert 'auto schema users: +streak_freeze_used_at (rows=4)' in caplog.text
    with fresh_db.connect() as conn:
        assert conn.execute(select(User.streak_freeze_week).where(User.id == 2)).scalar_one() == '2026-W47'
        assert conn.execute(text("SELECT COUNT(*) FROM app_migrations WHERE name = "
                                 "'schema:users:streak_freeze_used_at'")).scalar_one() == 1
    db.reverse_engagement_logs_migration()
    db.reverse_engagement_logs_migration()
    assert inspect(fresh_db).get_view_names() == []
    assert _marker_count(fresh_db) == 0
    assert _timestamps(fresh_db) == expected
    assert _snapshot(fresh_db, 'product_events') == events
    assert 'engagement logs reversed: users rows=4 product_events rows=5 retained' in caplog.text
    db._migrate_engagement_logs()
    assert _marker_count(fresh_db) == 1
    assert set(inspect(fresh_db).get_view_names()) == VIEWS
    assert _timestamps(fresh_db) == expected
    assert _snapshot(fresh_db, 'product_events') == events
    assert db._auto_migrate_all_tables() == {}


def test_views_read_existing_and_future_canonical_rows(fresh_db, caplog):
    _schema(fresh_db)
    names = ['life_event_sent', 'life_event_shown', 'life_event_replied', 'push_denied',
             'push_sent', 'life_event_sent_extra', 'streak_freeze', 'chat_user_message']
    metadata = '{"rail": "life", "reason": "night"}'

    def insert_batch():
        with fresh_db.begin() as conn:
            conn.execute(ProductEvent.__table__.insert(), [
                {'user_id': 7, 'character_id': 'anna_01', 'event_name': name, 'value': 2.5,
                 'metadata_json': metadata, 'created_at': NOW} for name in names
            ])

    insert_batch()
    before = _snapshot(fresh_db, 'product_events')
    db._migrate_engagement_logs()
    assert _snapshot(fresh_db, 'product_events') == before
    assert 'life_event_log rows=3 push_denial_log rows=1' in caplog.text
    for batch in (1, 2):
        if batch == 2:
            insert_batch()  # No migration rerun or duplicate log write is needed.
        all_events = _snapshot(fresh_db, 'product_events')
        assert len(all_events) == len(names) * batch
        for view, allowed in [('life_event_log', set(names[:3])), ('push_denial_log', {'push_denied'})]:
            rows = _snapshot(fresh_db, view)
            assert rows == [r for r in all_events if r.event_name in allowed]
            assert set(rows[0]._mapping) == set(ProductEvent.__table__.columns.keys())
            assert all(r.metadata_json == metadata for r in rows)
    db.reverse_engagement_logs_migration()
    db._migrate_engagement_logs()
    assert _snapshot(fresh_db, 'product_events') == all_events
    assert len(_snapshot(fresh_db, 'life_event_log')) == 6
    assert len(_snapshot(fresh_db, 'push_denial_log')) == 2


@pytest.mark.parametrize('ledger_reset', ['table', 'marker'])
@pytest.mark.parametrize('kept_views', [VIEWS, {'life_event_log'}, {'push_denial_log'}],
                         ids=['both-views', 'life-only', 'denial-only'])
def test_missing_ledger_repairs_only_missing_views_and_preserves_history(
        fresh_db, caplog, ledger_reset, kept_views):
    users = _schema(fresh_db)
    _seed(fresh_db, users)
    with fresh_db.begin() as conn:
        conn.execute(ProductEvent.__table__.insert(), [
            {'user_id': 1, 'event_name': name, 'created_at': NOW}
            for name in ('life_event_sent', 'life_event_shown', 'life_event_replied', 'push_denied')
        ])
    db._migrate_engagement_logs()
    with fresh_db.begin() as conn:
        # test_v3650_peach_scale.test_rescale_runs_once drops the entire ledger,
        # not the views. Also cover losing just this migration's marker.
        if ledger_reset == 'table':
            conn.execute(text('DROP TABLE app_migrations'))
        else:
            conn.execute(text('DELETE FROM app_migrations WHERE name = :n'),
                         {'n': db._ENGAGEMENT_LOG_MIGRATION})
        for view in VIEWS - kept_views:
            conn.execute(text(f'DROP VIEW {view}'))
        conn.execute(users.update().where(users.c.id == 1).values(streak_freeze_used_at=None))
        conn.execute(users.update().where(users.c.id == 3).values(streak_freeze_used_at=OLD))
    definitions = {view: inspect(fresh_db).get_view_definition(view) for view in kept_views}
    events = _snapshot(fresh_db, 'product_events')
    ddl = []

    def record_view_ddl(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith(('CREATE VIEW', 'DROP VIEW')):
            ddl.append(statement.split()[:3])

    caplog.clear()
    event.listen(fresh_db, 'before_cursor_execute', record_view_ddl)
    try:
        db._migrate_engagement_logs()
        assert _timestamps(fresh_db) == [(1, NOW), (2, None), (3, OLD), (4, OLD)]
        rows = _snapshot(fresh_db, 'users')
        db._migrate_engagement_logs()
        assert _snapshot(fresh_db, 'users') == rows
    finally:
        event.remove(fresh_db, 'before_cursor_execute', record_view_ddl)
    assert sorted(ddl) == [['CREATE', 'VIEW', view] for view in sorted(VIEWS - kept_views)]
    assert set(inspect(fresh_db).get_view_names()) == VIEWS
    assert {view: inspect(fresh_db).get_view_definition(view) for view in kept_views} == definitions
    assert _marker_count(fresh_db) == 1
    assert _snapshot(fresh_db, 'product_events') == events
    assert _snapshot(fresh_db, 'life_event_log') == [r for r in events if r.event_name.startswith('life_event_')]
    assert _snapshot(fresh_db, 'push_denial_log') == [r for r in events if r.event_name == 'push_denied']
    assert caplog.text.count('engagement logs applied:') == 1
    assert 'freeze timestamps backfilled=1' in caplog.text


@pytest.mark.parametrize('table', sorted(VIEWS))
def test_named_table_conflict_fails_without_overwriting_or_marking_applied(fresh_db, table):
    users = _schema(fresh_db)
    _seed(fresh_db, users)
    with fresh_db.begin() as conn:
        conn.execute(text(f'CREATE TABLE {table} (id INTEGER PRIMARY KEY, payload TEXT)'))
        conn.execute(text(f"INSERT INTO {table} (id, payload) VALUES (1, 'retain this row')"))
    events = _snapshot(fresh_db, 'product_events')
    user_rows = _snapshot(fresh_db, 'users')
    table_rows = _snapshot(fresh_db, table)
    for _ in range(2):
        with pytest.raises(OperationalError, match='already exists'):
            db._migrate_engagement_logs()
        assert inspect(fresh_db).get_view_names() == []
        assert 'app_migrations' not in inspect(fresh_db).get_table_names()
        assert _snapshot(fresh_db, table) == table_rows
        assert _snapshot(fresh_db, 'users') == user_rows
        assert _snapshot(fresh_db, 'product_events') == events


@pytest.mark.parametrize('existing_view', [None, 'life_event_log', 'push_denial_log'])
def test_failed_forward_rolls_back_views_backfill_and_ledger(fresh_db, monkeypatch, existing_view):
    users = _schema(fresh_db)
    _seed(fresh_db, users)
    if existing_view:
        db._migrate_engagement_logs()
        with fresh_db.begin() as conn:
            conn.execute(text('DROP TABLE app_migrations'))
            for view in VIEWS - {existing_view}:
                conn.execute(text(f'DROP VIEW {view}'))
            conn.execute(users.update().values(streak_freeze_used_at=None))
    definitions = {view: inspect(fresh_db).get_view_definition(view)
                   for view in inspect(fresh_db).get_view_names()}
    before = _snapshot(fresh_db, 'product_events')
    rows_in = db._rows_in

    def fail_after_backfill(conn, table):
        if table == 'life_event_log':
            raise RuntimeError('injected after backfill')
        return rows_in(conn, table)

    with monkeypatch.context() as patch:
        patch.setattr(db, '_rows_in', fail_after_backfill)
        with pytest.raises(RuntimeError, match='injected'):
            db._migrate_engagement_logs()
    assert {view: inspect(fresh_db).get_view_definition(view)
            for view in inspect(fresh_db).get_view_names()} == definitions
    assert 'app_migrations' not in inspect(fresh_db).get_table_names()
    assert _timestamps(fresh_db) == [(1, None), (2, None), (3, None), (4, None)]
    assert _snapshot(fresh_db, 'product_events') == before
    db._migrate_engagement_logs()
    assert set(inspect(fresh_db).get_view_names()) == VIEWS
    assert _marker_count(fresh_db) == 1
    assert _timestamps(fresh_db) == [(1, NOW), (2, None), (3, NOW), (4, OLD)]


def test_failed_reverse_restores_views_and_marker(fresh_db):
    users = _schema(fresh_db)
    _seed(fresh_db, users)
    db._migrate_engagement_logs()
    before = _snapshot(fresh_db, 'product_events')
    timestamps = _timestamps(fresh_db)

    def fail_delete(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith('DELETE FROM app_migrations'):
            raise RuntimeError('injected after DROP VIEW')

    event.listen(fresh_db, 'before_cursor_execute', fail_delete)
    try:
        with pytest.raises(RuntimeError, match='injected'):
            db.reverse_engagement_logs_migration()
    finally:
        event.remove(fresh_db, 'before_cursor_execute', fail_delete)
    assert set(inspect(fresh_db).get_view_names()) == VIEWS
    assert _marker_count(fresh_db) == 1
    assert _timestamps(fresh_db) == timestamps
    assert _snapshot(fresh_db, 'product_events') == before
    db.reverse_engagement_logs_migration()
    assert inspect(fresh_db).get_view_names() == []


@pytest.mark.parametrize('repair', ['auto', 'explicit'])
def test_failed_column_repair_is_transactional_on_legacy_sqlite(fresh_db, monkeypatch, repair):
    _schema(fresh_db, legacy=True)
    mark = db._mark_applied

    def fail_after_marker(conn, name):
        mark(conn, name)
        raise RuntimeError('injected after ALTER TABLE')

    with monkeypatch.context() as patch:
        patch.setattr(db, '_mark_applied', fail_after_marker)
        with pytest.raises(RuntimeError, match='injected'):
            if repair == 'auto':
                db._auto_migrate_all_tables()
            else:
                db._add_missing_columns('users', {'streak_freeze_used_at': 'TIMESTAMP'})
    assert 'streak_freeze_used_at' not in {c['name'] for c in inspect(fresh_db).get_columns('users')}
    assert 'app_migrations' not in inspect(fresh_db).get_table_names()
    assert db._auto_migrate_all_tables() == {'users': ['streak_freeze_used_at']}


@pytest.fixture
def writers(fresh_db, monkeypatch):
    _schema(fresh_db)
    Message.__table__.create(fresh_db)
    sessions = sessionmaker(bind=fresh_db, expire_on_commit=False)
    for module in (db, SR, G):
        monkeypatch.setattr(module, 'SessionLocal', sessions)

    def get_user(tid):
        with sessions() as session:
            return session.scalar(select(User).where(User.telegram_id == str(tid)))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.replace(tzinfo=timezone.utc).astimezone(tz) if tz else NOW

    monkeypatch.setattr(G, 'get_user', get_user)
    monkeypatch.setattr(G, '_today', lambda: NOW)
    monkeypatch.setattr(SR, 'datetime', Clock)
    monkeypatch.setattr(SR, 'SERIES_REWARD_ENABLED', True)
    for module in (SR, G):
        monkeypatch.setattr(module, 'SERIES_FREEZE_PER_WEEK', 1)
    monkeypatch.setattr(G, 'unlock_achievement', Mock())
    grant, track = Mock(return_value=0), Mock()
    monkeypatch.setattr(payments, 'grant_photo_credits', grant)
    monkeypatch.setattr(analytics_service, 'track_event', track)
    monkeypatch.setattr(SR, '_pending', {})
    return SimpleNamespace(sessions=sessions, grant=grant, track=track, row=lambda: get_user(TG))


def _writer_user(env, days=2, week=None, stamp=None, streak=2, messages=None):
    with env.sessions() as session:
        user = User(telegram_id=str(TG), streak_count=streak,
                    streak_last_date=None if days is None else NOW - timedelta(days=days),
                    streak_freeze_week=week, streak_freeze_used_at=stamp)
        session.add(user)
        session.flush()
        uid = user.id
        for _ in range(SR.SERIES_REWARD_MIN_MESSAGES if messages is None else messages):
            session.add(Message(user_id=uid, character_id='anna_01', role='user',
                                content='test', created_at=NOW))
        session.commit()
    return uid


def _write(path, uid):
    return SR.note_his_message(TG, uid) if path == 'series' else G.touch_activity(TG)


@pytest.mark.parametrize('path', ['series', 'activity'])
@pytest.mark.parametrize('previous_stamp', [None, OLD])
def test_both_writers_stamp_actual_utc_once_only_when_freeze_consumed(writers, path, previous_stamp):
    uid = _writer_user(writers, stamp=previous_stamp)
    assert _write(path, uid)
    row = writers.row()
    assert row.streak_freeze_used_at == NOW
    assert row.streak_freeze_used_at.tzinfo is None
    assert row.streak_freeze_week == SR._week_key(NOW.date().isoformat())
    assert row.streak_count == 3
    # Repeated activity and the other writer must not consume the same freeze again.
    _write(path, uid)
    _write('activity' if path == 'series' else 'series', uid)
    assert writers.row().streak_freeze_used_at == NOW
    assert writers.row().streak_count == 3
    freezes = [c for c in writers.track.call_args_list if c.args[1] == 'streak_freeze']
    assert len(freezes) == 1


@pytest.mark.parametrize('path', ['series', 'activity'])
@pytest.mark.parametrize('days,week,stamp,streak,enabled,expected', [
    (0, None, OLD, 2, 1, 2),
    (1, None, None, 2, 1, 3),
    (3, None, OLD, 2, 1, 1),
    (2, '2026-W47', OLD, 2, 1, 1),
    (2, '2026-W47', None, 2, 1, 1),
    (2, None, None, 2, 0, 1),
    (None, None, None, 0, 1, 1),
    (2, None, OLD, 0, 1, 1),
])
def test_non_consuming_paths_do_not_stamp_or_erase_time(
        writers, monkeypatch, path, days, week, stamp, streak, enabled, expected):
    for module in (SR, G):
        monkeypatch.setattr(module, 'SERIES_FREEZE_PER_WEEK', enabled)
    uid = _writer_user(writers, days=days, week=week, stamp=stamp, streak=streak)
    assert _write(path, uid)
    row = writers.row()
    assert row.streak_freeze_used_at == stamp
    assert row.streak_freeze_week == week
    assert row.streak_count == expected
    assert not [c for c in writers.track.call_args_list if c.args[1] == 'streak_freeze']


@pytest.mark.parametrize('enabled,messages', [(True, 4), (False, 5)])
def test_series_does_not_stamp_before_reward_eligibility(writers, monkeypatch, enabled, messages):
    monkeypatch.setattr(SR, 'SERIES_REWARD_ENABLED', enabled)
    uid = _writer_user(writers, messages=messages)
    assert SR.note_his_message(TG, uid) is None
    assert writers.row().streak_freeze_used_at is None
    assert writers.row().streak_freeze_week is None
    writers.grant.assert_not_called()
    writers.track.assert_not_called()


@pytest.mark.parametrize('path', ['series', 'activity'])
def test_freeze_timestamp_and_week_roll_back_with_existing_writer_transaction(writers, path):
    uid = _writer_user(writers, stamp=OLD)

    def fail_commit(session):
        raise RuntimeError('injected commit failure')

    event.listen(writers.sessions, 'before_commit', fail_commit)
    try:
        if path == 'series':
            assert _write(path, uid) is None  # Existing error-handling contract.
        else:
            with pytest.raises(RuntimeError, match='injected'):
                _write(path, uid)
    finally:
        event.remove(writers.sessions, 'before_commit', fail_commit)
    row = writers.row()
    assert row.streak_freeze_used_at == OLD
    assert row.streak_freeze_week is None
    assert row.streak_count == 2
    writers.track.assert_not_called()
    writers.grant.assert_not_called()
