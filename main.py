import asyncio
import logging

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, BufferedInputFile, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.chat_action import ChatActionSender

from config import (
    TELEGRAM_TOKEN, PREMIUM_MONTHLY_STARS, PHOTO_COST_STARS, CUSTOM_PHOTO_COST_STARS,
    ADMIN_TELEGRAM_IDS, CHARACTER_ID,
)
from services.user_service import (
    ensure_user, get_user, update_user_settings, touch_user,
    set_adult_confirmed, is_adult_confirmed,
)
from services.chat_service import reply as anna_reply
from services.access_service import can_send_message, is_premium
from services.photo_service import (
    PhotoRequest, parse_photo_request, deliver_photo, has_free_photo, build_photo_menu,
    create_offer, consume_offer, scene_allowed_for_stage, get_relationship_stage,
    get_relationship_level, is_custom_request, requires_adult_confirmation,
    SCENE_LEVELS, PhotoGenerationError,
)
from services.payments import record_payment, get_photo_credits
from services.reminder_service import set_timezone, create_from_text, cancel_active_wake
from services.scheduler_service import start_scheduler
from services.memory_service import reset_conversation as reset_memory
from services.db import SessionLocal
from models.relationship_models import UserCharacterRelationship, RelationshipEvent
from models.app_models import CharacterState, Reminder
from services.test_mode import STAGES, STAGE_LABELS, set_stage, clear_stage
from services.voice_service import transcribe, synthesize_bytes, VALID_VOICES

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger('annabot')
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

PHOTO_LABELS = {
    'selfie': '📸 Селфи',
    'home': '🏠 Дома',
    'park': '🌿 В парке',
    'cafe': '☕ В кафе',
    'outfit': '👗 Образ',
    'mirror': '🪞 Зеркало',
    'evening': '✨ Вечер',
    'fashion': '💎 Fashion',
    'personal': '💌 Личное фото',
    'lingerie': '🖤 Приватный fashion',
}

PHOTO_MENU_ORDER = ['selfie', 'home', 'park', 'cafe', 'outfit', 'mirror', 'evening', 'fashion', 'personal', 'lingerie']
RELATIONSHIP_LEVEL_NAMES = {
    1: 'Знакомство',
    2: 'Симпатия',
    3: 'Близкое общение',
    4: 'Доверие',
    5: 'Очень близки',
    6: 'Связь',
}

# Short-lived UI state only. Paid offers themselves are persisted in PostgreSQL.
_custom_drafts: dict[int, dict] = {}
_pending_adult_photo: dict[int, PhotoRequest] = {}
_pending_adult_custom: set[int] = set()


def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='💬 Общение'), KeyboardButton(text='📸 Фото')],
            [KeyboardButton(text='🎭 Образы'), KeyboardButton(text='🚀 Премиум')],
            [KeyboardButton(text='👤 Профиль'), KeyboardButton(text='⚙️ Настройки')],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def premium_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f'⭐ Premium — {PREMIUM_MONTHLY_STARS} Stars / 30 дней', callback_data='buy:premium')
    ]])


def adult_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ Мне 18+', callback_data='age:yes')],
        [InlineKeyboardButton(text='↩️ Нет', callback_data='age:no')],
    ])


