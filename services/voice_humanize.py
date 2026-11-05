"""V3.106.0: her voice notes sound like a woman, not an announcer.

Owner: «голос-то нормальным сделать, человеческим». Grok TTS (eve / ara) read
the chat text literally: emoji and «)))» were dropped, «хаха» was pronounced
as a word, and every line came out in the same even tone. Grok understands
speech tags inside the text (docs.x.ai text-to-speech): inline ``[laugh]``,
``[giggle]``, ``[chuckle]``, ``[sigh]``, ``[breath]``, ``[pause]`` and
wrapping ``<soft>…</soft>``, ``<whisper>…</whisper>``.

``to_speech(text, character_id)`` turns a chat line into a spoken one with a
few of those tags (at most MAX_TAGS, so it never sounds staged):

- «)))», «хаха», «ахах», 😂 → a giggle / laugh where it was;
- «…» → a short pause; «ммм» → a breath before it; 🥺 😔 → a sigh;
- a tender / intimate line, or a girl whose manner is a whisper → ``<soft>``;
- *actions in stars*, links and the remaining emoji are removed (they were
  read aloud or skipped awkwardly).

``strip_tags`` removes the tags again for the edge / old Gemini fallbacks;
``for_gemini`` rewrites them into Gemini 3.8 TTS tags (``<laugh>``, ``<sigh>``,
``<short pause>``) plus a ``style`` (whisper / empathetic / vocal_smile).
Flag: VOICE_HUMANIZE_ENABLED.
"""
from __future__ import annotations

import os
import re

ENABLED = os.getenv('VOICE_HUMANIZE_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')
MAX_TAGS = 3

SOFT_CHARACTERS = frozenset({'agata_01', 'maria_01', 'lera_01', 'liza_01', 'polina_01', 'kristina_01'})
_TENDER = re.compile(r'(скучаю|обнима|целую|нежн|люблю|мой хороший|мой милый|котик|засыпа|спокойной ночи|'
                     r'хочу тебя|прижм|шепч|рядом с тобой|miss you|kiss|hug|love you|good ?night|whisper)', re.I)
_WHISPER_ACTION = re.compile(r'\*[^*]{0,40}(шепч|шёпот|whisper)[^*]{0,40}\*', re.I)
_ACTION = re.compile(r'\*[^*\n]{1,80}\*')
_URL = re.compile(r'https?://\S+|@\w+')
_LAUGH_EMOJI = re.compile(r'[😂🤣😆😹]+')
_GIGGLE_EMOJI = re.compile(r'[😁😄😅🙈😜😝🤭]+')
_SMIRK_EMOJI = re.compile(r'[😏😉]+')
_SAD_EMOJI = re.compile(r'[🥺😔😢😞😥🥲]+')
_KISS_EMOJI = re.compile(r'[😘💋😚]+')
# anything else that is not a letter, digit, space or ordinary punctuation
_OTHER = re.compile(r"[^\w\s.,!?:;\-—…()«»\"'\[\]<>/]")
_BRACKETS = re.compile(r'\){2,}|\(\({1,}')
_HAHA = re.compile(r'\b(?:[ахх]?ха(?:ха)+х?|ахах\w*|хех\w*|хи(?:хи)+|haha\w*|hehe\w*|lol)\b', re.I)
_MMM = re.compile(r'\b(м{3,}|m{3,})\b', re.I)
_TAG = re.compile(r'\[(?:laugh|giggle|chuckle|sigh|breath|inhale|exhale|pause|long-pause)\]|</?(?:soft|whisper|slow)>')


def strip_tags(text: str) -> str:
    out = re.sub(r'\s{2,}', ' ', _TAG.sub('', text or ''))
    return re.sub(r'\s+([.,!?…])', r'\1', out).strip(' ,;')


def to_speech(text: str, character_id: str | None = None) -> str:
    """Chat line → a spoken line with a few Grok speech tags."""
    t = (text or '').strip()
    if not ENABLED or not t:
        return t
    whisper = bool(_WHISPER_ACTION.search(t))
    t = _ACTION.sub(' ', t)
    t = _URL.sub(' ', t)
    budget = [MAX_TAGS]

    def tag(name: str) -> str:
        if budget[0] <= 0:
            return ' '
        budget[0] -= 1
        return f' [{name}] '

    def once(pattern, name, s):
        return pattern.sub(lambda m: tag(name), s, count=1)

    t = once(_LAUGH_EMOJI, 'laugh', t)
    t = once(_HAHA, 'laugh', t)
    t = _HAHA.sub(' ', t)
    t = once(_BRACKETS, 'giggle', t)
    t = once(_GIGGLE_EMOJI, 'giggle', t)
    t = once(_SMIRK_EMOJI, 'chuckle', t)
    t = once(_SAD_EMOJI, 'sigh', t)
    t = _MMM.sub(lambda m: tag('breath').rstrip() + ' ' + m.group(1), t, count=1)
    if '…' in t or '...' in t:
        t = t.replace('...', '…')
        t = t.replace('…', '…' + tag('pause').rstrip(), 1)
    t = _KISS_EMOJI.sub(' ', t)
    t = _BRACKETS.sub(' ', t)
    t = re.sub(r'(?<=\w)\)+', '', t)  # a lone smiley «)» after a word
    t = _OTHER.sub(' ', t)
    t = re.sub(r'\s+([.,!?…])', r'\1', t)
    t = re.sub(r'\s{2,}', ' ', t).strip(' ,')
    if not t:
        return ''
    if whisper:
        return f'<whisper>{t}</whisper>'
    if (character_id or '') in SOFT_CHARACTERS or _TENDER.search(t):
        return f'<soft>{t}</soft>'
    return t


_GEM_MAP = (
    (re.compile(r'\[(?:laugh|giggle|chuckle)\]'), '<laugh>'),
    (re.compile(r'\[(?:sigh|exhale)\]'), '<sigh>'),
    (re.compile(r'\[(?:pause|long-pause|breath|inhale)\]'), '<short pause>'),
)


def for_gemini(spoken: str) -> tuple[str, str]:
    """V3.106.0: a to_speech() line → (Gemini 3.8 TTS text, style or '')."""
    t = spoken or ''
    style = ''
    if '<whisper>' in t:
        style = 'whisper'
    elif '<soft>' in t:
        style = 'empathetic'
    t = re.sub(r'</?(?:soft|whisper|slow)>', '', t)
    for pat, rep in _GEM_MAP:
        t = pat.sub(rep, t)
    if not style and '<laugh>' in t:
        style = 'vocal_smile'
    t = re.sub(r'\s{2,}', ' ', t).strip(' ,')
    return t, style
