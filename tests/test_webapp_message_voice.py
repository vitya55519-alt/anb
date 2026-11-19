"""Message-bound voice regressions; no startup, config, production DB, or providers."""
import ast
import asyncio
import json
from functools import lru_cache
from pathlib import Path
import re
import shutil
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import web

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / 'main.py'
SPA = ROOT / 'webapp' / 'index.html'
SOURCE = {'character_id': 'girl_a', 'message_id': 41, 'part': 0}
READY = {'ok': True, 'status': 'ready', 'voice_id': 8,
         'url': '/webapp/media/synthetic.ogg', 'cached': True, 'charged': 0}


@lru_cache(maxsize=None)
def syntax(path):
    return ast.parse(path.read_text(encoding='utf-8'))


def extract(path, name, scope):
    tree = syntax(path)
    node = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == name)
    node.decorator_list = []
    future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
    module = ast.fix_missing_locations(ast.Module(body=[future, node], type_ignores=[]))
    exec(compile(module, str(path), 'exec'), scope)
    return scope[name]


def stub_module(monkeypatch, package, name, **members):
    module = ModuleType('services.' + name)
    module.__dict__.update(members)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    setattr(package, name, module)
    return module


@pytest.fixture
def route(monkeypatch):
    # Replacing the package as well avoids importing production config transitively.
    package = ModuleType('services')
    package.__path__ = []
    monkeypatch.setitem(sys.modules, 'services', package)
    voices = stub_module(monkeypatch, package, 'message_voice_service',
                         reserve=Mock(return_value=dict(READY)), finish=Mock(return_value=dict(READY)),
                         fail=Mock(return_value=True), mark_playback=Mock(return_value=True),
                         ready_by_messages=Mock(return_value={}))
    auth = SimpleNamespace(validate_init_data=Mock(return_value={'verified': True}),
                           init_data_user=Mock(return_value={'id': 101}),
                           chat_media_file_path=Mock())
    scope = dict(web=web, asyncio=asyncio, webapp_service=auth,
                 synthesize_bytes=AsyncMock(return_value=b'OggS synthetic audio'), logger=Mock())
    return SimpleNamespace(
        speak=extract(MAIN, '_webapp_api_chat_speak', scope),
        event=extract(MAIN, '_webapp_api_chat_speak_event', scope),
        media=extract(MAIN, '_webapp_media', scope), scope=scope, voices=voices,
        auth=auth, synth=scope['synthesize_bytes'], package=package)


def request(body=None, *, error=None):
    return SimpleNamespace(query={'init_data': 'synthetic-auth'},
                           json=AsyncMock(return_value=body, side_effect=error),
                           match_info={'filename': 'synthetic.ogg'})


def response_json(response, status):
    assert response.status == status
    assert response.content_type == 'application/json'
    return json.loads(response.text)


def assert_no_synthesis(route):
    route.synth.assert_not_awaited()
    route.voices.finish.assert_not_called()
    route.voices.fail.assert_not_called()


@pytest.mark.parametrize('handler', ['speak', 'event', 'media'])
@pytest.mark.parametrize('invalid_signature', [True, False])
def test_auth_is_checked_before_body_or_services(route, handler, invalid_signature):
    if invalid_signature:
        route.auth.validate_init_data.return_value = None
    else:
        route.auth.init_data_user.return_value = {}
    req = request(SOURCE)
    response = asyncio.run(getattr(route, handler)(req))
    assert response.status == 401
    req.json.assert_not_awaited()
    route.voices.reserve.assert_not_called()
    route.voices.mark_playback.assert_not_called()
    route.auth.chat_media_file_path.assert_not_called()
    assert_no_synthesis(route)


