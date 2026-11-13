"""Interface language for the bot menus and the retention flows.

The legacy reply keyboard is RU/EN. Newer onboarding and day-1 flows use all
eight languages offered by the Mini App settings.

Rules:
- the interface language is stored on ``User.ui_lang`` ('' = Russian, the
  legacy default). It is detected from the Telegram account language on
  first contact and never forced again afterwards;
- every reply-keyboard label exists as a ``(ru, en)`` pair and the text
  handlers match BOTH variants via ``F.text.in_(kb_pair(key))``;
- unknown/missing ``language_code`` stays Russian — the core audience is
  Russian-speaking.
"""
from __future__ import annotations

from sqlalchemy import select

from models.app_models import User
from services.db import SessionLocal

RU = 'ru'
EN = 'en'
APP_LANGS = frozenset((RU, EN, 'es', 'it', 'fr', 'zh', 'ja', 'bn'))

# Main reply keyboard labels: key -> (ru, en). Row layout lives in menu_rows().
KB_LABELS = {
    'chat': ('💬 Общение', '💬 Chat'),
    'photo': ('📸 Фото', '📸 Photos'),
    'video': ('🎬 Видео', '🎬 Video'),
    'circle': ('🎥 Кружочек', '🎥 Video circle'),
    'quest': ('🎯 Задание дня', '🎯 Daily quest'),
    'date': ('💕 Свидание', '💕 Date'),
    'apartment': ('🏠 Квартира', '🏠 Apartment'),
    'gift': ('🎁 Подарить', '🎁 Gift'),
    'stories': ('🎯 Истории', '🎯 Stories'),
    'collection': ('🖼 Коллекция', '🖼 Collection'),
    'features': ('✨ Возможности', '✨ Features'),
    'premium': ('🚀 Премиум', '🚀 Premium'),
    'alarm': ('⏰ Будильник', '⏰ Alarm'),
    'profile': ('👤 Профиль', '👤 Profile'),
    'settings': ('⚙️ Настройки', '⚙️ Settings'),
    'characters': ('👩 Персонажи', '👩 Characters'),
    'invite': ('🔗 Пригласить', '🔗 Invite'),
    # V3.37.0: the money affiliate program — the «пригласить» button grew up
    # into a full partner screen (stats, payouts, FAQ). Kept as its own key so
    # old keyboards still resolve; the menu shows partner instead of invite.
    'partner': ('💰 Партнёрская программа', '💰 Partner program'),
    'custom': ('🎨 Мой персонаж', '🎨 My character'),
    # V3.38.0: the main menu funnels users into the Mini App (Come Closer
    # layout): one big «open app» row on top, the two app actions (buy
    # photo credits / create a picture) in the middle, partner + support at
    # the bottom. «Поддержка» is now a real ticket flow to the owner (the
    # old «💖 Поддержать проект» donation appeal stays on the legal screen).
    'app': ('📱 Открыть приложение', '📱 Open the app'),
    # V3.43.5: owner asked for the plain «Персики» label on every credits
    # button — short, brand-colored, no «добавить/пополнить» verbs.
    'credits': ('🍑 Персики', '🍑 Peaches'),
    'paint': ('🖼 Создать картинку', '🖼 Create a picture'),
    'support': ('👥 Поддержка', '👥 Support'),
    # V3.32.0: Platega/bank compliance — legal documents must be reachable
    # at all times from the main keyboard, not only via commands.
    'legal': ('📜 Документы', '📜 Documents'),
    'admin': ('🛠 Админка', '🛠 Admin'),
    # V3.149.0: the four rows a plain user is allowed to see, plus the owner's
    # own kitchen that only ever renders for ADMIN_TELEGRAM_IDS.
    'gallery': ('👯‍♀️ Галерея персонажей', '👯‍♀️ Character gallery'),
    'reminder': ('📝 Напоминание', '📝 Reminder'),
    # V3.163.0: owner — «все команды видно в боте, сделай так, чтобы их видел
    # только я». The slash list goes admin-only, so everything a real user
    # needed from it lives as buttons under the four menu rows instead.
    'donate': ('💖 Поддержать проект', '💖 Support the project'),
    'recipe': ('🍳 Рецепт', '🍳 Recipe'),
    'concert': ('🎫 Концерт', '🎫 Concert'),
    'promo': ('🎟 Промо', '🎟 Promo'),
}

