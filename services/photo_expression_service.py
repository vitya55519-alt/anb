"""Rule-based facial-expression detection for photo generation.

Photos used to always show the character with the same "warm relaxed smile",
regardless of the conversation. This module maps the emotional tone of the user's
latest message to a facial-expression description that is then injected into the
photo prompt — so a compliment yields a genuine smile, rudeness yields a hurt/
disappointed look, etc.

Deliberately NOT LLM-based: the photo pipeline is a paid, latency-sensitive path
and an extra model call per image would add cost and a failure point. Keyword
rules are deterministic, cheap, and good enough for expressive variety.

Matching is token-prefix based so Russian morphology works: "красивая" matches
the stem "красив", "обожаю" matches "обожа", etc. A plain "пришли фото" is NOT
rude — only genuine insults or pushy demands trigger an upset expression.

All expression descriptions are kept safe and visually clear — no "crying hard",
no grotesque or exaggerated distress — so image quality and the character's
identity lock are never undermined.
"""
from __future__ import annotations

import re

_TOKEN_SPLIT = re.compile(r'[^\w]+', re.UNICODE)

# Multi-word phrases checked first via substring match (token-prefix can't see
# phrases like "хочу тебя" because tokens are split on whitespace).
_PHRASES: list[tuple[str, str]] = [
    ('давай уже', 'upset'),
    ('хочу тебя', 'teasing'),
    ('хочу поцеловать', 'teasing'),
    ('хочу обнять', 'teasing'),
    ('want you', 'teasing'),
    ('want to kiss', 'teasing'),
    ('want to hug', 'teasing'),
]

# Ordered by priority: the first category whose stem matches a token wins.
# Rudeness is checked before compliment so "ты тупая, но красивая" resolves to
# upset (the insult dominates the expression in that moment).
_CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    # Rudeness / insults / aggressive demanding → hurt, disappointed.
    # A plain "пришли фото" / "давай" is NOT rude — it stays neutral. Only
    # genuine insults or pushy demands ("давай уже", быстрее, немедленно) trigger upset.
    (
        'upset',
        (
            'быстрее', 'немедленно', 'сейчас', 'идиот', 'тупая', 'дура',
            'ненави', 'отвратит', 'уродли', 'придур', 'заткни', 'отстань',
            'stupid', 'ugly', 'hate', 'shut', 'dumb', 'bitch', 'whore', 'idiot',
        ),
    ),
    # User is sad / lonely / tired → caring, concerned.
    (
        'concerned',
        (
            'грустно', 'грустн', 'плохо', 'устал', 'одинок', 'плач', 'депресс',
            'тосклив', 'тяжело', 'обидно', 'расстроен', 'тоскую',
            'sad', 'lonely', 'tired', 'depress', 'cry', 'anxious', 'stress',
            'exhausted', 'alone',
        ),
    ),
    # Playful / flirty → teasing smirk.
    # Note: bare "хочу"/"want" are intentionally NOT here — "хочу фото" or
    # "хочу спать" must stay neutral, not become flirt. Match only explicit
    # romantic/flirty stems.
    (
        'teasing',
        (
            'поцелуй', 'поцелова', 'обним', 'соблазн', 'флирт', 'заигрыв', 'провокаци',
            'шалун', 'подразни', 'жажд', 'игрив', 'горяч',
            'kiss', 'hug', 'cuddle', 'flirt', 'tease', 'wink', 'naughty',
            'playful',
        ),
    ),
    # Compliment / positive → warm genuine smile.
    (
        'smile',
        (
            'красив', 'красав', 'прекрасн', 'милый', 'мил', 'люблю', 'обожа', 'спасибо',
            'благодар', 'класс', 'супер', 'шикарн', 'восхитительн', 'лучш',
            'прелестн', 'симпатичн', 'чудесн', 'нравишься', 'тепло', 'уютн',
            'good', 'beautiful', 'pretty', 'gorgeous', 'lovely', 'love', 'amazing',
            'wonderful', 'cute', 'sweet', 'nice',
        ),
    ),
]


# Each value replaces the old hardcoded "natural warm relaxed expression..."
# sentence inside the EXPRESSION block of the photo prompt.
EXPRESSIONS: dict[str, str] = {
    'smile': (
        'a warm genuine soft smile with the eyes slightly crinkled, relaxed and happy. '
        'Keep it subtle and believable; avoid an exaggerated forced grin.'
    ),
    'upset': (
        'a slightly hurt, quietly disappointed expression: softer downturned mouth, '
        'subdued gaze, gentle furrow of the brow. Calm and restrained — not crying, '
        'not exaggerated distress, no tears.'
    ),
    'concerned': (
        'a gentle caring, concerned expression: soft worried eyes, empathetic warm gaze, '
        'a faint reassuring look. Subtle and believable, no exaggerated sadness.'
    ),
    'teasing': (
        'a playful teasing smirk with one eyebrow slightly raised, flirty confident gaze '
        'and a hint of a smile. Subtle and tasteful.'
    ),
    'neutral': (
        'a natural warm relaxed expression. Keep it subtle, relaxed and believable; '
        'avoid a blank stern expression and avoid an exaggerated forced grin.'
    ),
}


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_SPLIT.split(text.lower()) if t]


def detect_expression_key(text: str | None) -> str | None:
    """Return an expression key derived from the user's message, or None if the
    message carries no clear emotional signal (caller falls back to the default
    warm smile)."""
    if not text:
        return None
    lowered = text.lower()
    # 1. Multi-word phrases (substring) — checked first so "хочу тебя" and
    #    "давай уже" match even though their tokens are split on whitespace.
    for phrase, key in _PHRASES:
        if phrase in lowered:
            return key
    # 2. Single-token stem-prefix match (handles Russian morphology).
    toks = _tokens(text)
    if not toks:
        return None
    for key, stems in _CATEGORIES:
        for tok in toks:
            for stem in stems:
                if tok.startswith(stem):
                    return key
    return None


def expression_description(key: str | None, name: str) -> str:
    """Build the EXPRESSION prompt sentence for a character named `name`.

    Unknown/None keys fall back to the default neutral warm expression so the
    pipeline never breaks on an unmapped value.
    """
    desc = EXPRESSIONS.get(key or '', EXPRESSIONS['neutral'])
    return f'EXPRESSION: {name} has {desc}'
