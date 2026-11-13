"""V3.164.0 — owner ТЗ of 13 Nov 2026, two screenshots of the Mini App chat.

1. «Кнопка скачет… убери из чата кнопку позвать друга». The referral CTA was
   appended after every delivered photo, video and circle and never after a
   voice note, so the same dialog had it on one bubble and not on the next.
   It is gone from the chat; the gallery tile and the partner screen keep it.
2. «Модель ответила мне в мини-апп, а я вышел — оповещение в бот не пришло».
   Presence was the killer: a Telegram webview he only minimized keeps sending
   its 20-second heartbeat, so at the moment of delivery the bot still believed
   he was reading and threw the note away. Now being in the app only postpones
   the ping — the «away» beacon releases it — and the only thing that cancels
   one is proof he really saw the line: the SPA's «seen» ack for that dialog.
"""
import asyncio
import os
from pathlib import Path

os.environ.setdefault('TELEGRAM_TOKEN', '123456:test-fake-token-for-static-tests-only')
os.environ.setdefault('GEMINI_API_KEY', 'x')

from services import app_ping

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
HTML = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None, disable_notification=None):
        self.sent.append((chat_id, text, reply_markup, disable_notification))


def _reset():
    for d in (app_ping._presence, app_ping._pending, app_ping._last_ping, app_ping._day_count,
              app_ping._seen):
        d.clear()
    app_ping._armed.clear()
    app_ping._sending.clear()


def _patch(monkeypatch):
    monkeypatch.setattr(app_ping, 'APP_PING_DELAY_SECONDS', 0)
    monkeypatch.setattr(app_ping, '_user_ctx', lambda tg: {'uid': 1, 'lang': 'ru', 'tz': 'UTC'})
    monkeypatch.setattr(app_ping, '_character_name', lambda cid: 'Агата')
    monkeypatch.setattr(app_ping, '_quiet_now', lambda tz: False)
    monkeypatch.setattr(app_ping, '_read_since', lambda tg, cid, iso: False)


async def _drain():
    for _ in range(5):
        await asyncio.sleep(0)
    if app_ping._tasks:
        await asyncio.gather(*list(app_ping._tasks))


# ── 1. the invite button left the dialog ─────────────────────────────────
def test_the_chat_never_appends_the_referral_button():
    assert 'class="gencta"' not in HTML
    assert '.gencta' not in HTML
    assert 'invite_cta' in HTML                       # the string itself stays
    assert "id=\"galInvite\"" in HTML                 # the gallery keeps its CTA


# ── 2. presence postpones, it no longer cancels ──────────────────────────
def test_being_in_the_app_postpones_the_ping_and_the_exit_delivers_it(monkeypatch):
    _reset()
    _patch(monkeypatch)
    bot = FakeBot()

    async def run():
        app_ping.touch(21)                            # he is on screen
        assert app_ping.note(bot, 21, 'agata_01', 'лови фотку')
        await _drain()
        assert bot.sent == []                         # nothing was thrown away…
        assert app_ping._pending.get(21)              # …it waits for him to leave
        app_ping.touch(21, away=True)                 # he closes the app
        assert app_ping.flush(bot, 21)
        await _drain()
    asyncio.run(run())
    assert [c for c, *_ in bot.sent] == [21]
    assert 'Агата написала тебе в приложении' in bot.sent[0][1]
    assert not app_ping._pending.get(21)


def test_a_second_message_while_waiting_re_arms_and_still_goes(monkeypatch):
    _reset()
    _patch(monkeypatch)
    bot = FakeBot()

    async def run():
        app_ping.touch(22)
        assert app_ping.note(bot, 22, 'agata_01', 'первое')
        await _drain()                                # the waiter saw him in the app
        assert bot.sent == [] and app_ping._pending.get(22)
        app_ping.touch(22, away=True)
        assert app_ping.note(bot, 22, 'agata_01', 'второе')   # collapses + re-arms
        await _drain()
    asyncio.run(run())
    assert [c for c, *_ in bot.sent] == [22]
    assert '«второе»' in bot.sent[0][1] and 'и ещё 1' in bot.sent[0][1]


