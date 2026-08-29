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

import os
import re
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
