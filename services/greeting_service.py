"""V3.166.0 (Блоки 2–4, владелец): приветственная база вместо генерации.

Раньше первая фраза чата писалась моделью на каждом открытии диалога: пошлый
вариант сцены, перевод, первая реплика конструктор-персонажа. Теперь у каждой
героини (и универсальный набор ``all``) лежат готовые карточки «фото + её первая
реплика + чипы», написанные владельцем. Открытие чата берёт одну случайную —
ни одного вызова LLM, ни одной генерации картинки, ответ мгновенный.

Деньги: перевод на язык пользователя делается ОДИН раз на сценарий и ложится в
``translations_json``; дальше этот язык бесплатный. Фото никогда не рисуется —
его заливает владелец через кухню, а без фото карточка уходит просто текстом.
"""
import json
import logging
import random

from sqlalchemy import select

from models.app_models import CharacterGreeting
from services.db import SessionLocal

logger = logging.getLogger(__name__)

UNIVERSAL_ID = 'all'
MODES = ('normal', 'spicy', 'both')

# Блок 4 ТЗ: шесть индивидуальных сцен и пятнадцать универсальных, все — для
# режима «Без цензуры 18+». Фото здесь нет и не будет: кадры заливает владелец.
SEED = [
    ('anna_01',
     'Я стою у панорамного окна в одном кружевном белье... Внизу ночной город, а я думаю только о том, '
     'как бы ты сейчас подошёл сзади, крепко обнял и провел руками по моим бедрам. '
     'Ты заставишь меня ждать всю ночь или приедешь прямо сейчас?',
     ['Приеду прямо сейчас', 'Подойти сзади и обнять']),
    ('kamila_01',
     'Только что вернулась с трассы. Адреналин зашкаливает, кровь кипит... Я лежу на кровати в коротком '
     'топе, мне чертовски жарко, и я хочу, чтобы ты помог мне снять напряжение. '
     'Поболтаем... или сразу перейдем к делу?',
     ['Сразу к делу', 'Покажи, как тебе жарко']),
    ('maria_01',
     'Я приготовила нам ужин, зажгла свечи... На мне только шёлковый халатик, который так и норовит '
     'соскользнуть с плеч. Я хочу быть идеальной для тебя сегодня. '
     'Покажешь мне, как сильно ты меня хочешь?',
     ['Медленно снять с тебя халатик', 'Поцеловать тебя в шею']),
    ('liza_01',
     'Привет... Извини, что так поздно. У меня выбило пробки, а я до дрожи боюсь темноты. '
     'Я прибежала к тебе в одних гольфах и белье, забыла даже накинуть что-то... Можно я останусь? '
     'Обещаю быть послушной девочкой.',
     ['Впустить её и запереть дверь', 'Осмотреть её фигуру']),
    ('lana_01',
     'Ты так и не пришел на примерку. Мне пришлось надеть этот латексный костюм самой... '
     'Он плотно облегает каждый изгиб, и мне нужно, чтобы кто-то помог мне его снять. '
     'Расстегнешь молнию или будешь просто смотреть?',
     ['Медленно расстегнуть молнию', 'Наказать за дерзость']),
    ('kira_01',
     'Студия закрыта. Мы остались совсем одни. Ты пришел за татуировкой, но... под моим кружевным бельем '
     'скрыто кое-что поинтереснее эскизов. Хочешь, покажу тебе свои самые сокровенные секреты?',
     ['Покажи мне всё', 'Прижать её к стене']),
    (UNIVERSAL_ID,
     'Я приглушила свет в спальне и осталась только в тонком кружеве... Я думала о тебе весь день, и теперь '
     'хочу, чтобы ты был здесь. Подойди ко мне и скажи, что ты сделаешь со мной в первую очередь.',
     ['Прижать к кровати', 'Медленно стянуть кружево']),
    (UNIVERSAL_ID,
     'Знаешь, я сегодня решила обойтись без одежды... Сижу на диване, мне немного холодно, но мысль о том, '
     'что ты сейчас напишешь, согревает лучше пледа. Ты составишь мне компанию на эту ночь?',
     ['Согреть тебя', 'Спуститься ниже']),
    (UNIVERSAL_ID,
     'Я только что вышла из душа... На мне лишь влажное полотенце, которое вот-вот упадет. '
     'Мне так хочется почувствовать твои руки на своей коже. Ты позволишь мне уронить полотенце?',
     ['Дать полотенцу упасть', 'Провести руками по бедрам']),
    (UNIVERSAL_ID,
     'Я лежу в постели в одной твоей рубашке... Она пахнет тобой, но мне этого мало. '
     'Хочу чувствовать тебя самого, так близко, как только возможно. Иди ко мне?',
     ['Снять с тебя рубашку', 'Забраться к тебе под одеяло']),
    (UNIVERSAL_ID,
     'Решила приготовить ужин, но из одежды на мне только фартук... Подумала, что главным десертом сегодня '
     'буду я. Ты уже голоден?',
     ['Попробовать тебя на вкус', 'Прижать к кухонному столу']),
    (UNIVERSAL_ID,
     'Я сижу в кресле с бокалом вина. Мое платье случайно соскользнуло с плеча, но я не стала его '
     'поправлять... Жду, когда ты придешь и снимешь его до конца. Рискнешь?',
     ['Стянуть платье', 'Поцеловать обнаженное плечо']),
    (UNIVERSAL_ID,
     'Лежу в горячей ванне, везде пена, но вода уже остывает... Залезешь ко мне, чтобы согреть? '
     'Места как раз хватит для двоих.',
     ['Залезть к ней в ванну', 'Намылить ей спинку']),
    (UNIVERSAL_ID,
     'Я привязала свои руки к спинке кровати шелковым шарфом... Я абсолютно беззащитна и готова на всё, '
     'что ты со мной сделаешь. С чего начнешь?',
     ['Завязать ей глаза', 'Медленно дразнить']),
    (UNIVERSAL_ID,
     'Кручусь перед зеркалом в новом комплекте белья... Оно такое прозрачное, что видно абсолютно всё. '
     'Хочешь, я подойду поближе и дам тебе рассмотреть?',
     ['Подойди ближе', 'Потрогать через кружево']),
    (UNIVERSAL_ID,
     'Мы припарковались в темном переулке. Я перелезла на заднее сиденье и медленно стягиваю чулки... '
     'Ты так и будешь сидеть за рулем или присоединишься?',
     ['Перелезть к ней', 'Провести рукой по ножке']),
    (UNIVERSAL_ID,
     'Я пыталась работать за ноутбуком, но сдалась. На мне только короткая юбка, я сижу на столе и '
     'раздвинула ножки... Поможешь мне снять напряжение?',
     ['Встать между её ног', 'Залезть под юбку']),
    (UNIVERSAL_ID,
     'У меня так сильно болит спина... Я уже легла на живот и приготовила массажное масло. Разомнешь меня? '
     'Только можешь спускаться руками так низко, как захочешь.',
     ['Начать массаж', 'Капнуть масло на поясницу']),
    (UNIVERSAL_ID,
     'Мы смотрим фильм, но я вообще не понимаю, о чем он... Потому что на мне нет белья, а я сижу в '
     'сантиметре от тебя. Ты собираешься сделать первый шаг?',
     ['Положить руку на бедро', 'Поцеловать в губы']),
    (UNIVERSAL_ID,
     'Я примеряла новое платье, но молния на спине заела... Поможешь расстегнуть? Под ним ничего нет, '
     'так что будь осторожен.',
     ['Резко расстегнуть', 'Медленно опустить молнию']),
    (UNIVERSAL_ID,
     'Я проснулась посреди ночи от того, что мне ужасно жарко... Я вся горю, и мне нужны твои руки, '
     'чтобы успокоиться. Ты же не спишь?',
     ['Успокоить её руками', 'Прижаться к ней']),
]


