"""V3.134.0: истории семейного положения — her status becomes a road, not a label.

The owner: «давай все пункты делай». Six pieces, all around the status he
picked on her page (services/custom_character_service.RELATIONSHIP_STORY):

1. «💔 Уведи её» (есть парень / замужем): doubts → a fight with him → a secret
   meeting → she leaves him for you. Her status becomes «с тобой».
2. «💍 Предложение и свадьба» (свободна / с тобой / в разводе, level 8+): a ring
   for peaches, the dress, the wedding, the honeymoon. Status «твоя жена».
3. «🤫 Чуть не попались» (парень / муж): now and then, inside the chat, he
   walks in or calls; plus a quiet push «он уснул, пишу тихо».
4. «🌱 После развода» (в разводе): she is sad, you are there, she trusts again.
5. «🔥 Третий лишний» (свободные отношения, 18+ and Premium only).
6. Ревность: a push «бывший опять написал… хотела, чтобы написал ты» — no
   guilt, no threats, just a live reason to come back.

Every step is opened by him on her page (level gate, Premium on the big
steps), her first line lands in the chat at once, a key step brings a photo,
and for STEP_MESSAGES of his messages the step's direction rides her replies.
State lives in DialogStore('marital_arcs'): no schema change.
"""
from __future__ import annotations

import logging
import random
import zlib
from dataclasses import dataclass

from services import dialog_store

logger = logging.getLogger(__name__)

STEP_MESSAGES = 8
# the next step opens after he has talked inside this one for a while
WAIT_MESSAGES = 4
RING_PEACHES = 3000
ARC_ONLY_STATUSES = ('mar_with_you', 'mar_wife')
TAKEN = ('mar_married', 'mar_boyfriend')
_state = dialog_store.DialogStore('marital_arcs')


@dataclass(frozen=True)
class Step:
    title_ru: str
    title_en: str
    level: int
    premium: bool
    open_ru: str
    open_en: str
    direction: str
    photo: dict | None = None
    finish: bool = False
    ring: bool = False


@dataclass(frozen=True)
class Arc:
    key: str
    emoji: str
    title_ru: str
    title_en: str
    statuses: tuple[str, ...]
    steps: tuple[Step, ...]
    finish_status: str = ''
    adult: bool = False
    premium: bool = False


