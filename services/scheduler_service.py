import asyncio, datetime as dt, logging, random
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from config import (
    PROACTIVE_MIN_HOURS, RETENTION_REMINDER_HOURS, CHARACTER_ID, DAILY_GIFT_JACKPOT_AMOUNT,
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
from services import partner_service
from services import retention_features_service
from services import dialog_store
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

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


def _mark_blocked_tg(telegram_id: int) -> None:
    """V3.63.1: same as _mark_blocked, keyed by Telegram id. The daily gift
    loop passed a Telegram id to _mark_blocked (users.id is INTEGER, so ids
    above 2^31 crashed Postgres with «integer out of range»)."""
    try:
        with SessionLocal() as s:
            uid = s.scalar(select(User.id).where(User.telegram_id == str(telegram_id)))
        if uid:
            _mark_blocked(uid)
    except Exception:
        logger.exception('mark blocked failed tg=%s', telegram_id)

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
                # V3.63.2: she wakes him herself — a line in her character,
                # as a voice note, with a stop button.
                from services import wake_service
                from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup
                idx=min(r.attempts,wake_service.WAKE_ATTEMPTS-1)
                char_id=user.selected_character or CHARACTER_ID
                line=await wake_service.wake_line(telegram_id,char_id,idx,name=user.name or '',lang=user.ui_lang or 'ru')
                kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='☀️ я проснулся',callback_data='wake:up')]])
                audio=await wake_service.wake_voice(line,char_id,user.voice_style)
                if audio:
                    await bot.send_voice(telegram_id,BufferedInputFile(audio,filename=f'{char_id}.ogg'),caption=line,reply_markup=kb)
                else:
                    await bot.send_message(telegram_id,line,reply_markup=kb)
                await asyncio.to_thread(mark_after_send,r.id,idx==wake_service.WAKE_ATTEMPTS-1,wake_service.WAKE_DELAYS[idx])
            else:
                await bot.send_message(telegram_id,f"напоминаю: {r.text}"); await asyncio.to_thread(mark_after_send,r.id,True)
        except TelegramForbiddenError:
            # V3.55.9: blocked user — drop the reminder instead of retrying it
            # every 30 seconds forever, and take the proactive rail off too.
            await asyncio.to_thread(mark_after_send,r.id,True)
            _mark_blocked(r.user_id)
            logger.info('reminder dropped (user blocked bot) id=%s', r.id)
        except Exception: logger.exception('reminder failed id=%s', r.id if r else None)