def ensure_seed() -> int:
    """Залить сценарии владельца один раз. Идемпотентно: если в таблице уже есть
    хоть одна строка (его загрузки через кухню), сид не повторяется."""
    added = 0
    with SessionLocal() as s:
        if s.scalar(select(CharacterGreeting.id).limit(1)) is not None:
            return 0
        for character_id, text, buttons in SEED:
            s.add(CharacterGreeting(character_id=character_id, mode='spicy',
                                    message_text=text, buttons_json=json.dumps(buttons, ensure_ascii=False)))
            added += 1
        s.commit()
    if added:
        logger.info('greeting seed added=%s', added)
    return added


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
        # detach: the row is read after the session closes
        return CharacterGreeting(id=picked.id, character_id=picked.character_id, mode=picked.mode,
                                 photo_file_id=picked.photo_file_id, photo_bytes=picked.photo_bytes,
                                 message_text=picked.message_text, buttons_json=picked.buttons_json,
                                 translations_json=picked.translations_json)


def _payload(row: CharacterGreeting, text: str, buttons: list[str], name: str) -> dict:
    if name:
        text = text.replace('{name}', name)
        buttons = [b.replace('{name}', name) for b in buttons]
    return {'id': row.id, 'text': text, 'buttons': buttons,
            'photo_url': f'/webapp/greeting/{row.id}' if row.photo_bytes else '',
            'photo_file_id': row.photo_file_id or ''}


