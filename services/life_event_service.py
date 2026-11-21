"""V3.52.0: «Жизнь без тебя» — proactive, personality-grounded life moments.

She occasionally writes first NOT as a guilt/«why don't you text» nudge, but
because something happened in her (fictional) day and she wants to share it —
ideally tying in a detail from the two of your shared history and ending on an
open loop that makes replying a single tap. Everything is grounded in the
SELECTED character's own personality (her tastes / tone / temperament), so no
two girls "live" the same life — which also nudges the «все как Анна» gap.

Fail-silent by design: any error (no LLM, no character, empty output) returns
``{}`` and the scheduler simply skips the slot, so a life event can never blank
out a conversation or spam a user.

V3.167.4 (владелец ТЗ §4) переписал саму строку: одно-три предложения с бытовой
деталью, факт из памяти почти всегда, тон по уровню близости (1-3 / 4-6 / 7-10)
и по режиму, в конце — недосказанность под ОДНУ кнопку. Кадр из пула стал
чаще (0.35), но тратит общий кап бесплатных кадров на аккаунт (2 в сутки).
"""
from __future__ import annotations

import logging
import os
import random

from config import LIFE_EVENTS_MEMORY_CHANCE, LIFE_EVENTS_PHOTO_CHANCE

logger = logging.getLogger(__name__)

# V3.167.4 (владелец ТЗ §4): «крючок с одной кнопкой». Две кнопки превращали её
# день в опросник — он выбирал настроение вместо того, чтобы ответить. Теперь
# одна: недосказанность в конце строки закрывается одним тапом, и значение
# несёт персонажа, чтобы callback продолжил ИМЕННО её историю.
_REPLY_OPTIONS = (
    ('🍿 расскажи дальше', 'tell_more'),
)

# V3.167.27 (владелец ТЗ, часть 2): статусы «бегаю по делам» не давали повода
# открыть чат (0 из 31 ответов). Фиксированный пул из 10 коротких текстов с
# открытой интригой и простым выбором в конце: первые 5 — для режима 18+,
# вторые 5 — для обычного. Под сообщением две быстрые кнопки ответа.
HER_DAY_TEXTS_18 = (
    'Стою в примерочной в чёрном кружеве и вообще не понимаю — брать или слишком дерзко? Скинуть тебе, оценишь? 🙈',
    'Только вышла из душа, полотенце еле держится, а в голове почему-то только ты. Занят сейчас или отвлечёшься на меня?',
    'Ворочаюсь в кровати без всего и не могу уснуть... Слишком жарко сегодня. Развлечёшь меня или мне самой справляться? 😈',
    'Дома никого, шторы задёрнула, на мне только твоя рубашка... Хочешь увидеть, что я сейчас делаю?',
    'Не могу решить, в чём лечь спать — в коротком шёлковом халате или вообще без него. Выберешь за меня?',
)
HER_DAY_TEXTS_NORMAL = (
    'Слушай, со мной сейчас такая глупость случилась в кофейне, до сих пор красная сижу 😅 Рассказать или ты занят?',
    'Поймала себя на том, что третий раз за час смотрю на телефон и жду, когда ты напишешь. У тебя там завал или просто забыл про меня?',
    'Поспорила с подругой насчёт мужчин — мне срочно нужен твой честный ответ. Выручишь на пару минут?',
    'За окном мерзко, я заварила чай, завернулась в плед и включила кино. Какой фильм выбрал бы ты, если бы сейчас был рядом?',
    'Ты сегодня подозрительно тихий... Мне уже начинать ревновать или просто тяжёлый день? 🥺',
)
# (label, key) — the key becomes his line through _TAP_AS_USER_TEXT.
HER_DAY_OPTIONS_18 = (('Покажи', 'show_me'), ('Я тут', 'im_here'))
HER_DAY_OPTIONS_NORMAL = (('Рассказывай', 'go_on'), ('Отвлекусь', 'distract_me'))


