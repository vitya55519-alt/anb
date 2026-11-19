"""Offline backend tests: synthetic accounts, temporary SQLite, no provider calls."""
from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import io
import os
from pathlib import Path
import re
import socket
import struct
import sys
from threading import Barrier
from types import ModuleType, SimpleNamespace
import wave

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]


def _pure_source_module(filename, names, **scope):
    """Use the REAL parsing functions without importing chat's provider graph.

    Only these named public-code files are read; no character/private data,
    .env, startup, migrations, or persisted application databases are loaded.
    """
    path = ROOT / 'services' / filename
    tree = ast.parse(path.read_text(encoding='utf-8'))
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in names for target in node.targets):
            nodes.append(node)
    module = ModuleType(filename[:-3])
    module.__dict__.update(re=re, **scope)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), module.__dict__)
    return module


def _stub(monkeypatch, name, module):
    import services
    monkeypatch.setitem(sys.modules, f'services.{name}', module)
    monkeypatch.setattr(services, name, module, raising=False)


@pytest.fixture
def core(tmp_path, monkeypatch):
    # Disable dotenv even on older python-dotenv versions; never open .env.
    monkeypatch.setenv('PYTHON_DOTENV_DISABLED', '1')
    import dotenv
    monkeypatch.setattr(dotenv, 'load_dotenv', lambda *a, **k: False)
    for name in list(os.environ):
        if 'proxy' in name.lower():
            monkeypatch.delenv(name)
    for name in ('MINIMAX_API_KEY', 'OPENAI_API_KEY', 'AI_KEY', 'GEMINI_API_KEY',
                 'SPICYAPI_KEY', 'TTS_API_KEY', 'FAL_KEY', 'PLATEGA_API_KEY'):
        monkeypatch.setenv(name, 'synthetic-test-key')
    monkeypatch.setenv('TELEGRAM_TOKEN', '123456:synthetic-test-token')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + (tmp_path / 'voice.sqlite').as_posix())

    def no_network(*args, **kwargs):
        raise AssertionError('Network/provider calls are forbidden in voice core tests')
    monkeypatch.setattr(socket.socket, 'connect', no_network)
    monkeypatch.setattr(socket, 'create_connection', no_network)

    from models.app_models import (User, Message, MessageVoice, ChatMedia,
                                   ProductEvent, Subscription, StarTransaction)
    tables = [m.__table__ for m in (User, Message, MessageVoice, ChatMedia,
                                   ProductEvent, Subscription, StarTransaction)]
    engine = create_engine(os.environ['DATABASE_URL'],
                           connect_args={'check_same_thread': False, 'timeout': 20})
    User.metadata.create_all(engine, tables=tables)
    sessions = sessionmaker(engine, expire_on_commit=False)
    _stub(monkeypatch, 'db', SimpleNamespace(SessionLocal=sessions))
    scene = _pure_source_module('scene_card_service.py', {'CARD_LINE', 'strip_card'})
    parser = _pure_source_module('chat_service.py', {
        '_NOVEL_MARK', '_is_thought_key', '_is_draft_key', '_blocks', 'message_block',
        '_SPEAKER_LINE', '_SPEAKER_PIPE', 'duo_lines'}, scene_card_service=scene)
    _stub(monkeypatch, 'chat_service', parser)
    speakers = {}
    _stub(monkeypatch, 'chat_guest_service', SimpleNamespace(speakers=lambda tg, cid: speakers))
    from services import message_voice_service as voice, trial_caps, voice_humanize
    monkeypatch.setattr(voice, 'SessionLocal', sessions)
    monkeypatch.setattr(voice, 'SPEAK_FREE_PER_DAY', 3)
    monkeypatch.setattr(voice, 'SPEAK_PEACH_COST', 20)
    monkeypatch.setattr(voice, 'ADMIN_TELEGRAM_IDS', set())
    monkeypatch.setattr(voice_humanize, 'ENABLED', True)
    monkeypatch.setattr(trial_caps, 'CAPS', {k: dict(v) for k, v in trial_caps._DEFAULTS.items()})
    clock = [datetime(2026, 11, 18, 12)]
    monkeypatch.setattr(voice, '_now', lambda: clock[0])
    monkeypatch.setattr(trial_caps, '_now', lambda: clock[0])
    with sessions.begin() as s:
        s.add_all([User(id=1, telegram_id='101', bonus_peaches=7, photo_credits=73, voice_style='nova'),
                   User(id=2, telegram_id='102', bonus_peaches=0, photo_credits=0, voice_style='echo')])
    state = SimpleNamespace(V=voice, caps=trial_caps, sessions=sessions, engine=engine, clock=clock,
                            User=User, Message=Message, Voice=MessageVoice, Media=ChatMedia,
                            Event=ProductEvent, Sub=Subscription, Charge=StarTransaction,
                            speakers=speakers, humanize=voice_humanize)
    yield state
    engine.dispose()


