"""V3.152.0: owner ТЗ (Фогель, «Спринт 1») — Модуль 1 «Стертый черновик» +
Модуль 5 «живой биоритм».

Модуль 1 (50 🍑):
1. ответ из трёх блоков — THOUGHT / DRAFT / MESSAGE; платный текст живёт в
   отдельной колонке ``messages.draft_text`` и никогда не попадает в ``content``,
   в историю промпта, в озвучку, в payload приложения и в JSON истории, пока за
   него не уплачено;
2. триггер: 15–20 % ответов с уровня 2+, гарантированно при резком переходе на
   18+ на ранних уровнях, не чаще DRAFT_MAX_PER_DAY раз в сутки на пару;
3. деньги: списание ровно один раз, повторный тап бесплатный, при нехватке
   персиков черновик остаётся покупаемым, а не съеденным; чужая строка —
   not_found; владелец читает даром;
4. UI: карточка мыслей → «печатает…» 4 с → серая тарелка → MESSAGE; цена,
   триггер и лимиты — настройки в config.py.

Модуль 5: фазы суток 06–11 / 11–18 / 18–23 / 23–06, блок
``[CURRENT TIME CONTEXT]`` только в живом диалоге (уровень > 0), ночная
откровенность — только с уровня 6 и при открытой откровенности.
"""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select, update

from config import (DRAFT_MAX_PER_DAY, DRAFT_MIN_LEVEL, DRAFT_PEACH_COST,
                    DRAFT_TRIGGER_PCT)
from models.app_models import Message, User
from services.chat_service import (
    draft_block, join_thought_message, message_block, novel_draft,
    novel_format_suffix, split_thought_message, thought_block,
)
from services.db import SessionLocal
from services.memory_service import save_message
from services.ui_lang import FLOW_TEXT, flow_text
from services.user_service import ensure_user, update_user_settings
from services.webapp_service import api_chat_history
import services.chat_service as cs
import services.draft_service as ds
import services.biorhythm as br

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
WEBAPP = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
CONF = (ROOT / 'config.py').read_text(encoding='utf-8')
CHAR_SRC = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')

RAW3 = ('THOUGHT: у меня локти горят, я держу телефон экраном вниз и всё равно '
        'читаю его строчку третий раз\n'
        'DRAFT: я набрала, что чувствую его ладони у себя на талии и что не сплю '
        'из-за его сообщений, но не решусь это отправить\n'
        'MESSAGE: ты чего в такое время пишешь 🙂 я уже в пижаме, но чайник поставлю')

# одно слово из черновика — по нему и проверяем, что платный текст не уехал
PAID_WORD = 'талии'


def _fake_llm(monkeypatch, text):
    """Mock the dialogue model and remember every message array it was given."""
    seen = []

    async def fake(messages, **kw):
        seen.append(list(messages))
        return SimpleNamespace(text=text, provider='test', complete=True)

    monkeypatch.setattr(cs, 'generate_text', fake)
    return seen


def _talked(tid, name, n=5):
    """Five saved lines: the turn under test is the 6th — past the onboarding
    demo, which fires on the 5th."""
    uid = ensure_user(tid, name, language_code='ru')
    for i in range(n):
        save_message(uid, 'anna_01', 'user', f'привет {i}')
    return uid


def _draft_row(tid, name, draft='я бы призналась всё до конца', content='MESSAGE: держусь'):
    uid = ensure_user(tid, name, language_code='ru')
    mid = save_message(uid, 'anna_01', 'assistant', content, draft_text=draft)
    return uid, mid


def _peaches(tid) -> int:
    with SessionLocal() as s:
        return int(s.scalar(select(User.photo_credits)
                            .where(User.telegram_id == str(tid))) or 0)


def _set_peaches(tid, amount):
    with SessionLocal() as s:
        s.execute(update(User).where(User.telegram_id == str(tid))
                  .values(photo_credits=amount))
        s.commit()


