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


# V3.105.0: English words slipping into a Russian reply («нормально, especially
# когда это важное дело») — MiniMax does it now and then. A short directive for
# Russian talks, and one cheap repair call when a reply still has stray words.
import os as _os

RU_PURITY_ENABLED = _os.getenv('LANG_RU_PURITY_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')
_LAT_WORD = re.compile(r"(?<![A-Za-z0-9_@/.#])[A-Za-z][A-Za-z'\-]{2,}(?![A-Za-z0-9_@/.])")
# words that are fine in a Russian chat with this bot (product names, slang)
_ALLOWED = frozenset((
    'premium', 'vip', 'stars', 'telegram', 'tg', 'ok', 'okay', 'lol', 'wow', 'omg', 'sms', 'iphone',
    'instagram', 'inst', 'tiktok', 'youtube', 'netflix', 'wifi', 'wi-fi', 'online', 'offline', 'selfie',
    'emoji', 'gif', 'mp3', 'usb', 'pdf', 'xxx', 'bmw', 'audi', 'mercedes', 'kia', 'lada', 'nike', 'adidas',
    'zara', 'apple', 'samsung', 'xiaomi', 'playstation', 'xbox', 'ps5', 'dota', 'cs', 'fifa', 'gta',
    'minecraft', 'spotify', 'whatsapp', 'vk', 'ozon', 'wildberries', 'yandex', 'google', 'chatgpt', 'ai',
))

RU_DIRECTIVE = (
    'Пиши только по-русски: ни одного английского слова посреди фразы (не «especially», «anyway», «baby» — '
    'а «особенно», «короче», «малыш»). Латиницей можно только названия брендов и то, что он сам так написал.'
)


def stray_english(answer: str, user_texts=()) -> list[str]:
    """English words inside a Russian reply that he did not use himself."""
    if not RU_PURITY_ENABLED or not is_cyrillic_dominant(answer):
        return []
    his = set()
    for t in user_texts or ():
        his.update(w.lower() for w in _LAT_WORD.findall(t or ''))
    out = []
    for w in _LAT_WORD.findall(answer or ''):
        lw = w.lower()
        if lw in _ALLOWED or lw in his or w.isupper() or lw in out:
            continue
        out.append(lw)
    return out


def repair_prompt(answer: str, words: list[str]) -> list[dict]:
    return [
        {'role': 'system', 'content': (
            'Ты корректор. В русском сообщении девушки проскочили английские слова: ' + ', '.join(words) +
            '. Замени каждое на естественное русское слово или выражение по смыслу. Больше НИЧЕГО не меняй: '
            'тот же текст, те же эмодзи, та же пунктуация и регистр. Верни только исправленное сообщение.')},
        {'role': 'user', 'content': answer},
    ]