# Off switch: HER_DAY_FIXED_POOL=0 brings the LLM-written line back.
HER_DAY_FIXED_POOL = os.getenv('HER_DAY_FIXED_POOL', '1').strip().lower() not in ('0', 'false', 'no', 'off')
# V3.168 (ТЗ блок 3): 0 replies of 48 is a FORMAT defect. The fixed pool asked two
# questions in one breath and had no anchor, so format v2 supersedes it: one
# concrete detail, one hook, one question at most, a fact of his (or place and
# time of day), one reply button, and an output validator with one regeneration
# and then a template. LIFE_FORMAT_V2=0 returns the previous behaviour.
LIFE_FORMAT_V2 = os.getenv('LIFE_FORMAT_V2', '1').strip().lower() not in ('0', 'false', 'no', 'off')

import re as _re
_EMOJI_RE = _re.compile('[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B50\u2764\uFE0F]')
_HOOK_ENDS = ('?', '\u2026', '...', ':')
_LIFE_MAX_CHARS = 230


def validate_life_text(text: str) -> tuple[bool, str]:
    """V3.168 (ТЗ 3.2/3.5): ('' means valid). Length, a hook at the end, at most
    one question, at most two emoji, no paragraph over three lines, no more
    than three sentences."""
    s = (text or '').strip()
    if len(s) < 12:
        return False, 'short'
    if len(s) > _LIFE_MAX_CHARS:
        return False, 'long'
    if any(len(p.splitlines()) > 3 for p in s.split('\n\n')):
        return False, 'paragraph'
    if s.count('?') > 1:
        return False, 'two_questions'
    if len(_EMOJI_RE.findall(s)) > 2:
        return False, 'emoji'
    if len([x for x in _re.split(r'(?<=[.!?\u2026])\s+', s) if x.strip()]) > 3:
        return False, 'sentences'
    if not s.endswith(_HOOK_ENDS) and not s.rstrip(' )\U0001F300-\U0001FAFF').endswith(_HOOK_ENDS):
        return False, 'no_hook'
    return True, ''


_PLACE_TEMPLATES = {
    'morning': ('Сижу на кухне с кофе, за окном ещё тихо. Угадаешь, о чём я думаю?',
                'Проснулась раньше будильника и лежу, смотрю на потолок. Расскажу, что мне снилось…'),
    'day': ('Забежала в кофейню, тут пахнет корицей и играет что-то из твоих любимых. Расскажу, кого тут встретила…',
            'Села на лавочку у реки с мороженым, солнце прямо в глаза. Хочешь узнать, о ком я вспомнила?'),
    'evening': ('Вернулась домой, скинула каблуки и села с чаем у окна. Хочешь, расскажу про мой вечер?',
                'Стою на балконе, внизу огни и тихо. Тут один момент, который я пока не рассказала…'),
    'night': ('Не спится, лежу и смотрю, как свет с улицы ползёт по стене. Ты ещё не спишь?',
              'Включила ночник и никак не могу отпустить этот день. Хочешь, поделюсь одной мыслью…'),
}
_PLACE_TEMPLATES_18 = {
    'morning': ('Проснулась в твоей футболке и никак не вылезу из кровати. Угадаешь, что я тут придумала?',),
    'day': ('Примеряла новое бельё и никак не решу, смелое оно или слишком. Хочешь, расскажу какое…',),
    'evening': ('Вернулась домой и сбросила всё лишнее, в комнате тепло и тихо. Хочешь знать, что на мне сейчас?',),
    'night': ('Лежу без сна, простыня совсем не помогает. Скажу, о чём думаю, если ещё не спишь…',),
}