def message(c, *, user=1, cid='alpha', text='A neutral visible reply.', role='assistant', **fields):
    with c.sessions.begin() as s:
        row = c.Message(user_id=user, character_id=cid, role=role, content=text, **fields)
        s.add(row)
        s.flush()
        return row.id


def reserve(c, mid=None, *, cid='alpha', tg=101, **kwargs):
    if mid is None:
        mid = message(c, user=1 if tg == 101 else 2, cid=cid)
    return c.V.reserve(tg, cid, mid, **kwargs)


def done(c, reservation, audio=None, tg=101):
    return c.V.finish(tg, reservation['voice_id'], reservation['attempt'], wav() if audio is None else audio)


def fail(c, reservation, tg=101):
    return c.V.fail(tg, reservation['voice_id'], reservation['attempt'])


def wallet(c, uid=1):
    with c.sessions() as s:
        u = s.get(c.User, uid)
        return u.bonus_peaches, u.photo_credits


def events(c, name, uid=1):
    with c.sessions() as s:
        return list(s.scalars(select(c.Event).where(c.Event.user_id == uid,
                                                    c.Event.event_name == name)).all())


def used_free(c, count=3, uid=1):
    with c.sessions.begin() as s:
        rows = [c.Event(user_id=uid, character_id='previous', event_name='speak_free',
                        created_at=c.clock[0]) for _ in range(count)]
        s.add_all(rows)
        s.flush()
        return [r.id for r in rows]


def premium(c, *, used=0, product='premium_trial', days=3):
    with c.sessions.begin() as s:
        s.add(c.Sub(user_id=1, started_at=c.clock[0] - timedelta(hours=1),
                    expires_at=c.clock[0] + timedelta(days=days), status='active',
                    telegram_charge_id='synthetic-charge'))
        s.add(c.Charge(user_id=1, transaction_type='payment', product=product,
                       stars=75, telegram_charge_id='synthetic-charge'))
        s.add_all([c.Event(user_id=1, event_name='plan_voice', created_at=c.clock[0])
                   for _ in range(used)])


def together(functions):
    barrier = Barrier(len(functions))
    def run(fn):
        barrier.wait()
        return fn()
    with ThreadPoolExecutor(max_workers=len(functions)) as pool:
        return list(pool.map(run, functions))


def wav():
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b'\x00\x00' * 320)
    return buffer.getvalue()


def mp3(*, id3=False):
    # Two complete MPEG-1 Layer III, 128 kbps, 44.1 kHz frames.
    frame = b'\xff\xfb\x90\x00' + bytes(413)
    tag = b'ID3\x04\x00\x00\x00\x00\x00\x00' if id3 else b''
    return tag + frame * 2


