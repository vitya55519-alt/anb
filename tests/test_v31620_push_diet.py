# V3.162.0 — пуш-диета по словам владельца: «два пуша всего в день, не надо
# вот эти остальные херачить» и «короче, сделай текст». Живой человек получает
# её обычную фразу («привет, как спалось?» / «как прошёл день?») на своём язы-
# ке и кнопку, которая открывает диалог с ЕГО героиней в Mini App. Фото, голо-
# совое, прогноз совместимости, «что нового», «не прерывай серию», донат-пины и
# «жизнь без тебя» людям больше не пишут.

import asyncio
import datetime as dt
from pathlib import Path

import pytest
from config import MARKETING_PUSH_ENABLED, PUSH_MAX_PER_DAY, PUSH_RAILS
from models.app_models import ProductEvent
from services import push_governor as pg
from services import scheduler_service as ss
from services.db import SessionLocal
from services.ui_lang import APP_LANGS, RITUAL_LINES, flow_text, ritual_line
from services.user_service import ensure_user

ROOT = Path(__file__).resolve().parents[1]
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')

JUNK_JOBS = ('proactive', 'day1_hook', 'first_offer', 'trial_followup', 'heavy_offer', 'whats_new',
             'paid_day1', 'renewal_care', 'first_minutes', 'scenario_cards', 'donation_reminder',
             'partner_nudge', 'random_gifts', 'daily_compatibility', 'daily_gift', 'life_events')


def _events(uid: int, names, when=None) -> None:
    with SessionLocal() as s:
        for n in names:
            s.add(ProductEvent(user_id=uid, character_id='anna_01', event_name=n, value=0.0,
                               created_at=when or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None),
                               metadata_json='{}'))
        s.commit()


def test_two_a_day_and_the_noise_rails_are_off():
    # V3.167.0 (owner «разрешаю по пушам»): the marketing bucket stays at two,
    # the master flag is on again, and the rails the 13.11 dump condemned are
    # simply not named in the default list.
    # V3.167.12: heavy_offer belongs to the offers the owner asked to send more
    # often, not to the condemned noise — it now runs, behind the same gate.
    assert PUSH_MAX_PER_DAY == 2
    assert MARKETING_PUSH_ENABLED is True
    assert not {'partner_nudge', 'daily_compatibility', 'whats_new', 'random_gifts',
                'donation_reminder'} & PUSH_RAILS
    # The existing 1/2/3/7-day ladder is enabled, without widening marketing's cap.
    assert {'proactive', 'first_offer', 'heavy_offer'} <= PUSH_RAILS
    assert {'life_events', 'rituals', 'day1_hook', 'daily_gift',
            'scenario_cards', 'first_minutes'} <= PUSH_RAILS


def test_each_rail_family_spends_its_own_day(monkeypatch):
    # V3.162.0 counted every first write in one bucket, so 2149 «жизнь без тебя»
    # drank her morning and evening line dry. V3.167.0: the budgets are split —
    # a full life day says nothing about the ritual day.
    from services.db import init_db
    init_db()
    uid = ensure_user(771620001, 'Тест')
    monkeypatch.setattr(pg, 'local_hour', lambda tz: 12)
    monkeypatch.setattr(pg, 'PUSH_SPACING_WINDOW_MINUTES', 0)   # only the day caps
    assert pg.allow_push(uid, 'Europe/Moscow', 'ritual') == (True, '')
    _events(uid, ['ritual_morning_sent', 'ritual_evening_sent', 'morning_voice_sent'])
    assert pg.pushes_today(uid, 'Europe/Moscow', 'ritual') == 3
    assert pg.allow_push(uid, 'Europe/Moscow', 'ritual') == (False, 'daily')
    # her two lines are out, and the marketing rails are untouched by that
    assert pg.pushes_today(uid, 'Europe/Moscow', 'marketing') == 0
    assert pg.allow_push(uid, 'Europe/Moscow', 'marketing') == (True, '')
    # the life rail pays with its own money too (LIFE_EVENTS_MAX_PER_DAY)
    assert pg.rail_budget('life') == 4
    _events(uid, ['life_event_sent'] * 4)
    assert pg.allow_push(uid, 'Europe/Moscow', 'life') == (False, 'daily')