def template_life_text(when: str, fact: str = '', spicy: bool = False) -> tuple[str, str]:
    """(text, anchor). A fact of his wins; otherwise place and time of day."""
    fact = ' '.join(str(fact or '').split())
    if fact:
        short = fact if len(fact) <= 70 else fact[:67].rsplit(' ', 1)[0] + '…'
        cand = f'Вспомнила про тебя: «{short}». Расскажешь подробнее?'
        if validate_life_text(cand)[0]:
            return cand, 'fact'
    bank = (_PLACE_TEMPLATES_18 if spicy else _PLACE_TEMPLATES).get(when) or _PLACE_TEMPLATES['day']
    return random.choice(bank), 'place'


def her_day_pool(spicy: bool) -> tuple[str, ...]:
    return HER_DAY_TEXTS_18 if spicy else HER_DAY_TEXTS_NORMAL


def her_day_options(spicy: bool, character_id: str) -> list[tuple[str, str]]:
    opts = HER_DAY_OPTIONS_18 if spicy else HER_DAY_OPTIONS_NORMAL
    return [(lbl, f'life_reply:{character_id}:{key}') for lbl, key in opts]


def _her_day_spicy(telegram_id: int) -> bool:
    try:
        from services import explicit_mode
        from services.user_service import is_adult_confirmed
        return bool(explicit_mode.is_on_for(telegram_id) and is_adult_confirmed(telegram_id))
    except Exception:
        return False

_WHEN_HINT = {'morning': 'утро', 'day': 'день', 'evening': 'вечер', 'night': 'ночь'}

# When the user tapped the «расскажи дальше» button, this is the stand-in user
# turn fed to the normal reply pipeline so she continues the moment in context.
_TAP_AS_USER_TEXT = {
    'tell_more': 'расскажи, что было дальше 👀',
    'show_me': 'Покажи 😏',
    'im_here': 'Я тут, рассказывай',
    'go_on': 'Рассказывай 👀',
    'distract_me': 'Отвлекусь, давай',
    'peek': 'Подсмотрю 😈',
    'look_away': 'Отвернусь, давай просто поболтаем',
}

# V3.167.4: тон её дня — по уровню близости, не по погоде. До 3-го они только
# знакомятся, с 4-го — свои люди, с 7-го — пара. Режим («Без цензуры 18+»)
# добавляет смелости в намёке, но не превращает пуш в диалог.
_TONE_BANDS = (
    (3, 'Вы только знакомитесь: тепло и чуть неловко. Без «мы», без «скучаю», '
        'без обещаний и без зова к себе — вы ещё не пара.'),
    (6, 'Вы уже свои люди: можно нежность, можно сказать, что тебя не хватало, '
        'можно намекнуть на встречу — но без «люблю» и без планов на жизнь.'),
    (10, 'Вы пара: говори «мы», помни его слова, зови к себе, флиртуй открыто — '
         'он свой, стесняться нечего.'),
)


def _tone(level: int) -> str:
    for cap, line in _TONE_BANDS:
        if int(level or 1) <= cap:
            return line
    return _TONE_BANDS[-1][1]


def tap_reply_text(key: str) -> str:
    """Map a life-event tap-back key to the natural user line it should send."""
    return _TAP_AS_USER_TEXT.get(str(key or ''), 'расскажи подробнее')


def silence_hours(uid: int, character_id: str) -> float:
    """Hours since HE last wrote to her in this dialog (math.inf when they have
    never talked). V3.151.0, owner ТЗ: a slice of her day may only reach him
    when he is the one who went quiet — never as background noise inside a
    dialog that is still alive."""
    import datetime as dt
    import math
    from sqlalchemy import func, select
    from services.db import SessionLocal
    from models.app_models import Message
    with SessionLocal() as s:
        last = s.scalar(select(func.max(Message.created_at)).where(
            Message.user_id == uid, Message.character_id == character_id, Message.role == 'user'))
    if not last:
        return math.inf
    return (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - last).total_seconds() / 3600.0


