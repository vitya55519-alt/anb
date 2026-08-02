import asyncio
import logging

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.chat_action import ChatActionSender

from helpers import (
    keep_alive,
    search_user, new_user, update_user,
    update_user_waifu_name, update_user_waifu_role,
    get_waifu_role_descriptions, get_waifu_role_descriptions_with_id,
    chat_openai_waifu,
    delete_chat_log_user, delete_memory_summaries,
    is_rate_limited,
    update_user_last_active, toggle_user_voice, update_user_voice_style,
    update_user_appearance, toggle_user_proactive,
    transcribe_voice, generate_voice, VALID_VOICE_STYLES,
    generate_selfie,
    start_scheduler,
    set_timezone, create_wake_from_text, get_character_state, update_character_state,
    delete_memory_facts, delete_reminders,
)
from config import TELEGRAM_TOKEN, KEEP_ALIVE, ADMIN_TELEGRAM_IDS, CHARACTER_ID
from services.chat_service import reply as anna_reply, ensure_user as ensure_anna_user
from services.access_service import can_send_message

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


class Form(StatesGroup):
    get_user_name = State()
    get_girlfriend_name = State()
    get_girlfriend_model = State()
    get_appearance = State()


# CONFIGURATION FUNCTIONALITY

@dp.message(Command('start', 'help'))
async def send_welcome(message: types.Message, state: FSMContext):
    # Anna is ready immediately. Legacy /config remains available but is no longer
    # a gate in front of the actual Anna conversation engine.
    display_name = message.from_user.first_name or message.from_user.username or "друг"
    ensure_anna_user(message.from_user.id, display_name)

    # Keep the legacy user row alive for old voice/reminder/photo commands, but
    # give it sane Anna defaults so /start never launches the old Spanish setup.
    user_db = await asyncio.to_thread(search_user, message.from_user.id)
    if user_db is None:
        await asyncio.to_thread(new_user, message.from_user.id, display_name)
        user_db = await asyncio.to_thread(search_user, message.from_user.id)
    if user_db and not user_db.waifu_name:
        await asyncio.to_thread(update_user_waifu_name, message.from_user.id, "Анна")
    if user_db and not user_db.selected_waifu_role:
        roles = await asyncio.to_thread(get_waifu_role_descriptions_with_id)
        if roles:
            await asyncio.to_thread(update_user_waifu_role, message.from_user.id, roles[0][1])

    await message.answer(
        f"Привет, {display_name} 🙂 Я Анна. Не надо ничего настраивать — просто пиши мне.\n\n"
        "Если захочешь поменять имя, голос, часовой пояс или другие настройки — они всё ещё доступны через /config и команды.\n\n"
        "Ну что, о чём будем болтать?",
    )


@dp.message(Command('config_actual'))
async def actual_config(message: types.Message):
    user_db = await asyncio.to_thread(search_user, message.from_user.id)
    waifu_roles = await asyncio.to_thread(get_waifu_role_descriptions_with_id)

    if user_db:
        markup = types.ReplyKeyboardMarkup(
            keyboard=[
                [types.KeyboardButton(text="/my_name"), types.KeyboardButton(text="/waifu_name"), types.KeyboardButton(text="/waifu_role")],
                [types.KeyboardButton(text="/finalizar")],
            ],
            resize_keyboard=True,
        )
        role_desc = waifu_roles[user_db.selected_waifu_role - 1][0] if user_db.selected_waifu_role else "Sin configurar"
        voice_status = f"{'✅' if user_db.voice_enabled else '❌'} ({user_db.voice_style or 'nova'})"
        proactive_status = "✅" if user_db.proactive_enabled else "❌"
        await message.answer(
            f"Tu configuracion actual es:\n"
            f"Tu nombre: <b>{user_db.name}</b>\n"
            f"Mi nombre: <b>{user_db.waifu_name}</b>\n"
            f"Rol: <b>{role_desc}</b>\n"
            f"Voz: {voice_status}\n"
            f"Mensajes proactivos: {proactive_status}\n\n"
            f"Comandos: /voice · /selfie · /notifications · /reset",
            parse_mode="HTML",
            reply_markup=markup,
        )


