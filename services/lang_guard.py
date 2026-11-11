"""V3.98.0: she answers in the language he writes in.

3 Nov 2026 backup: 207 of 1475 replies to English messages (14%) came back in
Russian, 71 of 107 English-writing users got a Russian line at least once —
«Send a video» was answered with a story about a car dealership in Russian.
The persona prompt and the history are Russian, so the model slips back.

Two cheap defences, both pure text checks (no extra LLM call unless the check
fails): a short system directive right before his message, and — if the answer
still came out in Cyrillic — one regeneration with a firmer directive.
"""
from __future__ import annotations

import re

_CYR = re.compile(r'[А-Яа-яЁё]')
_LAT = re.compile(r'[A-Za-z]')
_WORD = re.compile(r"[a-z']+")
# common English function words; keyboard-layout gibberish typed by a Russian
# speaker («ghbdtn», «ltgkjq») never contains them
_EN_WORDS = frozenset((
    'i', 'you', 'the', 'and', 'to', 'is', 'are', 'am', 'it', 'me', 'my', 'we', 'your', 'what', 'how', 'why',
    'where', 'when', 'who', 'can', 'do', 'does', 'did', 'will', 'want', 'wanna', 'send', 'show', 'send',
    'pic', 'pics', 'photo', 'video', 'hi', 'hey', 'hello', 'yes', 'no', 'not', 'please', 'pls', 'with', 'for',
    'of', 'in', 'on', 'at', 'this', 'that', 'a', 'an', 'be', 'have', 'got', 'just', 'like', 'love', 'too',
    'tell', 'more', 'now', 'good', 'nice', 'ok', 'okay', 'thanks', 'thx', 'sexy', 'hot', 'baby', 'babe',
    'name', 'day', 'night', 'lol', 'fuck', 'naked', 'nude', 'dont', "don't", "i'm", "you're", "it's",
    'so', 'if', 'but', 'or', 'from', 'her', 'she', 'he', 'his', 'let', 'lets', "let's", 'come', 'see',
))


def is_cyrillic_dominant(text: str) -> bool:
    cyr = len(_CYR.findall(text or ''))
    lat = len(_LAT.findall(text or ''))
    return cyr > lat and cyr >= 6


def looks_english(text: str, language_code: str | None = None, recent_user_texts=()) -> bool:
    """True when his message is English: Latin letters only and either an
    English function word in it, or an English Telegram account, or his last
    messages were English too (so «ok», «hmm» keep the language)."""
    t = (text or '').strip()
    if not t or _CYR.search(t):
        return False
    letters = len(_LAT.findall(t))
    if letters < 2:
        return False
    words = _WORD.findall(t.lower())
    if any(w in _EN_WORDS for w in words):
        return True
    if (language_code or '').lower().startswith('en') and letters >= 3:
        return True
    for prev in list(recent_user_texts)[-3:]:
        p = (prev or '').strip()
        if p and not _CYR.search(p) and any(w in _EN_WORDS for w in _WORD.findall(p.lower())):
            return True
    return False


DIRECTIVE = (
    'ВАЖНО: пользователь пишет по-английски. Ответь ТОЛЬКО на английском — живым разговорным английским, '
    'без единого русского слова. Оставайся в роли и в своём характере; действия в *звёздочках* и эмодзи '
    'тоже на английском, как будто ты родом из его страны. Стиль: как в мессенджере — коротко, небрежно, '
    'без разбора поведения собеседника и без объяснения своих реакций; проявляй инициативу.'
)
STRICT_DIRECTIVE = (
    'СТРОГО: твой предыдущий ответ вышел по-русски, а пользователь пишет по-английски. Напиши этот ответ '
    'заново ПОЛНОСТЬЮ на английском. Ни одной русской буквы. Тот же смысл, тот же характер.'
)


# V3.105.0: English words slipping into a Russian reply («нормально, especially
# когда это важное дело») — MiniMax does it now and then. A short directive for
# Russian talks, and one cheap repair call when a reply still has stray words.
import os as _os

