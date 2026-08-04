from __future__ import annotations
import random, re
from dataclasses import dataclass

@dataclass(frozen=True)
class Behavior:
    intent: str
    max_sentences: int
    question_bias: str
    tone_hint: str

SERIOUS = re.compile(r"\b(плохо|устал|устала|груст|тяжел|боюсь|страшно|проблем|ссор|болит|не могу)\b", re.I)
FLIRTY = re.compile(r"\b(красивая|секс|целу|обним|скучаю|нравишься|покажись|фото|плать|бель)\b", re.I)
BRAG = re.compile(r"\b(сделал|получилось|купил|выиграл|заработал|смог)\b", re.I)

INTENTS = ("reaction", "opinion", "tease", "story", "question", "callback", "topic_shift")

def choose_behavior(text: str) -> Behavior:
    text = text or ""
    if SERIOUS.search(text):
        return Behavior("support", 4, "low", "тепло, внимательно, без шутки невпопад")
    if FLIRTY.search(text):
        return Behavior("flirt", random.choice((1,2,3)), "low", "игриво и уверенно, без графической сексуальности")
    if BRAG.search(text):
        return Behavior("reaction", 2, "low", "искренняя живая реакция, можно слегка подколоть")
    intent = random.choices(INTENTS, weights=(30,18,15,10,12,10,5), k=1)[0]
    return Behavior(intent, random.choice((1,2,2,3,4)), "normal" if intent == "question" else "low", "естественно, как в личном мессенджере")

def behavior_context(text: str) -> str:
    b = choose_behavior(text)
    return (
        f"ВНУТРЕННЕЕ НАМЕРЕНИЕ ЭТОЙ РЕПЛИКИ: {b.intent}. "
        f"Ориентир длины: не больше {b.max_sentences} коротких предложений, если контекст не требует большего. "
        f"Вопросы: {b.question_bias}; не задавай вопрос только ради продолжения разговора. "
        f"Подача: {b.tone_hint}. Не называй пользователю это намерение."
    )
