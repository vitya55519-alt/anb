"""V3.98.0: she answers in the language he writes in.

3 Nov 2026 backup: 207 of 1475 replies to English messages (14%) came back in
Russian, 71 of 107 English-writing users got a Russian line at least once —
«Send a video» was answered with a story about a car dealership in Russian.
The persona prompt and the history are Russian, so the model slips back.

Two cheap defences, both pure text checks (no extra LLM call unless the check
fails): a short system directive right before his message, and — if the answer
still came out in Cyrillic — one regeneration with a firmer directive.
"""
from __future__ import annotations

import re

_CYR = re.compile(r'[А-Яа-яЁё]')
_LAT = re.compile(r'[A-Za-z]')
_WORD = re.compile(r"[a-z']+")
# common English function words; keyboard-layout gibberish typed by a Russian
# speaker («ghbdtn», «ltgkjq») never contains them
_EN_WORDS = frozenset((
    'i', 'you', 'the', 'and', 'to', 'is', 'are', 'am', 'it', 'me', 'my', 'we', 'your', 'what', 'how', 'why',
    'where', 'when', 'who', 'can', 'do', 'does', 'did', 'will', 'want', 'wanna', 'send', 'show', 'send',
    'pic', 'pics', 'photo', 'video', 'hi', 'hey', 'hello', 'yes', 'no', 'not', 'please', 'pls', 'with', 'for',
    'of', 'in', 'on', 'at', 'this', 'that', 'a', 'an', 'be', 'have', 'got', 'just', 'like', 'love', 'too',
    'tell', 'more', 'now', 'good', 'nice', 'ok', 'okay', 'thanks', 'thx', 'sexy', 'hot', 'baby', 'babe',
    'name', 'day', 'night', 'lol', 'fuck', 'naked', 'nude', 'dont', "don't", "i'm", "you're", "it's",
    'so', 'if', 'but', 'or', 'from', 'her', 'she', 'he', 'his', 'let', 'lets', "let's", 'come', 'see',
))


def is_cyrillic_dominant(text: str) -> bool:
    cyr = len(_CYR.findall(text or ''))
    lat = len(_LAT.findall(text or ''))
    return cyr > lat and cyr >= 6


def looks_english(text: str, language_code: str | None = None, recent_user_texts=()) -> bool:
    """True when his message is English: Latin letters only and either an
    English function word in it, or an English Telegram account, or his last
    messages were English too (so «ok», «hmm» keep the language)."""
    t = (text or '').strip()
    if not t or _CYR.search(t):
        return False
    letters = len(_LAT.findall(t))
    if letters < 2:
        return False
    words = _WORD.findall(t.lower())
    if any(w in _EN_WORDS for w in words):
        return True
    if (language_code or '').lower().startswith('en') and letters >= 3:
        return True
    for prev in list(recent_user_texts)[-3:]:
        p = (prev or '').strip()
        if p and not _CYR.search(p) and any(w in _EN_WORDS for w in _WORD.findall(p.lower())):
            return True
    return False


DIRECTIVE = (
    'ВАЖНО: пользователь пишет по-английски. Ответь ТОЛЬКО на английском — живым разговорным английским, '
    'без единого русского слова. Оставайся в роли и в своём характере; действия в *звёздочках* и эмодзи '
    'тоже на английском, как будто ты родом из его страны.'
)
STRICT_DIRECTIVE = (
    'СТРОГО: твой предыдущий ответ вышел по-русски, а пользователь пишет по-английски. Напиши этот ответ '
    'заново ПОЛНОСТЬЮ на английском. Ни одной русской буквы. Тот же смысл, тот же характер.'
)
