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
from services.invite_funnel import GROUP_RULE, JOINT_PHOTO_RULE

logger = logging.getLogger(__name__)


def get_guest(telegram_id: int, character_id: str) -> str | None:
    try:
        with SessionLocal() as session:
            row = session.execute(
                select(ChatGuest.guest_id).where(
                    ChatGuest.user_id == int(telegram_id), ChatGuest.character_id == character_id)
            ).first()
        guest_id = row[0] if row else None
    except Exception:
        logger.exception('chat guest read failed user=%s', telegram_id)
        return None
    # V3.152.1: owner ТЗ (Задача 2) — в пару к героине чата встаёт только
    # официальная девушка «Персикового сада». Строка, оставшаяся от старой
    # пользовательской сборки, читается как «никого не звали»: иначе чужая
    # сборка продолжала бы попадать в duo-промпты и в совместные фото.
    if guest_id and not is_official_guest(guest_id):
        return None
    return guest_id


def is_official_guest(guest_id: str) -> bool:
    """Only a storefront girl of the garden can be invited as the second one.

    V3.152.1: the constructor personas (``custom_…`` ids) are excluded by id,
    before any card read — a user build is never an official heroine, whatever
    its card says."""
    if not guest_id:
        return False
    from services.custom_character_service import is_custom_character
    if is_custom_character(guest_id):
        return False
    try:
        from services.character_card_service import get_card
        card = get_card(guest_id)
    except Exception:
        return False
    return bool(card and card.status == 'active' and card.is_visible)


def set_guest(telegram_id: int, character_id: str, guest_id: str | None) -> None:
    # V3.152.1: the write path is gated the same way the read path is, so a
    # hand-crafted request cannot park a custom build in a chat either.
    if guest_id and not is_official_guest(guest_id):
        guest_id = None
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


def host_name(host_id: str) -> str:
    """What the host girl is called in this chat — cards and constructions both."""
    name = character_name(host_id)
    if name:
        return name
    try:
        from services.custom_character_service import is_custom_character, custom_character_params
        if is_custom_character(host_id):
            return custom_character_params(host_id)[1] or ''
    except Exception:
        pass
    return ''


def speakers(telegram_id: int, host_id: str) -> dict[str, str]:
    """V3.139.0: {name: character_id} of BOTH girls when this chat is a duo,
    {} when she writes alone. The chat model answers for both, each line with
    her name; every delivery layer reads this map to split the answer and to
    give each line her own voice. A constructor partner has no card of her own,
    so she is keyed by a synthetic id — voice_service picks a stable pooled
    voice from it, which is what keeps the two voices apart."""
    guest_id = get_guest(telegram_id, host_id)
    if guest_id:
        guest, host = character_name(guest_id), host_name(host_id)
        if not guest:
            return {}
        return {guest: guest_id, **({host: host_id} if host else {})}
    try:
        from services.custom_character_service import (
            is_custom_character, custom_character_params, duo_partner,
        )
        if is_custom_character(host_id):
            params, name = custom_character_params(host_id)
            partner = duo_partner(params)[0]
            if partner:
                duo_id = f'{host_id}-duo'
                return {name: host_id, partner: duo_id} if name else {partner: duo_id}
    except Exception:
        logger.exception('duo speakers read failed user=%s', telegram_id)
    return {}


def can_invite(telegram_id: int, host_id: str, guest_id: str) -> bool:
    """V3.152.1: owner ТЗ (Задача 2) — the guest pool is the official garden
    only. A storefront heroine, active and visible; the caller's own
    constructor build is no longer an option («пользовательские сборки должны
    быть полностью исключены из этого пула»)."""
    if not guest_id or guest_id == host_id:
        return False
    return is_official_guest(guest_id)


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


# Her status the way the HOST sees her friend (third person, short).
GUEST_STATUS = {
    'mar_single': '{g} свободна и ни с кем не встречается.',
    'mar_boyfriend': 'У {g} есть парень, его зовут {partner}; она переписывается с пользователем тайком от него.',
    'mar_married': '{g} замужем, мужа зовут {partner}; она переписывается с пользователем тайком от мужа и боится попасться.',
    'mar_divorced': '{g} в разводе и снова свободна.',
    'mar_open': 'У {g} свободные отношения: её партнёр, {partner}, в курсе и не против.',
    'mar_with_you': '{g} теперь вместе с пользователем, она его девушка.',
    'mar_wife': '{g} — жена пользователя, у них была свадьба.',
}


def guest_marital(telegram_id: int | None, guest_id: str) -> str:
    """The guest keeps the status the user picked in HER own chat (or her
    constructor default) — «Мэри замужем» stays true when she visits Анна."""
    status = ''
    if telegram_id:
        try:
            from services.webapp_service import _batch_marital
            status = _batch_marital(telegram_id, [guest_id]).get(guest_id, '')
        except Exception:
            status = ''
    if not status:
        try:
            from services.custom_character_service import is_custom_character
            from services.webapp_service import _default_marital
            status = _default_marital(guest_id, is_custom_character(guest_id))
        except Exception:
            status = ''
    return status or 'mar_single'


def guest_status_line(telegram_id: int | None, guest_id: str, name: str) -> str:
    status = guest_marital(telegram_id, guest_id)
    text = GUEST_STATUS.get(status, '')
    if '{partner}' in text:
        try:
            from services.custom_character_service import relationship_line
            import re
            partner = re.search(r'зовут (\w+)', relationship_line(status, guest_id) or '')
            text = text.replace('{partner}', partner.group(1) if partner else 'он')
        except Exception:
            text = text.replace('{partner}', 'он')
    return text.replace('{g}', name)


def guest_prompt(host_name: str, guest_id: str, telegram_id: int | None = None) -> str:
    name = character_name(guest_id)
    if not name:
        return ''
    host = host_name or 'ты'
    status = guest_status_line(telegram_id, guest_id, name)
    return (
        f'В ЧАТ ЗАШЛА {name} — пользователь сам позвал её в вашу переписку. Кто она: '
        f'{guest_description(guest_id) or "взрослая девушка со своим характером"}\n'
        + (f'Её семейное положение (так же, как в её собственном чате): {status} Не путай её положение со своим.\n' if status else '')
        + f'Теперь вас в чате двое: ты ({host}) и {name}. Ты пишешь реплики за обеих. Каждая реплика '
        f'с новой строки и начинается с имени, например «{host}: …» и «{name}: …». Обычно говорят обе, '
        f'у каждой свой характер, манера и отношение к нему; они могут подкалывать друг друга, '
        f'ревновать или объединяться против него. Не сливай их в одну и не забывай про вторую. '
        f'Обе — взрослые женщины. Кроме имени в начале строки — ничего оформлять не надо: никаких '
        f'действий в *звёздочках* и без ремарок в скобках, только то, что они набрали бы на телефоне.\n'
        + GROUP_RULE + '\n' + JOINT_PHOTO_RULE
    )
