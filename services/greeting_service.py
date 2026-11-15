"""V3.166.4 (Блоки 2–4, владелец): база стартовых сообщений + механика тизера.

Открытие чата — это готовая строка из базы заготовок и чипы под ней. Картинки
тут больше нет: фото приходит ТОЛЬКО когда он тапнул чип «Покажи / Скинь фото»,
и только в режиме «Без цензуры 18+». Тогда срабатывает кэш стартовых кадров
(``services/starter_photo_service``): четвёрка на пару «героиня × сценарий» уже
собрана — отдаём случайный кадр моментально и бесплатно, не собрана — рисуем
один по скрытому английскому промпту сценария (``image_prompt``) и кладём в
кэш. Для него это стоит нуля персиков и не трогает дневное бесплатное фото:
это воронка, а не товар.

V3.166.5 (владелец: «немота»): у заготовки появился ещё и ``reply_text`` — то,
что она говорит СРАЗУ ПЕРЕД кадром, который пообещала. Молчаливая фотка
выглядела файлом из архива, а не её сообщением; теперь тап чипа — это реплика,
и сразу следом кадр.

Романтика («Романтика и флирт») механику не видит: там, как и раньше, она
пишет сама. Перевод сценария по-прежнему платится ОДИН раз и хранится в
``translations_json``.
"""
import json
import logging
import random
import time

from sqlalchemy import delete as sql_delete, func, select

from models.app_models import CharacterGreeting
from services.db import SessionLocal

logger = logging.getLogger(__name__)

UNIVERSAL_ID = 'all'
MODES = ('normal', 'spicy', 'both')

# Блок 4 ТЗ V3.166.0: шесть его личных сцен топ-6 героинь. Владелец: «Мои
# личные заготовки для топ-6 героинь не трогай — я их сам потом настрою», так
# что скрытого промпта кадра и реплики перед ним у них нет (пустые строки).
SEED_PERSONAL = [
    ('anna_01',
     'Я стою у панорамного окна в одном кружевном белье... Внизу ночной город, а я думаю только о том, '
     'как бы ты сейчас подошёл сзади, крепко обнял и провел руками по моим бедрам. '
     'Ты заставишь меня ждать всю ночь или приедешь прямо сейчас?',
     ['Приеду прямо сейчас', 'Подойти сзади и обнять'], '', ''),
    ('kamila_01',
     'Только что вернулась с трассы. Адреналин зашкаливает, кровь кипит... Я лежу на кровати в коротком '
     'топе, мне чертовски жарко, и я хочу, чтобы ты помог мне снять напряжение. '
     'Поболтаем... или сразу перейдем к делу?',
     ['Сразу к делу', 'Покажи, как тебе жарко'], '', ''),
    ('maria_01',
     'Я приготовила нам ужин, зажгла свечи... На мне только шёлковый халатик, который так и норовит '
     'соскользнуть с плеч. Я хочу быть идеальной для тебя сегодня. '
     'Покажешь мне, как сильно ты меня хочешь?',
     ['Медленно снять с тебя халатик', 'Поцеловать тебя в шею'], '', ''),
    ('liza_01',
     'Привет... Извини, что так поздно. У меня выбило пробки, а я до дрожи боюсь темноты. '
     'Я прибежала к тебе в одних гольфах и белье, забыла даже накинуть что-то... Можно я останусь? '
     'Обещаю быть послушной девочкой.',
     ['Впустить её и запереть дверь', 'Осмотреть её фигуру'], '', ''),
    ('lana_01',
     'Ты так и не пришел на примерку. Мне пришлось надеть этот латексный костюм самой... '
     'Он плотно облегает каждый изгиб, и мне нужно, чтобы кто-то помог мне его снять. '
     'Расстегнешь молнию или будешь просто смотреть?',
     ['Медленно расстегнуть молнию', 'Наказать за дерзость'], '', ''),
    ('kira_01',
     'Студия закрыта. Мы остались совсем одни. Ты пришел за татуировкой, но... под моим кружевным бельем '
     'скрыто кое-что поинтереснее эскизов. Хочешь, покажу тебе свои самые сокровенные секреты?',
     ['Покажи мне всё', 'Прижать её к стене'], '', ''),
]