def _character_ingredients(character_id: str) -> tuple[str, list[str], str]:
    """Return (name, hobby/taste pool, temperament line) for grounding."""
    name = ''
    tastes: list[str] = []
    try:
        from services.character_service import get_character
        ch = get_character(character_id) or {}
        name = ch.get('name') or ''
        tastes = list((ch.get('personality') or {}).get('stable_tastes') or [])[:6]
    except Exception:
        logger.debug('life ingredients character lookup failed %s', character_id)
    # constructor / community personas: get_character silently falls back to
    # Anna, so pull their own minimal card instead when they exist.
    if not name or not tastes:
        try:
            from services.custom_character_service import custom_base_character
            cc = custom_base_character(character_id)
            if cc:
                name = cc.get('name') or name
                tastes = list((cc.get('personality') or {}).get('stable_tastes') or [])[:6] or tastes
        except Exception:
            pass
    temperament = ''
    try:
        from services.relationship_engine import PACE_HINTS
        temperament = PACE_HINTS.get(character_id, '') or ''
    except Exception:
        pass
    return (name, tastes, temperament)


def _memory_callback(telegram_id: int, character_id: str) -> str:
    """V3.167.4 (владелец ТЗ §4): «факт из памяти почти всегда» — её день цепляется
    за то, что он уже рассказывал, а не за анкету. Ручка LIFE_EVENTS_MEMORY_CHANCE."""
    if random.random() >= LIFE_EVENTS_MEMORY_CHANCE:
        return ''
    try:
        from services.user_service import ensure_user
        from services.memory_service import get_memories
        mems = get_memories(ensure_user(telegram_id), character_id, 12)
        if not mems:
            return ''
        return str(getattr(random.choice(mems), 'content', '') or '')[:200]
    except Exception:
        return ''


def _pending_hook(telegram_id: int) -> str:
    """~40% of the time, hand back the user's own unfinished topic to continue."""
    if random.random() > 0.40:
        return ''
    try:
        from services.user_service import get_state
        return str(getattr(get_state(telegram_id), 'pending_hook', '') or '')[:300]
    except Exception:
        return ''


def _recent_her_lines(telegram_id: int, character_id: str, limit: int = 6) -> list[str]:
    """Her last messages in this chat, so a new moment never repeats them."""
    try:
        from services.user_service import ensure_user
        from services.memory_service import get_recent_messages
        rows = get_recent_messages(ensure_user(telegram_id), character_id, 12)
        return [m.content for m in rows if m.role == 'assistant' and m.content][-limit:]
    except Exception:
        return []


def _system_prompt(name: str, when: str, tastes: list[str], temperament: str,
                   mem: str, hook: str, recent: list[str] | None = None,
                   level: int = 1, mode_on: bool = False, participation: bool = False) -> str:
    """V3.167.4 (владелец ТЗ §4): «её день» звучит как смс, а не как рассылка —
    одно-три предложения с бытовой деталью, без вопросов-анкет, тон по уровню
    близости и по режиму, в конце недосказанность под одну кнопку."""
    bits = [
        f'Ты — {name}.' if name else 'Ты — она.',
        temperament,
        _tone(level),
        'У него включён режим «Без цензуры 18+»: в намёке смелее, флирт открыто, '
        'можно сказать, что думаешь о нём. Подробностей самой сцены в пуше всё '
        'равно не давай — это одно сообщение, а не диалог.'
        if mode_on else 'Он в режиме «Романтика и флирт»: тепло, намёк, без пошлостей.',
        f'Сейчас у пользователя {_WHEN_HINT.get(when, "день")}.',
        'Напиши ОДНО сообщение ему: одно-три коротких предложения, не больше '
        '~180 знаков. Это случайный момент из твоего дня, которым ты сама '
        'решила поделиться — как настоящая смс в мессенджере.',
        'Обязательно одна бытовая деталь, которую видно: где ты стоишь, что '
        'держишь в руках, что только что случилось, что ты сейчас делаешь. Без '
        'общих слов вроде «день был сумасшедший».',
        'Это НЕ «скучаю / почему не пишешь» и НЕ вопрос про него. Не спрашивай '
        '«как дела», «что делаешь», «расскажи о себе», не проси фото и не '
        'задавай вопросов-анкет — он не обязан отвечать на пуш.',
        'Закончи недосказанностью — одной фразой, которая просит тап «расскажи '
        'дальше» («и тут он позвонил…», «угадаешь, что я ответила?»). Больше '
        'ничего после неё. Без хэштегов, не упоминай, что ты ИИ или что это рассылка.',
    ]
    if participation:
        from services.life_scene import PARTICIPATION_RULE
        # Replace the control cliffhanger, rather than asking for both formats.
        bits[-1] = PARTICIPATION_RULE
    if tastes:
        bits.append('Зацепка для момента (одна из твоих тем/вкусов): ' + random.choice(tastes) + '.')
    if mem:
        bits.append(f'Вспомни его же деталь, скажи её естественно и свяжи со своим моментом: «{mem}».')
    if hook:
        bits.append(f'Незакрытая тема пользователя, к которой можно вернуться: «{hook}».')
    if recent:
        bits.append('Твои последние сообщения ему, их не повторяй и не обещай то же снова: '
                    + ' | '.join(f'«{t[:120]}»' for t in recent[-4:]) + '.')
    return ' '.join(b for b in bits if b)