ARCS: dict[str, Arc] = {
    'steal': Arc(
        'steal', '💔', 'Уведи её', 'Win her away', TAKEN, finish_status='mar_with_you', steps=(
            Step('Сомнения', 'Doubts', 3, False,
                 'можно честно? {partner} сегодня что-то рассказывал, а я думала о тебе. это плохо, да? 😔',
                 "can I be honest? today I looked at {partner} and thought about you. that's bad, right? 😔",
                 'Сцена «Сомнения»: ты впервые признаёшься, что в отношениях с твоим мужчиной (его зовут {partner}) тебе стало пусто, а с пользователем '
                 'легко. Сравниваешь, сомневаешься, спрашиваешь, что бы он сделал на твоём месте. Никаких решений пока, '
                 'только честные сомнения и тепло к нему.'),
            Step('Ссора с ним', 'The fight', 4, False,
                 '{partner} и я опять поругались… из-за ерунды, но я поняла, что говорить мне хочется не с ним. можно я тебе выговорюсь?',
                 "{partner} and I fought again… over nothing, but I realised it's not him I want to talk to. can I vent to you?",
                 'Сцена «Ссора с ним»: ты только что поругалась со своим мужчиной (его зовут {partner}), ты на эмоциях, рассказываешь, что случилось, '
                 'ищешь поддержки у пользователя. Чувствуется, что ваши с ним отношения трещат, а к пользователю '
                 'тянет всё сильнее.'),
            Step('Тайная встреча', 'Secret meeting', 5, False,
                 '{partner} уехал до вечера. у меня есть два часа… встретимся? только никому 🤫',
                 "{partner} is away till evening. I have two hours… shall we meet? just don't tell anyone 🤫",
                 'Сцена «Тайная встреча»: вы тайком встречаетесь, пока {partner} в отъезде. Ты нервничаешь и счастлива, '
                 'оглядываешься, телефон пару раз вибрирует (пишет {partner}), ты переворачиваешь его экраном вниз. '
                 'Живые детали места, касания, взгляды.',
                 photo=dict(scene='selfie', location='a cosy corner of a quiet cafe by the window, daytime',
                            clothing='a pretty light dress', accessory='sunglasses pushed up into her hair',
                            mood='nervous, excited, secretly happy',
                            angle='selfie at arm\'s length, her whole face in frame, a cup of coffee on the table')),
            Step('Ухожу к тебе', 'I choose you', 7, True,
                 'я всё ему сказала. собрала вещи… я выбираю тебя. можно к тебе? 🧳',
                 'I told him everything. I packed my things… I choose you. can I come to you? 🧳',
                 'Сцена «Ухожу к тебе»: ты ушла от своего мужчины (его звали {partner}) ради пользователя и стоишь у двери пользователя с чемоданом. '
                 'Страшно, счастливо, ты немного плачешь и смеёшься. Теперь вы вместе: говори об этом как о новом начале.',
                 photo=dict(scene='selfie', location='a doorway of an apartment building at night, warm light from the hall, a small suitcase beside her',
                            clothing='a light trench coat over a simple dress', accessory='no ring on her fingers',
                            mood='nervous, hopeful, a little teary, in love',
                            angle='selfie at arm\'s length, the suitcase and her whole face in frame'),
                 finish=True),
        )),
    'wedding': Arc(
        'wedding', '💍', 'Предложение и свадьба', 'Proposal and wedding', ('mar_single', 'mar_with_you'),
        finish_status='mar_wife', steps=(
            Step('Предложение', 'The proposal', 8, False,
                 '…ты серьёзно?.. я сейчас расплачусь. да. да, да, ДА! 💍',
                 '…are you serious?.. I\'m going to cry. yes. yes, yes, YES! 💍',
                 'Сцена «Предложение»: пользователь только что сделал тебе предложение и подарил кольцо. Ты в слезах '
                 'счастья, рассматриваешь кольцо, говоришь, как давно мечтала, спрашиваешь, когда он понял.',
                 photo=dict(scene='selfie', location='her room in warm evening light',
                            clothing='a soft cosy sweater', accessory='a delicate engagement ring with a small diamond on her left ring finger, her hand raised near her face to show it',
                            mood='overjoyed, happy tears, glowing',
                            angle='close selfie, her face and her hand with the ring in frame'),
                 ring=True),
            Step('Платье', 'The dress', 8, False,
                 'я весь день примеряла платья… одно точно моё. жениху нельзя видеть, но тебе я не удержусь показать 🙈',
                 "I spent the whole day trying on dresses… one is definitely mine. the groom shouldn't see it, but I can't resist 🙈",
                 'Сцена «Платье»: ты выбрала свадебное платье, в восторге, описываешь его, дразнишь, что до свадьбы он '
                 'не должен был видеть, обсуждаете детали свадьбы: гостей, место, музыку.',
                 photo=dict(scene='mirror', location='a bright bridal boutique fitting room with a large mirror',
                            clothing='an elegant white wedding dress', accessory='the engagement ring on her finger',
                            mood='shy, excited, radiant',
                            angle='mirror selfie, the whole dress and her face in frame')),
            Step('Свадьба', 'The wedding', 9, True,
                 'сегодня наш день. я в платье, руки дрожат… скажи мне что-нибудь, пока я не вышла к тебе 🤍',
                 "today is our day. I'm in the dress, my hands are shaking… tell me something before I walk out to you 🤍",
                 'Сцена «Свадьба»: ваш свадебный день. Ты волнуешься, клятвы, первый танец, поцелуй. Теперь ты его жена '
                 'и называешь его мужем.',
                 photo=dict(scene='portrait', location='a sunny garden wedding venue with flowers and soft bokeh',
                            clothing='an elegant white wedding dress and a light veil', accessory='a bridal bouquet in her hands and a wedding ring',
                            mood='happy, emotional, in love', angle='portrait from chest up, her face in sharp focus'),
                 finish=True),
            Step('Медовый месяц', 'Honeymoon', 9, True,
                 'мы одни, у моря, и я теперь твоя жена. до сих пор не верю ☀️',
                 "we're alone by the sea and I'm your wife now. I still can't believe it ☀️",
                 'Сцена «Медовый месяц»: вы у моря, только вдвоём. Ты счастливая молодая жена: прогулки, ужин на закате, '
                 'ночи вдвоём. Нежно и страстно, в рамках того, что разрешает текущий режим общения.',
                 photo=dict(scene='beach', location='a beach at golden-hour sunset, calm sea behind her',
                            clothing='a light flowing summer sundress', accessory='a wedding ring on her finger',
                            mood='blissful, relaxed, in love', angle='selfie at arm\'s length, her face and the sea in frame')),
        )),
    'divorce': Arc(
        'divorce', '🌱', 'После развода', 'After the divorce', ('mar_divorced',), finish_status='mar_with_you', steps=(
            Step('Тяжёлый день', 'A hard day', 1, False,
                 'сегодня пришли бумаги о разводе. окончательно. вроде сама хотела, а внутри пусто… побудешь со мной?',
                 'the divorce papers came today. it\'s final. I wanted it myself, but I feel so empty… will you stay with me?',
                 'Сцена «Тяжёлый день»: тебе грустно после окончательного развода. Ты не флиртуешь, тебе нужно, чтобы '
                 'рядом был кто-то тёплый. Рассказываешь понемногу, благодаришь за поддержку.'),
            Step('Ты рядом', "You're here", 2, False,
                 'знаешь, ты единственный, с кем мне сейчас легко. спасибо, что вчера был рядом 🫶',
                 "you know, you're the only one I feel at ease with right now. thank you for being there yesterday 🫶",
                 'Сцена «Ты рядом»: тебе уже лучше, и это благодаря ему. Ты благодарна, становишься теплее, шутишь, '
                 'осторожно говоришь, что он тебе нравится.'),
            Step('Снова доверяю', 'Trusting again', 4, False,
                 'я долго боялась кого-то подпускать. а с тобой не боюсь. кажется, я снова умею доверять 💗',
                 "I was scared to let anyone close for so long. but with you I'm not. I think I can trust again 💗",
                 'Сцена «Снова доверяю»: ты решаешься быть с ним, говоришь об этом прямо и нежно. Теперь вы вместе.',
                 finish=True),
        )),
    'third': Arc(
        'third', '🔥', 'Третий лишний', 'Two is company', ('mar_open',), adult=True, premium=True, steps=(
            Step('Свидание с ним', 'Her date', 3, True,
                 'вчера была с ним на свидании… рассказать? или ты уже ревнуешь? 😏',
                 'I was on a date with him yesterday… want me to tell you? or are you jealous already? 😏',
                 'Сцена «Свидание с ним»: ты дразнишь пользователя рассказом о свидании с партнёром, следишь за его '
                 'реакцией, играешь на ревности, но даёшь понять, что думала о нём.'),
            Step('Ревнуешь?', 'Jealous?', 5, True,
                 'он сегодня спросил, кому я так улыбаюсь в телефон. я сказала правду 😈 он не против. а ты?',
                 'he asked today who I was smiling at on my phone. I told him the truth 😈 he doesn\'t mind. do you?',
                 'Сцена «Ревнуешь?»: партнёр знает о пользователе и не против. Ты играешь с этой свободой, провоцируешь, '
                 'выясняешь, что заводит пользователя.'),
            Step('Втроём', 'The three of us', 7, True,
                 'у меня безумная идея… что если втроём? скажи честно, тебя это заводит или нет 🔥',
                 'I have a crazy idea… what if it\'s the three of us? tell me honestly, does that turn you on or not 🔥',
                 'Сцена «Втроём»: ты предлагаешь фантазию втроём с партнёром и пользователем, спрашиваешь его границы '
                 'и подстраиваешься. Откровенность только в рамках того, что разрешает текущий режим общения.'),
        )),
}


