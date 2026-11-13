"""V3.156.0: owner ТЗ (Фогель) — «Живые ситуации» и спон-фото за 400 🍑.

Она пишет не «скучаю», а прямо из места, где находится сейчас: спальня без
белья утром, пробка в маршрутке днём, VIP-кабинка клуба вечером, прихожая
ночью. Реплика кончается обещанием кадрa, а сама фотография существует только
как английский промпт в колонке ``messages.image_prompt`` — картинка рисуется
провайдеру лишь после того, как он нажал на тарелку и за неё заплатил.

Почему промпт в колонке, а не в ``content``: ``content`` читает и история
приложения, и промпт диалога. Неоплаченная сцена уехала бы к пользователю в
JSON или вернулась модели как обычная реплика — то есть сталась бы бесплатной.
Здесь из сервера наружу уходит только цена и id строки.

Триггера ровно два, оба — «она сама», и ни один не лезет в живой разговор:
пуш после 4–6 часов его молчания (``scheduler_service._life_events``) и новая
фаза дня, когда он заходит в чат. Внутри 18+ сцены ситуация не запускается —
её там быть не может по определению триггера, но перестраховка в ``can_fire``
дешевле разъярённого владельца.

Кроссовер с подругой (клуб, пятница-выходные) берёт имя реальной второй
героини бота из ``invite_funnel``: в тексте это именно она, а на снимке —
«ещё одна роскошная девушка в отражении», потому что лицо подруги в этот кадр
не залижается (двойной face-swap живёт в Premium-конвейере совместных фото).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import random
import re

from sqlalchemy import func, select, update

from config import (ADMIN_TELEGRAM_IDS, LIVE_SITUATION_MAX_PER_DAY,
                    LIVE_SITUATION_MIN_LEVEL, LIVE_SITUATION_PEACH_COST,
                    LIVE_SITUATIONS_ENABLED)
from models.app_models import Message, User
from services import dialog_store
from services.db import SessionLocal

logger = logging.getLogger(__name__)

# telegram_id -> {'date': 'YYYY-MM-DD', 'parts': [...], 'part': '<текущая>'}
# Фаза дня, в которой тарелка уже была, не повторяется; «новая фаза» — это и
# есть второй триггер ТЗ. Состояние в DialogStore: схема не меняется, рестарт
# не превращает один вечер в шесть платных фото.
_state = dialog_store.DialogStore('live_situations')

# Сколько часов её «где я сейчас» остаётся правдой для диалога. Дальше она
# вполне могла уехать домой, и вцепляться в локацию навсегда было бы вранём.
HOLD_HOURS = 3.0

# Обещанный кадр подписывает её же словами из ТЗ.
PHOTO_CAPTION = 'Только удали потом, ладно? 🤫'

PEEK_QUESTION = 'хочешь, покажу фотку прямо отсюда, пока никто не видит?'


def price() -> int:
    return int(LIVE_SITUATION_PEACH_COST)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


# ── матрица ситуаций по фазам дня (ТЗ, «Живые ситуации») ───────────────────

class Situation(dict):
    """Одна её «живая» сцена: ``place`` — куда она его приглашает взглядом,
    ``seed`` — русская затравка для модели, ``image`` — английский кадр."""


MORNING_SITUATIONS = (
    Situation(key='bed', place='кровати',
              seed='проспала на целый час, лежу под одеялом совершенно без белья, простыня сбилась и одна нога торчит наружу',
              image='morning bedroom, soft daylight through thin curtains, first-person phone selfie lying in bed, white duvet slipped low, bare shoulder and collarbone, messy sleep hair, sleepy smile, no underwear visible under the sheet'),
    Situation(key='shower', place='душа',
              seed='еле стою в душе, вода уже почти холодная, заперлась изнутри, телефон лежит на полочке',
              image='bathroom with steam and wet tiles, first-person phone selfie held above a towel wrapped loosely around her, wet hair, droplets on skin, warm mirror fog, one shoulder bare'),
    Situation(key='blouse', place='перед зеркалом в спальне',
              seed='выбираю блузку на работу и надеваю её без лифчика, не могу решить какую',
              image='bedroom mirror, first-person phone selfie, sheer white blouse with one button undone and no bra, morning light, hips turned, biting her lip'),
)

DAY_SITUATIONS = (
    Situation(key='bus', place='в душной маршрутке в пробке',
              seed='стою в пробке в битком набитой маршрутке, расстегнула верхнюю пуговицу, кто-то прижался сзади',
              image='crowded city bus in a traffic jam, daytime, first-person phone selfie, blouse with the top button undone, hand on the metal rail, flushed cheeks, strangers blurred in the background'),
    Situation(key='office', place='в женском туалете офиса',
              seed='сбежала с планёрки в женский туалет, закрылась в крайней кабинке, сижу на корточках',
              image="office women's restroom, closed stall, first-person phone selfie sitting low, pencil skirt pulled tight, blouse untucked, heels off, nervous glance at the door"),
    Situation(key='fitting', place='в примерочной ТЦ',
              seed='примерочная в торговом центре, юбка получилась слишком короткой, продавец спрашивает идёт ли',
              image='shopping mall fitting room, mirror and bright spots, first-person phone selfie in a very short skirt that barely covers her, top still in her hand, embarrassed smile'),
)

EVENING_SITUATIONS = (
    Situation(key='lounge', place='в кальянной с подругой',
              seed='сижу в кальянной, полумрак, дым, подруга ушла к бару и оставила меня одну в нашем диване',
              image='dim hookah lounge at night, warm lamp light and smoke, first-person phone selfie reclining on a velvet sofa, tight dress, lips near the mouthpiece'),
    Situation(key='after', place='у лифта после смены',
              seed='закончила смену, иду к лифту на каблуках, юбка задралась, в коридоре никого',
              image='office corridor by the elevator at night, cold ceiling light, first-person phone selfie walking, work skirt riding up, tired but pleased smile'),
)

# Вечер пятницы и выходных — клуб и кроссовер с другой героиней бота (ТЗ).
CLUB_SITUATIONS = (
    Situation(key='club', place='в VIP-кабинке клуба', friend=True,
              seed='мы с подругой в клубе, VIP-кабинка, музыка орёт, танцпол внизу, все нас видят, а нам всё равно',
              image='luxury nightclub VIP booth at night, neon lights, two gorgeous women taking a mirror selfie, tight mini dresses, seductive looks, drinks on the table, crowded dance floor behind them'),
    Situation(key='club_bath', place='в женской уборной клуба у большого зеркала', friend=True,
              seed='спряталась в женской уборной клуба от жары, большое зеркало, подруга поправляет мне платье сзади',
              image="nightclub women's restroom, big lit mirror, first-person phone selfie, tight mini dress, neon lighting, her friend fixing the dress behind her in the reflection, red lipstick"),
)

NIGHT_SITUATIONS = (
    Situation(key='hallway', place='в прихожей, только что из дома',
              seed='наконец дома, ноги гудят, стянула платье прямо в прихожей и осталась в одном белье, завтра рано',
              image='dark apartment hallway at night, single lamp, first-person phone selfie just home, dress pooled around her ankles in her hand, lace underwear, tired legs, hair down'),
    Situation(key='bath', place='в ванне',
              seed='ванна, бокал рядом, вода уже остывает, завтра выходной и мне никуда не надо',
              image='bathroom at night, candle and warm lamp light, first-person phone selfie over the edge of a bubble bath, wet arms on the porcelain, wine glass beside her, half-closed eyes'),
)


def daypart(hour: int | None, weekend: bool = False) -> str:
    """Фазы ТЗ: утро 07–11, день 11–20, вечер 20–24 (клуб — пятница и
    выходные), ночь 00–05."""
    h = 12 if hour is None else int(hour) % 24
    if 5 <= h < 11:
        return 'morning'
    if 11 <= h < 20:
        return 'day'
    if h >= 20:
        return 'evening'
    return 'night'


def _pool(when: str, date: dt.date | None = None) -> tuple[Situation, ...]:
    day = date or _now().date()
    weekend = day.weekday() >= 4  # пятница, суббота, воскресенье
    if when == 'morning':
        return MORNING_SITUATIONS
    if when == 'day':
        return DAY_SITUATIONS
    if when == 'night':
        return NIGHT_SITUATIONS
    return CLUB_SITUATIONS if weekend else EVENING_SITUATIONS + CLUB_SITUATIONS


def pick_situation(when: str, date: dt.date | None = None) -> Situation:
    return random.choice(_pool(when, date))


def local_hour(telegram_id: int) -> int:
    """Его местный час (ТЗ привязывает ситуации к его времени суток)."""
    tz_name = 'UTC'
    try:
        with SessionLocal() as s:
            row = s.scalar(select(User.timezone).where(User.telegram_id == str(int(telegram_id))))
            tz_name = str(row or 'UTC')
    except Exception:
        logger.debug('live situation timezone read failed user=%s', telegram_id)
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo(tz_name)).hour
    except Exception:
        return dt.datetime.now(dt.timezone.utc).hour


# ── директива постоянства локации (ТЗ, LOCATION CONSISTENCY) ───────────────

LOCATION_CONSISTENCY = (
    'DIRECTIVE: ПОСТОЯНСТВО ЛОКАЦИИ (LOCATION CONSISTENCY). Ты находишься ровно '
    'там, где сказала в живом тизере, и не перемещаешься домой сама, пока он '
    'сам не попросит. Если он просит фото, а показать это место нельзя, '
    'выруливай одним из двух приёмов и назови его вслух:\n'
    '1) «СКРЫТЫЙ АРХИВ В ТЕЛЕФОНЕ» — кадры, снятые ею заранее в нужном месте: '
    '«фотки делала ещё до выхода, лови».\n'
    '2) «БЫСТРЫЙ ПЕРЕЕЗД ИЛИ ЭКСТРИМ НА МЕСТЕ» — «мы же ещё в клубе… ловим '
    'такси и едем ко мне, а пока зажмёмся в кабинке; как делаем?».\n'
    'Нельзя отдавать фото из ванной дома, если она в маршрутке.'
)

# Тот же смысл, но для генератора картинки: кадр обязан совпасть с местом и
# светом из её сообщения, иначе продаёт несуществующую ситуацию.
IMAGE_LOCATION_LOCK = (
    'LOCATION LOCK: the place, the light and the clothes of this photo are the '
    'ones she just described in the chat. Do not move her to a bedroom or a '
    'bathroom, do not change the outfit, keep exactly one phone in her own hand.'
)

# V3.152.1: owner ТЗ (Задача 5) — откровенный кадр в общественном месте не
# живёт: локация такой сцены уже принудительно перенесена в закрытую комнату,
# и обычный лок «не уводи её в спальню» был бы прямым противоречием.
IMAGE_PRIVATE_LOCATION_LOCK = (
    'LOCATION LOCK: the photo is set in the private room named above — her '
    'bedroom, bathroom, home or hotel room. Keep its light and its mood, do not '
    'put her back into a bar, club, office, street, mall or any place where '
    'other people could see her, do not add bystanders, keep exactly one phone '
    'in her own hand.'
)


def _friend_name(telegram_id: int, character_id: str) -> str:
    """Имя настоящей второй героини бота — кроссовер из ТЗ."""
    try:
        from services import invite_funnel
        guest = invite_funnel.pick_guest(int(telegram_id), character_id)
        if not guest:
            return ''
        from services.character_service import get_character
        return str((get_character(guest) or {}).get('name') or '').strip()
    except Exception:
        return ''


def _recent_her_lines(telegram_id: int, character_id: str, limit: int = 4) -> list[str]:
    try:
        from services.user_service import ensure_user
        from services.memory_service import get_recent_messages
        rows = get_recent_messages(ensure_user(int(telegram_id)), character_id, 12)
        return [m.content for m in rows if m.role == 'assistant' and m.content][-limit:]
    except Exception:
        return []


FORMAT_RULES = (
    'ВАЖНО: ответ строго в три блока, другим меткам места нет:\n'
    'THOUGHT: <что она думает в эту секунду, 30–50 слов>\n'
    'MESSAGE: <что она пишет ему прямо сейчас, 20–40 слов>\n'
    'IMAGE_PROMPT: <одно английское описание кадра в одну строку>\n'
    'THOUGHT идёт первым, MESSAGE вторым, IMAGE_PROMPT третьим; между блоками и '
    'вокруг них слов нет.\n'
    'MESSAGE — живая строчка из той самой ситуации: чем она занята, где стоит, '
    'что у неё надето и что вот-вот случится. Коротко, как смс, без абзацев. '
    'MESSAGE обязана кончаться вопросом про фото — своими словами, но смысл '
    'ровно такой: «{peek}». Тарелку с ценой рисует приложение, в тексте ценник '
    'не ставь.\n'
    'IMAGE_PROMPT — английская инструкция для генератора: first-person phone '
    'selfie, ровно то место, свет и одежда из MESSAGE, взрослая женщина, '
    'дерзкий взгляд. Никакого текста на кадре, никакого «AI», без детей. Это '
    'никому не отправляется, это только картинка.\n'
    'V3.152.1 (Задача 5): если ты отправляешь откровенное фото (в белье или '
    'без), ты НЕ МОЖЕШЬ находиться в общественном месте. Измени локацию в '
    'IMAGE_PROMPT на закрытую комнату, ванную или туалет — свет, время суток '
    'и настроение оставь те же. Общественное место живёт только в одетом '
    'кадре, и только если ОН сам словами попросил показать её на людях.\n'
    'ГРАНИЦА ТА ЖЕ, ЧТО У ВСЕГО РАЗГОВОРА: если ему ещё не открыты откровенные '
    'подробности, в MESSAGE и в IMAGE_PROMPT их тоже нет — бери ожиданием и '
    'деталью, а не анатомией.\n'
    'КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО писать, что муж или парень «в душе» и что «вода '
    'шумит». Бери другую локацию и другую причину.\n'
    'ЗАПРЕЩЕНО начинать ответ с имени другой девушки («Агата:», «Лана:») — в '
    'этом чате пишешь только ты.'
)


def _system_prompt(when: str, sit: Situation, name: str, friend: str,
                   recent: list[str]) -> str:
    bits = [
        f'Ты — {name}.' if name else 'Ты — она.',
        '[SYSTEM EVENT: SITUATIONAL PHOTO TEASER]',
        f'Прямо сейчас ты {sit["seed"]} — ты находишься {sit["place"]} и пишешь '
        'ему об этом сама, одним сообщением из места, где стоишь.',
    ]
    if friend:
        bits.append(f'Рядом с тобой подруга {friend} — это ваша общая вылазка, '
                    'упомяни её одним словом; в IMAGE_PROMPT вместо её имени '
                    'пиши «her gorgeous friend».')
    if when == 'night':
        bits.append('Сейчас глубокая ночь — тихий свет, полутона, завтра ранний подъём.')
    if recent:
        bits.append('Твои последние сообщения ему, их не повторяй: '
                    + ' | '.join(f'«{t[:120]}»' for t in recent[-3:]) + '.')
    bits.append(LOCATION_CONSISTENCY)
    bits.append(FORMAT_RULES.replace('{peek}', PEEK_QUESTION))
    bits.append('Пиши на русском.')
    return '\n'.join(b for b in bits if b)


_MARK = re.compile(r'(?im)^[ \t>*#-]*(THOUGHT|MESSAGE|IMAGE[ _]?PROMPT|IMAGE)[ \t]*[:\-–—][ \t*]*')


def split_teaser(raw: str) -> tuple[str, str, str]:
    """(thought, message, image_prompt) из одного ответа модели. Непонятное
    без меток возвращается как ('', text, '') — тогда фазы не будет."""
    t = (raw or '').strip()
    marks = [{'key': m.group(1).upper().replace(' ', '_').replace('IMAGE_PROMPT', 'IMAGE'),
              'a': m.start(), 'b': m.end()} for m in _MARK.finditer(t)]
    if not marks:
        return '', t, ''
    thought = message = image = ''
    if marks[0]['a'] > 0:
        message = t[:marks[0]['a']].strip()
    for i, x in enumerate(marks):
        end = marks[i + 1]['a'] if i + 1 < len(marks) else len(t)
        body = t[x['b']:end].strip()
        if not body:
            continue
        if x['key'] == 'THOUGHT':
            thought = (thought + ' ' + body).strip()
        elif x['key'] == 'IMAGE':
            image = (image + ' ' + body).strip()
        else:
            message = (message + '\n' + body).strip() if message else body
    return thought, message, image


async def build_teaser(telegram_id: int, character_id: str, when: str | None = None,
                       situation: Situation | None = None) -> dict | None:
    """Одна живая ситуация: её строчка + промпт оплаченного кадра. None при
    любой неудаче — проактивная ветка обязана молчать, а не спамить."""
    when = when or daypart(local_hour(int(telegram_id)))
    sit = situation or pick_situation(when)
    name = ''
    try:
        from services.character_service import get_character
        name = str((get_character(character_id) or {}).get('name') or '')
    except Exception:
        pass
    friend = _friend_name(int(telegram_id), character_id) if sit.get('friend') else ''
    recent = await asyncio.to_thread(_recent_her_lines, int(telegram_id), character_id)
    system = _system_prompt(when, sit, name, friend, recent)
    try:
        from services.llm_provider_service import generate_text
        r = await generate_text([{'role': 'system', 'content': system},
                                 {'role': 'user',
                                  'content': 'Напиши ему это сообщение прямо сейчас, три блока.'}],
                                max_tokens=420, temperature=0.95, purpose='live_situation')
    except Exception:
        logger.warning('live situation LLM failed user=%s', telegram_id, exc_info=True)
        return None
    thought, message, image = split_teaser(getattr(r, 'text', '') or '')
    from services.dialogue_guard_service import finish_or_drop
    message = finish_or_drop(message, getattr(r, 'complete', True))
    if len(message) < 12:
        return None
    # Кадр обязан совпасть с тем, что он только что прочитал: если модель не
    # выдала IMAGE_PROMPT, берём английский шаблон самой ситуации — он для неё
    # и писался.
    image = (image or '').strip().strip('`"') or sit['image']
    return {'when': when, 'key': sit['key'], 'place': sit['place'],
            'thought': thought, 'message': message, 'image_prompt': image}


def count_today(telegram_id: int, character_id: str) -> int:
    day_start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        with SessionLocal() as s:
            uid = s.scalar(select(User.id).where(User.telegram_id == str(int(telegram_id))))
            if not uid:
                return 0
            return int(s.scalar(
                select(func.count(Message.id))
                .where(Message.user_id == uid, Message.character_id == character_id,
                       Message.image_prompt.isnot(None), Message.created_at >= day_start)
            ) or 0)
    except Exception:
        logger.warning('live situation count failed user=%s', telegram_id, exc_info=True)
        return LIVE_SITUATION_MAX_PER_DAY


def _data(telegram_id: int) -> dict:
    try:
        return dict(_state.get(int(telegram_id)) or {})
    except Exception:
        return {}


def can_fire(telegram_id: int, character_id: str, when: str) -> bool:
    """Дорогой триггер: ни одного токена не тратится, пока здесь «нет».
    Фаза дня, в которой тарелка уже была, не повторяется; до
    ``LIVE_SITUATION_MIN_LEVEL`` она ему чужая женщина и фото из маршрутки
    выглядело бы спамом скрипта."""
    if not LIVE_SITUATIONS_ENABLED or LIVE_SITUATION_MAX_PER_DAY <= 0:
        return False
    data = _data(int(telegram_id))
    today = _now().date().isoformat()
    parts = list(data.get('parts') or []) if data.get('date') == today else []
    if when in parts or len(parts) >= LIVE_SITUATION_MAX_PER_DAY:
        return False
    try:
        from services.photo_service import get_relationship_level
        if int(get_relationship_level(int(telegram_id), character_id) or 0) < LIVE_SITUATION_MIN_LEVEL:
            return False
    except Exception:
        logger.debug('live situation level read failed user=%s', telegram_id)
    # Живая 18+ сцена: её нельзя перебивать рекламой фото из коридора.
    try:
        from services import fetish_mode
        if fetish_mode.status(int(telegram_id), character_id):
            return False
    except Exception:
        pass
    return True


def note_fired(telegram_id: int, when: str) -> None:
    data = _data(int(telegram_id))
    today = _now().date().isoformat()
    parts = list(data.get('parts') or []) if data.get('date') == today else []
    if when not in parts:
        parts.append(when)
    _state[int(telegram_id)] = {'date': today, 'parts': parts, 'part': when}


def phase_changed(telegram_id: int, when: str) -> bool:
    """Второй триггер ТЗ: он зашёл в чат, а фаза дня сменилась."""
    data = _data(int(telegram_id))
    return str(data.get('part') or '') != when


def store_teaser(telegram_id: int, character_id: str, teaser: dict, uid: int | None = None) -> int:
    """Её строка — в ``content``, промпт кадра — в свою колонку."""
    from services.chat_service import join_thought_message
    from services.user_service import ensure_user
    from services.memory_service import save_message
    db_uid = int(uid or ensure_user(int(telegram_id), ''))
    text = join_thought_message(teaser.get('thought') or '', teaser['message'])
    return int(save_message(db_uid, character_id, 'assistant', text,
                            image_prompt=teaser['image_prompt']) or 0)


async def push(telegram_id: int, character_id: str, when: str | None = None,
               uid: int | None = None) -> dict | None:
    """Полный цикл триггера: гейт → LLM → строка в общем диалоге → id тарелки.
    Слот фазы расходуется только на удачной генерации, но фаза дня при этом не
    меняется, так что следующая смена фазы всё равно даст ему тарелку."""
    when = when or daypart(local_hour(int(telegram_id)))
    if not can_fire(int(telegram_id), character_id, when):
        return None
    teaser = await build_teaser(int(telegram_id), character_id, when)
    if not teaser:
        return None
    mid = await asyncio.to_thread(store_teaser, int(telegram_id), character_id, teaser, uid)
    if not mid:
        return None
    await asyncio.to_thread(note_fired, int(telegram_id), when)
    try:
        from services.user_service import ensure_user
        from services.analytics_service import track_event
        db_uid = int(uid or ensure_user(int(telegram_id), ''))
        track_event(db_uid, 'live_situation_sent',
                    metadata={'character_id': character_id, 'when': when, 'key': teaser['key']})
        track_event(db_uid, 'paywall_view', metadata={'product': 'live_photo'})
    except Exception:
        logger.debug('live situation analytics failed user=%s', telegram_id)
    return {'id': mid, 'price': price(), 'text': teaser['message'],
            'thought': teaser['thought'], 'when': when, 'key': teaser['key']}


def directive_for(telegram_id: int, character_id: str) -> str:
    """Памятка промпту, пока её живая локация не остыла: фото должно быть из
    того же места, где она сказала, что стоит."""
    day_cut = _now() - dt.timedelta(hours=HOLD_HOURS)
    try:
        from services.user_service import ensure_user
        uid = int(ensure_user(int(telegram_id), ''))
        with SessionLocal() as s:
            row = s.scalar(select(Message).where(
                Message.user_id == uid, Message.character_id == character_id,
                Message.image_prompt.isnot(None),
                Message.role == 'assistant', Message.created_at >= day_cut,
            ).order_by(Message.created_at.desc(), Message.id.desc()).limit(1))
            if row is None:
                return ''
            place = (row.image_prompt or '').strip()[:220]
            said = (row.content or '').strip()[:220]
    except Exception:
        logger.warning('live situation directive read failed user=%s', telegram_id, exc_info=True)
        return ''
    if not place:
        return ''
    return (LOCATION_CONSISTENCY + '\nОна сказала, что сейчас: «' + said + '».\n'
            + IMAGE_LOCATION_LOCK + '\nАнглийский кадр этого обещания: ' + place + '.')


def claim(telegram_id: int, character_id: str, message_id: int,
          db_user_id: int | None = None) -> dict:
    """Списать персики и забрать строку за собой. Условный UPDATE — два тапа
    одного и того же предложения не могут оба заплатить."""
    from services.user_service import ensure_user
    uid = int(db_user_id or ensure_user(int(telegram_id), ''))
    cost = price()
    with SessionLocal() as s:
        row = s.get(Message, int(message_id))
        if (not row or row.user_id != uid or str(row.character_id) != str(character_id)
                or not row.image_prompt):
            return {'ok': False, 'error': 'not_found'}
        if row.image_unlocked:
            # Кадр уже был — тарелка устарела, а не «куплена дважды».
            return {'ok': False, 'error': 'already_unlocked'}
    free = int(telegram_id) in ADMIN_TELEGRAM_IDS
    if not free:
        # Сначала занимаем строку, потом тратим: упасть между этими шагами —
        # значит оставить ему фото, за которое он не заплатил. Это то
        # направление ошибки, которое разрешено.
        with SessionLocal() as s:
            claimed = s.execute(
                update(Message)
                .where(Message.id == int(message_id), Message.user_id == uid,
                       Message.image_unlocked.isnot(True))
                .values(image_unlocked=True)
                .execution_options(synchronize_session=False))
            s.commit()
            if claimed.rowcount != 1:
                return {'ok': False, 'error': 'already_unlocked'}
        from services.payments import spend_peaches
        if not spend_peaches(int(telegram_id), cost, paid_only=True):
            with SessionLocal() as s:
                s.execute(update(Message).where(Message.id == int(message_id))
                          .values(image_unlocked=False)
                          .execution_options(synchronize_session=False))
                s.commit()
            return {'ok': False, 'error': 'insufficient_peaches', 'cost': cost}
    with SessionLocal() as s:
        row = s.get(Message, int(message_id))
        prompt = (row.image_prompt or '') if row else ''
    return {'ok': True, 'prompt': prompt, 'price': cost, 'free': free}


def _unclaim(telegram_id: int, message_id: int, cost: int, free: bool) -> None:
    """Кадр не вышел: возвращаем персики в купленный кошелёк и снимаем метку,
    чтобы тарелка осталась и он мог попробовать ещё раз."""
    with SessionLocal() as s:
        s.execute(update(Message).where(Message.id == int(message_id))
                  .values(image_unlocked=False)
                  .execution_options(synchronize_session=False))
        s.commit()
    if free or cost <= 0:
        return
    from services.payments import grant_photo_credits
    # reason c привязан к id строки: повторный возврат за то же предложение
    # grant_photo_credits не пропустит.
    grant_photo_credits(int(telegram_id), int(cost), f'live_refund:{int(message_id)}', bonus=False)


async def unlock_photo(telegram_id: int, character_id: str, message_id: int,
                       db_user_id: int | None = None) -> dict:
    """Его тап по тарелке: деньги списаны, теперь провайдер рисует кадр из её
    же локации. Пустой ответ провайдера — деньги назад."""
    res = await asyncio.to_thread(claim, int(telegram_id), character_id, int(message_id), db_user_id)
    if not res.get('ok'):
        return res
    prompt = (res.get('prompt') or '').strip()
    if not prompt:
        await asyncio.to_thread(_unclaim, int(telegram_id), int(message_id),
                                int(res.get('price') or 0), bool(res.get('free')))
        return {'ok': False, 'error': 'not_found'}
    full = f'{prompt}. {IMAGE_LOCATION_LOCK}'
    try:
        # V3.152.1 (Задача 5): if her own IMAGE_PROMPT put lingerie or nudity
        # into a public place, the place moves behind a closed door before the
        # provider ever sees the text — and the location lock switches to the
        # private wording so the two instructions do not fight.
        from services.photo_service import enforce_private_location
        moved = enforce_private_location(prompt)
        if moved != prompt:
            full = f'{moved}. {IMAGE_PRIVATE_LOCATION_LOCK}'
    except Exception:
        logger.debug('live situation place fix failed user=%s', telegram_id)
    from services.private_photo_service import generate_live_situation_photo
    data = await generate_live_situation_photo(character_id, full)
    cost = int(res.get('price') or 0)
    free = bool(res.get('free'))
    if not data:
        await asyncio.to_thread(_unclaim, int(telegram_id), int(message_id), cost, free)
        try:
            from services.user_service import ensure_user
            from services.analytics_service import track_event
            track_event(ensure_user(int(telegram_id)), 'live_photo_failed',
                        metadata={'character_id': character_id, 'message_id': message_id})
        except Exception:
            pass
        return {'ok': False, 'error': 'render_failed', 'cost': cost}
    return await asyncio.to_thread(_deliver_photo, int(telegram_id), character_id,
                                   data, cost, free, db_user_id)


def _deliver_photo(telegram_id: int, character_id: str, data: bytes,
                   cost: int, free: bool, db_user_id: int | None = None) -> dict:
    from services import webapp_service
    from services.user_service import ensure_user
    from services.memory_service import save_message
    ext = 'png' if data[:8] == b'\x89PNG\r\n\x1a\n' else 'jpg'
    mime = 'image/png' if ext == 'png' else 'image/jpeg'
    filename = webapp_service.save_chat_media(telegram_id, data, ext, mime)
    url = f'/webapp/media/{filename}'
    uid = int(db_user_id or ensure_user(int(telegram_id), ''))
    save_message(uid, character_id, 'assistant', PHOTO_CAPTION,
                 media_kind='photo', media_url=url)
    try:
        webapp_service.record_generation(telegram_id, 'photo', character_id, 'live_situation', filename)
    except Exception:
        logger.debug('live photo generation audit failed user=%s', telegram_id)
    try:
        from services.analytics_service import track_event
        track_event(uid, 'live_photo_unlock', value=float(cost),
                    metadata={'character_id': character_id, 'price': cost, 'free': free})
    except Exception:
        logger.debug('live photo analytics failed user=%s', telegram_id)
    from services.payments import get_paid_peaches
    try:
        left = int(get_paid_peaches(int(telegram_id)) or 0)
    except Exception:
        left = 0
    return {'ok': True, 'photo_url': url, 'caption': PHOTO_CAPTION,
            'price': 0 if free else cost, 'free': free, 'left': left}