RU_PURITY_ENABLED = _os.getenv('LANG_RU_PURITY_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')
_LAT_WORD = re.compile(r"(?<![A-Za-z0-9_@/.#])[A-Za-z][A-Za-z'\-]{2,}(?![A-Za-z0-9_@/.])")
# words that are fine in a Russian chat with this bot (product names, slang)
_ALLOWED = frozenset((
    'premium', 'vip', 'stars', 'telegram', 'tg', 'ok', 'okay', 'lol', 'wow', 'omg', 'sms', 'iphone',
    'instagram', 'inst', 'tiktok', 'youtube', 'netflix', 'wifi', 'wi-fi', 'online', 'offline', 'selfie',
    'emoji', 'gif', 'mp3', 'usb', 'pdf', 'xxx', 'bmw', 'audi', 'mercedes', 'kia', 'lada', 'nike', 'adidas',
    'zara', 'apple', 'samsung', 'xiaomi', 'playstation', 'xbox', 'ps5', 'dota', 'cs', 'fifa', 'gta',
    'minecraft', 'spotify', 'whatsapp', 'vk', 'ozon', 'wildberries', 'yandex', 'google', 'chatgpt', 'ai',
))

RU_DIRECTIVE = (
    'Пиши только по-русски: ни одного английского слова посреди фразы (не «especially», «anyway», «baby» — '
    'а «особенно», «короче», «малыш»). Латиницей можно только названия брендов и то, что он сам так написал.'
)


def stray_english(answer: str, user_texts=()) -> list[str]:
    """English words inside a Russian reply that he did not use himself."""
    if not RU_PURITY_ENABLED or not is_cyrillic_dominant(answer):
        return []
    his = set()
    for t in user_texts or ():
        his.update(w.lower() for w in _LAT_WORD.findall(t or ''))
    out = []
    for w in _LAT_WORD.findall(answer or ''):
        lw = w.lower()
        if lw in _ALLOWED or lw in his or w.isupper() or lw in out:
            continue
        out.append(lw)
    return out


def repair_prompt(answer: str, words: list[str]) -> list[dict]:
    return [
        {'role': 'system', 'content': (
            'Ты корректор. В русском сообщении девушки проскочили английские слова: ' + ', '.join(words) +
            '. Замени каждое на естественное русское слово или выражение по смыслу. Больше НИЧЕГО не меняй: '
            'тот же текст, те же эмодзи, та же пунктуация и регистр. Верни только исправленное сообщение.')},
        {'role': 'user', 'content': answer},
    ]


# ── V3.117.0: she talks in HIS language, not only RU/EN ──────────────────────
# Owner: «бенгальский сделаем, чтобы интерфейс был, и она общалась на этих
# языках — мы же теряем аудиторию». The app interface already had ES/IT/FR/
# ZH/JA, but the chat only knew Russian and English: a Bengali or Spanish
# message got a Russian answer. Now the language comes from his own text
# (script or common words), then from his recent messages, then from the
# language he picked in the app, then from his Telegram account language.
# Russian stays the default and a Cyrillic message is always answered in
# Russian, so the Russian chat is untouched.

RU = 'ru'
EN = 'en'

# code -> (how to say «on <language>» in a Russian directive, the language's own name)
LANG_NAMES = {
    'en': ('английском', 'English'),
    'es': ('испанском', 'Español'),
    'it': ('итальянском', 'Italiano'),
    'fr': ('французском', 'Français'),
    'pt': ('португальском', 'Português'),
    'de': ('немецком', 'Deutsch'),
    'bn': ('бенгальском (বাংলা)', 'বাংলা'),
    'hi': ('хинди (हिन्दी)', 'हिन्दी'),
    'ar': ('арабском', 'العربية'),
    'zh': ('китайском', '中文'),
    'ja': ('японском', '日本語'),
    'ko': ('корейском', '한국어'),
    'th': ('тайском', 'ไทย'),
}
SUPPORTED = frozenset(LANG_NAMES) | {RU}

# scripts: one letter of these is enough to know the language
_SCRIPTS = (
    ('bn', re.compile(r'[ঀ-৿]')),
    ('hi', re.compile(r'[ऀ-ॿ]')),
    ('ar', re.compile(r'[؀-ۿ]')),
    ('ko', re.compile(r'[가-힯ᄀ-ᇿ]')),
    ('ja', re.compile(r'[぀-ヿ]')),
    ('th', re.compile(r'[฀-๿]')),
    ('zh', re.compile(r'[一-鿿]')),
)
_SCRIPT_RE = {code: rx for code, rx in _SCRIPTS}
_LAT_WORD_ANY = re.compile(r"[a-zà-ÿ']+")

