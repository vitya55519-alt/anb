"""V3.150.0 — owner: «дай мне возможность выбирать фото под голосовое».

1. Под превью ритуала растёт вторая кнопка «🖼 Фото под голосовое».
2. Карусель листает ЕЁ готовые кадры (генерации + его пул), брак и нагота в
   список не попадают, а выбранный кадр закрепляется за утром/вечером этого дня.
3. Закреплённый кадр важнее авто-подбора, а сам выбор сбрасывает бандл, который
   превью уже построил, — «✅ Отправить всем» уносит именно то, что он выбрал.
4. «🔄 Авто-подбор» и следующие сутки возвращают ротацию.
"""
import asyncio
import datetime as dt
from types import SimpleNamespace

import pytest

from services import evening_voice as ev
from services import scheduler_service as ss

ROOT = __import__('pathlib').Path(__file__).resolve().parents[1]
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')

CHAR = 'ph_choice_01'
DAY = '2026-11-12'
ADMIN_ID = 915000001


def _session():
    from services.db import SessionLocal, init_db
    init_db()
    return SessionLocal()


def _purge():
    from sqlalchemy import delete, select
    from models.app_models import ChatMedia, ProactivePhoto, ProductEvent, UserGeneration
    from services.db import SessionLocal
    with SessionLocal() as s:
        ids = [r.id for r in s.execute(select(UserGeneration.id).where(
            UserGeneration.character_id == CHAR)).all()]
        s.execute(delete(ProductEvent).where(ProductEvent.character_id == CHAR))
        s.execute(delete(ProactivePhoto).where(ProactivePhoto.character_id == CHAR))
        names = [r[0] for r in s.execute(select(UserGeneration.filename).where(
            UserGeneration.id.in_(ids))).all() if r[0]]
        if names:
            s.execute(delete(ChatMedia).where(ChatMedia.filename.in_(names)))
        s.commit()


@pytest.fixture(autouse=True)
def clean_db():
    _purge()
    _drop_bundles()
    yield
    _purge()
    _drop_bundles()


def _drop_bundles():
    # today's preview bundle is a cache of the pick — never let one test's
    # cached frame decide the next test's answer.
    for store in (ss._shared_bundles, ss._shared_locks):
        for k in [k for k in store if k[2] == CHAR]:
            store.pop(k, None)


def _add_pool(data: bytes = b'pool-photo', kind: str = 'photo', character_id: str = CHAR) -> int:
    from models.app_models import ProactivePhoto
    from services.db import SessionLocal
    with SessionLocal() as s:
        row = ProactivePhoto(image_bytes=data, content_type='image/jpeg', kind=kind,
                             character_id=character_id)
        s.add(row)
        s.commit()
        return row.id


def _add_generation(filename: str, data: bytes, prompt: str = 'street') -> int:
    from models.app_models import ChatMedia, UserGeneration
    from services.db import SessionLocal
    with SessionLocal() as s:
        row = UserGeneration(telegram_id=1, kind='photo', character_id=CHAR,
                             prompt=prompt, filename=filename)
        s.add(row)
        s.commit()
        s.add(ChatMedia(telegram_id='1', filename=filename, content_type='image/jpeg', data=data))
        s.commit()
        return row.id


# ── 1. the choice itself ───────────────────────────────────────────────────
def test_a_pinned_frame_survives_and_can_be_released():
    ev.set_choice('evening', DAY, CHAR, 'gen', 7)
    assert ev.get_choice('evening', DAY, CHAR) == {'kind': 'evening', 'day': DAY, 'source': 'gen', 'ref': 7}
    assert ev.get_choice('morning', DAY, CHAR) is None, 'утренний выбор не течёт в вечерний'
    assert ev.get_choice('evening', '2026-11-13', CHAR) is None, 'выбор живёт один день'
    ev.set_choice('evening', DAY, CHAR, None, None)
    assert ev.get_choice('evening', DAY, CHAR) is None, '«🔄 Авто-подбор» вернул ротацию'


def test_the_newest_pin_wins():
    ev.set_choice('evening', DAY, CHAR, 'gen', 1)
    ev.set_choice('evening', DAY, CHAR, 'pool', 2)
    assert ev.get_choice('evening', DAY, CHAR)['ref'] == 2


