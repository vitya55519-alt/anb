from __future__ import annotations
import re

# Character motifs must not become filler. Russian stems need their endings
# before the closing word boundary; bare stems such as «прогул» never matched.
THEMES = {
    "coffee/cafe": re.compile(r"\b(кофе|кафе|латте|капучино|эспрессо|coffee|cafe|latte|cappuccino|espresso)\b", re.I),
    "walk/city": re.compile(r"\b(прогул[а-яё]*|гуля[а-яё]*|парк[а-яё]*|набереж[а-яё]*|вышла пройтись|город[а-яё]*[^.!?\n]*вечер[а-яё]*|walk|park|embankment)\b", re.I),
    "home/cozy": re.compile(r"\b(дома|домашн[а-яё]*|уют[а-яё]*|диван[а-яё]*|плед[а-яё]*|home|cozy|sofa)\b", re.I),
    "gym": re.compile(r"\b(зал(?:а|е|у|ом|ы|ов|ам|ами|ах)?|трениров[а-яё]*|спорт[а-яё]*|gym|workout)\b", re.I),
    "food/restaurant": re.compile(r"\b(ресторан[а-яё]*|ужин[а-яё]*|поесть|ед(?:а|ы|е|у|ой)|restaurant|dinner|food)\b", re.I),
    "outfit/fashion": re.compile(r"\b(образ(?:а|е|у|ом|ы|ов|ам|ами|ах)?|одежд[а-яё]*|плать[а-яё]*|fashion|outfit|dress)\b", re.I),
}


def _field(message, name: str):
    return message.get(name, '') if isinstance(message, dict) else getattr(message, name, '')


# Match a whole conversational leave-taking, not a word mentioned inside a
# task, quote or purchase. In particular «пока думаю» and «не хочу спать» stay.
_PAUSE_PART = (
    r'(?:пока|до\s+(?:свидания|завтра|встречи|скорого|связи)|спокойной\s+ночи|'
    r'(?:я\s+)?(?:(?:пойду|иду|пошел|пошла|собираюсь)\s+)?спать|'
    r'(?:я\s+)?(?:ухожу|прощаюсь)|мне\s+пора(?:\s+(?:идти|спать|уходить))?|'
    r'мне\s+(?:надо|нужно)\s+(?:идти|спать|уходить)|на\s+сегодня\s+все|'
    r'(?:давай(?:те)?\s+)?(?:поговорим|продолжим|спишемся)\s+(?:позже|потом|завтра)|'
    r'давай\s+(?:позже|потом|завтра|(?:сделаем\s+)?паузу)|'
    r'(?:хочу|нужна|сделаем|возьмем)\s+пауз[ау]|'
    r'(?:не\s+пиши|не\s+отвечай)(?:\s+(?:пока|сейчас|мне|больше))*|'
    r'(?:я\s+)?не\s+хочу\s+(?:сейчас\s+)?(?:общаться|разговаривать|переписываться)(?:\s+сейчас)?|'
    r'(?:я\s+)?хочу\s+побыть\s+(?:один|одна)|'
    r'bye|goodbye|good\s*night|talk\s+(?:later|tomorrow)|'
    r'(?:i\s+)?need\s+a\s+break|let[’\']?s\s+pause)'
)
_PAUSE_FILLER = (r'(?:ну|ладно|хорошо|ок(?:ей)?|спасибо|все|пожалуйста|'
                 r'(?:я\s+)?(?:сейчас\s+)?(?:устал[а]?|занят[а]?))')
_PAUSE = re.compile(
    rf'(?:{_PAUSE_FILLER}\s+)*{_PAUSE_PART}(?:\s+(?:{_PAUSE_PART}|{_PAUSE_FILLER}))*', re.I)
_SHORT_REACTION = re.compile(
    r'(?:ну\s+)?(?:не\s+знаю|ага|угу|норм(?:ально)?|да|нет|ок(?:ей)?|'
    r'ясно|понятно|хорошо|давай|делай|не\s+сейчас|yes|yeah|no|ok(?:ay)?|idk)', re.I)