def photo_keyboard(telegram_id: int):
    level = get_relationship_level(telegram_id)
    unlocked = [scene for scene in PHOTO_MENU_ORDER if SCENE_LEVELS.get(scene, 99) <= level]
    rows = []
    for i in range(0, len(unlocked), 2):
        rows.append([
            InlineKeyboardButton(text=PHOTO_LABELS[scene], callback_data=f'photo:{scene}')
            for scene in unlocked[i:i + 2]
        ])

    # Show the NEXT unlock instead of hiding progression. This gives users a
    # concrete reason to continue the relationship without turning it into a paywall.
    future_levels = sorted({SCENE_LEVELS[s] for s in PHOTO_MENU_ORDER if SCENE_LEVELS.get(s, 99) > level})
    if future_levels:
        next_level = future_levels[0]
        locked = [s for s in PHOTO_MENU_ORDER if SCENE_LEVELS.get(s) == next_level]
        if level == 4 and next_level == 5:
            # Preview private fashion + paid customization together at the threshold.
            locked = locked[:1]
            rows.append([InlineKeyboardButton(
                text=f'🔒 {PHOTO_LABELS[locked[0]].replace("🖤 ", "")} · ур.{next_level}',
                callback_data=f'locked:{locked[0]}',
            )])
            rows.append([InlineKeyboardButton(
                text='🔒 ✨ Кастомное фото · ур.5',
                callback_data='locked:custom',
            )])
        else:
            for i in range(0, len(locked), 2):
                rows.append([
                    InlineKeyboardButton(
                        text=f'🔒 {PHOTO_LABELS[scene]} · ур.{next_level}',
                        callback_data=f'locked:{scene}',
                    )
                    for scene in locked[i:i + 2]
                ])

    if level >= 5:
        rows.append([InlineKeyboardButton(text=f'✨ Кастомное фото — {CUSTOM_PHOTO_COST_STARS}⭐', callback_data='custom:start')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def photo_retry_keyboard(scene: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔄 Повторить', callback_data=f'retry_photo:{scene}')],
        [InlineKeyboardButton(text='📸 Другой сюжет', callback_data='photo_menu:open')],
    ])


def photo_menu_text(telegram_id: int) -> str:
    info = build_photo_menu(telegram_id)
    level = info['level']
    name = RELATIONSHIP_LEVEL_NAMES.get(level, '')
    future = sorted({required for required in SCENE_LEVELS.values() if required > level})
    next_line = f'\n🔒 Следующие фото откроются на уровне {future[0]}/6' if future else '\n✨ Все уровни фото уже открыты'
    return (
        f'что показать? 😌\n'
        f'❤️ Близость: {level}/6 · {name}\n'
        f'🎁 Бесплатно сегодня: {info["free_left"]}/{info["limit"]} · credits: {info["credits"]}\n'
        f'📷 Один запрос = до {info["set_size"]} фото'
        f'{next_line}'
    )


def custom_color_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='🖤 Чёрный', callback_data='custom:color:black'),
            InlineKeyboardButton(text='🤍 Белый', callback_data='custom:color:white'),
            InlineKeyboardButton(text='❤️ Красный', callback_data='custom:color:red'),
        ]
    ])


def custom_addon_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🧦 Чулки', callback_data='custom:addon:stockings')],
        [InlineKeyboardButton(text='Без дополнения', callback_data='custom:addon:none')],
    ])


def custom_hair_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='Хвост', callback_data='custom:hair:ponytail'),
            InlineKeyboardButton(text='Пучок', callback_data='custom:hair:bun'),
            InlineKeyboardButton(text='Распущенные', callback_data='custom:hair:loose'),
        ]
    ])


def custom_place_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='🪞 Зеркало', callback_data='custom:place:mirror'),
            InlineKeyboardButton(text='🛋 Диван', callback_data='custom:place:sofa'),
        ],
        [InlineKeyboardButton(text='🏨 Отель', callback_data='custom:place:hotel')],
    ])


async def send_stars_invoice(chat_id: int, title: str, description: str, payload: str, stars: int):
    await bot.send_invoice(
        chat_id=chat_id,
        title=title,
        description=description,
        payload=payload,
        currency='XTR',
        prices=[LabeledPrice(label=title, amount=stars)],
        provider_token='',
    )


async def _offer_custom_photo(chat_id: int, telegram_id: int, request: PhotoRequest):
    offer_id = create_offer(telegram_id, request)
    await send_stars_invoice(
        chat_id,
        'Кастомное фото Анны',
        'Персональный образ: одежда / цвет / причёска / место / ракурс',
        f'photo:{offer_id}',
        CUSTOM_PHOTO_COST_STARS,
    )


