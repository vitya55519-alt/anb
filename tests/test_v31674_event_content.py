"""V3.167.4 #172 (владелец ТЗ §4, 16.11): «её день» звучит как смс, а не как рассылка.

Одно-три предложения с одной бытовой деталью, которую видно. Без вопросов-анкет
(«как дела / что делаешь / расскажи о себе») и без «скучаю / почему не пишешь»:
он не обязан отвечать на пуш. Факт из памяти — почти всегда (0.9), потому что
вспоминать его слова дороже, чем спрашивать. Тон — по уровню близости 1-3 /
4-6 / 7-10 и по режиму, а не по погоде. Крючок — один: недосказанность в конце
и одна кнопка «расскажи дальше», две кнопки превращали её день в опросник.
Кадр из пула стал чаще (0.35), но тратит общий кап бесплатных кадров на
аккаунт — 2 в сутки на обе рельсы разом. Рендеры за персики, цена кадра и
покупка персиков не тронуты.
"""
import uuid
from pathlib import Path

import config
from services import chat_photo_allowance as A
from services import life_event_service as L
from services import retention_features_service as rfs

ROOT = Path(__file__).resolve().parents[1]
LIFE = (ROOT / 'services' / 'life_event_service.py').read_text(encoding='utf-8')
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')


def _uid() -> int:
    from services.user_service import ensure_user
    return ensure_user(817240000 + uuid.uuid4().int % 99999, 'V')


def _char() -> str:
    return 'cap_girl_' + uuid.uuid4().hex[:6]


# ── Блок 1: сама строка ──────────────────────────────────────────────────────

def test_the_message_is_three_sentences_with_one_visible_detail():
    p = L._system_prompt('Аня', 'evening', [], '', '', '', level=2)
    assert 'одно-три коротких предложения' in p and '~180 знаков' in p
    assert 'бытовая деталь' in p and 'день был сумасшедший' in p   # общая фраза запрещена
    assert 'как настоящая смс в мессенджере' in p
    assert 'НЕ «скучаю / почему не пишешь»' in p


def test_the_push_never_turns_into_a_survey():
    p = L._system_prompt('Аня', 'day', [], '', '', '', level=1)
    for question in ('как дела', 'что делаешь', 'расскажи о себе'):
        assert question in p                       # названы как запрещённые
    assert 'он не обязан отвечать на пуш' in p
    assert 'не упоминай, что ты ИИ' in p and 'Без хэштегов' in p


def test_the_tone_follows_the_bond_not_the_weather():
    assert 'Вы только знакомитесь' in L._system_prompt('', 'day', [], '', '', '', level=1)
    assert 'Вы только знакомитесь' in L._system_prompt('', 'day', [], '', '', '', level=3)
    assert 'Вы уже свои люди' in L._system_prompt('', 'day', [], '', '', '', level=4)
    assert 'Вы уже свои люди' in L._system_prompt('', 'day', [], '', '', '', level=6)
    assert 'Вы пара' in L._system_prompt('', 'day', [], '', '', '', level=7)
    assert 'Вы пара' in L._system_prompt('', 'day', [], '', '', '', level=10)
    # до 3-го уровня она не зовёт к себе и не говорит «мы»
    assert 'без зова к себе' in L._tone(2)


def test_the_mode_steers_the_hint_and_never_the_graphic_detail():
    spicy = L._system_prompt('', 'night', [], '', '', '', level=5, mode_on=True)
    soft = L._system_prompt('', 'night', [], '', '', '', level=5, mode_on=False)
    assert 'Без цензуры 18+' in spicy and 'Подробностей самой сцены в пуше' in spicy
    assert 'Романтика и флирт' in soft and 'Без цензуры' not in soft


def test_the_memory_fact_is_almost_always_there():
    assert config.LIFE_EVENTS_MEMORY_CHANCE == 0.9
    p = L._system_prompt('', 'day', [], '', 'он боится голубей', '', level=2)
    assert 'Вспомни его же деталь' in p and '«он боится голубей»' in p
    assert 'Можешь естественно' not in p        # прежнее «можешь» стало правилом
    assert 'Зацепка для момента' not in p       # без вкусов не выдумываем


