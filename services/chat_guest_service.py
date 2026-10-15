"""V3.61.2: «позвать в чат» — invite a second girl into one girl's chat.

The guest is stored per (user, host chat). While she is there the host's chat
model writes both voices, each line starting with the speaker's name (the same
«Имя: …» format the constructor duo uses, so the app bolds the names).
Photos stay of the host only: the guest has no reference images in that shoot.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from models.app_models import ChatGuest
from services.db import SessionLocal

logger = logging.getLogger(__name__)


def get_guest(telegram_id: int, character_id: str) -> str | None:
    try:
        with SessionLocal() as session:
            row = session.execute(
                select(ChatGuest.guest_id).where(
                    ChatGuest.user_id == int(telegram_id), ChatGuest.character_id == character_id)
            ).first()
        return row[0] if row else None
    except Exception:
        logger.exception('chat guest read failed user=%s', telegram_id)
        return None


def set_guest(telegram_id: int, character_id: str, guest_id: str | None) -> None:
    with SessionLocal() as session:
        row = session.get(ChatGuest, (int(telegram_id), character_id))
        if guest_id:
            if row:
                row.guest_id = guest_id
            else:
                session.add(ChatGuest(user_id=int(telegram_id), character_id=character_id, guest_id=guest_id))
        elif row:
            session.delete(row)
        session.commit()


def character_name(character_id: str) -> str:
    try:
        from services.character_card_service import get_card
        card = get_card(character_id)
        if card and card.display_name:
            return card.display_name
    except Exception:
        pass
    return ''


def can_invite(telegram_id: int, host_id: str, guest_id: str) -> bool:
    """Any active storefront girl, or the caller's own private creation."""
    if not guest_id or guest_id == host_id:
        return False
    try:
        from services.character_card_service import get_card
        card = get_card(guest_id)
    except Exception:
        return False
    if not card or card.status != 'active':
        return False
    if card.is_visible:
        return True
    try:
        from services.custom_character_service import get_all_custom_characters
        return guest_id in {c.character_id for c in get_all_custom_characters(telegram_id)}
    except Exception:
        return False


def host_has_duo(character_id: str) -> bool:
    """A constructor duo already has two girls — no room for a guest."""
    try:
        from services.custom_character_service import is_custom_character, custom_character_params, duo_partner
        if not is_custom_character(character_id):
            return False
        return bool(duo_partner(custom_character_params(character_id)[0])[0])
    except Exception:
        return False


def guest_description(guest_id: str) -> str:
    """A short who-she-is line for the host's prompt."""
    try:
        from services.custom_character_service import (
            is_custom_character, custom_character_params, template_card_bio, get_custom_character_by_id,
        )
        if is_custom_character(guest_id):
            params, name = custom_character_params(guest_id)
            row = get_custom_character_by_id(guest_id)
            bits = [template_card_bio(params, name)]
            for extra in ((row.personality or '') if row else '', (row.backstory or '') if row else ''):
                if extra.strip():
                    bits.append(extra.strip()[:300])
            return ' '.join(bits)
    except Exception:
        logger.exception('custom guest description failed id=%s', guest_id)
    bits = []
    try:
        from services.character_card_service import get_card
        card = get_card(guest_id)
        if card:
            bits.append(f'{card.display_name}, {card.age} лет. {card.short_bio or ""}'.strip())
    except Exception:
        pass
    try:
        from services.character_service import get_character
        data = get_character(guest_id)
        if data.get('id') == guest_id:
            core = (data.get('personality') or {}).get('core') or []
            if core:
                bits.append('Характер: ' + ', '.join(core[:7]) + '.')
    except Exception:
        pass
    return ' '.join(bits)


def guest_prompt(host_name: str, guest_id: str) -> str:
    name = character_name(guest_id)
    if not name:
        return ''
    host = host_name or 'ты'
    return (
        f'В ЧАТ ЗАШЛА {name} — пользователь сам позвал её в вашу переписку. Кто она: '
        f'{guest_description(guest_id) or "взрослая девушка со своим характером"}\n'
        f'Теперь вас в чате двое: ты ({host}) и {name}. Ты пишешь реплики за обеих. Каждая реплика '
        f'с новой строки и начинается с имени, например «{host}: …» и «{name}: …». Обычно говорят обе, '
        f'у каждой свой характер, манера и отношение к нему; они могут подкалывать друг друга, '
        f'ревновать или объединяться против него. Не сливай их в одну и не забывай про вторую. '
        f'Обе — взрослые женщины.'
    )
