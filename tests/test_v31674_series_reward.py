"""V3.167.4 #171 (владелец, 16.11): «включи награду за серию».

Правило одно, без кнопки и без «забери сам»: зашёл, написал ей пять сообщений за
сутки — получил 50 🍑. Считаются его реплики в диалоге, а не дневный потолок,
чтобы Premium не остался без серии; сутки — московская полночь в 03:00 (дата UTC,
та же граница, что у прошлых наград за постоянство). Серия видна в шапке чата,
один пропущенный день в неделю закрывает заморозка, со вторым пропуска серия
начинается с единицы — и обнуляется только она: близость пары и её незакрытая
тема живут в других таблицах. ECONOMY: это единственная новая выдача релиза,
цена кадра (250 🍑) и покупку персиков не трогали, заработанные персики рендер
по-прежнему не оплачивают.
"""
import inspect
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import config
from services import payments as P
from services import series_reward as SR

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
CHAT_SERVICE = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def _tid() -> int:
    return 816740000 + uuid.uuid4().int % 99999


def _user(streak: int = 0, days_ago: int | None = None, freeze_week: str | None = None):
    """Аккаунт с заранее заданной серией: streak дней, последний — N суток назад."""
    from sqlalchemy import select, update
    from services.user_service import ensure_user
    from services.db import SessionLocal
    from models.app_models import User
    tid = _tid()
    uid = ensure_user(tid, 'V')
    last = None if days_ago is None else datetime.utcnow() - timedelta(days=days_ago)
    with SessionLocal() as s:
        s.execute(update(User).where(User.id == uid)
                  .values(streak_count=streak, streak_last_date=last,
                          streak_freeze_week=freeze_week))
        s.commit()
        row = s.scalar(select(User).where(User.id == uid))
        return tid, uid, row


def _lines(uid: int, n: int) -> None:
    """N его реплик в диалоге — ровно за сегодня."""
    from services.db import SessionLocal
    from models.app_models import Message
    with SessionLocal() as s:
        for _ in range(n):
            s.add(Message(user_id=uid, character_id='anna', role='user',
                          content='как ты?', created_at=datetime.utcnow()))
        s.commit()


def _row(tid: int):
    from sqlalchemy import select
    from services.db import SessionLocal
    from models.app_models import User
    with SessionLocal() as s:
        return s.scalar(select(User).where(User.telegram_id == str(tid)))


# ── Блок 1: пять сообщений = 50 🍑 ───────────────────────────────────────────

def test_five_of_his_own_lines_pay_exactly_fifty_peaches():
    tid, uid, _ = _user()
    _lines(uid, 4)
    assert SR.note_his_message(tid, uid) is None
    assert P.get_bonus_peaches(tid) == 0            # ни одного персика не ушло
    _lines(uid, 1)                                  # его пятая реплика за сутки
    notice = SR.note_his_message(tid, uid)
    assert notice and notice['amount'] == config.SERIES_REWARD_PEACHES == 50
    assert notice['streak'] == 1 and notice['frozen'] is False
    assert P.get_bonus_peaches(tid) == 50
    handed = SR.take_notice(tid)
    assert handed and handed['amount'] == 50 and handed['streak'] == 1


def test_the_day_pays_once_however_many_lines_follow():
    tid, uid, _ = _user()
    _lines(uid, 5)
    assert SR.note_his_message(tid, uid) is not None
    _lines(uid, 20)
    assert SR.note_his_message(tid, uid) is None
    assert P.get_bonus_peaches(tid) == 50


def test_a_replay_of_the_same_day_grants_nothing_even_if_the_stamp_is_lost():
    from sqlalchemy import update
    from services.db import SessionLocal
    from models.app_models import User
    tid, uid, _ = _user()
    _lines(uid, 6)
    assert SR.note_his_message(tid, uid) is not None
    # гонка двух тапов: метку суток снесли — reason всё равно один на сутки
    with SessionLocal() as s:
        s.execute(update(User).where(User.telegram_id == str(tid))
                  .values(streak_reward_day=None))
        s.commit()
    assert SR.note_his_message(tid, uid) is None
    assert P.get_bonus_peaches(tid) == 50


def test_the_money_lands_in_the_earned_wallet_a_render_cannot_pay_for():
    tid, uid, _ = _user()
    _lines(uid, 5)
    SR.note_his_message(tid, uid)
    assert P.get_bonus_peaches(tid) == 50
    assert P.get_paid_peaches(tid) == 0             # купленные не при чём
    assert not P.photo_peaches_ready(tid, config.EXPLICIT_PHOTO_PEACH_COST)


def test_the_flag_and_the_counter_are_owner_tuned_and_the_gift_stays_off():
    assert config.SERIES_REWARD_ENABLED is True
    assert config.SERIES_REWARD_PEACHES == 50
    assert config.SERIES_REWARD_MIN_MESSAGES == 5
    assert config.SERIES_FREEZE_PER_WEEK == 1
    # прежняя ручная рельса 🎁 не проснулась: две награды за один день не нужны
    assert 'DAILY_GIFT_ENABLED = os.getenv("DAILY_GIFT_ENABLED", "0")' in CONFIG
    assert config.DAILY_GIFT_ENABLED is False


