"""V3.157.0: owner ТЗ (Фогель, Модуль 6) — «Трофеи Страсти».

На её карточке живёт лента из шести фантазий, которые пара действительно
прожила: первое откровенное фото, сцена с перебивкой, прочитанный «Стертый
черновик», разговор после полуночи, седьмой уровень, финал её истории. Закрытый
слот — размытая плашка с 🔒 и подсказкой; открытый остаётся в профиле навсегда
и его можно переслушать: признание озвучивается ровно один раз, файл лежит
рядом со строкой трогфея. Шесть из шести отдают одно эксклюзивное фото альбома
— единственная бесплатная картинка модуля.

Тесты проверяют три вещи, на которых такой модуль ломается чаще всего: слот
открывается ТОЛЬКО по настоящему событию этой пары (не другой девушки и не по
чьим-то цифрам в памяти процесса), закрытый слот не выносит наружу ни одного
слова её будущего признания, и весь альбом стоит владельцу не больше одного
рендера и нуля персиков.
"""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from models.app_models import (Base, CharacterTrophy, Message, PrivateGallery, ProductEvent,
                               TrophyAlbum, User, UserGeneration)
from services import trophy_service as ts
from services.db import SessionLocal, engine

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')

CID = 'anna_01'
OTHER = 'alena_01'
_LEVELS = {}
_MARRIED = {}


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _uid_of(tid: int) -> int:
    with SessionLocal() as s:
        return int(s.scalar(_select_uid(tid)))


def _select_uid(tid: int):
    return select(User.id).where(User.telegram_id == str(tid))


def _pair(level: int = 6, tz: str = 'UTC', character_id: str = CID) -> tuple[int, int]:
    """A fresh (user, girl) pair: a relationship level and nothing lived yet."""
    Base.metadata.create_all(engine)
    stamp = _now().strftime('%H%M%S%f')
    tid = int(f'94{stamp}')
    with SessionLocal() as s:
        s.add(User(telegram_id=str(tid), name='t', timezone=tz, photo_credits=5000,
                   bonus_peaches=0))
        s.commit()
        uid = int(s.scalar(_select_uid(tid)))
        s.add(Message(user_id=uid, character_id=character_id, role='user',
                      content='привет', created_at=_now().replace(hour=15)))
        s.commit()
    _LEVELS[tid] = level
    return tid, uid


def _install_level_patch(monkeypatch):
    import services.photo_service as ps

    def fake(telegram_id, character_id=CID):
        # ступень близости считается на пару (он + она), поэтому у другой
        # девушки она начинается с нуля
        if str(character_id) != CID:
            return 0
        return int(_LEVELS.get(int(telegram_id), 0))

    monkeypatch.setattr(ps, 'get_relationship_level', fake)


def _install_marital_patch(monkeypatch):
    import services.photo_service as ps

    def fake(telegram_id, character_id):
        return _MARRIED.get((int(telegram_id), character_id), '')

    monkeypatch.setattr(ps, 'marital_status_for', fake)


def _setup(monkeypatch, **kw) -> tuple[int, int]:
    _install_level_patch(monkeypatch)
    _install_marital_patch(monkeypatch)
    return _pair(**kw)


def _unlocked(tid: int, cid: str = CID) -> list[str]:
    return [i['key'] for i in ts.board(tid, cid)['items'] if i['unlocked']]


def _draft(tid: int, cid: str = CID, unlocked: bool = True):
    with SessionLocal() as s:
        uid = _uid_of(tid)
        s.add(Message(user_id=uid, character_id=cid, role='assistant', content='ок',
                      draft_text='то, что я стёрла', draft_unlocked=unlocked))
        s.commit()


def _pick(tid: int, cid: str = CID):
    with SessionLocal() as s:
        s.add(ProductEvent(user_id=_uid_of(tid), event_name='interrupt_pick',
                           metadata_json=json.dumps({'event': 'e1', 'choice': 2,
                                                     'character_id': cid})))
        s.commit()


