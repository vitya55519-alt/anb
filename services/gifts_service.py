"""Gifts feature: paid gifts (Telegram Stars) that boost the relationship.
Pure catalog — payment and relationship deltas are handled in main.py."""
from dataclasses import dataclass
from datetime import date, datetime, timezone


@dataclass(frozen=True)
class Gift:
    id: str
    name: str
    emoji: str
    cost: int          # Telegram Stars
    affection: float   # relationship delta applied on purchase
    reaction: str      # her reply after receiving the gift


GIFTS: tuple[Gift, ...] = (
    Gift('chocolate', 'Шоколад', '🍫', 3, 0.5,
         'Мм, шоколад 🍫 Спасибо! Оставлю тебе кусочек… может быть 😄'),
    Gift('flowers', 'Цветы', '💐', 5, 1.0,
         'Какие красивые цветы 💐 Сразу в вазу — и буду смотреть на них весь день. Спасибо, любимый ❤️'),
    Gift('teddy', 'Мишка', '🧸', 7, 1.5,
         'Ой, какой милый мишка 🧸 Теперь он спит со мной. Ревновать будешь? 😏'),
    Gift('perfume', 'Парфюм', '🌸', 10, 2.0,
         'Ты угадал с ароматом 🌸 Теперь пахну им только для тебя.'),
    Gift('jewelry', 'Украшение', '💍', 15, 3.0,
         'Это… мне? 😳 Такое красивое. Ты меня балуешь, и мне это нравится 💍'),
    Gift('lingerie_set', 'Комплект белья', '🖤', 20, 4.0,
         'Очень смелый подарок 🖤 Я примерю его для тебя. Скоро.'),
    Gift('yacht', 'Прогулка на яхте', '🛥', 50, 10.0,
         'Яхта?! 😍 Ты серьёзно?.. Уже представляю закат, море и только мы вдвоём 🛥❤️'),
)


def get_all() -> list[Gift]:
    return list(GIFTS)


def get(gift_id: str) -> Gift | None:
    for gift in GIFTS:
        if gift.id == gift_id:
            return gift
    return None


# One gift per day is featured at a discount — deterministic rotation by date
# so everyone sees the same offer and it creates a reason to check in daily.
DAILY_DISCOUNT = 0.30


def get_daily_featured(today: date | None = None) -> Gift:
    today = today or datetime.now(timezone.utc).date()
    return GIFTS[today.toordinal() % len(GIFTS)]


def is_featured(gift: Gift, today: date | None = None) -> bool:
    return gift.id == get_daily_featured(today).id


def effective_cost(gift: Gift, today: date | None = None) -> int:
    if is_featured(gift, today):
        return max(1, round(gift.cost * (1 - DAILY_DISCOUNT)))
    return gift.cost