def _row(mid) -> Message:
    with SessionLocal() as s:
        return s.get(Message, int(mid))


def _slice(text, start, end=None):
    """The lines between two exact markers of a big source file."""
    i = text.index(start)
    if end is None:
        return text[i:]
    j = text.index(end, i)
    return text[i:j]


# ── 1. парсер: три блока ────────────────────────────────────────────────────

def test_three_blocks_split_and_the_paid_text_stays_alone():
    th, md = split_thought_message(RAW3)
    assert th.startswith('у меня локти горят')
    assert md.startswith('ты чего в такое время')
    assert PAID_WORD in draft_block(RAW3)
    # ни в сообщение, ни в карточку черновик не попадает
    assert PAID_WORD not in md and PAID_WORD not in th
    assert PAID_WORD not in message_block(RAW3)
    assert 'DRAFT' not in message_block(RAW3)


def test_russian_draft_marker_parses_too():
    raw = 'МЫСЛИ: ох\nЧЕРНОВИК: secret words\nСООБЩЕНИЕ: иду на кухню'
    assert draft_block(raw) == 'secret words'
    assert message_block(raw) == 'иду на кухню'


def test_a_broken_format_never_hands_the_draft_out_for_free():
    # блоки открыты, MESSAGE пуст — он получает карточку, а не платный текст
    raw = 'THOUGHT: молчу, мне страшно\nDRAFT: ' + PAID_WORD + '\nMESSAGE:'
    assert PAID_WORD not in message_block(raw)
    assert PAID_WORD not in thought_block(raw)
    assert message_block(raw) == 'молчу, мне страшно'


def test_the_draft_is_cleaned_like_the_card():
    dr = novel_draft('THOUGHT: а\nDRAFT: **я хочу** тебя\n   вернуть, и не только\nMESSAGE: ок')
    assert '*' not in dr and '\n' not in dr and 'я хочу' in dr
    assert novel_draft('THOUGHT: а\nMESSAGE: ок') == ''
    assert novel_draft('просто ответ без меток') == ''
    assert draft_block('просто ответ без меток') == ''


def test_the_stored_message_has_no_draft_marker_at_all():
    th, md = split_thought_message(RAW3)
    joined = join_thought_message(th, md)
    assert 'DRAFT' not in joined and PAID_WORD not in joined
    assert (thought_block(joined), message_block(joined)) == (th, md)
    assert novel_draft(joined) == ''


# ── 2. промпт: скрытый триггер и формат трёх блоков ─────────────────────────

def test_the_trigger_rides_before_the_three_block_rule(monkeypatch):
    tid = 557101
    _talked(tid, 'draftPrompt')
    monkeypatch.setattr(ds, 'will_trigger', lambda *a, **kw: True)
    seen = _fake_llm(monkeypatch, RAW3)
    answer = asyncio.run(cs.reply(tid, 'draftPrompt', 'ты чего не отвечаешь',
                                  language_code='ru'))
    msgs = seen[0]
    assert msgs[-1]['role'] == 'system'
    assert msgs[-1]['content'] == ds.DRAFT_FORMAT_SUFFIX
    assert msgs[-2]['content'].startswith('[SYSTEM TRIGGER: DRAFT_MESSAGE]')
    assert msgs[-3] == {'role': 'user', 'content': 'ты чего не отвечаешь'}
    # одна карточка и одно сообщение — черновика в его тексте нет
    assert PAID_WORD not in answer and 'DRAFT' not in answer


def test_the_draft_lands_in_its_own_column_not_in_the_text(monkeypatch):
    tid = 557102
    _talked(tid, 'draftColumn')
    monkeypatch.setattr(ds, 'will_trigger', lambda *a, **kw: True)
    _fake_llm(monkeypatch, RAW3)
    asyncio.run(cs.reply(tid, 'draftColumn', 'ты где пропала', language_code='ru'))
    offer = ds.take_pending(tid, 'anna_01')
    assert offer and offer['price'] == DRAFT_PEACH_COST
    row = _row(offer['id'])
    assert PAID_WORD in (row.draft_text or '')
    assert PAID_WORD not in row.content and 'DRAFT' not in row.content
    assert thought_block(row.content) and message_block(row.content)


