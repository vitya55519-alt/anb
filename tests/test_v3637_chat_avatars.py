"""V3.63.7: her small photo beside each of her messages in the app chat (WhatsApp-style)."""
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_every_bot_bubble_gets_her_avatar():
    i = SPA.index('function chatBubble(')
    body = SPA[i:SPA.index('function herAvatar()')]
    assert "const av = (cls === 'bot') ? herAvatar() : '';" in body
    assert "(av ? ' hav' : '')" in body


def test_avatar_uses_chat_photo_and_hides_on_error():
    i = SPA.index('function herAvatar()')
    body = SPA[i:i + 400]
    assert 'CHAT.duo' in body  # duo chats keep their per-line avatars
    assert "CHAT.photo || (CHAT.id ? '/webapp/photo/' + CHAT.id : '')" in body
    assert 'esc(src)' in body and "visibility" in body


def test_avatar_css_sits_left_of_bubble():
    assert '.msg.bot.hav { position: relative; margin-left: 36px;' in SPA
    assert '.msg .bav { position: absolute; left: -36px; bottom: 0;' in SPA


def test_voice_notes_use_the_telegram_style_player():
    assert "else if (m.media_kind === 'voice') body = cls === 'bot' ? body + voicePlayer(src) : voicePlayer(src);" in _js_function('chatBubble')
    player = _js_function('voicePlayer')
    assert 'function voicePlayer(src, text, voiceId)' in player and 'class="vp-wave"' in player
    assert "async function speakLazy(vp)" in SPA and "if (vp.dataset.lazy) { speakLazy(vp); return; }" in SPA
    # Media events don't bubble: all playback updates still use capture.
    # 'playing' was added for actual playback telemetry, not synthesis success.
    events = re.search(r"^(\[[^\n]*'timeupdate'[^\n]*\])\.forEach\(ev =>\n"
                       r"(.*?)\n  \}, (true|false)\)\);", SPA, re.M | re.S)
    assert events is not None and events[3] == 'true'
    assert {'loadedmetadata', 'durationchange', 'timeupdate', 'play', 'playing',
            'pause', 'ended'} <= set(re.findall(r"'([^']+)'", events[1]))
    assert "au.tagName !== 'AUDIO'" in events[2] and 'vpPaint(au)' in events[2]
    assert '<audio controls src=' not in SPA


def test_her_text_carries_a_voice_note_player():
    # Text keeps one player: lazy until generated, then its persistent ready
    # entitlement (for this part only), never a second synthesis after reload.
    assert '<button class="say sm">' not in SPA
    _run_chat_js(r'''
const m = { id: 17, character_id: 'anna', role: 'assistant',
  content: 'THOUGHT: private\nMESSAGE: public', voice_part: 1 };
const lazy = historyLine(m);
assert(lazy.includes('<div class="vp" data-lazy="1">'));
assert(!lazy.includes('<audio '));
const voices = [{ part: 0, url: '/wrong.ogg', voice_id: 50 },
                { part: 1, url: '/saved.ogg', voice_id: 51 }];
const ready = historyLine({ ...m, voices });
assert(ready.includes('<div class="vp" data-voice-id="51">'));
assert(ready.includes('<audio preload="metadata" src="/saved.ogg?init_data=auth%26test">'));
assert(!ready.includes('data-lazy=') && !ready.includes('/wrong.ogg'));
assert.equal(historyLine({ ...m, voices: [voices[0]] }), lazy);
for (const html of [lazy, ready]) {
  assert(html.includes('data-message-id="17"') && html.includes('data-character-id="anna"'));
  assert(html.includes('data-voice-part="1"') && html.includes('data-say="public"'));
  assert(!html.includes('private') && !html.includes('THOUGHT:'));
  assert.equal((html.match(/class="msg bot thcard/g) || []).length, 1);
  assert.equal((html.match(/class="vp"/g) || []).length, 1);
  assert(html.indexOf('public</div>') < html.indexOf('class="vp"'));
}
''')


def _node():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for frontend execution tests')
    return node


def _js_function(name):
    start = re.search(r'^(?:async )?function ' + name + r'\(', SPA, re.M).start()
    line_end = SPA.index('\n', start)
    end = line_end if SPA[start:line_end].rstrip().endswith('}') else SPA.index('\n}', start) + 2
    return SPA[start:end]