def _gallery(tid: int, cid: str = CID, category: str = 'nude_art'):
    with SessionLocal() as s:
        s.add(PrivateGallery(user_id=_uid_of(tid), character_id=cid, category=category,
                             type_id='bedroom', prompt_hash='x' * 12, image_bytes=b'aa'))
        s.commit()


def _at(tid: int, hour: int, cid: str = CID, role: str = 'user'):
    with SessionLocal() as s:
        s.add(Message(user_id=_uid_of(tid), character_id=cid, role=role, content='...',
                      created_at=_now().replace(hour=hour, minute=30)))
        s.commit()


class _FakeTTS:
    def __init__(self, data=b'OGGFAKE' * 8):
        self.data = data
        self.calls = []

    async def __call__(self, text, voice=None, character_id=None, mood=None):
        self.calls.append((text, character_id))
        return self.data


def _fake_tts(monkeypatch, data=b'OGGFAKE' * 8) -> _FakeTTS:
    import services.voice_service as vs
    fake = _FakeTTS(data)
    monkeypatch.setattr(vs, 'synthesize_bytes', fake)
    return fake


class _FakeRender:
    def __init__(self, data=b'\xff\xd8\xff\xe0' + b'j' * 60):
        self.data = data
        self.calls = []

    async def __call__(self, character_id, prompt):
        self.calls.append((character_id, prompt))
        return self.data


def _fake_render(monkeypatch, data=b'\xff\xd8\xff\xe0' + b'j' * 60) -> _FakeRender:
    import services.private_photo_service as pps
    fake = _FakeRender(data)
    monkeypatch.setattr(pps, 'generate_live_situation_photo', fake)
    return fake


def _open(tid, key, cid=CID, lang='ru'):
    return asyncio.run(ts.open_trophy(tid, cid, key, lang))


def _wallet(tid: int) -> int:
    from services.payments import get_paid_peaches
    return int(get_paid_peaches(tid) or 0)


# ── таблица: память пары, а не счётчик ──────────────────────────────────────

def test_the_trophy_tables_are_autocreated():
    assert 'character_trophies' in Base.metadata.tables
    assert 'trophy_album' in Base.metadata.tables
    cols = Base.metadata.tables['character_trophies'].columns.keys()
    assert {'user_id', 'character_id', 'key', 'unlocked_at', 'confession',
            'voice_url'} <= set(cols)
    assert 'photo_url' not in cols            # картинка живёт в trophy_album, не в слоте
    uniq = [sorted(c.name for c in uc.columns)
            for uc in Base.metadata.tables['character_trophies'].constraints
            if uc.__class__.__name__ == 'UniqueConstraint']
    assert ['character_id', 'key', 'user_id'] in uniq


def test_the_six_fantasies_of_the_owner_tz():
    assert [t.key for t in ts.TROPHIES] == ['first_photo', 'risk_scene', 'erased_draft',
                                            'night_talk', 'deep_seven', 'finale']
    assert ts.TOTAL == len(ts.TROPHIES) == 6


def test_every_slot_is_named_hinted_and_short_enough_to_be_spoken():
    banned = ('школ', 'школьн', 'несовершеннолет', 'student', 'school', 'teen')
    for t in ts.TROPHIES:
        assert t.key.isascii() and t.key.replace('_', '').isalpha(), t.key
        for field in ('title', 'hint', 'say'):
            ru, en = getattr(t, field + '_ru'), getattr(t, field + '_en')
            assert ru.strip() and en.strip(), (t.key, field)
            assert not any(b in ru.lower() or b in en.lower() for b in banned), t.key
        assert len(t.title_ru) <= 28 and len(t.hint_ru) <= 72, t.key
        # одно признание = одна короткая голосовая, а не монолог на минуту
        assert 40 <= len(t.say_ru) <= 220 and 40 <= len(t.say_en) <= 240, t.key
        assert t.emoji