def ogg():
    def page(packet, sequence, flags):
        header = (b'OggS\x00' + bytes([flags]) + struct.pack('<QII', 0, 1, sequence)
                  + bytes(4) + bytes([1, len(packet)]))
        raw = bytearray(header + packet)
        # Real Ogg CRC, so the synthetic fixture is also structurally valid.
        crc = 0
        for byte in raw:
            crc ^= byte << 24
            for _ in range(8):
                crc = ((crc << 1) ^ (0x04c11db7 if crc & 0x80000000 else 0)) & 0xffffffff
        raw[22:26] = struct.pack('<I', crc)
        return bytes(raw)
    identification = b'OpusHead' + struct.pack('<BBHIhB', 1, 1, 0, 48000, 0, 0)
    tags = b'OpusTags' + struct.pack('<II', 0, 0)
    return page(identification, 0, 2) + page(tags, 1, 0) + page(b'\xf8\xff\xfe', 2, 4)


def test_three_free_then_exact_twenty_and_account_scope(core):
    c = core
    for i, cid in enumerate(('alpha', 'beta', 'gamma')):
        r = reserve(c, cid=cid, allow_paid=True, quoted_price=20)
        assert (r['charged'], r['free_left']) == (0, 2 - i)
        assert done(c, r)['ok']
    assert wallet(c) == (7, 73)
    assert reserve(c) == {'ok': False, 'error': 'payment_required', 'price': 20}
    paid = reserve(c, allow_paid=True, quoted_price=20)
    assert paid['charged'] == 20
    assert paid['free_left'] is None  # No misleading "last free" UI notice.
    assert wallet(c) == (0, 60)
    assert done(c, paid)['charged'] == 20
    assert len(events(c, 'speak_free')) == 3
    assert len(events(c, 'speak_message')) == 4
    other = reserve(c, tg=102, cid='gamma')
    assert (other['charged'], other['free_left']) == (0, 2)
    assert wallet(c, 2) == (0, 0)


@pytest.mark.parametrize('kwargs', [
    {}, {'allow_paid': True}, {'quoted_price': 20},
    {'allow_paid': True, 'quoted_price': 19}, {'allow_paid': True, 'quoted_price': 2000},
    {'allow_paid': True, 'quoted_price': '20'}, {'allow_paid': True, 'quoted_price': 20.0},
    {'allow_paid': True, 'quoted_price': True},
])
def test_paid_requires_explicit_matching_integer_quote(core, kwargs):
    used_free(core)
    assert reserve(core, **kwargs) == {'ok': False, 'error': 'payment_required', 'price': 20}
    assert wallet(core) == (7, 73)
    with core.sessions() as s:
        assert s.scalar(select(func.count(core.Voice.id))) == 0


def test_insufficient_and_no_negative_balance(core):
    used_free(core, uid=2)
    assert reserve(core, tg=102, allow_paid=True, quoted_price=20) == {
        'ok': False, 'error': 'insufficient_peaches', 'price': 20}
    assert wallet(core, 2) == (0, 0)


def test_same_key_concurrent_and_unique_database_entitlement(core):
    mid = message(core)
    results = together([lambda: reserve(core, mid) for _ in range(8)])
    assert sum(r.get('status') == 'pending' for r in results) == 1
    assert sum(r.get('error') == 'voice_pending' for r in results) == 7
    assert len(events(core, 'speak_free')) == 1
    with core.sessions() as s:
        row = s.scalar(select(core.Voice))
        assert row.status == 'pending'
    with pytest.raises(IntegrityError), core.sessions.begin() as s:
        s.add(core.Voice(user_id=1, message_id=mid, part=0, character_id='alpha', attempt='duplicate'))


def test_simultaneous_different_messages_have_three_free_no_hidden_charge(core):
    mids = [message(core, cid=f'girl_{i}') for i in range(8)]
    results = together([lambda i=i: reserve(core, mids[i], cid=f'girl_{i}') for i in range(8)])
    assert sum(r.get('status') == 'pending' for r in results) == 3
    assert sum(r.get('error') == 'payment_required' for r in results) == 5
    assert wallet(core) == (7, 73)
    assert len(events(core, 'speak_free')) == 3


def test_concurrent_paid_different_messages_cannot_overdraw(core):
    used_free(core)
    mids = [message(core) for _ in range(8)]
    results = together([lambda mid=mid: reserve(core, mid, allow_paid=True, quoted_price=20) for mid in mids])
    assert sum(r.get('charged') == 20 for r in results) == 4
    assert sum(r.get('error') == 'insufficient_peaches' for r in results) == 4
    assert wallet(core) == (0, 0)


