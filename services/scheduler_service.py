import asyncio, datetime as dt, logging, random
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from config import (
    PROACTIVE_MIN_HOURS, RETENTION_REMINDER_HOURS, CHARACTER_ID,
    RITUALS_ENABLED, RITUAL_MORNING_START_HOUR, RITUAL_MORNING_END_HOUR,
    RITUAL_EVENING_START_HOUR, RITUAL_EVENING_END_HOUR, RITUAL_MAX_INACTIVE_DAYS,
    DONATION_LINK, DONATION_REMINDER_ENABLED,
    RETENTION_NUDGE_INTERVAL_HOURS, RETENTION_MAX_NUDGES,
    PROACTIVE_MAX_INACTIVE_DAYS,
    DAY1_HOOK_MAX_ACCOUNT_HOURS, DAY1_HOOK_MIN_INACTIVE_HOURS, PUBLIC_BASE_URL,
    LIFE_EVENTS_ENABLED, LIFE_EVENTS_MAX_PER_DAY, LIFE_EVENTS_SCAN_MINUTES,
    LIFE_EVENTS_ACTIVE_WINDOW_DAYS, LIFE_EVENTS_QUIET_START_HOUR, LIFE_EVENTS_QUIET_END_HOUR,
)
from services.db import SessionLocal
from models.app_models import User, CharacterState
from services.reminder_service import due_reminders, mark_after_send
from services.chat_service import proactive_reply
from services.analytics_service import track_event
from services import retention_service
from services import donation_service
from services import retention_features_service
from services import dialog_store
from aiogram.exceptions import TelegramForbiddenError

logger=logging.getLogger(__name__); scheduler=AsyncIOScheduler()


def _mark_blocked(uid: int) -> None:
    """V3.55.9: Telegram answered 403 (bot blocked / account deleted) — switch
    the user's proactive rail off so no scheduler job wastes LLM calls or API
    hits on someone who can never read them. The in-chat settings toggle can
    bring it back; we never auto-re-enable (that would trample a real opt-out)."""
    try:
        with SessionLocal() as s:
            u = s.get(User, uid)
            if u:
                u.proactive_enabled = False
                s.commit()
    except Exception:
        logger.exception('mark blocked failed user=%s', uid)

# V3.52.0: «Жизнь без тебя» dedup lives in dialog_sessions (DictStore), NOT an
# in-memory set. Railway redeploys are frequent here and wiped _ritual_sent, so a
# push could double-fire the same day; a persisted slot log keyed by telegram_id
# ({'date': iso, 'slots': [daypart, ...]}) survives restarts with zero new schema.
_life_events_store = dialog_store.DialogStore('life_events')

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
        except TelegramForbiddenError:
            # V3.55.9: blocked user — drop the reminder instead of retrying it
            # every 30 seconds forever, and take the proactive rail off too.
            await asyncio.to_thread(mark_after_send,r.id,True)
            _mark_blocked(r.user_id)
            logger.info('reminder dropped (user blocked bot) id=%s', r.id)
        except Exception: logger.exception('reminder failed id=%s', r.id if r else None)