async def handle_photo_request(chat_id: int, telegram_id: int, request: PhotoRequest):
    stage = get_relationship_stage(telegram_id)
    if not scene_allowed_for_stage(request.scene, stage):
        await bot.send_message(chat_id, 'такой образ я пока оставлю при себе 😏')
        return

    if requires_adult_confirmation(request) and not is_adult_confirmed(telegram_id):
        _pending_adult_photo[telegram_id] = request
        await bot.send_message(
            chat_id,
            'для более смелых fashion-образов нужно один раз подтвердить, что тебе 18+.',
            reply_markup=adult_keyboard(),
        )
        return

    # Owner can test all relationship levels without purchasing every test frame.
    if telegram_id in ADMIN_TELEGRAM_IDS:
        try:
            async with ChatActionSender.upload_photo(bot=bot, chat_id=chat_id):
                await deliver_photo(bot, chat_id, telegram_id, request, 'admin')
        except PhotoGenerationError as exc:
            logger.warning('admin photo generation failed provider=%s reason=%s user=%s', exc.provider, exc.reason, telegram_id)
            await bot.send_message(chat_id, 'фото сейчас не получилось 😕 лимит не списан.', reply_markup=photo_retry_keyboard(request.scene))
        except Exception:
            logger.exception('admin photo generation failed user=%s', telegram_id)
            await bot.send_message(chat_id, 'фото сейчас не получилось 😕 лимит не списан.', reply_markup=photo_retry_keyboard(request.scene))
        return

    # Personal changes are monetized as customization; relationship level itself is never sold.
    if is_custom_request(request):
        await _offer_custom_photo(chat_id, telegram_id, request)
        return

    credits = get_photo_credits(telegram_id)
    try:
        async with ChatActionSender.upload_photo(bot=bot, chat_id=chat_id):
            if has_free_photo(telegram_id):
                await deliver_photo(bot, chat_id, telegram_id, request, 'free')
                return
            if credits > 0:
                await deliver_photo(bot, chat_id, telegram_id, request, 'credit')
                return
    except PermissionError as exc:
        logger.info('photo denied user=%s reason=%s', telegram_id, exc)
        await bot.send_message(chat_id, 'этот вариант сейчас недоступен 😌')
        return
    except PhotoGenerationError as exc:
        logger.warning('photo generation failed provider=%s reason=%s user=%s scene=%s', exc.provider, exc.reason, telegram_id, request.scene)
        await bot.send_message(chat_id, 'фото сейчас не получилось 😕 лимит не списан. можно повторить.', reply_markup=photo_retry_keyboard(request.scene))
        return
    except Exception:
        logger.exception('photo generation failed user=%s', telegram_id)
        await bot.send_message(chat_id, 'фото сейчас не получилось 😕 лимит не списан. можно повторить.', reply_markup=photo_retry_keyboard(request.scene))
        return

    offer_id = create_offer(telegram_id, request)
    await bot.send_message(chat_id, f'бесплатный лимит на сегодня использован. следующее фото — {PHOTO_COST_STARS}⭐ ✨')
    await send_stars_invoice(
        chat_id,
        'Фото Анны',
        f'Новый сет до 3 фото: {PHOTO_LABELS.get(request.scene, request.scene)}',
        f'photo:{offer_id}',
        PHOTO_COST_STARS,
    )


@dp.message(CommandStart())
async def start(message: types.Message):
    name = message.from_user.first_name or message.from_user.username or 'ты'
    ensure_user(message.from_user.id, name)
    await message.answer(
        f'привет, {name} 🙂 я Анна. ничего настраивать не надо — просто пиши.',
        reply_markup=main_keyboard(),
    )


@dp.message(Command('help'))
async def help_cmd(message: types.Message):
    await message.answer(
        'просто пиши мне как обычно 🙂\n/photo — фото\n/premium — Premium\n/settings — настройки\n'
        '/wake 08:00 — разбудить\n/timezone Europe/Moscow — часовой пояс\n/reset — очистить переписку и память'
    )


@dp.message(Command('settings'))
async def settings(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name)
    user = get_user(message.from_user.id)
    credits = get_photo_credits(message.from_user.id)
    await message.answer(
        f'Настройки Анны\n\nЧасовой пояс: {user.timezone}\n'
        f'Голосовые ответы: {"вкл" if user.voice_enabled else "выкл"}\n'
        f'Инициативные сообщения: {"вкл" if user.proactive_enabled else "выкл"}\n'
        f'Premium: {"активен" if is_premium(message.from_user.id) else "нет"}\n'
        f'Фото-кредиты: {credits}\n18+: {"подтверждено" if is_adult_confirmed(message.from_user.id) else "не подтверждено"}\n\n'
        '/voice · /notifications · /timezone'
    )


@dp.message(Command('adult'))
async def adult_cmd(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name)
    await message.answer('подтверди возраст для более смелых fashion-категорий:', reply_markup=adult_keyboard())