# short everyday words that are not English (and not each other's, mostly)
_LATIN_WORDS = {
    'es': frozenset((
        'hola', 'qué', 'que', 'cómo', 'como', 'estás', 'estas', 'eres', 'tú', 'yo', 'muy', 'pero', 'por',
        'para', 'quiero', 'gracias', 'bien', 'sí', 'hermosa', 'guapa', 'amor', 'dónde', 'donde', 'cuándo',
        'tienes', 'soy', 'eso', 'esto', 'buenos', 'días', 'dias', 'noches', 'también', 'nada', 'mucho',
        'una', 'los', 'las', 'del', 'el', 'y', 'mi', 'te', 'quieres', 'puedes', 'foto', 'linda', 'bonita',
        'cariño', 'mañana', 'ahora', 'hoy', 'aquí', 'vale', 'claro', 'jaja', 'jajaja', 'besos', 'tengo',
    )),
    'it': frozenset((
        'ciao', 'stai', 'sono', 'sei', 'grazie', 'bella', 'bellissima', 'cosa', 'che', 'perché',
        'perche', 'anche', 'molto', 'tutto', 'voglio', 'vuoi', 'buongiorno', 'buonasera', 'notte', 'amore',
        'tesoro', 'io', 'tu', 'non', 'di', 'il', 'lo', 'gli', 'della', 'questo', 'questa', 'dove', 'quando',
        'adesso', 'oggi', 'domani', 'bene', 'si', 'mi', 'ti', 'piace', 'baci', 'hai', 'fammi',
    )),
    'fr': frozenset((
        'bonjour', 'bonsoir', 'salut', 'merci', 'je', 'tu', 'suis', 'est', 'avec', 'pourquoi',
        'comment', 'ça', 'ca', 'oui', 'non', 'très', 'tres', 'belle', 'jolie', 'mon', 'mes',
        'toi', 'moi', 'veux', 'peux', 'aussi', 'mais', 'les', 'des', 'une', 'le', 'la', 'et', 'qui', 'quoi',
        'où', 'quand', 'aujourd', "aujourd'hui", 'demain', 'bisous', "c'est", "j'ai", 'pas', 'chérie',
    )),
    'pt': frozenset((
        'olá', 'ola', 'obrigado', 'obrigada', 'você', 'voce', 'não', 'nao', 'tudo', 'bem', 'estou',
        'muito', 'linda', 'gostosa', 'quero', 'eu', 'meu', 'minha', 'amor', 'tchau', 'beijos', 'agora',
        'hoje', 'amanhã', 'então', 'também', 'tambem', 'uma', 'está', 'esta', 'foto', 'sim',
    )),
    'de': frozenset((
        'hallo', 'danke', 'ich', 'du', 'bist', 'nicht', 'wie', 'und', 'bitte', 'ja', 'nein', 'schön',
        'schon', 'liebe', 'mein', 'meine', 'dich', 'mich', 'was', 'wo', 'warum', 'heute', 'morgen', 'gut',
        'sehr', 'auch', 'aber', 'ist', 'das', 'der', 'die', 'ein', 'eine', 'hast', 'habe', 'willst', 'zeig',
    )),
}
# the same short word reads as several languages; letters with marks settle it
_LATIN_MARKS = {
    'es': re.compile(r'[ñ¿¡]'),
    'pt': re.compile(r'[ãõ]'),
    'de': re.compile(r'[ßäöü]'),
    'fr': re.compile(r'[êœëî]'),
}
# Bengali and Hindi speakers often type their language in Latin letters
ROMANIZED = frozenset(('bn', 'hi'))


def norm_code(code: str | None) -> str:
    """'bn-IN', 'pt-br', 'zh-hans' -> a supported code, or ''."""
    c = (code or '').strip().lower().replace('_', '-')
    if not c:
        return ''
    base = c.split('-')[0]
    return base if base in SUPPORTED else ''


def text_lang(text: str, preferred: str = '') -> str:
    """The language his message is clearly written in, or '' when the text
    alone does not say (emoji, «ok», a name, layout gibberish)."""
    t = (text or '').strip()
    if not t:
        return ''
    cyr = len(_CYR.findall(t))
    if cyr >= 2 or (cyr and cyr >= len(_LAT.findall(t))):
        return RU
    for code, rx in _SCRIPTS:
        if rx.search(t):
            if code == 'zh' and preferred == 'ja':
                return 'ja'
            return code
    letters = len(_LAT.findall(t))
    if letters < 2:
        return ''
    low = t.lower()
    words = _LAT_WORD_ANY.findall(low)
    scores = {code: sum(1 for w in words if w in ws) for code, ws in _LATIN_WORDS.items()}
    for code, rx in _LATIN_MARKS.items():
        if rx.search(low):
            scores[code] = scores.get(code, 0) + 2
    scores[EN] = sum(1 for w in words if w in _EN_WORDS)
    best = max(scores.values())
    if best <= 0:
        # «tumi kemon acho» — Bengali in Latin letters, if that is his language
        return preferred if preferred in ROMANIZED else ''
    top = [c for c, s in scores.items() if s == best]
    if preferred in top:
        return preferred
    if EN in top:
        return EN
    return top[0] if len(top) == 1 else ''