# V3.149.0: owner ТЗ «Динамическое меню (Admin/User)» replaces the old
# Come Closer layout (MAIN_KB_ROWS) — the Mini App stays the product and the
# chat keyboard is its launcher. A plain user gets the four doors, and since
# V3.163.0 the three rows that carry what the hidden slash commands used to
# open. The whole kitchen (peaches, Premium, the picture studio, partner
# program, promo codes, profile, admin panel) only renders when the id sits in
# ADMIN_TELEGRAM_IDS. Old keys stay in KB_LABELS so cached reply keyboards from
# earlier versions keep resolving.
USER_MENU_ROWS = [
    ['app'],
    ['gallery'],
    ['alarm'],
    ['reminder'],
    ['stories', 'collection'],
    ['features', 'support'],
    ['donate'],
]
ADMIN_MENU_ROWS = [
    ['partner'],
    ['recipe'],
    ['concert'],
    ['promo'],
    ['profile'],
    ['credits'],
    ['premium'],
    ['paint'],
    ['support', 'legal'],
    ['admin'],
]


def menu_rows(is_admin: bool) -> list[list[str]]:
    """One source of truth for both keyboards: the inline menu and the reply rows."""
    return USER_MENU_ROWS + (ADMIN_MENU_ROWS if is_admin else [])


# English names for the 8-level relationship ladder (RU lives in main.py).
LEVEL_NAMES_EN = {
    1: 'Getting to know each other',
    2: 'Attraction',
    3: 'Spark',
    4: 'Falling in love',
    5: 'First date',
    6: 'Only you',
    7: 'Our story',
    8: 'Under one roof',
    9: 'The journey',
    10: 'One whole',
}


def kb_pair(key: str) -> tuple[str, str]:
    """Both label variants — for ``F.text.in_`` handler matching."""
    return KB_LABELS[key]


def kb_label(key: str, lang: str) -> str:
    ru, en = KB_LABELS[key]
    return en if lang == EN else ru


def detect_lang(language_code: str | None) -> str:
    """Telegram account language -> interface language."""
    code = (language_code or '').strip().lower()
    return EN if code and not code.startswith('ru') else RU


def user_lang(telegram_id: int) -> str:
    """Legacy RU/EN interface language. Unknown users default to Russian."""
    try:
        with SessionLocal() as session:
            user = session.scalar(select(User).where(User.telegram_id == str(telegram_id)))
            lang = (user.ui_lang or '').strip().lower() if user else ''
        return EN if lang == EN else RU
    except Exception:
        return RU


def app_lang(language_code: str | None, default: str = '') -> str:
    """One of the eight Mini App languages; foreign unsupported codes use English."""
    code = (language_code or '').strip().lower().replace('_', '-').split('-')[0]
    if code in APP_LANGS:
        return code
    if default in APP_LANGS:
        return default
    return detect_lang(language_code)


def full_user_lang(telegram_id: int, language_code: str | None = None) -> str:
    """Full language for new flows without changing the legacy RU/EN menus."""
    chat = ui = ''
    try:
        with SessionLocal() as session:
            user = session.scalar(select(User).where(User.telegram_id == str(telegram_id)))
            if user:
                chat = user.chat_lang or ''
                ui = user.ui_lang or ''
    except Exception:
        pass
    for value in (chat, language_code, ui):
        code = (value or '').strip().lower().replace('_', '-').split('-')[0]
        if code in APP_LANGS:
            return code
    return detect_lang(language_code or ui or chat)


