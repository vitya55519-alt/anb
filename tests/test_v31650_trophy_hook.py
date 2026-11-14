"""V3.165.0 (#108, владелец): пустой слот «Трофеев Страсти» работает как зацепка.

Решение владельца прозвучало так: «оставить шесть моментов + зацепка». Значит
ничего уже заработанного не отнимается, новых трат не появляется и условия
открытия слотов остаются теми же шестью событиями. Поменялись ровно две вещи:
подсказка закрытого слота в ленте теперь называет конкретный кадр или шаг,
который его закроет (и тап по пустому слоту показывает именно её, а не
«не получилось»), и та же строка одним росчерком попадает в её промпт — раз в
несколько реплик она сама вспоминает то, чего между вами ещё не было.

Чего в зацепке сознательно нет: её будущих признаний (закрытый слот не знает
ни одного слова из них), цифр цены, персиков и Premium, и выдуманных моментов —
лента читает только то, что пара действительно прожила.
"""
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from models.app_models import Base, CharacterTrophy, PrivateGallery, TrophyAlbum, User
from services import trophy_service as ts
from services.db import SessionLocal, engine

os.environ.setdefault('TELEGRAM_TOKEN', '123456:fake-token')
os.environ.setdefault('OPENAI_API_KEY', 'fake')

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')

CID = 'anna_01'
OTHER = 'alena_01'
_LEVELS: dict[int, int] = {}

# Что, по ТЗ, закрывает каждый слот: две приметы по-русски и одна по-английски.
CLOSES = {
    'first_photo': ('наедине', 'сняться', 'private 18+'),
    'risk_scene': ('перебив', 'останься', 'interrupted'),
    'erased_draft': ('стёртое', 'прочитай', 'erased draft'),
    'night_talk': ('после 00:00', 'четвёрт', 'midnight'),
    'deep_seven': ('седьмая ступень', 'переписк', 'seventh'),
    'finale': ('финал', 'истори', 'ending'),
}


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _pair(level: int = 1) -> int:
    Base.metadata.create_all(engine)
    tid = 9_650_000_000 + uuid.uuid4().int % 999_999
    with SessionLocal() as s:
        s.add(User(telegram_id=str(tid), name='t', timezone='UTC'))
        s.commit()
    _LEVELS[tid] = level
    return tid


def _uid(tid: int) -> int:
    with SessionLocal() as s:
        return int(s.scalar(select(User.id).where(User.telegram_id == str(tid))))


def _photo(tid: int, cid: str = CID) -> None:
    with SessionLocal() as s:
        s.add(PrivateGallery(user_id=_uid(tid), character_id=cid, category='nude_art',
                             type_id='bedroom', prompt_hash='x' * 12, image_bytes=b'aa'))
        s.commit()


def _all_six(tid: int, cid: str = CID) -> None:
    with SessionLocal() as s:
        for t in ts.TROPHIES:
            s.add(CharacterTrophy(user_id=_uid(tid), character_id=cid, key=t.key,
                                  unlocked_at=_now()))
        s.commit()


def _album_photo(tid: int, cid: str = CID) -> None:
    with SessionLocal() as s:
        s.add(TrophyAlbum(telegram_id=int(tid), character_id=cid,
                          photo_url='/webapp/media/a.jpg', created_at=_now()))
        s.commit()


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    """Очередь зацепки живёт в памяти процесса, а ступень близости и её
    семейный статус берутся из подставных функций — как в наборе самих
    трофеев: тесты не наследуют состояние друг за другом."""
    ts._hook_fired.clear()
    import services.photo_service as ps

    def _level(telegram_id, character_id=CID):
        if str(character_id) != CID:
            return 0
        return int(_LEVELS.get(int(telegram_id), 0))

    monkeypatch.setattr(ps, 'get_relationship_level', _level)
    monkeypatch.setattr(ps, 'marital_status_for', lambda telegram_id, character_id: '')
    yield
    ts._hook_fired.clear()


# ── 1. лента: пустой слот сам говорит, чем его закрыть ──────────────────────

def test_a_locked_slot_names_the_frame_or_step_that_closes_it():
    for t in ts.TROPHIES:
        ru, en, want = t.hint_ru.lower(), t.hint_en.lower(), CLOSES[t.key]
        assert want[0] in ru and want[1] in ru, (t.key, ru)
        assert want[2] in en, (t.key, en)


def test_the_hints_stay_short_lines_and_carry_no_money():
    for t in ts.TROPHIES:
        assert len(t.hint_ru) <= 72 and len(t.hint_en) <= 78, t.key
        for banned in ('🍑', 'персик', 'premium', '300', '2 000', '⭐'):
            assert banned not in t.hint_ru.lower(), (t.key, banned)
        # закрытый слот не знает ни слова из её будущего признания
        assert t.say_ru[:24] not in t.hint_ru, t.key


def test_a_fresh_pair_still_sees_six_hints_not_six_errors():
    tid = _pair(level=1)
    board = ts.board(tid, CID)
    assert board['unlocked'] == 0
    assert [i['unlocked'] for i in board['items']] == [False] * 6
    assert all(i['hint'] for i in board['items'])
    assert 'Наедине' in board['items'][0]['hint']