def test_simultaneous_paid_same_key_charges_once(core):
    used_free(core)
    mid = message(core)
    results = together([lambda: reserve(core, mid, allow_paid=True, quoted_price=20) for _ in range(6)])
    assert sum(r.get('charged') == 20 for r in results) == 1
    assert wallet(core) == (0, 60)


def test_refund_exact_split_once_concurrent_and_retry(core):
    used_free(core)
    mid = message(core)
    r = reserve(core, mid, allow_paid=True, quoted_price=20)
    assert wallet(core) == (0, 60)
    results = together([lambda: fail(core, r) for _ in range(6)])
    assert results.count(True) == 1
    assert wallet(core) == (7, 73)
    retry = reserve(core, mid, allow_paid=True, quoted_price=20)
    assert retry['voice_id'] == r['voice_id']
    assert retry['attempt'] != r['attempt']
    assert fail(core, r) is False
    assert done(core, r)['error'] == 'voice_stale'
    assert wallet(core) == (0, 60)
    assert done(core, retry)['ok']
    assert fail(core, retry) is False
    assert wallet(core) == (0, 60)


def test_free_failure_only_removes_its_reserved_event(core):
    history = used_free(core, count=2)
    r = reserve(core)
    assert len(events(core, 'speak_free')) == 3
    assert events(core, 'speak_message') == []
    assert fail(core, r)
    assert [e.id for e in events(core, 'speak_free')] == history
    assert fail(core, r) is False
    assert reserve(core)['free_left'] == 0


def test_premium_preserves_tier_allowance_then_paid_not_extra_daily_three(core):
    premium(core, used=9, days=30)  # product metadata wins over the raw duration
    r = reserve(core)
    assert (r['charged'], r['free_left']) == (0, None)  # Plan quota is not the daily free quota.
    assert len(events(core, 'plan_voice')) == 10
    assert events(core, 'speak_free') == []
    assert reserve(core)['error'] == 'payment_required'
    paid = reserve(core, allow_paid=True, quoted_price=20)
    assert paid['charged'] == 20
    assert len(events(core, 'plan_voice')) == 10
    assert fail(core, paid)
    assert wallet(core) == (7, 73)
    assert fail(core, r)
    assert len(events(core, 'plan_voice')) == 9
    assert reserve(core)['charged'] == 0


def test_premium_automatic_and_tap_voice_share_atomic_cap(core):
    premium(core, used=9)
    mid = message(core)
    results = together([lambda: core.caps.take_voice(101), lambda: reserve(core, mid)])
    auto, tap = results
    assert int(auto) + int(tap.get('status') == 'pending') == 1
    assert len(events(core, 'plan_voice')) == 10
    if tap.get('status') == 'pending':
        assert fail(core, tap)
        assert core.caps.take_voice(101) is True
    else:
        assert tap['error'] == 'payment_required'
    assert core.caps.take_voice(101) is False
    assert events(core, 'speak_free') == []


def test_shared_lock_is_first_statement_and_plan_uses_supplied_session(core):
    statements = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())
    event.listen(core.engine, 'before_cursor_execute', capture)
    try:
        mid = message(core)
        statements.clear()
        reserve(core, mid)
        assert statements[0].startswith('update users')
        statements.clear()
        core.caps.take_voice(101)
        assert statements[0].startswith('update users')
        with core.sessions.begin() as s:
            s.add(core.Sub(user_id=1, status='active', started_at=core.clock[0],
                           expires_at=core.clock[0] + timedelta(days=7)))
            assert core.caps.plan_uid(1, session=s)[1]['voice'] == 20
    finally:
        event.remove(core.engine, 'before_cursor_execute', capture)