_ACTION_CONTEXT = re.compile(
    r'\b(?:фото[а-яё]*|селфи|сним(?:ок|ки|ка)|оплат[а-яё]*|куп(?:ить|и|им|лю|ишь|ите)|покуп[а-яё]*|'
    r'персик[а-яё]*|стоит|стоимость|цен(?:а|ы|у|е|ой)|рубл[а-яё]*|спис(?:ать|ание|ания|ывай)|'
    r'photo|selfie|buy|pay|purchase|price)\b', re.I)
_TURN_HEADER = 'ХОД ДИАЛОГА (важнее необязательных крючков выше; не озвучивай инструкцию): '


def _turn_text(text: str) -> str:
    return re.sub(r'[\s,.!?;:…—–-]+', ' ', (text or '').lower().replace('ё', 'е')).strip()


def is_explicit_pause(user_text: str) -> bool:
    """Conservative, side-effect-free detection of a request to end/pause chat."""
    return bool(_PAUSE.fullmatch(_turn_text(user_text)))


def build_turn_guidance(history, user_text: str) -> str:
    """Guide one ordinary turn using only chronological, visible chat messages.

    Accept ORM-like messages or role/content dicts. No storage, randomness or
    generation; callers exclude scenes, guests, care and task intents.
    """
    text = _turn_text(user_text)
    if not text:
        return ''
    if is_explicit_pause(user_text):
        return _TURN_HEADER + (
            'ПАУЗА: пользователь явно прощается или просит остановиться. Коротко и тепло прими паузу. '
            'Без нового вопроса, истории, игры, интриги или предложения; без вины, обиды, '
            'долга и требования ответить или вернуться. Не обещай написать позже сама.')

    dialogue = [m for m in history if _field(m, 'role') in ('user', 'assistant')]
    assistant = [str(_field(m, 'content') or '') for m in dialogue if _field(m, 'role') == 'assistant']
    last = assistant[-1] if assistant else ''
    short = len(text) <= 80 and len(text.split()) <= 6 and not re.search(r'[?？]', user_text or '')
    reaction = bool(_SHORT_REACTION.fullmatch(text))
    # A short acceptance/refusal of an offer is not a request for small talk.
    # Do not manufacture consent, execute a purchase, or reinterpret its scope.
    if short and reaction and _ACTION_CONTEXT.search(last):
        return _TURN_HEADER + (
            'ОТВЕТ НА ПРЕДЛОЖЕНИЕ: сохрани смысл согласия, отказа или неопределённости '
            'относительно последнего предложения. Не подменяй его скукой или сменой темы. '
            'Это не новое разрешение на фото, списание или другую платную операцию; '
            'соблюдай существующее подтверждение действия.')
    if _ACTION_CONTEXT.search(user_text or ''):
        return ''

    notes = []
    if sum(_field(m, 'role') == 'user' for m in dialogue) < 3 and len(assistant) <= 3:
        notes.append(
            'ПЕРВЫЕ 1–3 ХОДА: сначала ответь на мысль пользователя, затем добавь одну небанальную '
            'деталь своего характера по текущей теме, а не перечень вкусов или обстановки. '
            'Не начинай анкету знакомства и не предлагай меню тем. Не выдумывай общую историю.')
    if short and not reaction and re.search(r'[?？]', last):
        notes.append(
            'КОРОТКИЙ ОТВЕТ НА ВОПРОС: прочитай его в контексте своего последнего вопроса, '
            'а не как признак скуки. Если это конкретный ответ, прими сообщённую деталь '
            'и отреагируй на неё; не спрашивай то же заново и не додумывай факты о пользователе.')
    elif reaction:
        notes.append(
            'КОРОТКАЯ РЕАКЦИЯ: сохрани смысл ответа, в том числе согласие, отказ или «не знаю». '
            'Легко продолжи текущую тему своей конкретной реакцией или мнением, без скачка '
            'на новую тему, допроса, меню и просьбы придумать разговор. Не считай краткость скукой '
            'и не добавляй обязательный вопрос.')
    if len(assistant) >= 2 and all(re.search(r'[?？]', line) for line in assistant[-2:]):
        notes.append(
            'ДВА ВОПРОСА ПОДРЯД: в обеих последних репликах ты уже спрашивала. '
            'Этот ход без очередного вопроса или опроса: дай свою реакцию или мнение по теме, '
            'не требуя ответа.')
    return _TURN_HEADER + '\n'.join(notes) if notes else ''