# Блок 4 ТЗ V3.166.4, владелец: fifteen universal hooks, every one of them ends
# with her OFFERING a photo and the chips being his «yes, show me». The English
# tail of each row is the hidden frame prompt — never shown to him, only handed
# to the generator when he taps a chip. V3.166.5 adds the last item: the words
# she sends right BEFORE that frame — three of them are his own («Смотри... как
# тебе?», «Вода еще не высохла... нравится?», «Тут так горячо... не хватает
# только тебя.»), the rest are written in the same voice for every scenario.
SEED_UNIVERSAL = [
    ('Знаешь, чего не хватает на этой фотографии? Твоих рук на моем теле. Хочешь, скину фото, чтобы ты '
     'оценил, с чего бы начал?',
     ['Скинь фото', 'Очень хочу'],
     'bedroom, dim lighting, wearing sheer lace lingerie, seductive pose, looking at camera',
     'Смотри... как тебе?'),
    ('Просто решила напомнить, как я выгляжу. Хотя, честно говоря, прямо сейчас я думаю о вещах, от '
     'которых мне становится очень жарко... Показать тебе, в каком я сейчас виде?',
     ['Покажи', 'Жду фото'],
     'sitting on couch, cozy living room, wrapped in a thin blanket, bare shoulders, implied nude, '
     'seductive smile',
     'Укуталась в плед... под ним на мне больше ничего нет.'),
    ('Смотрю на себя и думаю... а как долго ты бы продержался, если бы мы прямо сейчас оказались заперты '
     'в одной спальне? Я только из душа. Прислать фоточку?',
     ['Да, присылай', 'Хочу увидеть'],
     'steamy bathroom, wet hair, wearing only a white towel, drops of water on skin, seductive look',
     'Вода еще не высохла... нравится?'),
    ('Если ты хочешь увидеть, что сейчас скрыто под моей одеждой, придется взять инициативу в свои '
     'руки... Хочешь посмотреть?',
     ['Показывай', 'Скинь фото'],
     "lying in bed, wearing an oversized men's white shirt, unbuttoned, bare legs, intimate mood",
     'Это твоя рубашка... больше на мне ничего нет.'),
    ('Ты вообще умеешь держать себя в руках? Потому что я, глядя на твой профиль, уже с трудом '
     'сдерживаюсь... Показать, какой у тебя сегодня будет десерт?',
     ['Покажи десерт', 'Жду фотку'],
     'kitchen background, wearing only a cooking apron, seductive smile, leaning on counter, highly detailed',
     'Готовлю сегодня только в фартуке... оцени, что под ним.'),
    ('Как думаешь, я хорошая девочка или... только притворяюсь на фото? Хочешь проверить, на что я '
     'способна без свидетелей? Скинуть фото?',
     ['Кидай', 'Хочу проверить'],
     'sitting in an armchair, holding a glass of wine, elegant dress slipping off one bare shoulder, '
     'dim lighting',
     'Бокал налит, платье сползло с плеча... дальше твоя очередь.'),
    ('У меня сегодня такое странное настроение... хочется нарушить пару правил и сделать что-то очень '
     'плохое. Хочешь посмотреть, где я сейчас?',
     ['Конечно', 'Покажи'],
     'relaxing in a bathtub covered in thick white foam, wet skin, candlelit, seductive eyes',
     'Тут так горячо... не хватает только тебя.'),
    ('Честно — лучше бы я отправила свою геопозицию, ужасно хочу почувствовать тебя рядом. Скинуть тебе '
     'фото, чтобы ты увидел, как я тебя жду?',
     ['Скинь', 'Жду фотку'],
     'lying on a bed, hands playfully tied to the headboard with a silk scarf, red lingerie, waiting',
     'Жду тебя вот в такой позе... сама не освобожусь, и не хочу.'),
    ('Я могу быть нежной, а могу... совсем другой. Какой вариант ты выберешь на сегодняшний вечер? '
     'Показать?',
     ['Показывай всё', 'Скинь фотку'],
     'taking a mirror selfie, wearing see-through lingerie, seductive look, bedroom mirror',
     'Снимала это для тебя, а не для зеркала...'),
    ('Представь, что ты стоишь у меня за спиной. Куда бы сейчас скользнули твои руки? Прислать пруфы '
     'того, как я сейчас выгляжу?',
     ['Давай пруфы', 'Хочу увидеть'],
     'dark car interior, back seat, taking off stockings, short skirt, seductive atmosphere',
     'Темно, за городом, никто не видит... смотри.'),
    ('Смотрю в экран и представляю, что ты стоишь напротив и медленно раздеваешь меня взглядом. Скинуть '
     'фото, чтобы тебе было проще представлять?',
     ['Скинь', 'Покажи'],
     'sitting on an office desk, wearing a short skirt and unbuttoned blouse, messy hair, '
     'looking up seductively',
     'Задержалась совсем одна... смотри, что под блузкой.'),
    ('Говорят, первое впечатление — самое важное. Ну как, я прохожу кастинг на твою главную фантазию '
     'этой ночи? Показать, какую фигуру тебе сегодня придется разминать?',
     ['Покажи', 'Присылай'],
     'lying on stomach on a bed, bare back, wearing tiny panties, massage oil bottle nearby, soft light',
     'Масло разогрела, а до спины самой не дотянуться...'),
    ('Я тут подумала... нам определенно стоит сократить дистанцию. Показать, как это выглядит с моего '
     'ракурса?',
     ['Покажи ракурс', 'Кидай фотку'],
     'pov looking down at her body, sitting on a sofa, dark room, tv light, wearing cozy but revealing '
     'homewear',
     'С моего ракурса всё выглядит гораздо интереснее...'),
    ('Обещаю вести себя прилично... ровно до тех пор, пока мы не останемся вдвоем. Скинуть фото, чтобы '
     'ты понял, с чем придется работать?',
     ['Покажи', 'Кидай'],
     'back view, unzipping an elegant dress, bare back, looking over shoulder, intimate bedroom',
     'Молния сзади, а сама не дотянусь... дальше только твоими руками.'),
    ('А если хочешь увидеть то, что я отправляю только самым близким... ты знаешь, что делать. Хочешь '
     'посмотреть, как я сейчас лежу?',
     ['Хочу', 'Скинь фото'],
     'tossing in bed, messy sheets, wearing a tiny silk camisole, sleepy but highly seductive look, '
     'morning light',
     'Не спится... ворочаюсь тут почти без всего, приходи.'),
]