# ── шесть условий ТЗ, каждое по настоящему событию ──────────────────────────

def test_a_pair_that_lived_nothing_sees_six_locked_slots(monkeypatch):
    tid, uid = _setup(monkeypatch, level=1)
    board = ts.board(tid, CID)
    assert board['unlocked'] == 0 and board['total'] == 6
    assert [i['unlocked'] for i in board['items']] == [False] * 6
    assert all(i['hint'] for i in board['items'])       # подсказка есть всегда


def test_the_first_frank_photo_of_this_girl_unlocks_the_first_slot(monkeypatch):
    tid, uid = _setup(monkeypatch)
    _gallery(tid, OTHER)
    assert 'first_photo' not in _unlocked(tid)
    _gallery(tid, CID)
    assert 'first_photo' in _unlocked(tid)


def test_a_frank_slot_also_accepts_a_paid_spicy_render(monkeypatch):
    tid, uid = _setup(monkeypatch)
    with SessionLocal() as s:
        s.add(UserGeneration(telegram_id=tid, kind='hot', character_id=CID, prompt='x'))
        s.commit()
    assert 'first_photo' in _unlocked(tid)


def test_an_ordinary_selfie_is_not_a_frank_photo(monkeypatch):
    tid, uid = _setup(monkeypatch)
    _gallery(tid, CID, category='portrait')
    with SessionLocal() as s:
        s.add(UserGeneration(telegram_id=tid, kind='photo', character_id=CID, prompt='x'))
        s.commit()
    assert 'first_photo' not in _unlocked(tid)


def test_a_resolved_qte_counts_only_for_the_girl_it_happened_with(monkeypatch):
    tid, uid = _setup(monkeypatch)
    _pick(tid, OTHER)
    assert 'risk_scene' not in _unlocked(tid)
    _pick(tid, CID)
    assert 'risk_scene' in _unlocked(tid)


def test_a_risky_scene_needs_his_answer_not_just_the_plate(monkeypatch):
    tid, uid = _setup(monkeypatch)
    with SessionLocal() as s:
        s.add(ProductEvent(user_id=_uid_of(tid), event_name='paywall_view',
                           metadata_json=json.dumps({'product': 'interrupt',
                                                     'character_id': CID})))
        s.commit()
    assert 'risk_scene' not in _unlocked(tid)


def test_one_erased_draft_read_unlocks_the_third_slot(monkeypatch):
    tid, uid = _setup(monkeypatch)
    _draft(tid, unlocked=False)
    assert 'erased_draft' not in _unlocked(tid)
    _draft(tid, unlocked=True)
    assert 'erased_draft' in _unlocked(tid)


def test_after_midnight_talk_needs_level_four_and_his_local_clock(monkeypatch):
    tid, uid = _setup(monkeypatch, level=3)
    _at(tid, 3)
    assert 'night_talk' not in _unlocked(tid)
    _LEVELS[tid] = 4
    assert 'night_talk' in _unlocked(tid)


def test_daylight_messages_never_count_as_a_night_talk(monkeypatch):
    tid, uid = _setup(monkeypatch, level=6)
    _at(tid, 13)
    _at(tid, 23)
    assert 'night_talk' not in _unlocked(tid)


def test_the_night_is_his_not_the_servers(monkeypatch):
    """21:00 UTC — это 00:30 в Токио (ночь) и 22:00 в Берлине (не ночь)."""
    base = datetime(2026, 11, 1, 21, 0, tzinfo=timezone.utc).replace(tzinfo=None)
    tids = {}
    for tz in ('Asia/Tokyo', 'Europe/Berlin'):
        tid, uid = _setup(monkeypatch, level=6, tz=tz)
        with SessionLocal() as s:
            s.add(Message(user_id=uid, character_id=CID, role='user', content='...',
                          created_at=base))
            s.commit()
        tids[tz] = tid
    assert 'night_talk' in _unlocked(tids['Asia/Tokyo'])
    assert 'night_talk' not in _unlocked(tids['Europe/Berlin'])