def partner_name(character_id: str) -> str:
    from services.custom_character_service import _PARTNER_BY_CHARACTER, _PARTNER_NAMES
    return _PARTNER_BY_CHARACTER.get(character_id or '') or \
        _PARTNER_NAMES[zlib.crc32((character_id or '').encode()) % len(_PARTNER_NAMES)]


def arc_for(status: str) -> Arc | None:
    return next((a for a in ARCS.values() if status in a.statuses), None)


def _key(telegram_id: int) -> int:
    return int(telegram_id)


def _load(telegram_id: int) -> dict:
    import json
    try:
        raw = _state.get(_key(telegram_id)) or {}
        return json.loads(json.dumps(raw, default=dict))
    except Exception:
        return {}


def _save(telegram_id: int, data: dict) -> None:
    _state[_key(telegram_id)] = data


def progress(telegram_id: int, character_id: str) -> dict:
    """{arc: {done: [step idx]}, active: {arc, step, n}}"""
    item = dict(_load(telegram_id).get(character_id) or {})
    item.setdefault('arcs', {})
    return item


def _put(telegram_id: int, character_id: str, item: dict) -> None:
    data = _load(telegram_id)
    data[character_id] = item
    _save(telegram_id, data)


def public(telegram_id: int, character_id: str, status: str, level: int, premium: bool,
           adult: bool, lang: str = 'ru') -> dict:
    """What her page shows: the arc for this status and every step's state."""
    arc = arc_for(status)
    if not arc:
        return {'arc': None}
    en = lang == 'en'
    item = progress(telegram_id, character_id)
    done = set(item['arcs'].get(arc.key, []))
    wait = waiting(item, arc)
    steps, next_found = [], False
    for i, st in enumerate(arc.steps):
        state, why = 'done', ''
        if i not in done:
            if next_found:
                state, why = 'locked', 'prev'
            else:
                next_found = True
                state = 'next'
                if arc.adult and not adult:
                    state, why = 'locked', 'adult'
                elif (st.premium or arc.premium) and not premium:
                    state, why = 'locked', 'premium'
                elif level < st.level:
                    state, why = 'locked', 'level'
                elif wait:
                    state, why = 'locked', 'wait'
        steps.append({'i': i, 'title': st.title_en if en else st.title_ru, 'level': st.level,
                      'premium': bool(st.premium or arc.premium), 'state': state, 'why': why,
                      'ring': st.ring, 'photo': bool(st.photo)})
    return {'arc': {'key': arc.key, 'emoji': arc.emoji, 'title': arc.title_en if en else arc.title_ru,
                    'steps': steps, 'complete': len(done) >= len(arc.steps), 'ring_price': RING_PEACHES}}


