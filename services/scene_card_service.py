"""V3.166.7 (владелец): скрытая анкета кадра — единственный источник сцены.

Она отвечает одним сообщением, и последней строкой пишет то, чего он не видит:
где стоит прямо сейчас, кто физически в этой же комнате, и как это выглядит на
фото. Отсюда локацию берёт генератор картинок и отсюда же решается, иметь ли
«мужа за спиной» в кадре: «Платон в гараже» — в кадре никого; «он за дверью» —
появляется. До этого место выбирали три независимые системы (состояние дня,
банк случайных идей, хардкод старта), и кадр спорил с её же словами.

Хранится как «Раздеть» — ``DialogStore`` по (пользователь, героиня), новой
таблицы нет. Живёт 6 часов: за это время она не «телепортируется», а дальше
снова говорит суточный сценарий.
"""
from __future__ import annotations

import logging
import re
import time

from services import dialog_store

logger = logging.getLogger(__name__)

TTL_SECONDS = 6 * 3600
_store = dialog_store.DialogStore('scene_card')

# «КАДР: где=примерочная | рядом=нет | кто= | сцена=a boutique fitting room…»
# SCENE/FRAME — потому что MiniMax изредка переводит метку на английский.
CARD_LINE = re.compile(r"(?im)^[ \t>*-]*(?:КАДР|FRAME|SCENE)[ \t]*[:=][ \t]*([^\n]+)")
_FIELDS = re.compile(r'\s*[|;]\s*')
_PAIR = re.compile(r'\s*[:=]\s*')
_KEYS = {
    'где': 'place', 'place': 'place', 'where': 'place',
    'рядом': 'near', 'near': 'near', 'nearby': 'near', 'кто_рядом': 'near',
    'кто': 'with', 'who': 'with', 'with': 'with',
    'сцена': 'scene', 'scene': 'scene',
}
_YES = ('да', 'yes', 'true', 'есть', 'в комнате', 'рядом')

LIMITS = {'place': 60, 'with': 120, 'scene': 320}

# Правило живёт здесь, а не в chat_service — как DRAFT_FORMAT_SUFFIX у
# draft_service: метку, её разбор и то, что ей можно и нельзя, знает один файл.
SCENE_CARD_DIRECTIVE = (
    'АНКЕТА КАДРА — служебная строка, которую он не читает:\n'
    'Последней строкой каждого ответа пиши ровно одну строку:\n'
    'КАДР: где=<где она стоит прямо сейчас, 1–3 слова> | рядом=<да или нет> | '
    'кто=<кто физически стоит в этой же комнате, по-английски 2–6 слов; если '
    'никого — пусто> | сцена=<по-английски 1–2 фразы: помещение, свет, что видно '
    'вокруг>\n'
    'Правила: «где» и «сцена» — ровно то место, о котором речь в этом сообщении. '
    'Если он уехал в гараж, а она стоит в примерочной — гаража в кадре нет. '
    '«рядом=да» только когда человек в этой же комнате и может обернуться прямо '
    'сейчас: муж на работе, в гараже, в машине, у друзей, в магазине в другом '
    'ряду или за дверью в другой комнате — это «рядом=нет» и пустое «кто». '
    '«сцена» — только помещение, свет и предметы; людей туда не пиши, для людей '
    'есть поле «кто». Место не меняется само: была кухня — остаётся кухня, пока '
    'разговор не уведёт её туда, где она сама скажет, что теперь.\n'
    'КАДР идёт последним, после MESSAGE, отдельных слов до него и после него нет. '
    'Он никогда не попадает в её сообщение, в озвучку и в то, что он читает.'
)

SCENE_CARD_DIRECTIVE_DUO = (
    'В чате вдвоём строка КАДР одна на двоих и стоит после обеих реплик: '
    'девушки в этот момент в одном месте, и «кто» — про всех, кто не они.'
)


def card_line(raw: str) -> str:
    """Скрытая строка кадра из сырого ответа модели — '' если её не написали."""
    m = CARD_LINE.search(raw or '')
    return m.group(1).strip() if m else ''


def strip_card(raw: str) -> str:
    """Ответ без строки кадра: её он не читает, и в базу она не ложится."""
    return CARD_LINE.sub('', raw or '')


def parse(line: str) -> dict:
    card: dict = {}
    for part in _FIELDS.split((line or '').strip()):
        if not _PAIR.search(part):
            continue
        key, value = _PAIR.split(part, 1)
        field = _KEYS.get(re.sub(r'\s+', '_', key.strip().lower()))
        if not field:
            continue
        value = re.sub(r'\s+', ' ', value.strip())
        if field == 'near':
            card['near'] = value.lower().startswith(_YES)
        elif value:
            card[field] = value[:LIMITS[field]]
    # «рядом=нет» переваривает любое «кто»: человека в этой комнате нет, и
    # выдуманного зрителя в кадр он не пускает.
    if not card.get('near'):
        card.pop('with', None)
    return card


def remember(telegram_id: int, character_id: str, line: str) -> None:
    card = parse(line)
    if not card:
        return
    states = dict(_store.get(int(telegram_id)) or {})
    states[str(character_id)] = {'at': int(time.time()), 'card': card}
    _store[int(telegram_id)] = states
    logger.info('scene card remembered user=%s girl=%s place=%s near=%s',
                telegram_id, character_id, card.get('place', '-'), card.get('near'))


def current(telegram_id: int, character_id: str) -> dict:
    got = (_store.get(int(telegram_id)) or {}).get(str(character_id))
    if not isinstance(got, dict):
        return {}
    try:
        at = int(got.get('at') or 0)
    except (TypeError, ValueError):
        return {}
    if not at or (time.time() - at) >= TTL_SECONDS:
        return {}
    card = got.get('card')
    return dict(card) if isinstance(card, dict) else {}


def scene_for(telegram_id: int, character_id: str) -> str:
    """Английское описание места — ровно то, что увидит генератор картинок."""
    card = current(telegram_id, character_id)
    scene = str(card.get('scene') or '')
    who = str(card.get('with') or '')
    if scene and who:
        return f'{scene}; in the same room: {who}'
    return scene


def together_with(telegram_id: int, character_id: str) -> tuple[bool | None, str]:
    """Кто физически в этой же комнате прямо сейчас («муж в гараже» → False).

    ``None`` — анкеты нет, и её отсутствие не должно отменять привычные механики
    (например «тсс… он за спиной» в «Раздеть»); False — анкета сказала, что
    в комнате никого, и выдуманного зрителя в кадр он не пускает."""
    card = current(telegram_id, character_id)
    if not card:
        return None, ''
    return bool(card.get('near')), str(card.get('with') or '')


def continuation(card: dict) -> str:
    """Её же живая сцена, отданная обратно в промпт: на следующем ходу она не
    «телепортируется» из примерочной в спальню. По-русски и без английских
    вставок — в промпте общения английский текст тянет за собой английные слова
    в её реплику."""
    place = str(card.get('place') or '').strip()
    if not place:
        return ''
    who = ', в этой же комнате кто-то есть' if card.get('near') else ', в этой комнате она одна'
    return (f'СЦЕНА СЕЙЧАС: она {place}{who}. Продолжай эту сцену, пока разговор '
            'не уведёт её в другое место.')