def _relationship_frame(telegram_id: int, character_id: str) -> tuple[int, bool]:
    """Уровень близости 1-10 и режим аккаунта — по ним её день звучит по-разному.
    Отказов не бывает: без БД и без персонажа это (1, False), самый спокойный тон."""
    level = 1
    try:
        from services.photo_service import get_relationship_level
        level = int(get_relationship_level(telegram_id, character_id) or 1)
    except Exception:
        logger.debug('life level lookup failed user=%s', telegram_id)
    try:
        from services import explicit_mode
        return level, bool(explicit_mode.is_on_for(int(telegram_id)))
    except Exception:
        return level, False


def _pool_photo(character_id: str, uid: int) -> tuple[bytes, str, str] | None:
    """Кадр, который она сама приложила к своему дню.

    V3.56.7: только её собственный пул — чужое лицо в её чате быть не может.
    V3.167.4 (владелец 16.11): «лимит 2 фото в сутки» — кадр тратит общий кап
    бесплатных кадров на аккаунт, а не живёт от него в стороне. Кап закрыт — её
    день приходит просто текстом. Рендера провайдера тут нет и быть не может."""
    try:
        from services import chat_photo_allowance, life_backlog
        if chat_photo_allowance.frames_left(uid) <= 0:
            life_backlog.note_denial(uid, 'life', 'photo_cap')
            return None
        from services.retention_features_service import random_proactive_photo
        photo = random_proactive_photo(character_id, user_id=uid)
        if photo and not chat_photo_allowance.use_push_frame(uid, character_id):
            life_backlog.note_denial(uid, 'life', 'photo_cap')
            return None
        return photo
    except Exception:
        logger.debug('life photo pick failed char=%s', character_id, exc_info=True)
        return None