def test_an_open_slot_loses_nothing_and_the_other_five_stay_hinted():
    tid = _pair(level=1)
    _photo(tid)
    board = ts.board(tid, CID)
    opened = [i for i in board['items'] if i['unlocked']]
    assert [i['key'] for i in opened] == ['first_photo']
    assert opened[0]['hint'] == ''
    assert len([i for i in board['items'] if not i['unlocked']]) == 5


# ── 2. промпт: она сама вспоминает незаполненный слот ──────────────────────

def test_the_hook_names_the_first_empty_slot_in_his_language():
    tid = _pair(level=1)
    line = ts.dialog_hook(tid, CID, 'ru', turns=5)
    assert 'ТРОФЕИ СТРАСТИ' in line and '0/6' in line
    assert ts.TROPHIES[0].title_ru in line and 'Наедине' in line
    assert ts.TROPHIES[1].title_ru not in line


def test_the_hook_walks_down_the_feed_as_slots_open():
    tid = _pair(level=1)
    _photo(tid)
    line = ts.dialog_hook(tid, CID, 'ru', turns=9)
    assert '1/6' in line and ts.TROPHIES[1].title_ru in line
    assert ts.TROPHIES[0].title_ru not in line


def test_the_english_line_carries_the_english_slot():
    tid = _pair(level=1)
    line = ts.dialog_hook(tid, CID, 'en', turns=4)
    assert 'TROPHIES OF PASSION' in line
    assert ts.TROPHIES[0].title_en in line and 'Private 18+' in line


def test_the_hook_never_borrows_a_confession_or_a_price():
    tid = _pair(level=6)
    line = ts.dialog_hook(tid, CID, 'ru', turns=20)
    assert line
    for t in ts.TROPHIES:
        assert t.say_ru not in line and t.say_en not in line
    for banned in ('🍑', '300', '⭐', 'купить'):
        assert banned not in line, banned


def test_the_album_is_the_last_hook_and_then_silence():
    tid = _pair(level=1)
    _all_six(tid)
    line = ts.dialog_hook(tid, CID, 'ru', turns=12)
    assert 'альбом' in line.lower()
    _album_photo(tid)
    ts._hook_fired.clear()
    assert ts.dialog_hook(tid, CID, 'ru', turns=13) == ''


def test_the_first_two_replies_never_hear_it():
    tid = _pair(level=1)
    assert ts.dialog_hook(tid, CID, 'ru', turns=0) == ''
    assert ts.dialog_hook(tid, CID, 'ru', turns=2) == ''
    assert ts.HOOK_MIN_TURNS == 3
    # гейт отработал ДО того, как лента вообще пересчитывалась
    assert ts._hook_fired == {}


def test_one_pair_hears_it_once_every_six_hours():
    tid = _pair(level=1)
    assert ts.dialog_hook(tid, CID, 'ru', turns=8)
    assert ts.dialog_hook(tid, CID, 'ru', turns=9) == ''
    assert ts.HOOK_COOLDOWN_SECONDS == 6 * 3600
    # вторая героиня — своя очередь: у неё она только начинает
    assert ts.dialog_hook(tid, OTHER, 'ru', turns=8)
    ts._hook_fired[(tid, OTHER)] -= ts.HOOK_COOLDOWN_SECONDS + 1
    assert ts.dialog_hook(tid, OTHER, 'ru', turns=9)


def test_a_turned_off_album_says_nothing(monkeypatch):
    tid = _pair(level=1)
    monkeypatch.setattr(ts, 'enabled', lambda: False)
    assert ts.dialog_hook(tid, CID, 'ru', turns=9) == ''


# ── 3. проводка: промпт, озвучка, приложение ───────────────────────────────

def test_the_hook_reaches_only_her_system_prompt_in_live_replies():
    reply = CHAT[CHAT.index('async def reply('):CHAT.index('async def proactive_reply(')]
    assert 'trophy_service.dialog_hook' in reply
    assert "turns=sum(1 for m in history if m.role == 'user')" in reply
    assert "explicit_line = (explicit_line + '\\n' if explicit_line else '') + _trophy_hook" in reply
    # без подтверждённых 18+ строки в промпте нет
    gate = reply[:reply.index('from services import trophy_service')]
    assert '_adult_ok(user_id)' in gate[gate.rindex('if mode_on'):]
    # пуши, направленные сцены и утренние звонки её не получают
    assert CHAT.count('trophy_service.dialog_hook') == 1


def test_the_service_block_never_reaches_the_voice():
    tts = MAIN[MAIN.index('def _tts_text'):MAIN.index('async def _webapp_reply_voice_url')]
    assert 'trophy' not in tts.lower()
    # и в озвучку самого трофея идёт только её признание
    src = (ROOT / 'services' / 'trophy_service.py').read_text(encoding='utf-8')
    leg = src[src.index('audio = await synthesize_bytes(text'):]
    assert 'HOOK_LINE' not in leg and 'dialog_hook' not in leg


def test_the_app_reads_the_slot_hint_instead_of_an_error():
    slot = SPA[SPA.index('function trophySlot(it)'):SPA.index('function renderTrophies')]
    assert 'data-hint="' in slot
    fn = SPA[SPA.index('async function openTrophy'):SPA.index('function openCharPage')]
    lock = fn.index("if (el.classList.contains('lock')) {")
    assert 'el.dataset.hint' in fn[lock:lock + 400]
    # тап по пустому слоту ничего не просит у сервера — подсказка уже в ленте
    assert lock < fn.index('/webapp/api/trophies/open')
