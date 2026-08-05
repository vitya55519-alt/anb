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
FLIRTY = re.compile(r"\b(красивая|целу|обним|скучаю|нравишься|покажись|фото|плать|бель|флирт)\b", re.I)
BRAG = re.compile(r"\b(сделал|получилось|купил|выиграл|заработал|смог)\b", re.I)
META = re.compile(r"\b(ты настоящ|ты реальн|ты человек|ты бот|ты ии|ты ai|искусственн|виртуальн)\b", re.I)
TASK = re.compile(r"\b(напиши код|код на|python|питон|посчитай|объясни|переведи|составь|реши|калькулятор|скрипт)\b", re.I)

INTENTS = ("reaction", "opinion", "tease", "story", "question", "callback", "topic_shift")


def choose_behavior(text: str) -> Behavior:
    text = text or ""
    if META.search(text):
        return Behavior("meta", 2, "none", "честно и коротко; без лекции про ИИ и без слова «виртуалка»")
    if TASK.search(text):
        return Behavior("task", 8, "none", "сразу выполни задачу; характер Анны оставь лёгким фоном, не превращай ответ в продажу общения")
    if SERIOUS.search(text):
        return Behavior("support", 4, "low", "тепло и внимательно; без терапевтических клише и без шутки невпопад")
    if FLIRTY.search(text):
        return Behavior("flirt", random.choice((1, 2, 3)), "low", "игриво, уверенно и естественно; без графических сексуальных описаний")
    if BRAG.search(text):
        return Behavior("reaction", 2, "low", "живая реакция; можно немного подколоть, но не хвали автоматически")
    intent = random.choices(INTENTS, weights=(32, 20, 14, 10, 9, 10, 5), k=1)[0]
    return Behavior(intent, random.choice((1, 2, 2, 3)), "normal" if intent == "question" else "low", "как личное сообщение, без ассистентского тона")


def behavior_context(text: str) -> str:
    b = choose_behavior(text)
    return (
        f"ВНУТРЕННЕЕ НАМЕРЕНИЕ ЭТОЙ РЕПЛИКИ: {b.intent}. "
        f"Ориентир длины: до {b.max_sentences} коротких предложений, если пользователь не попросил подробный ответ или код. "
        f"Вопросы: {b.question_bias}; не задавай вопрос только ради продолжения разговора. "
        f"Подача: {b.tone_hint}. Не называй пользователю это намерение."
    )
