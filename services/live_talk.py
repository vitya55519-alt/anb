"""V3.113.0: she answers in his rhythm and never bargains.

1 Nov 2026 backup, 2956 of her replies to his messages (25 Oct – 1 Nov):
- a third of his messages are 10 characters or less («ок», «как дела»), and
  she answered them with a median of 132 characters, half of all replies in
  two paragraphs. A short line answered with an essay is the first thing that
  gives a bot away;
- 10% of replies were a game or a condition («угадаешь — скину», «сначала
  ответь — потом покажу», «заслужи»). In the chats that ended the same day
  the last thing he saw was often a chain of such conditions;
- ~2% were cut mid-word on the token cap, and a few were her planning notes
  in English («phrasing / formula: … *   Is it in character»).

``rhythm_note`` is a short system note right before his message; ``fit_rhythm``
is the last-resort trim when a one-word message still got an essay.
``looks_leaked`` spots model planning text that slipped into the answer.
"""
from __future__ import annotations

import os
import re

ENABLED = os.getenv('LIVE_TALK_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')

_HEADER = 'Режиссёр (собеседнику не показывай и не упоминай): '

_NO_META = (' Не анализируй вслух его поведение и не объясняй, почему ты так отвечаешь. '
            'Не описывай свои действия, мимику и тон ни в *звёздочках*, ни в скобках — пиши только то, '
            'что человек набрал бы на телефоне, и не ставь имя перед репликой.')

SHORT_NOTE = (
    _HEADER + 'он написал совсем коротко. Ответь тоже коротко, как в живой переписке: одна строка, '
    'одно сообщение без второго абзаца. Но не только «ага» или «понятно»: после реакции добавь своё мнение, '
    'маленький факт о себе или конкретный вопрос по теме. Без описания, где ты и что на тебе.' + _NO_META
)
MEDIUM_NOTE = (
    _HEADER + 'ответь в его ритме: одна-две короткие фразы, одним сообщением. '
    'Сначала по сути того, что он сказал или спросил, затем развини тему своим мнением, деталью или вопросом.' + _NO_META
)
LONG_NOTE = (
    _HEADER + 'он написал развёрнуто — значит, ему важно. Сначала ответь по сути на то, что он рассказал '
    '(одна живая деталь из его слов), потом своё. До 3–4 коротких фраз; второй абзац только если есть правда вторая мысль.' + _NO_META
)

# A question still deserves an answer, even when it is two words long.
_QUESTION = re.compile(r'\?|\b(как|что|где|когда|почему|зачем|кто|какой|какая|какие|сколько|чем|who|what|where|when|why|how)\b', re.I)


def rhythm_kind(user_text: str) -> str:
    t = (user_text or '').strip()
    words = len(t.split())
    if len(t) <= 12 or (words <= 2 and len(t) <= 20):
        return 'short'
    if len(t) <= 60:
        return 'medium'
    return 'long'


def rhythm_note(user_text: str) -> str:
    if not ENABLED:
        return ''
    return {'short': SHORT_NOTE, 'medium': MEDIUM_NOTE, 'long': LONG_NOTE}[rhythm_kind(user_text)]


def fit_rhythm(answer: str, user_text: str) -> str:
    """A one-word message never gets an essay: when he wrote a few characters
    and she still sent several paragraphs, only her first bubble goes out."""
    if not ENABLED or not answer:
        return answer
    if rhythm_kind(user_text) != 'short':
        return answer
    bubbles = [b.strip() for b in answer.split('\n\n') if b.strip()]
    if len(bubbles) < 2 or len(answer) <= 200:
        return answer
    first = bubbles[0]
    # keep the second bubble when the first is only a sound («ох…», «ахах»)
    if len(re.findall(r'[а-яёa-z]{2,}', first, re.I)) < 3:
        return '\n\n'.join(bubbles[:2])
    return first


# ── bargaining («угадаешь — скину», «сначала ответь — потом покажу») ─────────
BARGAIN = re.compile(
    r'угада\w*|правд\w* или действи\w*|truth or dare|заслуж\w*|услови\w*|'
    r'сначала (ответь|скажи|расскажи|назови|покажи)|'
    r'скажешь\W{0,3}.{0,25}(покажу|пришлю|скину)|'
    r'(покажу|пришлю|скину)\W{0,3}.{0,15}(если|когда) (ты )?(скажешь|ответишь|угадаешь|назовёшь)',
    re.I,
)


def bargained_recently(recent_bot_texts, window: int = 8) -> bool:
    """True when one of her last ``window`` messages already set a game or a condition."""
    return any(BARGAIN.search(t or '') for t in list(recent_bot_texts or [])[-window:])


NO_BARGAIN_NOTE = (
    _HEADER + 'ты уже недавно ставила ему условие или предлагала игру. Сейчас без торга: никаких «угадай», '
    '«сначала ответь», «заслужи». Если он что-то просит — либо да, либо честное «не сейчас» с причиной из жизни.'
)


# ── model planning text that leaked into the answer ─────────────────────────
_LEAK = re.compile(
    r'(^|\n)\s*\*\s{2,}\S|'                       # «*   Is it in character» bullets
    r'\b(in character|the user|user\'s message|no repeats|phrasing|draft \d|final answer|'
    r'constraint|self-correction|let me (think|check|re-?read)|i need to (respond|reply|write))\b|'
    r'(^|\n)\s*(Detail|Check|Response|Reply|Output|Thought|Plan|Goal|Context|Persona)\s*:',
    re.I,
)


def looks_leaked(text: str) -> bool:
    return bool(_LEAK.search(text or ''))