def test_unlimited_premium_and_admin_never_pay(core, monkeypatch):
    premium(core)
    monkeypatch.setitem(core.caps.CAPS['trial'], 'voice', -1)
    r = reserve(core, allow_paid=True, quoted_price=20)
    assert (r['charged'], r['free_left']) == (0, None)
    assert len(events(core, 'plan_voice')) == 1
    monkeypatch.setattr(core.V, 'ADMIN_TELEGRAM_IDS', {102})
    used_free(core, uid=2)
    for _ in range(4):
        r = reserve(core, tg=102)
        assert (r['charged'], r['free_left']) == (0, None)
    assert wallet(core, 2) == (0, 0)


def test_replay_after_quota_and_utc_new_day_is_free(core):
    mid = message(core)
    r = reserve(core, mid)
    ready = done(core, r)
    used_free(core, count=2)
    assert reserve(core)['error'] == 'payment_required'
    assert reserve(core, mid) == {**ready, 'charged': 0, 'cached': True}
    core.clock[0] = core.clock[0].replace(hour=23, minute=59, second=59)
    assert reserve(core)['error'] == 'payment_required'
    core.clock[0] += timedelta(seconds=1)
    assert reserve(core, mid) == {**ready, 'charged': 0, 'cached': True}
    new = reserve(core, cid='another')
    assert (new['charged'], new['free_left']) == (0, 2)


@pytest.mark.parametrize('fields', [{'role': 'user'}, {'role': 'system'}, {'user': 2}])
def test_owned_assistant_required(core, fields):
    assert reserve(core, message(core, **fields))['error'] == 'not_found'
    assert events(core, 'speak_free') == []
    assert wallet(core) == (7, 73)


def test_character_part_owner_and_client_text_tampering_rejected(core):
    mid = message(core)
    assert reserve(core, mid, cid='beta')['error'] == 'not_found'
    assert reserve(core, 999999)['error'] == 'not_found'
    assert reserve(core, mid, tg=999)['error'] == 'not_found'
    for part in (-1, 1, 1.0, True, '0'):
        assert reserve(core, mid, part=part)['error'] == 'bad_request'
    assert reserve(core, mid, allow_paid='true')['error'] == 'bad_request'
    with pytest.raises(TypeError):
        core.V.reserve(101, 'alpha', mid, text='Injected replacement')
    with pytest.raises(TypeError):
        core.V.reserve(101, 'alpha', mid, voice_style='client-override')
    r = reserve(core, mid)
    assert done(core, r, tg=102)['error'] == 'voice_stale'
    assert fail(core, r, tg=102) is False
    assert fail(core, r) is True


def test_duo_parts_resolve_server_speaker_and_unknown_never_falls_back(core):
    core.speakers.update(Alpha='alpha', Beta='beta')
    mid = message(core, text='Alpha: First neutral line. | Beta: Second neutral line.')
    a = reserve(core, mid)
    b = reserve(core, mid, part=1)
    assert (a['text'], a['character_id']) == ('First neutral line.', 'alpha')
    assert (b['text'], b['character_id']) == ('Second neutral line.', 'beta')
    assert a['voice_id'] != b['voice_id']
    assert reserve(core, mid, part=2)['error'] == 'bad_request'
    unknown = message(core, text='Alpha: Neutral.\nUnknown: Also neutral.')
    assert reserve(core, unknown, part=1)['error'] == 'bad_request'
    assert len(events(core, 'speak_free')) == 2
    done(core, b)
    # Cached entitlement does not depend on the current guest still being here.
    core.speakers.clear()
    assert reserve(core, mid, part=1)['cached'] is True


@pytest.mark.parametrize('text, expected', [
    ('THOUGHT: Synthetic hidden thought.\nDRAFT: Synthetic hidden draft.\nMESSAGE: Visible line.', 'Visible line.'),
    ('MESSAGE: Visible line.\nDRAFT: Synthetic hidden draft.', 'Visible line.'),
    ('<think>Synthetic internal analysis.</think>Visible line.', 'Visible line.'),
    ('Visible line.\nSCENE: scene=synthetic room | near=no', 'Visible line.'),
    ('THOUGHT: Synthetic thought only.', None),
    ('DRAFT: Synthetic draft only.', None),
    ('<think>Synthetic unclosed thought.', None),
])
def test_hidden_blocks_never_spoken(core, text, expected):
    mid = message(core, text=text, draft_text='Synthetic private column.', image_prompt='Synthetic scene column.')
    r = reserve(core, mid)
    if expected is None:
        assert r['error'] == 'bad_request'
        assert events(core, 'speak_free') == []
    else:
        assert r['text'] == expected