async def _proactive(bot):
    now=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None); cutoff=now-dt.timedelta(hours=RETENTION_REMINDER_HOURS)
    # V3.55.9: ghost window — users silent longer than PROACTIVE_MAX_INACTIVE_DAYS
    # are treated as churned; chasing them with a 6th «скучаю» never worked and
    # only burns budget. A real return (last_active_at moves) re-arms the ladder.
    ghost_cutoff=now-dt.timedelta(days=PROACTIVE_MAX_INACTIVE_DAYS)
    with SessionLocal() as s:
        users=s.scalars(select(User).where(User.proactive_enabled==True,User.last_active_at<=cutoff,User.last_active_at>=ghost_cutoff)).all()
        ids=[u.id for u in users]
    for uid in ids:
        try:
            with SessionLocal() as s:
                u=s.get(User,uid); state=s.scalar(select(CharacterState).where(CharacterState.user_id==uid,CharacterState.character_id==CHARACTER_ID))
                if not u: continue
                telegram_id=int(u.telegram_id); name=u.name or 'ты'; hours=max(RETENTION_REMINDER_HOURS,int((now-u.last_active_at).total_seconds()/3600))
                streak=int(u.streak_count or 0)
                hook=bool(state and state.pending_hook)
                last_nudge=state.last_nudge_at if state else None
                nudge_count=int(state.nudge_count or 0) if state else 0
                # V3.44.16: the old guard (last_nudge_at >= last_active_at → skip
                # forever) allowed exactly ONE push per user lifetime — after it,
                # a silent user never heard from the bot again and D7 fell to 1%.
                # Now nudges repeat (spaced, capped) while the user stays away,
                # and a fresh silence cycle after a return resets the ladder.
                returned=bool(last_nudge and u.last_active_at and u.last_active_at>last_nudge)
                if last_nudge and not returned:
                    if (now-last_nudge).total_seconds() < RETENTION_NUDGE_INTERVAL_HOURS*3600: continue
                    if nudge_count >= RETENTION_MAX_NUDGES: continue
                # V3.55.9: consume the slot BEFORE spending money. The stamp used
                # to be written only after a successful send, so every failed send
                # (user blocked the bot, flood-wait, Telegram 4xx) left the user
                # eligible again an hour later — the hourly scan re-burned the
                # whole proactive LLM budget on unreachable users.
                st=state
                if st is None:
                    # V3.44.16: a user without an Anna state row used to be re-nudged
                    # EVERY hour (the write phase silently skipped). Persist the stamp.
                    st=CharacterState(user_id=uid,character_id=CHARACTER_ID)
                    s.add(st)
                st.last_nudge_at=now
                st.nudge_count=1 if (returned or not last_nudge) else nudge_count+1
                # A pending hook is consumed by one proactive follow-up so Anna does not repeat it forever.
                st.pending_hook=None
                s.commit()
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
                # V3.44.2: per-character retention texts
                char_id = CHARACTER_ID if CHARACTER_ID else 'anna_01'
                msg=retention_features_service.get_retention_text(kind, char_id)
                await bot.send_message(telegram_id,msg)
                track_event(uid, 'retention_push_sent', metadata={'hours_inactive': hours, 'kind': kind, 'nudge': nudge_count + 1})
            else:
                msg=await proactive_reply(telegram_id,name,hours)
                if not msg:
                    # Provider hiccup: the slot is already spent — do not send
                    # an empty message (that used to raise and re-arm the retry).
                    logger.warning('proactive empty reply user=%s', telegram_id)
                    continue
                await bot.send_message(telegram_id,msg)
                track_event(uid, 'proactive_sent', metadata={'hours_inactive': hours, 'nudge': nudge_count + 1})
        except TelegramForbiddenError:
            # V3.55.9: 403 = the user blocked or deleted the bot — switch the
            # whole proactive rail off for them instead of retrying every hour.
            _mark_blocked(uid)
            logger.info('proactive disabled for blocked user=%s', uid)
        except Exception: logger.exception('proactive failed user=%s',uid)