def test_a_refusal_names_the_rail_and_the_man(caplog, monkeypatch):
    # V3.167.0 п.1.3: «held back» must be tellable apart from «the job never ran».
    import logging
    from services.db import init_db
    init_db()
    uid = ensure_user(771620006, 'Тест')
    # час заморожен: в тишину (23→7) отказ называется «night», и тест проверял
    # бы не дневной кап, а стенные часы
    monkeypatch.setattr(pg, 'local_hour', lambda tz: 12)
    with caplog.at_level(logging.INFO, logger='services.push_governor'):
        pg.allow_push(uid, 'Europe/Moscow', 'scenario')
        _events(uid, ['scenario_card_sent'] * pg.rail_budget('scenario'))
        assert pg.allow_push(uid, 'Europe/Moscow', 'scenario') == (False, 'daily')
    held = [r.getMessage() for r in caplog.records if 'push held' in r.getMessage()]
    assert any(f'user={uid}' in line and 'rail=scenario' in line and 'reason=daily' in line
               for line in held), held


def test_the_day_is_his_not_the_servers():
    from zoneinfo import ZoneInfo
    start = pg._local_day_start('Asia/Kolkata')
    expect = dt.datetime.now(ZoneInfo('Asia/Kolkata')).replace(
        hour=0, minute=0, second=0, microsecond=0).astimezone(dt.timezone.utc).replace(tzinfo=None)
    assert abs((start - expect).total_seconds()) < 5
    assert pg._local_day_start('Mars/Olympus') == pg._local_day_start('Africa/Abidjan')


@pytest.mark.parametrize('kind', ('morning', 'evening'))
def test_her_lines_exist_in_every_app_language(kind):
    for lang in APP_LANGS:
        lines = RITUAL_LINES[lang][kind]
        assert len(lines) >= 4, (lang, kind)
        assert all(4 < len(l) < 90 for l in lines), (lang, kind, lines)
        assert ritual_line(kind, lang) in lines
    assert ritual_line(kind, 'de') in RITUAL_LINES['en'][kind]   # unknown → English
    assert flow_text('bn', 'open_chat') != flow_text('ru', 'open_chat')


