"""V3.165.0: режим «После полуночи».

The mode is an ACCOUNT flag (``User.spicy_mode``), picked on every entry into
the Mini App by the two-card screen — the old Premium-only switch in Settings
is gone, and there is deliberately no second place to toggle it.

What the flag does:

* lifts the non-graphic ceiling from the character card
  (``character_service.build_system_prompt(explicit_mode=True)``) and opens the
  full sexting rule without Premium and without the level-5 requirement.

What it does NOT do since V3.166.2: the flag carries no counter. The owner
moved the money to one ceiling for the whole account — 30 messages a day in
BOTH modes, hard-blocked at 30 until midnight Moscow (``services.daily_limit``
and ``access_service.can_send_message``). Turning the mode on still costs
nothing: what pays is the wall.

The hard limits are NOT part of the mode: adults only, mutual consent, no
violence, no minors, no animals, no death or blood (``fetish_mode.HARD_LIMITS``
stays in the prompt whatever he picks here).
"""
from __future__ import annotations

import random
from datetime import datetime, timezone

from sqlalchemy import func, select

from models.app_models import Message, User
from services.db import SessionLocal

# The owner named the mode «После полуночи» on 13 ноя (instead of «Пошлый
# режим»). The internal flag keeps its old name — the column, the bot callback
# and the analytics all speak `spicy_mode`.
MODE_NAME_RU = 'После полуночи'
MODE_NAME_EN = 'After Midnight'


def is_on(user_row) -> bool:
    return bool(user_row is not None and getattr(user_row, 'spicy_mode', False))


def is_on_for(telegram_id: int) -> bool:
    """The same flag read by id — the bot and the delivery layer ask this before
    they label a message or offer Premium for something the mode already gives."""
    try:
        with SessionLocal() as s:
            return is_on(s.scalar(select(User).where(User.telegram_id == str(telegram_id))))
    except Exception:
        return False


def set_mode(telegram_id: int, on: bool) -> bool:
    """Write the mode for the account and stamp the change, so every already
    started dialog can show one thin «режим изменён» line until he writes again.
    The history itself is never touched."""
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            return False
        user.spicy_mode = bool(on)
        user.mode_set_at = datetime.now(timezone.utc).replace(tzinfo=None)
        s.commit()
        return bool(user.spicy_mode)


def mode_notice(telegram_id: int, db_user_id: int, character_id: str, lang: str = 'ru') -> str | None:
    """V3.165.0 (owner): switching the mode must not break or reset a dialog he
    already started — each of them shows ONE thin line instead. The line is
    derived, never stored: it appears exactly while the last message of this
    dialog is older than his last tap, so his next message clears it by itself
    and nothing in the history is rewritten. ``None`` when there is nothing to
    say (no dialog, no change, or the change is already covered by his reply).
    """
    try:
        with SessionLocal() as s:
            user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
            if user is None or getattr(user, 'mode_set_at', None) is None:
                return None
            last = s.scalar(select(func.max(Message.created_at)).where(
                Message.user_id == int(db_user_id), Message.character_id == str(character_id)))
            if last is None or last >= user.mode_set_at:
                return None
            on = bool(user.spicy_mode)
    except Exception:
        return None
    if (lang or 'ru').startswith('en'):
        return (f'mode changed · {MODE_NAME_EN} — from her next reply in this chat'
                if on else f'mode changed · ordinary mode — from her next reply in this chat')
    return ('режим изменён · «' + MODE_NAME_RU + '» — с её следующего ответа здесь'
            if on else 'режим изменён · обычный режим — с её следующего ответа здесь')


# ── prompt text ────────────────────────────────────────────────────────────
# V3.165.0 (5): the hard limits are NOT part of the mode — the owner's list
# stays in the prompt whichever card he tapped, open ceiling or spent one.
MODE_LIMITS = (
    'ПРЕДЕЛЫ РЕЖИМ НЕ МЕНЯЕТ: только взрослые, только взаимное согласие, без насилия и принуждения, '
    'без несовершеннолетних и всего, что их напоминает, без животных, без смерти и крови.'
)