@pytest.mark.parametrize('body', [None, [], ['message'], 'text', True, 42, {},
    {'text': 'client supplied text', 'character_id': 'girl_a'},
    dict(SOURCE, message_id=0), dict(SOURCE, message_id=-1),
    dict(SOURCE, message_id={}), dict(SOURCE, message_id='not-an-id'),
    dict(SOURCE, message_id=True), dict(SOURCE, message_id=41.5),
    dict(SOURCE, message_id=float('inf')), dict(SOURCE, part=True),
    dict(SOURCE, part=0.5), dict(SOURCE, part=None),
    dict(SOURCE, character_id=''), dict(SOURCE, part=-1), dict(SOURCE, part=[]),
    dict(SOURCE, quoted_price=True), dict(SOURCE, quoted_price='30'),
    dict(SOURCE, quoted_price=30.5), dict(SOURCE, quoted_price=-1)])
def test_malformed_or_unbound_speak_requests_do_not_reserve(route, body):
    result = response_json(asyncio.run(route.speak(request(body))), 400)
    assert result == {'ok': False, 'error': 'bad_request'}
    route.voices.reserve.assert_not_called()
    assert_no_synthesis(route)


@pytest.mark.parametrize('handler', ['speak', 'event'])
def test_invalid_json_does_not_reserve(route, handler):
    result = response_json(asyncio.run(getattr(route, handler)(request(error=ValueError('invalid JSON')))), 400)
    assert result['error'] == 'bad_request'
    route.voices.reserve.assert_not_called()
    route.voices.mark_playback.assert_not_called()
    assert_no_synthesis(route)


@pytest.mark.parametrize('allow_paid', [None, False, 1, 'true', 'false', [], {}, True])
def test_only_literal_true_authorizes_the_exact_quote(route, allow_paid):
    body = dict(SOURCE, allow_paid=allow_paid, quoted_price=37)
    response_json(asyncio.run(route.speak(request(body))), 200)
    route.voices.reserve.assert_called_once_with(
        101, 'girl_a', 41, part=0, allow_paid=allow_paid is True, quoted_price=37)
    assert_no_synthesis(route)


@pytest.mark.parametrize(('error', 'status'), [
    ('payment_required', 402), ('insufficient_peaches', 402),
    ('voice_pending', 409), ('not_found', 404), ('bad_request', 400)])
def test_service_rejections_are_returned_without_tts_or_automatic_paid_retry(route, error, status):
    offer = {'ok': False, 'error': error, 'price': 37}
    route.voices.reserve.return_value = offer
    response = asyncio.run(route.speak(request(dict(SOURCE, text='untrusted', voice_style='evil'))))
    assert response_json(response, status) == offer
    assert response.headers['Cache-Control'] == 'no-store'
    route.voices.reserve.assert_called_once_with(
        101, 'girl_a', 41, part=0, allow_paid=False, quoted_price=None)
    assert_no_synthesis(route)


def test_foreign_source_is_delegated_with_authenticated_owner(route):
    route.voices.reserve.return_value = {'ok': False, 'error': 'not_found'}
    response = asyncio.run(route.speak(request(dict(SOURCE, message_id=999, telegram_id=202, user_id=202))))
    assert response_json(response, 404)['error'] == 'not_found'
    route.voices.reserve.assert_called_once_with(
        101, 'girl_a', 999, part=0, allow_paid=False, quoted_price=None)
    assert_no_synthesis(route)


def test_ready_replay_returns_persistent_url_without_tts(route):
    response = asyncio.run(route.speak(request(SOURCE)))
    assert response_json(response, 200) == READY
    assert response.headers['Cache-Control'] == 'no-store'
    assert_no_synthesis(route)


def reserve_new(route):
    route.voices.reserve.return_value = {
        'ok': True, 'status': 'pending', 'voice_id': 8, 'attempt': 'synthetic-attempt',
        'text': 'Stored visible reply', 'voice_style': 'server-selected',
        'character_id': 'girl_b', 'free_left': 1}


