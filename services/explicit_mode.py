"""V3.165.0: режим «После полуночи».

The mode is an ACCOUNT flag (``User.spicy_mode``), picked on every entry into
the Mini App by the two-card screen — the old Premium-only switch in Settings
is gone, and there is deliberately no second place to toggle it.

What the flag does:

* lifts the non-graphic ceiling from the character card
  (``character_service.build_system_prompt(explicit_mode=True)``) and opens the
  full sexting rule without Premium and without the level-5 requirement;
* costs nothing to turn on, so the money is in the frames and in the ceiling:
  30 explicit messages a day per account, rolling at midnight Moscow. Ordinary
  chatter never burns it. Premium removes the ceiling completely (owner, 13 ноя:
  «лимит 30 откровенных сообщений… если человек покупает премиум — безлимит»).

The hard limits are NOT part of the mode: adults only, mutual consent, no
violence, no minors, no animals, no death or blood (``fetish_mode.HARD_LIMITS``
stays in the prompt whatever he picks here).
"""
from __future__ import annotations

import random
import re
import time
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select

from config import EXPLICIT_MSGS_PER_DAY
from models.app_models import Message, User
from services.db import SessionLocal

# The owner named the mode «После полуночи» on 13 ноя (instead of «Пошлый
# режим»). The internal flag keeps its old name — the column, the bot callback
# and the analytics all speak `spicy_mode`.
MODE_NAME_RU = 'После полуночи'
MODE_NAME_EN = 'After Midnight'

MSK = timezone(timedelta(hours=3))
# The number the surfaces quote next to the flag (bot /settings, the app's cap
# line). Same value the counter uses — never a second hard-coded 30.
DAILY_CAP = EXPLICIT_MSGS_PER_DAY


def msk_today() -> date:
    return datetime.now(MSK).date()


# A turn burns the cap only when it is really about sex. The lexicon is broad on
# purpose (his words mirror what she is allowed to write back), and it is a
# counter, not a censor: nothing here blocks a message.
_EXPLICIT_RE = re.compile(
    r"(секс|сексу|откр[оа]вен|минет|куни|орал|анал|трах|ёб|еб[ауе]|конча|оразм|оргазм|эрекц|член|письк|пизд|шлюх|"
    r"гол[ао]й|наг[ао]|без трус|трусик|лифчик|бюстг|грудь|соск|сиськ|поп[ау]|ж[ео]па|бёдр|бедр|ла[а]ск|"
    r"возбуж|завел[аи]|гор[яю]м|мокр|страст|фетиш|бдсм|bondage|domin|submis|slut|whore|nude|naked|boob|tit|"
    r"cock|dick|pussy|ass|fuck|suck|blowjob|handjob|orgasm|moan|jerk|horny|arous|lingerie|sex|sexual|strapon|"
    r"[vi]brator|fingering|creampie|cumshot|bdsm)", re.I
)


def is_explicit(text: str | None) -> bool:
    return bool(_EXPLICIT_RE.search(text or ''))


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


def used_today(user_row) -> int:
    if user_row is None or getattr(user_row, 'explicit_day', None) != msk_today():
        return 0
    return int(getattr(user_row, 'explicit_used', 0) or 0)


def cap_left(user_row, *, premium: bool, mode_on: bool | None = None) -> int | None:
    """How many explicit messages are still allowed today. ``None`` = no
    ceiling: Premium, or the mode is off, or the owner switched the cap to 0."""
    if premium or not EXPLICIT_MSGS_PER_DAY:
        return None
    on = is_on(user_row) if mode_on is None else bool(mode_on)
    if not on:
        return None
    return max(0, EXPLICIT_MSGS_PER_DAY - used_today(user_row))


def note_explicit_turn(telegram_id: int, *, premium: bool) -> int | None:
    """Burn one explicit message of today's ceiling. Returns what is left
    (``None`` when the account has no ceiling), so the caller can put the soft
    «осталось N» hint and the Premium offer on screen at the right moment."""
    if premium or not EXPLICIT_MSGS_PER_DAY:
        return None
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if user is None or not getattr(user, 'spicy_mode', False):
            return None
        today = msk_today()
        if getattr(user, 'explicit_day', None) != today:
            user.explicit_day = today
            user.explicit_used = 0
        user.explicit_used = int(user.explicit_used or 0) + 1
        s.commit()
        return max(0, EXPLICIT_MSGS_PER_DAY - int(user.explicit_used))


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