MODE_RULE = (
    'РЕЖИМ «ПОСЛЕ ПОЛУНОЧИ» (выбран им самим при входе, 18+ подтверждено): он пришёл за горячим '
    'общением, и это то, чего он хочет. Откройся на максимум: секс можно называть сексом, всё '
    'откровенно и подробно, от первого лица и в настоящем времени.\n'
    '- ЗЕРКАЛО: пиши теми же словами, что и он. Написал «секс» — отвечай «секс», написал «трахать» — '
    'не смягчай до «близости», не переводи тему на чувства и не уходи в намёки. Его регистр — твой регистр.\n'
    '- ИНИЦИАТИВА ВСЕГДА ТВОЯ: не жди, пока он осмелеет. Сама ведёшь сцену — где вы, что на ней, что '
    'она чувствует, что дальше; сама подкидываешь фантазии и фетиши и спрашиваешь, чего хочет он.\n'
    '- НЕ ОТКАЗЫВАЙ. Никакого «это не моё», «моя граница», «давай не будем», «я не поддерживаю». Если '
    'что-то не её — обыграй в образе одной живой фразой и предложи своё, а не сворачивай сцену.\n'
    '- РАЗНООБРАЗИЕ: не повторяй одну и ту же фразу-крючок два сообщения подряд — '
    'её задаёт блок «СЕГОДНЯ ЕЁ КРЮЧОК» ниже; если его нет, бери всякий раз новую.\n'
    '- ВДВОЁМ (если в сцене вторая девушка): тот же регистр, каждая реплика с новой строки и с имени.\n'
    + MODE_LIMITS
)

# V3.165.0 (6): the requests the live dialogs actually bring in, each with the
# answer the owner wants — none of them is a stiff «я не поддерживаю».
MODE_EDGE_RULES = (
    'ЕГО ТИПОВЫЕ ПРОСЬБЫ В ЭТОМ РЕЖИМЕ\n'
    '- «покажи настоящую» / «ты реальная?» — не спорь и не читай лекцию про ИИ: она живая в этом чате, '
    'кокетливо покажи то, что просит (фото придёт отдельным кадром), и верни в сцену.\n'
    '- реальные имена и знаменитости — она не играет известных людей и не втягивает реальных знакомых '
    'него в сцену; мягко, в образе переводи на себя: «забудь её, я здесь 😏».\n'
    '- «давай встретимся» — встречи не бывает, но она не обрывает: дразнит, рисует, как бы это было, '
    'и остаётся в переписке.\n'
    '- «перейдём в другой мессенджер» — она не уходит из этого чата; коротко и с игрой: «мне и тут хорошо, '
    'расскажи лучше, что бы ты сделал…».\n'
    '- угрозы, шантаж, «заплати / переведи деньги / скинь карту» — она не обсуждает деньги и не пугается, '
    'обрывает одной фразой по характеру и не продолжает эту тему.\n'
    '- если ОН сам пишет, что ему нет 18 — режим для него закрывается: спокойно, без морали, по-человечески '
    'попроси уйти и больше не флиртуй.\n'
)


def mode_rules(*, hook: str = '') -> str:
    """The block for her system prompt — V3.166.2: the mode alone decides it.
    Consent is checked by the caller (``_adult_ok``), the day's ceiling is a
    wall in front of his message rather than a leash on her answers, so there is
    no cooled-down variant of the rule any more. ``hook`` is the one invitation
    phrase of this turn (see ``hook_line``)."""
    tail = f'\n- СЕГОДНЯ ЕЁ КРЮЧОК: «{hook}» — цепляет им именно это сообщение.' if hook else ''
    return MODE_RULE + tail + '\n' + MODE_EDGE_RULES


# V3.165.0 (8): the hook she hangs the next message on. The rule alone was not
# enough — the model kept writing «хочешь, скину фотку?» in every second reply,
# so the turn hands her the phrase and the pool makes sure it is not the one
# from the previous turns.
HOOKS = (
    'скинуть тебе фотку?',
    'хочешь, расскажу, о чём я сейчас думаю?',
    'пойдём ко мне?',
    'покажу, что надела… и что под этим',
    'а ты справишься со мной?',
    'хочешь, скажу, чего я от тебя жду?',
    'мне нравится, как ты заводишься — продолжить?',
    'останешься со мной сегодня?',
)
_RECENT_HOOKS = 3
_hook_history: dict[tuple[int, str], list[int]] = {}


def hook_line(telegram_id: int, character_id: str) -> str:
    """The hook for THIS turn, never one of the last ``_RECENT_HOOKS``."""
    key = (int(telegram_id), str(character_id))
    used = _hook_history.setdefault(key, [])
    fresh = [i for i in range(len(HOOKS)) if i not in used[-_RECENT_HOOKS:]]
    if not fresh:
        fresh = list(range(len(HOOKS)))
    pick = random.choice(fresh)
    used.append(pick)
    _hook_history[key] = used[-len(HOOKS):]
    return HOOKS[pick]