def test_the_draft_never_comes_back_to_the_model_as_a_free_line(monkeypatch):
    tid = 557103
    # восемь линий в запасе: 5-е и 7-е сообщения отдаёт скрипт онбординга,
    # а нам нужны два настоящих хода движка
    _talked(tid, 'draftHistory', n=7)
    monkeypatch.setattr(ds, 'will_trigger', lambda *a, **kw: True)
    _fake_llm(monkeypatch, RAW3)
    asyncio.run(cs.reply(tid, 'draftHistory', 'расскажи, о чём думаешь', language_code='ru'))
    seen = _fake_llm(monkeypatch, 'THOUGHT: пусто\nMESSAGE: всё хорошо')
    asyncio.run(cs.reply(tid, 'draftHistory', 'и всё-таки?', language_code='ru'))
    leaked = [m for m in seen[0] if PAID_WORD in json.dumps(m, ensure_ascii=False)]
    assert not leaked
    # история при этом на месте — тест не пустой
    assert any('THOUGHT:' in json.dumps(m, ensure_ascii=False) for m in seen[0])


def test_without_the_trigger_the_engine_stays_exactly_as_it_was(monkeypatch):
    tid = 557104
    _talked(tid, 'draftOff')
    monkeypatch.setattr(ds, 'will_trigger', lambda *a, **kw: False)
    seen = _fake_llm(monkeypatch, RAW3)
    asyncio.run(cs.reply(tid, 'draftOff', 'привет', language_code='ru'))
    assert seen[0][-1]['content'] == cs.NOVEL_FORMAT_SUFFIX
    assert not any('[SYSTEM TRIGGER: DRAFT_MESSAGE]' in str(m) for m in seen[0])
    assert ds.take_pending(tid, 'anna_01') is None


def test_the_draft_suffix_demands_the_contrast():
    suffix = novel_format_suffix(draft=True)
    assert 'THOUGHT:' in suffix and 'DRAFT:' in suffix and 'MESSAGE:' in suffix
    assert 'ГРАНИЦА ТА ЖЕ' in suffix          # цензуру Premium не обходит
    assert 'в душе' in suffix                 # анти-штамп живёт и здесь
    assert 'одна карточка мыслей' in suffix   # ТЗ: строго один пузырь за тап
    assert novel_format_suffix() is cs.NOVEL_FORMAT_SUFFIX


# ── 3. триггер: уровень, проценты, лимит, резкий переход ────────────────────

def test_the_knobs_are_the_tz_numbers():
    assert DRAFT_PEACH_COST == 50 and ds.price() == 50
    assert 15 <= DRAFT_TRIGGER_PCT <= 20
    assert DRAFT_MIN_LEVEL == 2 and DRAFT_MAX_PER_DAY == 4
    for knob in ('DRAFT_PRICE_PEACHES', 'DRAFT_TRIGGER_PCT',
                 'DRAFT_MIN_LEVEL', 'DRAFT_MAX_PER_DAY'):
        assert knob in CONF


def test_level_one_gets_no_plate(monkeypatch):
    monkeypatch.setattr(ds, 'count_today', lambda *a: 0)
    monkeypatch.setattr(ds, 'DRAFT_TRIGGER_PCT', 100)
    assert ds.will_trigger(1, 'anna_01', 1, 'привет') is False
    assert ds.will_trigger(1, 'anna_01', 2, 'привет') is True


def test_four_plates_a_day_is_the_ceiling(monkeypatch):
    monkeypatch.setattr(ds, 'DRAFT_TRIGGER_PCT', 100)
    monkeypatch.setattr(ds, 'count_today', lambda *a: DRAFT_MAX_PER_DAY)
    assert ds.will_trigger(1, 'anna_01', 5, 'привет') is False
    monkeypatch.setattr(ds, 'count_today', lambda *a: DRAFT_MAX_PER_DAY - 1)
    assert ds.will_trigger(1, 'anna_01', 5, 'привет') is True