def test_a_broken_timezone_string_falls_back_instead_of_failing(monkeypatch):
    tid, uid = _setup(monkeypatch, level=6, tz='Mars/Olympus_Mons')
    _at(tid, 2)
    assert 'night_talk' in _unlocked(tid)


def test_the_seventh_level_is_the_fifth_slot(monkeypatch):
    tid, uid = _setup(monkeypatch, level=6)
    assert 'deep_seven' not in _unlocked(tid)
    _LEVELS[tid] = 7
    assert 'deep_seven' in _unlocked(tid)


def test_the_finale_needs_her_story_ended_with_him(monkeypatch):
    tid, uid = _setup(monkeypatch, level=8)
    assert 'finale' not in _unlocked(tid)
    _MARRIED[(tid, CID)] = 'mar_with_you'
    assert 'finale' in _unlocked(tid)
    tid2, uid2 = _setup(monkeypatch, level=8)
    _MARRIED[(tid2, CID)] = 'mar_wife'
    assert 'finale' in _unlocked(tid2)


def test_the_deep_end_of_the_scale_is_a_finale_too(monkeypatch):
    tid, uid = _setup(monkeypatch, level=9)
    assert 'finale' in _unlocked(tid)


def test_another_mans_husband_status_does_not_open_her_finale(monkeypatch):
    tid, uid = _setup(monkeypatch, level=6)
    _MARRIED[(tid, OTHER)] = 'mar_wife'
    assert 'finale' not in _unlocked(tid)


# ── лента помнит: момент назад не откатить ──────────────────────────────────

def test_a_trophy_stays_when_the_reason_for_it_is_gone(monkeypatch):
    tid, uid = _setup(monkeypatch, level=7)
    assert 'deep_seven' in _unlocked(tid)
    first = _row(tid, 'deep_seven').unlocked_at
    _LEVELS[tid] = 1
    assert 'deep_seven' in _unlocked(tid)
    assert _row(tid, 'deep_seven').unlocked_at == first


def _row(tid, key, cid=CID):
    uid = _uid_of(tid)
    with SessionLocal() as s:
        return s.scalar(select(CharacterTrophy).where(
            CharacterTrophy.user_id == uid, CharacterTrophy.character_id == cid,
            CharacterTrophy.key == key))


def test_recounting_the_board_never_duplicates_a_slot(monkeypatch):
    tid, uid = _setup(monkeypatch, level=10)
    _gallery(tid), _pick(tid), _draft(tid), _at(tid, 3)
    for _ in range(3):
        ts.evaluate(tid, CID)
    uid_ = _uid_of(tid)
    with SessionLocal() as s:
        rows = s.query(CharacterTrophy).filter(CharacterTrophy.user_id == uid_).all()
    assert len(rows) == len(set(r.key for r in rows)) == 6


def test_his_album_on_one_girl_is_invisible_on_another(monkeypatch):
    tid, uid = _setup(monkeypatch, level=9)
    _at(tid, 3)
    assert ts.board(tid, CID)['unlocked'] == 3
    assert ts.board(tid, OTHER)['unlocked'] == 0


def test_a_user_without_a_row_gets_nothing(monkeypatch):
    _install_level_patch(monkeypatch)
    assert ts.evaluate(949999999, CID) == []
    assert ts.board(949999999, CID)['items'] == []
    assert ts.summary_line(949999999, CID).endswith('0/6')


# ── закрытый слот молчит ────────────────────────────────────────────────────

def test_a_locked_slot_never_leaks_what_she_will_confess(monkeypatch):
    tid, uid = _setup(monkeypatch, level=1)
    blob = json.dumps(ts.board(tid, CID), ensure_ascii=False)
    for t in ts.TROPHIES:
        assert t.say_ru not in blob and t.say_en not in blob, t.key
        assert t.key in blob and t.title_ru in blob


