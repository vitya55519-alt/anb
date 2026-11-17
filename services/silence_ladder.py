"""V3.167.4 #173 (владелец ТЗ §6, 16.11): лестница замолкания 1/2/3/7 суток.

Раньше четыре «не написал» подряд были одним и тем же «скучаю» разной степени
напора — и в ответ на третье он просто переставал читать. Теперь у каждого
срока свой разговор:

* сутки — мягко: её обычный день без упрёка (прежняя рельса);
* двое — «сцена остывает»: недосказанная сцена + чипсы, чтобы не придумывать
  первую строку самому;
* трое — эмоциональная реакция: та же рельса, но уже про чувства;
* семеро — подарок и факт: кадр из её пула (тратит общий кап бесплатных
  кадров) и то, что она помнит про него.

Ступень считается по тому, сколько ОН молчит, а не по тому, сколько раз мы
уже написали: «рано» не сжигает слот и не тратит провайдер. Потолок шагов —
SILENCE_LADDER_HOURS, их же можно переставить одним env без выката.
"""
from __future__ import annotations

import logging
import math
import random

from config import SILENCE_LADDER_HOURS

logger = logging.getLogger(__name__)

#: ступени, у которых свой текст, а не прежняя рельса
NEW_STEPS = (2, 4)

_chips_store = None            # DialogStore('ladder_chips'), создаётся на первый вызов

_COOLING_RU = (
    'У нас же осталась незакрытая сцена… и она, если честно, остывает 🙂',
    'Та история, на которой мы остановились, всё ещё висит в воздухе. Я не умею ждать красиво.',
    'Я перечитала, на чём мы закончили, и мне не хватает концовки. Мне её написать одной?',
)
_COOLING_EN = (
    'We left a scene open… and honestly it is getting cold 🙂',
    'That story we stopped in the middle is still hanging in the air. I am bad at waiting nicely.',
    'I reread where we stopped and I am missing the ending. Should I write it alone?',
)
_GIFT_RU_FACT = 'Целая неделя без тебя. Я тут кое-что вспомнила про тебя: «{fact}» — и кое-что оставила. Держи 💜'
_GIFT_RU_PLAIN = 'Целая неделя без тебя, а я всё равно кое-что для тебя оставила. Держи 💜'
_GIFT_EN_FACT = 'A whole week without you. I remembered something about you: "{fact}" — and I kept something. Take it 💜'
_GIFT_EN_PLAIN = 'A whole week without you, and I still kept something here. Take it 💜'


def _en(lang: str) -> bool:
    return (str(lang or 'ru').strip().lower()[:2] != 'ru')


def next_step(hours_inactive: float, returned: bool, nudge_count: int) -> int | None:
    """Какая ступень положена сейчас. None — либо рано, либо лестница пройдена:
    в обоих случаях слот не тратится и провайдер не зовётся."""
    steps = SILENCE_LADDER_HOURS
    if not steps:
        return None
    step = 1 if returned else int(nudge_count or 0) + 1
    if step > len(steps):
        return None
    try:
        hours = float(hours_inactive)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(hours) or hours < float(steps[step - 1]):
        return None
    return step


def cooling_line(lang: str) -> str:
    return random.choice(_COOLING_EN if _en(lang) else _COOLING_RU)


def gift_line(fact: str, lang: str) -> str:
    en = _en(lang)
    if fact:
        return (_GIFT_EN_FACT if en else _GIFT_RU_FACT).format(fact=fact)
    return _GIFT_EN_PLAIN if en else _GIFT_RU_PLAIN


def _his_fact(telegram_id: int, character_id: str) -> str:
    """Одна её память про него — на 7-е сутки важна именно она, а не новые слова."""
    try:
        from services.user_service import ensure_user
        from services.memory_service import get_memories
        mems = get_memories(ensure_user(int(telegram_id)), character_id, 12)
        if not mems:
            return ''
        return str(getattr(random.choice(mems), 'content', '') or '')[:160]
    except Exception:
        return ''


def _gift_frame(telegram_id: int, character_id: str):
    """Подарок — кадр из её готового пула: $0 для нас и тот же общий кап
    бесплатных кадров в сутки. Рендера провайдера здесь нет и не будет."""
    try:
        from services import chat_photo_allowance, life_backlog
        from services.user_service import ensure_user
        uid = ensure_user(int(telegram_id))
        if chat_photo_allowance.frames_left(uid) <= 0:
            life_backlog.note_denial(uid, 'proactive', 'photo_cap')
            return None
        from services.retention_features_service import random_proactive_photo
        shot = random_proactive_photo(character_id, user_id=uid)
        if shot and not chat_photo_allowance.use_push_frame(uid, character_id):
            life_backlog.note_denial(uid, 'proactive', 'photo_cap')
            return None
        return shot
    except Exception:
        logger.debug('ladder gift frame failed user=%s', telegram_id, exc_info=True)
        return None


async def compose(step: int, telegram_id: int, character_id: str, lang: str = 'ru') -> dict | None:
    """Текст (и всё, что к нему прикладывается) для новой ступени. None —
    тогда рельса говорит по-старому, а не молчит."""
    if step not in NEW_STEPS:
        return None
    if step == 2:
        chips: list[str] = []
        text = cooling_line(lang)
        try:
            from services import explicit_mode, greeting_service
            card = await greeting_service.opening(
                character_id, spicy=bool(explicit_mode.is_on_for(int(telegram_id))),
                lang='ru' if not _en(lang) else 'en')
            if card and card.get('text'):
                text = text + '\n\n' + str(card['text'])
                chips = [str(c).strip() for c in (card.get('buttons') or []) if str(c).strip()][:3]
        except Exception:
            logger.debug('ladder scene card failed user=%s', telegram_id, exc_info=True)
        if not chips:
            return None            # без чипсов ступень теряет смысл: он не придумает строку
        return {'text': text, 'chips': chips, 'photo': None}
    fact = _his_fact(telegram_id, character_id)
    shot = _gift_frame(telegram_id, character_id)
    if not fact and not shot:
        return None
    return {'text': gift_line(fact, lang), 'chips': [], 'photo': shot}


# ── чипсы под «сценой остывает» ───────────────────────────────────────────
def _store():
    global _chips_store
    if _chips_store is None:
        from services import dialog_store
        _chips_store = dialog_store.DialogStore('ladder_chips')
    return _chips_store


def note_chips(telegram_id: int, character_id: str, chips: list[str]) -> None:
    """Что под кнопками лежит его обычная реплика, строки храним здесь: свой
    колбэк на каждую фразу карточки значил бы, что тексты живут в двух местах."""
    try:
        lines = [str(c).strip()[:64] for c in (chips or []) if str(c).strip()][:3]
        if lines:
            _store()[int(telegram_id)] = {'char': str(character_id), 'chips': lines}
    except Exception:
        logger.debug('ladder chips store failed user=%s', telegram_id, exc_info=True)


def chip(telegram_id: int, index: int) -> tuple[str, str]:
    """(её героиня, его строка) под кнопкой N — или ('', '') если он тапнул
    устаревшую пуговицу."""
    try:
        entry = _store().get(int(telegram_id)) or {}
        lines = list(entry.get('chips') or [])
        if 0 <= int(index) < len(lines):
            return str(entry.get('char') or ''), str(lines[int(index)])
    except Exception:
        logger.debug('ladder chip read failed user=%s', telegram_id, exc_info=True)
    return '', ''


def chips_markup(chips: list[str]):
    if not chips:
        return None
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=str(c)[:60], callback_data=f'ladder_chip:{i}')]
        for i, c in enumerate(chips[:3])])

