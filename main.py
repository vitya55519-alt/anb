import asyncio, logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, BufferedInputFile
from aiogram.utils.chat_action import ChatActionSender

from config import TELEGRAM_TOKEN, PREMIUM_MONTHLY_STARS, PHOTO_COST_STARS, CUSTOM_PHOTO_COST_STARS, ADMIN_TELEGRAM_IDS, CHARACTER_ID
from services.user_service import ensure_user, get_user, update_user_settings, touch_user
from services.chat_service import reply as anna_reply
from services.access_service import can_send_message, is_premium
from services.photo_service import PhotoRequest, parse_photo_request, deliver_photo, has_free_photo, build_photo_menu, create_offer, consume_offer, scene_allowed_for_stage, get_relationship_stage
from services.payments import record_payment, get_photo_credits
from services.reminder_service import set_timezone, create_from_text, cancel_active_wake
from services.scheduler_service import start_scheduler
from services.memory_service import reset_conversation as reset_memory
from services.db import SessionLocal
from models.relationship_models import UserCharacterRelationship, RelationshipEvent
from models.app_models import CharacterState, Reminder
from services.test_mode import STAGES, STAGE_LABELS, set_stage, clear_stage, get_stage
from services.voice_service import transcribe, synthesize_bytes, VALID_VOICES

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger=logging.getLogger('annabot')
bot=Bot(token=TELEGRAM_TOKEN)
dp=Dispatcher()

PHOTO_LABELS={'selfie':'📸 Селфи','home':'🏠 Дома','park':'🌿 В парке','cafe':'☕ В кафе','outfit':'👗 Образ','mirror':'🪞 Зеркало','evening':'✨ Вечер','fashion':'💎 Fashion','lingerie':'🖤 Бельевой fashion'}

def photo_keyboard():
    rows=[]; items=list(PHOTO_LABELS.items())
    for i in range(0,len(items),2): rows.append([InlineKeyboardButton(text=label,callback_data=f'photo:{scene}') for scene,label in items[i:i+2]])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def premium_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f'⭐ Premium — {PREMIUM_MONTHLY_STARS} Stars / 30 дней',callback_data='buy:premium')]])

async def send_stars_invoice(chat_id:int,title:str,description:str,payload:str,stars:int):
    await bot.send_invoice(chat_id=chat_id,title=title,description=description,payload=payload,currency='XTR',prices=[LabeledPrice(label=title,amount=stars)],provider_token='')

async def send_photo_or_offer(message:types.Message, req:PhotoRequest):
    tid=message.from_user.id; stage=get_relationship_stage(tid)
    free_ok=has_free_photo(tid) and scene_allowed_for_stage(req.scene,stage)
    credits=get_photo_credits(tid)
    try:
        async with ChatActionSender.upload_photo(bot=bot,chat_id=message.chat.id):
            if free_ok:
                await deliver_photo(bot,message.chat.id,tid,req,'free')
                return
            if credits>0:
                await deliver_photo(bot,message.chat.id,tid,req,'credit')
                return
    except Exception:
        logger.exception('photo generation failed user=%s',tid)
        await message.answer('фото сейчас не получилось 😕 попробуй ещё раз чуть позже')
        return
    offer_id=create_offer(tid,req)
    await message.answer('бесплатный лимит/доступ для этого образа сейчас закончился. Могу сделать отдельное фото за Stars ✨')
    price=CUSTOM_PHOTO_COST_STARS if any((req.clothing,req.hairstyle,req.location,req.angle)) else PHOTO_COST_STARS
    await send_stars_invoice(message.chat.id,'Фото Анны',f'Новое фото: {PHOTO_LABELS.get(req.scene,req.scene)}',f'photo:{offer_id}',price)

@dp.message(CommandStart())
async def start(message:types.Message):
    name=message.from_user.first_name or message.from_user.username or 'ты'
    ensure_user(message.from_user.id,name)
    await message.answer(f'привет, {name} 🙂 я Анна. ничего настраивать не надо — просто пиши мне.\n\nФото: /photo · Premium: /premium · настройки: /settings')