@dp.message(Command('config'))
async def general_configuration(message: types.Message, state: FSMContext):
    markup = types.ReplyKeyboardRemove()
    await message.answer("Vamos a revisar tu configuracion", reply_markup=markup)
    user_db = await asyncio.to_thread(search_user, message.from_user.id)

    if user_db:
        await actual_config(message)
    else:
        await config_user_name(message, state)


@dp.message(StateFilter('*'), Command('cancel', 'finalizar'))
@dp.message(StateFilter('*'), F.text.casefold() == 'cancel')
async def cancel_handler(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        markup = types.ReplyKeyboardRemove()
        await message.answer('Podemos platicar si gustas', reply_markup=markup)
        return
    await state.clear()
    await message.reply('Accion cancelada')


@dp.message(Command('my_name'))
async def config_user_name(message: types.Message, state: FSMContext):
    if await asyncio.to_thread(search_user, message.from_user.id):
        await message.answer("Ya nos conocemos, pero si gustas puedo llamarte de otra forma.\n¿Cómo quieres que te llame ahora?")
    else:
        await message.answer("Primero quiero conocerte, dime tu nombre por favor:")
    await state.set_state(Form.get_user_name)


@dp.message(Form.get_user_name)
async def process_name(message: types.Message, state: FSMContext):
    user_name = message.text
    user_db = await asyncio.to_thread(search_user, message.from_user.id)
    if user_db:
        await asyncio.to_thread(update_user, message.from_user.id, user_name)
    else:
        await asyncio.to_thread(new_user, message.from_user.id, user_name)

    await state.clear()
    await message.reply(f"Genial, ahora te llamaré {user_name}")

    if user_db is None:
        await config_waifu_name(message, state)
    else:
        await actual_config(message)


@dp.message(Command('waifu_name'))
async def config_waifu_name(message: types.Message, state: FSMContext):
    user_db = await asyncio.to_thread(search_user, message.from_user.id)
    if user_db is None:
        await message.answer("Primero tengo que saber como te llamas")
        await config_user_name(message, state)
    else:
        await message.answer("Dime como quieres que me llame:")
    await state.set_state(Form.get_girlfriend_name)


@dp.message(Form.get_girlfriend_name)
async def process_waifu_name(message: types.Message, state: FSMContext):
    waifu_name = message.text
    if await asyncio.to_thread(search_user, message.from_user.id):
        await asyncio.to_thread(update_user_waifu_name, message.from_user.id, waifu_name)
    else:
        await asyncio.to_thread(new_user, message.from_user.id, waifu_name)

    await state.clear()
    await message.reply(f"Genial, ahora me llamaré {waifu_name}")

    user_db = await asyncio.to_thread(search_user, message.from_user.id)
    if user_db.selected_waifu_role is None:
        await config_waifu_role(message, state)
    else:
        await actual_config(message)


@dp.message(Command('waifu_role'))
async def config_waifu_role(message: types.Message, state: FSMContext):
    available_roles = await asyncio.to_thread(get_waifu_role_descriptions)
    keyboard = [[types.KeyboardButton(text=role)] for role in available_roles]
    markup = types.ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, selective=True)
    await message.answer("¿Qué rol quieres que tenga?", reply_markup=markup)
    await state.set_state(Form.get_girlfriend_model)


@dp.message(Form.get_girlfriend_model)
async def process_waifu_role(message: types.Message, state: FSMContext):
    available_roles = await asyncio.to_thread(get_waifu_role_descriptions)
    if message.text not in available_roles:
        return await message.reply("Rol invalido. Elige un rol de la lista.")

    waifu_roles_with_id = await asyncio.to_thread(get_waifu_role_descriptions_with_id)
    for description, role_id in waifu_roles_with_id:
        if description == message.text:
            await asyncio.to_thread(update_user_waifu_role, message.from_user.id, role_id)
            break

    markup = types.ReplyKeyboardRemove()
    await message.answer("Rol actualizado!", reply_markup=markup)
    await state.clear()
    await actual_config(message)


