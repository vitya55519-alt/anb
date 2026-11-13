"""V3.154.0: owner ТЗ (Фогель, Модуль 2) — «Перебивки» (QTE).

Внезапное внешнее событие посреди живого диалога: в замке поворачивается ключ,
на тумбочке звонит муж по видеосвязи, по лестнице идёт отец. Под карточкой
события три кнопки, и выбрать надо быстро — это адреналин, а не анкета. Тап
уходит в диалог как его действие с пометкой ``[EVENT ACTIVE]``, и она отыгрывает
страх спалиться, не выходя из сцены.

Событие привязано к её семейному положению (или к роли из конструктора): у
занятой — муж/парень, у мачехи — отец, у свободной — свет и курьер. Частота —
раз в ``INTERRUPT_EVERY_MIN..MAX`` его сообщений и не чаще
``INTERRUPT_MAX_PER_DAY`` раз в сутки на пару; до ``INTERRUPT_MIN_LEVEL`` она
вовсе не «секретная», и событие выглядело бы спамом от скрипта. Третий, самый
смелый вариант — Premium или за персики.

Счётчик живёт в DialogStore('interrupts'): схема не меняется, состояние пары
переживает рестарт. Сама карточка — только id события в памяти на минуту: текст
рисуется при доставке на языке пользователя, и никуда, кроме как в его чат, не
уезжает.
"""
from __future__ import annotations

import datetime as dt
import logging
import random
import time
from dataclasses import dataclass

from config import (INTERRUPTS_ENABLED, INTERRUPT_EVERY_MAX, INTERRUPT_EVERY_MIN,
                    INTERRUPT_MAX_PER_DAY, INTERRUPT_MIN_LEVEL, INTERRUPT_PEACH_COST)
from services import dialog_store

logger = logging.getLogger(__name__)

_state = dialog_store.DialogStore('interrupts')

# (telegram_id, character_id) -> {'id': event id, 'at': monotonic}
# Only the answer that was just generated carries it: the bot and the Mini App
# read the card once, right after chat_service.reply() returns.
_pending: dict[tuple[int, str], dict] = {}
_PENDING_TTL_SECONDS = 900.0

PAID_CHOICE = 2  # the third button is the bold one the ТЗ prices


def _en(lang: str) -> bool:
    """Anything but Russian takes the English event text — the same rule the
    wardrobe and the gift shop follow for their scene notes."""
    return str(lang or '').split('-')[0].lower() != 'ru'


@dataclass(frozen=True)
class Choice:
    ru: str          # button label he taps
    en: str
    act_ru: str      # his action, plain first person — no asterisk RP
    act_en: str
    paid: bool = False


@dataclass(frozen=True)
class Interrupt:
    id: str
    emoji: str
    ru: str          # {partner} is filled at render time
    en: str
    choices: tuple[Choice, ...]


def _choice(ru, en, act_ru, act_en, paid=False):
    return Choice(ru=ru, en=en, act_ru=act_ru, act_en=act_en, paid=paid)


# ── пул событий по её положению ────────────────────────────────────────────

TAKEN_EVENTS = (
    Interrupt(
        'key', '🚨',
        'ВНЕЗАПНО: в дверном замке поворачивается ключ — {partner} вернулся раньше времени!',
        'SUDDENLY: a key turns in the door lock — {partner} is home early!',
        (
            _choice('😈 Зажать ей рот рукой и продолжать в тишине',
                    '😈 Cover her mouth and keep going in silence',
                    'зажимаю ей рот рукой и продолжаю в тишине, не издавая ни звука',
                    'I cover her mouth with my hand and keep going without a sound'),
            _choice('🤫 Затолкать её в шкаф и замереть',
                    '🤫 Push her into the closet and freeze',
                    'толкаю её в шкаф, захлопываю дверцу и замираю рядом',
                    'I push her into the closet, shut the door and freeze next to it'),
            _choice('🎭 Заставить её ответить, не прекращая ласк',
                    '🎭 Make her answer him without stopping',
                    'шепчу ей: открой и ответь спокойно, а сама не останавливайся',
                    'I whisper: answer him calmly, and don\'t you stop', paid=True),
        )),
    Interrupt(
        'call', '📱',
        'ВНЕЗАПНО: на тумбочке разрывается её телефон — видеозвонок, {partner}!',
        'SUDDENLY: her phone shakes on the nightstand — a video call, {partner}!',
        (
            _choice('🤫 Сбросить и швырнуть телефон под подушку',
                    '🤫 Reject it and throw the phone under the pillow',
                    'сбрасываю звонок и сую её телефон под подушку',
                    'I reject the call and shove her phone under the pillow'),
            _choice('😈 Оставить звонок и прижать её к себе',
                    '😈 Leave it ringing and pull her close',
                    'не сбрасываю, беру её телефон и прижимаю её к себе, показывая только своё лицо',
                    'I don\'t reject it — I take her phone and pull her against me, showing only my face'),
            _choice('🎭 Заставить её ответить мужу, не останавливаясь',
                    '🎭 Make her answer him without stopping',
                    'шепчу: ответь ему, а я не останавливаюсь',
                    'I whisper: answer him — and I don\'t stop', paid=True),
        )),
)

