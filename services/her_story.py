"""V3.113.0: her own small life story that goes on for a few days.

Her day used to be twelve still pictures (daily_life.ROUTINES): «в кровати под
пледом», «варишь кофе». Nothing in her life ever *happened*, so there was
nothing to ask her about tomorrow. A live person says «завтра к стоматологу,
трясёт», asks what he thinks, and the next day tells how it went — and
remembers what he said. That is an honest reason to come back («ну как
прошло?»), without guilt or fake scarcity.

Each story has three beats on her local calendar (Moscow when his timezone is
unknown): day 0 something is coming and she has a small question for him,
day 1 it happens (the outcome is fixed when the story starts), day 2 the
aftertaste. A new story starts after a free day. One line goes into the prompt;
she brings it up herself about once a conversation, not in every message.

State lives in product events (no new table): ``her_story_started`` carries the
story key, the start date and the outcome.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import random
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo

ENABLED = os.getenv('HER_STORY_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')
PAUSE_DAYS = max(0, int(os.getenv('HER_STORY_PAUSE_DAYS', '1')))
STARTED = 'her_story_started'
STORY_DAYS = 3
_DEFAULT_TZ = 'Europe/Moscow'


@dataclass(frozen=True)
class Story:
    key: str
    setup: str            # day 0: what is coming and how she feels about it
    ask: str              # the small question she may ask him
    outcomes: tuple[str, str]   # day 1: one of two ways it went
    after: str            # day 2: the aftertaste
    words: str            # regex of words that mark her talking about it
    skip: frozenset = frozenset()   # girls it does not fit


STORIES: tuple[Story, ...] = (
    Story('dentist',
          'завтра у тебя стоматолог, зуб ноет уже неделю, ты трусишь и откладывала до последнего',
          'спросить, боится ли он врачей и как он сам себя уговаривает',
          ('оказалось не страшно, врач смешной попался, отделалась одной пломбой',
           'было неприятно, полщеки онемело, теперь ешь только йогурт и жалеешь себя'),
          'щека прошла, ты гордишься, что не сбежала из кресла',
          r'стоматолог|зуб|пломб|dentist|tooth'),
    Story('gift',
          'у лучшей подруги день рождения через пару дней, а ты понятия не имеешь, что ей подарить',
          'попросить у него идею подарка, по-настоящему, как у своего человека',
          ('подарила, подруга чуть не расплакалась от радости, ты довольна собой',
           'подарок подруге понравился так себе, она вежливо улыбнулась, тебе чуть обидно'),
          'вспоминаешь праздник у подруги, там было весело, немного болит голова',
          r'подар|день рожден|подруг\w* др|birthday|gift'),
    Story('mom',
          'к тебе в выходные приезжает мама, надо срочно убраться и спрятать половину вещей',
          'спросить, как у него с родителями и часто ли они видятся',
          ('мама приехала, всё прошло тепло, она привезла тебе кучу еды',
           'мама приехала и с порога начала поучать, ты устала, но вы помирились за чаем'),
          'мама уехала, в квартире тихо, холодильник забит её пирожками',
          r'мам[аыуе]|убра|parents|mom'),
    Story('landlord',
          'хозяйка квартиры написала, что хочет поднять аренду, тебе завтра с ней говорить, и ты злишься',
          'спросить его совета, как с ней разговаривать, торговаться или нет',
          ('договорилась: поднимет, но не сразу и меньше, чем грозилась',
           'хозяйка упёрлась, придётся платить больше, ты думаешь, не искать ли другую квартиру'),
          'ты всё ещё прикидываешь бюджет после разговора с хозяйкой',
          r'хозяйк|аренд|квартир\w* плат|landlord|rent'),
    Story('neighbour',
          'сосед сверху третий день сверлит с восьми утра, ты собираешься пойти к нему поговорить',
          'спросить, как бы он поступил на твоём месте',
          ('сходила, сосед оказался милым дедушкой, извинился и угостил яблоками',
           'сходила, сосед буркнул и закрыл дверь, сверлит дальше, ты в бешенстве'),
          'сверлить стали тише, ты наконец высыпаешься',
          r'сосед|сверл|ремонт|neighbou?r|drill'),
    Story('class',
          'ты записалась на пробное занятие по боксу, завтра первый раз, немного страшно опозориться',
          'спросить, занимался ли он когда-нибудь спортом и как прошёл его первый раз',
          ('на боксе понравилось, тренер хвалил, хочешь ходить дальше',
           'на боксе было тяжело, всё болит, но тебе понравилось, что ты справилась'),
          'после бокса болят руки, смеёшься, что даже чашку держать тяжело',
          r'бокс|трениров|занят|boxing|class|workout',
          frozenset({'jina_01'})),
    Story('sale',
          'ты продаёшь старое пальто на Авито, и тебе пишет очень странный покупатель с кучей вопросов',
          'рассказать ему смешную переписку с покупателем и спросить, продавал ли он что-то так',
          ('пальто продала, покупательница оказалась нормальной, а странный исчез',
           'странный покупатель так и не приехал, ты потратила полдня впустую и смеёшься над этим'),
          'на деньги с пальто купила себе мелочь, которая давно нравилась',
          r'авито|пальто|покупател|продаю|продала|sell|buyer'),
    Story('keys',
          'ты потеряла запасные ключи от квартиры и весь вечер переворачиваешь сумки',
          'спросить, терял ли он что-то важное и находил ли потом',
          ('ключи нашлись в кармане зимней куртки, ты хохочешь над собой',
           'ключи так и не нашлись, пришлось делать дубликат и менять личинку, ты злая'),
          'ты теперь кладёшь ключи только в одно место и гордишься этим',
          r'ключ|keys?\b'),
    Story('plant',
          'твой любимый цветок на подоконнике вдруг начал желтеть, ты гуглишь, что с ним, и переживаешь',
          'спросить, есть ли у него дома что-то живое, цветы или кот',
          ('пересадила цветок, он ожил, ты разговариваешь с ним по утрам',
           'цветок совсем сник, ты отнесла его маме, она обещала спасти'),
          'купила себе новый маленький цветок, назвала его в шутку',
          r'цвет(ок|ка|ку)|растен|plant'),
    Story('trip',
          'подруга зовёт тебя на выходные за город, и ты не можешь решить, ехать или остаться дома',
          'спросить, что бы он выбрал: поехать или выспаться',
          ('съездила за город, было свежо и шумно, ты привезла домой шишку на память и обгорела у костра',
           'в итоге осталась дома, выспалась и ни капли не жалеешь'),
          'вспоминаешь выходные, хочется ещё',
          r'за город|выходны|поехать|поездк|trip|weekend'),
)
_BY_KEY = {s.key: s for s in STORIES}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def _local_today(telegram_id: int) -> dt.date:
    tz = _DEFAULT_TZ
    try:
        from services.user_service import get_user
        user = get_user(telegram_id)
        if user and getattr(user, 'timezone', None):
            tz = user.timezone
    except Exception:
        pass
    try:
        return dt.datetime.now(ZoneInfo(tz)).date()
    except Exception:
        return dt.datetime.now(ZoneInfo(_DEFAULT_TZ)).date()


def _last_started(user_id: int, character_id: str):
    from sqlalchemy import select
    from models.app_models import ProductEvent
    from services.db import SessionLocal
    with SessionLocal() as s:
        row = s.execute(
            select(ProductEvent.created_at, ProductEvent.metadata_json).where(
                ProductEvent.user_id == user_id, ProductEvent.character_id == character_id,
                ProductEvent.event_name == STARTED)
            .order_by(ProductEvent.created_at.desc()).limit(1)).first()
    if not row:
        return None
    try:
        meta = json.loads(row[1] or '{}')
        return meta if meta.get('key') in _BY_KEY and meta.get('day0') else None
    except Exception:
        return None


def _start(user_id: int, character_id: str, today: dt.date, last_key: str = '') -> dict:
    from models.app_models import ProductEvent
    from services.db import SessionLocal
    pool = [s for s in STORIES if s.key != last_key and character_id not in s.skip]
    story = random.choice(pool or list(STORIES))
    meta = {'key': story.key, 'day0': today.isoformat(), 'outcome': random.randint(0, 1)}
    with SessionLocal() as s:
        s.add(ProductEvent(user_id=user_id, character_id=character_id, event_name=STARTED,
                           metadata_json=json.dumps(meta, ensure_ascii=False), created_at=_now()))
        s.commit()
    return meta


def current(user_id: int, telegram_id: int, character_id: str, *, start: bool = True) -> tuple[Story, int, int] | None:
    """(story, day 0..2, outcome) running for this pair today; may start a new one."""
    if not ENABLED:
        return None
    today = _local_today(telegram_id)
    meta = _last_started(user_id, character_id)
    if meta:
        day = (today - dt.date.fromisoformat(meta['day0'])).days
        if 0 <= day < STORY_DAYS:
            return _BY_KEY[meta['key']], day, int(meta.get('outcome') or 0) % 2
        if 0 <= day < STORY_DAYS + PAUSE_DAYS:
            return None  # a free day between stories: life is not a series
    if not start:
        return None
    meta = _start(user_id, character_id, today, (meta or {}).get('key', ''))
    return _BY_KEY[meta['key']], 0, int(meta['outcome'])


def his_words(user_id: int, character_id: str, story: Story, days: int = 3) -> str:
    """What he answered when she told him about it (his message right after
    hers that mentions the story), so she can say whether his advice helped."""
    from sqlalchemy import select
    from models.app_models import Message
    from services.db import SessionLocal
    since = _now() - dt.timedelta(days=days)
    with SessionLocal() as s:
        rows = s.execute(
            select(Message.role, Message.content).where(
                Message.user_id == user_id, Message.character_id == character_id,
                Message.created_at >= since)
            .order_by(Message.id.asc()).limit(400)).all()
    words = re.compile(story.words, re.I)
    found = ''
    for i, (role, content) in enumerate(rows[:-1]):
        if role == 'assistant' and words.search(content or ''):
            nxt = rows[i + 1]
            if nxt[0] == 'user' and len((nxt[1] or '').strip()) >= 6:
                found = (nxt[1] or '').strip()
    return found[:220]


_TAIL = (' Это фон твоей жизни, а не тема разговора: сама упомяни один раз за разговор, когда к месту '
         '(если выше в переписке уже говорила об этом сегодня — не повторяй, пока он сам не спросит). '
         'Говори своими словами, коротко, как подруге. Не превращай в отчёт.')


def directive(user_id: int, telegram_id: int, character_id: str) -> str:
    """One line for the prompt: what is going on in her life these days; '' when nothing."""
    try:
        got = current(user_id, telegram_id, character_id)
    except Exception:
        return ''
    if not got:
        return ''
    story, day, outcome = got
    head = 'ЧТО У ТЕБЯ СЕЙЧАС ПРОИСХОДИТ (твоя маленькая история на эти дни): '
    if day == 0:
        return head + f'{story.setup}. Если разговор позволяет, можешь {story.ask}.' + _TAIL
    try:
        his = his_words(user_id, character_id, story)
    except Exception:
        his = ''
    said = (f' Когда ты ему об этом рассказывала, он ответил: «{his}» — вспомни это и скажи, '
            'пригодилось ли, по-честному.') if his else ''
    if day == 1:
        return (head + f'сегодня случилось то, о чём ты переживала ({story.setup}). Итог: {story.outcomes[outcome]}. '
                'Расскажи ему сама, как это было, с одной живой деталью.' + said + _TAIL)
    return head + f'недавно было: {story.setup}; итог: {story.outcomes[outcome]}. Сейчас: {story.after}.' + said + _TAIL