def test_tts_humanize_compatibility_and_600_character_cap(core, monkeypatch):
    mid = message(core, text='Visible ' + 'x' * 800)
    assert len(reserve(core, mid)['text']) == 600
    mid = message(core, text='A [pause] <soft>line</soft> #42')
    assert reserve(core, mid)['text'] == 'A [pause] <soft>line</soft> #42'
    monkeypatch.setattr(core.humanize, 'ENABLED', False)
    mid = message(core, text='A [pause] <soft>line</soft> #42')
    assert reserve(core, mid)['text'] == 'A pause softlinesoft 42'


def test_stale_accountwide_free_recovery_and_late_old_finish(core):
    old_mid = message(core)
    old = reserve(core, old_mid)
    used_free(core, count=2)
    core.clock[0] += timedelta(minutes=3, seconds=1)
    replacement = reserve(core, cid='beta')
    assert replacement['charged'] == 0
    assert replacement['free_left'] == 0
    assert len(events(core, 'speak_free')) == 3
    assert done(core, old)['error'] == 'voice_stale'
    assert fail(core, old) is False
    assert done(core, replacement)['ok']
    assert len(events(core, 'speak_message')) == 1


def test_stale_same_key_retry_uses_new_attempt(core):
    mid = message(core)
    old = reserve(core, mid)
    core.clock[0] += timedelta(minutes=3, seconds=1)
    new = reserve(core, mid)
    assert new['voice_id'] == old['voice_id']
    assert new['attempt'] != old['attempt']
    assert done(core, old)['error'] == 'voice_stale'
    assert done(core, new)['ok']
    assert len(events(core, 'speak_free')) == 1


def test_stale_paid_refund_commits_even_on_cached_ready_return(core):
    mid = message(core)
    ready = done(core, reserve(core, mid))
    used_free(core, count=2)
    old = reserve(core, allow_paid=True, quoted_price=20)
    assert wallet(core) == (0, 60)
    core.clock[0] += timedelta(minutes=3, seconds=1)
    assert reserve(core, mid)['url'] == ready['url']
    assert wallet(core) == (7, 73)
    assert done(core, old)['error'] == 'voice_stale'


def test_stale_paid_refund_commits_even_on_payment_error(core):
    used_free(core)
    old = reserve(core, allow_paid=True, quoted_price=20)
    core.clock[0] += timedelta(minutes=3, seconds=1)
    assert reserve(core)['error'] == 'payment_required'
    assert wallet(core) == (7, 73)
    assert done(core, old)['error'] == 'voice_stale'


def test_stale_premium_quota_is_recovered_for_different_message(core):
    premium(core, used=9)
    old = reserve(core)
    core.clock[0] += timedelta(minutes=3, seconds=1)
    new = reserve(core, cid='beta')
    assert new['charged'] == 0
    assert len(events(core, 'plan_voice')) == 10
    assert done(core, old)['error'] == 'voice_stale'
    assert done(core, new)['ok']


def test_pending_outlives_caller_deadline_but_expired_finish_refunds(core):
    r = reserve(core)
    core.clock[0] += timedelta(seconds=91)
    assert done(core, r)['ok']
    old = reserve(core)
    core.clock[0] += timedelta(minutes=3, seconds=1)
    assert done(core, old)['error'] == 'voice_stale'
    assert len(events(core, 'speak_free')) == 1


