import asyncio, datetime as dt, logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from config import PROACTIVE_MIN_HOURS, CHARACTER_ID
from services.db import SessionLocal
from models.app_models import User, CharacterState
from services.reminder_service import due_reminders, mark_after_send
from services.chat_service import proactive_reply
from services.analytics_service import track_event

logger=logging.getLogger(__name__); scheduler=AsyncIOScheduler()

async def _reminders(bot):
    rows=await asyncio.to_thread(due_reminders)
    wake_msgs=['доброе утро ☀️ подъём','эй, ты там проснулся? 😂','соня, вставай уже','я всё ещё здесь 🙄','ну всё, последний шанс 😌','ладно, сдаюсь 😂']
    for r in rows:
        try:
            with SessionLocal() as s: user=s.get(User,r.user_id)
            if not user: await asyncio.to_thread(mark_after_send,r.id,True); continue
            if r.reminder_type=='wake':
                idx=min(r.attempts,len(wake_msgs)-1); await bot.send_message(int(user.telegram_id),wake_msgs[idx]); delays=[2,3,5,7,10,10]
                await asyncio.to_thread(mark_after_send,r.id,idx==len(wake_msgs)-1,delays[idx])
            else:
                await bot.send_message(int(user.telegram_id),f"напоминаю: {r.text}"); await asyncio.to_thread(mark_after_send,r.id,True)
        except Exception: logger.exception('reminder failed')

async def _proactive(bot):
    now=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None); cutoff=now-dt.timedelta(hours=PROACTIVE_MIN_HOURS)
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
                telegram_id=int(u.telegram_id); name=u.name or 'ты'; hours=max(PROACTIVE_MIN_HOURS,int((now-u.last_active_at).total_seconds()/3600))
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

def start_scheduler(bot):
    scheduler.add_job(_reminders,'interval',seconds=30,args=[bot],id='reminders',replace_existing=True)
    scheduler.add_job(_proactive,'interval',hours=1,args=[bot],id='proactive',replace_existing=True)
    if not scheduler.running: scheduler.start()