STEPMOM_EVENTS = (
    Interrupt(
        'stairs', '🚨',
        'ВНЕЗАПНО: по лестнице идут тяжёлые шаги — отец поднимается прямо к вашей комнате!',
        'SUDDENLY: heavy steps on the stairs — your father is coming straight to your room!',
        (
            _choice('🤫 Затащить её под одеяло и замереть',
                    '🤫 Pull her under the blanket and freeze',
                    'тяну её под одеяло, накрываю с головой и замираю',
                    'I pull her under the blanket, cover her head and freeze'),
            _choice('😈 Продолжать в тишине, прижав её к себе',
                    '😈 Keep going in silence, holding her close',
                    'прижимаю её к себе и продолжаю в полной тишине, только дыхание',
                    'I hold her close and keep going in total silence, only breathing'),
            _choice('🎭 Открыть дверь и продолжать ласки',
                    '🎭 Open the door and keep going',
                    'шепчу: открой ему и будь совершенно спокойна, а я продолжаю',
                    'I whisper: open the door and stay perfectly calm — and I keep going', paid=True),
        )),
)

FREE_EVENTS = (
    Interrupt(
        'lights', '⚡',
        'ВНЕЗАПНО: в доме гаснет свет — пробки, и в темноте слышно только её дыхание',
        'SUDDENLY: the lights die — a blackout, and in the dark only her breathing is audible',
        (
            _choice('🤫 Остановиться и ждать в темноте',
                    '🤫 Stop and wait in the dark',
                    'замираю в темноте и слушаю, как она дышит рядом',
                    'I freeze in the dark and listen to her breathing next to me'),
            _choice('😈 Продолжать на ощупь',
                    '😈 Keep going by touch',
                    'продолжаю на ощупь, в темноте она жмётся сильнее',
                    'I keep going by touch; in the dark she presses closer'),
            _choice('🎭 Найти свечи и продолжить как ни в чём не бывало',
                    '🎭 Find candles and carry on like nothing happened',
                    'нахожу свечи, зажигаю и продолжаю, как будто так и надо',
                    'I find candles, light them and carry on as if it was planned', paid=True),
        )),
    Interrupt(
        'courier', '📦',
        'ВНЕЗАПНО: курьер трезвонит в дверь в самый разгар момента, и она в одной футболке',
        'SUDDENLY: the courier rings the bell right in the middle of it, and she is in nothing but a t-shirt',
        (
            _choice('🤫 Спрятать её в ванной и открыть самому',
                    '🤫 Hide her in the bathroom and answer myself',
                    'отправляю её в ванную, поворачиваю замок и иду открывать в джинсах',
                    'I send her to the bathroom, lock it and go answer in my jeans'),
            _choice('😈 Открыть дверь, не останавливаясь',
                    '😈 Answer the door without stopping',
                    'открываю дверь прямо с ней на руках, курьер отводит глаза',
                    'I answer the door with her still in my arms; the courier looks away'),
            _choice('🎭 Позвать её подписать накладную',
                    '🎭 Call her to sign for the parcel',
                    'зову её подписать накладную и держу её за талию, пока курьер смотрит в пол',
                    'I call her to sign for it and keep my hand on her waist while the courier stares at the floor', paid=True),
        )),
)

POOLS = {'taken': TAKEN_EVENTS, 'stepmom': STEPMOM_EVENTS, 'free': FREE_EVENTS}
_BY_ID = {e.id: e for pool in POOLS.values() for e in pool}