def test_new_synthesis_uses_only_reserved_source_and_has_90_second_deadline(route):
    reserve_new(route)
    real_wait_for = asyncio.wait_for
    wait = AsyncMock(side_effect=real_wait_for)
    route.scope['asyncio'] = SimpleNamespace(to_thread=asyncio.to_thread, wait_for=wait,
                                             CancelledError=asyncio.CancelledError, shield=asyncio.shield)
    body = dict(SOURCE, text='NEVER SPEAK THIS', voice_style='attacker', url='https://invalid.test')
    response = asyncio.run(route.speak(request(body)))
    assert response_json(response, 200)['free_left'] == 1
    route.synth.assert_awaited_once_with('Stored visible reply', 'server-selected', character_id='girl_b')
    assert wait.await_args.kwargs == {'timeout': 90}
    route.voices.finish.assert_called_once_with(101, 8, 'synthetic-attempt', b'OggS synthetic audio')
    route.voices.fail.assert_not_called()
    assert 'Stored visible reply' not in response.text


@pytest.mark.parametrize('failure', ['provider', 'timeout', 'finish_exception', 'finish_rejected'])
def test_failed_generation_releases_the_attempt_for_refund(route, failure):
    reserve_new(route)
    if failure == 'provider':
        route.synth.side_effect = RuntimeError('synthetic private provider text')
    elif failure == 'timeout':
        async def timeout(awaitable, *, timeout):
            awaitable.close()
            raise asyncio.TimeoutError
        route.scope['asyncio'] = SimpleNamespace(to_thread=asyncio.to_thread, wait_for=timeout,
                                                 CancelledError=asyncio.CancelledError, shield=asyncio.shield)
    elif failure == 'finish_exception':
        route.voices.finish.side_effect = RuntimeError('synthetic storage failure')
    else:
        route.voices.finish.return_value = {'ok': False, 'error': 'invalid_audio'}
    response = asyncio.run(route.speak(request(SOURCE)))
    assert response_json(response, 502)['ok'] is False
    route.voices.fail.assert_called_once_with(101, 8, 'synthetic-attempt')
    assert 'synthetic private provider text' not in response.text
    assert 'synthetic private provider text' not in str(route.scope['logger'].mock_calls)


def test_cancellation_during_tts_refunds_and_propagates(route):
    reserve_new(route)

    async def scenario():
        entered = asyncio.Event()
        async def synth(*args, **kwargs):
            entered.set()
            await asyncio.Future()
        route.synth.side_effect = synth
        task = asyncio.create_task(route.speak(request(SOURCE)))
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(scenario())
    route.voices.fail.assert_called_once_with(101, 8, 'synthetic-attempt')
    route.voices.finish.assert_not_called()


@pytest.mark.parametrize('body', [None, [], True, {}, {'voice_id': 8, 'event': 'synth'},
    {'voice_id': 8, 'event': 'pause'}, {'voice_id': 8, 'event': 'ended'},
    {'voice_id': 0, 'event': 'play'}, {'voice_id': {}, 'event': 'end'},
    {'voice_id': True, 'event': 'play'}, {'voice_id': 8.5, 'event': 'end'},
    {'voice_id': float('inf'), 'event': 'play'}])
def test_analytics_rejects_invalid_events_and_json(route, body):
    assert response_json(asyncio.run(route.event(request(body))), 400)['error'] == 'bad_request'
    route.voices.mark_playback.assert_not_called()
    route.voices.reserve.assert_not_called()


@pytest.mark.parametrize('event', ['play', 'end'])
@pytest.mark.parametrize('owned', [True, False])
def test_analytics_uses_authenticated_owner_and_only_real_events(route, event, owned):
    route.voices.mark_playback.return_value = owned
    response = asyncio.run(route.event(request({'voice_id': 8, 'event': event,
                                                'telegram_id': 202, 'text': 'ignored'})))
    assert response_json(response, 200 if owned else 404) == {'ok': owned}
    route.voices.mark_playback.assert_called_once_with(101, 8, event)
    route.voices.reserve.assert_not_called()
    assert_no_synthesis(route)


