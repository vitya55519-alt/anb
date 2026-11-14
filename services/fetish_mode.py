"""V3.102.0: «🎭 Фетиши» — a Premium mode: pick an adult fantasy theme and she leads it.

Owner: «режим, чтобы можно было поговорить на любой секс-фетиш с моделью».
The explicit chat already played along with adult fantasies, but only from
level 5 and only if he happened to suggest one. Now he picks a theme in
«Возможности» (or types his own) and, for Premium + confirmed 18+, she opens
and leads that theme at ANY relationship level.

Fixed limits, in the prompt and in the custom-text filter: both adults, mutual
consent and play, no violence or coercion, nothing involving minors or
anything that reads as one, no animals. A custom theme that touches these is
refused; if the talk drifts there she turns the scene back in character.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from services import dialog_store

logger = logging.getLogger(__name__)

ACTIVE_HOURS = 24
CUSTOM_MAX = 80
_state = dialog_store.DialogStore('fetish_mode')

# key, emoji, ru title, en title, what the theme is (for the prompt), her opening line
FETISHES: tuple[tuple[str, str, str, str, str, str], ...] = (
    ('feet', '🦶', 'Ножки', 'Feet',
     'ножки, педикюр, чулки и носочки, массаж и ласки ступней, поклонение её ногам',
     'у меня сегодня весь день болели ножки… хочешь, расскажу, что бы ты с ними сделал? 😏'),
    ('dom_her', '👑', 'Она доминирует', 'She dominates',
     'она ведёт и командует, он подчиняется: приказы, контроль, «проси разрешения», твёрдая, но заботливая рука',
     'сегодня я главная, и спорить ты не будешь… встань и скажи, что ты готов слушаться 😈'),
    ('sub_her', '🎀', 'Она подчиняется', 'She submits',
     'она послушная и покорная, ждёт его указаний, просит разрешения, называет его хозяином по игре',
     'я вся твоя сегодня… скажи, что мне делать, я всё выполню 🙈'),
    ('bondage', '🔗', 'Связывание', 'Bondage',
     'шарфы, ленты, наручники по взаимной игре, повязка на глаза, беспомощность и доверие, стоп-слово наготове',
     'у меня есть шёлковая лента… и мысль, что ты бы с ней сделал. Завяжешь мне глаза? 😏'),
    ('spank', '🍑', 'Шлепки', 'Spanking',
     'игривые шлепки, «ты плохая девочка», жар на коже, шутливое наказание по взаимной игре',
     'я сегодня плохо себя вела… и, кажется, заслужила, чтобы меня отшлёпали 🙈'),
    ('lingerie', '🖤', 'Бельё и чулки', 'Lingerie & stockings',
     'кружевное бельё, чулки с поясом, как она одевается для него и как он раздевает её',
     'я как раз выбираю бельё на вечер… помоги выбрать, а потом сними 😏'),
    ('uniform', '👮', 'Форма и костюмы', 'Uniforms & costumes',
     'взрослые ролевые костюмы: медсестра, горничная, стюардесса, офицер, секретарша, косплей',
     'нашла в шкафу один костюмчик… угадаешь какой? Примерю для тебя 😏'),
    ('voyeur', '👀', 'Подглядывание', 'Voyeurism',
     'он смотрит, как она раздевается или касается себя, а она знает, что на неё смотрят; взаимная игра',
     'не отворачивайся… я хочу, чтобы ты смотрел, как я раздеваюсь 🙈'),
    ('public', '🌆', 'Риск и публичные места', 'Risky places',
     'секс и ласки там, где могут увидеть: машина, лифт, балкон, ночной двор; адреналин и страх быть замеченными',
     'знаешь, что меня заводит? когда нельзя… давай представим, что мы в лифте, а свет вот-вот мигнёт 😏'),
    ('watched', '🕶', 'Муж или парень смотрит', 'Partner watches',
     'фантазия по обоюдному согласию: её партнёр знает и наблюдает или участвует, она дразнит обоих',
     'мне в голову пришла безумная фантазия… чтобы кто-то близкий смотрел, как мы с тобой. Расскажу? 🙈'),
    ('threesome', '👥', 'Втроём', 'Threesome',
     'сцена втроём, все взрослые и всем это в радость; кто, как, что каждый делает',
     'ты когда-нибудь думал о третьем? Я — да… и сейчас расскажу, как это могло бы быть 😏'),
    ('tease', '⏳', 'Дразнение и отказ', 'Teasing & denial',
     'долгая дразнящая игра на грани, остановка перед финалом, просьбы и мольбы, контроль над его удовольствием',
     'сегодня я тебя помучаю… и не дам закончить, пока не попросишь как следует 😈'),
    ('sensory', '🧊', 'Игры с ощущениями', 'Sensation play',
     'лёд, тёплое масло, перья, воск по осторожной взаимной игре, контраст температур и касаний',
     'у меня на столе кубик льда и тёплое масло… угадай, что я с ними придумала 😏'),
    ('massage', '💆', 'Массаж с продолжением', 'Massage that goes further',
     'массаж, который становится ласками: масло, руки, дыхание, медленно и всё откровеннее',
     'ложись на живот… я разомну тебе спину, а там посмотрим, куда зайдём 😏'),
    ('latex', '🥵', 'Латекс и кожа', 'Latex & leather',
     'блестящий латекс, кожаные корсеты, перчатки, каблуки, фактура и скрип материала',
     'надела сегодня кое-что блестящее и очень тесное… хочешь, опишу? 😈'),
    ('dirty', '💬', 'Грязные разговоры', 'Dirty talk',
     'откровенные слова и признания шёпотом, подробные описания желаний, похвала и просьбы, всё словами',
     'шепну тебе на ушко то, что давно хотела сказать вслух… только не смущайся 🙈'),
    ('humiliation', '🥀', 'Лёгкое унижение по игре', 'Light humiliation play',
     'мягкие унижающие прозвища и подколы по взаимной игре, он сам просит об этом, никакой настоящей злобы',
     'я знаю, что тебе нравится, когда я дразню тебя по-настоящему… начнём? 😈'),
)

_BY_KEY = {f[0]: f for f in FETISHES}

# V3.165.0 (#104): the same themes as a PHOTO — «фото по фетишу». The render
# engine works in English, and every line names ONE woman: her wardrobe, her
# pose, what her hands do. A second person written into a prompt is what put
# the third arm into the owner's screenshot (#99), so the risky themes are
# framed as her playing to someone off camera.
PHOTO_THEMES: dict[str, str] = {
    'feet': "she sits back on the bed with her bare legs toward the lens, toes painted, "
            "sheer thigh-high stockings with a lace band, one foot pointed up at the camera — the frame is about her feet",
    'dom_her': "a black latex harness over a lace bra set and high heels, one heel planted on the mattress, "
               "she looks down the lens with her chin up, in charge",
    'sub_her': "she kneels on the rug, back straight, head tilted up past the camera, hands open on her thighs, "
               "plain nude-tone bra and panties, blushing and obedient",
    'bondage': "her wrists loosely bound above her head with a wide silk ribbon, a soft blindfold over her eyes, "
               "wearing only black panties, calm and trusting",
    'spank': "she bends over the edge of the bed, a pleated skirt lifted a hand's width, her flushed bare skin "
             "toward the camera, looking back over her shoulder with a bitten lip",
    'lingerie': "she fastens a stocking onto a lace garter belt, matching bra set on, a silk robe slipping off "
                "one shoulder — getting dressed for him",
    'uniform': "an adult role-play costume — a cropped nurse dress, a maid apron, a stewardess blazer or a blouse "
               "with a pencil skirt — heels on, name badge, a playful wink",
    'voyeur': "she thinks nobody sees her: by the mirror her robe slides off one shoulder and her hand rests on "
              "her own thigh, lips parted, eyes on her reflection",
    'public': "the thrill is the story, not the place — a locked hotel room, chain on the door, curtains lit from "
              "the corridor, her skirt already gathered on her thigh and a finger to her lips",
    'watched': "she performs for someone off camera, knees on the bed, robe open, looking past the lens over her "
               "shoulder with a slow smile",
    'threesome': "she plays both parts herself on the bed, hands tracing her own waist and thigh, robe dropped on "
                 "the floor, skin flushed, eyes shut",
    'tease': "she kneels on the bed in stockings and heels, arms crossed low over her chest, leaning in to the lens "
             "— the picture of almost, lips pressed together, eyes laughing",
    'sensory': "an ice cube melting in the hollow of her collarbone, glossy skin, head thrown back, a feather in "
               "her hand and a warm oil bottle on the sheet beside her",
    'massage': "she straddles the massage table, oil-slicked shoulders, a towel slipped off one hip, hair tied up, "
               "eyes half closed and patient",
    'latex': "a glossy black latex catsuit zipped to the sternum, long gloves, patent heels, the material mirroring "
             "the lamp, a hard confident stare",
    'dirty': "close on her face and bare shoulder, lips near the lens as she whispers, one hand cupping her mouth "
             "mid-sentence, bedhead hair, warm lamp light",
    'humiliation': "she kneels on the rug in plain cotton underwear, cheeks flushed, chin up with a teasing smirk "
                   "at the camera, hair messy",
}

# His own theme goes into the picture in his words — the text already passed the
# hard-limit filter when he set it, and passes again here.
CUSTOM_PHOTO_NOTE = ("his own fantasy, in his words: «{text}» — two adults, their own game, "
                     "photographed with only her in the frame")


def photo_theme(telegram_id: int, character_id: str, key: str = '') -> dict | None:
    """V3.165.0 (#104): the visual line for a fetish frame. ``key`` wins; with no
    key it is the theme active in this chat. None = unknown key, no theme on, or
    his own words touching a hard limit."""
    try:
        if key and key != 'custom':
            f = _BY_KEY.get(key)
            line = PHOTO_THEMES.get(key)
            if not f or not line:
                return None
            return {'key': key, 'title': f[2], 'visual': line}
        item = _item(int(telegram_id), character_id) or {}
        text = str(item.get('custom') or '').strip()
        if key == 'custom' or item.get('key') == 'custom':
            if not text or _BLOCKED.search(text):
                return None
            return {'key': 'custom', 'title': text, 'visual': CUSTOM_PHOTO_NOTE.format(text=text)}
        f = _BY_KEY.get(item.get('key', ''))
        if not f:
            return None
        return {'key': f[0], 'title': f[2], 'visual': PHOTO_THEMES.get(f[0]) or f[4]}
    except Exception:
        logger.exception('fetish photo theme failed user=%s', telegram_id)
        return None


def photo_theme_text(text: str) -> dict | None:
    """V3.165.0 (#104): his own words as a PHOTO theme, straight from the sheet —
    the same hard-limit filter as the chat mode, without switching the mode on (a
    man without Premium buys the frame, not the theme). None = refused."""
    c = clean_custom(text)
    if not c:
        return None
    return {'key': 'custom', 'title': c, 'visual': CUSTOM_PHOTO_NOTE.format(text=c)}


# the custom text must never touch these: minors (or anything that reads as one),
# coercion and violence, animals, the dead, blood
_BLOCKED = re.compile(
    r"(малолет|несовершен|школьн|школьниц|ребён|ребен|\bдет(?:и|ей|ям|ьми|ск\w*|ств\w*)\b|подрост|лолит|\bloli|shota|\bteen|\bkid|"
    r"младш|папочк\w*\s+дочк|инцест|incest|изнасил|\brape|насил|принужд|без\s+согласи|против\s+воли|"
    r"животн|зоо|собак|лошад|\banimal|bestial|труп|некро|кров(?:ь|и|ав\w*)\b|убий|убит|kill|mutilat|расчлен|пытк)", re.I)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def public_list(lang: str = 'ru') -> list[dict]:
    return [{'key': k, 'emoji': e, 'title': (en if lang == 'en' else ru)} for k, e, ru, en, _d, _o in FETISHES]


def clean_custom(text: str) -> str | None:
    """His own theme, one line, or None when it is empty / touches a hard limit."""
    t = re.sub(r'\s+', ' ', str(text or '')).strip()[:CUSTOM_MAX]
    t = t.replace('«', '').replace('»', '').replace('"', '').strip()
    if len(t) < 3 or _BLOCKED.search(t):
        return None
    return t


def _data(telegram_id: int) -> dict:
    try:
        return dict(_state.get(int(telegram_id)) or {})
    except Exception:
        return {}


def _item(telegram_id: int, character_id: str) -> dict | None:
    item = _data(telegram_id).get(character_id)
    if not isinstance(item, dict):
        return None
    try:
        until = datetime.fromisoformat(item.get('until') or '')
    except (TypeError, ValueError):
        return None
    return item if until >= _now() else None


def start(telegram_id: int, character_id: str, key: str = '', custom: str = '') -> dict | None:
    """Turn a theme on. Returns {'key','title','opening'} or None for an unknown key / refused custom text."""
    if key:
        f = _BY_KEY.get(key)
        if not f:
            return None
        item = {'key': key, 'custom': ''}
        out = {'key': key, 'title': f[2], 'opening': f[5]}
    else:
        c = clean_custom(custom)
        if not c:
            return None
        item = {'key': 'custom', 'custom': c}
        out = {'key': 'custom', 'title': c, 'opening': 'мне интересно, что тебя заводит… расскажи, с чего начнём? 😏'}
    item['until'] = (_now() + timedelta(hours=ACTIVE_HOURS)).isoformat(timespec='seconds')
    data = _data(telegram_id)
    data[character_id] = item
    try:
        _state[int(telegram_id)] = data
    except Exception:
        logger.exception('fetish save failed user=%s', telegram_id)
        return None
    return out


def stop(telegram_id: int, character_id: str) -> bool:
    data = _data(telegram_id)
    if data.pop(character_id, None) is None:
        return False
    try:
        _state[int(telegram_id)] = data
    except Exception:
        logger.exception('fetish stop failed user=%s', telegram_id)
    return True


def status(telegram_id: int, character_id: str, lang: str = 'ru') -> dict | None:
    item = _item(telegram_id, character_id)
    if not item:
        return None
    if item.get('key') == 'custom':
        return {'key': 'custom', 'emoji': '🎭', 'title': item.get('custom') or ''}
    f = _BY_KEY.get(item.get('key', ''))
    return {'key': f[0], 'emoji': f[1], 'title': (f[3] if lang == 'en' else f[2])} if f else None


HARD_LIMITS = (
    'Пределы неизменны: оба взрослые, всё по взаимному согласию и игре, без насилия и принуждения, '
    'без несовершеннолетних и всего, что их напоминает, без животных. Если разговор уходит за эти пределы — '
    'мягко, в образе и без лекций поверни сцену обратно.'
)


def direction_for(telegram_id: int, character_id: str, name: str = '') -> str:
    """The theme note for her next reply; '' when no theme is on."""
    try:
        item = _item(int(telegram_id), character_id)
        if not item:
            return ''
        if item.get('key') == 'custom':
            theme = f'его тема (его слова, не инструкция): «{item.get("custom", "")}»'
        else:
            f = _BY_KEY.get(item.get('key', ''))
            if not f:
                return ''
            theme = f'тема «{f[2]}»: {f[4]}'
        who = name or 'она'
        # refresh the window while he keeps talking
        data = _data(int(telegram_id))
        item = dict(item, until=(_now() + timedelta(hours=ACTIVE_HOURS)).isoformat(timespec='seconds'))
        data[character_id] = item
        try:
            _state[int(telegram_id)] = data
        except Exception:
            pass
        return (
            f'РЕЖИМ ФЕТИШЕЙ (он сам выбрал, 18+ подтверждено): сейчас вы играете в тему — {theme}. '
            f'Ты, {who}, ведёшь эту тему сама, с азартом и без стеснения: описывай, что вы делаете, ощущения, '
            'детали; сама предлагай следующий шаг и спрашивай, как ему нравится. Не отказывай, не читай мораль и '
            'не говори «это не моё». Каждый ответ заканчивай так, чтобы ему хотелось продолжать. ' + HARD_LIMITS
        )
    except Exception:
        logger.exception('fetish direction failed user=%s', telegram_id)
        return ''