def test_chosen_photo_hands_over_the_bytes():
    pid = _add_pool(b'pinned-by-owner')
    ev.set_choice('evening', DAY, CHAR, 'pool', pid)
    assert asyncio.run(ev.chosen_photo('evening', DAY, CHAR)) == (b'pinned-by-owner', 'image/jpeg', 'photo')
    assert asyncio.run(ev.chosen_photo('evening', DAY, 'other_char')) is None


def test_a_dead_frame_falls_back_to_the_rotation():
    ev.set_choice('evening', DAY, CHAR, 'pool', 999999)
    assert asyncio.run(ev.chosen_photo('evening', DAY, CHAR)) is None


# ── 2. what the carousel may offer ─────────────────────────────────────────
def test_the_carousel_never_offers_brak_or_nudity(monkeypatch):
    monkeypatch.setattr(ev, '_candidates', lambda c, u: [
        (1, 'a.jpg', {'rejected': True}),
        (2, 'b.jpg', {'defect': True, 'nudity': 'none'}),
        (3, 'c.jpg', {'defect': False, 'nudity': 'nude'}),
        (4, 'd.jpg', {'defect': False, 'nudity': 'lingerie'}),
        (5, 'e.jpg', {'defect': False, 'nudity': 'none'}),
        (6, 'f.jpg', None),
    ])
    monkeypatch.setattr(ev, '_pool_candidates', lambda c: [])
    got = ev.owner_candidates(CHAR)
    # ритуал уходит и бесплатным, и несовершеннолетним → только чистый кадр
    assert [g['ref'] for g in got] == [5, 6]
    assert got[0]['checked'] and not got[1]['checked'], 'кадр без vision-проверки помечен'


def test_the_pool_part_is_hers_and_photos_only():
    mine = _add_pool(b'mine')
    _add_pool(b'gif', kind='gif')
    _add_pool(b'other girl', character_id='other_char_01')
    _add_pool(b'untagged', character_id=None)
    refs = [c['ref'] for c in ev._pool_candidates(CHAR)]
    assert refs == [mine]


def test_candidate_media_reads_both_sources():
    gid = _add_generation('ph_choice_a.jpg', b'from-generation')
    pid = _add_pool(b'from-pool')
    assert ev.candidate_media('gen', gid)[:2] == (b'from-generation', 'image/jpeg')
    assert ev.candidate_media('pool', pid)[0] == b'from-pool'
    assert ev.candidate_media('gen', 999999) is None
    assert ev.candidate_media('pool', 999999) is None


def test_a_generation_without_a_file_is_not_offered():
    from models.app_models import UserGeneration
    from services.db import SessionLocal
    with SessionLocal() as s:
        row = UserGeneration(telegram_id=1, kind='photo', character_id=CHAR,
                             prompt='street', filename=None)
        s.add(row)
        s.commit()
        gid = row.id
    assert ev.candidate_media('gen', gid) is None


# ── 3. the ritual obeys him ────────────────────────────────────────────────
def test_the_pinned_frame_beats_the_auto_pick(monkeypatch):
    from services import retention_features_service as rfs
    from services import scheduler_service as ss
    pid = _add_pool(b'the one he chose')
    ev.set_choice('evening', DAY, CHAR, 'pool', pid)

    async def _no_voice(*a, **k):
        return None

    async def _never_auto(*a, **k):
        raise AssertionError('авто-подбор не запускается, когда владелец уже выбрал')

    monkeypatch.setattr(ev, 'voice_bytes', _no_voice)
    monkeypatch.setattr(ev, 'evening_photo', _never_auto)
    monkeypatch.setattr(rfs, 'get_retention_text', lambda kind, char: 'вечер 🌙')
    ss.invalidate_ritual_bundles('evening', DAY, CHAR)
    text, voice, shot = asyncio.run(ss._shared_ritual('evening', DAY, CHAR, 'ru'))
    assert text == 'вечер 🌙' and voice is None
    assert shot == (b'the one he chose', 'image/jpeg', 'photo')