async def _day1_hook(bot):
    """V3.44.16: the day-1 hook — young accounts that already went silent get
    ONE "your bonus wheel is waiting" push with an app button. D1 was 5%: the
    generic nudge arrives only after 24h of silence and (before the guard fix)
    fired once per lifetime, so most fresh users simply evaporated on day 1-2."""
    if not PUBLIC_BASE_URL:
        return
    now=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    young=now-dt.timedelta(hours=DAY1_HOOK_MAX_ACCOUNT_HOURS)
    silent=now-dt.timedelta(hours=DAY1_HOOK_MIN_INACTIVE_HOURS)
    with SessionLocal() as s:
        users=s.scalars(select(User).where(
            User.day1_hook_at.is_(None),
            User.proactive_enabled==True,
            User.created_at>=young,
            User.last_active_at<=silent,
        )).all()
        snapshot=[(u.id,int(u.telegram_id),u.last_active_at) for u in users]
    if snapshot:
        logger.info('day1 hook due count=%s', len(snapshot))
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    from services.consent_service import has_accepted
    for uid,telegram_id,last_active in snapshot:
        try:
            if not has_accepted(telegram_id):
                continue
            markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                # V3.55.5: the wheel is retired — day-1 now opens the streak gift
                text='🎁 Забрать дневной подарок',
                web_app=WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp'),
            )]])
            await bot.send_message(telegram_id,(
                'я тут сижу и скучаю по тебе 🥺 '
                'а ещё — у тебя уже копится дневной подарок 🍑 заходи каждый день — '
                'на 7-й день дают 3 персика, серия сгорает, если пропустить день\n'
                'загляни в приложение (Магазин) и возвращайся ко мне 💋'
            ),reply_markup=markup)
            with SessionLocal() as s:
                u=s.get(User,uid)
                if u:
                    u.day1_hook_at=now
                    s.commit()
            track_event(uid, 'day1_hook_sent', metadata={'hours_inactive': int((now-last_active).total_seconds()/3600) if last_active else 0})
        except TelegramForbiddenError:
            # V3.55.9: blocked — burn the hook slot so the 15-min scan stops
            # re-pinging an address that can never receive it.
            _mark_blocked(uid)
            with SessionLocal() as s:
                u=s.get(User,uid)
                if u:
                    u.day1_hook_at=now
                    s.commit()
        except Exception: logger.exception('day1 hook failed user=%s',uid)

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
        # V3.21.0: notify_rituals is the per-user opt-out (NULL = legacy on).
        users=s.scalars(select(User).where(User.proactive_enabled==True,User.notify_rituals!=False,User.last_active_at>=fresh_cutoff)).all()
        snapshot=[(u.id,u.telegram_id,u.name or 'ты',u.streak_count or 0,u.timezone,u.selected_character or '') for u in users]
    today_key=now.date().isoformat()
    for uid,tg_id,name,streak,tz,sel_char in snapshot:
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
            # V3.44.2: per-character ritual messages
            # V3.56.7: the ritual belongs to the character the USER chats with,
            # and so does the attached pool photo — the global CHARACTER_ID
            # used to dress every girl's morning ping in Anna's media.
            char_id = sel_char or CHARACTER_ID or 'anna_01'
            text=retention_features_service.get_retention_text(kind, char_id)
            if kind=='morning':
                # V3.55.5: the morning ritual now carries a CONCRETE reason to
                # open the app — today's unclaimed streak gift (the wheel died
                # with it: one daily bonus per rail, integer peaches only).
                try:
                    from services import gift_service
                    gs=gift_service.gift_status(int(tg_id))
                    if gs.get('enabled') and gs.get('available'):
                        text+=f"\n🎁 забирай дневной подарок +{gs.get('amount',1)} 🍑 в магазине приложения — на 7-й день дают 3"
                    elif gs.get('enabled') and not gs.get('claimed_today') and gs.get('capped'):
                        text+='\n🍑 копилка персиков полная — потрать, и подарок снова будет ждать'
                except Exception:
                    logger.exception('ritual gift check failed user=%s',uid)
            if streak and streak >= 3:
                text+=f'\n\nкстати, мы общаемся {streak} дней подряд 🔥 не прерывай серию 😉'
            # V3.47.2: if the owner loaded a media pool, the ritual arrives as a
            # real photo from her (clean, no watermark); else plain text.
            # V3.47.3: the pool also holds GIFs and videos — send by kind.
            shot = retention_features_service.random_proactive_photo(char_id)
            if shot:
                from aiogram.types import BufferedInputFile
                data, ctype, kind = shot
                if kind == 'gif':
                    await bot.send_animation(int(tg_id), BufferedInputFile(data, filename='ritual.mp4'), caption=text)
                elif kind == 'video':
                    await bot.send_video(int(tg_id), BufferedInputFile(data, filename='ritual.mp4'), caption=text)
                else:
                    await bot.send_photo(int(tg_id), BufferedInputFile(data, filename='ritual.jpg'), caption=text)
            else:
                await bot.send_message(int(tg_id),text)
            _ritual_sent.add(guard)
            track_event(uid, f'ritual_{kind}_sent', metadata={'streak': streak, 'tz': tz})
        except TelegramForbiddenError:
            # V3.55.9: blocked — consume today's ritual slot and switch the
            # proactive rail off (the 30-min scan used to retry all day).
            _ritual_sent.add((uid,'blocked',today_key))
            _mark_blocked(uid)
        except Exception: logger.exception('ritual failed user=%s',uid)

