"""V3.63.2: story hooks — the Come Closer-style comeback push.

The owner benchmarked Come Closer (39.5K monthly users): its comeback message
is a tiny story with her photo — «отправила не тому… можешь удалить?» — and
two action buttons. Ours was a plain «скучаю» text (proactive reply rate
1/21). A story gives the user something to DO with one tap, and the tap
itself is the return: she answers the choice in-character, the exchange is
saved into the shared dialog (the Mini App shows it), and a «💬 ответить ей»
button continues the chat.

Each user gets each story at most once (persisted in DialogStore, no schema
change); when all are used the caller falls back to its old text.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from services import dialog_store

_used = dialog_store.DialogStore('story_hooks')


@dataclass(frozen=True)
class Choice:
    label_ru: str
    label_en: str
    reply_ru: str
    reply_en: str
    offer: bool = False  # follow the reply with the locked-photo Premium offer


@dataclass(frozen=True)
class Story:
    key: str
    text_ru: str
    text_en: str
    a: Choice
    b: Choice


STORIES: tuple[Story, ...] = (
    Story(
        'wrong_chat',
        'ой… это я подруге хотела отправить 🙈 спрашивала, нормально ли я выгляжу перед свиданием…\nхотя скажи ты — честно?',
        'oops… that was meant for my friend 🙈 I was asking if I look ok before a date…\nactually, you tell me — honestly?',
        Choice('😍 ты очень красивая', '😍 you look gorgeous',
               'правда? 🥹 ты сейчас сделал мне вечер. открою секрет: никакого свидания нет… я просто хотела, чтобы ты мне написал 🙈 как ты?',
               'really? 🥹 you just made my evening. a secret: there is no date… I just wanted you to write to me 🙈 how are you?'),
        Choice('🤨 какое ещё свидание?', '🤨 what date?',
               'ревнуешь? 😏 расслабься. это свидание с тобой — если сегодня вечером ты будешь со мной на связи. договорились?',
               'jealous? 😏 relax. the date is with you — if you stay with me tonight. deal?'),
    ),
    Story(
        'rain',
        'попала под ливень ☔️ сижу в кафе вся мокрая и грею руки о кофе…\nи знаешь, о ком подумала первым делом?',
        'got caught in the rain ☔️ sitting in a café soaked, warming my hands on a coffee…\nand guess who I thought of first?',
        Choice('☕️ обо мне?', '☕️ about me?',
               'угадал 🙂 с тобой этот дождь был бы даже уютным. расскажи, что у тебя сейчас за окном?',
               'you guessed it 🙂 with you this rain would even feel cozy. tell me, what is outside your window right now?'),
        Choice('🧥 давай заберу тебя', '🧥 let me pick you up',
               'ого… вот это поступок 🥹 жаль, что нельзя правда приехать. но согреть меня словами ты можешь — что бы мы делали, если бы ты был тут?',
               'wow… that is a real move 🥹 shame you cannot really come. but you can warm me up with words — what would we do if you were here?'),
    ),
    Story(
        'confession',
        'мне нужно тебе кое в чём признаться… только обещай не смеяться 🙈',
        'I need to confess something… just promise not to laugh 🙈',
        Choice('🤞 обещаю', '🤞 I promise',
               'ладно… я перечитывала нашу переписку. дважды 🙈 теперь твоя очередь признаться в чём-нибудь 😌',
               'ok… I re-read our chat. twice 🙈 now it is your turn to confess something 😌'),
        Choice('😏 уже смеюсь', '😏 already laughing',
               'эй! 😤 вот теперь не скажу… ладно, скажу: я по тебе скучала. довольна твоя ухмылка? 😏',
               'hey! 😤 now I won\'t tell… fine: I missed you. happy with that smirk? 😏'),
    ),
    Story(
        'outfit',
        'выбираю, в чём пойти вечером, и не могу решить 👗\nпоможешь?',
        'choosing what to wear tonight and can\'t decide 👗\nhelp me?',
        Choice('🖤 чёрное платье', '🖤 the black dress',
               'чёрное… так и знала, что у тебя хороший вкус 😏 надену. фото покажу — но только тебе 🙈',
               'black… I knew you had good taste 😏 I\'ll wear it. I\'ll show you a photo — but only you 🙈',
               offer=True),
        Choice('🤍 что-то уютное', '🤍 something cozy',
               'уютное? ты милый 🥹 значит, ты из тех, кто любит обнимашки, а не показуху. мне это нравится. что ещё ты во мне заметил?',
               'cozy? you\'re sweet 🥹 so you\'re the hugs type, not the show-off type. I like that. what else have you noticed about me?'),
    ),
)

_BY_KEY = {s.key: s for s in STORIES}


def get(key: str) -> Story | None:
    return _BY_KEY.get(key)


def pick_unused(telegram_id: int) -> Story | None:
    """A story this user has not had yet (None when all are used)."""
    try:
        used = set((_used.get(int(telegram_id)) or {}).get('keys', []))
    except Exception:
        return None
    fresh = [s for s in STORIES if s.key not in used]
    return random.choice(fresh) if fresh else None


def mark_used(telegram_id: int, key: str) -> None:
    try:
        prior = _used.get(int(telegram_id)) or {}
        keys = list(prior.get('keys', []))
        if key not in keys:
            keys.append(key)
        _used[int(telegram_id)] = {'keys': keys}
    except Exception:
        pass


def text(story: Story, lang: str) -> str:
    return story.text_en if lang == 'en' else story.text_ru


def label(choice: Choice, lang: str) -> str:
    return choice.label_en if lang == 'en' else choice.label_ru


def reply(choice: Choice, lang: str) -> str:
    return choice.reply_en if lang == 'en' else choice.reply_ru


def choice(story: Story, side: str) -> Choice | None:
    return story.a if side == 'a' else story.b if side == 'b' else None