def test_the_preview_bundle_is_dropped_when_he_repins(monkeypatch):
    from services import scheduler_service as ss
    ss._shared_bundles[('evening', DAY, CHAR, 'ru')] = ('old', None, b'old-photo')
    ss._shared_bundles[('evening', DAY, CHAR, 'en')] = ('old', None, b'old-photo')
    ss._shared_bundles[('evening', DAY, 'other_char_01', 'ru')] = ('keep', None, None)
    ss.invalidate_ritual_bundles('evening', DAY, CHAR)
    assert ('evening', DAY, CHAR, 'ru') not in ss._shared_bundles, 'en/ru бандлы этой девушки сброшены'
    assert ('evening', DAY, CHAR, 'en') not in ss._shared_bundles
    assert ('evening', DAY, 'other_char_01', 'ru') in ss._shared_bundles, 'чужой бандл не тронут'
    ss._shared_bundles.pop(('evening', DAY, 'other_char_01', 'ru'), None)


def test_the_auto_pick_still_runs_without_a_pin(monkeypatch):
    from services import scheduler_service as ss

    async def _no_voice(*a, **k):
        return None

    async def _auto(*a, **k):
        return b'auto', 'image/jpeg', 'photo'

    monkeypatch.setattr(ev, 'voice_bytes', _no_voice)
    monkeypatch.setattr(ev, 'evening_photo', _auto)
    monkeypatch.setattr(ss.retention_features_service, 'get_retention_text', lambda kind, char: 'текст')
    ss.invalidate_ritual_bundles('evening', DAY, CHAR)
    _text, _voice, shot = asyncio.run(ss._shared_ritual('evening', DAY, CHAR, 'ru'))
    assert shot == (b'auto', 'image/jpeg', 'photo')
    ss.invalidate_ritual_bundles('evening', DAY, CHAR)


# ── 4. the buttons ─────────────────────────────────────────────────────────
def test_the_preview_asks_him_about_the_photo():
    preview = SCHED[SCHED.index('async def _ritual_preview('):SCHED.index('# V3.113.0')]
    assert "callback_data=f'ritual_ok:{kind}:{day}'" in preview
    assert "callback_data=f'ritual_ph:open:{kind}'" in preview
    assert 'Фото под голосовое' in preview


def test_the_pool_screen_opens_the_same_picker():
    screen = MAIN[MAIN.index('def admin_prophoto_keyboard('):MAIN.index('def _prophoto_choose_keyboard(')]
    assert "callback_data='ritual_ph:open:morning'" in screen
    assert "callback_data='ritual_ph:open:evening'" in screen


def test_every_picker_callback_stays_admin_only():
    body = MAIN[MAIN.index('RITUAL_PH_WAIT: dict[int, dict] = {}'):
               MAIN.index('# V3.108.1: owner — «2 записи и всё»')]
    handlers = body.count('@dp.callback_query(F.data')
    assert handlers == 6, 'открыть, девушки, выбор девушки, листать, закрепить, авто'
    assert body.count('if cq.from_user.id not in ADMIN_TELEGRAM_IDS:') == handlers
    # «✅ Это фото» writes the pin and drops the cached bundle
    set_handler = body[body.index("F.data == 'ritual_ph:set'"):]
    assert '_ev.set_choice' in set_handler
    assert 'invalidate_ritual_bundles' in set_handler
    assert '_ev.candidate_media' in body, 'листание не генерит новый кадр'
    assert 'ev.evening_photo' not in body and '_ev.voice_bytes' not in body, 'выбор фото = $0 генераций'


def test_callbacks_fit_telegrams_64_byte_limit():
    for sample in ('ritual_ph:open:evening', 'ritual_ph:set', 'ritual_ph:auto',
                   'ritual_ph:next', 'ritual_ph:char'):
        assert len(sample.encode()) <= 64
    # character_id is String(64); a callback carries it after «ritual_ph:char:»
    ids = [c for c in _character_ids() if c]
    assert all(len(f'ritual_ph:char:{c}'.encode()) <= 64 for c in ids), ids


def _character_ids():
    try:
        from services.character_card_service import list_cards
        return [c.character_id for c in list_cards(visible_only=False)]
    except Exception:
        return []


# ── 5. the picker walks the carousel and pins ──────────────────────────────
class _Msg:
    def __init__(self):
        self.edited = []
        self.answers = []

    async def edit_media(self, media, reply_markup=None):
        self.edited.append((media, reply_markup))

    async def answer(self, text, reply_markup=None):
        self.answers.append((text, reply_markup))


class _CQ:
    def __init__(self, data: str, admin_id: int = ADMIN_ID):
        self.data = data
        self.from_user = SimpleNamespace(id=admin_id, first_name='Owner')
        self.message = _Msg()
        self.answers = []

    async def answer(self, *a, **k):
        self.answers.append((a, k))