def _run_chat_js(checks):
    names = ('esc', 'fmtTime', 'parseThought', 'messageCard', 'sameChat', 'showRecording',
             'draftPlate', 'livePlate', 'eventActions', 'historyLine', 'afterDraft', 'chatBubble',
             'duoNames', 'playDuo', 'herAvatar', 'voicePlayer', 'vpFmt',
             'renderChatReply', 'insertChatReply', 'appendLiveTeaser')
    declarations = '\n'.join(_js_function(name) for name in names)
    declarations += '\n' + re.search(r'^const peachNum = .*;', SPA, re.M).group()
    declarations += '\n' + re.search(r'^const VP_BARS = .*;', SPA, re.M).group()
    setup = r'''
const assert = require('node:assert/strict');
let CHAT = { id: 'anna', name: 'Анна', photo: '/anna.jpg', custom: true };
let CHAT_LEVEL = null;
let ME = { premium: true };
const tg = { initData: 'auth&test' };
const L = { rec_voice: 'recording', typing_now: 'typing', pa_undress: 'undress',
  pa_anim: 'animate', photo_save: 'save', duo_together: 'together', duo_blur_btn: 'premium',
  draft_plate: n => n + ' erased a draft', draft_btn: p => 'read ' + p,
  draft_open: (n, t) => n + ': ' + t, live_btn: p => 'open ' + p };
const painted = [], timers = [];
const box = { insertAdjacentHTML: (_, html) => { if (html) painted.push(html); },
  scrollTop: 0, scrollHeight: 100 };
const document = { getElementById: id => id === 'chatMsgs' ? box : { remove() {} } };
const setTimeout = (done, ms) => timers.push({ done, ms });
const loadChatLevel = () => {};
const refreshPlotBar = () => {};
const renderGuest = () => {};
const undressTease = () => {};
const PP = () => 42;
const forkButtons = () => '<button data-branch="romance">romance</button>';
const reset = () => { painted.length = 0; timers.length = 0; };
'''
    source = setup + declarations + '\n(async () => {\n' + checks + '\n})().catch(e => { console.error(e); process.exitCode = 1; });'
    result = subprocess.run([_node(), '-'], input=source, text=True, encoding='utf-8',
                            capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_delayed_duo_reply_does_not_move_into_another_chat():
    _run_chat_js(r'''
const pending = playDuo([{name: 'Анна', text: 'Ответ только здесь'}]);
CHAT = {id: 'other', name: 'Другая'};
timers.shift().done();
await pending;
assert(!painted.some(html => html.includes('Ответ только здесь')));
''')


def test_event_actions_are_escaped_and_survive_photo_history():
    _run_chat_js(r'''
const msg = {id: 27, role: 'assistant', content: 'A story', media_kind: 'photo',
  media_url: '/webapp/media/test.jpg', actions: [
    {type: 'reply', label: '<img onerror=bad()>', text: '\" onclick=\"bad()'},
    {type: 'story_hook', label: 'Answer', story_key: 'confession', choice: 'a'},
    {type: 'callback', label: 'Danger', text: 'ignored'}]};
const html = historyLine(msg);
assert(html.includes('data-event-message="27"'));
assert(html.includes('data-event-index="1"'));
assert(html.includes('&lt;img onerror=bad()&gt;'));
assert(!html.includes('<img onerror=bad()>'));
assert(!html.includes('Danger'));
assert(!eventActions({...msg, role: 'user'}));
''')


def test_inline_javascript_syntax():
    scripts = re.findall(r'^\s*<script\b[^>]*>(.*?)</script\s*>', SPA, re.S | re.I | re.M)
    assert any(script.strip() for script in scripts)
    for script in scripts:
        if not script.strip():
            continue
        result = subprocess.run([_node(), '--check'], input=script, text=True,
                                encoding='utf-8', capture_output=True, timeout=20)
        assert result.returncode == 0, result.stderr


def test_only_message_sections_reach_her_text_and_tts():
    _run_chat_js(r'''
const cases = [
  ['обычный ответ\n\nвторой абзац', 'обычный ответ\n\nвторой абзац'],
  ['THOUGHT: private\nMESSAGE: public', 'public'],
  ['MESSAGE: public\nTHOUGHT: private', 'public'],
  ['private preamble\nTHOUGHT: private\nMESSAGE: public', 'public'],
  ['МЫСЛИ: private\nСООБЩЕНИЕ: public', 'public'],
  ['thought: private message: public', 'public'],
  ['THOUGHT: private', ''],
  ['THOUGHT: private\nMESSAGE: ', ''],
  ['MESSAGE: public\nTHOUGHT: private\nMESSAGE: more', 'public\n\nmore'],
  ['MESSAGE: <b>public</b>', '<b>public</b>']
];
for (const [raw, expected] of cases) {
  assert.equal(parseThought(raw).message, expected);
  const m = { id: 1, role: 'assistant', content: raw, novel: true };
  const html = historyLine(m);
  assert.equal(m.content, raw);
  assert(!html.includes('private'));
  assert(!html.includes('THOUGHT:'));
  if (!expected) { assert.equal(html, ''); continue; }
  assert(html.includes('<div class="th-b">' + esc(expected) + '</div>'));
  assert(html.includes('data-say="' + esc(expected) + '"'));
  assert.equal((html.match(/class="msg bot thcard/g) || []).length, 1);
  assert.equal((html.match(/class="vp"/g) || []).length, 1);
}
''')


def test_history_events_and_new_replies_share_one_immediate_pink_message():
    _run_chat_js(r'''
const raw = 'THOUGHT: private\nMESSAGE: Первый абзац\n\nВторой абзац';
const m = { id: 1, role: 'assistant', content: raw };
const expected = historyLine(m);
assert.equal(chatBubble({ ...m, role: 'bot', ts: null }), expected);
assert(expected.includes('data-message-id="1"') && expected.includes('data-character-id="anna"'));
renderChatReply({ reply: raw, message_id: m.id }, 'anna');
assert.deepEqual(painted, [expected]);
assert.equal(timers.length, 0);
assert(expected.includes('<div class="th-h">&#128173; Анна</div>'));
assert(expected.includes('Первый абзац\n\nВторой абзац'));
assert(!expected.includes('Мысли') && !expected.includes('th-t'));
assert(expected.indexOf('class="th-b"') < expected.indexOf('class="vp"'));
reset();
insertChatReply({ reply: raw, message_id: m.id }, 'anna');
assert.deepEqual(painted, [expected]);
reset();
// A teaser's id is not a persisted Message.id. Its unsourced bubble must
// still match the full rendering of an equivalent unsourced history item.
const teaserMessage = historyLine({ role: 'assistant', content: raw });
assert(teaserMessage.includes('data-message-id="0"'));
appendLiveTeaser({ id: 8, text: raw, thought: 'MESSAGE: private', price: 1234 });
assert.deepEqual(painted, [teaserMessage, livePlate({ id: 8, price: 1234 })]);
assert(!painted.join('').includes('private'));
assert.equal(timers.length, 0);
CHAT.name = '<img src=x>';
assert(chatBubble('bot', 'safe').includes('&lt;img src=x&gt;</div>'));
assert(!chatBubble('bot', 'safe').includes('<img src=x>'));
''')


def test_chat_previews_hide_old_thoughts_but_leave_user_text_unchanged():
    _run_chat_js(_js_function('fmtDay') + '\n' + _js_function('renderChats') + r'''
document.getElementById = () => box;
box.querySelectorAll = () => [];
const raw = 'THOUGHT: private\nMESSAGE: public';
renderChats([{ id: 'anna', name: 'Анна', last_role: 'assistant', last_message: raw }]);
assert(box.innerHTML.includes('<div class="prev">public</div>'));
assert(!box.innerHTML.includes('private'));
renderChats([{ id: 'anna', name: 'Анна', last_role: 'user', last_message: raw }]);
assert(box.innerHTML.includes(esc(raw)));
''')


def test_voice_replies_keep_text_above_one_player_including_history():
    _run_chat_js(r'''
const raw = 'THOUGHT: private\nMESSAGE: public\n\nmore';
const m = { id: 2, role: 'assistant', content: raw, media_kind: 'voice', media_url: '/voice.ogg' };
const expected = historyLine(m);
renderChatReply({ reply: raw, message_id: m.id, voice_url: '/voice.ogg' }, 'anna');
assert.deepEqual(painted, [expected]);
assert.equal(timers.length, 0);
assert(expected.includes('class="msg bot thcard hav"'));
assert(expected.indexOf('public\n\nmore</div>') < expected.indexOf('class="vp"'));
assert.equal((expected.match(/class="vp"/g) || []).length, 1);
assert(expected.includes('/voice.ogg?init_data=auth%26test'));
assert(!expected.includes('private') && !expected.includes('data-say=') && !expected.includes('data-lazy='));
const empty = chatBubble({ ...m, content: 'THOUGHT: private' });
assert(empty.includes('<audio ') && !empty.includes('private') && !empty.includes('class="th-b"'));
const user = chatBubble({ ...m, role: 'user' });
assert(user.includes('class="msg user"') && !user.includes('thcard'));
assert(user.includes(raw) && user.indexOf('class="vp"') < user.indexOf(raw));
assert(!user.includes('data-message-id=') && !user.includes('data-character-id='));
assert(!user.includes('data-voice-part=') && !user.includes('data-say='));
''')


def test_photos_actions_user_messages_and_forks_are_preserved():
    _run_chat_js(r'''
const raw = 'THOUGHT: private\nMESSAGE: caption';
for (const kind of ['photo', 'hot', 'cosplay', 'room']) {
  const html = historyLine({ id: 3, role: 'assistant', content: raw, media_kind: kind, media_url: '/photo.jpg' });
  assert(html.startsWith('<div class="msg bot hav"'));
  assert.equal((html.match(/<img class="m"/g) || []).length, 1);
  assert(html.includes('data-lb="1"'));
  assert(html.indexOf('<img class="m"') < html.indexOf('class="phact"'));
  assert(html.indexOf('class="phact"') < html.indexOf('class="thcard"'));
  assert(html.includes('data-pact="animate"') && !html.includes('private'));
  assert.equal(html.includes('data-pact="undress"'), kind !== 'room');
  assert(!html.includes('class="vp"'));
}
const user = chatBubble('user', raw, null);
assert.equal(user, '<div class="msg user">' + esc(raw) + '</div>');
const userPhoto = chatBubble({ role: 'user', content: raw, media_kind: 'photo', media_url: '/mine.jpg' });
assert(userPhoto.includes('data-dl=') && userPhoto.includes(raw) && !userPhoto.includes('thcard'));
const fork = chatBubble({ role: 'assistant', content: 'choice', media_kind: 'fork', ts: '2026-11-11T12:00:00Z' });
assert(fork.includes('data-branch="romance"') && fork.includes('class="t"'));
CHAT.guest = { name: 'Агата', photo: '/agata.jpg' };
assert(chatBubble({ role: 'bot', media_kind: 'photo', media_url: '/joint.jpg' }).includes('data-duojoint="1"'));
const teaser = chatBubble({ role: 'bot', media_kind: 'duo_teaser', media_url: '/blur.jpg' });
assert(teaser.includes('data-duobuy="1"') && !teaser.includes('data-pact=') && !teaser.includes('data-dl='));
''')


def test_draft_live_plates_and_wrong_chat_guards_survive():
    _run_chat_js(r'''
const raw = 'THOUGHT: private\nMESSAGE: public';
const draft = { id: 7, price: 1234, text: 'unpaid secret' };
const m = { id: 7, role: 'assistant', content: raw, draft };
const expected = draftPlate(draft) + chatBubble({ ...m, role: 'bot', ts: null });
assert.equal(historyLine(m), expected);
assert(!expected.includes('unpaid secret') && !expected.includes('private'));
assert(expected.includes('data-draft="7"') && expected.includes('1\u00a0234'));
renderChatReply({ reply: raw, message_id: m.id, draft }, 'anna');
assert.deepEqual(timers.map(t => t.ms), [4000]);
assert(!painted.join('').includes('public'));
timers.shift().done();
assert.equal(painted.slice(1).join(''), expected);
assert.equal(timers.length, 0);
const paid = historyLine({ ...m, draft: { paid: true, text: '<paid draft>' }, live: { id: 9, price: 4321 } });
assert(paid.includes('&lt;paid draft&gt;') && !paid.includes('data-draft='));
assert(paid.indexOf('data-lplate="9"') < paid.indexOf('data-dplate="7"'));
assert(paid.indexOf('data-dplate="7"') < paid.indexOf('class="msg bot thcard'));
assert.equal(livePlate({ id: 9, paid: true }), '');
reset();
renderChatReply({ reply: raw }, 'other');
insertChatReply({ reply: raw, voice_url: '/voice.ogg' }, 'other');
assert.equal(painted.length, 0);
assert.equal(timers.length, 0);
renderChatReply({ reply: raw, message_id: m.id, draft }, 'anna');
const count = painted.length;
CHAT = { id: 'other', name: 'Other' };
timers.shift().done();
assert.equal(painted.length, count);
''')


def test_duo_names_avatars_and_voice_order_survive():
    _run_chat_js(r'''
CHAT.duo = 'Агата';
CHAT.guest = { name: 'Агата', photo: '/agata.jpg' };
const raw = 'THOUGHT: private\nMESSAGE: Анна: привет\nАгата: и я тут';
for (const voice of [false, true]) {
  const html = historyLine({ id: 9, role: 'assistant', content: raw,
    media_kind: voice ? 'voice' : null, media_url: voice ? '/duo.ogg' : null });
  assert(html.includes('<b class="duo-nm">Анна:</b>'));
  assert(html.includes('<b class="duo-nm">Агата:</b>'));
  assert.equal((html.match(/class="duo-av"/g) || []).length, 2);
  assert(!html.includes('private') && !html.includes('class="th-h"') && !html.includes('class="bav"'));
  assert(html.indexOf('и я тут') < html.indexOf('class="vp"'));
}
const playing = playDuo([{ name: 'Агата', text: 'THOUGHT: private\nMESSAGE: гостевой ответ', voice_url: '/guest.ogg' }]);
timers.shift().done();
await playing;
const html = painted.at(-1);
assert(html.includes('<b class="duo-nm">Агата:</b> гостевой ответ'));
assert(html.indexOf('гостевой ответ') < html.indexOf('class="vp"'));
assert(!html.includes('private'));
''')