# ── её положение: кто может «зайти» ────────────────────────────────────────

TAKEN = ('mar_married', 'mar_boyfriend', 'mar_open')
FREE = ('mar_single', 'mar_divorced')
# «С тобой» и «жена» — ревности уже нет, ловить некого: событие сломало бы историю.
SILENT = ('mar_with_you', 'mar_wife')


def status_group(telegram_id: int, character_id: str) -> str:
    """'stepmom' | 'taken' | 'free' | '' — whose door can open at any second."""
    try:
        from sqlalchemy import select
        from models.relationship_models import UserCharacterRelationship
        from services.db import SessionLocal
        status = None
        with SessionLocal() as s:
            row = s.execute(
                select(UserCharacterRelationship.marital_status)
                .where(UserCharacterRelationship.user_id == int(telegram_id),
                       UserCharacterRelationship.character_id == str(character_id))
            ).scalar_one_or_none()
            status = row
        if status == 'mar_married':
            # the constructor's stepmother is married to his father — that is the event
            from services.custom_character_service import is_custom_character, custom_character_params
            if is_custom_character(character_id):
                params, _raw = custom_character_params(character_id)
                if str(params.get('scenario') or '') == 'scn_stepmom':
                    return 'stepmom'
        if status in SILENT:
            return ''
        if status in TAKEN:
            return 'taken'
        if status in FREE:
            return 'free'
        # nothing picked yet: a custom girl carries the constructor's choice,
        # and a built-in one without a status is treated as free
        try:
            from services.custom_character_service import is_custom_character, custom_character_params
            if is_custom_character(character_id):
                params, _raw = custom_character_params(character_id)
                if str(params.get('scenario') or '') == 'scn_stepmom':
                    return 'stepmom'
                status = str(params.get('marital') or '') or None
                if status in SILENT:
                    return ''
                if status in TAKEN:
                    return 'taken'
        except Exception:
            pass
        return 'free'
    except Exception:
        logger.warning('interrupt status lookup failed user=%s', telegram_id, exc_info=True)
        return ''


def partner_name(character_id: str) -> str:
    try:
        from services.marital_arcs import partner_name as _pn
        return _pn(character_id)
    except Exception:
        return 'муж'


# ── счётчик: раз в 10–15 сообщений, не чаще раза в сутки ───────────────────

def _load(telegram_id: int) -> dict:
    try:
        return dict(_state.get(int(telegram_id)) or {})
    except Exception:
        return {}


def _save(telegram_id: int, data: dict) -> None:
    try:
        _state[int(telegram_id)] = data
    except Exception:
        logger.warning('interrupt state save failed user=%s', telegram_id, exc_info=True)


def _pair(telegram_id: int, character_id: str) -> dict:
    item = dict(_load(telegram_id).get(character_id) or {})
    item.setdefault('left', random.randint(INTERRUPT_EVERY_MIN, INTERRUPT_EVERY_MAX))
    return item


def _put(telegram_id: int, character_id: str, item: dict) -> None:
    data = _load(telegram_id)
    data[character_id] = item
    _save(telegram_id, data)


def _today() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d')


def note_turn(telegram_id: int, character_id: str, level: int) -> str | None:
    """One live reply of hers is done. Returns the event id when this answer
    must carry a перебивка — the delivery layer renders the card itself."""
    if not INTERRUPTS_ENABLED or INTERRUPT_MAX_PER_DAY <= 0:
        return None
    if int(level or 0) < INTERRUPT_MIN_LEVEL:
        return None
    group = status_group(telegram_id, character_id)
    pool = POOLS.get(group)
    if not pool:
        return None
    item = _pair(telegram_id, character_id)
    day = _today()
    if item.get('day') != day:
        item['day'] = day
        item['used'] = 0
    left = int(item.get('left') or 1) - 1
    if left > 0:
        item['left'] = left
        _put(telegram_id, character_id, item)
        return None
    if int(item.get('used') or 0) >= INTERRUPT_MAX_PER_DAY:
        # today is spent: re-roll the wait so tomorrow does not fire on his first line
        item['left'] = random.randint(INTERRUPT_EVERY_MIN, INTERRUPT_EVERY_MAX)
        _put(telegram_id, character_id, item)
        return None
    event = random.choice(pool)
    item['left'] = random.randint(INTERRUPT_EVERY_MIN, INTERRUPT_EVERY_MAX)
    item['used'] = int(item.get('used') or 0) + 1
    item['last'] = event.id
    item['picked'] = False
    _put(telegram_id, character_id, item)
    _pending[(int(telegram_id), str(character_id))] = {'id': event.id, 'at': time.monotonic()}
    return event.id