@pytest.mark.parametrize(('suffix', 'mime'), [('ogg', 'audio/ogg'), ('wav', 'audio/wav'), ('mp3', 'audio/mpeg')])
def test_persistent_audio_download_uses_owner_and_correct_mime(route, tmp_path, suffix, mime):
    path = tmp_path / ('synthetic.' + suffix)
    path.write_bytes(b'synthetic audio')
    route.auth.chat_media_file_path.return_value = path
    req = request()
    req.match_info['filename'] = path.name
    response = asyncio.run(route.media(req))
    assert response.status == 200
    assert response.body == b'synthetic audio'
    assert response.content_type == mime
    assert response.headers['Cache-Control'].startswith('private,')
    route.auth.chat_media_file_path.assert_called_once_with(101, path.name)


def test_foreign_or_missing_media_is_not_downloaded(route):
    route.auth.chat_media_file_path.return_value = None
    assert asyncio.run(route.media(request())).status == 404


def test_history_associates_ready_voices_by_source_id_not_position(route, monkeypatch):
    rows = [SimpleNamespace(id=i, role='assistant', content='Stored ' + str(i), created_at=None)
            for i in (41, 42, 43)]
    memory = stub_module(monkeypatch, route.package, 'memory_service',
                         get_recent_messages=Mock(return_value=rows), message_actions=Mock(return_value=[]))
    stub_module(monkeypatch, route.package, 'chat_service', message_block=lambda text: text)
    route.voices.ready_by_messages.return_value = {43: [dict(READY, part=0)], 999: [dict(READY)]}
    history = extract(ROOT / 'services' / 'webapp_service.py', 'api_chat_history', {})
    result = history(7, 'girl_a')
    memory.get_recent_messages.assert_called_once_with(7, 'girl_a', 30)
    route.voices.ready_by_messages.assert_called_once_with(7, [41, 42, 43])
    assert [row['voices'] for row in result] == [[], [], [dict(READY, part=0)]]
    assert [row['id'] for row in result] == [41, 42, 43]


def test_fresh_reply_id_selects_only_owned_assistant_source(route, monkeypatch):
    # A minimal mapped table executes the production ownership query, in memory.
    from sqlalchemy import Column, Integer, String, create_engine, select
    from sqlalchemy.orm import declarative_base, sessionmaker

    base = declarative_base()

    class Message(base):
        __tablename__ = 'synthetic_messages'
        id = Column(Integer, primary_key=True)
        user_id = Column(Integer)
        character_id = Column(String)
        role = Column(String)
        content = Column(String)
        media_kind = Column(String)
        media_url = Column(String)

    engine = create_engine('sqlite://')
    base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    stub_module(monkeypatch, route.package, 'chat_service',
                message_block=lambda text: text.split('MESSAGE:')[-1].strip())
    associate = extract(ROOT / 'services' / 'webapp_service.py', 'chat_reply_message_id',
                        dict(SessionLocal=sessions, select=select, Message=Message))
    try:
        with sessions.begin() as session:
            for ident, owner, girl, role, content in [
                (40, 7, 'girl_a', 'assistant', 'Reply'),
                (41, 7, 'girl_a', 'assistant', 'THOUGHT: synthetic\nMESSAGE: Reply'),
                (42, 7, 'girl_b', 'assistant', 'Reply'),
                (43, 8, 'girl_a', 'assistant', 'Reply'),
                (44, 7, 'girl_a', 'user', 'Reply'),
                (45, 7, 'girl_a', 'assistant', 'Unrelated reply'),
            ]:
                session.add(Message(id=ident, user_id=owner, character_id=girl,
                                    role=role, content=content))
        assert associate(7, 'girl_a', 'Reply', READY['url']) == 41
        assert associate(7, 'girl_a', 'No matching source') is None
        assert associate(7, 'girl_a', '') is None
        with sessions() as session:
            source = session.get(Message, 41)
            assert (source.media_kind, source.media_url) == ('voice', READY['url'])
            assert all(row.media_url is None for row in session.scalars(
                select(Message).where(Message.id != 41)))
    finally:
        engine.dispose()


def js_function(source, name):
    match = re.search(r'^(?:async )?function ' + re.escape(name) + r'\(', source, re.M)
    assert match, 'Missing production function: ' + name
    start = match.start()
    line_end = source.index('\n', start)
    end = line_end if source[start:line_end].rstrip().endswith('}') else source.index('\n}', start) + 2
    return source[start:end]


