import asyncio
import datetime as dt
import logging
import openai
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from openai import AsyncOpenAI
from config import AI_KEY, AI_MODEL, AI_BASE_URL, PROACTIVE_MIN_HOURS

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


def start_scheduler(bot):
    scheduler.add_job(_check_due_reminders, 'interval', seconds=30, args=[bot], id='reminders', replace_existing=True)
    scheduler.add_job(_check_inactive_users, 'interval', hours=1, args=[bot], id='proactive_check', replace_existing=True)
    if not scheduler.running:
        scheduler.start()
    logger.info('Human scheduler started')


async def _check_due_reminders(bot):
    from .db_interaction import get_due_reminders, mark_reminder_sent, search_user
    rows = await asyncio.to_thread(get_due_reminders)
    for row in rows:
        try:
            user = await asyncio.to_thread(search_user, row.relIdUser)
            if not user:
                await asyncio.to_thread(mark_reminder_sent, row.idReminder)
                continue
            if row.reminder_type == 'wake':
                messages = [
                    'доброе утро ☀️ подъём',
                    'ты там вообще проснулся? 😂',
                    'я серьёзно, соня. вставай',
                    'ну ладно, ещё один пинг 😑',
                    'я тебя предупреждала 😌',
                    'всё, сдаюсь. но ты мне потом не говори, что я не будила 😂',
                ]
                idx = min(row.attempts or 0, len(messages) - 1)
                await bot.send_message(user.telegram_id, messages[idx])
                await asyncio.to_thread(mark_reminder_sent, row.idReminder, idx >= len(messages) - 1)
                if idx < len(messages) - 1:
                    # next nudge in 3-8 minutes
                    from .db_interaction import reschedule_reminder
                    delay = [3, 5, 5, 8, 10][idx]
                    await asyncio.to_thread(reschedule_reminder, row.idReminder, (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=delay)).replace(tzinfo=None))
            else:
                await bot.send_message(user.telegram_id, row.text)
                await asyncio.to_thread(mark_reminder_sent, row.idReminder, True)
        except Exception:
            logger.exception('Reminder delivery failed')


async def _check_inactive_users(bot):
    from .db_interaction import get_active_proactive_users, update_user_last_active
    cutoff = dt.datetime.now() - dt.timedelta(hours=PROACTIVE_MIN_HOURS)
    users = await asyncio.to_thread(get_active_proactive_users, cutoff)
    for user in users:
        try:
            hours_inactive = int((dt.datetime.now() - user.last_active).total_seconds() / 3600)
            msg = await _generate_proactive_message(user, hours_inactive)
            await bot.send_message(user.telegram_id, msg)
            await asyncio.to_thread(update_user_last_active, user.telegram_id)
        except Exception:
            logger.exception('Failed to send proactive message to user %s', user.telegram_id)


async def _generate_proactive_message(user, hours_inactive: int) -> str:
    # Use the canonical Anna character/memory/relationship stack instead of the
    # legacy Spanish WaifuRole prompt. This keeps proactive messages consistent
    # with normal chat.
    from services.chat_service import proactive_reply
    return await proactive_reply(
        int(user.telegram_id),
        user.name or "друг",
        hours_inactive,
    )