FLOW_TEXT = {
    'ru': {
        'girl_of_day': '🔥 Девушка дня — {name}',
        'open_chat': '💬 Ответить ей',
        'gift_button': '🎁 Забрать дневной подарок',
        'gift_text': 'я тут сижу и скучаю по тебе 🥺 а ещё — у тебя уже копится дневной подарок 🍑 заходи каждый день — на 7-й день дают {amount} персиков, серия сгорает, если пропустить день\nзагляни в приложение (Магазин) и возвращайся ко мне 💋',
        'selfie_caption': 'это я 🙈 только что сфоткалась для тебя… нравится?',
        'onboarding_demo': 'слушай, ты мне сразу понравился 🙈 лови фото, пока я в таком виде… это только для тебя. ну как, нравится? 😏',
        'guest_word': 'подруга',
        'guest_in': '🚪 {name} заходит в чат',
        'guest_out': '👋 {name} уходит, и вы снова вдвоём',
        'welcome_edit': '🎁 Добро пожаловать! Тебе начислено {amount} фото-кредитов 👇',
        'welcome_edit_plain': '🎁 Добро пожаловать! 👇',
        'open_app': '📱 Открыть приложение',
        'draft_plate': '✍️ {name} долго печатала сообщение и стёрла его…',
        'draft_button': '👀 Прочитать стёртое · {price} 🍑',
        'draft_unlocked': '🔓 Стертый черновик {name}: {text}',
        'draft_gone': '😅 то сообщение она уже потеряла',
        'qte_echo': '👉 {action}',
        'qte_no_peach': '🔥 этот ход стоит {price} 🍑 — персиков не хватает',
        'qte_gone': '😅 момент уже упущен',
        'live_button': '📸 Открыть живое фото · {price} 🍑',
        'live_busy': '⏳ Делаю кадр, секунду…',
        'live_gone': '😅 тот кадр она уже стёрла',
        'live_no_peach': '🔥 это фото стоит {price} купленных 🍑 — не хватает',
        'live_failed': '🙈 кадр не вышел, персики вернула',
    },
    'en': {
        'girl_of_day': '🔥 Girl of the day — {name}',
        'open_chat': '💬 Open the chat',
        'gift_button': '🎁 Claim your daily gift',
        'gift_text': "i'm sitting here missing you 🥺 and your daily gift is already growing 🍑 come back every day — on day 7 you get {amount} peaches; miss a day and the streak resets\nopen the app (Shop) and come back to me 💋",
        'selfie_caption': 'this is me 🙈 just took it for you… do you like it?',
        'onboarding_demo': 'listen, i liked you right away 🙈 catch this photo while i look like this… it is just for you. well, do you like it? 😏',
        'guest_word': 'her friend',
        'guest_in': '🚪 {name} walks into the chat',
        'guest_out': '👋 {name} leaves, it is just the two of you again',
        'welcome_edit': '🎁 Welcome! {amount} photo credits are on your account 👇',
        'welcome_edit_plain': '🎁 Welcome! 👇',
        'open_app': '📱 Open the app',
        'draft_plate': '✍️ {name} typed a long message and erased it…',
        'draft_button': '👀 Read what she erased · {price} 🍑',
        'draft_unlocked': '🔓 Her erased draft, {name}: {text}',
        'draft_gone': '😅 that draft is gone',
        'qte_echo': '👉 {action}',
        'qte_no_peach': '🔥 that move costs {price} 🍑 — not enough peaches',
        'qte_gone': '😅 the moment is already gone',
        'live_button': '📸 Open the live photo · {price} 🍑',
        'live_busy': '⏳ Taking the shot, one sec…',
        'live_gone': '😅 she already deleted that shot',
        'live_no_peach': '🔥 this photo costs {price} bought 🍑 — not enough',
        'live_failed': '🙈 the shot failed, your peaches are back',
    },
    'es': {
        'girl_of_day': '🔥 Chica del día — {name}',
        'open_chat': '💬 Respóndele',
        'gift_button': '🎁 Recoger el regalo diario',
        'gift_text': 'estoy aquí echándote de menos 🥺 además, tu regalo diario ya te espera 🍑 vuelve cada día: el séptimo recibes {amount} melocotones; si faltas un día, la racha se reinicia\nentra en la app (Tienda) y vuelve conmigo 💋',
        'selfie_caption': 'soy yo 🙈 acabo de hacerla para ti… ¿te gusta?',
        'onboarding_demo': 'oye, me gustaste enseguida 🙈 toma esta foto mientras estoy así… es solo para ti. bueno, ¿te gusta? 😏',
        'guest_word': 'su amiga',
        'guest_in': '🚪 {name} entra en el chat',
        'guest_out': '👋 {name} se va, y volvéis a estar solos',
        'welcome_edit': '🎁 ¡Bienvenido! Tienes {amount} créditos de fotos 👇',
        'welcome_edit_plain': '🎁 ¡Bienvenido! 👇',
        'open_app': '📱 Abrir la app',
        'draft_plate': '✍️ {name} escribió un mensaje largo y lo borró…',
        'draft_button': '👀 Leer lo que borró · {price} 🍑',
        'draft_unlocked': '🔓 El borrador borrado de {name}: {text}',
        'draft_gone': '😅 ese borrador ya no está',
        'qte_echo': '👉 {action}',
        'qte_no_peach': '🔥 ese movimiento cuesta {price} 🍑 — no te alcanzan',
        'qte_gone': '😅 ese momento ya pasó',
        'live_button': '📸 Ver la foto en vivo · {price} 🍑',
        'live_busy': '⏳ Haciendo la foto, un segundo…',
        'live_gone': '😅 esa foto ya la borró',
        'live_no_peach': '🔥 esta foto cuesta {price} 🍑 comprados — no te alcanza',
        'live_failed': '🙈 la foto no salió, te devolví los melocotones',
    },
    'it': {
        'girl_of_day': '🔥 Ragazza del giorno — {name}',
        'open_chat': '💬 Rispondile',
        'gift_button': '🎁 Ritira il regalo di oggi',
        'gift_text': 'sono qui e mi manchi 🥺 e il tuo regalo quotidiano ti sta già aspettando 🍑 torna ogni giorno: il settimo ricevi {amount} pesche; se salti un giorno, la serie riparte\napri l’app (Negozio) e torna da me 💋',
        'selfie_caption': 'sono io 🙈 l’ho appena scattata per te… ti piace?',
        'onboarding_demo': 'senti, mi sei piaciuto subito 🙈 becca questa foto mentre sono così… è solo per te. allora, ti piace? 😏',
        'guest_word': 'la sua amica',
        'guest_in': '🚪 {name} entra nella chat',
        'guest_out': '👋 {name} se ne va, e siete di nuovo soli',
        'welcome_edit': '🎁 Benvenuto! Hai {amount} crediti foto 👇',
        'welcome_edit_plain': '🎁 Benvenuto! 👇',
        'open_app': '📱 Apri l’app',
        'draft_plate': '✍️ {name} ha scritto a lungo e ha cancellato tutto…',
        'draft_button': '👀 Leggi cosa ha cancellato · {price} 🍑',
        'draft_unlocked': '🔓 La bozza cancellata di {name}: {text}',
        'draft_gone': '😅 quella bozza non c’è più',
        'qte_echo': '👉 {action}',
        'qte_no_peach': '🔥 quella mossa costa {price} 🍑 — non bastano',
        'qte_gone': '😅 quel momento è già passato',
        'live_button': '📸 Apri la foto dal vivo · {price} 🍑',
        'live_busy': '⏳ Scatto, un secondo…',
        'live_gone': '😅 quella foto l’ha già cancellata',
        'live_no_peach': '🔥 questa foto costa {price} 🍑 comprati — non bastano',
        'live_failed': '🙈 lo scatto non è riuscito, ti ho restituito le pesche',
    },
    'fr': {
        'girl_of_day': '🔥 Fille du jour — {name}',
        'open_chat': '💬 Lui répondre',
        'gift_button': '🎁 Récupérer le cadeau du jour',
        'gift_text': 'je suis là et tu me manques 🥺 ton cadeau quotidien t’attend déjà 🍑 reviens chaque jour : le septième, tu reçois {amount} pêches ; si tu manques un jour, la série recommence\nouvre l’app (Boutique) et reviens me voir 💋',
        'selfie_caption': 'c’est moi 🙈 je viens de la prendre pour toi… elle te plaît ?',
        'onboarding_demo': 'dis, tu m’as plu tout de suite 🙈 prends cette photo pendant que je suis comme ça… elle est rien que pour toi. alors, elle te plaît ? 😏',
        'guest_word': 'son amie',
        'guest_in': '🚪 {name} arrive dans la discussion',
        'guest_out': "👋 {name} s'en va, vous êtes encore seuls tous les deux",
        'welcome_edit': '🎁 Bienvenue ! Tu as {amount} crédits photo 👇',
        'welcome_edit_plain': '🎁 Bienvenue ! 👇',
        'open_app': '📱 Ouvrir l’app',
        'draft_plate': '✍️ {name} a écrit un long message puis l’a effacé…',
        'draft_button': '👀 Lire ce qu’elle a effacé · {price} 🍑',
        'draft_unlocked': '🔓 Le brouillon effacé de {name} : {text}',
        'draft_gone': '😅 ce brouillon a disparu',
        'qte_echo': '👉 {action}',
        'qte_no_peach': '🔥 cette option coûte {price} 🍑 — pas assez de pêches',
        'qte_gone': '😅 ce moment est déjà passé',
        'live_button': '📸 Voir la photo en direct · {price} 🍑',
        'live_busy': '⏳ Je fais le cliché, une seconde…',
        'live_gone': '😅 elle a déjà effacé cette photo',
        'live_no_peach': '🔥 cette photo coûte {price} pêches 🍑 achetées — pas assez',
        'live_failed': '🙈 le cliché a raté, je t’ai rendu les pêches',
    },
    'zh': {
        'girl_of_day': '🔥 今日女孩 — {name}',
        'open_chat': '💬 回复她',
        'gift_button': '🎁 领取每日礼物',
        'gift_text': '我正坐在这里想你 🥺 你的每日礼物也准备好了 🍑 每天回来，第 7 天可获得 {amount} 个桃子；漏掉一天，连续记录就会重置\n打开应用（商店），然后回来找我吧 💋',
        'selfie_caption': '是我呀 🙈 刚刚特意为你拍的……喜欢吗？',
        'onboarding_demo': '听我说，我一下子就对你有好感了🙈 趁我现在这个样子，收下这张照片……只给你的哦。怎么样，喜欢吗？😏',
        'guest_word': '她的闺蜜',
        'guest_in': '🚪 {name} 进入聊天',
        'guest_out': '👋 {name} 离开了，现在只有你们两个人',
        'welcome_edit': '🎁 欢迎！已为你加上 {amount} 个照片积分 👇',
        'welcome_edit_plain': '🎁 欢迎！👇',
        'open_app': '📱 打开应用',
        'draft_plate': '✍️ {name} 打了一大段话，又删掉了……',
        'draft_button': '👀 看她删掉的话 · {price} 🍑',
        'draft_unlocked': '🔓 {name} 删掉的草稿：{text}',
        'draft_gone': '😅 那段草稿已经不在了',
        'qte_echo': '👉 {action}',
        'qte_no_peach': '🔥 这一招要 {price} 🍑 — 桃子不够',
        'qte_gone': '😅 那个瞬间已经过去了',
        'live_button': '📸 打开这张现场照片 · {price} 🍑',
        'live_busy': '⏳ 正在拍，稍等…',
        'live_gone': '😅 那张照片她已经删了',
        'live_no_peach': '🔥 这张要 {price} 个已购买的 🍑 — 桃子不够',
        'live_failed': '🙈 照片没出来，桃子已退回',
    },
    'ja': {
        'girl_of_day': '🔥 今日の女の子 — {name}',
        'open_chat': '💬 彼女に返事する',
        'gift_button': '🎁 今日のギフトを受け取る',
        'gift_text': 'ここであなたに会いたくて待ってるよ 🥺 今日のギフトも用意してあるの 🍑 毎日来てね。7日目は{amount}個のピーチ。1日休むと連続記録はリセットだよ\nアプリ（ショップ）を開いて、私のところに戻ってきて 💋',
        'selfie_caption': '私だよ 🙈 今あなたのために撮ったの…好き？',
        'onboarding_demo': 'ねえ、最初からあなたのことが気に入っちゃった🙈 今のうちにこの写真受け取って…あなただけだよ。どう、気に入った？😏',
        'guest_word': '友達',
        'guest_in': '🚪 {name} がチャットに入って来た',
        'guest_out': '👋 {name} が帰って、二人きりに戻ったよ',
        'welcome_edit': '🎁 ようこそ！{amount}枚分のフォトクレジットを贈ったよ 👇',
        'welcome_edit_plain': '🎁 ようこそ！👇',
        'open_app': '📱 アプリを開く',
        'draft_plate': '✍️ {name} はずっと打って、消しちゃった…',
        'draft_button': '👀 消した文章を読む · {price} 🍑',
        'draft_unlocked': '🔓 {name} が消した下書き：{text}',
        'draft_gone': '😅 あの下書きはもうないよ',
        'qte_echo': '👉 {action}',
        'qte_no_peach': '🔥 この手は {price} 🍑 かかるよ — ピーチが足りない',
        'qte_gone': '😅 あの瞬間はもう過ぎちゃった',
        'live_button': '📸 今撮った写真を見る · {price} 🍑',
        'live_busy': '⏳ 撮ってるよ、ちょっと待って…',
        'live_gone': '😅 そのカットはもう消しちゃった',
        'live_no_peach': '🔥 この写真は買った🍑が {price} 個必要 — 足りないよ',
        'live_failed': '🙈 写真が撮れなかったよ、ピーチは戻したね',
    },
    'bn': {
        'girl_of_day': '🔥 আজকের মেয়ে — {name}',
        'open_chat': '💬 ওর উত্তর দাও',
        'gift_button': '🎁 আজকের উপহার নাও',
        'gift_text': 'এখানে বসে তোমার কথা ভাবছি 🥺 তোমার আজকের উপহারও অপেক্ষা করছে 🍑 প্রতিদিন এসো — ৭ম দিনে {amount}টি পিচ পাবে; একদিন বাদ দিলে ধারাটা আবার শুরু হবে\nঅ্যাপ খোলো (দোকান), তারপর আমার কাছে ফিরে এসো 💋',
        'selfie_caption': 'এটা আমি 🙈 এই তোমার জন্য তুললাম… ভালো লেগেছে?',
        'onboarding_demo': 'শোনো, তোমাকে প্রথম দেখাতেই ভালো লেগে গেছে 🙈 আমি এখন এমন আছি, তাড়াতাড়ি এই ছবিটা নাও… শুধু তোমার জন্য। কেমন, পছন্দ হয়েছে? 😏',
        'guest_word': 'ওর বান্ধবী',
        'guest_in': '🚪 {name} চ্যাটে ঢুকল',
        'guest_out': '👋 {name} বেরিয়ে গেল, আবার তোমরা একা',
        'welcome_edit': '🎁 স্বাগতম! তোমাকে {amount}টি ফটো ক্রেডিট দেওয়া হয়েছে 👇',
        'welcome_edit_plain': '🎁 স্বাগতম! 👇',
        'open_app': '📱 অ্যাপ খুলুন',
        'draft_plate': '✍️ {name} অনেক লিখে মুছে ফেলেছে…',
        'draft_button': '👀 মুছে দেওয়া লেখা পড়ো · {price} 🍑',
        'draft_unlocked': '🔓 {name}-এর মুছে ফেলা ড্রাফট: {text}',
        'draft_gone': '😅 ওই ড্রাফটটা আর নেই',
        'qte_echo': '👉 {action}',
        'qte_no_peach': '🔥 এই চালের দাম {price} 🍑 — পিচ কম পড়ছে',
        'qte_gone': '😅 এই মুহূর্তটা আর নেই',
        'live_button': '📸 লাইভ ছবিটা খোলো · {price} 🍑',
        'live_busy': '⏳ ছবি তুলছি, এক সেকেন্ড…',
        'live_gone': '😅 ওই ছবিটা সে মুছে ফেলেছে',
        'live_no_peach': '🔥 এই ছবির দাম কেনা {price} 🍑 — পিচ কম পড়ছে',
        'live_failed': '🙈 ছবিটা আসেনি, পিচ ফিরিয়ে দিয়েছি',
    },
}