@pytest.fixture
def picker(monkeypatch):
    import main
    monkeypatch.setattr(main, 'ADMIN_TELEGRAM_IDS', {ADMIN_ID})
    monkeypatch.setattr(main, 'CHARACTER_ID', CHAR)
    monkeypatch.setattr(ev, '_candidates', lambda c, u: [])
    main.RITUAL_PH_WAIT.pop(ADMIN_ID, None)
    return main


def test_the_carousel_walks_her_frames(picker):
    main = picker
    a = _add_pool(b'first')
    b = _add_pool(b'second')
    cq = _CQ('ritual_ph:open:evening')
    main.RITUAL_PH_WAIT[cq.from_user.id] = {'kind': 'evening', 'character_id': CHAR, 'idx': 0}
    asyncio.run(main._ritual_ph_show(cq, {'kind': 'evening', 'character_id': CHAR, 'idx': 0}))
    cands = ev.owner_candidates(CHAR)
    assert [c['ref'] for c in cands] == [b, a], 'в карусель попадают оба её кадра'
    caption = cq.message.edited[0][0].caption
    assert f'1/{len(cands)}' in caption
    assert 'авто-подбор' in caption
    rows = cq.message.edited[0][1].inline_keyboard
    assert [btn.text for btn in rows[0]] == ['◀️', '✅ Это фото', '▶️']
    assert [btn.text for btn in rows[1]] == ['🔄 Авто-подбор', '👩 Другая героиня']
    # ▶️ walks to the other frame instead of generating a new one ($0 генераций)
    nxt = _CQ('ritual_ph:next')
    asyncio.run(main.ritual_ph_move(nxt))
    assert '2/%s' % len(cands) in nxt.message.edited[0][0].caption
    assert main.RITUAL_PH_WAIT[ADMIN_ID]['idx'] == 1
    wrap = _CQ('ritual_ph:next')
    asyncio.run(main.ritual_ph_move(wrap))
    assert '1/%s' % len(cands) in wrap.message.edited[0][0].caption, 'карусель замыкается'


def test_pinning_writes_the_choice_and_says_so(picker):
    main = picker
    pid = _add_pool(b'chosen')
    cq = _CQ('ritual_ph:set')
    main.RITUAL_PH_WAIT[cq.from_user.id] = {'kind': 'evening', 'character_id': CHAR, 'idx': 0}
    asyncio.run(main.ritual_ph_set(cq))
    today = ss.ritual_day()
    assert ev.get_choice('evening', today, CHAR) == {
        'kind': 'evening', 'day': today, 'source': 'pool', 'ref': pid}
    note = cq.message.edited[0][0].caption
    assert 'закреплен кадр #%s' % pid in note
    assert '✅ Отправить всем' in cq.message.edited[0][0].caption


def test_the_release_button_gives_the_rotation_back(picker):
    main = picker
    pid = _add_pool(b'chosen')
    cq = _CQ('ritual_ph:set')
    main.RITUAL_PH_WAIT[cq.from_user.id] = {'kind': 'evening', 'character_id': CHAR, 'idx': 0}
    asyncio.run(main.ritual_ph_set(cq))
    auto = _CQ('ritual_ph:auto')
    asyncio.run(main.ritual_ph_auto(auto))
    assert ev.get_choice('evening', ss.ritual_day(), CHAR) is None
    assert 'Авто-подбор' in auto.message.edited[0][0].caption


def test_a_stranger_cannot_pin_the_owners_photo(picker):
    main = picker
    _add_pool(b'chosen')
    cq = _CQ('ritual_ph:set', admin_id=915000002)
    main.RITUAL_PH_WAIT[cq.from_user.id] = {'kind': 'evening', 'character_id': CHAR, 'idx': 0}
    asyncio.run(main.ritual_ph_set(cq))
    assert ev.get_choice('evening', ss.ritual_day(), CHAR) is None
    assert cq.message.edited == [] and cq.message.answers == []


def test_the_picker_survives_a_lost_session(picker):
    main = picker
    cq = _CQ('ritual_ph:next')
    main.RITUAL_PH_WAIT.pop(cq.from_user.id, None)
    asyncio.run(main.ritual_ph_move(cq))
    assert cq.answers[0][1].get('show_alert')
    assert cq.message.edited == []
