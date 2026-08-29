import asyncio, datetime as dt, logging, random
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from config import (
    PROACTIVE_MIN_HOURS, RETENTION_REMINDER_HOURS, CHARACTER_ID,
    RITUALS_ENABLED, RITUAL_MORNING_START_HOUR, RITUAL_MORNING_END_HOUR,
    RITUAL_EVENING_START_HOUR, RITUAL_EVENING_END_HOUR, RITUAL_MAX_INACTIVE_DAYS,
)
from services.db import SessionLocal
from models.app_models import User, CharacterState
from services.reminder_service import due_reminders, mark_after_send
from services.chat_service import proactive_reply
from services.analytics_service import track_event
from services import retention_service

logger=logging.getLogger(__name__); scheduler=AsyncIOScheduler()

# V3.20.0: in-memory guard so each ritual fires at most once per user/day/kind.
# A Railway redeploy can theoretically duplicate one ritual message that day —
# an acceptable trade-off for zero extra DB schema.
_ritual_sent: set[tuple[int, str, str]] = set()

async def _reminders(bot):
    rows=await asyncio.to_thread(due_reminders)
    if rows:
        logger.info('scheduler checking reminders count=%s ids=%s', len(rows), [r.id for r in rows])
    wake_msgs=['доброе утро ☀️ подъём','эй, ты там проснулся? 😂','соня, вставай уже','я всё ещё здесь 🙄','ну всё, последний шанс 😌','ладно, сдаюсь 😂']
    for r in rows:
        try:
            with SessionLocal() as s: user=s.get(User,r.user_id)
            if not user:
                logger.warning('reminder user missing id=%s', r.id)
                await asyncio.to_thread(mark_after_send,r.id,True); continue
            telegram_id=int(user.telegram_id)
            logger.info('sending reminder id=%s type=%s user=%s attempts=%s/%s due=%s tz=%s',
                        r.id, r.reminder_type, telegram_id, r.attempts, r.max_attempts, r.due_at_utc, r.timezone)
            if r.reminder_type=='wake':
                idx=min(r.attempts,len(wake_msgs)-1); await bot.send_message(telegram_id,wake_msgs[idx]); delays=[2,3,5,7,10,10]
                await asyncio.to_thread(mark_after_send,r.id,idx==len(wake_msgs)-1,delays[idx])
            else:
                await bot.send_message(telegram_id,f"напоминаю: {r.text}"); await asyncio.to_thread(mark_after_send,r.id,True)
        except Exception: logger.exception('reminder failed id=%s', r.id if r else None)

async def _proactive(bot):
    now=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None); cutoff=now-dt.timedelta(hours=RETENTION_REMINDER_HOURS)
    with SessionLocal() as s:
        users=s.scalars(select(User).where(User.proactive_enabled==True,User.last_active_at<=cutoff)).all()
        ids=[u.id for u in users]
    for uid in ids:
        try:
            with SessionLocal() as s:
                u=s.get(User,uid); state=s.scalar(select(CharacterState).where(CharacterState.user_id==uid,CharacterState.character_id==CHARACTER_ID))
                if not u: continue
                # only one nudge after the user's last message
                if state and state.last_nudge_at and state.last_nudge_at>=u.last_active_at: continue
                telegram_id=int(u.telegram_id); name=u.name or 'ты'; hours=max(RETENTION_REMINDER_HOURS,int((now-u.last_active_at).total_seconds()/3600))
                streak=int(u.streak_count or 0)
                hook=bool(state and state.pending_hook)
            if hours < PROACTIVE_MIN_HOURS:
                # V3.20.0 first tier (24-48h): cheap static emotional push —
                # unfinished-conversation cliffhanger first, then jealousy for
                # established streaks, otherwise a plain "I miss you".
                if hook:
                    kind='cliffhanger'
                elif streak >= 3 and random.random() < 0.5:
                    kind='jealousy'
                else:
                    kind='miss'
                msg=retention_service.pick_text(kind)
                await bot.send_message(telegram_id,msg)
                track_event(uid, 'retention_push_sent', metadata={'hours_inactive': hours, 'kind': kind})
            else:
                msg=await proactive_reply(telegram_id,name,hours); await bot.send_message(telegram_id,msg)
                track_event(uid, 'proactive_sent', metadata={'hours_inactive': hours})
            with SessionLocal() as s:
                st=s.scalar(select(CharacterState).where(CharacterState.user_id==uid,CharacterState.character_id==CHARACTER_ID))
                if st:
                    st.last_nudge_at=now
                    # A pending hook is consumed by one proactive follow-up so Anna does not repeat it forever.
                    st.pending_hook=None
                    s.commit()
        except Exception: logger.exception('proactive failed user=%s',uid)

def _user_local_hour(user) -> int | None:
    """Best-effort local hour for rituals; None when the timezone is unusable."""
    try:
        from zoneinfo import ZoneInfo
        tz=ZoneInfo(user.timezone or 'UTC')
        return dt.datetime.now(tz).hour
    except Exception:
        return dt.datetime.now(dt.timezone.utc).hour

async def _rituals(bot):
    """V3.20.0: morning/evening rituals — she writes first in the user's local
    time window. Only recent (RITUAL_MAX_INACTIVE_DAYS) opt-in users get them."""
    now=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    fresh_cutoff=now-dt.timedelta(days=RITUAL_MAX_INACTIVE_DAYS)
    with SessionLocal() as s:
        users=s.scalars(select(User).where(User.proactive_enabled==True,User.last_active_at>=fresh_cutoff)).all()
        snapshot=[(u.id,u.telegram_id,u.name or 'ты',u.streak_count or 0,u.timezone) for u in users]
    today_key=now.date().isoformat()
    for uid,tg_id,name,streak,tz in snapshot:
        try:
            with SessionLocal() as s:
                u=s.get(User,uid)
                if not u: continue
                local_hour=_user_local_hour(u)
            kind=None
            if RITUAL_MORNING_START_HOUR <= local_hour < RITUAL_MORNING_END_HOUR:
                kind='morning'
            elif RITUAL_EVENING_START_HOUR <= local_hour < RITUAL_EVENING_END_HOUR:
                kind='evening'
            if not kind: continue
            guard=(uid,kind,today_key)
            if guard in _ritual_sent: continue
            text=retention_service.pick_text(kind)
            if streak and streak >= 3:
                text+=f'\n\nкстати, мы общаемся {streak} дней подряд 🔥 не прерывай серию 😉'
            await bot.send_message(int(tg_id),text)
            _ritual_sent.add(guard)
            track_event(uid, f'ritual_{kind}_sent', metadata={'streak': streak, 'tz': tz})
        except Exception: logger.exception('ritual failed user=%s',uid)

def start_scheduler(bot):
    scheduler.add_job(_reminders,'interval',seconds=30,args=[bot],id='reminders',replace_existing=True)
    scheduler.add_job(_proactive,'interval',hours=1,args=[bot],id='proactive',replace_existing=True)
    if RITUALS_ENABLED:
        scheduler.add_job(_rituals,'interval',minutes=30,args=[bot],id='rituals',replace_existing=True)
    if not scheduler.running: scheduler.start()
