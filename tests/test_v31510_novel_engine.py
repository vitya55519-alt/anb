"""V3.151.0: owner ТЗ (Фогель) — «Движок визуальной новеллы: мысли vs слова».

Часть 1 (техническая сырость):
1. фоновая «будтовуха» life_event не подмешивается в живой диалог — пуш только
   после того, как замолчал он (LIFE_EVENTS_SILENCE_HOURS, по умолчанию 4 часа);
2. один ответ модели = одна реплика, не 2–3 пузыря (хук «two» убран, правило в
   промпте, поверх карточки splitBubbles не работает);
3. THOUGHT/MESSAGE парсятся и рисуются: в приложении 💭 карточка (розовый
   #FF4D8D, font-weight 700, курсив), в боте 💭 <b>Мысли Имя:</b> <i>…</i>;
   в озвучку этот блок НЕ передаётся; тайминг — карточка сразу, «записывает
   голосовое…» не короче 3 секунд, потом MESSAGE с голосом;
4. после последнего user-сообщения идёт системный суффикс с форматом, запретом
   начинать с чужих имён и запретом штампа «он в душе» / «вода шумит».

Часть 2 (ядро новеллы): два слоя, контраст «думает одно — пишет другое», гейт
по уровню 1–2 / 3–5 / 6–10, один физический шаг за сообщение, taboo для
замужних. Блок [3.1] «Мачеха»: муж для пасынка всегда «твой отец».
"""
import asyncio
import math
import uuid
from pathlib import Path
from types import SimpleNamespace

from services.chat_service import (
    NOVEL_FORMAT_SUFFIX, NOVEL_FORMAT_SUFFIX_DUO, join_thought_message,
    message_block, novel_engine_context, novel_format_suffix, novel_pair,
    split_thought_message, thought_block,
)
from services.custom_character_service import RELATIONSHIP_STORY, SCENARIO_STORY
from services.life_event_service import silence_hours
from services.memory_service import get_recent_messages, save_message
from services.user_service import ensure_user
from services import chat_guest_service as cgs
import services.chat_service as cs

from config import LIFE_EVENTS_SILENCE_HOURS

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CUSTOM = (ROOT / 'services' / 'custom_character_service.py').read_text(encoding='utf-8')
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
HOOKS = (ROOT / 'services' / 'hook_service.py').read_text(encoding='utf-8')
CHAR = (ROOT / 'services' / 'character_service.py').read_text(encoding='utf-8')
WEBAPP = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')