def test_sharp_pivot_to_18plus_is_guaranteed_at_early_levels(monkeypatch):
    monkeypatch.setattr(ds, 'count_today', lambda *a: 0)
    monkeypatch.setattr(ds, 'DRAFT_TRIGGER_PCT', 0)      # кости убраны
    import services.intimacy_gate as ig
    monkeypatch.setattr(ig, 'wants_sext', lambda t: True)
    assert ds.will_trigger(1, 'anna_01', 2, 'хочу тебя') is True
    assert ds.will_trigger(1, 'anna_01', 5, 'хочу тебя') is True
    # на 6+ она уже не теряется — там обычная вероятность
    assert ds.will_trigger(1, 'anna_01', 6, 'хочу тебя') is False


def test_a_free_draft_switches_the_whole_feature_off(monkeypatch):
    monkeypatch.setattr(ds, 'count_today', lambda *a: 0)
    monkeypatch.setattr(ds, 'DRAFT_PEACH_COST', 0)
    assert ds.will_trigger(1, 'anna_01', 5, 'хочу тебя') is False


def test_count_today_only_counts_todays_erased_drafts():
    tid = 557110
    uid = ensure_user(tid, 'draftCount', language_code='ru')
    before = ds.count_today(uid, 'anna_01')
    save_message(uid, 'anna_01', 'assistant', 'MESSAGE: ок', draft_text='набрала и стёрла')
    save_message(uid, 'anna_01', 'assistant', 'MESSAGE: ок')
    assert ds.count_today(uid, 'anna_01') == before + 1


# ── 4. деньги ───────────────────────────────────────────────────────────────

def test_unlock_charges_once_and_the_second_tap_is_free():
    tid = 557120
    draft = 'я бы призналась всё до конца'
    uid, mid = _draft_row(tid, 'draftPay', draft=draft)
    _set_peaches(tid, 200)
    res = ds.unlock(tid, 'anna_01', mid, db_user_id=uid)
    assert res['ok'] and res['text'] == draft and res['price'] == DRAFT_PEACH_COST
    assert _peaches(tid) == 200 - DRAFT_PEACH_COST
    assert _row(mid).draft_unlocked is True
    again = ds.unlock(tid, 'anna_01', mid, db_user_id=uid)
    assert again['ok'] and again['free'] and again['price'] == 0
    assert again['text'] == draft and _peaches(tid) == 200 - DRAFT_PEACH_COST


def test_a_failed_charge_leaves_the_draft_buyable_not_eaten(monkeypatch):
    tid = 557121
    draft = 'то, что она не отправила'
    uid, mid = _draft_row(tid, 'draftFail', draft=draft)
    _set_peaches(tid, 10)
    import services.payments as pay
    monkeypatch.setattr(pay, 'spend_peaches', lambda *a, **kw: False)
    res = ds.unlock(tid, 'anna_01', mid, db_user_id=uid)
    assert res == {'ok': False, 'error': 'insufficient_peaches', 'cost': DRAFT_PEACH_COST}
    assert _peaches(tid) == 10
    row = _row(mid)
    assert not row.draft_unlocked            # захват снят — оплатит позже
    assert row.draft_text == draft


def test_the_owner_reads_it_without_spending(monkeypatch):
    tid = 557122
    uid, mid = _draft_row(tid, 'draftOwner', draft='черновик для владельца')
    _set_peaches(tid, 500)
    monkeypatch.setattr(ds, 'ADMIN_TELEGRAM_IDS', {tid})

    def _boom(*a, **kw):
        raise AssertionError('списание вызвано для владельца')

    import services.payments as pay
    monkeypatch.setattr(pay, 'spend_peaches', _boom)
    res = ds.unlock(tid, 'anna_01', mid, db_user_id=uid)
    assert res['ok'] and res['free'] and res['text'] == 'черновик для владельца'
    assert _peaches(tid) == 500