def test_switched_off_the_rail_is_silent():
    from services import series_reward
    tid, uid, _ = _user()
    _lines(uid, 12)
    series_reward.SERIES_REWARD_ENABLED = False
    try:
        assert SR.note_his_message(tid, uid) is None
    finally:
        series_reward.SERIES_REWARD_ENABLED = True
    assert P.get_bonus_peaches(tid) == 0
    # серия не продвинулась: платёж и счётчик живут вместе
    assert _row(tid).streak_count == 0


# ── Блок 2: серия, заморозка и то, что не обнуляется ─────────────────────────

def test_the_series_counts_the_days_he_came_not_the_lines_he_wrote():
    tid, uid, _ = _user(streak=3, days_ago=1)
    _lines(uid, 5)
    notice = SR.note_his_message(tid, uid)
    assert notice['streak'] == 4
    assert _row(tid).streak_count == 4


def test_one_missed_day_a_week_is_frozen_and_the_series_keeps_growing():
    tid, uid, _ = _user(streak=4, days_ago=2)
    _lines(uid, 5)
    notice = SR.note_his_message(tid, uid)
    assert notice['frozen'] is True and notice['streak'] == 5
    row = _row(tid)
    assert row.streak_count == 5
    assert row.streak_freeze_week == SR._week_key(SR.day_key())


def test_the_second_missed_day_restarts_only_the_series():
    week = SR._week_key(SR.day_key())
    tid, uid, _ = _user(streak=4, days_ago=2, freeze_week=week)
    _lines(uid, 5)
    notice = SR.note_his_message(tid, uid)
    assert notice['frozen'] is False and notice['streak'] == 1
    row = _row(tid)
    assert row.streak_count == 1
    assert row.streak_freeze_week == week            # заморозка не потрачена зря
    assert P.get_bonus_peaches(tid) == 50            # награда суток всё равно его


def test_without_freeze_a_miss_always_starts_at_one():
    from services import series_reward
    series_reward.SERIES_FREEZE_PER_WEEK = 0
    try:
        tid, uid, _ = _user(streak=6, days_ago=2)
        _lines(uid, 5)
        assert SR.note_his_message(tid, uid)['streak'] == 1
    finally:
        series_reward.SERIES_FREEZE_PER_WEEK = config.SERIES_FREEZE_PER_WEEK


def test_the_bot_side_rescues_the_series_the_same_way():
    from services import gamification_service as G
    tid, uid, _ = _user(streak=3, days_ago=2)
    summary = G.touch_activity(tid)
    assert summary['streak_count'] == 4
    assert _row(tid).streak_freeze_week == SR._week_key(SR.day_key())
    # вторая пропущенная неделя за ту же KC-неделю — серия с единицы
    tid2, uid2, _ = _user(streak=3, days_ago=2, freeze_week=SR._week_key(SR.day_key()))
    assert G.touch_activity(tid2)['streak_count'] == 1


# ── Блок 3: как он об этом узнаёт ────────────────────────────────────────────

def test_the_notice_is_handed_over_once_and_the_plashka_is_readable():
    tid, uid, _ = _user(streak=1, days_ago=1)
    _lines(uid, 5)
    assert SR.note_his_message(tid, uid) is not None
    first = SR.take_notice(tid)
    assert first and SR.take_notice(tid) is None
    ru = SR.line(first, 'ru')
    assert 'серия 2' in ru and '50 🍑' in ru
    assert 'days in a row' in SR.line(first, 'en')


def test_a_stale_notice_is_never_shown_on_the_next_visit():
    tid, uid, _ = _user()
    _lines(uid, 5)
    SR.note_his_message(tid, uid)
    SR._pending[tid]['at'] -= SR._PENDING_TTL_SECONDS + 1
    assert SR.take_notice(tid) is None


def test_the_check_runs_inside_the_accepted_turn_of_both_platforms():
    assert 'series_reward.note_his_message' in CHAT_SERVICE   # один ход — бот и Mini App
    assert MAIN.count('series_reward.take_notice') == 2       # плашка: бот + payload чата
    assert MAIN.count('await _series_note(message, message.from_user.id)') == 2
    assert "payload['series']" in MAIN
    assert "snap['streak'] = int(getattr(user, 'streak_count', 0) or 0)" in MAIN


def test_the_app_shows_the_series_in_the_header_and_the_gift_under_her_answer():
    assert 'id="chatStreak"' in INDEX
    assert "Number(j.streak)" in INDEX and "'🔥 ' + days" in INDEX
    assert 'j.series' in INDEX and 'sernote' in INDEX
    # один день — не серия: чип молчит, пока не набралось два
    assert "days > 1 ? '🔥 ' + days : ''" in INDEX


def test_the_new_columns_are_declared_for_the_auto_migration():
    from models.app_models import User
    assert 'streak_freeze_week' in User.__table__.columns
    assert 'streak_reward_day' in User.__table__.columns
    assert 'reason=f\'series_reward_{today}\'' in inspect.getsource(SR.note_his_message)
