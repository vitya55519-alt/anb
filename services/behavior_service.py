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
CODE_TASK = re.compile(r"\b(напиши код|код на|python|питон|скрипт|калькулятор|програм(?:му|ма)|функци[юя]|бота на)\b", re.I)
UTILITY_TASK = re.compile(r"\b(посчитай|объясни|переведи|реши|составь)\b", re.I)
CODE_SPECIFIC = re.compile(
    r"(сразу|полностью|полный\s+код|готовый\s+код|без\s+вопросов|консольн\w*|\bcli\b|\bgui\b|\btkinter\b|\bpyqt\b|"
    r"\bflask\b|\bfastapi\b|\bdjango\b|командн\w*\s+строк\w*|интерфейс\w*|кнопк\w*|умнож\w*|"
    r"делен\w*|делить|файл\w*|класс\w*|функци\w*|\bapi\b|\bjson\b|\bsqlite\b|\bpostgres\w*\b|[+*/])",
    re.I,
)

INTENTS = ("reaction", "opinion", "tease", "story", "question", "callback", "topic_shift")


def _is_short_followup(text: str) -> bool:
    clean = (text or "").strip()
    return 0 < len(clean) <= 140 and len(clean.split()) <= 18


def choose_behavior(text: str, previous_user_text: str = "") -> Behavior:
    text = text or ""
    previous_user_text = previous_user_text or ""
    if META.search(text):
        return Behavior("meta", 2, "none", "честно и коротко; без лекции про ИИ и без слова «виртуалка»")

    if CODE_TASK.search(text):
        return Behavior(
            "task_character", 3, "low",
            "сохраняй реальные компетенции персонажа: Анна не программист и не должна внезапно писать код как эксперт; ответь естественно от её лица",
        )


    if UTILITY_TASK.search(text):
        return Behavior("task_execute", 10, "none", "выполни понятную задачу компетентно, сохраняя характер Анны только лёгким фоном")
    if SERIOUS.search(text):
        return Behavior("support", 4, "low", "тепло и внимательно; без терапевтических клише и без шутки невпопад")
    if FLIRTY.search(text):
        return Behavior("flirt", random.choice((1, 2, 3)), "low", "игриво, уверенно и естественно; без графических сексуальных описаний")
    if BRAG.search(text):
        return Behavior("reaction", 2, "low", "живая реакция; можно немного подколоть, но не хвали автоматически")
    intent = random.choices(INTENTS, weights=(32, 20, 14, 10, 9, 10, 5), k=1)[0]
    return Behavior(intent, random.choice((1, 2, 2, 3)), "normal" if intent == "question" else "low", "как личное сообщение, без ассистентского тона")


def behavior_context(text: str, previous_user_text: str = "") -> str:
    b = choose_behavior(text, previous_user_text)
    extra = ""
    if b.intent == "task_clarify":
        extra = (
            " ТЕХНИЧЕСКИЙ ЗАПРОС НЕДООПРЕДЕЛЁН: не печатай код, инструкцию или длинное решение в этой реплике. "
            "Сначала выясни одну реально влияющую на результат деталь (например, консольный вариант или GUI)."
        )
    elif b.intent == "task_execute":
        extra = (
            " ТЕХНИЧЕСКИЙ РЕЖИМ: полезность важна, но Анна не превращается в безличного ассистента. "
            "Не начинай с «Конечно», «Вот код» или длинной служебной преамбулы; одной короткой живой фразы достаточно."
        )
    return (
        f"ВНУТРЕННЕЕ НАМЕРЕНИЕ ЭТОЙ РЕПЛИКИ: {b.intent}. "
        f"Ориентир длины: до {b.max_sentences} коротких предложений, если пользователь не запросил уже конкретную подробную задачу. "
        f"Вопросы: {b.question_bias}; не задавай вопрос только ради продолжения разговора. "
        f"Подача: {b.tone_hint}. Не называй пользователю это намерение.{extra}"
    )
