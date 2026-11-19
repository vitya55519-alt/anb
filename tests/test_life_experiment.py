"""Synthetic SQLite-only coverage of the bounded life experiment backend."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import threading

import pytest
from sqlalchemy import create_engine, event as sa_event, func, select
from sqlalchemy.orm import sessionmaker

from models.app_models import (
    CommunicationProfile, LifeEvent, LifeEventReply, LifeExperiment,
    LifeExperimentIssue, LifeParticipant, Memory, Message, User,
)
from services import life_experiment as life

T0 = datetime(2026, 11, 1, 12)
DAY = timedelta(days=1)
LIFE_TABLES = (LifeExperiment, LifeParticipant, LifeEvent,
               LifeEventReply, LifeExperimentIssue)
TABLES = (User, Message, Memory, CommunicationProfile) + LIFE_TABLES


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + (tmp_path / 'synthetic-life.db').as_posix(),
                           connect_args={'check_same_thread': False, 'timeout': 30})
    for model in TABLES:
        model.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(life, 'SessionLocal', factory)
    monkeypatch.setattr(life, 'ENABLED', True)
    with factory.begin() as session:
        session.add_all(User(id=uid, telegram_id=f'synthetic-{uid}') for uid in range(1, 17))
    yield factory
    engine.dispose()


def context(uid=1, *, mode=False, now=T0):
    return {**life.assignment(uid, now=now), 'mode_on': mode}


def delivery(db, *, uid=1, cid='anna', at=T0, ctx=None, **kwargs):
    with db.begin() as session:
        message = Message(user_id=uid, character_id=cid, role='assistant',
                          content='synthetic life source', origin='life', created_at=at, **kwargs)
        session.add(message)
        session.flush()
        result = life.record_delivery(session, message, ctx)
        session.flush()
        return result


def reply(db, *, uid=1, cid='anna', at=None, **kwargs):
    values = dict(user_id=uid, character_id=cid, role='user', content='synthetic input',
                  origin='user_input', created_at=at or T0 + timedelta(minutes=1))
    values.update(kwargs)
    with db.begin() as session:
        message = Message(**values)
        session.add(message)
        session.flush()
        result = life.record_reply(session, message)
        return result, message.id


def row(db, model, identity):
    with db() as session:
        return session.get(model, identity)


def participant(db, uid=1):
    with db() as session:
        return session.scalar(select(LifeParticipant).where(LifeParticipant.user_id == uid))


def count(db, model):
    with db() as session:
        return session.scalar(select(func.count()).select_from(model))


def treatment_context(db, *, mode=False):
    for uid in range(1, 17):
        ctx = context(uid, mode=mode)
        if ctx['variant'] == 'treatment':
            return uid, ctx
    raise AssertionError('Expected both deterministic arms')


def test_schema_has_no_chat_copies_or_message_foreign_keys(db):
    expected = {'key', 'started_at', 'status', 'stopped_at', 'stop_reason', 'review_sent_at'}
    assert set(LifeExperiment.__table__.columns.keys()) == expected
    for model in LIFE_TABLES:
        assert not {'content', 'text', 'prompt', 'image_prompt', 'metadata_json'} & set(model.__table__.columns.keys())
        assert not model.__table__.foreign_keys
    assert LifeEvent.__table__.c.reply_count.default.arg == 0
    assert LifeEvent.__table__.c.scene_status.default.arg == 'pending'
    assert LifeEventReply.__table__.c.message_id.primary_key


def test_report_is_read_only_and_does_not_start_run(db):
    statements = []
    engine = db.kw['bind']
    listener = lambda conn, cursor, statement, parameters, ctx, many: statements.append(statement)
    sa_event.listen(engine, 'before_cursor_execute', listener)
    try:
        data = life.collect_report(now=T0)
    finally:
        sa_event.remove(engine, 'before_cursor_execute', listener)
    assert all(sql.lstrip().upper().startswith('SELECT') for sql in statements)
    assert data['status'] == 'not_started'
    assert data['outcome'] == 'inconclusive'
    assert data['started_at'] is None
    assert count(db, LifeExperiment) == count(db, LifeParticipant) == 0
    assert 'не начат' in life.render_report(data)


def test_stable_sha_split_survives_restart_heroine_and_mode_switches(db, monkeypatch):
    with db.begin() as session:
        session.add_all(User(id=uid, telegram_id=f'synthetic-{uid}') for uid in range(17, 201))
    assigned = {uid: life.assignment(uid, now=T0) for uid in range(1, 201)}
    treatment = sum(value['variant'] == 'treatment' for value in assigned.values())
    assert 75 <= treatment <= 125
    for uid, value in assigned.items():
        parity = int(hashlib.sha256(f'{life.EXPERIMENT_KEY}:{uid}'.encode()).hexdigest(), 16) % 2
        assert value == {'experiment_key': life.EXPERIMENT_KEY, 'variant': ('control', 'treatment')[parity]}
    importlib.reload(life)
    monkeypatch.setattr(life, 'SessionLocal', db)
    monkeypatch.setattr(life, 'ENABLED', True)
    for uid in (1, 2, 3, 4):
        with db.begin() as session:
            user = session.get(User, uid)
            user.spicy_mode, user.selected_character = True, 'other'
        assert life.assignment(uid, now=T0 + DAY) == assigned[uid]
    assert row(db, LifeExperiment, life.EXPERIMENT_KEY).started_at == T0
    assert count(db, LifeParticipant) == 200


def test_assignment_bounds_disabled_missing_user_and_no_reassignment(db, monkeypatch):
    monkeypatch.setattr(life, 'ENABLED', False)
    assert life.assignment(1, now=T0)['variant'] == 'outside'
    assert count(db, LifeExperiment) == 0
    monkeypatch.setattr(life, 'ENABLED', True)
    assert life.assignment(999, now=T0)['variant'] == 'outside'
    assert count(db, LifeExperiment) == 0
    assigned = life.assignment(1, now=T0)
    assert life.assignment(2, now=T0 + 14 * DAY - timedelta(microseconds=1))['variant'] in life.ARMS
    for uid in (1, 3):
        assert life.assignment(uid, now=T0 + 14 * DAY) == {'experiment_key': None, 'variant': 'outside'}
    assert participant(db, 3) is None
    assert participant(db, 1).variant == assigned['variant']
    data = life.collect_report(now=T0 + 15 * DAY)
    assert sum(a['assigned'] for a in data['arms'].values()) == 2
    assert sum(a['missing_deliveries'] for a in data['arms'].values()) == 2
    assert sum(a['recipients'] for a in data['arms'].values()) == 0


def test_run_insert_collision_keeps_existing_start_and_outer_transaction(db, monkeypatch):
    life.assignment(1, now=T0)
    real_lock = life._lock_run
    calls = 0

    def competing_insert(session, key=life.EXPERIMENT_KEY):
        nonlocal calls
        calls += 1
        return None if calls == 1 else real_lock(session, key)

    monkeypatch.setattr(life, '_lock_run', competing_insert)
    assert life.assignment(2, now=T0 + DAY)['variant'] in life.ARMS
    assert calls == 2
    assert row(db, LifeExperiment, life.EXPERIMENT_KEY).started_at == T0
    assert participant(db, 2) is not None


def test_nested_run_creation_rolls_back_with_outer_transaction(db):
    with db() as session:
        life._lock_user(session, 1)
        life._ensure_run(session, T0)
        session.rollback()
    assert count(db, LifeExperiment) == 0


def test_concurrent_first_assignment_same_and_different_users(db):
    barrier = threading.Barrier(8)

    def assign(index):
        barrier.wait(timeout=15)
        uid = 1 if index < 4 else index
        return uid, life.assignment(uid, now=T0)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(assign, range(8)))
    assert count(db, LifeExperiment) == 1
    assert count(db, LifeParticipant) == 5
    assert len({r['variant'] for uid, r in results if uid == 1}) == 1


@pytest.mark.parametrize('mode', [False, True])
def test_first_delivery_anchors_mode_and_event_not_assignment(db, mode):
    ctx = context(mode=mode)
    assert participant(db).first_event_id is None
    first = delivery(db, at=T0 + timedelta(hours=3), ctx=ctx)
    assert first.delivered_at == T0 + timedelta(hours=3)
    delivery(db, cid='other', at=T0 + timedelta(hours=4), ctx={**ctx, 'mode_on': not mode})
    p = participant(db)
    assert p.first_event_id == first.id and p.first_mode is mode
    assert p.assigned_at == T0


def test_only_explicit_context_enrolls_and_live_photo_is_always_outside(db):
    ctx = context()
    ordinary = delivery(db)
    photo = delivery(db, ctx=ctx, image_prompt='synthetic image description')
    explicit_photo = delivery(db, ctx={**ctx, 'kind': 'live_photo'})
    foreign = delivery(db, ctx={**ctx, 'experiment_key': 'other'})
    unassigned = delivery(db, uid=2, ctx=ctx)
    for e in (ordinary, photo, explicit_photo, foreign, unassigned):
        assert e.variant == 'outside' and e.experiment_key is None
    assert ordinary.kind == 'moment'
    assert photo.kind == explicit_photo.kind == 'live_photo'
    assert participant(db).first_event_id is None
    assert participant(db, 2) is None


@pytest.mark.parametrize('origin,role', [('digest', 'assistant'), ('push', 'assistant'),
                                        (None, 'assistant'), ('life', 'user')])
def test_non_life_assistant_delivery_is_ignored(db, origin, role):
    ctx = context()
    with db.begin() as session:
        message = Message(user_id=1, character_id='anna', role=role,
                          content='synthetic', origin=origin, created_at=T0)
        session.add(message)
        session.flush()
        assert life.record_delivery(session, message, ctx) is None
    assert count(db, LifeEvent) == 0


def test_delivery_and_reply_rollback_with_message_transaction(db):
    ctx = context()
    with db() as session:
        source = Message(user_id=1, character_id='anna', role='assistant',
                         content='synthetic', origin='life', created_at=T0)
        session.add(source)
        session.flush()
        event = life.record_delivery(session, source, ctx)
        incoming = Message(user_id=1, character_id='anna', role='user',
                           content='synthetic', origin='user_input', created_at=T0)
        session.add(incoming)
        session.flush()
        assert life.record_reply(session, incoming) == event.id
        session.rollback()
    assert count(db, Message) == count(db, LifeEvent) == count(db, LifeEventReply) == 0
    assert participant(db).first_event_id is None


def test_delivery_idempotence_and_message_deletion_compatibility(db):
    ctx = context()
    first = delivery(db, ctx=ctx)
    second = delivery(db, at=T0 + timedelta(minutes=1), ctx=ctx)
    with db.begin() as session:
        source = session.get(Message, first.message_id)
        assert life.record_delivery(session, source, ctx).id == first.id
        session.delete(source)
    assert count(db, LifeEvent) == 2
    assert row(db, LifeEvent, second.id).closed_reason != 'superseded'


@pytest.mark.parametrize('replacement', ['moment', 'live_photo'])
def test_new_life_supersedes_pending_active_paused_same_pair_only(db, replacement):
    uid, ctx = treatment_context(db)
    first = delivery(db, uid=uid, ctx=ctx)
    other = delivery(db, uid=uid, cid='other', ctx=ctx)
    with db.begin() as session:
        session.get(LifeEvent, first.id).scene_status = 'paused'
    fresh = delivery(db, uid=uid, at=T0 + timedelta(minutes=1), ctx=ctx,
                     image_prompt='synthetic' if replacement == 'live_photo' else None)
    old = row(db, LifeEvent, first.id)
    assert (old.scene_status, old.closed_reason) == ('closed', 'superseded')
    assert row(db, LifeEvent, other.id).scene_status == 'pending'
    with db.begin() as session:
        assert life.record_delivery(session, session.get(Message, first.message_id), ctx).id == first.id
    assert row(db, LifeEvent, fresh.id).closed_reason != 'superseded'
    # A late, older source can be recorded, but must not revive its scene.
    stale = delivery(db, uid=uid, at=T0 - timedelta(minutes=1), ctx=ctx)
    assert (stale.scene_status, stale.closed_reason) == ('closed', 'superseded')


def test_stop_in_flight_preserves_generated_variant_and_disables_cached_scene(db):
    uid, ctx = treatment_context(db)
    first = delivery(db, uid=uid, ctx=ctx)
    with db() as session:
        cached_run = session.get(LifeExperiment, life.EXPERIMENT_KEY)
        assert life.scene_enabled(session, first)
        assert not session.dirty
        life.stop(now=T0 + DAY)
        assert cached_run.status == 'running'
        assert not life.scene_enabled(session, first)
        assert not session.dirty
    late = delivery(db, uid=uid, at=T0 + DAY, ctx=ctx)
    assert late.variant == 'treatment' and late.experiment_key == life.EXPERIMENT_KEY
    assert late.scene_status == 'closed'
    assert life.assignment(uid, now=T0 + DAY)['variant'] == 'outside'
    original = row(db, LifeExperiment, life.EXPERIMENT_KEY)
    life.stop('another_reason', now=T0 + 2 * DAY)
    again = row(db, LifeExperiment, life.EXPERIMENT_KEY)
    assert (again.stopped_at, again.stop_reason) == (original.stopped_at, 'manual')
    assert life.collect_report(now=T0 + 30 * DAY)['outcome'] == 'stopped'


def test_stop_before_enrollment_is_durable_without_fake_start(db):
    life.stop(now=T0)
    assert life.assignment(1, now=T0 + DAY)['variant'] == 'outside'
    assert row(db, LifeExperiment, life.EXPERIMENT_KEY).started_at is None
    assert count(db, LifeParticipant) == 0


def test_scene_allowed_after_enrollment_and_disabled_without_mutation(db, monkeypatch):
    uid, ctx = treatment_context(db)
    first = delivery(db, uid=uid, ctx=ctx)
    assert life.assignment(uid, now=T0 + 20 * DAY)['variant'] == 'outside'
    with db() as session:
        assert life.scene_enabled(session, first)
        monkeypatch.setattr(life, 'ENABLED', False)
        assert not life.scene_enabled(session, first)
        assert not session.dirty
    late = delivery(db, uid=uid, at=T0 + DAY, ctx=ctx)
    assert late.variant == 'treatment' and late.scene_status == 'closed'


@pytest.mark.parametrize('mode', [False, True])
def test_first_reply_included_three_reply_engagement_and_no_false_open(db, mode):
    first = delivery(db, ctx=context(mode=mode))
    for number in range(1, 5):
        result, message_id = reply(db, at=T0 + timedelta(minutes=number))
        assert result == first.id
        with db.begin() as session:
            assert life.record_reply(session, session.get(Message, message_id)) == first.id
        saved = row(db, LifeEvent, first.id)
        assert saved.reply_count == number
        assert saved.opened_at is None
        assert saved.first_reply_at == T0 + timedelta(minutes=1)
        assert saved.engaged_at == (T0 + timedelta(minutes=3) if number >= 3 else None)
    assert count(db, LifeEventReply) == 4


def test_reply_chooses_latest_event_and_isolates_users_and_heroines(db):
    ctx = context()
    first = delivery(db, ctx=ctx)
    newer = delivery(db, at=T0 + timedelta(minutes=1), ctx=ctx)
    other = delivery(db, cid='other', ctx=ctx)
    assert reply(db, at=T0 + timedelta(minutes=2))[0] == newer.id
    assert reply(db, cid='other')[0] == other.id
    assert reply(db, uid=2)[0] is None
    assert reply(db, cid='unknown')[0] is None
    assert row(db, LifeEvent, first.id).reply_count == 0
    outside = delivery(db, at=T0 + timedelta(minutes=3), image_prompt='synthetic')
    assert reply(db, at=T0 + timedelta(minutes=4))[0] == outside.id
    assert row(db, LifeEvent, newer.id).reply_count == 1


def test_equal_delivery_timestamps_use_message_id_and_reject_pre_source_message(db):
    older_reply_id = reply(db, at=T0 + timedelta(minutes=1))[1]
    first = delivery(db, at=T0)
    second = delivery(db, at=T0)
    assert reply(db, at=T0)[0] == second.id
    with db.begin() as session:
        assert life.record_reply(session, session.get(Message, older_reply_id)) is None
    assert row(db, LifeEvent, first.id).reply_count == 0


@pytest.mark.parametrize('offset,attributed', [
    (timedelta(microseconds=-1), False), (timedelta(0), True),
    (DAY - timedelta(microseconds=1), True), (DAY, False),
    (DAY + timedelta(microseconds=1), False),
])
def test_strict_reply_24h_boundary(db, offset, attributed):
    first = delivery(db, ctx=context())
    assert (reply(db, at=T0 + offset)[0] == first.id) is attributed
    assert row(db, LifeEvent, first.id).opened_at is None


@pytest.mark.parametrize('changes', [
    {'origin': None}, {'origin': 'purchase'}, {'origin': 'system'},
    {'role': 'system'}, {'role': 'assistant'}, {'content': '  \n '},
    {'media_kind': 'photo'}, {'media_kind': 'video'}, {'media_kind': 'circle'},
    {'media_url': 'synthetic://media'}, {'image_prompt': 'synthetic'},
])
def test_only_accepted_real_text_or_transcribed_voice_is_reply(db, changes):
    first = delivery(db, ctx=context())
    assert reply(db, **changes)[0] is None
    assert row(db, LifeEvent, first.id).reply_count == 0
    assert participant(db).returned_at is None
    assert count(db, LifeEventReply) == 0


def test_voice_transcript_counts_and_delayed_input_engagement_timestamp(db):
    first = delivery(db, ctx=context())
    for minute in (4, 3, 2, 1):
        assert reply(db, at=T0 + timedelta(minutes=minute), media_kind='voice',
                     media_url='synthetic://voice')[0] == first.id
    saved = row(db, LifeEvent, first.id)
    assert saved.first_reply_at == T0 + timedelta(minutes=1)
    assert saved.engaged_at == T0 + timedelta(minutes=3)
    assert saved.opened_at is None


def test_concurrent_delivery_and_reply_retries_are_idempotent(db):
    ctx = context()
    source = delivery(db, ctx=ctx)
    result, reply_id = reply(db)
    assert result == source.id
    barrier = threading.Barrier(8)

    def retry(index):
        with db.begin() as session:
            message = session.get(Message, source.message_id if index % 2 else reply_id)
            barrier.wait(timeout=15)
            if index % 2:
                return life.record_delivery(session, message, ctx).id
            return life.record_reply(session, message)

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert set(executor.map(retry, range(8))) == {source.id}
    assert count(db, LifeEvent) == count(db, LifeEventReply) == 1
    assert row(db, LifeEvent, source.id).reply_count == 1


def test_concurrent_new_reply_saves_do_not_lose_increments(db):
    source = delivery(db, ctx=context())
    barrier = threading.Barrier(8)

    def save(index):
        barrier.wait(timeout=15)
        return reply(db, at=T0 + timedelta(minutes=index + 1))[0]

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert set(executor.map(save, range(8))) == {source.id}
    saved = row(db, LifeEvent, source.id)
    assert saved.reply_count == count(db, LifeEventReply) == 8
    assert saved.first_reply_at == T0 + timedelta(minutes=1)
    assert saved.engaged_at == T0 + timedelta(minutes=3)
    assert saved.opened_at is None


def test_open_is_explicit_same_pair_idempotent_and_never_a_reply(db):
    first = delivery(db, ctx=context())
    second = delivery(db, at=T0 + timedelta(hours=1))
    future = delivery(db, at=T0 + 2 * DAY)
    other = delivery(db, cid='other')
    stranger = delivery(db, uid=2)
    assert life.record_open(1, 'anna', now=T0 + timedelta(hours=2)) == 2
    assert life.record_open(1, 'anna', now=T0 + timedelta(hours=3)) == 0
    for event in (first, second):
        saved = row(db, LifeEvent, event.id)
        assert saved.opened_at == T0 + timedelta(hours=2)
        assert saved.reply_count == 0 and saved.first_reply_at is None
    for event in (future, other, stranger):
        assert row(db, LifeEvent, event.id).opened_at is None
    assert count(db, LifeEventReply) == 0
    assert participant(db).returned_at is None


@pytest.mark.parametrize('offset,opens', [(timedelta(microseconds=-1), 0),
                                         (timedelta(0), 1),
                                         (DAY - timedelta(microseconds=1), 1), (DAY, 0)])
def test_open_24h_boundary(db, offset, opens):
    delivery(db)
    assert life.record_open(1, 'anna', now=T0 + offset) == opens


@pytest.mark.parametrize('via', ['open', 'reply'])
@pytest.mark.parametrize('offset,returned', [(DAY - timedelta(microseconds=1), False),
    (DAY, True), (7 * DAY - timedelta(microseconds=1), True), (7 * DAY, False)])
def test_return_window_is_next_day_until_strict_seven_days(db, via, offset, returned):
    first = delivery(db, ctx=context())
    if via == 'open':
        life.record_open(1, 'anna', now=T0 + offset)
    else:
        reply(db, at=T0 + offset)
    assert (participant(db).returned_at is not None) is returned
    if offset >= DAY:
        saved = row(db, LifeEvent, first.id)
        assert saved.opened_at is None and saved.reply_count == 0
    before = life.collect_report(now=T0 + 7 * DAY - timedelta(microseconds=1))
    after = life.collect_report(now=T0 + 7 * DAY)
    arm = participant(db).variant
    assert before['arms'][arm]['return7d_n'] == 0
    assert after['arms'][arm]['return7d_n'] == 1
    assert after['arms'][arm]['return7d_count'] == int(returned)


def test_return_only_first_experimental_heroine_and_real_action(db):
    ctx = context()
    delivery(db, cid='outside')
    first = delivery(db, cid='anna', ctx=ctx)
    delivery(db, cid='other', at=T0 + DAY, ctx=ctx)
    life.record_open(1, 'other', now=T0 + 2 * DAY)
    reply(db, cid='other', at=T0 + 2 * DAY)
    reply(db, cid='anna', at=T0 + 2 * DAY, origin='purchase')
    life.record_open(2, 'anna', now=T0 + 2 * DAY)
    assert participant(db).returned_at is None
    life.record_open(1, 'anna', now=T0 + 2 * DAY)
    assert participant(db).returned_at == T0 + 2 * DAY
    assert row(db, LifeEvent, first.id).opened_at is None
    life.record_open(1, 'anna', now=T0 + 3 * DAY)
    assert participant(db).returned_at == T0 + 2 * DAY


def test_naive_utc_normalization(db):
    aware = T0.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=3)))
    ctx = context(now=aware)
    assert row(db, LifeExperiment, life.EXPERIMENT_KEY).started_at == T0
    first = delivery(db, ctx=ctx)
    life.record_open(1, 'anna', now=aware)
    assert row(db, LifeEvent, first.id).opened_at == T0


def test_issue_evidence_validation_dedup_upgrade_and_distinct_confirmed_stop(db):
    uid, ctx = treatment_context(db)
    source = delivery(db, uid=uid, ctx=ctx)
    _, one = reply(db, uid=uid)
    _, two = reply(db, uid=uid, at=T0 + timedelta(minutes=2))
    _, stranger = reply(db, uid=16 if uid != 16 else 15)
    _, other = reply(db, uid=uid, cid='other')
    _, before = reply(db, uid=uid, at=T0 - DAY)
    for message_id in (source.message_id, stranger, other, before, 99999):
        assert life.record_issue(source.id, message_id, 'memory', confirmed=True) is None
    assert life.record_issue(99999, one, 'memory', confirmed=True) is None
    with pytest.raises(ValueError):
        life.record_issue(source.id, one, 'arbitrary')
    issue_id = life.record_issue(source.id, one, 'memory')
    assert life.record_issue(source.id, one, 'memory') == issue_id
    life.record_issue(source.id, two, 'intrusive')
    assert row(db, LifeExperiment, life.EXPERIMENT_KEY).status == 'running'
    assert life.record_issue(source.id, one, 'memory', confirmed=True) == issue_id
    life.record_issue(source.id, one, 'intrusive', confirmed=True)
    assert row(db, LifeExperiment, life.EXPERIMENT_KEY).status == 'running'
    life.record_issue(source.id, one, 'memory', confirmed=False)
    assert row(db, LifeExperimentIssue, issue_id).confirmed is True
    life.record_issue(source.id, two, 'intrusive', confirmed=True)
    stopped = row(db, LifeExperiment, life.EXPERIMENT_KEY)
    assert (stopped.status, stopped.stop_reason) == ('stopped', 'repeated_quality_errors')
    assert count(db, LifeExperimentIssue) == 3
    with db() as session:
        assert not life.scene_enabled(session, source)


def test_outside_incidents_do_not_start_or_stop_experiment(db):
    source = delivery(db)
    for minute in (1, 2):
        _, evidence = reply(db, at=T0 + timedelta(minutes=minute))
        life.record_issue(source.id, evidence, 'memory', confirmed=True)
    assert count(db, LifeExperiment) == 0
    context()
    _, evidence = reply(db, at=T0 + timedelta(minutes=3))
    life.record_issue(source.id, evidence, 'intrusive', confirmed=True)
    assert row(db, LifeExperiment, life.EXPERIMENT_KEY).status == 'running'


def test_concurrent_issue_confirmation_is_deduplicated_and_stops(db):
    uid, ctx = treatment_context(db)
    source = delivery(db, uid=uid, ctx=ctx)
    evidence = [reply(db, uid=uid, at=T0 + timedelta(minutes=i + 1))[1] for i in range(2)]
    barrier = threading.Barrier(8)

    def confirm(index):
        barrier.wait(timeout=15)
        return life.record_issue(source.id, evidence[index % 2], 'memory', confirmed=True)

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert len(set(executor.map(confirm, range(8)))) == 2
    assert count(db, LifeExperimentIssue) == 2
    assert row(db, LifeExperiment, life.EXPERIMENT_KEY).stop_reason == 'repeated_quality_errors'


def test_report_excludes_whole_pending_participant_and_segments_first_mode(db):
    ctx = context(mode=False)
    first = delivery(db, ctx=ctx)
    for minute in (1, 2, 3):
        reply(db, at=T0 + timedelta(minutes=minute))
    delivery(db, at=T0 + 2 * DAY, cid='other', ctx={**ctx, 'mode_on': True})
    arm = ctx['variant']
    pending = life.collect_report(now=T0 + 2 * DAY + timedelta(hours=1))
    a = pending['arms'][arm]
    assert (a['recipients'], a['pending'], a['n'], a['engaged']) == (1, 1, 0, 0)
    assert pending['modes']['off']['arms'][arm]['pending'] == 1
    assert pending['modes']['on']['arms'][arm]['assigned'] == 0
    assert pending['mixed_mode'] == 1
    mature = life.collect_report(now=T0 + 3 * DAY)
    assert mature['arms'][arm]['n'] == mature['arms'][arm]['engaged'] == 1
    assert mature['modes']['off']['arms'][arm]['n'] == 1
    assert mature['outcome'] == 'inconclusive'
    assert participant(db).first_event_id == first.id


def seed_report(db, *, n=700, control=70, treatment=210, delivered_at=None):
    """Generate only synthetic identifiers/measurement rows for large cohorts."""
    delivered_at = delivered_at or T0
    with db.begin() as session:
        session.add(LifeExperiment(key=life.EXPERIMENT_KEY, started_at=T0, status='running'))
        for arm_index, (arm, successes) in enumerate((('control', control), ('treatment', treatment))):
            for index in range(n):
                uid = 1000 + arm_index * n + index
                identity = arm_index * n + index + 1
                session.add(LifeParticipant(user_id=uid, experiment_key=life.EXPERIMENT_KEY,
                    variant=arm, assigned_at=T0, first_event_id=identity, first_mode=bool(index % 2)))
                session.add(LifeEvent(id=identity, user_id=uid, character_id='anna',
                    message_id=identity, kind='moment', experiment_key=life.EXPERIMENT_KEY,
                    variant=arm, mode_on=bool(index % 2), delivered_at=delivered_at,
                    reply_count=3 if index < successes else 0,
                    engaged_at=delivered_at + timedelta(minutes=3) if index < successes else None))


def test_small_perfect_sample_never_wins(db):
    seed_report(db, n=10, control=0, treatment=10)
    data = life.collect_report(now=T0 + 30 * DAY)
    assert data['delta_pp'] == 100
    assert data['ci95_pp'][0] > 0
    assert data['outcome'] == 'inconclusive'


def test_final_success_requires_full_enrollment_700_per_arm_and_maturity(db):
    seed_report(db)
    early = life.collect_report(now=T0 + 14 * DAY - timedelta(microseconds=1))
    assert early['outcome'] == 'inconclusive'
    final = life.collect_report(now=T0 + 14 * DAY)
    assert final['outcome'] == 'success'
    assert final['delta_pp'] == pytest.approx(20)
    assert final['ci95_pp'][0] > 0
    assert final['enrollment_deadline'] == T0 + 14 * DAY
    assert final['arms']['control']['n'] == final['arms']['treatment']['n'] == 700
    assert final['arms']['control']['return7d_n'] == 700
    for arm in life.ARMS:
        assert sum(s['arms'][arm]['n'] for s in final['modes'].values()) == final['arms'][arm]['n']
    rendered = life.render_report(final)
    for text in ('95% ДИ', 'п.п.', 'возврат 7д', 'без доставки', 'Режим выкл.', 'Режим вкл.'):
        assert text in rendered
    life.stop(now=T0 + 15 * DAY)
    assert life.collect_report(now=T0 + 15 * DAY)['outcome'] == 'stopped'


def test_pending_recent_successes_block_apparent_large_win(db):
    seed_report(db, delivered_at=T0 + 13 * DAY + timedelta(hours=1))
    data = life.collect_report(now=T0 + 14 * DAY)
    assert data['pending'] == 1400 and data['pending_events'] == 1400
    assert data['arms']['treatment']['n'] == 0
    assert data['arms']['treatment']['engaged'] == 0
    assert data['outcome'] == 'inconclusive'
    assert life.collect_report(now=T0 + 14 * DAY + timedelta(hours=1))['outcome'] == 'success'


def test_single_pending_participant_blocks_final_win_even_with_enough_others(db):
    seed_report(db, n=701)
    with db.begin() as session:
        session.add(LifeEvent(user_id=1000, character_id='other', message_id=99999,
            kind='moment', experiment_key=life.EXPERIMENT_KEY, variant='control',
            mode_on=True, delivered_at=T0 + 14 * DAY, reply_count=3))
    data = life.collect_report(now=T0 + 14 * DAY)
    assert data['arms']['control']['n'] == 700
    assert data['pending'] == 1 and data['outcome'] == 'inconclusive'


@pytest.mark.parametrize('n,control,treatment,outcome', [
    (699, 0, 699, 'inconclusive'), (700, 70, 90, 'target_not_met'),
    (700, 350, 385, 'inconclusive'), (700, 70, 105, 'success'),
])
def test_minimum_lift_and_confidence_interval_all_required(db, n, control, treatment, outcome):
    seed_report(db, n=n, control=control, treatment=treatment)
    assert life.collect_report(now=T0 + 20 * DAY)['outcome'] == outcome


def test_disabled_report_cannot_declare_success(db, monkeypatch):
    seed_report(db)
    monkeypatch.setattr(life, 'ENABLED', False)
    data = life.collect_report(now=T0 + 14 * DAY)
    assert data['outcome'] == 'inconclusive'
    assert 'выключен' in life.render_report(data)


def test_primary_ignores_outside_and_live_photo_even_if_mislabeled_experimental(db):
    ctx = context()
    delivery(db, ctx=ctx)
    with db.begin() as session:
        session.add_all([
            LifeEvent(user_id=1, character_id='anna', message_id=998, kind='live_photo',
                experiment_key=life.EXPERIMENT_KEY, variant=ctx['variant'], delivered_at=T0, reply_count=3),
            LifeEvent(user_id=1, character_id='anna', message_id=999, kind='moment',
                variant='outside', delivered_at=T0 + 15 * DAY, reply_count=3),
        ])
    data = life.collect_report(now=T0 + 15 * DAY)
    assert data['arms'][ctx['variant']]['deliveries'] == 1
    assert data['arms'][ctx['variant']]['engaged'] == data['pending'] == 0


def test_stop_reason_rejects_private_text(db):
    with pytest.raises(ValueError):
        life.stop('synthetic private complaint text')
    assert count(db, LifeExperiment) == 0


def test_review_due_once_after_fourteen_days_and_single_claim(db):
    assert not life.review_due(now=T0)
    life.assignment(1, now=T0)
    assert not life.review_due(now=T0 + 14 * DAY - timedelta(microseconds=1))
    assert life.review_due(now=T0 + 14 * DAY)
    assert life.mark_review_sent(now=T0 + 14 * DAY)
    assert not life.mark_review_sent(now=T0 + 15 * DAY)
    assert not life.review_due(now=T0 + 15 * DAY)
    assert row(db, LifeExperiment, life.EXPERIMENT_KEY).review_sent_at == T0 + 14 * DAY


def test_review_claim_requires_real_start(db):
    life.stop(now=T0)
    assert not life.review_due(now=T0 + 30 * DAY)
    assert not life.mark_review_sent(now=T0 + 30 * DAY)


def test_admin_confirm_issue_stops_after_two_distinct(db):
    uid, ctx = treatment_context(db)
    source = delivery(db, uid=uid, ctx=ctx)
    _, one = reply(db, uid=uid)
    _, two = reply(db, uid=uid, at=T0 + timedelta(minutes=2))
    first = life.record_issue(source.id, one, 'memory')
    second = life.record_issue(source.id, two, 'intrusive')
    queue = life.recent_issues()
    assert {q['id'] for q in queue} >= {first, second}
    assert all(not q['confirmed'] for q in queue)
    assert life.confirm_issue(first)
    assert not life.confirm_issue(first)  # already confirmed
    assert row(db, LifeExperiment, life.EXPERIMENT_KEY).status == 'running'
    assert life.confirm_issue(second)
    assert row(db, LifeExperiment, life.EXPERIMENT_KEY).stop_reason == 'repeated_quality_errors'
    assert not life.confirm_issue(99999)


def test_deleted_source_is_not_attributed_and_not_a_return(db):
    first = delivery(db, ctx=context())
    with db.begin() as session:
        session.delete(session.get(Message, first.message_id))
    assert reply(db)[0] is None
    life.record_open(1, 'anna', now=T0 + 2 * DAY)
    assert participant(db).returned_at is None
    assert row(db, LifeEvent, first.id).reply_count == 0


def test_funnel_counters_are_separate_from_engagement(db):
    ctx = context()
    delivery(db, ctx=ctx)
    life.record_open(1, 'anna', now=T0 + timedelta(hours=1))
    reply(db, at=T0 + timedelta(minutes=2))
    data = life.collect_report(now=T0 + 2 * DAY)
    arm = data['arms'][ctx['variant']]
    assert arm['opened_recipients'] == 1 and arm['replied_recipients'] == 1
    assert arm['engaged'] == 0  # one reply is not three
    assert 'открыли 1' in life.render_report(data)


def test_reset_closes_scenes_but_keeps_measurement(db, monkeypatch):
    from services import memory_service as memory
    monkeypatch.setattr(memory, 'SessionLocal', db)
    uid, ctx = treatment_context(db)
    source = delivery(db, uid=uid, ctx=ctx)
    reply(db, uid=uid)
    memory.reset_conversation(uid, 'anna')
    saved = row(db, LifeEvent, source.id)
    assert saved.scene_status == 'closed' and saved.closed_reason == 'conversation_reset'
    assert saved.reply_count == 1  # counts survive, chat text does not
    assert count(db, Message) == 0