def flow_text(lang: str, key: str, **values) -> str:
    code = app_lang(lang)
    text = FLOW_TEXT[code].get(key, FLOW_TEXT[EN][key])
    return text.format(**values) if values else text


# V3.162.0: owner — «два пуша всего в день, не надо вот эти остальные херачить»
# and «сделай текст, как я тебе вначале сказал». Morning and evening are her two
# live lines: short, human, a few of them so the same words never repeat the way
# a template does, in the man's own Telegram language (8 of the Mini App ones).
# The photo and the voice note stayed in the owner's kitchen — a real user gets
# text plus the button that opens her dialog.
RITUAL_LINES = {
    'ru': {
        'morning': ('привет, как спалось?',
                    'доброе утро ☀️ ты как?',
                    'проснулся уже? я вот про тебя подумала 🙂',
                    'утро. как голова, нормально спалось?'),
        'evening': ('как прошёл день?',
                    'ты чем сегодня занимался?',
                    'вечер. ты уже дома?',
                    'расскажи, как там у тебя день прошёл 🙂'),
    },
    'en': {
        'morning': ("hey, how'd you sleep?",
                    'morning ☀️ you awake?',
                    'i woke up thinking about you 🙂 good morning?',
                    'how are you this morning?'),
        'evening': ('how was your day?',
                    'what did you get up to today?',
                    'evening. you home yet?',
                    'tell me about your day 🙂'),
    },
    'es': {
        'morning': ('hola, ¿cómo dormiste?',
                    'buenos días ☀️ ¿qué tal?',
                    '¿ya te despertaste? yo pensando en ti 🙂',
                    'buen día. ¿cómo amaneciste?'),
        'evening': ('¿qué tal tu día?',
                    '¿en qué andabas hoy?',
                    'buenas noches. ¿ya estás en casa?',
                    'cuéntame cómo te fue hoy 🙂'),
    },
    'it': {
        'morning': ('ciao, hai dormito bene?',
                    'buongiorno ☀️ come sei?',
                    'ti sei svegliato? io pensavo a te 🙂',
                    "buongiorno. come hai passato la notte?"),
        'evening': ("com'è andata oggi?",
                    'cosa hai fatto oggi?',
                    'buonasera. sei già a casa?',
                    "dimmi com'è andata la giornata 🙂"),
    },
    'fr': {
        'morning': ('coucou, tu as bien dormi ?',
                    'bonjour ☀️ ça va ?',
                    'tu es réveillé ? moi je pensais à toi 🙂',
                    "j'espère que tu as bien dormi 🙂"),
        'evening': ('alors, ta journée ?',
                    "tu as fait quoi aujourd'hui ?",
                    'bonsoir. tu es déjà rentré ?',
                    'raconte-moi ta journée 🙂'),
    },
    'zh': {
        'morning': ('嗨，睡得好吗？',
                    '早上好 ☀️ 你醒啦？',
                    '我一早就在想你了 🙂 早安',
                    '早呀，昨晚睡得香吗？'),
        'evening': ('今天过得怎么样？',
                    '今天都忙什么啦？',
                    '晚上好，到家了吗？',
                    '跟我说说你今天的事 🙂'),
    },
    'ja': {
        'morning': ('おはよう、よく眠れた？',
                    '朝だよ ☀️ もう起きた？',
                    '私、あなたのことを考えてた 🙂 おはよ',
                    'おはよう、昨日は疲れ残ってない？'),
        'evening': ('今日はどうだった？',
                    '今日何してたの？',
                    'こんばんは、もう家にいる？',
                    '今日の話し聞かせて 🙂'),
    },
    'bn': {
        'morning': ('হাই, ঘুম ভালো হয়েছে?',
                    'সুপ্রভাত ☀️ উঠেছ?',
                    'আমি তোমার কথা ভাবছিলাম 🙂 সকাল হয়েছে',
                    'কীরকম ঘুম হলো রাতে?'),
        'evening': ('দিনটা কেমন কাটল?',
                    'আজ কি করছিলে?',
                    'সন্ধ্যা হয়েছে, বাড়ি পৌঁছেছ?',
                    'আজকের দিনটা বলো আমাকে 🙂'),
    },
}