@dp.message(Command('help'))
async def help_cmd(message:types.Message):
    await message.answer('просто пиши мне как обычно 🙂\n/photo — фото\n/premium — Premium\n/settings — настройки\n/wake 08:00 — разбудить\n/timezone Europe/Moscow — часовой пояс\n/reset — очистить нашу переписку и память')

@dp.message(Command('settings'))
async def settings(message:types.Message):
    ensure_user(message.from_user.id,message.from_user.first_name)
    u=get_user(message.from_user.id); credits=get_photo_credits(message.from_user.id)
    await message.answer(f'Настройки Анны\n\nЧасовой пояс: {u.timezone}\nГолосовые ответы: {"вкл" if u.voice_enabled else "выкл"}\nИнициативные сообщения: {"вкл" if u.proactive_enabled else "выкл"}\nPremium: {"активен" if is_premium(message.from_user.id) else "нет"}\nФото-кредиты: {credits}\n\n/voice · /notifications · /timezone')

@dp.message(Command('premium'))
async def premium(message:types.Message):
    ensure_user(message.from_user.id,message.from_user.first_name)
    if is_premium(message.from_user.id):
        await message.answer(f'Premium уже активен ✨\nФото-кредиты: {get_photo_credits(message.from_user.id)}')
        return
    await message.answer('Premium на 30 дней:\n• расширенная память и полный лимит сообщений\n• до 4 обычных фото в день\n• 12 дополнительных photo credits\n• больше инициативных сообщений/continuity\n• приоритетные визуальные функции\n\nОтношения не покупаются — они развиваются из общения.',reply_markup=premium_keyboard())

@dp.callback_query(F.data=='buy:premium')
async def buy_premium(cq:types.CallbackQuery):
    ensure_user(cq.from_user.id,cq.from_user.first_name)
    await cq.answer()
    await send_stars_invoice(cq.message.chat.id,'Anna Premium','Premium-доступ на 30 дней','premium_month',PREMIUM_MONTHLY_STARS)

@dp.pre_checkout_query()
async def pre_checkout(query:types.PreCheckoutQuery):
    await query.answer(ok=True)

@dp.message(F.successful_payment)
async def successful_payment(message:types.Message):
    p=message.successful_payment; payload=p.invoice_payload; charge=p.telegram_payment_charge_id
    if payload=='premium_month':
        record_payment(message.from_user.id,'premium_month',p.total_amount,charge)
        await message.answer('готово ✨ Premium активирован на 30 дней, и я добавила 12 photo credits')
        return
    if payload.startswith('photo:'):
        try: offer_id=int(payload.split(':',1)[1])
        except ValueError: return
        req=consume_offer(message.from_user.id,offer_id)
        if not req:
            await message.answer('оплата прошла, но запрос фото уже устарел. Напиши /photo — кредит я сохраню.')
            record_payment(message.from_user.id,'photo',p.total_amount,charge); return
        record_payment(message.from_user.id,'photo',p.total_amount,charge)
        try:
            async with ChatActionSender.upload_photo(bot=bot,chat_id=message.chat.id):
                await deliver_photo(bot,message.chat.id,message.from_user.id,req,'credit')
        except Exception:
            logger.exception('paid photo generation failed user=%s',message.from_user.id)
            await message.answer('оплата сохранена как photo credit. фото сейчас не получилось — попробуй /photo позже, кредит не пропадёт.')

@dp.message(Command('photo','selfie'))
async def photo_menu(message:types.Message):
    ensure_user(message.from_user.id,message.from_user.first_name)
    info=build_photo_menu(message.from_user.id)
    await message.answer(f'что показать? 😌\nСегодня: {info["free_left"]} включённых фото · credits: {info["credits"]}',reply_markup=photo_keyboard())