def _to_app_chat(uid, tg_id, char_id, text, shot=None) -> None:
    """V3.61.8: what she writes first also lands in the shared dialog, so the
    Mini App shows it in her chat with the «new» badge — the user opens the app
    and sees «ты где?» from her instead of the last thing he said himself.
    Saved after a successful send only: a blocked user gets no ghost history."""
    try:
        from services.memory_service import save_message
        media_kind = media_url = None
        if shot:
            from services import webapp_service
            data, ctype, pkind = shot
            moving = pkind in ('gif', 'video')
            filename = webapp_service.save_chat_media(int(tg_id), data, 'mp4' if moving else 'jpg', ctype)
            media_kind, media_url = ('video' if moving else 'photo'), f'/webapp/media/{filename}'
        save_message(uid, char_id, 'assistant', text, media_kind=media_kind, media_url=media_url)
    except Exception:
        logger.exception('proactive app-chat persist failed user=%s', uid)


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
                u=s.get(User,uid)
                if not u: continue
                # V3.59.0: the push comes from the girl this user actually talks
                # to — it used to always be the default heroine, so someone
                # chatting with Alena got «скучаю» from a stranger.
                char_id=(getattr(u,'selected_character','') or '').strip() or CHARACTER_ID
                state=s.scalar(select(CharacterState).where(CharacterState.user_id==uid,CharacterState.character_id==char_id))
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
                    st=CharacterState(user_id=uid,character_id=char_id)
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
                # V3.63.2: the plain «скучаю» became a story hook while the
                # user still has unused stories; cliffhanger/jealousy stay.
                if kind=='miss' and await _send_story(bot,uid,telegram_id,char_id):
                    track_event(uid, 'retention_push_sent', metadata={'hours_inactive': hours, 'kind': 'story', 'nudge': nudge_count + 1})
                    continue
                # V3.44.2: per-character retention texts
                msg=''
                if kind in ('cliffhanger','miss'):
                    # V3.101.0: the push picks up THE topic of his last talk (0 of
                    # 136 proactive pushes got a reply in 3 h) — the static line
                    # stays as the fallback when there is no talk to pick up.
                    try:
                        msg=await proactive_reply(telegram_id,name,hours,character_id=char_id,topic=True)
                    except Exception as topic_exc:
                        logger.warning('topic push failed user=%s: %s',uid,topic_exc)
                        msg=''
                    if msg:
                        kind=kind+'_topic'
                if not msg:
                    msg=retention_features_service.get_retention_text(kind, char_id)
                await bot.send_message(telegram_id,msg)
                _to_app_chat(uid,telegram_id,char_id,msg)
                track_event(uid, 'retention_push_sent', metadata={'hours_inactive': hours, 'kind': kind, 'nudge': nudge_count + 1})
            else:
                msg=await proactive_reply(telegram_id,name,hours,character_id=char_id,topic=True)
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
            # V3.63.2: a story hook first (Come Closer benchmark); the gift
            # text below stays as the fallback once every story was used.
            with SessionLocal() as s:
                _u=s.get(User,uid)
                _char=((getattr(_u,'selected_character','') or '').strip() if _u else '') or CHARACTER_ID
            if await _send_story(bot,uid,telegram_id,_char):
                with SessionLocal() as s:
                    u=s.get(User,uid)
                    if u:
                        u.day1_hook_at=now
                        s.commit()
                track_event(uid, 'day1_hook_sent', metadata={'hours_inactive': int((now-last_active).total_seconds()/3600) if last_active else 0, 'story': True})
                continue
            markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                # V3.55.5: the wheel is retired — day-1 now opens the streak gift
                text='🎁 Забрать дневной подарок',
                web_app=WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp'),
            )]])
            await bot.send_message(telegram_id,(
                'я тут сижу и скучаю по тебе 🥺 '
                'а ещё — у тебя уже копится дневной подарок 🍑 заходи каждый день — '
                f'на 7-й день дают {DAILY_GIFT_JACKPOT_AMOUNT} персиков, серия сгорает, если пропустить день\n'
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

_MEDIA_DIR = __import__('pathlib').Path(__file__).resolve().parents[1] / 'data' / 'media'


async def send_scenario_card(bot, uid: int | None, telegram_id: int, scenario, *, bonus: int | None = None):
    """V3.75.0: one scenario card (services/scenario_cards.py) — her looping
    cover, the setup, her quote and ONE button that opens the Mini App chat
    straight into the scene. Her opening line also lands in her dialog, so
    the app shows it and the model knows how the scene started."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    from config import SCENARIO_TAP_PEACHES
    from services import scenario_cards as sc
    cov=sc.cover(scenario.key)
    if not cov or not PUBLIC_BASE_URL:
        return None
    markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=scenario.button,
        web_app=WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp?open=chat&scene={scenario.key}'),
    )]])
    cap=sc.caption(scenario, SCENARIO_TAP_PEACHES if bonus is None else bonus)
    kind=cov.get('kind') or 'animation'
    method={'photo':'send_photo','video':'send_video'}.get(kind,'send_animation')
    msg=await getattr(bot,method)(telegram_id,cov['file_id'],caption=cap,parse_mode='HTML',reply_markup=markup)
    if uid:
        _to_app_chat(uid,telegram_id,scenario.character_id,sc.opening_line(scenario))
    return msg


def _scenario_local_hour(tz_name) -> int:
    """The audience is Russian and most rows still carry the default «UTC»,
    so an unset zone counts as Moscow for the evening window."""
    from zoneinfo import ZoneInfo
    name=(tz_name or '').strip()
    if name in ('','UTC','Etc/UTC'):
        name='Europe/Moscow'
    try:
        return dt.datetime.now(ZoneInfo(name)).hour
    except Exception:
        return dt.datetime.now(ZoneInfo('Europe/Moscow')).hour


async def _scenario_cards(bot):
    """V3.75.0: at most one scenario card a day per user, in his evening,
    while he is around (active in the last SCENARIO_ACTIVE_DAYS) but not
    chatting right now; never the same scene twice. Only scenes whose cover
    is already rendered go out, so nothing is sent before the admin makes
    covers in «/scenes»."""
    from config import (SCENARIO_CARDS_ENABLED, SCENARIO_INTERVAL_HOURS, SCENARIO_MIN_SILENT_HOURS,
                        SCENARIO_ACTIVE_DAYS, SCENARIO_LOCAL_START_HOUR, SCENARIO_LOCAL_END_HOUR)
    from services import scenario_cards as sc
    if not SCENARIO_CARDS_ENABLED or not PUBLIC_BASE_URL or not sc.covers():
        return
    from services.character_card_service import list_cards
    from services.consent_service import has_accepted
    now=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    try:
        available={c.character_id for c in list_cards(visible_only=True) if c.status=='active'}
    except Exception:
        logger.exception('scenario cards: cards load failed'); return
    with SessionLocal() as s:
        rows=s.execute(select(User.id,User.telegram_id,User.timezone,User.selected_character).where(
            User.proactive_enabled==True,
            User.adult_confirmed==True,
            User.last_active_at>=now-dt.timedelta(days=SCENARIO_ACTIVE_DAYS),
            User.last_active_at<=now-dt.timedelta(hours=SCENARIO_MIN_SILENT_HOURS),
        )).all()
    sent=0
    for uid,tg,tz,selected in rows:
        try:
            if not (SCENARIO_LOCAL_START_HOUR <= _scenario_local_hour(tz) < SCENARIO_LOCAL_END_HOUR):
                continue
            telegram_id=int(tg)
            last=sc.last_sent_at(telegram_id)
            if last and now-last < dt.timedelta(hours=SCENARIO_INTERVAL_HOURS):
                continue
            if not has_accepted(telegram_id):
                continue
            scenario=sc.pick_next(telegram_id,available,current=(selected or '').strip() or CHARACTER_ID)
            if not scenario:
                continue
            # consume the slot first — a failed send must not re-fire every scan
            sc.mark_sent(telegram_id,scenario.key)
            if await send_scenario_card(bot,uid,telegram_id,scenario):
                sent+=1
                track_event(uid,'scenario_card_sent',character_id=scenario.character_id,metadata={'key':scenario.key})
                await asyncio.sleep(0.05)
        except TelegramForbiddenError:
            _mark_blocked(uid)
        except Exception: logger.exception('scenario card failed user=%s',uid)
    if sent:
        logger.info('scenario cards sent=%s',sent)


def _media_pick(folder: str, prefer: str = '', exact: bool = False):
    """A photo from data/media/<folder>/ (owner-supplied, default heroine
    only): <prefer>.jpg when present, otherwise a random one (or None with
    ``exact``, so a story never gets a picture from another story)."""
    d = _MEDIA_DIR / folder
    try:
        files = sorted(p for p in d.iterdir() if p.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp'))
    except Exception:
        return None
    if not files:
        return None
    for f in files:
        if prefer and f.stem == prefer:
            return f
    return None if exact else random.choice(files)


def _offer_reference(char_id: str):
    """Photo of the girl for the locked offer card: the owner's own picks in
    data/media/offer/ for the default heroine, else her reference photo
    (default heroine as the fallback, e.g. for constructor personas)."""
    from pathlib import Path
    if (char_id or CHARACTER_ID) == CHARACTER_ID:
        picked = _media_pick('offer')
        if picked:
            return picked
    return _reference_photo(char_id)


def _reference_photo(char_id: str):
    """Her canonical everyday reference (Anna: the café shot)."""
    from pathlib import Path
    try:
        from services.character_registry import get_character
        from services.photo_service import _seedream_reference_path
        return _seedream_reference_path(get_character(char_id or CHARACTER_ID))
    except Exception:
        return Path(__file__).resolve().parents[1] / 'data' / 'references' / 'anna' / '01_anna_canonical_look_v3.png'


async def _send_story(bot, uid: int, telegram_id: int, char_id: str) -> bool:
    """V3.63.2: a story hook (services/story_hooks.py) — her photo, a tiny
    story and two choice buttons. False when this user has used them all."""
    from services import story_hooks
    from services.ui_lang import user_lang, EN
    from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup
    story=story_hooks.pick_unused(telegram_id)
    if story is None:
        return False
    story_hooks.mark_used(telegram_id, story.key)
    lang='en' if user_lang(telegram_id)==EN else 'ru'
    markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=story_hooks.label(story.a,lang),callback_data=f'story:{story.key}:a')],
        [InlineKeyboardButton(text=story_hooks.label(story.b,lang),callback_data=f'story:{story.key}:b')],
    ])
    body=story_hooks.text(story,lang)
    photo=None
    # V3.63.2: the owner's own photos of THIS girl (uploaded via /storyphoto,
    # kept as Telegram file_ids) come first for stories where they fit.
    from services import push_photos
    file_id=push_photos.pick(char_id or CHARACTER_ID) if story.photo_ok else None
    if file_id:
        await bot.send_photo(telegram_id,file_id,caption=body,reply_markup=markup)
        _to_app_chat(uid,telegram_id,char_id or CHARACTER_ID,body)
        track_event(uid,'story_hook_sent',metadata={'story':story.key,'photo':'owner'})
        return True
    # Only the default heroine's reference is a known everyday (café) shot;
    # other girls get the text-only story rather than a random reference.
    if (char_id or CHARACTER_ID)==CHARACTER_ID:
        try:
            def _jpg():
                import io
                from PIL import Image
                src=_media_pick('stories',story.key,exact=True) or _reference_photo(char_id)
                img=Image.open(src).convert('RGB'); img.thumbnail((900,1200))
                buf=io.BytesIO(); img.save(buf,'JPEG',quality=86); return buf.getvalue()
            photo=await asyncio.to_thread(_jpg)
        except Exception:
            logger.exception('story photo failed user=%s',uid)
    if photo:
        await bot.send_photo(telegram_id,BufferedInputFile(photo,filename='story.jpg'),caption=body,reply_markup=markup)
    else:
        await bot.send_message(telegram_id,body,reply_markup=markup)
    _to_app_chat(uid,telegram_id,char_id or CHARACTER_ID,body)
    track_event(uid,'story_hook_sent',metadata={'story':story.key})
    return True


async def _first_offer(bot):
    """V3.63.2: the first-evening offer (services/first_offer_service.py) —
    one locked-photo card per fresh, interested user, so the paid offer is
    actually seen instead of waiting for a daily limit nobody reaches."""
    from services import first_offer_service as fos
    if not fos.FIRST_OFFER_ENABLED:
        return
    from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    from services.access_service import is_premium
    from services.consent_service import has_accepted
    from services.ui_lang import user_lang, EN
    from config import ADMIN_TELEGRAM_IDS
    try:
        rows=await asyncio.to_thread(fos.candidates)
    except Exception:
        logger.exception('first offer scan failed'); return
    for uid,telegram_id,char_id in rows:
        try:
            if telegram_id in ADMIN_TELEGRAM_IDS or fos.already_offered(telegram_id):
                continue
            if not has_accepted(telegram_id) or is_premium(telegram_id):
                continue
            # consume the slot first — a failed send must not re-fire every scan
            fos.mark_offered(telegram_id)
            lang=user_lang(telegram_id)
            label='just for you' if lang==EN else 'только для тебя'
            # V3.63.2: her own photo (owner upload) blurred into the cover when
            # there is one; otherwise the repo's pre-blurred cover / reference.
            from services import push_photos
            source=_offer_reference(char_id)
            fid=push_photos.pick(char_id or CHARACTER_ID)
            if fid:
                try:
                    source=await bot.download(fid)
                except Exception:
                    logger.warning('first offer photo download failed user=%s',uid)
            card=await asyncio.to_thread(fos.locked_card,source,label)
            buttons=[[InlineKeyboardButton(text='🔓 open' if lang==EN else '🔓 открыть',callback_data='first_offer:open')]]
            if PUBLIC_BASE_URL:
                buttons.append([InlineKeyboardButton(text='💬 reply to her' if lang==EN else '💬 ответить ей',
                                                     web_app=WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp?open=chat'))])
            await bot.send_photo(telegram_id,BufferedInputFile(card,filename='for_you.jpg'),
                                 caption=fos.caption('en' if lang==EN else 'ru'),
                                 reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
            track_event(uid,'first_offer_sent',character_id=char_id or CHARACTER_ID)
        except TelegramForbiddenError:
            _mark_blocked(uid)
        except Exception: logger.exception('first offer failed user=%s',uid)


def _user_local_hour(user) -> int | None:
    """Best-effort local hour for rituals; None when the timezone is unusable."""
    try:
        from zoneinfo import ZoneInfo
        tz=ZoneInfo(user.timezone or 'UTC')
        return dt.datetime.now(tz).hour
    except Exception:
        return dt.datetime.now(dt.timezone.utc).hour

# V3.59.2: (user_id, date) pairs whose morning ritual keeps last night's promise.
_ritual_promised: set = set()
# V3.64.8: the morning that keeps the promise says so once, in her words.
_PROMISE_KEPT = (
    'как обещала 😌 доброе утро',
    'доброе утро ☀️ обещала же, держи',
    'проснулся? это тебе, как и обещала 💋',
    'утро ☀️ вчера обещала, сегодня показываю',
)


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
            # V3.64.8: her words and the service promo no longer share one
            # caption («...составишь компанию?\n🎁 забирай дневной подарок»):
            # the caption is only her line, the gift is a button under it.
            gift_label=None
            if kind=='morning':
                # V3.55.5: the morning ritual now carries a CONCRETE reason to
                # open the app — today's unclaimed streak gift (the wheel died
                # with it: one daily bonus per rail, integer peaches only).
                try:
                    from services import gift_service
                    gs=gift_service.gift_status(int(tg_id))
                    if gs.get('enabled') and gs.get('available'):
                        gift_label=f"🎁 Забрать подарок +{gs.get('amount',1)} 🍑"
                except Exception:
                    logger.exception('ritual gift check failed user=%s',uid)
            # V3.47.2: if the owner loaded a media pool, the ritual arrives as a
            # real photo from her (clean, no watermark); else plain text.
            # V3.47.3: the pool also holds GIFs and videos — send by kind.
            # the evening only checks the pool (its photo waits for the morning),
            # so only a shot that is really sent counts in his rotation
            shot = retention_features_service.random_proactive_photo(char_id, user_id=uid if kind=='morning' else None)
            evening_voice=None
            if kind=='evening':
                # V3.101.0: «как прошёл день» tied to what she knows about him
                # (the template evening got replies from 10%).
                _el='ru'
                try:
                    from services.chat_service import morning_callback
                    from services.ui_lang import user_lang, EN
                    _el='en' if user_lang(int(tg_id))==EN else 'ru'
                    evening_text=await morning_callback(int(tg_id), name, _el, char_id, evening=True)
                    if evening_text:
                        text=evening_text
                        track_event(uid,'evening_callback_sent',character_id=char_id)
                    elif _el=='en':
                        # V3.107.0: the template pool is Russian-only — English
                        # users get an English evening (and hear it in English).
                        from services import evening_voice as _ev
                        text=_ev.en_evening_line()
                except Exception:
                    logger.exception('evening callback failed user=%s',uid)
                # V3.107.0: owner — the evening comes as her voice note, for
                # everyone, in his language. Only her own line is spoken.
                try:
                    from services import evening_voice as _ev
                    evening_voice=await _ev.voice_bytes(text, char_id, _el)
                except Exception:
                    logger.exception('evening voice failed user=%s',uid)
            # V3.110.0: owner — a photo of her comes with the evening voice
            # every evening. Only a ready photo (no new render), rotated per user.
            evening_shot=None
            if kind=='evening':
                try:
                    from services import evening_voice as _ev
                    evening_shot=await asyncio.to_thread(_ev.evening_photo, char_id, uid)
                except Exception:
                    logger.exception('evening photo failed user=%s',uid)
                    evening_shot=None
            # V3.59.2: the evening plants a reason to come back — a promise the
            # morning ritual keeps with a photo. Only promised when her media
            # pool can actually deliver one.
            # V3.110.0: with the evening photo there, the promise is dropped —
            # the photo is already in his hands tonight.
            if kind=='evening' and evening_shot:
                shot=evening_shot
            elif kind=='evening' and shot:
                text+=('\n\nand tomorrow morning I\'ll send you something, don\'t oversleep 😏' if _el=='en'
                       else '\n\nа завтра утром пришлю тебе кое-что, не проспи 😏')
                _ritual_promised.add((uid,(now+dt.timedelta(days=1)).date().isoformat()))
                shot=None  # the promise IS the hook; the photo waits for the morning
            elif kind=='morning' and shot and (uid,today_key) in _ritual_promised:
                # one greeting, not «доброе утро» glued onto another «утро»
                text=random.choice(_PROMISE_KEPT)
                _ritual_promised.discard((uid,today_key))
            if kind=='morning':
                # V3.97.0: when he talked to her yesterday, the morning picks
                # up THAT talk (his plans, their joke) instead of a template.
                try:
                    from services.chat_service import morning_callback
                    from services.ui_lang import user_lang, EN
                    _ml='en' if user_lang(int(tg_id))==EN else 'ru'
                    callback=await morning_callback(int(tg_id), name, _ml, char_id)
                    if callback:
                        text=callback if not text.startswith(tuple(_PROMISE_KEPT)) else text+'\n\n'+callback
                        track_event(uid,'morning_callback_sent',character_id=char_id)
                except Exception:
                    logger.exception('morning callback failed user=%s',uid)
            if streak and streak >= 3 and (not shot or evening_shot):
                text+=f'\n\nкстати, мы общаемся {streak} дней подряд 🔥 не прерывай серию 😉'
            markup=None
            if gift_label:
                if PUBLIC_BASE_URL:
                    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
                    markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                        text=gift_label, web_app=WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp'))]])
                else:
                    text+='\n\n'+gift_label.replace('Забрать подарок','дневной подарок ждёт в приложении,')
            if evening_voice and evening_shot:
                # photo first (quiet, no caption), then her voice with the words
                from aiogram.types import BufferedInputFile
                from services import evening_voice as _ev
                _pd, _pc, _pk = evening_shot
                await bot.send_photo(int(tg_id), BufferedInputFile(_pd, filename='evening.jpg'))
                await bot.send_voice(int(tg_id), BufferedInputFile(evening_voice, filename=f'{char_id}.ogg'), caption=_ev.caption(text), reply_markup=markup)
                track_event(uid, 'evening_voice_sent', character_id=char_id)
                track_event(uid, 'evening_photo_sent', character_id=char_id)
            elif evening_voice and not shot:
                from aiogram.types import BufferedInputFile
                from services import evening_voice as _ev
                await bot.send_voice(int(tg_id), BufferedInputFile(evening_voice, filename=f'{char_id}.ogg'), caption=_ev.caption(text), reply_markup=markup)
                track_event(uid, 'evening_voice_sent', character_id=char_id)
            elif shot:
                from aiogram.types import BufferedInputFile
                data, ctype, media_kind = shot
                if media_kind == 'gif':
                    await bot.send_animation(int(tg_id), BufferedInputFile(data, filename='ritual.mp4'), caption=text, reply_markup=markup)
                elif media_kind == 'video':
                    await bot.send_video(int(tg_id), BufferedInputFile(data, filename='ritual.mp4'), caption=text, reply_markup=markup)
                else:
                    await bot.send_photo(int(tg_id), BufferedInputFile(data, filename='ritual.jpg'), caption=text, reply_markup=markup)
                if evening_shot:
                    track_event(uid, 'evening_photo_sent', character_id=char_id)
            else:
                await bot.send_message(int(tg_id),text,reply_markup=markup)
            _to_app_chat(uid,tg_id,char_id,text,shot)
            _ritual_sent.add(guard)
            track_event(uid, f'ritual_{kind}_sent', metadata={'streak': streak, 'tz': tz})
        except TelegramForbiddenError:
            # V3.55.9: blocked — consume today's ritual slot and switch the
            # proactive rail off (the 30-min scan used to retry all day).
            _ritual_sent.add((uid,'blocked',today_key))
            _mark_blocked(uid)
        except TelegramBadRequest as e:
            # V3.63.1: «chat not found» = the user never opened the bot or the
            # account is gone; it failed every 30-min scan all day. Same as blocked.
            if 'chat not found' in str(e).lower():
                _ritual_sent.add((uid,'blocked',today_key))
                _mark_blocked(uid)
            else:
                logger.exception('ritual failed user=%s',uid)
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

async def _partner_nudge(bot):
    """V3.62.13: remind active users that the partner link pays real money
    (owner's ask). Daytime only (Moscow 11:00–21:59); gating lives in
    partner_service.due_partner_nudges (max 3, every 10 days)."""
    now=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    if not 8 <= now.hour < 19:
        return
    rows=await asyncio.to_thread(partner_service.due_partner_nudges, now)
    if not rows:
        return
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from services.referral_service import referral_link
    try:
        me=await bot.get_me()
    except Exception:
        logger.exception('partner nudge: get_me failed'); return
    for uid,tg_id,lang in rows[:200]:
        try:
            link=referral_link(me.username or 'bot', tg_id)
            kb=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text='📤 Share the link' if lang=='en' else '📤 Поделиться ссылкой', url=partner_service.partner_share_url(lang, link))],
                [InlineKeyboardButton(text='💰 My partner screen' if lang=='en' else '💰 Моя партнёрка', callback_data='partner:open')],
            ])
            await bot.send_message(int(tg_id), partner_service.partner_nudge_text(lang, link), reply_markup=kb, disable_web_page_preview=True)
            track_event(uid, 'partner_nudge_sent', metadata={'lang': lang})
        except TelegramForbiddenError:
            track_event(uid, 'partner_nudge_sent', metadata={'lang': lang, 'blocked': True})
            _mark_blocked(uid)
        except Exception: logger.exception('partner nudge failed user=%s', uid)
        await asyncio.sleep(0.05)

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
            _to_app_chat(uid,tg_id,char_id,msg)
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
                _mark_blocked_tg(tid)
            except TelegramBadRequest as e:
                if 'chat not found' in str(e).lower():
                    _mark_blocked_tg(tid)
                else:
                    logger.exception('daily gift failed user=%s', tid)
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

async def _channel_bonus_holds(bot):
    """V3.68.0: pay the channel bonus to users whose hold ran out and who are
    still subscribed; a user who left loses the hold. Pings the payout."""
    from config import CHANNEL_SUBSCRIBE_USERNAME, CHANNEL_SUBSCRIBE_BONUS_CREDITS
    from services import channel_bonus_service as cbs
    from services.payments import grant_photo_credits
    try:
        ids = await asyncio.to_thread(cbs.due_hold_ids)
    except Exception:
        logger.exception('channel bonus holds scan failed')
        return
    for tid in ids:
        try:
            member = await bot.get_chat_member(chat_id=f'@{CHANNEL_SUBSCRIBE_USERNAME}', user_id=tid)
        except Exception:
            logger.warning('channel bonus hold check failed user=%s', tid)
            continue
        if member.status not in ('member', 'administrator', 'creator'):
            await asyncio.to_thread(cbs.clear_hold, tid)
            continue
        balance = await asyncio.to_thread(grant_photo_credits, tid, CHANNEL_SUBSCRIBE_BONUS_CREDITS, 'channel_subscribe')
        await asyncio.to_thread(cbs.clear_hold, tid)
        if balance < 0:
            continue
        try:
            await bot.send_message(tid, f'🍑 Ты с нами уже {cbs.CHANNEL_BONUS_HOLD_DAYS} дня — спасибо, что остался в канале! '
                                        f'+{CHANNEL_SUBSCRIBE_BONUS_CREDITS} персиков уже на балансе 😘')
        except TelegramForbiddenError:
            _mark_blocked_tg(tid)
        except Exception:
            logger.warning('channel bonus ping failed user=%s', tid)
        await asyncio.sleep(0.5)


def _char_name(cid: str) -> str:
    try:
        from services.character_service import get_character
        return (get_character(cid) or {}).get('name') or cid
    except Exception:
        return cid


async def _weekly_report(bot):
    """V3.97.0: Monday 09:00 MSK — the week in one message to the admins."""
    from config import ADMIN_TELEGRAM_IDS
    from services import weekly_report
    try:
        data = await asyncio.to_thread(weekly_report.collect, 7)
        text = weekly_report.render(data, _char_name)
    except Exception:
        logger.exception('weekly report failed'); return
    for admin_id in ADMIN_TELEGRAM_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            logger.exception('weekly report send failed admin=%s', admin_id)


async def _first_minutes(bot):
    """V3.97.0: one nudge for the people who went quiet in their first ten
    minutes (services/first_minutes.py) — consent step or first message."""
    from services import first_minutes as fm
    if not fm.ENABLED:
        return
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    from services.consent_service import has_accepted
    from services.ui_lang import user_lang, EN
    try:
        rows = await asyncio.to_thread(fm.candidates)
    except Exception:
        logger.exception('first minutes scan failed'); return
    for uid, telegram_id, char_id in rows:
        try:
            stage = 'silent' if has_accepted(telegram_id) else 'consent'
            await asyncio.to_thread(fm.mark, uid, stage, char_id or CHARACTER_ID)
            en = user_lang(telegram_id) == EN
            if stage == 'consent':
                kb = [[InlineKeyboardButton(text='✅ I am 18+ · I accept the terms' if en else '✅ Мне есть 18 · принимаю условия',
                                            callback_data='consent:accept')]]
            elif PUBLIC_BASE_URL:
                kb = [[InlineKeyboardButton(text='💬 say hi' if en else '💬 написать ей',
                                            web_app=WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp?open=chat'))]]
            else:
                kb = []
            text = fm.text(stage, 'en' if en else 'ru')
            await bot.send_message(telegram_id, text,
                                   reply_markup=InlineKeyboardMarkup(inline_keyboard=kb) if kb else None)
            if stage == 'silent':
                _to_app_chat(uid, telegram_id, char_id or CHARACTER_ID, text)
            track_event(uid, 'first_minutes_nudge_sent', metadata={'stage': stage}, character_id=char_id or CHARACTER_ID)
        except TelegramForbiddenError:
            _mark_blocked(uid)
        except Exception:
            logger.exception('first minutes nudge failed user=%s', uid)


async def _trial_followup(bot):
    """V3.97.0: she writes before the 99 ₽ trial ends and once after it ran
    out (services/trial_followup.py) — with the week / month buttons."""
    from services import trial_followup as tf
    if not tf.ENABLED:
        return
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    from services.ui_lang import user_lang, EN
    from services.character_service import get_character
    from config import (PREMIUM_WEEKLY_STARS, PREMIUM_MONTHLY_STARS, PLATEGA_ENABLED,
                        PLATEGA_PREMIUM_WEEKLY_PRICE_RUB, PLATEGA_PREMIUM_PRICE_RUB)
    try:
        rows = await asyncio.to_thread(tf.candidates)
    except Exception:
        logger.exception('trial followup scan failed'); return
    for uid, telegram_id, char_id, stage in rows:
        try:
            # the slot first — a failed send must not re-fire every scan
            await asyncio.to_thread(tf.mark, uid, stage, char_id or CHARACTER_ID)
            lang = 'en' if user_lang(telegram_id) == EN else 'ru'
            try:
                name = (get_character(char_id or CHARACTER_ID) or {}).get('name', '')
            except Exception:
                name = ''
            text = tf.text(stage, name, lang)
            en = lang == 'en'
            from services import vip_offer
            if vip_offer.info(telegram_id).get('loyal'):
                # V3.104.0: his loyalty month (−50%) from the first payment.
                from services.renewal_care import stay_buttons
                kb = stay_buttons(telegram_id, en)
            else:
                kb = [[InlineKeyboardButton(text=(f'💗 a week — {PREMIUM_WEEKLY_STARS} Stars' if en
                                                  else f'💗 неделя — {PREMIUM_WEEKLY_STARS} Stars'),
                                            callback_data='buy:premium_week')]]
                if PLATEGA_ENABLED and not en:
                    kb.append([InlineKeyboardButton(text=f'💳 неделя — {PLATEGA_PREMIUM_WEEKLY_PRICE_RUB} ₽ · карта / СБП',
                                                    callback_data='platega:premium_week')])
                    kb.append([InlineKeyboardButton(text=f'💳 месяц — {PLATEGA_PREMIUM_PRICE_RUB} ₽ · карта / СБП',
                                                    callback_data='platega:premium_month')])
                else:
                    kb.append([InlineKeyboardButton(text=(f'⭐ a month — {PREMIUM_MONTHLY_STARS} Stars' if en
                                                          else f'⭐ месяц — {PREMIUM_MONTHLY_STARS} Stars'),
                                                    callback_data='buy:premium')])
            if PUBLIC_BASE_URL:
                kb.append([InlineKeyboardButton(text='💬 reply to her' if en else '💬 ответить ей',
                                                web_app=WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp?open=chat'))])
            await bot.send_message(telegram_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
            _to_app_chat(uid, telegram_id, char_id or CHARACTER_ID, text)
            track_event(uid, 'trial_followup_sent', metadata={'stage': stage}, character_id=char_id or CHARACTER_ID)
        except TelegramForbiddenError:
            _mark_blocked(uid)
        except Exception:
            logger.exception('trial followup failed user=%s', uid)


def _msk_daytime(now: dt.datetime | None = None) -> bool:
    """09:00–22:59 Moscow time: personal messages never wake him at night."""
    now = now or dt.datetime.now(dt.timezone.utc)
    return 9 <= (now.hour + 3) % 24 <= 22


async def _paid_day1(bot):
    """V3.104.0: the day after he paid she writes first about something he told
    her (services/paid_welcome.py). Once per payment; skipped while he is here."""
    from services import paid_welcome as pw
    if not (pw.DAY1_ENABLED and _msk_daytime()):
        return
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    from services.ui_lang import user_lang, EN
    from services.chat_service import paid_moment
    try:
        rows = await asyncio.to_thread(pw.day1_candidates)
    except Exception:
        logger.exception('paid day1 scan failed'); return
    for uid, telegram_id, char_id, product in rows:
        char_id = char_id or CHARACTER_ID
        try:
            # the slot first — a failed send must not re-fire every scan
            await asyncio.to_thread(pw.mark, uid, pw.DAY1_EVENT, char_id, product)
            lang = 'en' if user_lang(telegram_id) == EN else 'ru'
            text = await paid_moment(telegram_id, '', 'day1', language_code='en' if lang == 'en' else None,
                                     character_id=char_id) or pw.fallback('day1', lang)
            kb = None
            if PUBLIC_BASE_URL:
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                    text='💬 reply to her' if lang == 'en' else '💬 ответить ей',
                    web_app=WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp?open=chat'))]])
            await bot.send_message(telegram_id, text, reply_markup=kb)
            _to_app_chat(uid, telegram_id, char_id, text)
        except TelegramForbiddenError:
            _mark_blocked(uid)
        except Exception:
            logger.exception('paid day1 failed user=%s', uid)


async def _renewal_care(bot):
    """V3.104.0: a day before his paid week/month ends she remembers their talks
    and asks him to stay; once more after it ran out (services/renewal_care.py)."""
    from services import renewal_care as rc
    if not (rc.ENABLED and _msk_daytime()):
        return
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    from services.ui_lang import user_lang, EN
    from services.chat_service import paid_moment
    try:
        rows = await asyncio.to_thread(rc.candidates)
    except Exception:
        logger.exception('renewal care scan failed'); return
    for uid, telegram_id, char_id, stage, product in rows:
        char_id = char_id or CHARACTER_ID
        try:
            await asyncio.to_thread(rc.mark, uid, stage, char_id)
            lang = 'en' if user_lang(telegram_id) == EN else 'ru'
            en = lang == 'en'
            text = await paid_moment(telegram_id, '', 'renew_soon' if stage == 'soon' else 'renew_ended',
                                     language_code='en' if en else None, character_id=char_id) or rc.fallback(stage, lang)
            kb = rc.stay_buttons(telegram_id, en)
            if PUBLIC_BASE_URL:
                kb.append([InlineKeyboardButton(text='💬 reply to her' if en else '💬 ответить ей',
                                                web_app=WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp?open=chat'))])
            await bot.send_message(telegram_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
            _to_app_chat(uid, telegram_id, char_id, text)
            track_event(uid, 'renewal_care_sent', metadata={'stage': stage, 'product': product}, character_id=char_id)
        except TelegramForbiddenError:
            _mark_blocked(uid)
        except Exception:
            logger.exception('renewal care failed user=%s', uid)


async def _girl_of_day(bot):
    """V3.92.0: «🔥 Девушка дня» (switches at 03:00 MSK) — at 09:00 MSK the admins get
    the ready channel post with a «📣 В канал» button."""
    from config import ADMIN_TELEGRAM_IDS
    from services import girl_of_day
    for admin_id in ADMIN_TELEGRAM_IDS:
        try:
            await girl_of_day.send_admin_preview(bot, admin_id)
        except Exception:
            logger.exception('girl of day preview failed admin=%s', admin_id)


async def _db_backup(bot):
    """V3.82.0: Railway Hobby has no Postgres backups — dump the DB daily and
    send it to the admins as a Telegram document."""
    from config import ADMIN_TELEGRAM_IDS
    from services import backup_service
    from aiogram.types import BufferedInputFile
    if not ADMIN_TELEGRAM_IDS:
        return
    try:
        data, counts = await asyncio.to_thread(backup_service.dump_database)
    except Exception:
        logger.exception('db backup dump failed')
        for admin_id in ADMIN_TELEGRAM_IDS:
            try:
                await bot.send_message(admin_id, '⚠️ ежедневный бэкап базы не получился, смотри логи Railway (db backup).')
            except Exception:
                pass
        return
    caption = backup_service.summary_line(counts, len(data))
    logger.info('db backup ready bytes=%s tables=%s', len(data), len(counts))
    for admin_id in ADMIN_TELEGRAM_IDS:
        try:
            if len(data) > backup_service.TELEGRAM_DOC_LIMIT:
                await bot.send_message(admin_id, caption + '\n⚠️ файл больше лимита Telegram (50 МБ), не отправлен.')
                continue
            await bot.send_document(admin_id, BufferedInputFile(data, filename=backup_service.backup_filename()),
                                    caption=caption[:1000], disable_notification=True)
        except Exception:
            logger.exception('db backup send failed admin=%s', admin_id)


def start_scheduler(bot):
    scheduler.add_job(_reminders,'interval',seconds=30,args=[bot],id='reminders',replace_existing=True)
    scheduler.add_job(_proactive,'interval',hours=1,args=[bot],id='proactive',replace_existing=True)
    # V3.44.16: the day-1 hook scans often but sends at most once per user.
    scheduler.add_job(_day1_hook,'interval',minutes=15,args=[bot],id='day1_hook',replace_existing=True)
    scheduler.add_job(_first_offer,'interval',minutes=10,args=[bot],id='first_offer',replace_existing=True)
    scheduler.add_job(_trial_followup,'interval',minutes=15,args=[bot],id='trial_followup',replace_existing=True)
    # V3.104.0: next-day message after a payment, and «останешься?» before the end.
    scheduler.add_job(_paid_day1,'interval',minutes=15,args=[bot],id='paid_day1',replace_existing=True)
    scheduler.add_job(_renewal_care,'interval',minutes=15,args=[bot],id='renewal_care',replace_existing=True)
    scheduler.add_job(_first_minutes,'interval',minutes=3,args=[bot],id='first_minutes',replace_existing=True)
    scheduler.add_job(_weekly_report,'cron',day_of_week='mon',hour=6,minute=0,args=[bot],id='weekly_report',replace_existing=True)
    # V3.75.0: scenario cards — scans often, one card a day per user at most.
    scheduler.add_job(_scenario_cards,'interval',minutes=20,args=[bot],id='scenario_cards',replace_existing=True)
    if RITUALS_ENABLED:
        scheduler.add_job(_rituals,'interval',minutes=30,args=[bot],id='rituals',replace_existing=True)
    if DONATION_REMINDER_ENABLED and DONATION_LINK:
        scheduler.add_job(_donation_reminder,'interval',hours=12,args=[bot],id='donation_reminder',replace_existing=True)
    # V3.62.13: partner-program reminder (real-money referral payouts).
    scheduler.add_job(_partner_nudge,'interval',hours=2,args=[bot],id='partner_nudge',replace_existing=True)
    # V3.44.2: new retention jobs
    scheduler.add_job(_random_gifts,'interval',hours=6,args=[bot],id='random_gifts',replace_existing=True)
    scheduler.add_job(_daily_compatibility,'interval',hours=12,args=[bot],id='daily_compatibility',replace_existing=True)
    scheduler.add_job(_mood_update,'interval',hours=1,args=[bot],id='mood_update',replace_existing=True)
    # V3.68.0: channel bonus after the hold.
    scheduler.add_job(_channel_bonus_holds,'interval',hours=1,args=[bot],id='channel_bonus_holds',replace_existing=True)
    # V3.82.0: daily DB backup to the admins (00:30 UTC = 03:30 MSK, quiet hours).
    scheduler.add_job(_db_backup,'cron',hour=0,minute=30,args=[bot],id='db_backup',replace_existing=True)
    # V3.92.0: «🔥 Девушка дня» channel post for the admins at 09:00 MSK.
    scheduler.add_job(_girl_of_day,'cron',hour=6,minute=0,args=[bot],id='girl_of_day',replace_existing=True)
    # V3.45.0: ежедневный подарок — раз в день в 12:00
    scheduler.add_job(_daily_gift,'cron',hour=12,minute=0,args=[bot],id='daily_gift',replace_existing=True)
    # V3.52.0: «Жизнь без тебя» — scans often, but the persisted slot log caps each
    # user to LIFE_EVENTS_MAX_PER_DAY spontaneous messages per day.
    if LIFE_EVENTS_ENABLED:
        scheduler.add_job(_life_events,'interval',minutes=LIFE_EVENTS_SCAN_MINUTES,args=[bot],id='life_events',replace_existing=True)
    if not scheduler.running: scheduler.start()