@dp.callback_query(F.data == 'age:yes')
async def age_yes(cq: types.CallbackQuery):
    set_adult_confirmed(cq.from_user.id, True)
    await cq.answer('18+ подтверждено')
    await cq.message.answer('готово 🙂')
    if cq.from_user.id in _pending_adult_custom:
        _pending_adult_custom.discard(cq.from_user.id)
        await start_custom_flow(cq.message.chat.id, cq.from_user.id)
        return
    req = _pending_adult_photo.pop(cq.from_user.id, None)
    if req:
        await handle_photo_request(cq.message.chat.id, cq.from_user.id, req)


@dp.callback_query(F.data == 'age:no')
async def age_no(cq: types.CallbackQuery):
    set_adult_confirmed(cq.from_user.id, False)
    _pending_adult_photo.pop(cq.from_user.id, None)
    _pending_adult_custom.discard(cq.from_user.id)
    await cq.answer()
    await cq.message.answer('поняла. тогда оставим обычные фото 🙂')


@dp.message(Command('premium'))
async def premium(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name)
    if is_premium(message.from_user.id):
        await message.answer(f'Premium уже активен ✨\nФото-кредиты: {get_photo_credits(message.from_user.id)}')
        return
    await message.answer(
        'Premium на 30 дней:\n• расширенная память и полный лимит сообщений\n'
        '• 12 дополнительных photo credits\n• больше continuity и инициативных сообщений\n\n'
        'Бесплатные фото зависят от близости: 1–2 уровень — 1/день, 3–6 — 2/день.\n'
        'Отношения не покупаются — они развиваются из общения. Кастомные фото оплачиваются отдельно.',
        reply_markup=premium_keyboard(),
    )


@dp.callback_query(F.data == 'buy:premium')
async def buy_premium(cq: types.CallbackQuery):
    ensure_user(cq.from_user.id, cq.from_user.first_name)
    await cq.answer()
    await send_stars_invoice(cq.message.chat.id, 'Anna Premium', 'Premium-доступ на 30 дней', 'premium_month', PREMIUM_MONTHLY_STARS)


@dp.pre_checkout_query()
async def pre_checkout(query: types.PreCheckoutQuery):
    await query.answer(ok=True)


@dp.message(F.successful_payment)
async def successful_payment(message: types.Message):
    payment = message.successful_payment
    payload = payment.invoice_payload
    charge = payment.telegram_payment_charge_id
    if payload == 'premium_month':
        record_payment(message.from_user.id, 'premium_month', payment.total_amount, charge)
        await message.answer('готово ✨ Premium активирован на 30 дней, и я добавила 12 photo credits')
        return

    if payload.startswith('photo:'):
        try:
            offer_id = int(payload.split(':', 1)[1])
        except ValueError:
            return
        request = consume_offer(message.from_user.id, offer_id)
        product = 'custom_photo' if payment.total_amount >= CUSTOM_PHOTO_COST_STARS else 'photo'
        record_payment(message.from_user.id, product, payment.total_amount, charge)
        if not request:
            await message.answer('оплата прошла, а запрос уже устарел. Photo credit сохранён — он не пропадёт.')
            return
        try:
            async with ChatActionSender.upload_photo(bot=bot, chat_id=message.chat.id):
                await deliver_photo(bot, message.chat.id, message.from_user.id, request, 'credit')
        except PermissionError as exc:
            logger.info('paid photo denied user=%s reason=%s', message.from_user.id, exc)
            await message.answer('оплата сохранена как photo credit. этот образ сейчас недоступен, кредит не пропадёт.')
        except PhotoGenerationError as exc:
            logger.warning('paid photo generation failed provider=%s reason=%s user=%s', exc.provider, exc.reason, message.from_user.id)
            await message.answer('фото сейчас не получилось, но оплаченный photo credit сохранён.', reply_markup=photo_retry_keyboard(request.scene))
        except Exception:
            logger.exception('paid photo generation failed user=%s', message.from_user.id)
            await message.answer('фото сейчас не получилось, но оплаченный photo credit сохранён.', reply_markup=photo_retry_keyboard(request.scene))


@dp.message(Command('photo', 'selfie'))
async def photo_menu(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name)
    await message.answer(
        photo_menu_text(message.from_user.id),
        reply_markup=photo_keyboard(message.from_user.id),
    )