@pytest.fixture
def ritual_user(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.app_models import Base, User
    from services import analytics_service, memory_service

    # only_tg selects the owner media-preview path, not the ordinary text path.
    # Give the real scan its own DB instead of scanning other tests' users.
    engine = create_engine('sqlite:///' + (tmp_path / 'ritual.sqlite').as_posix(),
                           connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    for module in (ss, memory_service, analytics_service):
        monkeypatch.setattr(module, 'SessionLocal', sessions)
    tid = 771620002
    with sessions() as s:
        user = User(telegram_id=str(tid), name='Test', proactive_enabled=True,
                    notify_rituals=True, timezone='UTC', selected_character='anna_01',
                    ui_lang='ru', chat_lang='ru',
                    last_active_at=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
        s.add(user)
        s.commit()
        uid = user.id
    try:
        yield tid, uid, sessions
    finally:
        engine.dispose()


def test_ritual_lands_in_history_and_only_a_generic_note_opens_her_dialog(monkeypatch, ritual_user):
    import config
    from services import app_ping, ui_lang, webapp_service

    tid, uid, sessions = ritual_user
    sent = {'message': [], 'media': []}

    class Bot:
        async def send_message(self, chat_id, text, reply_markup=None, **_kw):
            sent['message'].append((chat_id, text, reply_markup))

        async def send_photo(self, *a, **kw):
            sent['media'].append('photo')

        async def send_voice(self, *a, **kw):
            sent['media'].append('voice')

        async def send_animation(self, *a, **kw):
            sent['media'].append('animation')

    monkeypatch.setattr(ss, '_user_local_hour', lambda u: 9)
    monkeypatch.setattr(ss, 'RITUAL_APPROVAL_MODE', False)
    monkeypatch.setattr(ss, 'RITUAL_MEDIA_TO_USERS', False)
    monkeypatch.setattr(ss, '_ritual_sent', set())
    monkeypatch.setattr(ss, '_ritual_hydrated', set())
    monkeypatch.setattr(pg, 'allow_push', lambda *a, **kw: (True, ''))
    monkeypatch.setattr(ui_lang, 'full_user_lang', lambda tg: 'ru')
    monkeypatch.setattr(config, 'PUBLIC_BASE_URL', 'https://x.test')
    monkeypatch.setattr(app_ping, 'APP_PING_ENABLED', True)
    for name in ('_pending', '_presence', '_seen', '_last_ping', '_day_count'):
        monkeypatch.setattr(app_ping, name, {})
    monkeypatch.setattr(app_ping, '_sending', set())
    # Drive the delayed delivery explicitly, without sleeping or background tasks.
    monkeypatch.setattr(app_ping, '_arm', lambda *a: None)
    monkeypatch.setattr(app_ping, '_read_since', lambda *a: False)
    monkeypatch.setattr(app_ping, '_quiet_now', lambda tz: False)
    monkeypatch.setattr(app_ping, '_character_name', lambda char: 'Анна')
    monkeypatch.setattr(app_ping, '_user_ctx', lambda tg: {'uid': uid, 'lang': 'ru', 'tz': 'UTC'})
    bot = Bot()
    asyncio.run(ss._rituals(bot))
    asyncio.run(ss._rituals(bot))                 # a second scan cannot duplicate it

    history = webapp_service.api_chat_history(uid, 'anna_01')
    assert len(history) == 1
    row = history[0]
    assert row['id'] and row['role'] == 'assistant' and row['origin'] == 'push'
    assert row['content'] in RITUAL_LINES['ru']['morning']
    assert row['media_kind'] is None and row['media_url'] is None
    assert row['actions'] == []
    assert sent['message'] == []                 # no direct Telegram delivery
    assert set(app_ping._pending) == {tid}
    pending = app_ping._pending[tid]
    assert pending['char'] == 'anna_01' and pending['count'] == 1
    assert pending['generic'] is True and pending['channel'] == 'default'
    assert pending['text'] == '' and pending['media'] is None
    assert asyncio.run(app_ping._deliver(bot, tid)) == 'sent'

    assert len(sent['message']) == 1
    chat, text, markup = sent['message'][0]
    assert chat == tid
    assert text == app_ping.ping_text('Анна', '', None, 0, 'ru')
    assert row['content'] not in text
    assert markup.inline_keyboard[0][0].web_app.url == 'https://x.test/webapp?open=chat&char=anna_01'
    assert sent['media'] == []
    assert (uid, 'morning', dt.datetime.now(dt.timezone.utc).date().isoformat()) in ss._ritual_sent
    with sessions() as s:
        events = s.query(ProductEvent).filter_by(user_id=uid, event_name='ritual_morning_sent').all()
        assert len(events) == 1


def test_the_text_line_needs_no_approval_press():
    body = SCHED[SCHED.index('async def _rituals('):SCHED.index('async def _donation_reminder')]
    assert 'if not preview and not RITUAL_MEDIA_TO_USERS:' in body
    assert 'await _ritual_line_push(bot, uid, int(tg_id)' in body
    assert "RITUAL_MEDIA_TO_USERS=_os.getenv('RITUAL_MEDIA_TO_USERS','false')" in SCHED
    # the paid media ritual (and its ✅) is what the owner previews for himself
    assert 'await _ritual_preview(bot, msk_kind, msk_day)' in body


def test_every_marketing_rail_sits_behind_one_switch():
    jobs = SCHED[SCHED.index('def start_scheduler(bot):'):]
    block = jobs[jobs.index('if MARKETING_PUSH_ENABLED:'):]
    for name in JUNK_JOBS:
        assert f"id='{name}'" in block, name
        assert jobs.index(f"id='{name}'") > jobs.index('if MARKETING_PUSH_ENABLED:'), name
    for kept in ('rituals', 'reminders', 'db_backup'):
        assert f"id='{kept}'" in jobs
        assert f"id='{kept}'" not in block