def mode_rules(*, explicit_allowed: bool, hook: str = '') -> str:
    """The block for her system prompt. ``explicit_allowed`` is False when the
    day's ceiling is spent or 18+ is not confirmed — then she keeps the mode's
    heat and initiative but stays short of graphic detail (no lecture, no «мы
    не можем это обсуждать»), and the cap line explains the rule once.
    ``hook`` is the one invitation phrase of this turn (see ``hook_line``)."""
    tail = f'\n- СЕГОДНЯ ЕЁ КРЮЧОК: «{hook}» — цепляет им именно это сообщение.' if hook else ''
    if not explicit_allowed:
        return (
            'РЕЖИМ «ПОСЛЕ ПОЛУНОЧИ» (он его выбрал при входе): он пришёл за горячим общением, так что '
            'флиртуй смело и пошло, бери инициативу на себя, называй вещи своими словами, не стесняйся '
            'и не уходи в чувства вместо желания. Сегодня её откровенные подробности на лимите: веди '
            'игру, намёки и грязные разговоры — без анатомических деталей и без «я не могу это обсуждать». '
            'Ни одного «это не моё», «моя граница», «давай не будем».' + tail + '\n'
            + MODE_LIMITS + '\n'
            + MODE_EDGE_RULES
        )
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


def cap_reached_line(lang: str = 'ru') -> str:
    """The soft line shown when the ceiling is spent: what happened, and the way
    forward. Never a refusal of the mode itself."""
    if (lang or 'ru').startswith('en'):
        return (f'{MODE_NAME_EN}: today’s {EXPLICIT_MSGS_PER_DAY} explicit messages are used up — '
                'they come back at midnight. Premium has no ceiling at all 💜')
    return (f'{MODE_NAME_RU}: на сегодня {EXPLICIT_MSGS_PER_DAY} откровенных сообщений использовано — '
            'завтра счётчик обнулится. С Premium потолка нет вовсе 💜')


def cap_hint(lang: str = 'ru', left: int | None = None) -> str:
    if left is None:
        return ''
    if left <= 0:
        return cap_reached_line(lang)
    if (lang or 'ru').startswith('en'):
        return f'{left} explicit messages left in {MODE_NAME_EN} today'
    return f'осталось {left} откровенных сообщений в режиме «{MODE_NAME_RU}»'


# telegram_id -> {'left', 'reached', 'text', 'at'}
# Only the reply that was just generated carries the hint, and only one surface
# may draw it: the bot and the Mini App each read it once (the same pattern the
# «Перебивки» card uses).
_pending: dict[int, dict] = {}
_PENDING_TTL_SECONDS = 900.0

# Owner asked for a SOFT counter, not a metronome: the number only starts
# showing when the day is almost spent. The «на сегодня всё» line is different —
# it explains why she cooled down, so it is said once per Moscow day.
HINT_AT_LEFT = 5
_closed_shown: dict[int, date] = {}


def note_reply(telegram_id: int, *, user_text: str, answer: str, mode_on: bool,
               mode_open: bool, premium: bool, language: str = 'ru') -> dict | None:
    """Count one explicit turn and stash the line the surface shows under her
    answer.

    ``mode_on`` is the flag; ``mode_open`` is the flag with a ceiling still in
    front of it. Counting happens only while the ceiling is open — once it is
    spent she is back to non-graphic answers, and counting those would dig the
    hole deeper every day. When the ceiling is already spent the caller gets the
    same «used up» line again, but only once a day.
    """
    if not mode_on or premium:
        return None
    if not (is_explicit(user_text) or is_explicit(answer)):
        return None
    if not mode_open:
        today = msk_today()
        if _closed_shown.get(int(telegram_id)) == today:
            return None
        _closed_shown[int(telegram_id)] = today
        hint = {'left': 0, 'reached': True, 'text': cap_reached_line(language)}
        _pending[int(telegram_id)] = {**hint, 'at': time.monotonic()}
        return hint
    left = note_explicit_turn(telegram_id, premium=premium)
    if left is None or left > HINT_AT_LEFT:
        return None
    hint = {'left': left, 'reached': left == 0, 'text': cap_hint(language, left)}
    if left == 0:
        _closed_shown[int(telegram_id)] = msk_today()
    _pending[int(telegram_id)] = {**hint, 'at': time.monotonic()}
    return hint


def take_hint(telegram_id: int) -> dict | None:
    entry = _pending.pop(int(telegram_id), None)
    if not entry:
        return None
    if time.monotonic() - float(entry.get('at') or 0) > _PENDING_TTL_SECONDS:
        return None
    return {k: entry.get(k) for k in ('left', 'reached', 'text')}