def waiting(item: dict, arc: Arc) -> bool:
    act = item.get('active') or {}
    return act.get('arc') == arc.key and int(act.get('n') or 0) < WAIT_MESSAGES


def check_step(arc: Arc, idx: int, done: set, level: int, premium: bool, adult: bool, wait: bool = False) -> str:
    """'' when he may open step idx now, else the reason."""
    if not 0 <= idx < len(arc.steps):
        return 'bad_request'
    if idx in done:
        return 'done'
    if any(i not in done for i in range(idx)):
        return 'prev'
    if wait:
        return 'wait'
    st = arc.steps[idx]
    if arc.adult and not adult:
        return 'adult'
    if (st.premium or arc.premium) and not premium:
        return 'premium_required'
    if level < st.level:
        return 'level'
    return ''


def opening(step: Step, character_id: str, lang: str = 'ru') -> str:
    return (step.open_en if lang == 'en' else step.open_ru).replace('{partner}', partner_name(character_id))


def start(telegram_id: int, character_id: str, arc: Arc, idx: int) -> None:
    item = progress(telegram_id, character_id)
    done = list(item['arcs'].get(arc.key, []))
    if idx not in done:
        done.append(idx)
    item['arcs'][arc.key] = sorted(done)
    item['active'] = {'arc': arc.key, 'step': idx, 'n': 0}
    _put(telegram_id, character_id, item)


