"""V3.167.4 #173 (владелец ТЗ §6, 16.11): её день не превращается в стену смс.

Пока он не ответил, «жёлтых цветов» в диалоге накапливается не больше трёх
(``LIFE_EVENTS_UNANSWERED_MAX``): рельса встаёт и ждёт, слот суток не сгорает —
после его реплики она заговорит в этой же части суток снова.

Если же он вернулся из паузы длиннее трёх суток
(``LIFE_EVENTS_DIGEST_AFTER_HOURS``), догонять её по одной смс поздно: вместо
трёх опозданий приходит одна сводка того, что у неё было. Сводка склеена из её
же строк, без провайдера и без новых обещаний, ровно один раз за день.
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault('TELEGRAM_TOKEN', '123456:test-fake-token-for-static-tests-only')
os.environ.setdefault('GEMINI_API_KEY', 'x')

from sqlalchemy import select

import config
from models.app_models import DialogSession, Message
from services import life_backlog as B
from services.db import SessionLocal

ROOT = Path(__file__).resolve().parents[1]
CFG = (ROOT / 'config.py').read_text(encoding='utf-8')
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
LIFE = SCHED[SCHED.index('async def _life_events'):SCHED.index('async def _channel_bonus_holds')]

CHAR = 'anna_01'


class _Bot:
    """Только send_message: сводка — статическая склейка её же строк."""

    def __init__(self):
        self.sent = []

    async def send_message(self, telegram_id, text, **_kw):
        self.sent.append((int(telegram_id), text))


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _user() -> tuple[int, int]:
    from services.user_service import ensure_user
    tid = 917350000 + uuid.uuid4().int % 49999
    return tid, ensure_user(tid, 'V')


def _line(uid: int, role: str, text: str, ago: timedelta) -> int:
    from services.memory_service import save_message
    mid = save_message(uid, CHAR, role, text)
    with SessionLocal() as s:
        row = s.get(Message, mid)
        row.created_at = _now() - ago
        s.commit()
        return mid


def _dialog(uid: int) -> list[Message]:
    with SessionLocal() as s:
        return list(s.scalars(select(Message).where(Message.user_id == uid,
                                                    Message.character_id == CHAR)
                              .order_by(Message.id)).all())


# ── 1. пока он молчит, она не сыплет ────────────────────────────────────────
def test_the_pile_is_three_of_her_lines_after_his_last_word():
    tid, uid = _user()
    _line(uid, 'user', 'привет', timedelta(days=6))
    assert B.unanswered(uid, CHAR) == []
    for i, day in enumerate((5, 4, 3)):
        _line(uid, 'assistant', f'её строка {i}', timedelta(days=day))
    assert [t for t, _ in B.unanswered(uid, CHAR)] == ['её строка 0', 'её строка 1', 'её строка 2']
    assert B.is_capped(uid, CHAR) is True          # четвёртая была бы рассылкой
    _line(uid, 'user', 'ого, и что дальше?', timedelta(hours=2))
    assert B.is_capped(uid, CHAR) is False         # он ответил — счётчик обнулился


def test_two_lines_are_still_a_dialog_not_a_wall():
    tid, uid = _user()
    _line(uid, 'user', 'привет', timedelta(days=4))
    _line(uid, 'assistant', 'одна', timedelta(days=3))
    _line(uid, 'assistant', 'две', timedelta(days=2))
    assert B.is_capped(uid, CHAR) is False


def test_the_rail_waits_without_burning_the_slot():
    assert 'life_backlog.is_capped(uid, char_id)' in LIFE
    assert 'from services.life_event_service import build_life_moment' in SCHED
    # кап стоит до того, как что-либо потрачено: ни слота, ни провайдера
    gate = LIFE.index('life_backlog.is_capped(uid, char_id)')
    assert gate < LIFE.index('slots.append(part)')
    assert gate < LIFE.index('live_push(')
    assert gate < LIFE.index('moment = await build_life_moment(')
    assert 'continue' in LIFE[gate:gate + 200]


# ── 2. возврат из длинной паузы: одна сводка вместо трёх догонок ─────────────
def test_the_digest_picks_up_only_the_gap_he_just_left():
    tid, uid = _user()
    _line(uid, 'user', 'был тут', timedelta(days=8))
    _line(uid, 'assistant', 'у меня завал на работе', timedelta(days=7))
    _line(uid, 'assistant', 'сломалась кофеварка', timedelta(days=6))
    _line(uid, 'assistant', 'купила новые кеды', timedelta(days=5))
    _line(uid, 'user', 'вернулся!', timedelta(hours=1))
    _line(uid, 'assistant', 'а вот и ты 🙂', timedelta(minutes=50))   # уже после возврата
    lines, _ts = zip(*B.missed(uid, CHAR))
    assert lines == ('у меня завал на работе', 'сломалась кофеварка', 'купила новые кеды')
    text = B.due(uid, CHAR)
    assert text.startswith('Пока тебя не было, у меня было 3 истории:')
    assert '1) «у меня завал на работе»' in text and '3) «купила новые кеды»' in text
    assert 'а вот и ты' not in text                # его настоящий ход в сводку не попадает
    assert text.endswith('С любой и начнём 💜')


def test_a_short_pause_and_a_single_visit_are_not_a_digest():
    tid, uid = _user()
    _line(uid, 'user', 'привет', timedelta(hours=6))
    _line(uid, 'assistant', 'привет-привет', timedelta(hours=5))
    _line(uid, 'assistant', 'как ты там?', timedelta(hours=4))
    _line(uid, 'user', 'норм', timedelta(hours=1))
    assert B.due(uid, CHAR) == ''                  # пауза короче трёх суток — догонять рано
    tid2, uid2 = _user()
    _line(uid2, 'assistant', 'он писал один раз', timedelta(days=9))
    _line(uid2, 'user', 'и то привет', timedelta(hours=2))
    assert B.missed(uid2, CHAR) == []              # возвращаться было некуда
    assert B.due(uid2, CHAR) == ''


def test_the_digest_is_plain_words_and_both_languages():
    long = 'И ещё целая история про то, как я сегодня не смогла найти второй носок ' * 3
    text = B.digest_text(['короткая', long, 'ещё одна', 'четвёртая не нужна'], 'ru')
    assert text.count('«') == 3                    # больше трёх она не перечисляет
    assert '4)' not in text
    assert '…' in text                             # длинное — на слове, без разорванной фразы
    assert 'While you were away' in B.digest_text(['one', 'two'], 'en')
    assert B.digest_text([], 'ru') == ''


# ── 3. доставка: ровно один раз за сутки ────────────────────────────────────
def test_the_return_gets_one_digest_and_then_she_waits():
    tid, uid = _user()
    _line(uid, 'user', 'ушёл в завал', timedelta(days=9))
    _line(uid, 'assistant', 'принесла документы в офис не ту папку', timedelta(days=8))
    _line(uid, 'assistant', 'дождь застал меня у метро', timedelta(days=7))
    _line(uid, 'user', 'я вернулся', timedelta(hours=1))
    bot = _Bot()
    assert asyncio.run(B.maybe_digest(bot, uid, tid, CHAR, 'ru')) is True
    assert len(bot.sent) == 1 and bot.sent[0][0] == tid
    assert 'у меня было 2 истории' in bot.sent[0][1]
    assert _dialog(uid)[-1].role == 'assistant'    # сводка легла в общий диалог (бейдж Mini App)
    assert asyncio.run(B.maybe_digest(bot, uid, tid, CHAR, 'ru')) is True
    assert len(bot.sent) == 1                      # второй раз за день она не повторяется
    with SessionLocal() as s:                      # отметка живёт в dialog_sessions
        assert s.scalar(select(DialogSession.session_key).where(
            DialogSession.telegram_id == int(tid),
            DialogSession.session_key == 'life_backlog')) == 'life_backlog'


def test_while_he_is_still_away_there_is_nothing_to_sum_up():
    tid, uid = _user()
    _line(uid, 'user', 'пропал на неделю', timedelta(days=7))
    _line(uid, 'assistant', 'у меня переезд', timedelta(days=6))
    _line(uid, 'assistant', 'новый сосед шумит', timedelta(days=5))
    bot = _Bot()
    assert asyncio.run(B.maybe_digest(bot, uid, tid, CHAR, 'ru')) is False
    assert bot.sent == [] and len(_dialog(uid)) == 3    # сводка — про возврат, не про молчание


def test_the_digest_is_a_return_gate_not_a_slot():
    assert 'life_backlog.maybe_digest(bot, uid, tg_id, char_id' in LIFE
    call = LIFE.index('life_backlog.maybe_digest(bot, uid, tg_id, char_id')
    # он вернулся — её обычный пуш этого скана не нужен
    assert "if await life_backlog.maybe_digest" in LIFE
    assert LIFE.index('continue', call) - call < 120
    # сводка не ждёт, пока освободится слот части суток, и сама слот не берёт
    assert call < LIFE.index('if part in slots or len(slots) >= per_day:')
    assert call < LIFE.index("slots.append(part)")


def test_the_knobs():
    assert 'LIFE_EVENTS_UNANSWERED_MAX", "3"' in CFG
    assert 'LIFE_EVENTS_DIGEST_AFTER_HOURS", "72"' in CFG
    assert config.LIFE_EVENTS_UNANSWERED_MAX == 3
    assert config.LIFE_EVENTS_DIGEST_AFTER_HOURS == 72
    assert B.RETURN_WINDOW_HOURS == 24
    # сводка не зовёт провайдера: модуль живёт на её же строках
    src = (ROOT / 'services' / 'life_backlog.py').read_text(encoding='utf-8')
    for word in ('generate_text', 'llm_provider_service', 'build_life_moment', 'grant_photo_credits'):
        assert word not in src, word