def test_his_plate_points_only_at_his_own_row():
    tid = 557123
    uid_owner, mid = _draft_row(tid, 'draftMine', draft='её черновик мне')
    uid_other, _mid = _draft_row(557124, 'draftOther')
    _set_peaches(tid, 200)
    assert ds.unlock(tid, 'anna_01', mid, db_user_id=uid_other) == \
        {'ok': False, 'error': 'not_found'}
    assert _peaches(tid) == 200                  # чужая строка не съела персики
    assert ds.unlock(tid, 'anna_01', 999999999, db_user_id=uid_owner) == \
        {'ok': False, 'error': 'not_found'}
    assert ds.unlock(tid, 'alisa_01', mid, db_user_id=uid_owner) == \
        {'ok': False, 'error': 'not_found'}


def test_a_plain_message_has_nothing_to_unlock():
    tid = 557125
    uid, mid = _draft_row(tid, 'draftNone', draft=None)
    assert ds.unlock(tid, 'anna_01', mid, db_user_id=uid) == {'ok': False, 'error': 'not_found'}


def test_the_pending_plate_carries_no_text():
    tid = 557126
    uid = ensure_user(tid, 'draftPending', language_code='ru')
    mid = save_message(uid, 'anna_01', 'assistant', 'MESSAGE: держусь',
                       draft_text='секрет, который не уедет в payload')
    ds.note_pending(tid, 'anna_01', mid)
    assert ds.peek_pending(tid, 'anna_01') == {'id': mid, 'price': DRAFT_PEACH_COST}
    offer = ds.take_pending(tid, 'anna_01')
    assert set(offer) == {'id', 'price'}
    assert 'секрет' not in json.dumps(offer, ensure_ascii=False)
    assert ds.take_pending(tid, 'anna_01') is None   # тарелка читается один раз


def test_a_stale_plate_is_dropped(monkeypatch):
    tid = 557127
    uid = ensure_user(tid, 'draftStale', language_code='ru')
    mid = save_message(uid, 'anna_01', 'assistant', 'MESSAGE: ок', draft_text='старое')
    ds.note_pending(tid, 'anna_01', mid)
    monkeypatch.setattr(ds, '_PENDING_TTL_SECONDS', -1.0)
    assert ds.take_pending(tid, 'anna_01') is None
    assert ds.peek_pending(tid, 'anna_01') is None


# ── 5. история приложения: до и после оплаты ────────────────────────────────

def test_locked_draft_leaves_the_server_without_its_text():
    tid = 557130
    draft = 'то, что она стёрла, — платный текст'
    uid, mid = _draft_row(tid, 'draftLocked', draft=draft)
    history = api_chat_history(uid, 'anna_01', 30)
    entry = [h for h in history if h['id'] == mid][0]
    assert entry['draft'] == {'paid': False, 'price': DRAFT_PEACH_COST, 'text': ''}
    assert draft not in json.dumps(history, ensure_ascii=False)


def test_the_history_ships_the_text_only_after_payment():
    tid = 557131
    draft = 'текст, за который он уже заплатил'
    uid, mid = _draft_row(tid, 'draftPaid', draft=draft)
    _set_peaches(tid, 0)
    res = ds.unlock(tid, 'anna_01', mid, db_user_id=uid)
    assert res['ok'] is False and res['error'] == 'insufficient_peaches'
    entry = [h for h in api_chat_history(uid, 'anna_01', 30) if h['id'] == mid][0]
    assert entry['draft']['paid'] is False
    _set_peaches(tid, 500)
    assert ds.unlock(tid, 'anna_01', mid, db_user_id=uid)['ok']
    entry = [h for h in api_chat_history(uid, 'anna_01', 30) if h['id'] == mid][0]
    assert entry['draft']['paid'] and entry['draft']['text'] == draft
    assert ds.draft_of(uid, mid) == draft