async def _donation_reminder(bot):
    """V3.31.3: weekly «support the project» ping to active, opted-in users.
    The job runs often, but each user is gated by last_donation_ping_at in the
    DB (once per DONATION_REMINDER_INTERVAL_DAYS), so a Railway redeploy can
    never double-send within the week."""
    if not DONATION_REMINDER_ENABLED or not DONATION_LINK:
        return
    now=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    rows=await asyncio.to_thread(donation_service.due_donation_pings, now)
    if rows:
        logger.info('donation reminder due count=%s', len(rows))
    for uid,tg_id,lang in rows:
        try:
            await bot.send_message(int(tg_id), donation_service.donation_appeal(lang), reply_markup=donation_service.donation_keyboard(lang))
            await asyncio.to_thread(donation_service.mark_donation_ping_sent, uid, now)
            track_event(uid, 'donation_reminder_sent', metadata={'lang': lang})
        except Exception: logger.exception('donation reminder failed user=%s', uid)

async def _random_gifts(bot):
    """V3.44.2: random photo gifts from character - sends 1-2 times per day."""
    now=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    fresh_cutoff=now-dt.timedelta(days=RITUAL_MAX_INACTIVE_DAYS)
    with SessionLocal() as s:
        users=s.scalars(select(User).where(User.proactive_enabled==True,User.notify_rituals!=False,User.last_active_at>=fresh_cutoff)).all()
        snapshot=[(u.id,u.telegram_id,u.selected_character or CHARACTER_ID) for u in users]
    # Random 10% of users get a gift each run
    for uid,tg_id,char_id in snapshot:
        if random.random() > 0.1: continue  # 10% chance
        try:
            msg=retention_features_service.get_character_gift(char_id)
            await bot.send_message(int(tg_id), msg)
            track_event(uid, 'random_gift_sent', metadata={'character_id': char_id})
        except Exception: logger.exception('random gift failed user=%s',uid)

async def _daily_compatibility(bot):
    """V3.44.2: daily compatibility forecast - once per day in morning window."""
    now=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    fresh_cutoff=now-dt.timedelta(days=RITUAL_MAX_INACTIVE_DAYS)
    with SessionLocal() as s:
        users=s.scalars(select(User).where(User.proactive_enabled==True,User.notify_rituals!=False,User.last_active_at>=fresh_cutoff)).all()
        snapshot=[(u.id,u.telegram_id,u.selected_character or CHARACTER_ID) for u in users]
    today_key=now.date().isoformat()
    for uid,tg_id,char_id in snapshot:
        try:
            guard=(uid,'compatibility',today_key)
            if guard in _ritual_sent: continue
            forecast=retention_features_service.get_daily_compatibility()
            await bot.send_message(int(tg_id), forecast)
            _ritual_sent.add(guard)
            track_event(uid, 'compatibility_forecast_sent', metadata={'character_id': char_id})
        except Exception: logger.exception('compatibility forecast failed user=%s',uid)

async def _mood_update(bot):
    """V3.44.2: update character mood based on user activity."""
    now=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    cutoff=now-dt.timedelta(hours=24)
    with SessionLocal() as s:
        users=s.scalars(select(User).where(User.last_active_at>=cutoff)).all()
        snapshot=[(u.id,u.selected_character or CHARACTER_ID) for u in users]
    for uid,char_id in snapshot:
        try:
            with SessionLocal() as s:
                state=s.scalar(select(CharacterState).where(CharacterState.user_id==uid,CharacterState.character_id==char_id))
                if not state: continue
                # Update mood based on activity
                hours_since=now - state.updated_at
                if hours_since.total_seconds() < 3600:  # Active in last hour
                    state.mood='happy'
                    state.energy=min(1.0, state.energy + 0.1)
                elif hours_since.total_seconds() < 86400:  # Active today
                    state.mood='neutral'
                else:  # Inactive
                    state.mood='sad'
                    state.energy=max(0.0, state.energy - 0.1)
                s.commit()
        except Exception: logger.exception('mood update failed user=%s',uid)