SEED = list(SEED_PERSONAL)


def _universal_rows() -> list[tuple[str, str, list[str], str, str]]:
    return [(UNIVERSAL_ID, text, buttons, prompt, reply) for text, buttons, prompt, reply in SEED_UNIVERSAL]


_seed_marker = None  # filled below, once DialogStore is importable


def _add(s, row: tuple) -> None:
    character_id, text, buttons, prompt, reply = row
    s.add(CharacterGreeting(character_id=character_id, mode='spicy', message_text=text,
                            buttons_json=json.dumps(buttons, ensure_ascii=False),
                            image_prompt=prompt or '', reply_text=(reply or '').strip()))


def ensure_seed() -> int:
    """Залить сценарии владельца один раз. Идемпотентно: если в таблице уже есть
    хоть одна строка (его загрузки через кухню), сид не повторяется."""
    added = 0
    with SessionLocal() as s:
        if s.scalar(select(CharacterGreeting.id).limit(1)) is not None:
            return 0
        for row in list(SEED) + _universal_rows():
            _add(s, row)
            added += 1
        s.commit()
    if added:
        logger.info('greeting seed added=%s', added)
    return added


# БЛОК 4 ТЗ V3.166.4: старые 15 универсальных строк удаляются полностью и
# заменяются новыми, фото из карточек снимаются — механика тапов и кэша больше
# не раздаёт кадр, загруженный владельцем. Делается ОДИН раз (флаг в
# dialog_sessions), иначе его собственные универсальные карточки из кухни
# гибли бы при каждом старте.
_SYNC_KEY = 0
_sync_done = None  # DialogStore('greeting_seed_v31664'), made on the first call