JS_SETUP = r'''
const assert = require('node:assert/strict');
let CHAT = {id: 'girl_a', name: 'A', custom: true};
let CHAT_LEVEL = null, ME = {premium: false}, LANG = 'en';
const tg = {initData: 'synthetic&auth'};
const L = {reply_err: 'Failed', speak_free_left: n => 'Remaining: ' + n};
const painted = [], notices = [], calls = [], listeners = {}, audios = [];
const box = {insertAdjacentHTML: (_, html) => painted.push(html), scrollHeight: 20};
const document = {
  addEventListener: (name, fn, capture) => { (listeners[name] ||= []).push(fn); },
  getElementById: id => id === 'chatMsgs' ? box : {remove() {}},
  querySelectorAll: () => audios,
  createElement: tag => {
    assert.equal(tag, 'audio');
    const au = {tagName: 'AUDIO', paused: true, currentTime: 0, duration: 8,
      play() { this.playCalls = (this.playCalls || 0) + 1; return Promise.resolve(); },
      pause() { this.paused = true; }, closest() { return this.parent; }};
    audios.push(au); return au;
  }
};
const toast = text => notices.push(text);
const loadChatLevel = () => {}, refreshPlotBar = () => {}, renderGuest = () => {};
const herAvatar = () => '', duoNames = text => text;
const draftPlate = () => '', livePlate = () => '', eventActions = () => '';
const afterDraft = (d, done) => done();
const window = {confirm: () => { throw Error('Unexpected confirmation'); }};
const reply = (body, status=200) => ({ok: status < 400, status, json: async () => body});
const ready = {ok: true, voice_id: 8, url: '/webapp/media/synthetic.ogg'};
const deferred = () => { let resolve; const promise = new Promise(r => {resolve = r;}); return {promise, resolve}; };
const emit = (event, target) => (listeners[event] || []).forEach(fn => fn({target}));
function note(id=41) {
  const msg = {dataset: {characterId: 'girl_a', messageId: String(id), voicePart: '0'},
    getAttribute: () => 'Stored reply'};
  const btn = {textContent: '▶'}, duration = {};
  const vp = {dataset: {lazy: '1'}, isConnected: true, msg, btn, children: [],
    closest: () => msg,
    querySelector: sel => sel === '.vp-btn' ? btn : sel === '.vp-dur' ? duration : vp.children[0],
    querySelectorAll: () => [],
    appendChild(au) { au.parent = vp; vp.children.push(au); }};
  return vp;
}
let fetch = async () => { throw Error('Unexpected network request'); };
'''


