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
from config import MARKETING_PUSH_ENABLED, PUSH_MAX_PER_DAY, PUBLIC_BASE_URL
from models.app_models import ProductEvent
from services import push_governor as pg
from services import scheduler_service as ss
from services.db import SessionLocal, init_db
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


def test_two_a_day_and_the_rest_is_off():
    assert PUSH_MAX_PER_DAY == 2
    assert MARKETING_PUSH_ENABLED is False


def test_the_third_first_write_of_his_day_is_one_too_many(monkeypatch):
    from services.db import init_db
    init_db()
    uid = ensure_user(771620001, 'Тест')
    monkeypatch.setattr(pg, 'local_hour', lambda tz: 12)
    monkeypatch.setattr(pg, 'PUSH_SPACING_WINDOW_MINUTES', 0)   # only the day cap
    assert pg.allow_push(uid, 'Europe/Moscow') == (True, '')
    _events(uid, ['ritual_morning_sent', 'ritual_evening_sent'])
    assert pg.pushes_today(uid, 'Europe/Moscow') == 2
    assert pg.allow_push(uid, 'Europe/Moscow') == (False, 'daily')


def test_the_day_is_his_not_the_servers():
    from zoneinfo import ZoneInfo
    start = pg._local_day_start('Asia/Kolkata')
    expect = dt.datetime.now(ZoneInfo('Asia/Kolkata')).replace(
        hour=0, minute=0, second=0, microsecond=0).astimezone(dt.timezone.utc).replace(tzinfo=None)
    assert abs((start - expect).total_seconds()) < 5
    assert pg._local_day_start('Mars/Olympus') == pg._local_day_start('UTC')


@pytest.mark.parametrize('kind', ('morning', 'evening'))
def test_her_lines_exist_in_every_app_language(kind):
    for lang in APP_LANGS:
        lines = RITUAL_LINES[lang][kind]
        assert len(lines) >= 4, (lang, kind)
        assert all(4 < len(l) < 90 for l in lines), (lang, kind, lines)
        assert ritual_line(kind, lang) in lines
    assert ritual_line(kind, 'de') in RITUAL_LINES['en'][kind]   # unknown → English
    assert flow_text('bn', 'open_chat') != flow_text('ru', 'open_chat')


def test_users_get_the_text_push_with_the_button_into_her_dialog(monkeypatch):
    init_db()
    tid = 771620002
    uid = ensure_user(tid, 'Тест')
    with SessionLocal() as s:
        from models.app_models import User
        u = s.get(User, uid)
        u.proactive_enabled = True
        u.notify_rituals = True
        u.timezone = 'UTC'
        u.selected_character = 'anna_01'
        u.last_active_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        s.commit()

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
    # only THIS man may pass the gate today — nobody else in the test DB gets written to
    monkeypatch.setattr(pg, 'allow_push',
                        lambda uid_, tz=None: (True, '') if uid_ == uid else (False, 'daily'))
    monkeypatch.setattr(ss, 'PUBLIC_BASE_URL', PUBLIC_BASE_URL or 'https://x.test', raising=False)
    ss._ritual_sent.clear()
    ss._ritual_hydrated.clear()
    asyncio.run(ss._rituals(Bot()))

    mine = [m for m in sent['message'] if m[0] == tid]
    assert len(mine) == 1, mine
    _chat, text, markup = mine[0]
    assert text in RITUAL_LINES['ru']['morning']
    btn = markup.inline_keyboard[0][0]
    assert btn.web_app.url.endswith('/webapp?open=chat&char=anna_01')
    assert sent['media'] == []                       # no photo, no voice note
    assert (uid, 'morning', dt.datetime.now(dt.timezone.utc).date().isoformat()) in ss._ritual_sent


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