def sync_universal_seed() -> dict:
    """Принудительная замена универсального набора и снос фото с карточек."""
    global _sync_done
    if _sync_done is None:
        from services.dialog_store import DialogStore
        _sync_done = DialogStore('greeting_seed_v31664')
    if _sync_done.get(_SYNC_KEY):
        return {'replaced': 0, 'added': 0, 'photos_stripped': 0}
    stripped = 0
    with SessionLocal() as s:
        old = int(s.scalar(
            select(func.count(CharacterGreeting.id)).where(CharacterGreeting.character_id == UNIVERSAL_ID)
        ) or 0)
        s.execute(sql_delete(CharacterGreeting).where(CharacterGreeting.character_id == UNIVERSAL_ID))
        for row in _universal_rows():
            _add(s, row)
        for row in list(s.scalars(select(CharacterGreeting))):
            if row.photo_bytes is not None or row.photo_file_id:
                row.photo_bytes = None
                row.photo_file_id = None
                stripped += 1
        s.commit()
    _sync_done[_SYNC_KEY] = True
    logger.info('greeting universal seed synced removed=%s added=%s photos_stripped=%s',
                old, len(SEED_UNIVERSAL), stripped)
    return {'replaced': old, 'added': len(SEED_UNIVERSAL), 'photos_stripped': stripped}


# V3.166.5 (владелец: «немота»): его карточки лежат в проде с V3.166.4, а
# ``sync_universal_seed`` свой флаг уже поставил и больше не сработает — поэтому
# реплики перед кадром дописывает отдельная ОДНОРАЗОВАЯ заливка со своим флагом.
# Заполняются только пустые ``reply_text``: то, что он вписал сам в кухне,
# остаётся нетронутым.
_REPLY_KEY = 0
_replies_done = None  # DialogStore('greeting_reply_v31665'), made on the first call


def sync_universal_replies() -> int:
    from sqlalchemy import or_
    global _replies_done
    if _replies_done is None:
        from services.dialog_store import DialogStore
        _replies_done = DialogStore('greeting_reply_v31665')
    if _replies_done.get(_REPLY_KEY):
        return 0
    wanted = {text: reply for text, _buttons, _prompt, reply in SEED_UNIVERSAL}
    filled = 0
    with SessionLocal() as s:
        rows = list(s.scalars(select(CharacterGreeting).where(
            CharacterGreeting.character_id == UNIVERSAL_ID,
            or_(CharacterGreeting.reply_text == '', CharacterGreeting.reply_text.is_(None)))))
        for row in rows:
            reply = wanted.get(row.message_text or '')
            if reply:
                row.reply_text = reply
                filled += 1
        s.commit()
    _replies_done[_REPLY_KEY] = True
    logger.info('greeting reply_text filled=%s of %s', filled, len(rows))
    return filled


def _buttons(row: CharacterGreeting) -> list[str]:
    try:
        raw = json.loads(row.buttons_json or '[]')
    except Exception:
        return []
    return [str(b).strip() for b in raw if str(b).strip()][:4]


def _translations(row: CharacterGreeting) -> dict:
    try:
        data = json.loads(row.translations_json or '{}')
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _choose(character_id: str, mode: str) -> CharacterGreeting | None:
    wanted = (mode, 'both')
    with SessionLocal() as s:
        rows = list(s.scalars(select(CharacterGreeting).where(
            CharacterGreeting.character_id == character_id,
            CharacterGreeting.mode.in_(wanted))))
        if not rows:
            rows = list(s.scalars(select(CharacterGreeting).where(
                CharacterGreeting.character_id == UNIVERSAL_ID,
                CharacterGreeting.mode.in_(wanted))))
        if not rows:
            return None
        picked = random.choice(rows)
        # detach: the row is read after the session closes. The photo columns
        # are not copied — V3.166.4 never serves a card picture, only the frame
        # behind a tapped chip, which lives in starter_photo_cache.
        return CharacterGreeting(id=picked.id, character_id=picked.character_id, mode=picked.mode,
                                 message_text=picked.message_text, buttons_json=picked.buttons_json,
                                 translations_json=picked.translations_json,
                                 image_prompt=picked.image_prompt, reply_text=picked.reply_text)


def _payload(row: CharacterGreeting, text: str, buttons: list[str], name: str,
             reply: str = '') -> dict:
    if name:
        text = text.replace('{name}', name)
        buttons = [b.replace('{name}', name) for b in buttons]
    return {'id': row.id, 'text': text, 'buttons': buttons,
            # Пусто, когда у сценария нет скрытого промпта кадра: тап по чипу
            # тогда обычное сообщение. Сам промпт наружу не отдаётся никогда.
            'starter': bool(row.image_prompt),
            # V3.166.5 (владелец: «немота»): её слова ПЕРЕД кадром. Клиент их не
            # видит — они кладутся в предложение, чтобы тап по чипу ответил им на
            # том же языке, на котором он читал карточку.
            'reply': reply}


