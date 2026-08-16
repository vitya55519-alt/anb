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