@pytest.mark.parametrize('factory, ext, mime', [(wav, 'wav', 'audio/wav'), (ogg, 'ogg', 'audio/ogg'),
                                              (mp3, 'mp3', 'audio/mpeg'),
                                              (lambda: mp3(id3=True), 'mp3', 'audio/mpeg')])
def test_audio_formats_store_true_mime_and_database_bytes(core, factory, ext, mime):
    r = reserve(core)
    audio = factory()
    result = done(core, r, audio=audio)
    assert result['ok'] is True
    assert result['url'].endswith('.' + ext)
    with core.sessions() as s:
        media = s.scalar(select(core.Media))
        ledger = s.get(core.Voice, r['voice_id'])
        assert media.telegram_id == '101'
        assert (media.content_type, media.data) == (mime, audio)
        assert ledger.status == 'ready'
        assert ledger.filename == media.filename
    assert done(core, r, audio=audio)['error'] == 'voice_stale'
    assert len(events(core, 'speak_message')) == 1


@pytest.mark.parametrize('audio', [b'', b'<html>upstream error</html>' * 5, b'OggS', b'RIFF' + bytes(50),
                                   b'ID3' + bytes(50), wav()[:-1], ogg()[:-1], mp3()[:-1],
                                   b'\xff\xfb\x90\x00', b'ID3\x04\x00\x00\x7f\x7f\x7f\x7f' + bytes(50)])
def test_invalid_or_truncated_audio_refunds_and_never_becomes_ready(core, audio):
    used_free(core)
    r = reserve(core, allow_paid=True, quoted_price=20)
    assert done(core, r, audio=audio)['error'] == 'invalid_audio'
    assert wallet(core) == (7, 73)
    assert fail(core, r) is False
    assert events(core, 'speak_message') == []
    with core.sessions() as s:
        assert s.scalar(select(func.count(core.Media.id))) == 0
        assert s.get(core.Voice, r['voice_id']).status == 'failed'


def test_finish_media_and_ready_event_are_one_transaction(core):
    used_free(core)
    r = reserve(core, allow_paid=True, quoted_price=20)
    def abort_media(mapper, connection, target):
        raise RuntimeError('Synthetic database write failure')
    event.listen(core.Media, 'before_insert', abort_media)
    try:
        with pytest.raises(RuntimeError, match='Synthetic database write failure'):
            done(core, r)
    finally:
        event.remove(core.Media, 'before_insert', abort_media)
    with core.sessions() as s:
        assert s.get(core.Voice, r['voice_id']).status == 'pending'
        assert s.scalar(select(func.count(core.Media.id))) == 0
    assert events(core, 'speak_message') == []
    assert fail(core, r) is True  # caller's exception/finally path
    assert wallet(core) == (7, 73)


def test_finish_and_fail_race_has_exactly_one_winner(core):
    used_free(core)
    r = reserve(core, allow_paid=True, quoted_price=20)
    ready, refunded = together([lambda: done(core, r), lambda: fail(core, r)])
    assert int(ready['ok']) + int(refunded) == 1
    if ready['ok']:
        assert wallet(core) == (0, 60)
        assert len(events(core, 'speak_message')) == 1
    else:
        assert wallet(core) == (7, 73)
        assert events(core, 'speak_message') == []


def test_existing_voice_media_replays_without_quota_or_new_synthesis(core):
    used_free(core)
    mid = message(core, text='', media_kind='voice', media_url='/webapp/media/12345678_12345678.ogg')
    result = reserve(core, mid)
    assert result['status'] == 'ready'
    assert result['charged'] == 0 and result['cached'] is True
    assert reserve(core, mid) == result
    assert reserve(core, mid, part=1)['error'] == 'bad_request'
    assert wallet(core) == (7, 73)
    assert len(events(core, 'speak_free')) == 3
    assert events(core, 'speak_message') == []