def test_the_bot_card_only_counts_and_the_app_gets_the_titles(monkeypatch):
    tid, uid = _setup(monkeypatch, level=9)
    _at(tid, 3)
    assert ts.summary_line(tid, CID) == '🏆 Открытые фантазии: 3/6'
    assert ts.summary_line(tid, CID, 'en') == '🏆 Open fantasies: 3/6'
    en = ts.board(tid, CID, 'en')
    assert en['items'][4]['title'] == 'The seventh level'


# ── тап по слоту: один голос навсегда ───────────────────────────────────────

def test_a_locked_slot_refuses_him_and_wastes_no_voice(monkeypatch):
    tid, uid = _setup(monkeypatch, level=1)
    tts = _fake_tts(monkeypatch)
    res = _open(tid, 'deep_seven')
    assert res == {'ok': False, 'error': 'locked'}
    assert tts.calls == []


def test_an_unknown_key_is_a_bad_request(monkeypatch):
    tid, uid = _setup(monkeypatch, level=9)
    _fake_tts(monkeypatch)
    assert _open(tid, 'threesome') == {'ok': False, 'error': 'bad_request'}


def test_opening_a_slot_speaks_once_and_stays_replayable(monkeypatch):
    tid, uid = _setup(monkeypatch, level=7)
    tts = _fake_tts(monkeypatch)
    first = _open(tid, 'deep_seven')
    assert first['ok'] and first['voice_url'].startswith('/webapp/media/')
    assert first['text'] == ts.get('deep_seven').say_ru
    assert tts.calls and tts.calls[0][1] == CID
    row = _row(tid, 'deep_seven')
    assert row.voice_url == first['voice_url'] and row.confession == first['text']
    again = _open(tid, 'deep_seven')
    assert again['voice_url'] == first['voice_url'] and len(tts.calls) == 1
    board = ts.board(tid, CID)
    slot = [i for i in board['items'] if i['key'] == 'deep_seven'][0]
    assert slot['opened'] and slot['say'] == first['text']


def test_a_slot_can_be_heard_in_his_language_once(monkeypatch):
    tid, uid = _setup(monkeypatch, level=7)
    _fake_tts(monkeypatch)
    assert _open(tid, 'deep_seven', lang='en')['text'] == ts.get('deep_seven').say_en
    # второй раз — уже сохранённое признание, язык не переключает её голос
    assert _open(tid, 'deep_seven', lang='ru')['text'] == ts.get('deep_seven').say_en


def test_a_broken_tts_costs_nothing_and_the_tap_can_repeat(monkeypatch):
    tid, uid = _setup(monkeypatch, level=7)
    _fake_tts(monkeypatch, data=b'')
    assert _open(tid, 'deep_seven') == {'ok': False, 'error': 'voice_failed'}
    assert _row(tid, 'deep_seven').voice_url is None
    _fake_tts(monkeypatch)
    assert _open(tid, 'deep_seven')['ok']


def _lived_everything(tid):
    """All six ТЗ moments really happened between him and this girl."""
    _gallery(tid)
    _pick(tid)
    _draft(tid)
    _at(tid, 3)


def test_the_whole_album_costs_no_peaches(monkeypatch):
    tid, uid = _setup(monkeypatch, level=10)
    _lived_everything(tid)
    _fake_tts(monkeypatch)
    _fake_render(monkeypatch)
    before = _wallet(tid)
    for key in [t.key for t in ts.TROPHIES]:
        assert _open(tid, key)['ok'], key
    assert _wallet(tid) == before