# V3.45.0: ежедневный подарок «Подарок от неё» — бесплатное фото раз в день
async def _daily_gift(bot):
    try:
        today = dt.date.today()
        # V3.56.0: the gift photo now comes from the free pool (see
        # send_daily_gift), but we still only push to users who opted in and
        # were recently active — a dead account gets nothing, and the cap is
        # trimmed from 50 to 15 so even pool sends stay a courtesy, not spam.
        fresh_cutoff = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(days=RITUAL_MAX_INACTIVE_DAYS)
        with SessionLocal() as s:
            users = s.execute(select(User).where(
                ((User.last_daily_gift_date != today) | (User.last_daily_gift_date.is_(None))),
                User.proactive_enabled == True,
                User.last_active_at >= fresh_cutoff,
            )).scalars().all()
            user_ids = [u.telegram_id for u in users if u.telegram_id]
        if not user_ids:
            return
        # Отправляем подарок случайным активным пользователям (макс 15 в день)
        import random
        targets = random.sample(user_ids, min(15, len(user_ids)))
        from services.private_photo_service import send_daily_gift
        sent = 0
        for tid in targets:
            try:
                if await send_daily_gift(tid, bot):
                    sent += 1
                await asyncio.sleep(1)  # Не перегружать API
            except TelegramForbiddenError:
                _mark_blocked(int(tid))
            except Exception:
                logger.exception('daily gift failed user=%s', tid)
        logger.info('daily gifts sent count=%s/%s', sent, len(targets))
    except Exception:
        logger.exception('daily gift job failed')

def _user_local_hour_simple(tz_name) -> int | None:
    """Same as _user_local_hour but takes a raw timezone string (the session that
    loaded the User row is already closed when the life-events loop runs)."""
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo(tz_name or 'UTC')).hour
    except Exception:
        return dt.datetime.now(dt.timezone.utc).hour


def _daypart(hour: int | None) -> str:
    if hour is None:
        return 'day'
    if 5 <= hour < 11:
        return 'morning'
    if 11 <= hour < 17:
        return 'day'
    if 17 <= hour < 22:
        return 'evening'
    return 'night'


def _in_quiet_hours(hour: int | None) -> bool:
    """Wrap-aware quiet window [start, end). 23→7 blocks 23,0..6 but allows 8..22."""
    if hour is None:
        return False
    start, end = LIFE_EVENTS_QUIET_START_HOUR, LIFE_EVENTS_QUIET_END_HOUR
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


