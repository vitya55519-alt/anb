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
    ('🙈', '☺️', '😊', '🥺', '😳', '🤭'),
    ('🥰', '😘', '😍', '💕', '❤️', '🤍'),
    ('😌', '✨', '🌙'),
    ('😂', '😅', '🤣', '😆'),
    ('🙄', '😑', '😤', '😒'),
)
_EMOJI_GROUP_OF = {e: g for g in _EMOJI_GROUPS for e in g}
_EMOJI_TOKEN = re.compile('|'.join(re.escape(e) for e in sorted(_EMOJI_GROUP_OF, key=len, reverse=True)))


def diversify_emoji(answer: str, recent_bot_texts, rng=None) -> str:
    """Swap emoji repeated from her last messages for another of the same mood."""
    import random
    rng = rng or random
    if not answer:
        return answer
    recent = {m.group(0) for t in recent_bot_texts or () for m in _EMOJI_TOKEN.finditer(t or '')}
    used: set[str] = set()

    def swap(m):
        e = m.group(0)
        if e not in recent and e not in used:
            used.add(e)
            return e
        options = [x for x in _EMOJI_GROUP_OF[e] if x not in recent and x not in used]
        if not options:
            return e
        new = rng.choice(options)
        used.add(new)
        return new

    return _EMOJI_TOKEN.sub(swap, answer)
