"""Dates feature: paid dates (Telegram Stars) gated by relationship level.
A successful date boosts the relationship and ends with a fresh photo set
from the date scene as the reward. Payment handling lives in main.py."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Date:
    id: str
    name: str
    emoji: str
    min_level: int
    cost: int          # Telegram Stars
    affection: float   # relationship delta applied on a successful date
    scene: str         # photo scene for the reward photo set
    text: str          # short narration of the date


DATES: tuple[Date, ...] = (
    Date('cafe', 'Кофейня', '☕', 1, 5, 1.0, 'cafe',
         'Мы сидим у окна, пьём латте и болтаем обо всём на свете. Она смеётся над твоими шутками и незаметно кладёт руку на твою.'),
    Date('park', 'Прогулка в парке', '🌳', 1, 5, 1.0, 'park',
         'Тёплый вечер, аллея, фонари. Вы идёте медленно, держась за руки, и время словно останавливается.'),
    Date('cinema', 'Кино', '🎬', 2, 7, 1.5, 'cinema',
         'Тёмный зал, последний ряд. Она кладёт голову тебе на плечо ещё до начала фильма.'),
    Date('embankment', 'Набережная', '🌇', 2, 7, 1.5, 'embankment',
         'Закат над водой, лёгкий ветер. Вы стоите у перил, и она то и дело смотрит на тебя, а не на вид.'),
    Date('restaurant', 'Ресторан', '🍷', 3, 10, 2.0, 'restaurant',
         'Свечи, тихая музыка, бокал вина. Она выглядит особенно красиво этим вечером — и знает это.'),
    Date('rooftop', 'Крыша', '🌃', 4, 12, 2.5, 'rooftop',
         'Огни города внизу, плед на двоих и тишина, в которой слышно только её дыхание рядом.'),
    Date('club', 'Клуб', '🪩', 5, 15, 3.0, 'club',
         'Громкая музыка, танцы до утра. Она танцует только с тобой — и всем вокруг это очевидно.'),
)


def get_available(level: int) -> list[Date]:
    return [date for date in DATES if date.min_level <= max(1, min(6, level))]


def get_locked(level: int) -> list[Date]:
    """Dates still closed for this level — shown with a lock in the menu."""
    return [date for date in DATES if date.min_level > max(1, min(6, level))]


def get(date_id: str) -> Date | None:
    for date in DATES:
        if date.id == date_id:
            return date
    return None