def run_js(checks):
    node = shutil.which('node')
    assert node, 'Node.js is required to execute frontend regression tests'
    source = SPA.read_text(encoding='utf-8')
    names = ('esc', 'fmtTime', 'parseThought', 'messageCard', 'sameChat', 'chatBubble',
             'historyLine', 'insertChatReply', 'speakSource', 'confirmVoice', 'speakLazy',
             'voicePlaybackEvent', 'voicePlayer', 'vpFmt', 'vpPlay', 'vpPaint')
    declarations = '\n'.join(js_function(source, name) for name in names)
    declarations += '\n' + re.search(r'^const VP_BARS = .*;', source, re.M).group()
    # Execute the real capture-phase listeners as well as their functions.
    start = source.index("['loadedmetadata', 'durationchange', 'timeupdate'")
    declarations += '\n' + source[start:source.index("document.addEventListener('click'", start)]
    program = JS_SETUP + '\n' + declarations + '\n(async () => {\n' + checks + '\n})()'
    harness = ('const vm = require("node:vm");\n'
               'const context = vm.createContext({require, console});\n'
               'const deadline = setTimeout(() => {console.error("Unfinished UI test"); process.exit(1);}, 5000);\n'
               'Promise.resolve(vm.runInContext(' + json.dumps(program) + ', context))'
               '.then(() => clearTimeout(deadline), e => {clearTimeout(deadline); console.error(e); process.exitCode = 1;});')
    result = subprocess.run([node, '-'], input=harness, encoding='utf-8',
                            capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_ui_explicit_quote_confirmation_and_source_only_payload():
    run_js(r'''
const vp = note();
const approval = deferred();
tg.showConfirm = (question, done) => {
  assert.match(question, /37 peaches/);
  assert.match(question, /Replaying is free/);
  approval.promise.then(done);
};
const offered = deferred();
fetch = async (url, options) => {
  assert.match(url, /^\/webapp\/api\/chat\/speak\?init_data=synthetic%26auth$/);
  calls.push(JSON.parse(options.body));
  if (calls.length === 1) { offered.resolve(); return reply({ok: false, error: 'payment_required', price: 37}, 402); }
  return reply(ready);
};
const pending = speakLazy(vp);
await offered.promise;
assert.equal(calls.length, 1);
assert.deepEqual(calls[0], {character_id: 'girl_a', message_id: 41, part: 0});
approval.resolve(true);
await pending;
assert.deepEqual(calls[1], {...calls[0], allow_paid: true, quoted_price: 37});
assert.equal(vp.children.length, 1);
assert.equal(vp.children[0].src, '/webapp/media/synthetic.ogg?init_data=synthetic%26auth');
assert.equal(vp.dataset.voiceId, '8');
assert.equal(vp.dataset.lazy, undefined);
assert.equal(vp.dataset.busy, undefined);
assert.equal(vp.children[0].playCalls, 1);
''')


@pytest.mark.parametrize('price', [0, -1, 1.5, None, 'not-a-price'])
def test_ui_invalid_payment_offer_never_sends_paid_request(price):
    run_js('const price = ' + json.dumps(price) + r''';
fetch = async (url, options) => { calls.push(JSON.parse(options.body));
  return reply({ok: false, error: 'payment_required', price}, 402); };
const vp = note(); await speakLazy(vp);
assert.equal(calls.length, 1); assert.equal(vp.children.length, 0);
assert.equal(vp.dataset.busy, undefined);
''')


def test_ui_declined_payment_and_changed_quote_never_silently_charge():
    run_js(r'''
let approve = false, confirmations = 0;
tg.showConfirm = (q, done) => { confirmations++; done(approve); };
fetch = async (url, options) => { calls.push(JSON.parse(options.body));
  return reply({ok: false, error: 'payment_required', price: calls.length > 2 ? 40 : 37}, 402); };
let vp = note(); await speakLazy(vp);
assert.equal(calls.length, 1); assert.equal(vp.children.length, 0);
approve = true; vp = note(); await speakLazy(vp);
assert.equal(calls.length, 3); assert.equal(confirmations, 2);
assert.equal(calls[2].quoted_price, 37);
assert.equal(vp.children.length, 0); // revised offer needs another explicit user action
''')


@pytest.mark.parametrize('stage', ['history', 'first_response', 'confirmation', 'paid_response'])
@pytest.mark.parametrize('stale', ['chat_changed', 'detached'])
def test_ui_stale_chat_or_removed_note_stops_after_every_await(stage, stale):
    run_js('const stage = ' + json.dumps(stage) + '; const stale = ' + json.dumps(stale) + r''';
const vp = note(stage === 'history' ? 0 : 41), gate = deferred(), entered = deferred();
const wait = async value => { entered.resolve(); await gate.promise; return value; };
tg.showConfirm = (q, done) => {
  if (stage === 'confirmation') wait(true).then(done); else done(true);
};
fetch = async (url, options) => {
  calls.push(options ? JSON.parse(options.body) : null);
  if (stage === 'history') return wait(reply({ok: true, history: [{id: 41, role: 'assistant', content: 'Stored reply'}]}));
  if (stage === 'first_response') return wait(reply(ready));
  if (calls.length === 1) return reply({ok: false, error: 'payment_required', price: 37}, 402);
  return wait(reply(ready));
};
const pending = speakLazy(vp); await entered.promise;
if (stale === 'chat_changed') CHAT = {id: 'girl_b'}; else vp.isConnected = false;
gate.resolve(); await pending;
assert.equal(calls.length, stage === 'paid_response' ? 2 : 1);
assert.equal(vp.children.length, 0); assert.equal(audios.length, 0);
assert.equal(vp.dataset.busy, undefined); assert.equal(vp.btn.textContent, '▶');
assert.equal(notices.length, 0);
''')


def test_ui_double_tap_does_not_make_a_second_reservation():
    run_js(r'''
const vp = note(), gate = deferred(), entered = deferred();
fetch = async (url, options) => { calls.push(JSON.parse(options.body)); entered.resolve(); return gate.promise; };
const pending = speakLazy(vp); await entered.promise;
await speakLazy(vp); assert.equal(calls.length, 1);
gate.resolve(reply(ready)); await pending;
assert.equal(vp.children.length, 1);
''')


def test_ui_fallback_matches_owned_assistant_history_not_arbitrary_text():
    run_js(r'''
fetch = async (url, options) => {
  calls.push({url, options});
  return reply({ok: true, history: [
    {id: 40, role: 'assistant', content: 'Stored reply'},
    {id: 41, role: 'assistant', content: 'THOUGHT: synthetic hidden\nMESSAGE: Stored reply'},
    {id: 42, role: 'user', content: 'Stored reply'},
    {id: 43, role: 'assistant', content: 'Different reply'}]});
};
const vp = note(0);
assert.equal(await speakSource(vp.msg, 'girl_a'), 41);
assert.equal(vp.msg.dataset.messageId, '41');
assert.match(calls[0].url, /character_id=girl_a/);
assert.equal(calls[0].options, undefined);
assert.equal(await speakSource(vp.msg, 'girl_a'), 41);
assert.equal(calls.length, 1);
vp.msg.dataset.messageId = '0'; vp.msg.getAttribute = () => 'Unstored text';
await speakLazy(vp);
assert.equal(calls.length, 2); assert.equal(vp.children.length, 0);
assert(calls.every(c => !c.url.includes('/speak')));
''')


def test_ui_fresh_reply_ids_and_history_ready_url_survive_rendering():
    run_js(r'''
insertChatReply({reply: 'Fresh reply', message_id: 41}, 'girl_a');
assert(painted[0].includes('data-message-id="41"'));
assert(painted[0].includes('data-character-id="girl_a"'));
assert(painted[0].includes('data-lazy="1"'));
const html = historyLine({id: 41, role: 'assistant', character_id: 'girl_a', content: 'Fresh reply',
  voice_part: 1, voices: [{part: 0, voice_id: 7, url: '/wrong.ogg'}, {...ready, part: 1}]});
assert(html.includes('data-message-id="41"'));
assert(html.includes('data-voice-part="1"'));
assert(html.includes('data-voice-id="8"'));
assert(html.includes('/webapp/media/synthetic.ogg?init_data=synthetic%26auth'));
assert(!html.includes('/wrong.ogg')); assert(!html.includes('data-lazy'));
CHAT = {id: 'girl_b'};
insertChatReply({reply: 'Stale reply', message_id: 42}, 'girl_a');
assert.equal(painted.length, 1);
''')


def test_ui_analytics_wait_for_actual_playback_and_deduplicate():
    run_js(r'''
const vp = note();
fetch = async (url, options) => { calls.push({url, body: JSON.parse(options.body)}); return reply(ready); };
await speakLazy(vp);
assert.equal(calls.length, 1); // play() call alone is not proof of audible playback
const au = vp.children[0];
emit('loadedmetadata', au); emit('pause', au); emit('play', au);
assert.equal(calls.length, 1); // loading or requesting play is not actual playback
emit('playing', au); emit('playing', au); emit('ended', au); emit('ended', au);
assert.deepEqual(calls.slice(1).map(c => c.body), [{voice_id: 8, event: 'play'}, {voice_id: 8, event: 'end'}]);
assert(calls.slice(1).every(c => c.url.includes('/speak/event?')));
assert.equal(au.currentTime, 0);
''')
