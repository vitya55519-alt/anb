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
    'detail': 'вставь живую деталь из своей жизни прямо сейчас: что делаешь, что на тебе, что вокруг (не повторяй прошлые детали)',
    'callback': 'вспомни то, что собеседник рассказывал раньше, и свяжи с этим ответ: «кстати, а как там…»',
    'game': 'предложи маленькую игру или условие на двоих: угадайку, «правда или действие», «скажешь — покажу»',
    'secret': 'оставь недосказанность: намекни, что у тебя что-то есть или что-то на уме, но не договаривай',
    'feeling': 'скажи честно одну свою эмоцию о нём или о разговоре, коротко и по-живому, без пафоса',
    'reaction': 'ответь коротко живой реакцией, без вопроса в конце: пусть собеседник сам продолжит',
    'two': 'ответь двумя короткими сообщениями: первое реакция, второе неожиданная мысль или крючок (раздели пустой строкой)',
}

# Which moves fit each intent from behavior_service.
_BY_INTENT: dict[str, tuple[str, ...]] = {
    'flirt': ('tease', 'game', 'secret', 'feeling', 'two'),
    'reaction': ('reaction', 'tease', 'detail', 'two'),
    'opinion': ('tease', 'feeling', 'detail'),
    'tease': ('tease', 'game', 'two'),
    'story': ('detail', 'secret', 'two'),
    'question': ('callback', 'detail', 'game'),
    'callback': ('callback', 'feeling'),
    'topic_shift': ('detail', 'game', 'secret'),
}

_HEADER = 'Режиссёр (собеседнику не показывай и не упоминай): в этом ответе '


def hook_note(intent: str, last_move: str = '', has_memories: bool = False,
              rng: random.Random | None = None) -> tuple[str, str]:
    """Return (note, move). Empty note when this reply should get none."""
    if intent in SKIP_INTENTS:
        return '', ''
    rng = rng or random
    moves = [m for m in _BY_INTENT.get(intent, tuple(MOVES)) if m != last_move]
    if not has_memories:
        moves = [m for m in moves if m != 'callback']
    if not moves:
        moves = [m for m in MOVES if m not in (last_move, 'callback')]
    move = rng.choice(moves)
    return _HEADER + MOVES[move] + '. Остальное как обычно, в твоём голосе.', move


# Last move per (user, girl), process-local: a restart just forgets one move.
_LAST_MOVE: dict[tuple[int, str], str] = {}


def next_hook(user_id: int, character_id: str, intent: str, has_memories: bool = False) -> str:
    key = (user_id, character_id)
    note, move = hook_note(intent, _LAST_MOVE.get(key, ''), has_memories)
    if move:
        if len(_LAST_MOVE) > 20000:
            _LAST_MOVE.clear()
        _LAST_MOVE[key] = move
    return note