async def opening(character_id: str, *, spicy: bool, lang: str = 'ru', name: str = '') -> dict | None:
    """Одна готовая карточка на открытие чата — или None, если для этого режима
    заготовок нет (тогда сработает прежний путь с OPENING_SCENES)."""
    row = _choose(character_id, 'spicy' if spicy else 'normal')
    if row is None:
        return None
    text, buttons, reply = row.message_text or '', _buttons(row), row.reply_text or ''
    lang = (lang or 'ru').lower()
    if lang != 'ru' and text:
        cached = _translations(row).get(lang)
        # Карточка, переведённая до V3.166.5, реплику перед кадром не хранит —
        # тогда перевод снимается ещё раз (одна короткая плата на сценарий и
        # язык) и кэшируется уже целиком.
        if isinstance(cached, dict) and cached.get('text') and (not reply or cached.get('reply')):
            text = str(cached['text'])
            buttons = [str(b) for b in cached.get('buttons') or buttons]
            reply = str(cached.get('reply') or '')
        else:
            translated = await _translate(text, buttons, lang, reply)
            if translated:
                text, buttons, reply = translated
                _cache_translation(row.id, lang, text, buttons, reply)
    return _payload(row, text, buttons, name, reply)


def _cache_translation(greeting_id: int, lang: str, text: str, buttons: list[str],
                       reply: str = '') -> None:
    try:
        with SessionLocal() as s:
            row = s.get(CharacterGreeting, int(greeting_id))
            if not row:
                return
            data = _translations(row)
            old = data.get(lang)
            entry = {'text': text, 'buttons': buttons}
            if reply or (isinstance(old, dict) and old.get('reply')):
                entry['reply'] = reply
            data[lang] = entry
            row.translations_json = json.dumps(data, ensure_ascii=False)
            s.commit()
    except Exception:
        logger.warning('greeting translation cache failed id=%s', greeting_id)