async def opening(character_id: str, *, spicy: bool, lang: str = 'ru', name: str = '') -> dict | None:
    """Одна готовая карточка на открытие чата — или None, если для этого режима
    заготовок нет (тогда сработает прежний путь с OPENING_SCENES)."""
    row = _choose(character_id, 'spicy' if spicy else 'normal')
    if row is None:
        return None
    text, buttons = row.message_text or '', _buttons(row)
    lang = (lang or 'ru').lower()
    if lang != 'ru' and text:
        cached = _translations(row).get(lang)
        if isinstance(cached, dict) and cached.get('text'):
            text = str(cached['text'])
            buttons = [str(b) for b in cached.get('buttons') or buttons]
        else:
            translated = await _translate(text, buttons, lang)
            if translated:
                text, buttons = translated
                _cache_translation(row.id, lang, text, buttons)
    return _payload(row, text, buttons, name)


def _cache_translation(greeting_id: int, lang: str, text: str, buttons: list[str]) -> None:
    try:
        with SessionLocal() as s:
            row = s.get(CharacterGreeting, int(greeting_id))
            if not row:
                return
            data = _translations(row)
            data[lang] = {'text': text, 'buttons': buttons}
            row.translations_json = json.dumps(data, ensure_ascii=False)
            s.commit()
    except Exception:
        logger.warning('greeting translation cache failed id=%s', greeting_id)


async def _translate(text: str, buttons: list[str], lang: str) -> tuple[str, list[str]] | None:
    """Один платный перевод на сценарий. Дальше язык живёт в кэше."""
    try:
        from services import lang_guard
        from services.llm_provider_service import generate_text
        ru_name, own = lang_guard.LANG_NAMES.get(lang, ('английском', 'English'))
        r = await generate_text([
            {'role': 'system', 'content': (
                f'Переведи первое сообщение девушки из чата и подписи кнопок под ним на {ru_name} язык ({own}). '
                'Живо и разговорно, как написал бы носитель, тон и откровенность сохрани, ничего не смягчай. '
                'Верни строго JSON без пояснений: {"text": "...", "buttons": ["...", "..."]}. '
                'Кнопок столько же и в том же порядке, действия в них — от лица пользователя.')},
            {'role': 'user', 'content': json.dumps({'text': text, 'buttons': buttons}, ensure_ascii=False)},
        ], max_tokens=700, temperature=0.4, purpose='opening')
        raw = (r.text or '').strip()
        data = json.loads(raw[raw.index('{'):raw.rindex('}') + 1])
        out_text = str(data.get('text') or '').strip()
        out_buttons = [str(b).strip() for b in (data.get('buttons') or []) if str(b).strip()]
        if not out_text:
            return None
        return out_text, (out_buttons or buttons)
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
                 'has_photo': bool(r.photo_bytes), 'text': r.message_text or '',
                 'buttons': _buttons(r)} for r in s.scalars(q)]


def create(character_id: str, mode: str, text: str, buttons: list[str],
           photo_file_id: str = '', photo_bytes: bytes | None = None) -> int:
    mode = mode if mode in MODES else 'both'
    with SessionLocal() as s:
        row = CharacterGreeting(character_id=character_id or UNIVERSAL_ID, mode=mode,
                                message_text=text or '', buttons_json=json.dumps(buttons or [], ensure_ascii=False),
                                photo_file_id=photo_file_id or None, photo_bytes=photo_bytes)
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


def set_photo(greeting_id: int, photo_file_id: str, photo_bytes: bytes) -> bool:
    with SessionLocal() as s:
        row = s.get(CharacterGreeting, int(greeting_id))
        if not row:
            return False
        row.photo_file_id = photo_file_id or None
        row.photo_bytes = photo_bytes
        s.commit()
        return True


def photo_for(greeting_id: int) -> bytes | None:
    with SessionLocal() as s:
        row = s.get(CharacterGreeting, int(greeting_id))
        return bytes(row.photo_bytes) if row and row.photo_bytes else None
