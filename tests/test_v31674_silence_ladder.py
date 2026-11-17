"""V3.167.4 #173 (владелец ТЗ §6, 16.11): лестница замолкания 1/2/3/7 суток.

Прежде четыре «не написал» подряд были одним и тем же «скучаю» разной степени
напора. Теперь у срока свой разговор: сутки — мягко (прежняя рельса), двое —
«сцена остывает» и под ней его же строки, трое — эмоциональная реакция, семеро
— кадр из её пула и то, что она про него помнит. Больше четырёх раз за цикл она
не пишет: ``RETENTION_MAX_NUDGES`` стал 4, ровно по числу ступеней.

Ступень считается по его молчанию, а не по нашим отправлениям: «рано» не
сжигает слот и не зовёт провайдера — проверка стоит до записи в CharacterState.

Живые проверки ходят по чистой БД, статические пиляют scheduler и main как текст.
"""
import asyncio
import os
import uuid
from pathlib import Path

os.environ.setdefault('TELEGRAM_TOKEN', '123456:test-fake-token-for-static-tests-only')
os.environ.setdefault('GEMINI_API_KEY', 'x')

from sqlalchemy import select

import config
from models.app_models import DialogSession
from services import silence_ladder as S
from services.db import SessionLocal


ROOT = Path(__file__).resolve().parents[1]
CFG = (ROOT / 'config.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
LADDER = (ROOT / 'services' / 'silence_ladder.py').read_text(encoding='utf-8')
PROACTIVE = SCHED[SCHED.index('async def _proactive'):SCHED.index('async def _day1_hook')]


def _user() -> tuple[int, int, str]:
    """(telegram_id, uid, character_id) — свежий аккаунт под своим героем."""
    from services.user_service import ensure_user
    tid = 917300000 + uuid.uuid4().int % 99999
    return tid, ensure_user(tid, 'V'), 'ladder_girl_' + uuid.uuid4().hex[:6]


def _dialog(uid: int, char: str) -> list:
    from models.app_models import Message
    with SessionLocal() as s:
        return list(s.scalars(select(Message).where(Message.user_id == uid,
                                                    Message.character_id == char)
                              .order_by(Message.id)).all())


# ── 1. сами сроки ────────────────────────────────────────────────────────────
def test_the_ladder_has_four_deadlines_and_no_fifth_nudge():
    assert 'SILENCE_LADDER_HOURS", "24,48,72,168"' in CFG
    assert config.SILENCE_LADDER_HOURS == (24, 48, 72, 168)
    # пять одинаковых «скучаю» не работают: шагов ровно столько, сколько ступеней
    assert 'RETENTION_MAX_NUDGES", "4"' in CFG
    assert config.RETENTION_MAX_NUDGES == len(config.SILENCE_LADDER_HOURS) == 4


def test_the_step_follows_his_silence_not_our_count():
    assert S.next_step(30, False, 0) == 1          # сутки — мягко
    assert S.next_step(30, False, 1) is None       # до «сцены» ещё сутки ждать
    assert S.next_step(50, False, 1) == 2
    assert S.next_step(73, False, 2) == 3
    assert S.next_step(169, False, 3) == 4
    assert S.next_step(4000, False, 4) is None     # лестница пройдена: пятого раза нет


def test_his_return_starts_the_ladder_again():
    # вернулся — значит сначала мягко, а не сразу с подарком за неделю
    assert S.next_step(26, True, 3) == 1
    assert S.next_step(3, True, 0) is None         # ещё не прошло и суток
    assert S.next_step(float('nan'), False, 0) is None
    assert S.next_step('не дата', False, 0) is None


def test_only_two_steps_need_their_own_words():
    assert S.NEW_STEPS == (2, 4)
    # 1 и 3 остаются на измеренных рельсах (miss / story / topic / proactive_reply)
    assert asyncio.run(S.compose(1, 917399999, 'anna_01', 'ru')) is None
    assert asyncio.run(S.compose(3, 917399999, 'anna_01', 'ru')) is None
    assert asyncio.run(S.compose(5, 917399999, 'anna_01', 'ru')) is None


# ── 2. тексты ступеней ───────────────────────────────────────────────────────
def test_the_cooling_scene_is_hers_and_short():
    ru = {S.cooling_line('ru') for _ in range(30)}
    en = {S.cooling_line('en') for _ in range(30)}
    assert ru <= set(S._COOLING_RU) and en <= set(S._COOLING_EN) and not (ru & en)
    assert len(ru) > 1 and len(en) > 1             # одна и та же строка каждый раз — шаблон
    for line in list(S._COOLING_RU) + list(S._COOLING_EN):
        assert '*' not in line and len(line) < 130
    # недосказанность, а не упрёк
    assert not any(w in line.lower() for line in S._COOLING_RU
                   for w in ('почему ты', 'почему не', 'ты игноришь'))


def test_the_gift_leaves_him_the_memory_not_a_peach():
    with_fact = S.gift_line('он боится голубей', 'ru')
    assert 'неделя без тебя' in with_fact and 'он боится голубей' in with_fact
    assert 'персик' not in with_fact.lower()       # подарок — кадр, а не валюта
    plain = S.gift_line('', 'ru')
    assert 'кое-что для тебя оставила' in plain and '«' not in plain
    assert S.gift_line('', 'en') in S._GIFT_EN_PLAIN


def test_a_gift_needs_something_to_give():
    tid, uid, char = _user()
    # ни её памяти про него, ни кадра в её пуле — ступень молчит и отдаёт ход
    # прежней рельсе, а не приходит пустой подписью «держани»
    assert asyncio.run(S.compose(4, tid, char, 'ru')) is None
    assert _dialog(uid, char) == []


# ── 3. чипсы: его строка под её сценой ───────────────────────────────────────
def test_scheduled_chips_survive_in_the_message_not_a_telegram_keyboard(monkeypatch):
    import json
    from datetime import datetime, timedelta, timezone
    from models.app_models import CharacterState, User
    from services import app_ping, scheduler_service as scheduler, webapp_service

    tid, uid, char = _user()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with SessionLocal() as s:
        user = s.get(User, uid)
        user.selected_character = char
        user.last_active_at = now - timedelta(hours=50)
        user.proactive_enabled = True
        s.add(CharacterState(user_id=uid, character_id=char, nudge_count=1,
                             last_nudge_at=now - timedelta(hours=26)))
        s.commit()
    chips = ['Что было дальше?', 'Ты откуда пишешь?', 'Продолжай']
    text = 'У нас осталась незакрытая сцена.'
    expected = [{'type': 'reply', 'label': chip, 'text': chip} for chip in chips]

    async def compose(step, telegram_id, character_id, lang):
        assert (step, telegram_id, character_id) == (2, tid, char)
        return {'text': text, 'chips': chips, 'photo': None}

    notifications = []

    def note(bot, telegram_id, character_id, body, **kwargs):
        # The notification is only queued after a committed, actionable row exists.
        rows = _dialog(uid, char)
        assert len(rows) == 1 and json.loads(rows[0].actions_json) == expected
        notifications.append((telegram_id, character_id, body, kwargs))

    def no_legacy_store(*args, **kwargs):
        raise AssertionError('scheduled chips must not use the Telegram chip store')

    monkeypatch.setattr(scheduler, '_push_ok', lambda user_id, *a: user_id == uid)
    monkeypatch.setattr(S, 'compose', compose)
    monkeypatch.setattr(S, 'note_chips', no_legacy_store)
    monkeypatch.setattr(S, 'chips_markup', no_legacy_store)
    monkeypatch.setattr(app_ping, 'note', note)
    asyncio.run(scheduler._proactive(object()))

    # Fresh sessions/history reads require no transient chip cache after restart.
    rows = _dialog(uid, char)
    assert len(rows) == 1 and rows[0].content == text and rows[0].origin == 'push'
    assert json.loads(rows[0].actions_json) == expected
    history = webapp_service.api_chat_history(uid, char)
    assert len(history) == 1 and history[0]['id'] == rows[0].id
    assert history[0]['actions'] == expected
    assert notifications == [(tid, char, '', {'channel': 'default', 'generic': True})]


def test_legacy_telegram_chips_remain_readable_after_a_redeploy():
    tid, _uid, char = _user()
    S.note_chips(tid, char, ['Что было дальше?', 'Ты откуда пишешь?', 'Третья', 'четвёртая'])
    assert S.chip(tid, 0) == (char, 'Что было дальше?')
    assert S.chip(tid, 1)[1] == 'Ты откуда пишешь?'
    assert S.chip(tid, 2)[1] == 'Третья'
    assert S.chip(tid, 3) == ('', '')              # четвертого чипса она не кладёт
    assert S.chip(tid + 10 ** 7, 0) == ('', '')    # чужой тап не выдаёт чужую строку
    with SessionLocal() as s:                      # состояние — в dialog_sessions
        assert s.scalar(select(DialogSession.session_key).where(
            DialogSession.telegram_id == int(tid),
            DialogSession.session_key == 'ladder_chips')) == 'ladder_chips'


def test_the_chip_buttons_carry_only_an_index():
    markup = S.chips_markup(['Одна', 'Две'])
    rows = markup.inline_keyboard
    assert [b.callback_data for b in rows[0]] == ['ladder_chip:0']
    assert rows[1][0].callback_data == 'ladder_chip:1'
    assert 'Одна' == rows[0][0].text
    assert S.chips_markup([]) is None
    # в callback нет ни её фразы, ни чужого текста — только номер
    assert 'ladder_chip:{i}' in LADDER and 'callback_data=f' in LADDER


def test_the_legacy_tap_only_opens_the_app():
    assert "F.data.startswith('ladder_chip:')" in MAIN
    handler = MAIN[MAIN.index('async def on_ladder_chip_tap'):MAIN.index('async def _tap_her_button')]
    assert 'await app_only_callback(cq)' in handler
    resolver = MAIN[MAIN.index('def _bot_callback_character'):MAIN.index('async def app_only_callback')]
    assert 'silence_ladder.chip(' in resolver
    shared = MAIN[MAIN.index('async def _tap_her_button'):MAIN.index('_constructor_sessions =')]
    assert 'await _redirect_bot_chat(cq.message, cq.from_user, character_id)' in shared
    assert 'anna_reply' not in shared and 'can_send_message' not in shared


# ── 4. рельса: слот тратится только на сыгравшую ступень ─────────────────────
def test_the_step_is_chosen_before_the_slot_is_spent():
    assert 'step=silence_ladder.next_step(hours,returned,nudge_count)' in PROACTIVE
    assert PROACTIVE.index('if step is None: continue') < PROACTIVE.index('st.last_nudge_at=now')
    # прежние стражи на месте: интервал и потолок из 4
    assert 'nudge_count >= RETENTION_MAX_NUDGES' in PROACTIVE
    assert 'RETENTION_NUDGE_INTERVAL_HOURS*3600' in PROACTIVE


def test_the_new_steps_are_delivered_counted_and_end_the_loop():
    body = PROACTIVE[PROACTIVE.index('if step in silence_ladder.NEW_STEPS:'):]
    sent = body[:body.index('if hours < PROACTIVE_MIN_HOURS:')]
    assert "silence_ladder.compose(step,telegram_id,char_id,user_lang)" in sent
    assert "actions=[{'type': 'reply', 'label': chip, 'text': chip} for chip in chips]" in sent
    assert "if not _app_delivery(bot,uid,telegram_id,char_id,pack['text'],shot,actions=actions):" in sent
    assert 'silence_ladder.note_chips(' not in sent
    assert 'silence_ladder.chips_markup(' not in sent and 'bot.send_' not in sent
    assert sent.index('_app_delivery(') < sent.index('track_event(')
    assert "f'ladder_{step}'" in sent
    assert sent.rstrip().endswith('continue')
    # не собралось — говорит прежняя рельса, а не молчит
    assert 'if pack and pack' in sent


def test_a_gift_frame_goes_through_the_shared_free_cap():
    tid, uid, char = _user()
    from services import chat_photo_allowance as A
    from services import retention_features_service as rfs
    for i in range(3):
        assert rfs.add_proactive_photo(b'g%d' % i + b'x' * 50, 'image/jpeg', 'photo',
                                       character_id=char)
    assert A.frames_left(uid) == config.FREE_FRAMES_PER_DAY
    assert S._gift_frame(tid, char) is not None
    assert S._gift_frame(tid, char) is not None
    assert A.frames_left(uid) == 0
    assert S._gift_frame(tid, char) is None        # третий кадр — только текстом
    assert 'frames_left(uid) <= 0' in LADDER and 'use_push_frame' in LADDER
    assert 'generate_image' not in LADDER          # и тем более не рендер провайдера


def test_the_scene_step_needs_its_chips():
    body = LADDER[LADDER.index('async def compose('):LADDER.index('def _store()')]
    assert 'greeting_service.opening(' in body      # карточка та же, что при открытии чата
    assert 'explicit_mode.is_on_for(' in body       # и в том же режиме
    assert 'if not chips:' in body and 'return None' in body
    assert '[:3]' in body                           # три строки, не стена кнопок