@dp.callback_query(F.data.startswith('photo:'))
async def photo_callback(cq:types.CallbackQuery):
    await cq.answer(); scene=cq.data.split(':',1)[1]
    fake=cq.message
    # callback sender is the user; message.from_user is the bot, so generate directly with cq.from_user id
    tid=cq.from_user.id; ensure_user(tid,cq.from_user.first_name)
    req=PhotoRequest(scene=scene); stage=get_relationship_stage(tid)
    try:
        async with ChatActionSender.upload_photo(bot=bot,chat_id=cq.message.chat.id):
            if has_free_photo(tid) and scene_allowed_for_stage(scene,stage):
                await deliver_photo(bot,cq.message.chat.id,tid,req,'free'); return
            if get_photo_credits(tid)>0:
                await deliver_photo(bot,cq.message.chat.id,tid,req,'credit'); return
    except Exception:
        logger.exception('callback photo failed'); await cq.message.answer('с фото сейчас что-то не вышло 😕 попробуй ещё раз позже'); return
    offer_id=create_offer(tid,req)
    await send_stars_invoice(cq.message.chat.id,'Фото Анны',f'Новое фото: {PHOTO_LABELS.get(scene,scene)}',f'photo:{offer_id}',PHOTO_COST_STARS)

@dp.message(Command('voice'))
async def voice_toggle(message:types.Message):
    ensure_user(message.from_user.id,message.from_user.first_name); u=get_user(message.from_user.id); new=not u.voice_enabled
    update_user_settings(message.from_user.id,voice_enabled=new)
    await message.answer('голосовые ответы включены 🎙️' if new else 'голосовые ответы выключены')

@dp.message(Command('voice_style'))
async def voice_style(message:types.Message):
    parts=(message.text or '').split(maxsplit=1)
    if len(parts)<2 or parts[1] not in VALID_VOICES:
        await message.answer('Доступно: '+', '.join(VALID_VOICES)); return
    update_user_settings(message.from_user.id,voice_style=parts[1]); await message.answer(f'голос: {parts[1]} 🎙️')

@dp.message(Command('notifications'))
async def notifications(message:types.Message):
    ensure_user(message.from_user.id,message.from_user.first_name); u=get_user(message.from_user.id); new=not u.proactive_enabled
    update_user_settings(message.from_user.id,proactive_enabled=new)
    await message.answer('иногда буду писать первой 😌' if new else 'хорошо, первой писать не буду')

@dp.message(Command('timezone'))
async def timezone_cmd(message:types.Message):
    parts=(message.text or '').split(maxsplit=1)
    if len(parts)<2:
        ensure_user(message.from_user.id); await message.answer(f'Сейчас: {get_user(message.from_user.id).timezone}\nПример: /timezone Europe/Moscow'); return
    try: set_timezone(message.from_user.id,parts[1].strip()); await message.answer('готово, запомнила часовой пояс')
    except Exception: await message.answer('не узнаю такой часовой пояс. пример: Europe/Moscow')

@dp.message(Command('wake'))
async def wake_cmd(message:types.Message):
    rid=create_from_text(message.from_user.id,message.text or '')
    await message.answer('запомнила 😌 разбужу и немного понастойчивее, если не ответишь' if rid else 'напиши время, например /wake 08:00')

@dp.message(Command('reset'))
async def reset_cmd(message:types.Message):
    uid=ensure_user(message.from_user.id,message.from_user.first_name)
    reset_memory(uid,CHARACTER_ID)
    with SessionLocal() as s:
        rel=s.query(UserCharacterRelationship).filter_by(user_id=uid,character_id=CHARACTER_ID).first()
        if rel:
            s.query(RelationshipEvent).filter(RelationshipEvent.user_character_id==rel.id).delete(synchronize_session=False)
            s.delete(rel)
        st=s.query(CharacterState).filter_by(user_id=uid,character_id=CHARACTER_ID).first()
        if st:
            st.mood='neutral'; st.energy=.65; st.affection=.45; st.playfulness=.55; st.irritation=0; st.pending_hook=None
        s.query(Reminder).filter_by(user_id=uid).delete(synchronize_session=False); s.commit()
    clear_stage(message.from_user.id)
    await message.answer('готово. нашу переписку, память и развитие отношений начала заново.')

