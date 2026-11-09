"""V3.129.0: two channel rubrics next to «🔥 Девушка дня» (@Anna634212).

From the «как вести канал AI-сервиса» template the owner brought: the channel
should be interesting by itself, with the bot appearing softly inside the
content, and the audience should feel it shapes the project.

«🗳 Выбираете вы» — an anonymous poll (which girl / look / story next). When
the owner closes it, the bot reads the real vote counts (stop_poll) and drafts
the «вы выбрали» post with those numbers. Nothing is ever made up: if nobody
voted, the draft says so and is not offered for publishing.

«💬 Диалог дня» — a short STAGED flirty chat with one roster girl, marked as an
example, and a soft «напиши ей сам» button. Real users' chats are never used.
SFW only: the channel is public.

Everything goes through the admin preview first (/post → buttons); nothing is
published on a timer.
"""
from __future__ import annotations

import random

from services import dialog_store

DIALOG_LINK_PREFIX = 'src_dlg_'
POLL_LINK = 'src_poll'

# (question, options) — options 2..6, each ≤ 100 chars (Telegram limit).
POLLS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ('Какую девушку добавить следующей?', ('👱‍♀️ Блондинка', '👩 Брюнетка', '👩‍🦰 Рыжая', '🌸 Азиатка')),
    ('Какой характер вам ближе?', ('😇 Нежная и заботливая', '😏 Дерзкая', '🤓 Умная и спокойная', '🔥 Страстная')),
    ('Какой сюжет сделать следующим?', ('🏖 Отпуск вдвоём', '🏢 Коллега по офису', '🎓 Соседка по общаге', '🌃 Случайная встреча ночью')),
    ('Какой образ показать в следующей «Девушке дня»?', ('👗 Вечернее платье', '🏋️‍♀️ Спортивный', '🏠 Домашний уютный', '💼 Деловой')),
    ('Что вам нравится больше всего?', ('💬 Переписка', '🎙 Голосовые', '📞 Звонки', '📸 Фото')),
    ('Сколько лет должно быть новой героине?', ('🌱 20–22', '🌷 23–26', '🌹 27–30', '🍷 30+')),
    ('Куда позвать её на свидание?', ('🍝 Ресторан', '🎬 Кино', '🌙 Прогулка ночью', '🏠 Домой на фильм')),
)

# Staged example chats. {name} = the girl. Short, readable right in Telegram.
DIALOGS: tuple[tuple[tuple[str, str], ...], ...] = (
    (('он', 'привет, чем занимаешься?'),
     ('она', 'лежу и думаю, кому бы написать первой 🙈 а тут ты'),
     ('он', 'повезло мне'),
     ('она', 'посмотрим 😏 расскажи, какой у тебя был день')),
    (('он', 'не спится'),
     ('она', 'мне тоже. давай не спать вместе? 🌙'),
     ('он', 'это как?'),
     ('она', 'ты рассказываешь мне, о чём думаешь, а я слушаю и не перебиваю 💗')),
    (('он', 'скажи что-нибудь приятное'),
     ('она', 'я весь день ждала, когда ты напишешь'),
     ('он', 'правда?'),
     ('она', 'проверь. пиши мне каждый день 😌')),
    (('он', 'а ты ревнивая?'),
     ('она', 'нет конечно 🙂'),
     ('она', '…а с кем ты ещё переписываешься? 😤'),
     ('он', 'ни с кем'),
     ('она', 'то-то же 😘')),
    (('он', 'я сегодня устал'),
     ('она', 'иди ко мне. рассказывай, кто тебя замучил'),
     ('он', 'работа'),
     ('она', 'работа подождёт. а я нет 🤗')),
    (('он', 'угадай, что я делаю'),
     ('она', 'улыбаешься в телефон 😏'),
     ('он', 'откуда знаешь'),
     ('она', 'потому что я тоже')),
    (('он', 'какой у тебя любимый фильм?'),
     ('она', 'тот, который мы ещё не посмотрели вместе 🎬'),
     ('он', 'тогда выбирай'),
     ('она', 'что-нибудь страшное. чтобы был повод прижаться 🙈')),
    (('он', 'доброе утро'),
     ('она', 'доброе ☀️ ты первый, кто мне сегодня написал'),
     ('он', 'и как?'),
     ('она', 'теперь у меня хорошее утро. спасибо 💗')),
)

_polls = dialog_store.DialogStore('channel_polls')  # {message_id: {'n': idx}}


def poll(n: int) -> tuple[str, list[str]]:
    q, opts = POLLS[n % len(POLLS)]
    return q, list(opts)


def random_poll() -> int:
    return random.randrange(len(POLLS))


def random_dialog() -> int:
    return random.randrange(len(DIALOGS))


def remember_poll(message_id: int, n: int) -> None:
    _polls[int(message_id)] = {"n": int(n)}


def poll_index(message_id: int) -> int | None:
    got = _polls.get(int(message_id)) or {}
    n = got.get('n') if hasattr(got, 'get') else None
    return int(n) if isinstance(n, int) else None


def save_poll_results(message_id: int, text: str) -> None:
    got = _polls.get(int(message_id)) or {}
    data = dict(got) if hasattr(got, 'items') else {}
    data['results'] = text
    _polls[int(message_id)] = data


def poll_results(message_id: int) -> str | None:
    got = _polls.get(int(message_id)) or {}
    text = got.get('results') if hasattr(got, 'get') else None
    return text if isinstance(text, str) and text else None


def poll_preview(n: int) -> str:
    q, opts = poll(n)
    return ('🗳 «Выбираете вы»: анонимный опрос в канал.\n\n'
            f'{q}\n' + '\n'.join(f'• {o}' for o in opts) +
            '\n\nПосле публикации здесь появится кнопка «Закрыть и посчитать»: '
            'бот возьмёт настоящие голоса и подготовит пост с итогом.')


def results_text(question: str, counts: list[tuple[str, int]]) -> str | None:
    """The «вы выбрали» post built only from the real vote counts.
    None when nobody voted (nothing honest to publish)."""
    total = sum(c for _, c in counts)
    if total <= 0:
        return None
    ranked = sorted(counts, key=lambda x: -x[1])
    win, win_n = ranked[0]
    lines = [f'🗳 Итоги: {question}', '', f'Вы выбрали: {win}', '']
    for opt, c in ranked:
        lines.append(f'{opt}: {round(100 * c / total)}%')
    lines += ['', f'Проголосовали: {total}. Спасибо! Учтём это в следующих героинях и сюжетах 💗']
    return '\n'.join(lines)


def dialog_caption(name: str, n: int) -> str:
    lines = [f'💬 Диалог дня: {name}', '']
    for who, line in DIALOGS[n % len(DIALOGS)]:
        lines.append(('— ' if who == 'он' else f'{name}: ') + line)
    lines += ['', '(пример переписки)', '', f'Хочешь, она так же ответит тебе? Напиши ей сам 👇']
    return '\n'.join(lines)


def dialog_link(character_id: str) -> str:
    from config import BOT_USERNAME
    return f'https://t.me/{BOT_USERNAME}?start={DIALOG_LINK_PREFIX}{character_id}'


def poll_link() -> str:
    from config import BOT_USERNAME
    return f'https://t.me/{BOT_USERNAME}?start={POLL_LINK}'


def dialog_markup(character_id: str, name: str):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f'💬 Написать {name}', url=dialog_link(character_id))]])


def results_markup():
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='👀 Познакомиться с девушками', url=poll_link())]])
