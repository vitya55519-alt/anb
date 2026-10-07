"""V3.55.9 static checks: the proactive money leak (owner: «вовлеченность ужас»).

Admin stats showed $2.489/day on purpose='proactive' with 3302 LLM calls while
only 6 users were active. Root cause: CharacterState nudge stamps were written
ONLY after a successful send — every failed send (user blocked the bot, 4xx,
flood-wait) left the user eligible again an hour later, so the hourly scan
re-burned an LLM call per unreachable user forever.

Fixes pinned here:
1. stamp-before-spend: the nudge slot is consumed inside the read session,
   before proactive_reply()/send_message() run;
2. ghost window: PROACTIVE_MAX_INACTIVE_DAYS caps how long a silent user is
   chased at all (SQL filter User.last_active_at>=ghost_cutoff);
3. TelegramForbiddenError (403) disables the user's proactive rail in every
   job that can hit it (_proactive/_reminders/_day1_hook/_rituals/_life_events)
   instead of retrying forever;
4. an empty proactive_reply() result skips the send (the slot is already spent).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
SCHEDULER = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')

PROACTIVE = SCHEDULER[SCHEDULER.index('async def _proactive(bot):'):SCHEDULER.index('async def _day1_hook(bot):')]
DAY1 = SCHEDULER[SCHEDULER.index('async def _day1_hook(bot):'):SCHEDULER.index('def _user_local_hour(')]
RITUALS = SCHEDULER[SCHEDULER.index('async def _rituals(bot):'):SCHEDULER.index('async def _donation_reminder(bot):')]
LIFE = SCHEDULER[SCHEDULER.index('async def _life_events(bot):'):SCHEDULER.index('def start_scheduler(')]
REMINDERS = SCHEDULER[SCHEDULER.index('async def _reminders(bot):'):SCHEDULER.index('async def _proactive(bot):')]


def test_ghost_window_knob():
    assert 'PROACTIVE_MAX_INACTIVE_DAYS = max(3, min(30, int(os.getenv("PROACTIVE_MAX_INACTIVE_DAYS", "10"))))' in CONFIG
    assert 'PROACTIVE_MAX_INACTIVE_DAYS,' in SCHEDULER
    assert 'ghost_cutoff=now-dt.timedelta(days=PROACTIVE_MAX_INACTIVE_DAYS)' in PROACTIVE
    assert 'User.last_active_at>=ghost_cutoff' in PROACTIVE


def test_stamp_consumed_before_money_is_spent():
    # the slot write must happen BEFORE the LLM call / send, so a failed
    # send can never re-arm the hourly retry
    assert PROACTIVE.index('st.last_nudge_at=now') < PROACTIVE.index('msg=await proactive_reply(')
    assert PROACTIVE.index('s.commit()') < PROACTIVE.index('await bot.send_message(telegram_id,msg)')
    # the old post-send stamp session is gone (only one stamp block in the job)
    assert PROACTIVE.count('st.last_nudge_at=now') == 1


def test_empty_llm_reply_does_not_send():
    assert 'if not msg:' in PROACTIVE
    assert "logger.warning('proactive empty reply user=%s', telegram_id)" in PROACTIVE


def test_forbidden_disables_proactive_rail():
    assert 'from aiogram.exceptions import TelegramForbiddenError' in SCHEDULER
    # the helper itself: never auto-re-enabled, opt-out stays respected
    helper = SCHEDULER[SCHEDULER.index('def _mark_blocked(uid: int) -> None:'):SCHEDULER.index("_life_events_store")]
    assert 'u.proactive_enabled = False' in helper
    # every LLM/send-heavy job has a dedicated 403 branch before the generic one
    for job in (PROACTIVE, REMINDERS, DAY1, RITUALS, LIFE):
        assert 'except TelegramForbiddenError:' in job
        assert '_mark_blocked(' in job
    assert 'except TelegramForbiddenError:' in PROACTIVE
    assert PROACTIVE.index('except TelegramForbiddenError:') < PROACTIVE.index('except Exception:')
    # blocked users drop their pending reminders and burn the day-1 slot
    assert 'await asyncio.to_thread(mark_after_send,r.id,True)' in REMINDERS[REMINDERS.index('except TelegramForbiddenError:'):]
    assert 'u.day1_hook_at=now' in DAY1[DAY1.index('except TelegramForbiddenError:'):]


def test_v34416_ladder_pins_survive_refactor():
    # the V3.44.16 repeat-nudge ladder must stay intact after the move
    assert 'returned=bool(last_nudge and u.last_active_at and u.last_active_at>last_nudge)' in PROACTIVE
    assert '(now-last_nudge).total_seconds() < RETENTION_NUDGE_INTERVAL_HOURS*3600' in PROACTIVE
    assert 'nudge_count >= RETENTION_MAX_NUDGES' in PROACTIVE
    assert 'st.nudge_count=1 if (returned or not last_nudge) else nudge_count+1' in PROACTIVE
    assert 'if st is None:' in PROACTIVE
    assert 'st=CharacterState(user_id=uid,character_id=CHARACTER_ID)' in PROACTIVE