@dp.callback_query(F.data.startswith('locked:'))
async def locked_photo_callback(cq: types.CallbackQuery):
    item = cq.data.split(':', 1)[1]
    required = 5 if item == 'custom' else SCENE_LEVELS.get(item, 6)
    current = get_relationship_level(cq.from_user.id)
    await cq.answer(
        f'🔒 Откроется на уровне {required}/6. Сейчас {current}/6. Близость растёт от общения — купить уровень нельзя.',
        show_alert=True,
    )


@dp.callback_query(F.data == 'photo_menu:open')
async def photo_menu_callback(cq: types.CallbackQuery):
    ensure_user(cq.from_user.id, cq.from_user.first_name)
    await cq.answer()
    await cq.message.answer(photo_menu_text(cq.from_user.id), reply_markup=photo_keyboard(cq.from_user.id))


@dp.callback_query(F.data.startswith('retry_photo:'))
async def retry_photo_callback(cq: types.CallbackQuery):
    await cq.answer('пробую ещё раз')
    scene = cq.data.split(':', 1)[1]
    await handle_photo_request(cq.message.chat.id, cq.from_user.id, PhotoRequest(scene=scene))


@dp.callback_query(F.data.startswith('photo:'))
async def photo_callback(cq: types.CallbackQuery):
    await cq.answer()
    scene = cq.data.split(':', 1)[1]
    tid = cq.from_user.id
    ensure_user(tid, cq.from_user.first_name)
    await handle_photo_request(cq.message.chat.id, tid, PhotoRequest(scene=scene))


async def start_custom_flow(chat_id: int, telegram_id: int):
    if get_relationship_level(telegram_id) < 5:
        await bot.send_message(chat_id, 'кастомные приватные образы откроются позже — тут Stars уровень отношений не заменяют 😏')
        return
    if not is_adult_confirmed(telegram_id):
        _pending_adult_custom.add(telegram_id)
        await bot.send_message(chat_id, 'сначала одно подтверждение 18+.', reply_markup=adult_keyboard())
        return
    _custom_drafts[telegram_id] = {}
    await bot.send_message(chat_id, 'начнём с цвета:', reply_markup=custom_color_keyboard())


@dp.callback_query(F.data == 'custom:start')
async def custom_start(cq: types.CallbackQuery):
    await cq.answer()
    await start_custom_flow(cq.message.chat.id, cq.from_user.id)


@dp.callback_query(F.data.startswith('custom:color:'))
async def custom_color(cq: types.CallbackQuery):
    await cq.answer()
    color = cq.data.rsplit(':', 1)[1]
    _custom_drafts.setdefault(cq.from_user.id, {})['color'] = color
    await cq.message.answer('добавить чулки?', reply_markup=custom_addon_keyboard())


@dp.callback_query(F.data.startswith('custom:addon:'))
async def custom_addon(cq: types.CallbackQuery):
    await cq.answer()
    addon = cq.data.rsplit(':', 1)[1]
    _custom_drafts.setdefault(cq.from_user.id, {})['addon'] = addon
    await cq.message.answer('причёска?', reply_markup=custom_hair_keyboard())


@dp.callback_query(F.data.startswith('custom:hair:'))
async def custom_hair(cq: types.CallbackQuery):
    await cq.answer()
    hair = cq.data.rsplit(':', 1)[1]
    _custom_drafts.setdefault(cq.from_user.id, {})['hair'] = hair
    await cq.message.answer('и где сделать кадр?', reply_markup=custom_place_keyboard())


@dp.callback_query(F.data.startswith('custom:place:'))
async def custom_place(cq: types.CallbackQuery):
    await cq.answer()
    draft = _custom_drafts.pop(cq.from_user.id, {})
    place = cq.data.rsplit(':', 1)[1]
    color = draft.get('color', 'black')
    clothing = f'{color} elegant lingerie fashion set with opaque fabric and polished catalog styling'
    if draft.get('addon') == 'stockings':
        clothing += ', with matching thigh-high stockings'
    hair_map = {
        'ponytail': 'high ponytail',
        'bun': 'neat bun',
        'loose': 'long loose softly wavy hair',
    }
    place_map = {
        'mirror': ('realistic mirror photo in a tasteful modern apartment', 'full-body mirror framing'),
        'sofa': ('sitting naturally on a modern sofa in a tidy apartment', 'natural three-quarter seated framing'),
        'hotel': ('tasteful modern hotel room', 'elegant full-body fashion portrait'),
    }
    location, angle = place_map.get(place, place_map['mirror'])
    request = PhotoRequest(
        scene='lingerie',
        clothing=clothing,
        hairstyle=hair_map.get(draft.get('hair', 'loose'), hair_map['loose']),
        location=location,
        angle=angle,
        mood='confident, warm, polished fashion editorial',
    )
    await _offer_custom_photo(cq.message.chat.id, cq.from_user.id, request)


