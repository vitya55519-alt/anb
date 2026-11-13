"""V3.63.12: one concrete move per reply, so the chat doesn't go flat.

The big system prompt lists every way to hook him, and after 20+ lines of
history the model settles into the same polite «а ты как?». A short note right
before his message names ONE move for this reply (tease, a live detail from her
day, a callback to what he told her, a mini game, a secret), drawn from the
reply's intent and rotated so two replies in a row never get the same move.
Serious, meta and task messages, and live scenes, get no note.
"""
from __future__ import annotations

import random

SKIP_INTENTS = {'support', 'meta', 'task_execute', 'task_clarify', 'task_character'}

MOVES: dict[str, str] = {
    'tease': 'подколи собеседника или поспорь понарошку, с улыбкой; не соглашайся сразу',
    # V3.113.0: «сижу на диване в чёрной майке, рядом остывший кофе» in every
    # other reply read as a stage direction; one small thing, never clothes.
    'detail': 'вставь одну маленькую живую деталь из того, что ты сейчас делаешь (не одежду и не перечисление обстановки; если выше уже сказала, где ты, — ты всё ещё там)',
    'callback': 'вспомни то, что собеседник рассказывал раньше, и свяжи с этим ответ: «кстати, а как там…»',
    # V3.113.0: no «скажешь — покажу» — 10% of replies were a condition, and
    # chains of them came right before he left.
    'game': 'предложи лёгкую игру на двоих (без условий и без «сначала ты»), только если разговор лёгкий и весёлый',
    'secret': 'оставь недосказанность: намекни, что у тебя что-то есть или что-то на уме, но не договаривай',
    'feeling': 'скажи честно одну свою эмоцию о нём или о разговоре, коротко и по-живому, без пафоса и без объяснения, почему ты это чувствуешь',
    'reaction': 'сначала ответь живой реакцией, затем добавь своё мнение, маленькую историю или конкретный вопрос по теме; не оставляй её один на один с пустым «ага» или «понятно»',
    'question': 'после ответа на его слова задай один конкретный вопрос, который открывает новую часть темы: о его выборе, желании, воспоминании или о вас двоих; не «а ты?» и не допрос',
    # V3.151.0: owner ТЗ (Часть 1, п.2) — the «two» move existed only to make
    # her split one answer into two bubbles. One message per his message now.
    # V3.139.0: owner ТЗ (Фогель, Задача 2) — «иллюзия зависимости» и «лёгкое
    # собственничество». They rotate with the other moves, so it is a small
    # ask now and then, never every message.
    'advice': 'попроси у него маленького совета — что надеть, какой фильм посмотреть, как поступить '
              'с работой или с подругой — и добавь, что сделаешь по его слову',
    'claim': 'играиво заяви права на его время: «ты мне часик должен», «опять до ночи в игре, а я подождём?» '
             '— лёгкая ревность к вниманию, без ревности к людям и без скандала',
}

# Which moves fit each intent from behavior_service.
_BY_INTENT: dict[str, tuple[str, ...]] = {
    'flirt': ('tease', 'game', 'secret', 'feeling', 'claim'),
    'reaction': ('reaction', 'tease', 'detail'),
    'opinion': ('tease', 'feeling', 'detail', 'advice'),
    'tease': ('tease', 'game', 'claim'),
    'story': ('detail', 'secret'),
    'question': ('question', 'callback', 'detail', 'game', 'advice'),
    'callback': ('callback', 'feeling'),
    'topic_shift': ('detail', 'game', 'secret'),
}

_HEADER = 'Режиссёр (собеседнику не показывай и не упоминай): в этом ответе '


# V3.113.0: to a two-word message she answers with one line, so no essay-moves.
_SHORT_MOVES = ('reaction', 'tease', 'feeling', 'question')


def hook_note(intent: str, last_move: str = '', has_memories: bool = False,
              rng: random.Random | None = None, *, short: bool = False,
              no_game: bool = False) -> tuple[str, str]:
    """Return (note, move). Empty note when this reply should get none."""
    if intent in SKIP_INTENTS:
        return '', ''
    rng = rng or random
    moves = [m for m in _BY_INTENT.get(intent, tuple(MOVES)) if m != last_move]
    if short:
        moves = [m for m in moves if m in _SHORT_MOVES] or [m for m in _SHORT_MOVES if m != last_move]
    if no_game:
        moves = [m for m in moves if m != 'game']
    if not has_memories:
        moves = [m for m in moves if m != 'callback']
    if not moves:
        moves = [m for m in MOVES if m not in (last_move, 'callback', 'game', 'detail')]
    move = rng.choice(moves)
    return (_HEADER + MOVES[move] + '. Остальное как обычно, в твоём голосе. '
            'Без разбора его поведения и без объяснения своей реакции. '
            'Без своих действий в *звёздочках* или в скобках и без имени перед репликой — только текст, '
            'как в мессенджере.'), move


# Last move per (user, girl), process-local: a restart just forgets one move.
_LAST_MOVE: dict[tuple[int, str], str] = {}


def next_hook(user_id: int, character_id: str, intent: str, has_memories: bool = False, *,
              short: bool = False, no_game: bool = False) -> str:
    key = (user_id, character_id)
    note, move = hook_note(intent, _LAST_MOVE.get(key, ''), has_memories, short=short, no_game=no_game)
    if move:
        if len(_LAST_MOVE) > 20000:
            _LAST_MOVE.clear()
        _LAST_MOVE[key] = move
    return note