async def build_life_moment(telegram_id: int, character_id: str, when: str = 'day') -> dict:
    """Compose one spontaneous life message. Returns {} on any failure/empty."""
    try:
        # V3.158.0: the push runs in the scheduler's task, where nobody marked
        # the user — without this her life moment costs land in the ownerless
        # pile and the ROI of the source that brought him stays invisible.
        from services import spend_service
        spend_service.set_spend_user(int(telegram_id))
        spend_service.set_spend_source('her_day')
        spicy = _her_day_spicy(int(telegram_id))
        if HER_DAY_FIXED_POOL and not LIFE_FORMAT_V2:
            pool = her_day_pool(spicy)
            recent_lines = _recent_her_lines(telegram_id, character_id)
            recent_blob = ' '.join(recent_lines)
            fresh = [t for t in pool if t[:30] not in recent_blob] or list(pool)
            from services.user_service import ensure_user as _eu
            photo = None
            if LIFE_EVENTS_PHOTO_CHANCE and random.random() < LIFE_EVENTS_PHOTO_CHANCE:
                photo = _pool_photo(character_id, _eu(telegram_id))
            return {'text': random.choice(fresh), 'photo': photo,
                    'options': her_day_options(spicy, character_id), 'when': when,
                    'actions': None, 'experiment': {'variant': 'pool', 'mode_on': spicy}}
        name, tastes, temperament = _character_ingredients(character_id)
        mem = _memory_callback(telegram_id, character_id)
        hook = _pending_hook(telegram_id)
        recent = _recent_her_lines(telegram_id, character_id)
        from services.user_service import ensure_user
        uid = ensure_user(telegram_id)
        level, mode_on = _relationship_frame(telegram_id, character_id)
        from services import life_experiment
        experiment = life_experiment.assignment(uid)
        experiment['mode_on'] = mode_on
        participation = experiment['variant'] == 'treatment'
        # The legacy pending hook is account-wide. Never copy it into a new
        # character-specific scene; the confirmed memory above is scoped.
        system = _system_prompt(name, when, tastes, temperament, mem,
                                '' if participation else hook, recent,
                                level=level, mode_on=mode_on, participation=participation)
        from services.llm_provider_service import generate_text
        # V3.63.1: a system-only request is rejected by MiniMax («chat content
        # is empty») and Gemini («contents is not specified») — every life
        # moment failed. The user turn carries the ask.
        from services.dialogue_guard_service import finish_or_drop, polish_first_message
        anchor = 'fact' if (mem or (hook and not participation)) else 'place'

        async def _gen(extra: str = ''):
            ask = 'Напиши ему это сообщение сейчас.' + extra
            r = await generate_text([{'role': 'system', 'content': system},
                                     {'role': 'user', 'content': ask}],
                                    max_tokens=160 if participation else 90,
                                    temperature=0.95, purpose='life_event')
            out = (getattr(r, 'text', '') or '').strip().strip('"').strip()
            acts = None
            if participation:
                from services.life_scene import parse_moment
                out, acts = parse_moment(out)
                if not out:
                    return '', None
            # V3.63.15: same chat polish as replies (no em dash, no emoji tic) and
            # nothing she already said; a pure repeat skips the slot.
            out = finish_or_drop(out, getattr(r, 'complete', True))
            out = polish_first_message(out, recent)
            return out, acts

        text, actions = await _gen()
        if LIFE_FORMAT_V2:
            # V3.168 (ТЗ 3.5): validator on the way out — one regeneration, then a template.
            ok, why = validate_life_text(text)
            if not ok:
                text, actions = await _gen(' Коротко: 1-2 предложения, одна бытовая деталь, не больше одного '
                                           'вопроса, в конце крючок или недосказанность, не больше двух эмодзи.')
                ok, why = validate_life_text(text)
            if not ok:
                logger.info('life text failed validation (%s), template used user=%s', why, telegram_id)
                text, anchor = template_life_text(when, mem or hook, spicy=spicy)
                actions = None
        elif len(text) < 8:
            return {}
        photo = None
        if LIFE_EVENTS_PHOTO_CHANCE and random.random() < LIFE_EVENTS_PHOTO_CHANCE:
            photo = _pool_photo(character_id, uid)
        options = [(lbl, f'life_reply:{character_id}:{key}') for lbl, key in _REPLY_OPTIONS]
        return {'text': text, 'photo': photo, 'options': options, 'when': when,
                'actions': actions, 'experiment': experiment, 'anchor': anchor}
    except Exception:
        logger.exception('build_life_moment failed user=%s char=%s', telegram_id, character_id)
        return {}