async def _life_events(bot):
    """V3.52.0: «Жизнь без тебя» — she occasionally writes first about something
    from her own day (grounded in HER personality + shared memory), never as a
    guilt/«why don't you text» nudge. Only for recently-active opted-in users;
    photos come from the existing media pool only (no provider render). The
    message is persisted into the shared dialog so it lights up the Mini App
    «Чаты» tab as new, and carries one-tap reply buttons to move reply-rate."""
    if not LIFE_EVENTS_ENABLED or LIFE_EVENTS_MAX_PER_DAY <= 0:
        return
    from services.consent_service import has_accepted
    from services.life_event_service import build_life_moment
    from services.memory_service import save_message
    from services import webapp_service
    from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    fresh_cutoff = now - dt.timedelta(days=LIFE_EVENTS_ACTIVE_WINDOW_DAYS)
    with SessionLocal() as s:
        users = s.scalars(select(User).where(
            User.proactive_enabled == True,
            User.notify_rituals != False,
            User.last_active_at >= fresh_cutoff,
        )).all()
        snapshot = [(u.id, int(u.telegram_id), u.name or 'ты',
                     (u.selected_character or CHARACTER_ID), u.timezone) for u in users]
    today_key = now.date().isoformat()
    for uid, tg_id, _name, char_id, tz in snapshot:
        try:
            if not has_accepted(tg_id):
                continue
            local_hour = _user_local_hour_simple(tz)
            if _in_quiet_hours(local_hour):
                continue
            part = _daypart(local_hour)
            prior = _life_events_store.get(tg_id) or {}
            slots = list(prior.get('slots') or []) if prior.get('date') == today_key else []
            if part in slots or len(slots) >= LIFE_EVENTS_MAX_PER_DAY:
                continue
            # Sprinkle sends across the scan window instead of firing at the
            # boundary for everyone at once (also keeps the LLM load flat).
            if random.random() > 0.35:
                continue
            moment = await build_life_moment(tg_id, char_id, when=part)
            # Consume the slot whether or not text came back, so an empty/no-LLM
            # day does not retry the provider every scan.
            slots.append(part)
            _life_events_store[tg_id] = {'date': today_key, 'slots': slots}
            if not moment or not moment.get('text'):
                continue
            text = moment['text']
            photo = moment.get('photo')
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=lbl, callback_data=cb)] for lbl, cb in (moment.get('options') or [])
            ])
            media_kind = media_url = None
            if photo:
                data, ctype, pkind = photo
                ext = 'jpg' if pkind not in ('gif', 'video') else 'mp4'
                media_kind = 'video' if pkind in ('gif', 'video') else 'photo'
                filename = webapp_service.save_chat_media(tg_id, data, ext, ctype)
                media_url = f'/webapp/media/{filename}'
            # Persist into the SHARED dialog BEFORE delivering, so the Mini App
            # «Чаты» badge (assistant msg newer than last read) lights up.
            save_message(uid, char_id, 'assistant', text, media_kind=media_kind, media_url=media_url)
            if media_url:
                if pkind == 'gif':
                    await bot.send_animation(tg_id, BufferedInputFile(data, filename='life.mp4'), caption=text, reply_markup=markup)
                elif pkind == 'video':
                    await bot.send_video(tg_id, BufferedInputFile(data, filename='life.mp4'), caption=text, reply_markup=markup)
                else:
                    await bot.send_photo(tg_id, BufferedInputFile(data, filename='life.jpg'), caption=text, reply_markup=markup)
            else:
                await bot.send_message(tg_id, text, reply_markup=markup)
            track_event(uid, 'life_event_sent', metadata={'character_id': char_id, 'when': part, 'has_photo': bool(media_url)})
        except TelegramForbiddenError:
            # V3.55.9: blocked — the slot is already consumed above; take the
            # whole proactive rail off so no LLM money goes to this user.
            _mark_blocked(uid)
        except Exception:
            logger.exception('life event failed user=%s', uid)

def start_scheduler(bot):
    scheduler.add_job(_reminders,'interval',seconds=30,args=[bot],id='reminders',replace_existing=True)
    scheduler.add_job(_proactive,'interval',hours=1,args=[bot],id='proactive',replace_existing=True)
    # V3.44.16: the day-1 hook scans often but sends at most once per user.
    scheduler.add_job(_day1_hook,'interval',minutes=15,args=[bot],id='day1_hook',replace_existing=True)
    if RITUALS_ENABLED:
        scheduler.add_job(_rituals,'interval',minutes=30,args=[bot],id='rituals',replace_existing=True)
    if DONATION_REMINDER_ENABLED and DONATION_LINK:
        scheduler.add_job(_donation_reminder,'interval',hours=12,args=[bot],id='donation_reminder',replace_existing=True)
    # V3.44.2: new retention jobs
    scheduler.add_job(_random_gifts,'interval',hours=6,args=[bot],id='random_gifts',replace_existing=True)
    scheduler.add_job(_daily_compatibility,'interval',hours=12,args=[bot],id='daily_compatibility',replace_existing=True)
    scheduler.add_job(_mood_update,'interval',hours=1,args=[bot],id='mood_update',replace_existing=True)
    # V3.45.0: ежедневный подарок — раз в день в 12:00
    scheduler.add_job(_daily_gift,'cron',hour=12,minute=0,args=[bot],id='daily_gift',replace_existing=True)
    # V3.52.0: «Жизнь без тебя» — scans often, but the persisted slot log caps each
    # user to LIFE_EVENTS_MAX_PER_DAY spontaneous messages per day.
    if LIFE_EVENTS_ENABLED:
        scheduler.add_job(_life_events,'interval',minutes=LIFE_EVENTS_SCAN_MINUTES,args=[bot],id='life_events',replace_existing=True)
    if not scheduler.running: scheduler.start()