def test_the_chance_knob_still_silences_the_memory(monkeypatch):
    monkeypatch.setattr(L.random, 'random', lambda: 0.95)   # хуже порога 0.9
    assert L._memory_callback(817249999, 'anna_01') == ''


# ── Блок 2: крючок с одной кнопкой ──────────────────────────────────────────

def test_there_is_exactly_one_hook_button():
    assert len(L._REPLY_OPTIONS) == 1
    label, key = L._REPLY_OPTIONS[0]
    assert label == '🍿 расскажи дальше' and key == 'tell_more'
    assert 'дальше' in L.tap_reply_text('tell_more')
    assert 'miss_you' not in LIFE               # второй кнопки больше нет
    # кнопка продолжает ИМЕННО её историю: персонаж живёт в callback
    assert "f'life_reply:{character_id}:{key}'" in LIFE
    assert 'Закончи недосказанностью' in L._system_prompt('', 'day', [], '', '', '')


# ── Блок 3: шанс кадра и общий кап бесплатных кадров ────────────────────────

def test_the_frame_chance_grew_and_the_pool_rails_now_share_one_ceiling():
    assert config.LIFE_EVENTS_PHOTO_CHANCE == 0.35
    assert config.FREE_FRAMES_PER_DAY == 2
    assert config.CHAT_POOL_PHOTOS_PER_DAY == 1          # чатную квоту не меняли
    assert A.PUSH_EVENT == 'push_pool_photo'
    assert 'photo = random_proactive_photo(character_id, user_id=' in LIFE
    # рельса на месте и по-прежнему берёт только пул: scheduler не рендерит
    assert 'from services.life_event_service import build_life_moment' in SCHED
    assert 'generate_image' not in SCHED


def test_two_frames_a_day_in_total_however_many_days_she_has():
    uid, char = _uid(), _char()
    for i in range(3):
        assert rfs.add_proactive_photo(b'img%d' % i + b'x' * 50, 'image/jpeg', 'photo',
                                       character_id=char)
    assert A.frames_left(uid) == config.FREE_FRAMES_PER_DAY
    assert L._pool_photo(char, uid) is not None
    assert L._pool_photo(char, uid) is not None
    assert A.frames_left(uid) == 0
    assert L._pool_photo(char, uid) is None              # третий кадр — только текстом
    assert A.count_today(uid, A.PUSH_EVENT) == 2


def test_a_chat_frame_spends_the_same_day_quota():
    uid, char = _uid(), _char()
    for i in range(3):
        rfs.add_proactive_photo(b'c%d' % i + b'x' * 50, 'image/jpeg', 'photo', character_id=char)
    assert A.pool_photos_left(uid) == 1                  # своя квота чата
    assert L._pool_photo(char, uid) is not None          # её день забрал один кадр
    assert A.frames_left(uid) == config.FREE_FRAMES_PER_DAY - 1
    assert L._pool_photo(char, uid) is not None          # второй закрыл кап аккаунта
    assert A.frames_left(uid) == 0
    # теперь и в чате пуловый кадр не показать: кап один на обе рельсы
    assert A.pool_photos_left(uid) == 0
    assert L._pool_photo(char, uid) is None


def test_the_paid_economy_is_outside_this_cap():
    uid, char = _uid(), _char()
    rfs.add_proactive_photo(b'p' * 60, 'image/jpeg', 'photo', character_id=char)
    before = A.free_chat_photos_left(uid, premium=False)
    assert L._pool_photo(char, uid) is not None
    assert L._pool_photo(char, uid) is not None
    assert A.frames_left(uid) == 0
    # бесплатный рендер в чате считается своими правилами: кап пуловых кадров
    # его не урезает и не добавляет
    assert A.free_chat_photos_left(uid, premium=False) == before
    assert A.free_chat_photos_left(uid, premium=True) > 0
    assert config.EXPLICIT_PHOTO_PEACH_COST == 250


def test_the_frame_gate_lives_in_the_photo_helper_not_the_scheduler():
    src = L._pool_photo.__doc__ or ''
    assert 'лимит 2 фото в сутки' in src
    body = LIFE[LIFE.index('def _pool_photo('):LIFE.index('async def build_life_moment')]
    assert 'frames_left(uid) <= 0' in body and 'use_push_frame(uid, character_id)' in body
    assert 'generate_image' not in body and 'render' not in body.lower()