def test_rows_without_a_draft_carry_no_draft_key():
    tid = 557132
    uid = ensure_user(tid, 'draftAbsent', language_code='ru')
    mid = save_message(uid, 'anna_01', 'assistant', 'MESSAGE: просто ответ')
    entry = [h for h in api_chat_history(uid, 'anna_01', 30) if h['id'] == mid][0]
    assert 'draft' not in entry


# ── 6. Модуль 5: биоритм ────────────────────────────────────────────────────

def test_the_day_phases_are_the_tz_windows():
    assert [br.phase(h) for h in (6, 9, 10)] == [br.MORNING] * 3
    assert [br.phase(h) for h in (11, 14, 17)] == [br.DAY] * 3
    assert [br.phase(h) for h in (18, 21, 22)] == [br.EVENING] * 3
    assert [br.phase(h) for h in (23, 0, 3, 5)] == [br.NIGHT] * 4


def test_every_phase_block_is_marked_and_subordinate():
    for hour in (8, 13, 20, 1):
        text = br.phase_directive(hour, level=4)
        assert text.startswith('[CURRENT TIME CONTEXT]')
        assert text.rstrip().endswith('она слышна в том, как ты пишешь.')
        assert 'не переписывай из-за неё то' in text


def test_night_is_a_whisper_and_opens_only_with_level_and_premium():
    plain = br.phase_directive(23, level=1)
    assert 'ГЛУБОКАЯ НОЧЬ (23–06)' in plain and 'шёпот' in plain
    assert 'ты трогаешь себя' not in plain
    assert 'лежишь с телефоном' in plain
    high = br.phase_directive(23, level=6)
    assert 'ты трогаешь себя' not in high          # откровенность ещё не открыта
    assert 'не можешь уснуть от мыслей' in high
    hot = br.phase_directive(23, level=6, spicy_open=True)
    assert 'ты трогаешь себя в постели и думаешь о нём' in hot
    assert 'шёпотом' in hot                        # и открытая — только шёпотом
    assert 'уровень' not in hot                    # скрытая кухня наружу не лезет


def test_someones_husband_shows_up_in_the_tone():
    for status, word in (('mar_married', 'Муж'), ('mar_boyfriend', 'Парень')):
        assert word in br.phase_directive(20, level=3, marital_status=status)
        assert word in br.phase_directive(13, level=3, marital_status=status)
    free = br.phase_directive(20, level=3, marital_status='mar_single')
    assert 'Муж' not in free and 'Парень' not in free


def test_the_time_block_rides_only_in_the_live_dialog():
    tid = 557140
    ensure_user(tid, 'bioTime', language_code='ru')
    update_user_settings(tid, timezone='Europe/Moscow')
    plain = cs._time_context(tid, 'anna_01')
    assert '[CURRENT TIME CONTEXT]' not in plain and 'время суток' in plain
    live = cs._time_context(tid, 'anna_01', level=3)
    assert live.count('[CURRENT TIME CONTEXT]') == 1
    # метка и тон берутся из одного места: «день» в шёпоте ночи не пройдёт
    labels = {'утро': 'УТРО (06–11)', 'день': 'ДЕНЬ (11–18)',
              'вечер': 'ВЕЧЕР (18–23)', 'ночь': 'ГЛУБОКАЯ НОЧЬ (23–06)'}
    hits = [w for w, head in labels.items()
            if f'время суток: {w}.' in live and head in live]
    assert len(hits) == 1, live


def test_only_the_live_dialog_asks_for_the_tone_block():
    calls = [ln.strip() for ln in CHAR_SRC.splitlines() if 'time_context=_time_context(' in ln]
    assert len(calls) >= 3
    assert sum(1 for c in calls if 'level=adaptation_level' in c) == 1
    assert sum(1 for c in calls if 'level=' not in c) >= 2   # пуши — без тонового блока
    assert 'if level else' in CHAR_SRC