@dp.message(Command('testlevel','relationship_test'))
async def testlevel(message:types.Message):
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        await message.answer('эта команда только для владельца'); return
    parts=(message.text or '').split(maxsplit=1)
    if len(parts)<2:
        await message.answer('Использование: /testlevel 1..6 или /testlevel off'); return
    arg=parts[1].strip().lower()
    if arg=='off': clear_stage(message.from_user.id); await message.answer('тестовый уровень выключен'); return
    if not arg.isdigit() or not 1<=int(arg)<=6:
        await message.answer('нужен уровень от 1 до 6'); return
    stage=STAGES[int(arg)-1]; set_stage(message.from_user.id,stage); await message.answer(f'тест: {STAGE_LABELS[stage]}')

async def send_answer(message:types.Message,text:str):
    u=get_user(message.from_user.id)
    if u and u.voice_enabled:
        try:
            audio=await synthesize_bytes(text,u.voice_style); await message.answer_voice(BufferedInputFile(audio,filename='anna.ogg'))
            return
        except Exception: logger.exception('tts failed')
    await message.answer(text)

@dp.message(F.voice)
async def voice_message(message:types.Message):
    ensure_user(message.from_user.id,message.from_user.first_name); cancel_active_wake(message.from_user.id)
    if not can_send_message(message.from_user.id): await message.answer('на сегодня бесплатный лимит сообщений закончился. /premium'); return
    try:
        data=await bot.download(message.voice); text=await transcribe(data)
        async with ChatActionSender.typing(bot=bot,chat_id=message.chat.id): answer=await anna_reply(message.from_user.id,message.from_user.first_name or 'ты',text)
        await send_answer(message,answer)
        req=parse_photo_request(text)
        if req: await send_photo_or_offer(message,req)
        if create_from_text(message.from_user.id,text): await message.answer('и время тоже запомнила 😌')
        touch_user(message.from_user.id)
    except Exception:
        logger.exception('voice handler'); await message.answer('голосовое сейчас не получилось разобрать 😕')

@dp.message(F.text)
async def text_message(message:types.Message):
    if (message.text or '').startswith('/'): return
    ensure_user(message.from_user.id,message.from_user.first_name); cancel_active_wake(message.from_user.id)
    if not can_send_message(message.from_user.id): await message.answer('на сегодня бесплатный лимит сообщений закончился. Premium: /premium'); return
    text=message.text or ''
    try:
        async with ChatActionSender.typing(bot=bot,chat_id=message.chat.id): answer=await anna_reply(message.from_user.id,message.from_user.first_name or 'ты',text)
        await send_answer(message,answer)
        req=parse_photo_request(text)
        if req: await send_photo_or_offer(message,req)
        rid=create_from_text(message.from_user.id,text)
        if rid: await message.answer('запомнила 😌')
        touch_user(message.from_user.id)
    except Exception:
        logger.exception('chat handler user=%s',message.from_user.id); await message.answer('я сейчас немного зависла 😅 напиши ещё раз')

async def main():
    await bot.set_my_commands([
        types.BotCommand(command='start',description='Начать общение'),
        types.BotCommand(command='photo',description='📸 Фото Анны'),
        types.BotCommand(command='premium',description='⭐ Premium'),
        types.BotCommand(command='settings',description='Настройки'),
        types.BotCommand(command='voice',description='Голосовые ответы'),
        types.BotCommand(command='notifications',description='Инициативные сообщения'),
        types.BotCommand(command='wake',description='Будильник: /wake 08:00'),
        types.BotCommand(command='reset',description='Очистить память и историю'),
    ])
    start_scheduler(bot)
    logger.info('AnnaBot started')
    await dp.start_polling(bot)

if __name__=='__main__': asyncio.run(main())