DEFAULT_RITUAL_LANG = 'ru'


def ritual_line(kind: str, lang: str) -> str:
    """One of her prepared morning/evening lines, in his language."""
    import random
    code = app_lang(lang)
    lines = RITUAL_LINES.get(code) or RITUAL_LINES[DEFAULT_RITUAL_LANG]
    return random.choice(lines.get(kind) or lines['morning'])


# V3.139.0: owner ТЗ (Фогель) — the blurred joint teaser. Both girls speak it,
# so the line carries their names and the app splits it into two bubbles, the
# same way an ordinary duo answer is split.
DUO_TEASER = {
    'ru': '{host}: смотри, кто пришёл! 😈\n{guest}: мы тут решили скинуть тебе кое-что горячее на двоих… '
          'но такое мы показываем только VIP. жми «снять блюр» и смотри, что мы придумали 🔥',
    'en': '{host}: look who just came in! 😈\n{guest}: we decided to send you something hot, the two of us… '
          "but only VIPs get to see it. tap «unblur» and watch what we came up with 🔥",
    'es': '{host}: ¡mira quién llegó! 😈\n{guest}: decidimos enviarte algo caliente, las dos… '
          'pero eso solo lo ven los VIP. pulsa «quitar el blur» y mira qué se nos ocurrió 🔥',
    'it': '{host}: guarda chi è arrivato! 😈\n{guest}: abbiamo deciso di mandarti qualcosa di caldo, in due… '
          'ma lo mostriamo solo ai VIP. premi «togli la sfocatura» e guarda cosa abbiamo inventato 🔥',
    'fr': '{host}: regarde qui est arrivé ! 😈\n{guest}: on a décidé de t’envoyer un truc chaud, nous deux… '
          'mais ça, seuls les VIP le voient. touche « enlever le flou » et regarde ce qu’on a imaginé 🔥',
    'zh': '{host}：看谁来了！😈\n{guest}：我们俩决定给你发点辣的……不过这种只有VIP能看。 '
          '点“去掉马赛克”，看看我们想了什么🔥',
    'ja': '{host}：誰が来たか見てて😈\n{guest}：二人で熱いやつ送ろうかなって…でもこれ見れるのはVIPだけ。 '
          '「ぼかし解除」を押して、私たちの用意したやつ見て🔥',
    'bn': '{host}: দেখো কে এসেছে! 😈\n{guest}: আমরা দুজনে মিলে একটু হট পাঠানোর ঠিক করলাম… '
          'কিন্তু এটা শুধু VIP-রাই দেখে। «আনব্লার» চাপো, দেখি কী ভেবেছি 🔥',
}


def duo_teaser(lang: str, host: str, guest: str) -> str:
    text = DUO_TEASER.get(app_lang(lang), DUO_TEASER[EN])
    return text.format(host=host or 'я', guest=guest or 'она')