def detect_lang(text: str, language_code: str | None = None, recent_user_texts=(), preferred: str = '') -> str:
    """The language to answer this message in. Russian unless something says otherwise."""
    preferred = norm_code(preferred)
    own = text_lang(text, preferred)
    if own:
        return own
    for prev in reversed(list(recent_user_texts)[-4:]):
        got = text_lang(prev, preferred)
        if got:
            return got
    if preferred:
        return preferred
    code = norm_code(language_code)
    if code == EN:
        # V3.98.0 rule: an English account with a Latin word keeps English;
        # a Russian with an English Telegram sending a sticker stays Russian
        return EN if len(_LAT.findall(text or '')) >= 3 else RU
    return code or RU


def directive(lang: str) -> str:
    """System line right before his message: answer only in this language."""
    if lang == EN:
        return DIRECTIVE
    ru_name, own = LANG_NAMES.get(lang, ('его языке', ''))
    line = (f'ВАЖНО: пользователь пишет на {ru_name}. Ответь ТОЛЬКО на {ru_name} языке ({own}) — живо и '
            f'разговорно, как носитель, без единого русского слова. Оставайся в роли и в своём характере; '
            f'действия в *звёздочках* тоже на этом языке. Стиль: как в мессенджере — коротко, небрежно, '
            f'без разбора поведения собеседника и без объяснения своих реакций; проявляй инициативу.')
    if lang in ROMANIZED:
        line += (' Если он пишет на своём языке латиницей, отвечай так же латиницей; если родным письмом — '
                 'родным письмом.')
    return line


def strict_directive(lang: str) -> str:
    if lang == EN:
        return STRICT_DIRECTIVE
    ru_name, own = LANG_NAMES.get(lang, ('его языке', ''))
    return (f'СТРОГО: твой предыдущий ответ вышел не на том языке, а пользователь пишет на {ru_name}. '
            f'Напиши этот ответ заново ПОЛНОСТЬЮ на {ru_name} языке ({own}). Ни одной русской буквы. '
            f'Тот же смысл, тот же характер.')


def reply_ok(answer: str, lang: str, user_text: str = '') -> bool:
    """False when a reply for a foreign-language talk came out wrong:
    mostly Cyrillic, or plain Latin while he writes in his own script."""
    if lang == RU:
        return True
    if is_cyrillic_dominant(answer):
        return False
    rx = _SCRIPT_RE.get(lang)
    if rx and rx.search(user_text or '') and not rx.search(answer or ''):
        if lang == 'ja' and _SCRIPT_RE['zh'].search(answer or ''):
            return True
        return False
    return True


def name_line(lang: str) -> str:
    """For the prompts she writes first in: «Пиши на <языке>.»"""
    if lang == RU or lang not in LANG_NAMES:
        return ''
    ru_name, own = LANG_NAMES[lang]
    return (f' Пиши только на {ru_name} языке ({own}), он говорит на нём. '
            f'Стиль: коротко и по-живому, без объяснения своих реакций; проявляй инициативу.')


def stored_lang(db_user_id) -> str:
    """Last language he wrote in (or picked in the app), '' if unknown."""
    try:
        from models.app_models import User
        from services.db import SessionLocal
        with SessionLocal() as session:
            user = session.get(User, int(db_user_id))
            return norm_code(getattr(user, 'chat_lang', '') if user else '')
    except Exception:
        return ''


def remember(db_user_id, lang: str) -> None:
    lang = norm_code(lang)
    if not lang:
        return
    try:
        from models.app_models import User
        from services.db import SessionLocal
        with SessionLocal() as session:
            user = session.get(User, int(db_user_id))
            if user is not None and (user.chat_lang or '') != lang:
                user.chat_lang = lang
                session.commit()
    except Exception:
        pass


def lang_for_push(db_user_id, language_code: str | None = None) -> str:
    """Language for a message she sends first (no text of his to read)."""
    got = stored_lang(db_user_id)
    if got:
        return got
    code = norm_code(language_code)
    return code or RU