def test_six_of_six_gives_exactly_one_exclusive_photo(monkeypatch):
    tid, uid = _setup(monkeypatch, level=10)
    _lived_everything(tid)
    _fake_tts(monkeypatch)
    render = _fake_render(monkeypatch)
    for key in [t.key for t in ts.TROPHIES]:
        assert _open(tid, key)['photo_url'] == ''   # слоты отдают только голос
    assert render.calls == []                       # до тапа по альбому — ни пикселя
    last = _open(tid, 'album')
    assert last['ok'] and last['photo_url'].startswith('/webapp/media/')
    assert len(render.calls) == 1
    cid, prompt = render.calls[0]
    assert cid == CID and 'slip dress' in prompt and 'six small printed photos' in prompt
    assert _open(tid, 'album')['photo_url'] == last['photo_url']
    assert len(render.calls) == 1                   # и навсегда один
    album = _album_row(tid)
    assert album.photo_url == last['photo_url']
    assert ts.board(tid, CID)['album']['photo_url'] == last['photo_url']
    assert ts.board(tid, CID)['album_ready']


def _album_row(tid, cid=CID):
    with SessionLocal() as s:
        return s.scalar(select(TrophyAlbum).where(
            TrophyAlbum.telegram_id == tid, TrophyAlbum.character_id == cid))


def test_a_failed_album_photo_is_not_forgotten_or_double_paid(monkeypatch):
    tid, uid = _setup(monkeypatch, level=10)
    _lived_everything(tid)
    _fake_tts(monkeypatch)
    _fake_render(monkeypatch, data=b'')
    res = _open(tid, 'album')
    assert res['ok'] is False and res['error'] == 'render_failed'
    assert _album_row(tid) is None or not _album_row(tid).photo_url
    render = _fake_render(monkeypatch)
    assert _open(tid, 'album')['photo_url'].startswith('/webapp/media/')
    assert len(render.calls) == 1


def test_five_of_six_is_not_an_album(monkeypatch):
    tid, uid = _setup(monkeypatch, level=7)
    _gallery(tid)
    _draft(tid)
    _at(tid, 3)
    _fake_tts(monkeypatch)
    render = _fake_render(monkeypatch)
    for key in ('first_photo', 'erased_draft', 'night_talk', 'deep_seven'):
        assert _open(tid, key)['ok']
    board = ts.board(tid, CID)
    assert board['unlocked'] == 4 and not board['album_ready']
    # четыре из шести: альбом вежливо отказывает и ничего не рисует
    assert _open(tid, 'album') == {'ok': False, 'error': 'locked'}
    assert render.calls == []
    assert [i for i in board['items'] if i['unlocked']] and \
        all(i['hint'] == '' for i in board['items'] if i['unlocked'])


def test_the_album_photo_is_logged_for_the_owner_feed(monkeypatch):
    tid, uid = _setup(monkeypatch, level=10)
    _lived_everything(tid)
    _fake_tts(monkeypatch)
    _fake_render(monkeypatch)
    for key in [t.key for t in ts.TROPHIES]:
        _open(tid, key)
    _open(tid, 'album')
    with SessionLocal() as s:
        rows = s.query(UserGeneration).filter(UserGeneration.telegram_id == tid,
                                              UserGeneration.kind == 'photo').all()
    assert any('slip dress' in (r.prompt or '') for r in rows)
    with SessionLocal() as s:
        events = [e.event_name for e in s.query(ProductEvent).filter(
            ProductEvent.user_id == _uid_of(tid)).all()]
    assert 'trophy_opened' in events and 'trophy_album_opened' in events


# ── выключатель модуля ──────────────────────────────────────────────────────

def test_the_owner_can_turn_the_album_off(monkeypatch):
    tid, uid = _setup(monkeypatch, level=10)
    monkeypatch.setattr(ts, 'enabled', lambda: False)
    assert ts.evaluate(tid, CID) == []
    assert ts.board(tid, CID)['enabled'] is False
    assert ts.summary_line(tid, CID) == ''
    assert _open(tid, 'deep_seven') == {'ok': False, 'error': 'bad_request'}


def test_the_switch_lives_in_the_env(monkeypatch):
    from config import TROPHIES_ENABLED
    assert TROPHIES_ENABLED is True


# ── проводка: бот, приложение, Mini App ─────────────────────────────────────