def build_repetition_guard(history, user_text: str, window: int = 8) -> str:
    """Tell the model which self-initiated motifs are becoming repetitive.

    The guard never blocks a theme the user explicitly brought up in the current turn.
    """
    user_text = user_text or ""
    recent_assistant = [_field(m, "content") or "" for m in history if _field(m, "role") == "assistant"][-window:]
    if not recent_assistant:
        return ""

    blocked: list[str] = []
    for name, pattern in THEMES.items():
        if pattern.search(user_text):
            continue
        hits = sum(1 for msg in recent_assistant if pattern.search(msg))
        threshold = 1 if name == "coffee/cafe" else 2
        if hits >= threshold:
            blocked.append(name)

    if not blocked:
        return (
            "РАЗНООБРАЗИЕ ДИАЛОГА: не используй бытовые вкусы героини как обязательную вставку. "
            "Если текущей теме не нужен бытовой комментарий, лучше вообще не добавляй его."
        )

    return (
        "АНТИ-ПОВТОР ТЕМ: в недавних репликах героиня уже использовала мотивы: " + ", ".join(blocked) + ". "
        "Не инициируй их снова в этой реплике и не притягивай к ним текущее состояние/локацию. "
        "Если пользователь сам явно поднял такую тему, это ограничение не действует. Выбери другую естественную деталь или вообще обойдись без бытового фона."
    )


# V3.63.11: the girls wrote only 😏 and 🙈 (the prompt's own examples plus the
# model copying its last messages). An emoji she used in her recent messages,
# or twice in one answer, is swapped for a fresh one of the same mood.
_EMOJI_GROUPS = (
    ('😏', '😉', '😈', '😜', '💋', '🔥', '😋'),
    ('🙈', '🙊', '🙉', '☺️', '😊', '🥺', '😳', '🤭'),
    ('🥰', '😘', '😍', '💕', '❤️', '🤍'),
    ('😌', '✨', '🌙'),
    ('😂', '😅', '🤣', '😆'),
    ('🙄', '😑', '😤', '😒'),
)
_EMOJI_GROUP_OF = {e: g for g in _EMOJI_GROUPS for e in g}
# V3.63.14: the monkeys were her tic (🙈 then 🙊 on the very next reply); one is
# fine now and then, any monkey after a monkey becomes another shy face.
_MONKEYS = frozenset('🙈🙊🙉')
_EMOJI_TOKEN = re.compile('|'.join(re.escape(e) for e in sorted(_EMOJI_GROUP_OF, key=len, reverse=True)))


def diversify_emoji(answer: str, recent_bot_texts, rng=None) -> str:
    """Swap emoji repeated from her last messages for another of the same mood."""
    import random
    rng = rng or random
    if not answer:
        return answer
    recent = {m.group(0) for t in recent_bot_texts or () for m in _EMOJI_TOKEN.finditer(t or '')}
    used: set[str] = set()

    monkey_seen = bool(recent & _MONKEYS)

    def swap(m):
        nonlocal monkey_seen
        e = m.group(0)
        repeat_monkey = e in _MONKEYS and monkey_seen
        if e in _MONKEYS:
            monkey_seen = True
        if e not in recent and e not in used and not repeat_monkey:
            used.add(e)
            return e
        options = [x for x in _EMOJI_GROUP_OF[e] if x not in recent and x not in used and x not in _MONKEYS]
        if not options:
            return e
        new = rng.choice(options)
        used.add(new)
        return new

    return _EMOJI_TOKEN.sub(swap, answer)


