"""V3.155.0: owner ТЗ (Фогель, Модуль 3) — «Эмоциональные якоря».

Каждые 15 его сообщений фоновый промпт выжимает из диалога ОДИН яркий общий
момент и кладёт его в user_character_anchors (на пару — последние 5). Блок
[SHARED EMOTIONAL MEMORY (ЯКОРЯ ВАШЕЙ ИСТОРИИ)] едет в системный промпт, а
вслух она вспоминает якорь раз в 4–5 реплик — и только в THOUGHT/MESSAGE, никогда
в озвучку.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from models.app_models import Base, Memory, Message, User, UserCharacterAnchor
from services import anchor_service
from services.db import SessionLocal, engine
from config import ANCHOR_ECHO_MAX, ANCHOR_ECHO_MIN, ANCHOR_EVERY_MESSAGES, ANCHOR_MAX

ROOT = Path(__file__).resolve().parents[1]
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
CHAR = (ROOT / 'services' / 'character_service.py').read_text(encoding='utf-8')
VOICE = (ROOT / 'services' / 'voice_service.py').read_text(encoding='utf-8')

ECHO_LINE = 'ИМЕННО В ЭТОМ ОТВЕТЕ'
CID = 'anna_01'


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _pair(user_messages: int = 0, text: str = 'расскажи мне про тот вечер у озера, я всё думаю'):
    """A fresh (user, girl) pair with ``user_messages`` of his live lines."""
    Base.metadata.create_all(engine)
    stamp = _now().strftime('%H%M%S%f')
    with SessionLocal() as s:
        u = User(telegram_id=f'92{stamp}', name='t')
        s.add(u)
        s.commit()
        uid = u.id
        i = 0
        while i < user_messages:
            body = f'{text} {i}' if i % 2 == 0 else f'ага, и что было дальше {i}'
            s.add(Message(user_id=uid, character_id=CID, role='user', content=body,
                          created_at=_now() + timedelta(minutes=i)))
            s.add(Message(user_id=uid, character_id=CID, role='assistant',
                          content=f'мне тогда было так страшно и так хорошо {i}',
                          created_at=_now() + timedelta(minutes=i, seconds=20)))
            i += 1
        s.commit()
    anchor_service._state[int(uid)] = {}
    return uid


def _echo_calls(uid, times: int = 1):
    return [ECHO_LINE in anchor_service.anchors_block(uid, CID, tick=True) for _ in range(times)]


# ── таблица и её лимит ─────────────────────────────────────────────────────

def test_the_anchor_table_is_autocreated():
    assert 'user_character_anchors' in Base.metadata.tables
    cols = Base.metadata.tables['user_character_anchors'].columns.keys()
    assert {'user_id', 'character_id', 'content', 'created_at'} <= set(cols)


def test_only_the_five_latest_moments_stay_on_the_pair():
    uid = _pair()
    for i in range(8):
        anchor_service.add_anchor(uid, CID, f'как мы вспомнили момент {i}')
    left = anchor_service.list_anchors(uid, CID)
    assert len(left) == min(ANCHOR_MAX, 8) == ANCHOR_MAX
    assert left == [f'как мы вспомнили момент {i}' for i in range(8 - ANCHOR_MAX, 8)]
    # oldest first: she walks through the story in the order it happened
    assert left[0] < left[-1]


def test_the_same_moment_is_not_stored_twice():
    uid = _pair()
    anchor_service.add_anchor(uid, CID, 'тот вечер, когда мы чуть не попались')
    anchor_service.add_anchor(uid, CID, '   тот вечер,   когда мы чуть не попались  ')
    assert len(anchor_service.list_anchors(uid, CID)) == 1


def test_an_empty_anchor_stores_nothing():
    uid = _pair()
    anchor_service.add_anchor(uid, CID, '')
    anchor_service.add_anchor(uid, CID, '   ')
    assert anchor_service.list_anchors(uid, CID) == []


def test_anchors_have_their_own_table_and_touch_nothing_else():
    # memories are stable facts about HIM and their extraction prompt bans the
    # intimate history; an anchor is the pair's own moment, so it must land in
    # its own table and never overwrite his facts or his dialog lines
    uid = _pair()
    anchor_service.add_anchor(uid, CID, 'наша первая ночь')
    with SessionLocal() as s:
        assert s.query(UserCharacterAnchor).filter(
            UserCharacterAnchor.user_id == uid).count() == 1
        assert s.query(Memory).filter(Memory.user_id == uid).count() == 0
        assert s.query(Message).filter(Message.user_id == uid).count() == 0


# ── блок в системном промпте ───────────────────────────────────────────────

def test_the_block_is_the_тз_header_with_the_rhythm_rule():
    uid = _pair()
    anchor_service.add_anchor(uid, CID, 'как мы сидели на кухне до утра')
    block = anchor_service.anchors_block(uid, CID)
    assert block.startswith('[SHARED EMOTIONAL MEMORY (ЯКОРЯ ВАШЕЙ ИСТОРИИ)]')
    assert '- как мы сидели на кухне до утра' in block
    assert 'раз в 4–5 сообщений' in block
    assert 'THOUGHT' in block and 'MESSAGE' in block
    assert 'Не выдумывай' in block
    assert 'не пересказывай момент целиком' in block


def test_a_pair_without_history_gets_no_block():
    assert anchor_service.anchors_block(_pair(), CID) == ''


def test_disabled_module_draws_no_block():
    uid = _pair()
    anchor_service.add_anchor(uid, CID, 'как мы поссорились из-подруги')
    old = anchor_service.ANCHORS_ENABLED
    anchor_service.ANCHORS_ENABLED = False
    try:
        assert anchor_service.anchors_block(uid, CID, tick=True) == ''
    finally:
        anchor_service.ANCHORS_ENABLED = old


# ── ритм воспоминаний ──────────────────────────────────────────────────────

def test_she_remembers_every_four_or_five_replies():
    uid = _pair()
    for i in range(3):
        anchor_service.add_anchor(uid, CID, f'якорь {i}')
    hits = _echo_calls(uid, times=40)
    assert hits[0] is False            # the reply that finds the anchors only starts the clock
    gaps = []
    last = 0
    for n, hit in enumerate(hits[1:], start=1):
        if hit:
            gaps.append(n - last)
            last = n
    assert len(gaps) >= 6
    assert all(ANCHOR_ECHO_MIN <= g <= ANCHOR_ECHO_MAX for g in gaps), gaps


def test_the_recollections_rotate_instead_of_repeating_one():
    uid = _pair()
    for i in range(3):
        anchor_service.add_anchor(uid, CID, f'якорь {i}')
    picked = []
    for _ in range(40):
        block = anchor_service.anchors_block(uid, CID, tick=True)
        if ECHO_LINE in block:
            picked.append([a for a in anchor_service.list_anchors(uid, CID)
                           if a in block.split(ECHO_LINE)[1]][0])
    assert len(set(picked)) == 3


def test_pushes_do_not_spend_the_rhythm():
    uid = _pair()
    anchor_service.add_anchor(uid, CID, 'как мы смеялись над тем курьером')
    anchor_service.anchors_block(uid, CID, tick=True)          # starts the clock
    for _ in range(30):
        assert ECHO_LINE not in anchor_service.anchors_block(uid, CID)   # a push never recollects
    # the clock is still where the live reply left it: three more replies are
    # too few, and had the 30 pushes spent it, one of them would already recall
    assert _echo_calls(uid, times=ANCHOR_ECHO_MIN - 1) == [False] * (ANCHOR_ECHO_MIN - 1)
    assert any(_echo_calls(uid, times=ANCHOR_ECHO_MAX - ANCHOR_ECHO_MIN + 2))


# ── фоновый worker ─────────────────────────────────────────────────────────

class _FakeLLM:
    def __init__(self, text):
        self.calls = []
        self._text = text

    async def __call__(self, messages=None, **kw):
        self.calls.append((messages, kw))
        return SimpleNamespace(text=self._text)


def _run_extraction(monkeypatch, uid, text='{"anchor":"как мы целовались в лифте"}'):
    fake = _FakeLLM(text)
    monkeypatch.setattr('services.llm_provider_service.generate_text', fake)
    asyncio.run(anchor_service.maybe_extract_anchor(uid, CID))
    return fake


def test_the_worker_fires_on_every_fifteenth_of_his_messages(monkeypatch):
    early = _pair(ANCHOR_EVERY_MESSAGES - 1)
    assert _run_extraction(monkeypatch, early).calls == []
    assert anchor_service.list_anchors(early, CID) == []
    due = _pair(ANCHOR_EVERY_MESSAGES)
    fake = _run_extraction(monkeypatch, due)
    assert len(fake.calls) == 1
    assert anchor_service.list_anchors(due, CID) == ['как мы целовались в лифте']
    # and the next boundary is another 15 lines away, not the very next reply
    later = _pair(ANCHOR_EVERY_MESSAGES + 1)
    assert _run_extraction(monkeypatch, later).calls == []
    assert anchor_service.list_anchors(later, CID) == []


def test_the_worker_reads_only_the_recent_dialog(monkeypatch):
    uid = _pair(ANCHOR_EVERY_MESSAGES)
    fake = _run_extraction(monkeypatch, uid)
    transcript = fake.calls[0][0][-1]['content']
    assert 'Он: ' in transcript and 'Она: ' in transcript
    assert fake.calls[0][1]['purpose'] == 'anchor_extraction'
    assert 'JSON' in anchor_service.EXTRACT_PROMPT
    assert 'не выдумывай' in anchor_service.EXTRACT_PROMPT
    assert 'платёжные данные' in anchor_service.EXTRACT_PROMPT


def test_a_thin_dialog_is_not_sent_to_the_model(monkeypatch):
    Base.metadata.create_all(engine)
    stamp = _now().strftime('%H%M%S%f')
    with SessionLocal() as s:
        u = User(telegram_id=f'93{stamp}', name='t')
        s.add(u)
        s.commit()
        uid = u.id
        for i in range(ANCHOR_EVERY_MESSAGES):
            s.add(Message(user_id=uid, character_id=CID, role='user', content='ок',
                          created_at=_now() + timedelta(minutes=i)))
        s.commit()
    assert _run_extraction(monkeypatch, uid).calls == []
    assert anchor_service.list_anchors(uid, CID) == []


def test_junk_from_the_worker_is_never_stored():
    assert anchor_service.parse_anchor('') == ''
    assert anchor_service.parse_anchor('У меня нет яркого момента.') == ''
    assert anchor_service.parse_anchor('{"anchor":""}') == ''
    assert anchor_service.parse_anchor('{"anchor":null}') == ''
    assert anchor_service.parse_anchor('{"anchor":[]}') == ''
    assert anchor_service.parse_anchor('{"anchor":"как мы…"}') == 'как мы…'
    assert len(anchor_service.parse_anchor('{"anchor":"' + 'д' * 500 + '"}')) <= 140


def test_disabled_module_never_calls_the_model(monkeypatch):
    uid = _pair(ANCHOR_EVERY_MESSAGES)
    old = anchor_service.ANCHORS_ENABLED
    anchor_service.ANCHORS_ENABLED = False
    try:
        assert _run_extraction(monkeypatch, uid).calls == []
    finally:
        anchor_service.ANCHORS_ENABLED = old


# ── проводка ───────────────────────────────────────────────────────────────

def test_the_live_reply_carries_the_block_and_starts_the_worker():
    assert 'anchor_service.anchors_block, db_user_id, character_id, tick=not scene' in CHAT
    assert 'anchors=anchors,' in CHAT
    assert '_spawn_background(anchor_service.maybe_extract_anchor(db_user_id, character_id)' in CHAT
    # a push shows the anchors but never spends the counter
    assert CHAT.count('anchor_service.anchors_block, db_user_id, character_id),') == 2


def test_the_block_renders_under_память():
    assert 'anchors: str = ""' in CHAR
    assert 'anchors_block_text = f"\\n{anchors}\\n" if anchors else ""' in CHAR
    assert 'ПАМЯТЬ\n{memory_text}\n{anchors_block_text}' in CHAR


def test_the_anchor_block_never_reaches_the_voice():
    # TTS reads her message text; the service must not be imported there at all
    assert 'anchor' not in VOICE.lower()


def test_the_prompt_block_is_not_a_fifth_message_layer():
    uid = _pair()
    anchor_service.add_anchor(uid, CID, 'как мы разминулись у подъезда')
    block = anchor_service.anchors_block(uid, CID, tick=True)
    for marker in ('THOUGHT:', 'MESSAGE:', 'DRAFT:', '[EVENT ACTIVE]'):
        assert marker not in block