def _slice(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i)]


def _fn(text, name):
    """One top-level JS function, up to the next one at column zero."""
    i = text.index('function ' + name)
    return text[i:text.index('\nfunction ', i + 10)]


def test_the_app_reads_and_opens_the_album_by_init_data():
    read = _slice(MAIN, 'async def _webapp_api_trophies', 'async def _webapp_api_trophy_open')
    write = _slice(MAIN, 'async def _webapp_api_trophy_open', 'async def _webapp_api_chat_live')
    for block in (read, write):
        assert "validate_init_data(request.query.get('init_data', ''))" in block
        assert "'auth'" in block
    assert "trophy_service.board" in read and "'character_id'" in read
    assert 'open_trophy' in write
    assert "'/webapp/api/trophies', _webapp_api_trophies" in MAIN
    assert "'/webapp/api/trophies/open', _webapp_api_trophy_open" in MAIN


def test_the_bot_card_carries_only_the_counter():
    card = _slice(MAIN, 'def _character_card_text', 'def _character_fallback_photo')
    assert 'trophy_service.summary_line(viewer_id, card.character_id)' in card
    assert 'open_trophy' not in card           # в боте ничего не озвучивается
    assert 'synthesize_bytes' not in card


def test_the_mini_app_draws_the_blurred_row_and_replays_the_voice():
    assert 'function trophySlot' in SPA and 'function renderTrophies' in SPA
    assert 'data-trophy="' in SPA and 'async function openTrophy' in SPA
    assert '/webapp/api/trophies?init_data=' in SPA
    assert '/webapp/api/trophies/open?init_data=' in SPA
    assert 'loadTrophies(c.id);' in _fn(SPA, 'openCharPage')
    assert '.tro.lock .tro-pic { filter: blur' in SPA          # размытый закрытый слот
    assert 'trow' in SPA and "display: flex" in SPA
    assert 'voicePlayer(j.voice_url' in SPA                    # переслушать в профиле
    for key in ('tr_head', 'tr_open', 'tr_replay', 'tr_busy', 'tr_failed', 'tr_album'):
        assert SPA.count(key + ':') >= 2, key                  # en + ru


def test_the_fantasy_row_folds_behind_its_title_like_the_storyline_button():
    line = [l for l in SPA.splitlines() if 'id="charTrophies"' in l][0]
    assert 'foldable fold' in line                          # свёрнута по умолчанию
    # V3.165.0 (#105): та же строка, что у всех панелей — «метка · значение».
    assert 'class="pl" id="charTrophiesLbl"' in line and 'class="pv" id="charTrophiesVal"' in line
    assert '<div class="pbody">' in line and 'id="charTrophyRow"' in line
    assert '.charblock.fold .pbody { display: none; }' in SPA
    wiring = _slice(SPA, '// V3.131.0: tap the row title', 'const MARITAL_KEYS')
    assert '#charview .charblock.foldable > .foldhead' in wiring   # один тап на все строки
    assert "classList.toggle('fold')" in wiring


def test_the_slot_row_is_a_carousel_of_seven_cards():
    js = _slice(SPA, 'function renderTrophies(j)', 'async function fetchTrophies')
    assert "key: 'album'" in js and "j.album_ready" in js
    assert "(j.unlocked || 0) + '/' + (j.total || 6)" in js    # «Открытые фантазии (0/6)»
    # закрытый альбом остаётся подсказкой: тап по нему ничего не просит у сервера
    assert "key === 'album' && el.classList.contains('lock')" in _fn(SPA, 'openTrophy')


def test_the_service_never_buys_anything_and_never_rolls_the_paywall():
    src = (ROOT / 'services' / 'trophy_service.py').read_text(encoding='utf-8')
    for banned in ('spend_peaches', 'grant_photo_credits', "product': 'trophy"):
        assert banned not in src
    assert 'def open_trophy' in src and 'synthesize_bytes' in src
