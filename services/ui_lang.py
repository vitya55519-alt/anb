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

# Main reply keyboard labels: key -> (ru, en). Row layout lives in MAIN_KB_ROWS.
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
    # old keyboards still resolve; MAIN_KB_ROWS shows partner instead of invite.
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
}

# V3.38.0: the Come Closer funnel layout — the Mini App is the product, the
# chat keyboard is its launcher. Old keys stay in KB_LABELS so cached reply
# keyboards from earlier versions keep resolving to their handlers.
# V3.40.0: owner benchmarked the Come Closer main menu (screenshot) — the two
# app actions each get their OWN full-width row instead of sharing one.
# V3.41.0: owner asked to keep terms/privacy reachable from the main menu, so
# the «📜 Документы» (Условия + Privacy) row is pinned at the bottom. Character
# selection is gone from the chat funnel — it lives in the Mini App now.
# V3.42.0: the owner wants the partner program to be a BIG full-width button
# («Партнёрская программа», not «Партнёрка»); support shares the bottom row
# with the legal documents so compliance stays one tap away.
MAIN_KB_ROWS = [
    ['app'],
    ['credits'],
    # V3.62.11: zero purchases in 30 days — Premium was not reachable from
    # the bot menu at all, so it gets its own row again under the peaches.
    ['premium'],
    ['paint'],
    ['partner'],
    ['support', 'legal'],
]

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
        'picker_prompt': 'с кем хочешь познакомиться? выбери ту, что нравится, — потом можно сменить в любой момент 👇',
        'girl_of_day': '🔥 Девушка дня — {name}',
        'picker_agata_01': '🥀 Агата — нежная готка, шепчет ASMR',
        'picker_anna_01': '👩🏻 Анна — нежность и страсть',
        'picker_alisa_01': '📚 Алиса — застенчивая учительница',
        'picker_kamila_01': '🏎 Камила — горячая южанка',
        'picker_rita_01': '🦊 Рита — рыжая хохотушка',
        'reply_in_app': '💬 ответить ей в приложении',
        'open_chat': '💬 Ответить ей',
        'gift_button': '🎁 Забрать дневной подарок',
        'gift_text': 'я тут сижу и скучаю по тебе 🥺 а ещё — у тебя уже копится дневной подарок 🍑 заходи каждый день — на 7-й день дают {amount} персиков, серия сгорает, если пропустить день\nзагляни в приложение (Магазин) и возвращайся ко мне 💋',
        'selfie_caption': 'это я 🙈 только что сфоткалась для тебя… нравится?',
        'welcome_bonus': '🎁 добро пожаловать! подарил тебе {amount} фото-кредитов — попробуй первое фото бесплатно.\nВсе героини, чаты, картинки и магазин — в приложении 👇',
        'welcome_plain': 'Добро пожаловать 🙂 все героини, чаты и магазин — в приложении 👇',
    },
    'en': {
        'picker_prompt': 'who do you want to talk to first? pick the one you like — you can change her any time 👇',
        'girl_of_day': '🔥 Girl of the day — {name}',
        'picker_agata_01': '🥀 Agata — tender goth, whispers ASMR',
        'picker_anna_01': '👩🏻 Anna — tenderness and passion',
        'picker_alisa_01': '📚 Alisa — shy young teacher',
        'picker_kamila_01': '🏎 Kamila — hot southern racer',
        'picker_rita_01': '🦊 Rita — red-haired tease',
        'reply_in_app': '💬 reply to her in the app',
        'open_chat': '💬 Open the chat',
        'gift_button': '🎁 Claim your daily gift',
        'gift_text': "i'm sitting here missing you 🥺 and your daily gift is already growing 🍑 come back every day — on day 7 you get {amount} peaches; miss a day and the streak resets\nopen the app (Shop) and come back to me 💋",
        'selfie_caption': 'this is me 🙈 just took it for you… do you like it?',
        'welcome_bonus': '🎁 welcome! I gave you {amount} photo credits — try your first photo for free.\nAll the heroines, chats, pictures and the shop live in the app 👇',
        'welcome_plain': 'Welcome 🙂 the heroines, chats and the shop live in the app 👇',
    },
    'es': {
        'picker_prompt': '¿con quién quieres hablar primero? elige la que te guste; puedes cambiarla cuando quieras 👇',
        'girl_of_day': '🔥 Chica del día — {name}',
        'picker_agata_01': '🥀 Agata — gótica dulce, susurra ASMR',
        'picker_anna_01': '👩🏻 Anna — ternura y pasión',
        'picker_alisa_01': '📚 Alisa — profesora joven y tímida',
        'picker_kamila_01': '🏎 Kamila — piloto sureña y atrevida',
        'picker_rita_01': '🦊 Rita — pelirroja y bromista',
        'reply_in_app': '💬 respóndele en la app',
        'open_chat': '💬 Respóndele',
        'gift_button': '🎁 Recoger el regalo diario',
        'gift_text': 'estoy aquí echándote de menos 🥺 además, tu regalo diario ya te espera 🍑 vuelve cada día: el séptimo recibes {amount} melocotones; si faltas un día, la racha se reinicia\nentra en la app (Tienda) y vuelve conmigo 💋',
        'selfie_caption': 'soy yo 🙈 acabo de hacerla para ti… ¿te gusta?',
        'welcome_bonus': '🎁 ¡bienvenido! te regalé {amount} créditos de fotos: prueba tu primera foto gratis.\nTodas las chicas, chats, imágenes y la tienda están en la app 👇',
        'welcome_plain': 'Bienvenido 🙂 las chicas, chats y la tienda están en la app 👇',
    },
    'it': {
        'picker_prompt': 'con chi vuoi parlare prima? scegli quella che ti piace: puoi cambiarla quando vuoi 👇',
        'girl_of_day': '🔥 Ragazza del giorno — {name}',
        'picker_agata_01': '🥀 Agata — gotica dolce, sussurra ASMR',
        'picker_anna_01': '👩🏻 Anna — dolcezza e passione',
        'picker_alisa_01': '📚 Alisa — giovane insegnante timida',
        'picker_kamila_01': '🏎 Kamila — pilota del sud audace',
        'picker_rita_01': '🦊 Rita — rossa e scherzosa',
        'reply_in_app': "💬 rispondile nell'app",
        'open_chat': '💬 Rispondile',
        'gift_button': '🎁 Ritira il regalo di oggi',
        'gift_text': 'sono qui e mi manchi 🥺 e il tuo regalo quotidiano ti sta già aspettando 🍑 torna ogni giorno: il settimo ricevi {amount} pesche; se salti un giorno, la serie riparte\napri l’app (Negozio) e torna da me 💋',
        'selfie_caption': 'sono io 🙈 l’ho appena scattata per te… ti piace?',
        'welcome_bonus': '🎁 benvenuto! ti ho regalato {amount} crediti foto: prova la prima foto gratis.\nTutte le ragazze, chat, immagini e il negozio sono nell’app 👇',
        'welcome_plain': 'Benvenuto 🙂 ragazze, chat e negozio sono nell’app 👇',
    },
    'fr': {
        'picker_prompt': 'avec qui veux-tu parler en premier ? choisis celle qui te plaît — tu pourras changer à tout moment 👇',
        'girl_of_day': '🔥 Fille du jour — {name}',
        'picker_agata_01': '🥀 Agata — gothique douce, chuchote en ASMR',
        'picker_anna_01': '👩🏻 Anna — tendresse et passion',
        'picker_alisa_01': '📚 Alisa — jeune prof timide',
        'picker_kamila_01': '🏎 Kamila — pilote du sud audacieuse',
        'picker_rita_01': '🦊 Rita — rousse et taquine',
        'reply_in_app': '💬 lui répondre dans l’app',
        'open_chat': '💬 Lui répondre',
        'gift_button': '🎁 Récupérer le cadeau du jour',
        'gift_text': 'je suis là et tu me manques 🥺 ton cadeau quotidien t’attend déjà 🍑 reviens chaque jour : le septième, tu reçois {amount} pêches ; si tu manques un jour, la série recommence\nouvre l’app (Boutique) et reviens me voir 💋',
        'selfie_caption': 'c’est moi 🙈 je viens de la prendre pour toi… elle te plaît ?',
        'welcome_bonus': '🎁 bienvenue ! je t’ai offert {amount} crédits photo — essaie ta première photo gratuitement.\nToutes les filles, tchats, images et la boutique sont dans l’app 👇',
        'welcome_plain': 'Bienvenue 🙂 les filles, tchats et la boutique sont dans l’app 👇',
    },
    'zh': {
        'picker_prompt': '想先和谁聊天？选一个你喜欢的女孩，之后随时可以更换 👇',
        'girl_of_day': '🔥 今日女孩 — {name}',
        'picker_agata_01': '🥀 阿加塔 — 温柔的哥特女孩，轻声 ASMR',
        'picker_anna_01': '👩🏻 安娜 — 温柔与热情',
        'picker_alisa_01': '📚 阿丽莎 — 害羞的年轻老师',
        'picker_kamila_01': '🏎 卡米拉 — 热情的南方赛车手',
        'picker_rita_01': '🦊 丽塔 — 爱笑的红发女孩',
        'reply_in_app': '💬 在应用里回复她',
        'open_chat': '💬 回复她',
        'gift_button': '🎁 领取每日礼物',
        'gift_text': '我正坐在这里想你 🥺 你的每日礼物也准备好了 🍑 每天回来，第 7 天可获得 {amount} 个桃子；漏掉一天，连续记录就会重置\n打开应用（商店），然后回来找我吧 💋',
        'selfie_caption': '是我呀 🙈 刚刚特意为你拍的……喜欢吗？',
        'welcome_bonus': '🎁 欢迎！送你 {amount} 个照片积分，第一张图片免费体验。\n所有女孩、聊天、图片和商店都在应用里 👇',
        'welcome_plain': '欢迎 🙂 女孩、聊天和商店都在应用里 👇',
    },
    'ja': {
        'picker_prompt': '最初に誰と話す？好きな子を選んでね。あとでいつでも変更できるよ 👇',
        'girl_of_day': '🔥 今日の女の子 — {name}',
        'picker_agata_01': '🥀 アガタ — 優しいゴス系、ASMRをささやく',
        'picker_anna_01': '👩🏻 アンナ — 優しさと情熱',
        'picker_alisa_01': '📚 アリサ — 内気な若い先生',
        'picker_kamila_01': '🏎 カミラ — 情熱的な南のレーサー',
        'picker_rita_01': '🦊 リタ — 赤毛のお茶目な子',
        'reply_in_app': '💬 アプリで返事する',
        'open_chat': '💬 彼女に返事する',
        'gift_button': '🎁 今日のギフトを受け取る',
        'gift_text': 'ここであなたに会いたくて待ってるよ 🥺 今日のギフトも用意してあるの 🍑 毎日来てね。7日目は{amount}個のピーチ。1日休むと連続記録はリセットだよ\nアプリ（ショップ）を開いて、私のところに戻ってきて 💋',
        'selfie_caption': '私だよ 🙈 今あなたのために撮ったの…好き？',
        'welcome_bonus': '🎁 ようこそ！{amount}枚分のフォトクレジットをプレゼント。最初の画像を無料で試してね。\n女の子、チャット、画像、ショップはすべてアプリにあるよ 👇',
        'welcome_plain': 'ようこそ 🙂 女の子、チャット、ショップはアプリにあるよ 👇',
    },
    'bn': {
        'picker_prompt': 'প্রথমে কার সাথে কথা বলতে চাও? যাকে পছন্দ তাকে বেছে নাও — পরে যেকোনো সময় বদলাতে পারবে 👇',
        'girl_of_day': '🔥 আজকের মেয়ে — {name}',
        'picker_agata_01': '🥀 আগাতা — কোমল গথিক, ফিসফিসে ASMR',
        'picker_anna_01': '👩🏻 আন্না — কোমলতা আর আবেগ',
        'picker_alisa_01': '📚 আলিসা — লাজুক তরুণ শিক্ষিকা',
        'picker_kamila_01': '🏎 কামিলা — দুঃসাহসী দক্ষিণী রেসার',
        'picker_rita_01': '🦊 রিতা — লাল চুলের চঞ্চল মেয়ে',
        'reply_in_app': '💬 অ্যাপে ওর উত্তর দাও',
        'open_chat': '💬 ওর উত্তর দাও',
        'gift_button': '🎁 আজকের উপহার নাও',
        'gift_text': 'এখানে বসে তোমার কথা ভাবছি 🥺 তোমার আজকের উপহারও অপেক্ষা করছে 🍑 প্রতিদিন এসো — ৭ম দিনে {amount}টি পিচ পাবে; একদিন বাদ দিলে ধারাটা আবার শুরু হবে\nঅ্যাপ খোলো (দোকান), তারপর আমার কাছে ফিরে এসো 💋',
        'selfie_caption': 'এটা আমি 🙈 এই তোমার জন্য তুললাম… ভালো লেগেছে?',
        'welcome_bonus': '🎁 স্বাগতম! তোমাকে {amount}টি ফটো ক্রেডিট দিলাম — প্রথম ছবিটি ফ্রি বানাও।\nসব মেয়ে, চ্যাট, ছবি আর দোকান অ্যাপেই আছে 👇',
        'welcome_plain': 'স্বাগতম 🙂 মেয়েরা, চ্যাট আর দোকান অ্যাপেই আছে 👇',
    },
}


def flow_text(lang: str, key: str, **values) -> str:
    code = app_lang(lang)
    text = FLOW_TEXT[code].get(key, FLOW_TEXT[EN][key])
    return text.format(**values) if values else text