@dp.message(Command('reset'))
async def reset_conversation(message: types.Message):
    user_db = await asyncio.to_thread(search_user, message.from_user.id)
    if not user_db:
        await message.answer("Aún no tenemos conversaciones guardadas 😊")
        return
    await asyncio.to_thread(delete_chat_log_user, message.from_user.id)
    await asyncio.to_thread(delete_memory_summaries, message.from_user.id)
    await asyncio.to_thread(delete_memory_facts, message.from_user.id)
    await asyncio.to_thread(delete_reminders, message.from_user.id)
    await message.answer("Listo, borré nuestros recuerdos guardados 🥺 Empecemos de cero...")


# VOICE COMMANDS

@dp.message(Command('voice'))
async def toggle_voice(message: types.Message):
    user_db = await asyncio.to_thread(search_user, message.from_user.id)
    if not user_db:
        await message.answer("Primero necesito conocerte. Usa /start")
        return

    new_state = not (user_db.voice_enabled or False)
    await asyncio.to_thread(toggle_user_voice, message.from_user.id, new_state)

    if new_state:
        styles_list = " · ".join(VALID_VOICE_STYLES)
        await message.answer(
            f"🔊 Respuestas de voz activadas con estilo <b>{user_db.voice_style or 'nova'}</b>.\n"
            f"Estilos disponibles: {styles_list}\n"
            f"Cambia el estilo con: <code>/voice_style nova</code>",
            parse_mode="HTML",
        )
    else:
        await message.answer("🔇 Respuestas de voz desactivadas.")