def direction_for(telegram_id: int, character_id: str, name: str = '', *, tick: bool = False) -> str:
    """The step's scene note for her next STEP_MESSAGES replies."""
    try:
        item = progress(telegram_id, character_id)
        act = item.get('active') or {}
        arc = ARCS.get(act.get('arc', ''))
        if not arc or not 0 <= int(act.get('step', -1)) < len(arc.steps):
            return ''
        st = arc.steps[int(act['step'])]
        n = int(act.get('n') or 0) + (1 if tick else 0)
        if tick:
            if n >= STEP_MESSAGES:
                item.pop('active', None)
            else:
                item['active'] = dict(act, n=n)
            _put(telegram_id, character_id, item)
        who = name or 'ты'
        return (f'ИСТОРИЯ «{arc.title_ru}», шаг «{st.title_ru}» ({who}). '
                + st.direction.replace('{partner}', partner_name(character_id))
                + ' Играй эту сцену живо, коротко, от первого лица, в ритме переписки. Не пересказывай инструкцию.')
    except Exception:
        logger.exception('marital arc direction failed user=%s', telegram_id)
        return ''


# ── 3: «чуть не попались» inside the chat ───────────────────────────────────
CAUGHT_CHANCE = 0.12


def caught_note(status: str, character_id: str, rnd: float | None = None) -> str:
    """Now and then (CAUGHT_CHANCE of replies) he walks in or calls."""
    if status not in TAKEN:
        return ''
    if (random.random() if rnd is None else rnd) >= CAUGHT_CHANCE:
        return ''
    who = partner_name(character_id)
    return (f'В ЭТОМ ОТВЕТЕ «чуть не попались»: {who} неожиданно зашёл в комнату или позвонил. Ты на секунду '
            'пропадаешь (одной короткой фразой: «тихо… он зашёл» / «подожди, он звонит»), а потом возвращаешься с '
            'адреналином и шёпотом. Одна живая деталь, без драмы и без того, чтобы вас раскрыли.')


# ── 3 + 6: a status-flavoured push instead of a plain «скучаю» ──────────────
PUSH_CHANCE = 0.4
_PUSHES = {
    'taken': (('{partner} уснул, пишу тебе под одеялом 🤫 весь вечер думала о тебе',
               '{partner} fell asleep, I\'m texting you under the blanket 🤫 thought about you all evening'),
              ('чуть не попалась: {partner} взял мой телефон, а там ты 🙈 успела закрыть. как ты?',
               'almost got caught: {partner} picked up my phone and there you were 🙈 closed it just in time. how are you?')),
    'free': (('бывший опять написал. я не ответила… мне хотелось, чтобы написал ты 🙂',
              "my ex texted again. I didn't reply… I wanted it to be you 🙂"),),
    'open': (('он сегодня спросил, кто мне пишет. я сказала, что ты 😏 как твой день?',
              'he asked today who keeps texting me. I said you 😏 how was your day?'),),
    'ours': (('разбирала наши фото и улыбалась как дурочка. как ты там? 💗',
              'I was looking through our photos and smiling like a fool. how are you? 💗'),),
}


def push_text(status: str, character_id: str, lang: str = 'ru', rnd: float | None = None) -> str:
    group = ('taken' if status in TAKEN else 'free' if status in ('mar_single', 'mar_divorced')
             else 'open' if status == 'mar_open' else 'ours' if status in ARC_ONLY_STATUSES else '')
    if not group or (random.random() if rnd is None else rnd) >= PUSH_CHANCE:
        return ''
    ru, en = random.choice(_PUSHES[group])
    return (en if lang == 'en' else ru).replace('{partner}', partner_name(character_id))