@dp.message(Command('voice'))
async def voice_toggle(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name)
    user = get_user(message.from_user.id)
    new = not user.voice_enabled
    update_user_settings(message.from_user.id, voice_enabled=new)
    await message.answer('голосовые ответы включены 🎙️' if new else 'голосовые ответы выключены')


@dp.message(Command('voice_style'))
async def voice_style(message: types.Message):
    parts = (message.text or '').split(maxsplit=1)
    if len(parts) < 2 or parts[1] not in VALID_VOICES:
        await message.answer('Доступно: ' + ', '.join(VALID_VOICES))
        return
    update_user_settings(message.from_user.id, voice_style=parts[1])
    await message.answer(f'голос: {parts[1]} 🎙️')


@dp.message(Command('notifications'))
async def notifications(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name)
    user = get_user(message.from_user.id)
    new = not user.proactive_enabled
    update_user_settings(message.from_user.id, proactive_enabled=new)
    await message.answer('иногда буду писать первой 😌' if new else 'хорошо, первой писать не буду')


@dp.message(Command('timezone'))
async def timezone_cmd(message: types.Message):
    parts = (message.text or '').split(maxsplit=1)
    if len(parts) < 2:
        ensure_user(message.from_user.id)
        await message.answer(f'Сейчас: {get_user(message.from_user.id).timezone}\nПример: /timezone Europe/Moscow')
        return
    try:
        set_timezone(message.from_user.id, parts[1].strip())
        await message.answer('готово, запомнила часовой пояс')
    except Exception:
        await message.answer('не узнаю такой часовой пояс. пример: Europe/Moscow')


@dp.message(Command('wake'))
async def wake_cmd(message: types.Message):
    rid = create_from_text(message.from_user.id, message.text or '')
    await message.answer('запомнила 😌 разбужу и немного понастойчивее, если не ответишь' if rid else 'напиши время, например /wake 08:00')


@dp.message(Command('reset'))
async def reset_cmd(message: types.Message):
    uid = ensure_user(message.from_user.id, message.from_user.first_name)
    reset_memory(uid, CHARACTER_ID)
    with SessionLocal() as session:
        rel = session.query(UserCharacterRelationship).filter_by(user_id=uid, character_id=CHARACTER_ID).first()
        if rel:
            session.query(RelationshipEvent).filter(RelationshipEvent.user_character_id == rel.id).delete(synchronize_session=False)
            session.delete(rel)
        state = session.query(CharacterState).filter_by(user_id=uid, character_id=CHARACTER_ID).first()
        if state:
            state.mood = 'neutral'
            state.energy = .65
            state.affection = .45
            state.playfulness = .55
            state.irritation = 0
            state.pending_hook = None
        session.query(Reminder).filter_by(user_id=uid).delete(synchronize_session=False)
        session.commit()
    clear_stage(message.from_user.id)
    await message.answer('готово. нашу переписку, память и развитие отношений начала заново.')


@dp.message(Command('testlevel', 'relationship_test'))
async def testlevel(message: types.Message):
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        await message.answer('эта команда только для владельца')
        return
    parts = (message.text or '').split(maxsplit=1)
    if len(parts) < 2:
        await message.answer('Использование: /testlevel 1..6 или /testlevel off')
        return
    arg = parts[1].strip().lower()
    if arg == 'off':
        clear_stage(message.from_user.id)
        await message.answer('тестовый уровень выключен')
        return
    if not arg.isdigit() or not 1 <= int(arg) <= 6:
        await message.answer('нужен уровень от 1 до 6')
        return
    stage = STAGES[int(arg) - 1]
    set_stage(message.from_user.id, stage)
    await message.answer(f'тест: {STAGE_LABELS[stage]}')