@dp.message(Command('voice_style'))
async def set_voice_style(message: types.Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or parts[1].strip() not in VALID_VOICE_STYLES:
        await message.answer(f"Estilos válidos: {' · '.join(VALID_VOICE_STYLES)}")
        return
    style = parts[1].strip()
    await asyncio.to_thread(update_user_voice_style, message.from_user.id, style)
    await message.answer(f"Voz cambiada a <b>{style}</b> 🎙️", parse_mode="HTML")


# VOICE MESSAGE HANDLER

@dp.message(F.voice)
async def handle_voice_message(message: types.Message, state: FSMContext):
    user_db = await asyncio.to_thread(search_user, message.from_user.id)
    if user_db is None or user_db.name is None or user_db.waifu_name is None or user_db.selected_waifu_role is None:
        await general_configuration(message, state)
        return

    if is_rate_limited(message.from_user.id):
        await message.answer("Dame un respiro, estoy un poco abrumada 💕")
        return

    try:
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            voice_bytes = await bot.download(message.voice)
            transcribed = await transcribe_voice(voice_bytes)

        await message.answer(f"🎤 _{transcribed}_", parse_mode="Markdown")

        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            response_txt = await anna_reply(
                message.from_user.id, user_db.name or message.from_user.first_name or "друг", transcribed
            )

        # Natural photo request becomes part of the conversation, not only /selfie.
        if _photo_request(message.text):
            try:
                async with ChatActionSender.upload_photo(bot=bot, chat_id=message.chat.id):
                    image_url = await generate_selfie(
                        user_db.waifu_name,
                        next((desc for desc, rid in await asyncio.to_thread(get_waifu_role_descriptions_with_id) if rid == user_db.selected_waifu_role), ""),
                        user_db.appearance_description,
                    )
                await _send_chat_result(message, response_txt, user_db)
                await message.answer_photo(image_url, caption="😌")
            except Exception:
                await _send_chat_result(message, response_txt, user_db)
        else:
            await _send_chat_result(message, response_txt, user_db)

        # Natural reminder/wake request is parsed after the normal conversational response.
        if any(k in message.text.lower() for k in ('разбуди', 'wake me', 'despierta', 'despertarme', 'напомни', 'remind me', 'recuérdame', 'recuerdame')):
            try:
                rid = await asyncio.to_thread(create_wake_from_text, message.from_user.id, message.text)
                if rid:
                    await message.answer("запомнила 😌")
            except Exception:
                logger.exception("Failed to create natural reminder")

        await asyncio.to_thread(update_user_last_active, message.from_user.id)

    except Exception as e:
        logger.error("Error in voice handler for user %s: %s", message.from_user.id, e)
        await message.answer("Tuve problemas con el audio, intenta de nuevo 🥺")


# SELFIE COMMANDS

@dp.message(Command('selfie'))
async def send_selfie(message: types.Message):
    user_db = await asyncio.to_thread(search_user, message.from_user.id)
    if not user_db or not user_db.waifu_name or not user_db.selected_waifu_role:
        await message.answer("Primero completa la configuración con /start")
        return

    waifu_roles = await asyncio.to_thread(get_waifu_role_descriptions_with_id)
    role_desc = next(
        (desc for desc, rid in waifu_roles if rid == user_db.selected_waifu_role),
        ""
    )

    await message.answer("Un momento, me estoy arreglando para la foto... 📸")
    try:
        async with ChatActionSender.upload_photo(bot=bot, chat_id=message.chat.id):
            image_url = await generate_selfie(
                user_db.waifu_name,
                role_desc,
                user_db.appearance_description,
            )
        await message.answer_photo(image_url, caption=f"¿Te gusta? 😊")
    except Exception as e:
        logger.error("Selfie generation failed for user %s: %s", message.from_user.id, e)
        await message.answer("No pude tomar la foto ahora mismo 🥺 Intenta más tarde.")


@dp.message(Command('appearance'))
async def set_appearance(message: types.Message, state: FSMContext):
    await message.answer(
        "Descríbeme cómo quieres que me vea en las fotos. Por ejemplo:\n"
        "<i>'cabello largo negro, ojos verdes, estilo casual elegante'</i>",
        parse_mode="HTML",
    )
    await state.set_state(Form.get_appearance)


@dp.message(Form.get_appearance)
async def process_appearance(message: types.Message, state: FSMContext):
    await asyncio.to_thread(update_user_appearance, message.from_user.id, message.text)
    await state.clear()
    await message.answer("Guardado ✅ Usa /selfie para verme así 📸")



# REMINDERS / WAKE-UP

@dp.message(Command('timezone'))
async def timezone_command(message: types.Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        state_db = await asyncio.to_thread(get_character_state, message.from_user.id)
        await message.answer(f"Tu zona horaria actual es <code>{state_db.timezone}</code>. Ejemplo: /timezone Europe/Madrid", parse_mode="HTML")
        return
    try:
        await asyncio.to_thread(set_timezone, message.from_user.id, parts[1].strip())
        await message.answer(f"listo 😌 usaré <code>{parts[1].strip()}</code> para tus horarios", parse_mode="HTML")
    except Exception:
        await message.answer("Esa zona horaria no me suena 😅 Usa una como Europe/Madrid, America/New_York o Asia/Kolkata.")

@dp.message(Command('wake'))
async def wake_command(message: types.Message):
    user_db = await asyncio.to_thread(search_user, message.from_user.id)
    if not user_db:
        await message.answer("Primero haz /start 😌")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Dime la hora, por ejemplo: /wake 08:00")
        return
    reminder_id = await asyncio.to_thread(create_wake_from_text, message.from_user.id, f"wake me at {parts[1]}")
    if reminder_id:
        await message.answer("hecho 😌 a esa hora te despierto. y sí, voy a insistir un poquito 😂")
    else:
        await message.answer("No entendí la hora 😅 prueba /wake 08:00")

@dp.message(Command('relationship_test'))
async def relationship_test(message: types.Message):
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        await message.answer("No tienes acceso a esa función.")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Uso: /relationship_test 0|10|50|200|500|1000")
        return
    n = int(parts[1])
    # Deliberately only for testing: relationship count is set directly for the configured admin.
    from helpers.db_connection import SessionLocal
    from models.waifu_models import RelationshipState
    def _set():
        with SessionLocal() as session:
            row = session.query(RelationshipState).filter(RelationshipState.relIdUser == message.from_user.id).first()
            if not row:
                row = RelationshipState(relIdUser=message.from_user.id)
                session.add(row)
            row.total_messages = n
            session.commit()
    await asyncio.to_thread(_set)
    await message.answer(f"🧪 Уровень отношений выставлен на тестовое значение {n} сообщений.")

# NOTIFICATIONS

@dp.message(Command('notifications'))
async def toggle_notifications(message: types.Message):
    user_db = await asyncio.to_thread(search_user, message.from_user.id)
    if not user_db:
        await message.answer("Primero necesito conocerte. Usa /start")
        return

    new_state = not (user_db.proactive_enabled if user_db.proactive_enabled is not None else True)
    await asyncio.to_thread(toggle_user_proactive, message.from_user.id, new_state)

    if new_state:
        await message.answer("🔔 Te voy a escribir cuando te extrañe 💕")
    else:
        await message.answer("🔕 De acuerdo, no te molestaré si no me escribes primero.")



def _photo_request(text: str) -> bool:
    t = text.lower()
    keys = ('фото', 'фотку', 'селфи', 'покажись', 'покажи себя', 'picture', 'photo', 'selfie', 'pic', 'foto', 'muéstrate')
    return any(k in t for k in keys)

async def _send_chat_result(message: types.Message, response_txt: str, user_db):
    # Optional natural multi-message bursts: the model may use ||| when it genuinely helps.
    chunks = [x.strip() for x in response_txt.split('|||') if x.strip()]
    for chunk in chunks[:3]:
        if user_db.voice_enabled:
            audio_bytes = await generate_voice(chunk, user_db.voice_style or 'nova')
            await message.answer_voice(types.BufferedInputFile(audio_bytes, "response.ogg"))
        else:
            await message.answer(chunk)

# CHATGPT FUNCTIONALITY

@dp.message()
async def gpt(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("Por ahora solo puedo leer mensajes de texto 😊")
        return
    if len(message.text) > 2000:
        await message.answer("Tu mensaje es muy largo, ¿puedes resumirlo un poco? 🥺")
        return

    if is_rate_limited(message.from_user.id):
        await message.answer("Dame un respiro, estoy un poco abrumada 💕")
        return

    user_db = await asyncio.to_thread(search_user, message.from_user.id)
    if user_db is None:
        display_name = message.from_user.first_name or message.from_user.username or "друг"
        ensure_anna_user(message.from_user.id, display_name)
        await asyncio.to_thread(new_user, message.from_user.id, display_name)
        user_db = await asyncio.to_thread(search_user, message.from_user.id)

    if not await asyncio.to_thread(can_send_message, message.from_user.id):
        await message.answer("Я сегодня уже много болтала 😅 Давай продолжим завтра или подключи Premium.")
        return

    try:
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            response_txt = await anna_reply(
                message.from_user.id, user_db.name or message.from_user.first_name or "друг", message.text
            )

        if user_db.voice_enabled:
            audio_bytes = await generate_voice(response_txt, user_db.voice_style or 'nova')
            await message.answer_voice(types.BufferedInputFile(audio_bytes, "response.ogg"))
        else:
            await message.answer(response_txt)

        await asyncio.to_thread(update_user_last_active, message.from_user.id)

    except Exception as e:
        logger.error("Unhandled error in gpt handler for user %s: %s", message.from_user.id, e)
        await message.answer("Algo salió mal, intenta de nuevo 💕")


async def main():
    if KEEP_ALIVE:
        keep_alive()
    start_scheduler(bot)

    await bot.set_my_commands([
        types.BotCommand(command="start",         description="Bienvenida e inicio"),
        types.BotCommand(command="config_actual", description="Ver tu configuración actual"),
        types.BotCommand(command="config",        description="Editar configuración"),
        types.BotCommand(command="selfie",        description="📸 Genera una foto de tu waifu"),
        types.BotCommand(command="voice",         description="🔊 Activar/desactivar respuestas de voz"),
        types.BotCommand(command="voice_style",   description="🎙️ Cambiar estilo de voz (ej: /voice_style nova)"),
        types.BotCommand(command="appearance",    description="🎨 Describir apariencia para las fotos"),
        types.BotCommand(command="notifications", description="🔔 Activar/desactivar mensajes proactivos"),
        types.BotCommand(command="wake",          description="⏰ Despertarme a una hora"),
        types.BotCommand(command="timezone",      description="🌍 Configurar zona horaria"),
        types.BotCommand(command="reset",         description="🗑️ Borrar historial de conversación"),
        types.BotCommand(command="my_name",       description="Cambiar tu nombre"),
        types.BotCommand(command="waifu_name",    description="Cambiar el nombre de tu waifu"),
        types.BotCommand(command="waifu_role",    description="Cambiar personalidad"),
        types.BotCommand(command="finalizar",     description="Cancelar acción actual"),
    ])

    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
