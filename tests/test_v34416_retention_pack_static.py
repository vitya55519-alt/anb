"""V3.44.16 static checks: the retention pack (owner: «удержание дно просто»).

D1 was 5% / D7 1% with 45 weekly signups. Root causes fixed:
1. `_proactive` allowed exactly ONE nudge per user lifetime — the guard
   `last_nudge_at >= last_active_at` skipped a silent user forever after the
   first push, and the 48h+ LLM tier was dead code. Nudges now repeat (spaced
   by RETENTION_NUDGE_INTERVAL_HOURS, capped at RETENTION_MAX_NUDGES) and the
   ladder resets when the user returns.
2. A user without an Anna CharacterState row was re-nudged EVERY hour — the
   write phase silently skipped, so no stamp was ever persisted.
3. No day-1 hook existed: young silent accounts now get one «your bonus wheel
   is waiting» push with an app button (User.day1_hook_at).
4. The morning ritual and the sleep-block reply now carry a concrete reason
   to return tomorrow: the unclaimed daily bonus wheel.
5. Streaks became visible from day 2 (were invisible until the 3-day reward).
6. The studio render is bounded by PHOTO_TOTAL_BUDGET_SECONDS (49% failures,
   unbounded hangs).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
SCHEDULER = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')


def test_nudge_knobs_exist():
    assert 'RETENTION_NUDGE_INTERVAL_HOURS' in CONFIG
    assert 'RETENTION_MAX_NUDGES' in CONFIG
    assert 'DAY1_HOOK_MAX_ACCOUNT_HOURS' in CONFIG
    assert 'DAY1_HOOK_MIN_INACTIVE_HOURS' in CONFIG


def test_one_nudge_per_lifetime_guard_removed():
    # the old guard skipped a silent user FOREVER after the first push
    assert 'state.last_nudge_at>=u.last_active_at' not in SCHEDULER
    # replacements: spacing + cap + reset-on-return
    assert '(now-last_nudge).total_seconds() < RETENTION_NUDGE_INTERVAL_HOURS*3600' in SCHEDULER
    assert 'nudge_count >= RETENTION_MAX_NUDGES' in SCHEDULER
    assert 'returned=bool(last_nudge and u.last_active_at and u.last_active_at>last_nudge)' in SCHEDULER
    assert 'st.nudge_count=1 if (returned or not last_nudge) else nudge_count+1' in SCHEDULER


def test_missing_state_row_no_longer_spams_hourly():
    # a user without an Anna state row used to be nudged every hour because
    # the stamp write silently skipped — now the row is created
    proactive = SCHEDULER[SCHEDULER.index('async def _proactive(bot):'):SCHEDULER.index('async def _day1_hook(bot):')]
    assert 'if st is None:' in proactive
    assert 'st=CharacterState(user_id=uid,character_id=CHARACTER_ID)' in proactive


def test_day1_hook_job():
    hook = SCHEDULER[SCHEDULER.index('async def _day1_hook(bot):'):SCHEDULER.index('def _user_local_hour(')]
    # young + silent + not yet hooked accounts only
    assert 'User.day1_hook_at.is_(None)' in hook
    assert 'User.created_at>=young' in hook
    assert 'User.last_active_at<=silent' in hook
    # the message promises the wheel and opens the app
    assert 'колесе ежедневного бонуса' in hook
    assert 'WebAppInfo(url=f\'{PUBLIC_BASE_URL}/webapp\')' in hook
    # exactly once per user
    assert 'u.day1_hook_at=now' in hook
    assert 'has_accepted(telegram_id)' in hook
    # registered on the scheduler
    assert "scheduler.add_job(_day1_hook,'interval',minutes=15" in SCHEDULER


def test_morning_ritual_mentions_unclaimed_wheel():
    rituals = SCHEDULER[SCHEDULER.index('async def _rituals(bot):'):SCHEDULER.index('async def _donation_reminder(bot):')]
    assert "get_daily_bonus_status(int(tg_id)).get('claimed')" in rituals
    assert 'на колесе бонуса тебя ждёт подарок' in rituals


def test_model_columns_for_retention():
    assert 'day1_hook_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)' in MODELS
    assert 'nudge_count: Mapped[int] = mapped_column(Integer, default=0)' in MODELS


def test_sleep_block_promises_tomorrow():
    block = MAIN[MAIN.index('async def _sleep_block_reply('):MAIN.index('# V3.27.0: ruble-shop balances')]
    assert "pick_text('sleep') + '\\nа завтра утром на колесе бонуса" in block


def test_streak_visible_from_day_two():
    start = MAIN.index("from services.gamification_service import touch_activity, check_first_message")
    handler = MAIN[start:start + 2000]
    assert "gam.get('new_streak_day') and int(gam.get('streak_count') or 0) >= 2" in handler
    assert 'приходи завтра — не прерывай серию' in handler


def test_studio_render_bounded():
    studio = MAIN[MAIN.index('async def _webapp_api_picture_generate('):MAIN.index('async def _webapp_pipeline_photo(')]
    assert 'asyncio.wait_for(' in studio
    assert 'timeout=PHOTO_TOTAL_BUDGET_SECONDS,' in studio
    assert 'except asyncio.TimeoutError:' in studio