RAW = ('THOUGHT: у меня локти горят, я держу телефон экраном вниз и всё равно '
       'читаю его строчку третий раз\n'
       'MESSAGE: ты чего в такое время пишешь 🙂 я уже в пижаме, но чайник поставлю')


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
    demo (it fires on the 5th and, as a fallback, on the 7th)."""
    uid = ensure_user(tid, name, language_code='ru')
    for i in range(n):
        save_message(uid, 'anna_01', 'user', f'привет {i}')
    return uid


# ── 1. парсер меток ─────────────────────────────────────────────────────────

def test_markers_split_both_layers():
    th, md = split_thought_message(RAW)
    assert th.startswith('у меня локти горят') and 'пижаме' not in th
    assert md.startswith('ты чего в такое время') and 'горят' not in md
    assert thought_block(RAW) == th and message_block(RAW) == md


def test_russian_markers_split_too():
    assert split_thought_message('МЫСЛИ: ох, меня сейчас вынесет\nСООБЩЕНИЕ: иду на кухню') == \
        ('ох, меня сейчас вынесет', 'иду на кухню')


def test_unmarked_answer_stays_exactly_as_it_was():
    # every older caller and every mocked plain answer keeps working
    assert split_thought_message('привет, как ты') == ('', 'привет, как ты')
    assert thought_block('привет, как ты') == ''
    assert message_block('привет, как ты') == 'привет, как ты'


def test_a_card_without_a_message_never_eats_her_reply():
    th, md = novel_pair('THOUGHT: молчу, мне страшно\nMESSAGE:')
    assert md == 'молчу, мне страшно' and th == ''
    # only a THOUGHT block came back: the mark is stripped, he still gets a line
    th, md = novel_pair('THOUGHT: только мысль')
    assert (th, md) == ('', 'только мысль')


def test_join_roundtrips_and_the_card_never_enters_the_spoken_text():
    th, md = novel_pair(RAW)
    joined = join_thought_message(th, md)
    assert joined.startswith('THOUGHT: ') and '\nMESSAGE: ' in joined
    assert (thought_block(joined), message_block(joined)) == (th, md)
    # «В TTS (озвучку) этот блок НЕ передавать!»
    assert 'THOUGHT' not in joined.replace('THOUGHT: ', '', 1)
    assert 'горят' not in message_block(joined)
    assert join_thought_message('', md) == md


def test_the_message_is_cleaned_and_the_card_stays_prose():
    th, md = novel_pair('THOUGHT: **не могу** дышать, он опять пишет\n'
                        'MESSAGE: *отворачиваюсь* ну *привет* 🙂')
    assert '**' not in th and '\n' not in th and 'не могу' in th
    assert '*' not in md and 'привет' in md


# ── 2. промпт: формат после последнего user, ядро, гейт по уровню ───────────

def test_the_format_rule_rides_after_his_last_message(monkeypatch):
    tid = 556101
    uid = _talked(tid, 'novelSuffix')
    seen = _fake_llm(monkeypatch, RAW)
    answer = asyncio.run(cs.reply(tid, 'novelSuffix', 'ты чего не отвечаешь', language_code='ru'))
    msgs = seen[0]
    assert msgs[-1]['role'] == 'system' and msgs[-1]['content'] == NOVEL_FORMAT_SUFFIX
    assert msgs[-2] == {'role': 'user', 'content': 'ты чего не отвечаешь'}
    assert msgs[0]['role'] == 'system' and 'ДВИЖОК НОВЕЛЛЫ' in msgs[0]['content']
    assert thought_block(answer) and message_block(answer)
    saved = [m.content for m in get_recent_messages(uid, 'anna_01', 12) if m.role == 'assistant']
    assert answer in saved


def test_duo_chat_keeps_one_layer_but_shares_the_bans(monkeypatch):
    tid = 556102
    _talked(tid, 'novelDuo')
    cgs.set_guest(tid, 'anna_01', 'alisa_01')
    try:
        seen = _fake_llm(monkeypatch, 'Анна: мы вдвоём пришли\nАлиса: и не уходим')
        asyncio.run(cs.reply(tid, 'novelDuo', 'пригласи подругу', language_code='ru'))
        msgs = seen[0]
        assert msgs[-1]['content'] == NOVEL_FORMAT_SUFFIX_DUO
        assert 'ДВИЖОК НОВЕЛЛЫ' not in msgs[0]['content']
    finally:
        cgs.set_guest(tid, 'anna_01', None)


def test_engine_context_gates_levels_and_the_taboo():
    low, mid, high = novel_engine_context(1), novel_engine_context(4), novel_engine_context(8)
    assert 'УРОВЕНЬ 1–2' in low and 'УРОВЕНЬ 3–5' not in low
    assert 'УРОВЕНЬ 3–5' in mid
    assert 'УРОВЕНЬ 6–10' in high and 'УРОВЕНЬ 1–2' not in high
    for block in (low, mid, high):
        assert 'ДВА СЛОЯ' in block and 'КОНТРАСТ' in block
        assert 'один физический шаг' in block.lower()
    married = novel_engine_context(3, 'mar_married')
    assert 'ГДЕ РИСК' in married and 'муж' in married
    bf = novel_engine_context(3, 'mar_boyfriend')
    assert 'ГДЕ РИСК' in bf and 'парень' in bf
    for alone in ('mar_single', 'mar_divorced', 'mar_open', ''):
        assert 'ГДЕ РИСК' not in novel_engine_context(3, alone)


def test_format_suffix_bans_the_shower_gag_and_foreign_names():
    for txt in (NOVEL_FORMAT_SUFFIX, NOVEL_FORMAT_SUFFIX_DUO):
        assert 'ЗАПРЕЩЕНО' in txt and 'вода шумит' in txt
    assert 'имени другой девушки' in NOVEL_FORMAT_SUFFIX
    assert '«Агата:»' in NOVEL_FORMAT_SUFFIX
    assert novel_format_suffix(True) is NOVEL_FORMAT_SUFFIX_DUO
    assert novel_format_suffix() is NOVEL_FORMAT_SUFFIX


def test_prompts_have_no_shower_example_and_one_reply_per_turn():
    # in the constructor stories the gag survives only as a prohibition
    for key in ('mar_boyfriend', 'mar_married'):
        s = RELATIONSHIP_STORY[key]
        assert s.count('он в душе') <= 1 and s.count('вода шумит') <= 1
        assert 'ЗАПРЕЩЕНО' in s and 'он задержался на работе' in s
    assert 'На его сообщение — ОДНА твоя реплика' in CHAR
    assert 'Второе сообщение отделяй пустой строкой' not in CHAR
    # the hook move whose whole job was splitting one answer into two bubbles
    assert "'two':" not in HOOKS and '"two":' not in HOOKS


# ── 3. мачеха [3.1]: муж для пасынка — «твой отец» ──────────────────────────

def test_stepmom_block_calls_his_husband_your_father():
    s = SCENARIO_STORY['scn_stepmom']
    assert 'твой отец' in s and 'твой папа' in s and 'никогда «мой муж»' in s
    assert 'НА УРОВНЯХ 1–2' in s and 'НА УРОВНЯХ 3+' in s
    assert 'не родственники по крови' in s and 'взрослым' in s
    assert 'твой отец' in CUSTOM and 'КАК ЕГО НАЗЫВАТЬ' in CUSTOM


# ── 4. life_event не лезет в живой диалог ───────────────────────────────────

def test_silence_hours_measures_his_last_line():
    uid = ensure_user(556103, 'novelSilent', language_code='ru')
    cid = 'v31510_' + uuid.uuid4().hex[:10]   # a dialog nobody has ever written to
    assert silence_hours(uid, cid) == math.inf
    save_message(uid, cid, 'user', 'привет')
    assert silence_hours(uid, cid) < 0.01        # the dialog is alive
    assert silence_hours(uid, 'alisa_01') == math.inf  # per dialog, not global


def test_life_push_waits_for_the_silence_gate():
    assert LIFE_EVENTS_SILENCE_HOURS >= 4
    body = SCHED[SCHED.index('async def _life_events'):]
    body = body[:body.index('\nasync def ')]
    assert 'silence_hours(uid, char_id) < LIFE_EVENTS_SILENCE_HOURS' in body
    assert body.index('silence_hours(uid, char_id)') < body.index('await build_life_moment')


# ── 5. доставка: карточка → пауза записи → одно сообщение с голосом ─────────

def test_bot_sends_the_card_then_one_message():
    assert '_thought_card' in MAIN and '💭 <b>Мысли' in MAIN
    body = MAIN[MAIN.index('async def _send_answer_body'):]
    body = body[:body.index('\nasync def ')]
    assert 'thought = thought_block(text)' in body
    assert '_send_novel_answer(message, thought, message_block(text), user)' in body
    n = MAIN[MAIN.index('async def _send_novel_answer'):MAIN.index('async def _voice_premium_nudge')]
    assert 'record_voice' in n and 'VOICE_RECORD_MIN_SECONDS' in n and 'answer_voice' in n
    # the voice is built from `said` alone — the card is text only
    assert 'synthesize_bytes(said,' in n


def test_app_voice_and_call_never_speak_the_thought():
    turn = MAIN[MAIN.index('async def _webapp_chat_turn'):]
    turn = turn[:turn.index('\nasync def ')]
    assert 'said = message_block(answer' in turn
    assert 'thought_said = thought_block(answer' in turn
    assert turn.index('said = message_block') < turn.index('_webapp_reply_voice_url')
    assert 'voice_call.spoken(invite_funnel.strip_tag(message_block(answer)))' in MAIN


def test_webapp_draws_the_pink_card_and_holds_the_recording():
    assert '.thcard .th-h { color: #FF4D8D; font-weight: 700' in WEBAPP
    assert '.thcard .th-b { font-style: italic' in WEBAPP
    assert 'function parseThought(' in WEBAPP and 'function thoughtCard(' in WEBAPP
    assert '💭 Мысли ' in WEBAPP and 'rec_voice' in WEBAPP
    render = WEBAPP[WEBAPP.index('function renderChatReply('):WEBAPP.index('function insertChatReply(')]
    assert 'parseThought(String(j.reply' in render and 'thoughtCard(nv.thought)' in render
    assert 'showRecording(() => insertChatReply' in render
    rec = WEBAPP[WEBAPP.index('function showRecording('):WEBAPP.index('function chatBubble(')]
    assert 'Math.max(3000' in rec
    # one bubble per turn, and the history redraws the card, not the raw marks
    assert '|| j.novel) ? [j.reply] : splitBubbles' in WEBAPP
    assert 'content: nv.message, novel: true' in WEBAPP
