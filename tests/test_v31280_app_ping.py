"""V3.128.0: she wrote in the app while he was away — a ping in the bot chat."""
import asyncio
from pathlib import Path

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


def _patch(monkeypatch, lang='ru'):
    monkeypatch.setattr(app_ping, 'APP_PING_DELAY_SECONDS', 0)
    monkeypatch.setattr(app_ping, '_user_ctx', lambda tg: {'uid': 1, 'lang': lang, 'tz': 'UTC'})
    monkeypatch.setattr(app_ping, '_character_name', lambda cid: 'Аня')
    monkeypatch.setattr(app_ping, '_quiet_now', lambda tz: False)
    monkeypatch.setattr(app_ping, '_read_since', lambda tg, cid, iso: False)


async def _drain():
    for _ in range(5):
        await asyncio.sleep(0)
    if app_ping._tasks:
        await asyncio.gather(*list(app_ping._tasks))


def test_preview_drops_stage_directions_and_cuts_on_word():
    assert app_ping.preview('*улыбаюсь* ну привет, где ты был?') == 'ну привет, где ты был?'
    long = 'слово ' * 60
    out = app_ping.preview(long)
    assert out.endswith('…') and len(out) <= app_ping.PREVIEW_CHARS + 1


def test_ping_text_ru_en_photo_and_collapse():
    t = app_ping.ping_text('Аня', 'скучаю', None, 2, 'ru')
    assert 'Аня написала тебе в приложении' in t and '«скучаю»' in t and 'и ещё 2' in t
    p = app_ping.ping_text('Аня', '📸', 'photo', 0, 'ru')
    assert 'прислала тебе фото' in p and '«' not in p
    e = app_ping.ping_text('Anna', 'miss you', None, 0, 'en')
    assert 'wrote to you in the app' in e


def test_presence_heartbeat_and_away():
    _reset()
    assert not app_ping.in_app(5)                                  # never heard from
    app_ping.touch(5, now=100.0)
    assert app_ping.in_app(5, now=110.0)
    assert not app_ping.in_app(5, now=100.0 + app_ping.APP_PRESENCE_SECONDS + 1)
    app_ping.touch(5, away=True, now=120.0)
    assert not app_ping.in_app(5, now=121.0)


def test_the_wait_decides_not_the_moment_her_answer_lands(monkeypatch):
    """V3.162.0: owner — «она пишет. я выхожу, мне ничего не приходит». He
    closes the app a second after his own message, so presence read at that
    moment was always «still in the app» and the ping died before it began."""
    _reset()
    _patch(monkeypatch)
    bot = FakeBot()

    async def run():
        assert app_ping.note(bot, 7, 'anna_01', 'привет')          # no heartbeat at all: pinged
        app_ping.touch(11)                                         # heartbeat alive: he is reading
        assert app_ping.note(bot, 11, 'anna_01', 'привет')
        await _drain()
    asyncio.run(run())
    assert [c for c, *_ in bot.sent] == [7]


def test_away_user_gets_one_collapsed_ping_with_deep_link(monkeypatch):
    _reset()
    _patch(monkeypatch)
    monkeypatch.setattr('config.PUBLIC_BASE_URL', 'https://x.test', raising=False)
    bot = FakeBot()

    async def run():
        app_ping.touch(8, away=True)
        assert app_ping.note(bot, 8, 'anna_01', 'первое')
        assert app_ping.note(bot, 8, 'anna_01', '*смеюсь* второе')
        await _drain()
    asyncio.run(run())
    assert len(bot.sent) == 1
    chat_id, text, markup, quiet = bot.sent[0]
    assert chat_id == 8 and '«второе»' in text and 'и ещё 1' in text and quiet is False
    btn = markup.inline_keyboard[0][0]
    assert btn.web_app.url.endswith('/webapp?open=chat&char=anna_01')


def test_cooldown_and_daily_cap(monkeypatch):
    _reset()
    assert app_ping.limits_ok(9, now=1000.0)
    app_ping._count_ping(9, now=1000.0)
    assert not app_ping.limits_ok(9, now=1000.0 + 60)
    assert app_ping.limits_ok(9, now=1000.0 + app_ping.APP_PING_COOLDOWN_MINUTES * 60 + 1)
    app_ping._day_count[9] = (app_ping._today(), app_ping.APP_PING_MAX_PER_DAY)
    assert not app_ping.limits_ok(9, now=10 ** 9)


def test_back_in_app_before_the_wait_cancels(monkeypatch):
    _reset()
    _patch(monkeypatch)
    bot = FakeBot()

    async def run():
        app_ping.touch(10, away=True)
        assert app_ping.note(bot, 10, 'anna_01', 'ау')
        app_ping.touch(10)  # he came back during the wait
        await _drain()
    asyncio.run(run())
    assert bot.sent == []


def test_hooks_and_spa_wiring():
    assert "app.router.add_post('/webapp/api/presence', _webapp_api_presence)" in MAIN
    assert '@_pings_app_reply' in MAIN
    assert MAIN.count('_app_ping(telegram_id, character_id') >= 6
    assert '/webapp/api/presence?state=' in HTML and 'sendBeacon' in HTML
    assert "tg.onEvent('deactivated'" in HTML
    assert "sp.get('char')" in HTML
