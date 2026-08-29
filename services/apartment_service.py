"""Apartment feature: rooms unlocked by relationship level, each with small
interactive actions. Pure catalog service — no DB of its own; relationship
deltas are applied by the caller through the shared relationship engine."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Room:
    id: str
    name: str
    emoji: str
    description: str
    min_level: int
    actions: tuple[tuple[str, str], ...]  # (button title, action_id)


# The action catalogue is intentionally warm and playful; every action gives a
# small relationship/intimacy bump so the apartment feels alive, not a menu.
ROOM_ACTIONS: dict[str, tuple[str, float, float]] = {
    # action_id: (her reply, relationship delta, intimacy delta)
    'talk': ('Устраиваюсь рядом 😊 Рассказывай, как прошёл день — я никуда не тороплюсь.', 0.6, 0.2),
    'movie': ('О, фильм! Я выберу что-то романтичное, а ты обнимешь меня под пледом 🎬', 0.5, 0.4),
    'coffee': ('Сейчас сварю нам кофе ☕ Садись, я принесу прямо к тебе.', 0.4, 0.1),
    'dinner': ('Готовлю для тебя ужин 🍝 Ты мой любимый дегустатор, знаешь ли.', 0.6, 0.2),
    'relax': ('Ложись рядом 😌 Полежим просто так, без телефонов и спешки.', 0.4, 0.5),
    'intimate': ('Иди ко мне… дверь уже закрыта 💋', 0.5, 1.0),
    'shower': ('Подожди меня пять минут 🚿 Или… не жди 😉', 0.3, 0.7),
    'bath': ('Набираю ванну с пеной 🛁 Составишь компанию?', 0.3, 0.6),
}

ROOMS: tuple[Room, ...] = (
    Room(
        id='living', name='Гостиная', emoji='🛋',
        description='Уютная гостиная с мягким диваном и большим телевизором. Здесь мы болтаем и смотрим фильмы.',
        min_level=1,
        actions=(('💬 Общаться', 'talk'), ('📺 Фильм', 'movie')),
    ),
    Room(
        id='kitchen', name='Кухня', emoji='🍳',
        description='Светлая кухня. Пахнет кофе и свежей выпечкой — я как раз что-то готовлю.',
        min_level=2,
        actions=(('☕ Кофе', 'coffee'), ('🍝 Ужин', 'dinner')),
    ),
    Room(
        id='bedroom', name='Спальня', emoji='🛏',
        description='Моя спальня: мягкий свет, шёлковое бельё и очень удобная кровать.',
        min_level=3,
        actions=(('😌 Отдых', 'relax'), ('💋 Интим', 'intimate')),
    ),
    Room(
        id='bathroom', name='Ванная', emoji='🛁',
        description='Тёплый пар, зеркало в мягком свете и большая ванна.',
        min_level=4,
        actions=(('🚿 Душ', 'shower'), ('🛁 Ванна', 'bath')),
    ),
    # V3.21.0: premium plateau rooms (levels 7-8).
    Room(
        id='candles', name='Комната со свечами', emoji='🕯',
        description='Полумрак, десятки свечей и плед на полу. Сюда мы приходим, когда хочется только друг друга.',
        min_level=7,
        actions=(('💋 Интим', 'intimate'), ('😌 Отдых', 'relax')),
    ),
)


def get_available_rooms(level: int) -> list[Room]:
    return [room for room in ROOMS if room.min_level <= max(1, min(8, level))]


def get_locked_rooms(level: int) -> list[Room]:
    """Rooms still closed for this level — shown with a lock in the menu."""
    return [room for room in ROOMS if room.min_level > max(1, min(8, level))]


def get_room(room_id: str) -> Room | None:
    for room in ROOMS:
        if room.id == room_id:
            return room
    return None


def room_action_reply(room_id: str, action_id: str) -> tuple[str, float, float] | None:
    """Her reply + (relationship, intimacy) deltas for an apartment action."""
    room = get_room(room_id)
    if not room or action_id not in dict(room.actions).values():
        return None
    return ROOM_ACTIONS.get(action_id)