# V3.63.13: a girl in Telegram doesn't open every bubble with a capital letter
# and close it with a full stop — that tidy punctuation read as a bot. Only
# everyday opening words are lowercased, so names keep their capital.
_CASUAL_OPENERS = frozenset(
    'а ах ахах ага блин в вот да даже доброе ещё же знаешь и или как какой какая какие кстати ладно '
    'мм ммм может мой моя мне меня мы на наверное не нет ну о ого ой ох по погоди подожди понятно привет '
    'приветик прости просто раз сегодня серьёзно слушай смотри так там теперь тогда только ты тебе тебя '
    'у угу уже фу хаха хах хм хочешь честно что чего чё это эй я'.split()
)
_OPENER = re.compile(r'^([А-ЯЁ])([а-яё]*)')


def casual_punctuation(answer: str) -> str:
    if not answer or '```' in answer:
        return answer
    bubbles = []
    for bubble in answer.split('\n\n'):
        b = bubble.strip()
        m = _OPENER.match(b)
        if m and (m.group(1) + m.group(2)).lower() in _CASUAL_OPENERS:
            b = m.group(1).lower() + b[1:]
        if b.endswith('.') and not b.endswith('..'):
            b = b[:-1]
        # V3.63.14: nobody types an em dash on a phone keyboard; it was in every
        # reply and read as a machine. A comma reads the same in chat.
        b = re.sub(r'\s*,?\s+[—–]\s+', ', ', b)
        bubbles.append(b)
    return '\n\n'.join(bubbles)


# V3.63.15: the messages she writes first (proactive, life moments) are built
# without the dialogue guard, and she kept sending the same promise again
# («завтра утром пришлю тебе кое-что 🙈 не проси»). A sentence whose words
# mostly repeat one of her recent sentences is dropped.
_SENTENCE_SPLIT = re.compile(r'(?<=[.!?…])\s+|\n+')
_WORD = re.compile(r'[а-яёa-z0-9]+(?:-[а-яёa-z0-9]+)?')


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or '').lower().replace('ё', 'е')) if len(w) > 1}


def drop_repeated_lines(answer: str, recent_bot_texts, min_words: int = 4,
                        threshold: float = 0.75) -> str:
    """Remove sentences that mostly repeat her recent ones; '' when all repeat."""
    if not answer:
        return answer
    seen = [w for t in recent_bot_texts or () for s in _SENTENCE_SPLIT.split(t or '')
            if len(w := _words(s)) >= min_words]
    if not seen:
        return answer
    bubbles = []
    for bubble in answer.strip().split('\n\n'):
        kept = []
        for s in _SENTENCE_SPLIT.split(bubble):
            w = _words(s)
            if len(w) >= min_words and any(len(w & old) / len(w) >= threshold for old in seen):
                continue
            kept.append(s.strip())
        b = ' '.join(k for k in kept if k)
        if b:
            bubbles.append(b)
    return '\n\n'.join(bubbles)


def polish_first_message(text: str, recent_bot_texts) -> str:
    """Same chat polish as replies for a message she sends on her own."""
    text = drop_repeated_lines(text, recent_bot_texts)
    if not text:
        return ''
    return casual_punctuation(diversify_emoji(text, recent_bot_texts))


# V3.64.8: a message cut on the token cap («Надела сегодня тот») or one that
# came back as a stray English word («perspective,») must never be sent.
_SENTENCE_END = re.compile(r'[.!?…)।。！？]|[\U0001F300-\U0001FAFF☀-➿]')


def finish_or_drop(text: str, complete: bool = True, lang: str = 'ru') -> str:
    """Cut an unfinished message back to its last whole sentence; '' if none."""
    text = (text or '').strip()
    # V3.117.0: Bengali, Japanese, Spanish… — any letters count there
    _letters = {'en': r'[a-z]{3}', 'ru': r'[а-яё]{3}'}.get(lang, r'[^\W\d_]{2}')
    if not re.search(_letters, text, re.I):
        return ''
    if complete:
        return text
    ends = [m.end() for m in _SENTENCE_END.finditer(text)]
    if not ends:
        return ''
    cut = text[:ends[-1]].strip()
    return cut if len(cut) >= 12 else ''
