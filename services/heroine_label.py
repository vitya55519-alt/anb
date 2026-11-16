"""V3.167.1 (владелец, Q3): «подпись 💬 [Имя]: нужна ДЛЯ ВСЕХ сообщений
(и текст, и фото, и подарки, и кружки)… кроме дефолтной Анны».

У бота одна ветка на всех: в Mini App у каждой героини свой диалог, а push,
уровневый кадр, подарок и кружок приходят в один и тот же чат Telegram. Без
метки он не видит, кто ему написал — и отвечает не той. Дефолтная героиня
(CHARACTER_ID, сейчас это Анна) не подписывается: её чат и есть её чат, а
лишний префикс ломает теги, кнопки и уже подписанные строки.
"""
from __future__ import annotations

from config import CHARACTER_ID

PREFIX = '💬 '


def name_of(character_id: str) -> str:
    """Имя для метки: карточка, а если её нет — конструктор."""
    if not character_id:
        return ''
    try:
        from services.chat_guest_service import host_name
        return (host_name(character_id) or '').strip()
    except Exception:
        return ''


def label(character_id: str) -> str:
    if not character_id or character_id == CHARACTER_ID:
        return ''
    name = name_of(character_id)
    return f'{PREFIX}{name}: ' if name else ''


def stamp(text: str, character_id: str) -> str:
    """Метка в начале её строки — текста или подписи к кадру. Пустой текст не
    подписываем, уже подписанный не подписываем дважды."""
    if not text:
        return text
    tag = label(character_id)
    if not tag or text.startswith(tag):
        return text
    return tag + text