def take_pending(telegram_id: int, character_id: str) -> str:
    """Read the card once — the bot and the app must not both draw it."""
    entry = _pending.pop((int(telegram_id), str(character_id)), None)
    if not entry:
        return ''
    if time.monotonic() - float(entry.get('at') or 0) > _PENDING_TTL_SECONDS:
        return ''
    return str(entry.get('id') or '')


def can_pick(telegram_id: int, character_id: str, event_id: str) -> bool:
    """Only the newest event of a pair is still answerable: a card he left on
    screen must not be paid for a second time after a newer one came."""
    item = dict(_load(telegram_id).get(str(character_id)) or {})
    if not item.get('last'):
        # the counter store was reset (or the card predates it) — let him answer
        return True
    return str(item.get('last')) == str(event_id) and not item.get('picked')


def mark_resolved(telegram_id: int, character_id: str, event_id: str) -> None:
    item = _pair(telegram_id, character_id)
    item['last'] = str(event_id)
    item['picked'] = True
    _put(telegram_id, character_id, item)


def get(event_id: str) -> Interrupt | None:
    return _BY_ID.get(str(event_id or ''))


def card(telegram_id: int, character_id: str, event_id: str, lang: str = 'ru') -> dict:
    """What he sees: the event line and the three answers, priced on the bold one."""
    event = get(event_id)
    if not event:
        return {}
    en = _en(lang)
    who = partner_name(character_id)
    text = (event.en if en else event.ru).format(partner=who)
    choices = [{'n': i,
                'label': (c.en if en else c.ru),
                'paid': bool(c.paid),
                'price': INTERRUPT_PEACH_COST if c.paid else 0}
               for i, c in enumerate(event.choices)]
    return {'id': event.id, 'emoji': event.emoji, 'text': text, 'choices': choices,
            'cost': INTERRUPT_PEACH_COST}


def choice_of(event_id: str, n: int) -> Choice | None:
    event = get(event_id)
    if not event:
        return None
    try:
        idx = int(n)
    except (TypeError, ValueError):
        return None
    if not 0 <= idx < len(event.choices):
        return None
    return event.choices[idx]


def action_text(event_id: str, n: int, lang: str = 'ru') -> str:
    c = choice_of(event_id, n)
    if not c:
        return ''
    return c.act_en if _en(lang) else c.act_ru


def scene_note(event_id: str, n: int, character_id: str = '', lang: str = 'ru') -> str:
    """The [EVENT ACTIVE] block: she plays the fear of getting caught and stays
    in the scene until he moves again."""
    event = get(event_id)
    c = choice_of(event_id, n)
    if not event or not c:
        return ''
    who = partner_name(character_id) if event.id in ('key', 'call') else ''
    if _en(lang):
        return (
            '[EVENT ACTIVE] ' + event.emoji + ' ' + event.en.format(partner=who) + '\n'
            'His answer to the event: "' + c.act_en + '". Play it out in this reply: heart pounding, '
            'whispers, broken sentences, body frozen or trembling, one living detail of fear of being '
            'caught. Stay inside the scene until he moves again — no drama, no confession, you are not found. '
            'Never ask for permission to continue and never comment on the buttons.')
    return (
        '[EVENT ACTIVE] ' + event.emoji + ' ' + event.ru.format(partner=who) + '\n'
        'Его ответ на событие: «' + c.act_ru + '». Отыграй это в этом же ответе: колотящееся сердце, '
        'шёпот, обрывки фраз, замершее или дрожащее тело, одна живая деталь страха спалиться. '
        'Оставайся в сцене, пока он не пошевелится, — без драмы, без признаний, вас не находят. '
        'Никогда не спрашивай разрешения продолжить и не упоминай кнопки.')


def is_paid(event_id: str, n: int) -> bool:
    c = choice_of(event_id, n)
    return bool(c and c.paid)


def price() -> int:
    return int(INTERRUPT_PEACH_COST)