def test_playback_owned_ready_whitelisted_deduplicated_and_history(core):
    mid = message(core)
    r = reserve(core, mid)
    assert core.V.mark_playback(101, r['voice_id'], 'play') is False
    ready = done(core, r)
    assert core.V.mark_playback(102, r['voice_id'], 'play') is False
    assert core.V.mark_playback(101, r['voice_id'], 'arbitrary_event') is False
    results = together([lambda: core.V.mark_playback(101, r['voice_id'], 'play') for _ in range(5)])
    assert results.count(True) == 1
    assert core.V.mark_playback(101, r['voice_id'], 'end') is True
    assert core.V.mark_playback(101, r['voice_id'], 'end') is False
    for name in ('speak_message', 'speak_play', 'speak_end'):
        rows = events(core, name)
        assert len(rows) == 1
        assert rows[0].metadata_json == '{}'
    assert core.V.ready_by_messages(1, [mid, mid, 999, True]) == {
        mid: [{'part': 0, 'url': ready['url'], 'voice_id': r['voice_id']}]}
    assert core.V.ready_by_messages(2, [mid]) == {}
    assert core.V.ready_by_messages(1, []) == {}


def test_combined_concurrent_free_then_paid_reservations(core):
    mids = [message(core) for _ in range(9)]
    results = together([lambda mid=mid: reserve(core, mid, allow_paid=True, quoted_price=20)
                        for mid in mids])
    assert sum(r.get('charged') == 0 for r in results) == 3
    assert sum(r.get('charged') == 20 for r in results) == 4
    assert sum(r.get('error') == 'insufficient_peaches' for r in results) == 2
    assert wallet(core) == (0, 0)
    assert len(events(core, 'speak_free')) == 3


@pytest.mark.parametrize('is_premium', [False, True])
def test_invalid_audio_refunds_free_or_premium_quota(core, is_premium):
    if is_premium:
        premium(core, used=9)
        name, before = 'plan_voice', 9
    else:
        used_free(core, count=2)
        name, before = 'speak_free', 2
    r = reserve(core)
    assert done(core, r, audio=b'') == {'ok': False, 'error': 'invalid_audio'}
    assert len(events(core, name)) == before
    assert reserve(core)['charged'] == 0


def test_refund_adds_exact_split_without_overwriting_other_wallet_changes(core):
    used_free(core)
    r = reserve(core, allow_paid=True, quoted_price=20)
    with core.sessions.begin() as s:
        user = s.get(core.User, 1)
        user.bonus_peaches += 2
        user.photo_credits += 5
    assert fail(core, r)
    assert wallet(core) == (9, 78)


def test_paid_replay_never_recharges_on_same_or_next_day(core):
    used_free(core)
    mid = message(core)
    paid = reserve(core, mid, allow_paid=True, quoted_price=20)
    done(core, paid)
    before = wallet(core)
    for advance in (0, 1):
        core.clock[0] += timedelta(days=advance)
        cached = reserve(core, mid, allow_paid=True, quoted_price=20)
        assert cached['cached'] and cached['charged'] == 0
        assert wallet(core) == before
    assert len(events(core, 'speak_message')) == 1


@pytest.mark.parametrize('factory', [ogg, wav, mp3])
def test_database_bytes_restore_through_existing_media_reader(core, tmp_path, factory):
    # Run the real disk-cache restoration body without importing the webapp.
    import logging
    reader = _pure_source_module('webapp_service.py', {'_MEDIA_NAME_RE', 'chat_media_file_path'},
                                 Path=Path, APP_MEDIA_DIR=tmp_path / 'media-cache',
                                 ChatMedia=core.Media, SessionLocal=core.sessions,
                                 select=select, logger=logging.getLogger(__name__))
    r = reserve(core)
    ready = done(core, r, audio=factory())
    filename = ready['url'].rsplit('/', 1)[1]
    assert reader.chat_media_file_path(102, filename) is None
    path = reader.chat_media_file_path(101, filename)
    assert path is not None
    assert path.read_bytes() == factory()


def test_config_price_is_direct_twenty_not_scaled():
    tree = ast.parse((ROOT / 'config.py').read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'SPEAK_PEACH_COST' for t in n.targets))
    assert isinstance(node.value, ast.Constant) and type(node.value.value) is int
    assert node.value.value == 20