def test_the_seen_ack_is_what_cancels_a_ping(monkeypatch):
    """He read her line in the app — the bot stays silent, and the messages are
    not left waiting to be delivered after his next exit."""
    _reset()
    _patch(monkeypatch)
    bot = FakeBot()

    async def run():
        app_ping.touch(23, away=True)
        assert app_ping.note(bot, 23, 'agata_01', 'ну как ты?')
        app_ping.seen(23, 'agata_01')
        await _drain()
    asyncio.run(run())
    assert bot.sent == []
    assert not app_ping._pending.get(23)


def test_an_ack_for_another_dialog_does_not_silence_her(monkeypatch):
    _reset()
    _patch(monkeypatch)
    bot = FakeBot()

    async def run():
        app_ping.touch(24, away=True)
        assert app_ping.note(bot, 24, 'agata_01', 'скучаю')
        app_ping.seen(24, 'marina_01')
        await _drain()
    asyncio.run(run())
    assert [c for c, *_ in bot.sent] == [24]


def test_a_wait_older_than_the_ttl_is_dropped(monkeypatch):
    """A note about a line from half an hour ago reads as a bug, not a reminder."""
    _reset()
    _patch(monkeypatch)
    bot = FakeBot()

    async def run():
        app_ping.touch(25)
        assert app_ping.note(bot, 25, 'agata_01', 'скучаю')
        app_ping._pending[25]['at'] -= app_ping.APP_PING_PENDING_TTL_SECONDS + 1
        assert await app_ping._deliver(bot, 25) == 'stale'
    asyncio.run(run())
    assert bot.sent == [] and not app_ping._pending.get(25)


def test_deliver_answers_with_the_reason(monkeypatch):
    _reset()
    _patch(monkeypatch)
    bot = FakeBot()

    async def run():
        app_ping.touch(26)
        assert await app_ping._deliver(bot, 26) == 'empty'
        assert app_ping.note(bot, 26, 'agata_01', 'ау')
        assert await app_ping._deliver(bot, 26) == 'in_app'
        app_ping.touch(26, away=True)
        assert await app_ping._deliver(bot, 26) == 'sent'
        assert await app_ping._deliver(bot, 26) == 'empty'
    asyncio.run(run())
    assert len(bot.sent) == 1


# ── wiring ───────────────────────────────────────────────────────────────
def test_the_away_beacon_releases_what_is_waiting():
    presence = MAIN.split('async def _webapp_api_presence')[1].split('\nasync def ')[0]
    assert "state == 'seen'" in presence
    assert 'app_ping.seen(int(telegram_id)' in presence
    assert 'app_ping.flush(bot, int(telegram_id))' in presence
    assert 'app_ping.touch(int(telegram_id), away=away)' in presence


def test_the_spa_acks_the_bubbles_he_actually_sees():
    assert 'function pingSeen()' in HTML
    assert "'/webapp/api/presence?state=seen&char='" in HTML
    assert 'function seenObserver()' in HTML
    assert "observe(box, { childList: true })" in HTML


def test_the_ping_state_is_documented_as_postpone_not_discard():
    src = (ROOT / 'services' / 'app_ping.py').read_text(encoding='utf-8')
    assert 'APP_PING_PENDING_TTL_SECONDS' in src
    assert "logger.info('app ping waiting user=%s reason=in_app', tg)" in src
    assert "logger.info('app ping cancelled user=%s reason=already_read', tg)" in src


# ── 3. the owner's question: three photos in a row — admin or bug? ───────
def test_every_free_photo_wall_sits_behind_the_admin_check():
    """Not a bug: an id in ADMIN_TELEGRAM_IDS is never gated, so she can send
    him photo after photo. A free man hits the wall after his one photo a day."""
    gate = MAIN.split('def _chat_photo_gate(')[1].split('\ndef ')[0]
    assert 'if telegram_id not in ADMIN_TELEGRAM_IDS:' in gate
    assert "return 'free_used'" in gate
    pool = MAIN.split('def _free_photo_from_pool(')[1].split('\ndef ')[0]
    assert 'if telegram_id in ADMIN_TELEGRAM_IDS:' in pool
