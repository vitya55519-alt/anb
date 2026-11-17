"""V3.23.0 — Spicy monetization pack.

Three paid products for the audience that comes for the sensual content,
all outside the free daily photo quota (delivered with delivery_type
'paid', which never touches free_used and never consumes photo credits):

1. SPICY_SETS — curated hot photo sets (boudoir/tease/nude) sold directly
   from the photo menu;
2. PRIVATE_GIFTS — gifts with an 18+ photo finale (like dates, but
   intimate): an affection delta + narration + a private scene photo set;
3. Fantasy constructor — the user pays, describes a fantasy in free text,
   and the bot assembles a matching custom set.

Safety rules:
- every product is gated by relationship level AND the one-time 18+
  confirmation; pre_checkout re-validates amount, level and age gate;
- the fantasy parser NEVER passes raw user text into the image prompt —
  only whitelisted keyword extractions — so users cannot smuggle prompt
  payloads past the providers' moderation.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass(frozen=True)
class SpicySet:
    id: str
    name: str
    name_en: str
    emoji: str
    min_level: int
    cost: int          # Telegram Stars
    scene: str         # photo scene for the generated set
    mood: str          # mood injected into the PhotoRequest
    text: str          # RU narration sent with the set
    text_en: str
    # V3.50.0: extra relationship-path requirement (-100 tenderness .. +100
    # passion). The boldest set also asks for an uninhibited path; the level
    # and the one-time 18+ confirmation always stay the primary gates.
    min_path: int = 0


@dataclass(frozen=True)
class PrivateGift:
    id: str
    name: str
    name_en: str
    emoji: str
    min_level: int
    cost: int          # Telegram Stars
    affection: float   # relationship delta applied on purchase
    scene: str         # photo scene for the 18+ finale set
    mood: str
    text: str          # RU narration
    text_en: str


SPICY_SETS: tuple[SpicySet, ...] = (
    SpicySet(
        'boudoir', 'Будуар', 'Boudoir', '🔥', 5, 15, 'lingerie',
        'confident, intimate',
        'Свечи, медленная музыка и только кружево. Она ждала именно тебя.',
        'Candles, slow music and nothing but lace. She was waiting for you.',
    ),
    SpicySet(
        'tease', 'Дразнит', 'Teasing you', '😈', 6, 20, 'tease',
        'playful, teasing',
        'Она играет: взгляд через плечо, силуэт в мягком свете — и никаких спойлеров.',
        'She is playing a game: a glance over her shoulder, a silhouette in soft light — no spoilers.',
    ),
    SpicySet(
        'devoted', 'Только для тебя', 'Only for you', '🖤', 6, 25, 'nude',
        'intimate, trusting',
        'Самое личное, что она может доверить. Только для твоих глаз.',
        'The most personal thing she can entrust. Only for your eyes.',
        min_path=30,
    ),
)

PRIVATE_GIFTS: tuple[PrivateGift, ...] = (
    PrivateGift(
        'silk', 'Шёлковый халатик', 'Silk robe', '🎀', 5, 15, 2.0, 'lingerie',
        'soft, tender',
        'Она медленно примеряет твой подарок — шёлк скользит по коже, и она ловит твой взгляд.',
        'She slowly tries on your gift — silk sliding over her skin as she catches your eye.',
    ),
    PrivateGift(
        'lace', 'Кружевной комплект', 'Lace set', '🖤', 6, 20, 2.5, 'lingerie',
        'confident, playful',
        'Ты угадал с размером 😏 Она вертится перед зеркалом, показывая, как сидит кружево.',
        'You guessed the size right 😏 She turns in front of the mirror, showing how the lace fits.',
    ),
    PrivateGift(
        'candles', 'Ванна при свечах', 'Candlelit bath', '🕯', 6, 25, 3.0, 'tease',
        'relaxed, teasing',
        'Пена, свечи и никакой спешки. Она зовёт тебя составить компанию.',
        'Foam, candles and no hurry at all. She invites you to keep her company.',
    ),
)

# Fantasy constructor: paid scenario-to-photo-set product.
FANTASY_COST_STARS = max(5, int(os.getenv('FANTASY_COST_STARS', '30')))
FANTASY_MIN_LEVEL = 6


def get_spicy_set(set_id: str) -> SpicySet | None:
    for item in SPICY_SETS:
        if item.id == set_id:
            return item
    return None


def get_private_gift(gift_id: str) -> PrivateGift | None:
    for item in PRIVATE_GIFTS:
        if item.id == gift_id:
            return item
    return None


# Paid entitlements are not expiring wizard state. Keep one immutable identity
# per charge, including terminal orders, so payment/request replays cannot render.
PAID_FANTASY_PREFIX = 'paid_fantasy:'


def paid_fantasy_key(charge: str) -> str:
    # Existing PostgreSQL column is VARCHAR(32); no schema migration is needed.
    # Check the full charge in the payload as well (fail closed on a collision).
    return PAID_FANTASY_PREFIX + hashlib.sha256(charge.encode('utf-8')).hexdigest()[:19]


@contextmanager
def _fantasy_session(telegram_id: int):
    from sqlalchemy import select, update
    from models.app_models import User
    from services.db import SessionLocal

    with SessionLocal() as session:
        # Like memory/story claims: locks the account on SQLite AND PostgreSQL.
        session.execute(update(User).where(User.telegram_id == str(telegram_id))
                        .values(chat_used=User.chat_used))
        user = session.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if user is None:
            raise ValueError('fantasy user not found')
        yield session, user
        session.commit()


def _fantasy_row(session, telegram_id: int, charge: str):
    from sqlalchemy import select
    from models.app_models import DialogSession

    row = session.scalar(select(DialogSession).where(
        DialogSession.telegram_id == int(telegram_id),
        DialogSession.session_key == paid_fantasy_key(charge)))
    if row is not None and json.loads(row.payload_json).get('charge') != charge:
        raise ValueError('fantasy charge key collision')
    return row


def _create_fantasy_order(session, user, charge: str, amount: int,
                          character_id: str, language: str, created_at=None):
    from models.app_models import DialogSession, Message

    if not charge or amount <= 0 or not character_id:
        raise ValueError('invalid paid fantasy')
    row = _fantasy_row(session, int(user.telegram_id), charge)
    if row is not None:
        return json.loads(row.payload_json), False
    instruction = (
        'Your paid photo set is saved. Describe the scenario here: outfit, place, mood. '
        'This is a photo scenario, not a chat turn; no second payment is needed.'
        if language == 'en' else
        'Оплаченный фотосет сохранён. Опиши здесь сценарий: образ, место, настроение. '
        'Это сценарий фото, а не ход диалога; повторная оплата не нужна.')
    message = Message(user_id=user.id, character_id=character_id, role='assistant',
                      content=instruction, origin='fantasy')
    session.add(message)
    session.flush()
    order = {'charge': charge, 'amount': amount, 'character_id': character_id,
             'status': 'pending', 'language': language, 'instruction_id': message.id}
    row = DialogSession(telegram_id=int(user.telegram_id), session_key=paid_fantasy_key(charge),
                        payload_json=json.dumps(order, ensure_ascii=False))
    if created_at is not None:
        row.created_at = created_at
    session.add(row)
    session.flush()
    return order, True


def _migrate_fantasy_pending(session, user, language: str):
    from sqlalchemy import select
    from models.app_models import DialogSession
    from config import CHARACTER_ID

    legacy = session.scalar(select(DialogSession).where(
        DialogSession.telegram_id == int(user.telegram_id),
        DialogSession.session_key == 'fantasy_pending'))
    if legacy is None:
        return
    value = json.loads(legacy.payload_json)
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError('invalid legacy paid fantasy')
    charge, amount = value
    # Bind once to the persisted selection, never to an arbitrary request's girl.
    character_id = (user.selected_character or '').strip() or CHARACTER_ID
    _create_fantasy_order(session, user, str(charge), int(amount), character_id,
                          language, legacy.created_at)
    session.delete(legacy)
    session.flush()


def create_paid_fantasy(telegram_id: int, charge: str, amount: int,
                        character_id: str, language: str = 'ru') -> tuple[dict, bool]:
    """Persist payment entitlement + app instruction atomically, without overwrites."""
    with _fantasy_session(telegram_id) as (session, user):
        _migrate_fantasy_pending(session, user, language)
        return _create_fantasy_order(session, user, charge, int(amount), character_id, language)


def paid_fantasy_response(order: dict) -> dict:
    english = order.get('language') == 'en'
    status = order['status']
    replies = {
        'generating': ('Scenario received. Your paid set is being prepared.',
                       'Сценарий принят. Готовим оплаченный сет.'),
        'delivered': ('Your paid set has been delivered to this chat.',
                      'Оплаченный сет уже доставлен в этот чат.'),
        'refunded': ('The set could not be delivered. Stars were refunded.',
                     'Сет не удалось доставить. Stars возвращены.'),
        'needs_support': ('Your order is saved. Contact /support to check delivery; do not pay again.',
                          'Заказ сохранён. Напиши /support для проверки доставки; не оплачивай повторно.'),
    }
    reply = replies[status][0 if english else 1]
    return {'ok': True, 'reply': reply, 'message_id': order.get('message_id'),
            'fantasy_status': status}


def claim_paid_fantasy(telegram_id: int, character_id: str, text: str,
                       language: str = 'ru') -> dict | None:
    """Intercept a scenario, or its replay, before chat/memory/quota processing.

    An ambiguous generating order is NEVER reclaimed after a restart. The saved
    text also deduplicates a replay after delivery, even if another purchase waits.
    """
    from sqlalchemy import select
    from models.app_models import DialogSession, Message

    text = (text or '').strip()[:4000]
    with _fantasy_session(telegram_id) as (session, user):
        _migrate_fantasy_pending(session, user, language)
        rows = session.scalars(select(DialogSession).where(
            DialogSession.telegram_id == int(telegram_id),
            DialogSession.session_key.startswith(PAID_FANTASY_PREFIX, autoescape=True))
            .order_by(DialogSession.created_at, DialogSession.id)).all()
        orders = [(row, json.loads(row.payload_json)) for row in rows]
        mine = [(row, order) for row, order in orders if order['character_id'] == character_id]
        replay = next((order for _, order in mine if order.get('request', {}).get('text') == text), None)
        active = next((order for _, order in mine if order['status'] in {'generating', 'needs_support'}), None)
        pending = next(((row, order) for row, order in mine if order['status'] == 'pending'), None)
        if not (replay or active or pending):
            return None
        if not user.adult_confirmed:
            return {'claimed': False, 'response': {'ok': False, 'error': 'adult'}}
        if replay or active:
            return {'claimed': False, 'response': paid_fantasy_response(replay or active)}
        if len(text) < 3:
            return {'claimed': False, 'response': {'ok': False, 'error': 'fantasy_scenario_short'}}
        # Do not claim another girl's queued order while a previous set is in flight.
        if any(order['status'] in {'generating', 'needs_support'} for _, order in orders):
            return {'claimed': False, 'response': {'ok': False, 'error': 'fantasy_busy'}}
        row, order = pending
        fields = parse_fantasy(text)
        order.update(status='generating', request={'text': text, 'fields': fields})
        scenario = Message(user_id=user.id, character_id=character_id, role='user',
                           content=('Paid photo scenario: ' if language == 'en' else
                                    'Сценарий оплаченного фото: ') + text, origin='fantasy')
        ack = Message(user_id=user.id, character_id=character_id, role='assistant',
                      content=paid_fantasy_response(order)['reply'], origin='fantasy')
        session.add_all([scenario, ack])
        session.flush()
        order.update(message_id=ack.id, scenario_message_id=scenario.id)
        row.payload_json = json.dumps(order, ensure_ascii=False)
        return {'claimed': True, 'order': order, 'response': paid_fantasy_response(order)}


def finish_paid_fantasy(telegram_id: int, charge: str, status: str) -> bool:
    """Record confirmed delivery/refund, or ambiguity; never reopen an order."""
    if status not in {'delivered', 'refunded', 'needs_support'}:
        raise ValueError('invalid fantasy completion')
    with _fantasy_session(telegram_id) as (session, user):
        row = _fantasy_row(session, telegram_id, charge)
        if row is None:
            return False
        order = json.loads(row.payload_json)
        if order['status'] in {'delivered', 'refunded'}:
            return order['status'] == status
        if order['status'] not in {'generating', 'needs_support'}:
            return False
        order['status'] = status
        row.payload_json = json.dumps(order, ensure_ascii=False)
        return True


def get_paid_fantasy(telegram_id: int, charge: str) -> dict | None:
    from services.db import SessionLocal

    with SessionLocal() as session:
        row = _fantasy_row(session, telegram_id, charge)
        return json.loads(row.payload_json) if row else None


# --- Fantasy constructor parser ----------------------------------------------
# Only whitelisted keyword extractions below EVER reach the image prompt.

_SCENE_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ('nude', re.compile(r'голой|голую|голая|голые|голых|голым|голыми|обнаж|без одежды|полностью без|без ничего|максимально откровен|полное доверие|самое личное|самое сокровен|самый интим|самая интим|самые интим|ню\b|нагая|нагой|нагую|нагое|нагие|нагих|нагим|нагими|нагому|нагою', re.I)),
    ('tease', re.compile(r'дразн|попу|попк|спин|силуэт|сзади|загадочн|интриг|полуоберну|оглядыва|взгляд через плечо', re.I)),
    ('lingerie', re.compile(r'бель|кружев|лифчик|бюстгальтер|чулк|подвязк|корсет|пеньюар|неглиже|линжери', re.I)),
)

_COLOR_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ('black', re.compile(r'чёрн|черн', re.I)),
    ('white', re.compile(r'бел(?:ое|ом|ый|ая|ую|ого|ые|ых|ым|ой)|белоснеж', re.I)),
    ('red', re.compile(r'красн|ал(?:ое|ый|ая|ую)|бордов', re.I)),
    ('pink', re.compile(r'розов|нежно-розов', re.I)),
    ('purple', re.compile(r'фиолет|лилов|сиренев', re.I)),
    ('blue', re.compile(r'син(?:ее|ий|яя|юю)|голуб', re.I)),
)

_STYLE_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ('stockings and garter belt', re.compile(r'чулк|подвязк', re.I)),
    ('lace', re.compile(r'кружев', re.I)),
    ('silk', re.compile(r'шёлк|шелк|атлас', re.I)),
    ('corset', re.compile(r'корсет', re.I)),
)

_LOCATION_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ('bedroom', re.compile(r'кроват|спальн|постел', re.I)),
    ('bathroom', re.compile(r'душ|ванн|пена', re.I)),
    ('in front of a large mirror', re.compile(r'зеркал', re.I)),
    ('hotel room', re.compile(r'отел|номер', re.I)),
    ('on a cozy sofa', re.compile(r'диван', re.I)),
    ('by a night window with city lights', re.compile(r'окн|ночн\w* город', re.I)),
)

_MOOD_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ('tender, soft', re.compile(r'нежн|ласков|мягк', re.I)),
    ('bold, passionate', re.compile(r'дерзк|страст|горяч|смел', re.I)),
    ('playful, teasing', re.compile(r'игрив|дразн|озорн|шали', re.I)),
    ('romantic, warm', re.compile(r'романтич|влюблён|влюблен|тепл', re.I)),
    ('confident, dominant', re.compile(r'домин|уверен|властн|команд', re.I)),
)

_TIME_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ('evening', re.compile(r'вечер|ночь|ночн|закат|свеч', re.I)),
    ('morning', re.compile(r'утр|рассвет|после сна', re.I)),
)


def parse_fantasy(text: str) -> dict:
    """Map free text to WHITELISTED PhotoRequest fields only.

    Returns a dict of keyword args for PhotoRequest. Raw user text is never
    included — every value below is a fixed, moderation-safe string.
    """
    text = (text or '').strip().lower()
    scene = 'lingerie'  # default for the level-6+ gated product
    for candidate, pattern in _SCENE_PATTERNS:
        if pattern.search(text):
            scene = candidate
            break
    color = next((c for c, p in _COLOR_PATTERNS if p.search(text)), '')
    style = next((s for s, p in _STYLE_PATTERNS if p.search(text)), '')
    location = next((loc for loc, p in _LOCATION_PATTERNS if p.search(text)), '')
    mood = next((m for m, p in _MOOD_PATTERNS if p.search(text)), 'intimate, trusting')
    time_of_day = next((t for t, p in _TIME_PATTERNS if p.search(text)), '')
    return {
        'scene': scene,
        'mood': mood,
        'location': location,
        'time_of_day': time_of_day,
        'underwear_color': color,
        'underwear_style': style,
        'customized': True,
    }