def test_the_hour_block_and_the_draft_never_reach_the_voice():
    # озвучка и пуши берут только MESSAGE: ни карточка, ни платный черновик
    # в TTS не передаются («В TTS (озвучку) этот блок НЕ передавать!»)
    assert '_send_novel_answer(message, thought, message_block(text)' in MAIN
    assert "said = message_block(answer or '')" in MAIN
    assert 'draft_block' not in MAIN and 'draft_text' not in MAIN
    assert 'draft_block' not in WEBAPP and 'draft_text' not in WEBAPP
    assert 'thought_block(' in MAIN          # карточка живёт отдельным сообщением


# ── 7. тексты, кнопка в Telegram, эндпоинт, приложение ──────────────────────

def test_every_language_has_the_plate_and_the_button():
    for code in FLOW_TEXT:
        for key, values in (('draft_plate', {'name': 'Анна'}),
                            ('draft_button', {'price': 50}),
                            ('draft_unlocked', {'name': 'Анна', 'text': 'текст'}),
                            ('draft_gone', {})):
            text = flow_text(code, key, **values)
            assert text and '{' not in text, (code, key)
        assert '50' in flow_text(code, 'draft_button', price=DRAFT_PEACH_COST)
        assert 'Анна' in flow_text(code, 'draft_plate', name='Анна')


def test_main_sells_the_plate_in_telegram():
    assert 'callback_data=f"draft:unlock:{offer.get(\'id\')}"' in MAIN
    assert "F.data.startswith('draft:unlock:')" in MAIN
    assert 'async def _send_draft_plate(' in MAIN
    assert 'draft_service.take_pending' in MAIN
    assert "flow_text(lang, 'draft_unlocked'" in MAIN
    assert 'await asyncio.to_thread(draft_service.unlock' in MAIN
    assert "add_post('/webapp/api/chat/draft'" in MAIN
    assert "error == 'insufficient_peaches'" in MAIN


def test_the_mini_app_draws_the_plate_and_buys_it():
    assert 'function draftPlate(d)' in WEBAPP
    assert 'function historyLine(m)' in WEBAPP
    assert 'function afterDraft(d, done)' in WEBAPP
    assert 'data-draft="' in WEBAPP and 'unlockDraft' in WEBAPP
    assert "'/webapp/api/chat/draft?init_data=" in WEBAPP
    assert "quickBuy('peaches', () => unlockDraft(id, btn))" in WEBAPP
    assert 'j.history.map(historyLine)' in WEBAPP
    assert 'draft_plate:' in WEBAPP and 'draft_btn:' in WEBAPP and 'draft_open:' in WEBAPP
    assert 'class="dplate' in WEBAPP


def test_the_paid_plate_order_is_card_then_plate_then_message():
    # в истории: карточка → тарелка → её сообщение
    line = [ln for ln in WEBAPP.splitlines() if 'thoughtCard(nv.thought) + draftPlate(d)' in ln][0]
    assert line.index('thoughtCard(nv.thought)') < line.index('draftPlate(d)')
    # вживу: «печатает…» 4 секунды → тарелка → MESSAGE
    after = _slice(WEBAPP, 'function afterDraft(d, done)', 'async function unlockDraft')
    assert after.index('showRecording(') < after.index('draftPlate(d)')
    assert ', 4000,' in after
    reply = _slice(WEBAPP, 'function renderChatReply', 'function insertChatReply')
    assert reply.index('thoughtCard(nv.thought)') < \
        reply.index('afterDraft(j.draft, () => showRecording(')


def test_the_webapp_payload_names_the_plate_without_naming_the_text():
    turn = _slice(MAIN, 'async def _webapp_chat_turn', 'async def _webapp_api_chat_start')
    assert 'draft_offer = draft_service.take_pending(telegram_id, character_id)' in turn
    assert "payload['draft'] = draft_offer" in turn
    assert 'draft_text' not in turn
    assert 'unlock' not in turn