async def _translate(text: str, buttons: list[str], lang: str,
                     reply: str = '') -> tuple[str, list[str], str] | None:
    """Один платный перевод на сценарий. Дальше язык живёт в кэше."""
    try:
        from services import lang_guard
        from services.llm_provider_service import generate_text
        ru_name, own = lang_guard.LANG_NAMES.get(lang, ('английском', 'English'))
        payload = {'text': text, 'buttons': buttons}
        if reply:
            payload['reply'] = reply
        r = await generate_text([
            {'role': 'system', 'content': (
                f'Переведи первое сообщение девушки из чата и подписи кнопок под ним на {ru_name} язык ({own}). '
                'Живо и разговорно, как написал бы носитель, тон и откровенность сохрани, ничего не смягчай. '
                'Верни строго JSON без пояснений: {"text": "...", "buttons": ["...", "..."], "reply": "..."}. '
                'Кнопок столько же и в том же порядке, действия в них — от лица пользователя. '
                '"reply" — её короткая фраза перед фотографией, верни её в том же поле.')},
            {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
        ], max_tokens=700, temperature=0.4, purpose='opening')
        raw = (r.text or '').strip()
        data = json.loads(raw[raw.index('{'):raw.rindex('}') + 1])
        out_text = str(data.get('text') or '').strip()
        out_buttons = [str(b).strip() for b in (data.get('buttons') or []) if str(b).strip()]
        if not out_text:
            return None
        return out_text, (out_buttons or buttons), str(data.get('reply') or '').strip() or reply
    except Exception:
        logger.warning('greeting translation failed lang=%s', lang)
        return None


# ── кухня владельца ────────────────────────────────────────────────────────

def list_for(character_id: str | None = None) -> list[dict]:
    with SessionLocal() as s:
        q = select(CharacterGreeting).order_by(CharacterGreeting.character_id, CharacterGreeting.id)
        if character_id:
            q = q.where(CharacterGreeting.character_id == character_id)
        return [{'id': r.id, 'character_id': r.character_id, 'mode': r.mode,
                 'has_prompt': bool(r.image_prompt), 'text': r.message_text or '',
                 'reply': r.reply_text or '', 'buttons': _buttons(r)} for r in s.scalars(q)]


def scenarios_for(character_id: str) -> list[dict]:
    """Экран «Стартовые фото»: сценарии, у которых есть скрытый промпт кадра —
    его собственные и все универсальные. Без промпта тап чипа остаётся словами."""
    with SessionLocal() as s:
        rows = list(s.scalars(
            select(CharacterGreeting)
            .where(CharacterGreeting.character_id.in_([character_id, UNIVERSAL_ID]),
                   CharacterGreeting.image_prompt != '')
            .order_by(CharacterGreeting.character_id, CharacterGreeting.id)
        ))
    return [{'id': int(r.id), 'character_id': r.character_id, 'text': r.message_text or '',
             'buttons': _buttons(r)} for r in rows]


def image_prompt_for(greeting_id: int) -> str:
    try:
        with SessionLocal() as s:
            row = s.get(CharacterGreeting, int(greeting_id))
            return (row.image_prompt or '') if row else ''
    except Exception:
        logger.warning('greeting prompt read failed id=%s', greeting_id)
        return ''


def create(character_id: str, mode: str, text: str, buttons: list[str], image_prompt: str = '',
           reply_text: str = '') -> int:
    mode = mode if mode in MODES else 'both'
    with SessionLocal() as s:
        row = CharacterGreeting(character_id=character_id or UNIVERSAL_ID, mode=mode,
                                message_text=text or '',
                                buttons_json=json.dumps(buttons or [], ensure_ascii=False),
                                image_prompt=(image_prompt or '').strip(),
                                reply_text=(reply_text or '').strip())
        s.add(row)
        s.commit()
        return int(row.id)


def delete(greeting_id: int) -> bool:
    with SessionLocal() as s:
        row = s.get(CharacterGreeting, int(greeting_id))
        if not row:
            return False
        s.delete(row)
        s.commit()
        return True


def reply_for(greeting_id: int) -> str:
    """Что она хотела сказать перед этим кадром (V3.166.5, «немота»)."""
    try:
        with SessionLocal() as s:
            row = s.get(CharacterGreeting, int(greeting_id))
            return (row.reply_text or '') if row else ''
    except Exception:
        logger.warning('greeting reply read failed id=%s', greeting_id)
        return ''


# ── БЛОК 2 ТЗ V3.166.4: кто предложил кадр и чем это «да» ──────────────────
# Открытие чата запоминает карточку, которую он только что прочитал, а тап по
# чипу сверяется с её кнопками. Регулярки «похоже на просьбу фото» тут не
# работают: его «Показывай» и «Скинь фото» — те же слова, что и в обычных
# репликах, а решают сейчас деньги и генерация. Живёт в памяти процесса, как
# метка демо-селфи (services/onboarding_demo) и подсказка дневного лимита.
_OFFER_TTL = 1800.0
_offers: dict[tuple[int, str], dict] = {}


def remember_offer(telegram_id: int, character_id: str, greeting_id: int, buttons: list[str],
                   reply_text: str = '') -> None:
    _offers[(int(telegram_id), character_id)] = {
        'greeting_id': int(greeting_id),
        'buttons': [str(b).strip().casefold() for b in buttons if str(b).strip()],
        # V3.166.5: её слова перед кадром помнятся в том языке, в котором он
        # только что прочитал карточку.
        'reply': str(reply_text or ''),
        'at': time.monotonic()}


def take_offer(telegram_id: int, character_id: str, text: str) -> dict | None:
    """Его реплика ровно совпала с кнопкой только что открытой карточки — значит
    он согласился посмотреть кадр. None — ничего не предложено или это другой
    текст: ход уходит обычным путём."""
    offer = _offers.get((int(telegram_id), character_id))
    if not offer:
        return None
    if time.monotonic() - float(offer.get('at') or 0) > _OFFER_TTL:
        _offers.pop((int(telegram_id), character_id), None)
        return None
    wanted = (text or '').strip().casefold()
    if not wanted or wanted not in (offer.get('buttons') or []):
        return None
    prompt = image_prompt_for(int(offer['greeting_id']))
    if not prompt:
        return None
    return {'greeting_id': int(offer['greeting_id']), 'image_prompt': prompt,
            'reply_text': str(offer.get('reply') or '') or reply_for(int(offer['greeting_id']))}

