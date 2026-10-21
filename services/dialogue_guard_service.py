from __future__ import annotations
import re

# Motifs Anna may naturally have, but must not recycle as filler every few messages.
THEMES = {
    "coffee/cafe": re.compile(r"\b(кофе|кафе|латте|капучино|эспрессо|coffee|cafe|latte|cappuccino|espresso)\b", re.I),
    "walk/city": re.compile(r"\b(прогул|гуля|парк|набереж|вышла пройти|город.*вечер|walk|park|embankment)\b", re.I),
    "home/cozy": re.compile(r"\b(дома|домашн|уют|диван|плед|home|cozy|sofa)\b", re.I),
    "gym": re.compile(r"\b(зал|трениров|спорт|gym|workout)\b", re.I),
    "food/restaurant": re.compile(r"\b(ресторан|ужин|поесть|еда|restaurant|dinner|food)\b", re.I),
    "outfit/fashion": re.compile(r"\b(образ|одежд|плать|fashion|outfit|dress)\b", re.I),
}


def build_repetition_guard(history, user_text: str, window: int = 8) -> str:
    """Tell the model which self-initiated motifs are becoming repetitive.

    The guard never blocks a theme the user explicitly brought up in the current turn.
    """
    user_text = user_text or ""
    recent_assistant = [getattr(m, "content", "") or "" for m in history if getattr(m, "role", "") == "assistant"][-window:]
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
            "РАЗНООБРАЗИЕ ДИАЛОГА: не используй бытовые вкусы Анны как обязательную вставку. "
            "Если текущей теме не нужен бытовой комментарий, лучше вообще не добавляй его."
        )

    return (
        "АНТИ-ПОВТОР ТЕМ: в недавних репликах Анна уже использовала мотивы: " + ", ".join(blocked) + ". "
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
_SENTENCE_END = re.compile(r'[.!?…)]|[\U0001F300-\U0001FAFF☀-➿]')


def finish_or_drop(text: str, complete: bool = True, lang: str = 'ru') -> str:
    """Cut an unfinished message back to its last whole sentence; '' if none."""
    text = (text or '').strip()
    if not re.search(r'[a-z]{3}' if lang == 'en' else r'[а-яё]{3}', text, re.I):
        return ''
    if complete:
        return text
    ends = [m.end() for m in _SENTENCE_END.finditer(text)]
    if not ends:
        return ''
    cut = text[:ends[-1]].strip()
    return cut if len(cut) >= 12 else ''
