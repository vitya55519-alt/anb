"""V3.145.0 — owner ТЗ: the daily push must not land as three bubbles in one
second. Her words go under the photo, the voice note follows a few seconds
later while he sees «Анна записывает голосовое…», and nothing is pinned.

Static pins keep the shape of the send (the scheduler is impossible to run for
real in a test); the two live tests drive _ritual_voice with a fake bot, so the
order status → pause → send is proven, not just written down.
"""
import asyncio
import time
from pathlib import Path

from services import scheduler_service as ss

ROOT = Path(__file__).resolve().parents[1]
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
HYGIENE = (ROOT / 'services' / 'chat_hygiene.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')

RITUALS = SCHED[SCHED.index('async def _rituals(bot, only_tg=None, force_kind=None):'):
                SCHED.index('async def _donation_reminder(bot):')]
VOICE = SCHED[SCHED.index('async def _ritual_voice('):SCHED.index('async def _rituals(')]
# the delivery branch: photo with her words first, the voice note behind it
BRANCH = RITUALS[RITUALS.index('if ritual_voice:'):RITUALS.index('elif shot:')]


# ── glue: photo + text are one message ─────────────────────────────────────
def test_her_words_live_under_the_photo():
    for method in ('send_animation', 'send_video', 'send_photo'):
        lines = [ln.strip() for ln in BRANCH.splitlines() if f'await bot.{method}(' in ln]
        assert len(lines) == 1, method
        assert 'caption=_ev.caption(text)' in lines[0], method
        assert 'reply_markup=markup' in lines[0], method
    # and the text never becomes a third bubble of its own
    assert 'send_message' not in BRANCH


def test_the_voice_does_not_repeat_what_the_photo_already_said():
    assert BRANCH.count('voice_caption, voice_markup = _ev.caption(text), markup') == 1
    assert BRANCH.index('voice_caption=voice_markup=None') < BRANCH.index('if shot:')
    # the no-photo branch is the only one handing the words + the gift button
    # to the voice note
    tail = BRANCH[BRANCH.rindex('else:'):]
    assert 'voice_caption, voice_markup = _ev.caption(text), markup' in tail
    assert '_send_later(_ritual_voice(' in tail
    assert 'caption=voice_caption, markup=voice_markup' in BRANCH


# ── timings: «записывает голосовое», then the note ─────────────────────────
def test_the_voice_note_follows_the_record_status():
    send = VOICE.index('await bot.send_voice(int(tg_id), BufferedInputFile(ritual_voice')
    assert VOICE.index("await bot.send_chat_action(int(tg_id), action='record_voice')") < send
    assert VOICE.index('await asyncio.sleep(RITUAL_VOICE_HOLD_SECONDS)') < send
    assert RITUALS.index('_send_later(_ritual_voice(') > RITUALS.index('await bot.send_photo')


def test_the_hold_is_the_owner_s_four_seconds_and_a_knob():
    assert ss.RITUAL_VOICE_HOLD_SECONDS == 4
    assert "float(_os.getenv('RITUAL_VOICE_HOLD_SECONDS', '4'))" in SCHED


def test_the_pause_never_parks_the_scan():
    # a literal `await` here would add 4 s per user and the whole audience
    # would stop fitting into the morning window — the note is its own task
    assert 'await _ritual_voice(' not in RITUALS
    assert '_send_later(_ritual_voice(' in RITUALS
    assert 'asyncio.create_task(coro)' in SCHED
    assert SCHED.count('_pending_voices') >= 3  # kept referenced until done


def test_the_status_failure_still_delivers_the_voice():
    class _NoStatus:
        def __init__(self):
            self.sent = []

        async def send_chat_action(self, chat_id, action=None, **kw):
            raise RuntimeError('no status for you')

        async def send_voice(self, chat_id, voice, **kw):
            self.sent.append(kw.get('caption'))

    bot = _NoStatus()
    asyncio.run(ss._ritual_voice(bot, 777, 'anna_01', b'ogg'))
    assert bot.sent == [None]


def test_live_he_sees_her_recording_before_the_note_lands(monkeypatch):
    monkeypatch.setattr(ss, 'RITUAL_VOICE_HOLD_SECONDS', 0.2)

    class _Bot:
        def __init__(self):
            self.calls = []

        async def send_chat_action(self, chat_id, action=None, **kw):
            self.calls.append(('status', chat_id, action))

        async def send_voice(self, chat_id, voice, **kw):
            self.calls.append(('voice', chat_id, kw.get('caption'), kw.get('reply_markup')))

    bot = _Bot()
    started = time.monotonic()
    asyncio.run(ss._ritual_voice(bot, 4242, 'anna_01', b'ogg', caption='утро ☀️', markup='KB'))
    held = time.monotonic() - started
    assert [c[0] for c in bot.calls] == ['status', 'voice']
    assert bot.calls[0][2] == 'record_voice'
    assert bot.calls[1] == ('voice', 4242, 'утро ☀️', 'KB')
    assert 0.2 <= held < 2  # the pause is real, and it is the pause, not a hang


# ── no auto-pins on pushes ─────────────────────────────────────────────────
def test_no_push_rail_pins_anything():
    for rail in ('async def _rituals(', 'async def _proactive(', 'async def _life_events(',
                 'async def _reminders(', 'async def _ritual_voice('):
        body = SCHED[SCHED.index(rail):SCHED.index(rail) + 12000]
        assert 'pin_chat_message' not in body, rail
    assert 'pin_chat_message' not in SCHED and 'unpin_all_chat_messages' not in SCHED


def test_the_only_pin_left_is_the_muted_main_menu():
    # the menu is what the owner pinned on purpose: one per chat, no sound,
    # and the «бот закрепил сообщение» line is deleted right after it.
    assert 'await bot.pin_chat_message(chat_id, message_id, disable_notification=True)' in HYGIENE
    assert HYGIENE.count('pin_chat_message') == 1
    assert HYGIENE.count('unpin_all_chat_messages') == 1
    assert 'await chat_hygiene.pin_menu(bot, chat_id, message_id)' in MAIN