async def send_answer(message: types.Message, text: str):
    user = get_user(message.from_user.id)
    if user and user.voice_enabled:
        try:
            audio = await synthesize_bytes(text, user.voice_style)
            await message.answer_voice(BufferedInputFile(audio, filename='anna.ogg'))
            return
        except Exception:
            logger.exception('tts failed')

    # Short paragraph breaks feel more like Telegram bubbles; keep code blocks intact.
    if '```' not in text and '\n\n' in text and len(text) < 700:
        parts = [p.strip() for p in text.split('\n\n') if p.strip()]
        if 1 < len(parts) <= 3:
            for part in parts:
                await message.answer(part)
                await asyncio.sleep(0.35)
            return
    await message.answer(text)


@dp.message(F.text == '💬 Общение')
async def chat_button(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name)
    await message.answer('я здесь 🙂 просто пиши мне как обычно')


@dp.message(F.text == '📸 Фото')
async def photo_button(message: types.Message):
    await photo_menu(message)


@dp.message(F.text == '🎭 Образы')
async def looks_button(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name)
    await message.answer(photo_menu_text(message.from_user.id), reply_markup=photo_keyboard(message.from_user.id))


@dp.message(F.text == '🚀 Премиум')
async def premium_button(message: types.Message):
    await premium(message)


@dp.message(F.text == '👤 Профиль')
async def profile_button(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name)
    info = build_photo_menu(message.from_user.id)
    await message.answer(
        f'👤 Твой профиль\n\n'
        f'❤️ Близость: {info["level"]}/6 · {RELATIONSHIP_LEVEL_NAMES.get(info["level"], "")}\n'
        f'⭐ Premium: {"активен" if info["premium"] else "нет"}\n'
        f'📸 Фото сегодня: {info["free_left"]} включено\n'
        f'🎟 Photo credits: {info["credits"]}'
    )


@dp.message(F.text == '⚙️ Настройки')
async def settings_button(message: types.Message):
    await settings(message)


@dp.message(F.voice)
async def voice_message(message: types.Message):
    ensure_user(message.from_user.id, message.from_user.first_name)
    cancel_active_wake(message.from_user.id)
    if not can_send_message(message.from_user.id):
        await message.answer('на сегодня бесплатный лимит сообщений закончился. /premium')
        return
    try:
        data = await bot.download(message.voice)
        text = await transcribe(data)
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            answer = await anna_reply(message.from_user.id, message.from_user.first_name or 'ты', text)
        await send_answer(message, answer)
        request = parse_photo_request(text)
        if request:
            await handle_photo_request(message.chat.id, message.from_user.id, request)
        if create_from_text(message.from_user.id, text):
            await message.answer('и время тоже запомнила 😌')
        touch_user(message.from_user.id)
    except Exception:
        logger.exception('voice handler')
        await message.answer('голосовое сейчас не получилось разобрать 😕')


@dp.message(F.text)
async def text_message(message: types.Message):
    if (message.text or '').startswith('/'):
        return
    ensure_user(message.from_user.id, message.from_user.first_name)
    cancel_active_wake(message.from_user.id)
    if not can_send_message(message.from_user.id):
        await message.answer('на сегодня бесплатный лимит сообщений закончился. Premium: /premium')
        return
    text = message.text or ''
    try:
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            answer = await anna_reply(message.from_user.id, message.from_user.first_name or 'ты', text)
        await send_answer(message, answer)
        request = parse_photo_request(text)
        if request:
            await handle_photo_request(message.chat.id, message.from_user.id, request)
        rid = create_from_text(message.from_user.id, text)
        if rid:
            await message.answer('запомнила 😌')
        touch_user(message.from_user.id)
    except Exception:
        logger.exception('chat handler user=%s', message.from_user.id)
        await message.answer('я сейчас немного зависла 😅 напиши ещё раз')


async def main():
    await bot.set_my_commands([
        types.BotCommand(command='start', description='Начать общение'),
        types.BotCommand(command='photo', description='📸 Фото Анны'),
        types.BotCommand(command='premium', description='⭐ Premium'),
        types.BotCommand(command='settings', description='Настройки'),
        types.BotCommand(command='voice', description='Голосовые ответы'),
        types.BotCommand(command='notifications', description='Инициативные сообщения'),
        types.BotCommand(command='wake', description='Будильник: /wake 08:00'),
        types.BotCommand(command='reset', description='Очистить память и историю'),
    ])
    start_scheduler(bot)
    logger.info('AnnaBot started')
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
