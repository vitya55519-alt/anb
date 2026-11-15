"""V3.166.4 (Блоки 1–4): «механика тизера» — кэш стартовых кадров.

Открытие чата = её строка + чипы, картинки нет. Тап по чипу в режиме
«Без цензуры 18+» берёт кадр из starter_photo_cache (или дорисовывает один по
скрытому английскому промпту сценария и оставляет его следующим). Ему это стоит
нуля персиков и не трогает дневное бесплатное фото; ход при этом сгорает из 30
сообщений на аккаунт.
"""
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from models.app_models import Base, CharacterGreeting, DialogSession, StarterPhotoCache
from services import greeting_service, starter_photo_service
from services.db import SessionLocal, engine

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
SYNC_STORE_KEY = 'greeting_seed_v31664'


def _wipe():
    Base.metadata.create_all(engine)
    for cls in (CharacterGreeting, StarterPhotoCache):
        with SessionLocal() as s:
            s.execute(delete(cls))
            s.commit()
    with SessionLocal() as s:
        s.execute(delete(DialogSession).where(DialogSession.session_key == SYNC_STORE_KEY))
        s.commit()
    greeting_service._sync_done = None
    greeting_service._offers.clear()


@pytest.fixture(autouse=True)
def clean_tables():
    _wipe()
    yield
    _wipe()


def _scenario(character_id: str = 'all', prompt: str = 'bedroom, lace lingerie') -> int:
    return greeting_service.create(character_id, 'spicy', 'Показать тебе, как я выгляжу?',
                                   ['Покажи', 'Скинь фото'], image_prompt=prompt)


# ── Блок 1: таблица и потолок в четыре кадра ────────────────────────────────

def test_schema_has_the_hidden_prompt_and_the_cache_table():
    assert 'image_prompt: Mapped[str]' in MODELS
    assert '__tablename__ = "starter_photo_cache"' in MODELS
    with SessionLocal() as s:
        cols = {c.name for c in StarterPhotoCache.__table__.columns}
    assert {'id', 'character_id', 'greeting_id', 'file_id', 'photo_bytes', 'created_at'} <= cols


def test_cache_holds_exactly_four_frames_per_girl_and_scenario():
    gid = _scenario()
    ids = [starter_photo_service.save('anna_01', gid, f'jpeg-{i}'.encode()) for i in range(4)]
    assert all(ids) and len(set(ids)) == 4
    assert starter_photo_service.save('anna_01', gid, b'fifth') is None
    assert starter_photo_service.count('anna_01', gid) == 4
    assert starter_photo_service.is_full('anna_01', gid)
    # the cap is per pair: another girl and another scenario each get their four
    other_gid = _scenario()
    assert starter_photo_service.save('maria_01', gid, b'other-girl')
    assert starter_photo_service.save('anna_01', other_gid, b'other-scenario')
    assert starter_photo_service.counts_for('anna_01') == {gid: 4, other_gid: 1}


def test_deleting_one_frame_leaves_three_and_the_next_tap_refills_it():
    gid = _scenario()
    ids = [starter_photo_service.save('anna_01', gid, f'jpeg-{i}'.encode()) for i in range(4)]
    assert starter_photo_service.delete(ids[0]) is True
    assert starter_photo_service.count('anna_01', gid) == 3
    assert not starter_photo_service.is_full('anna_01', gid)
    assert starter_photo_service.delete(ids[0]) is False
    assert starter_photo_service.save('anna_01', gid, b'refill')


def test_pick_returns_a_cached_frame_with_bytes():
    gid = _scenario()
    ids = [starter_photo_service.save('anna_01', gid, f'jpeg-{i}'.encode()) for i in range(3)]
    picked = starter_photo_service.pick('anna_01', gid)
    assert picked in ids
    assert starter_photo_service.body_for(picked) == f'jpeg-{ids.index(picked)}'.encode()
    # a scenario nobody has drawn for is empty: the caller renders
    assert starter_photo_service.pick('anna_01', _scenario()) is None
    assert starter_photo_service.body_for(0) is None


def test_pick_skips_a_frame_without_bytes():
    gid = _scenario()
    with SessionLocal() as s:
        s.add(StarterPhotoCache(character_id='anna_01', greeting_id=gid, photo_bytes=None))
        s.commit()
    assert starter_photo_service.pick('anna_01', gid) is None


# ── Блок 2: тап по чипу узнаётся по кнопкам этой же карточки ────────────────

def test_chip_tap_matches_the_button_they_actually_sent():
    gid = _scenario()
    greeting_service.remember_offer(111, 'anna_01', gid, ['Покажи', 'Скинь фото'])
    assert greeting_service.take_offer(111, 'anna_01', 'Покажи') == {
        'greeting_id': gid, 'image_prompt': 'bedroom, lace lingerie'}
    assert greeting_service.take_offer(111, 'anna_01', '  покажи ')  # регистр и пробелы — те же слова
    assert greeting_service.take_offer(111, 'anna_01', 'Привет, как ты?') is None
    assert greeting_service.take_offer(222, 'anna_01', 'Покажи') is None      # другой аккаунт
    assert greeting_service.take_offer(111, 'maria_01', 'Покажи') is None     # другая девушка


def test_offer_expires_and_a_card_without_a_prompt_never_offers_a_frame():
    gid = _scenario()
    greeting_service.remember_offer(111, 'anna_01', gid, ['Покажи', 'Скинь фото'])
    greeting_service._OFFER_TTL = -1.0
    try:
        assert greeting_service.take_offer(111, 'anna_01', 'Покажи') is None
    finally:
        greeting_service._OFFER_TTL = 1800.0
    plain = _scenario(prompt='')
    greeting_service.remember_offer(111, 'anna_01', plain, ['Покажи'])
    assert greeting_service.take_offer(111, 'anna_01', 'Покажи') is None


def test_hidden_prompt_never_leaves_the_server():
    gid = _scenario()
    assert 'bedroom' not in str(greeting_service.list_for('all'))
    assert 'bedroom' not in str(greeting_service.scenarios_for('anna_01'))
    assert greeting_service.image_prompt_for(gid) == 'bedroom, lace lingerie'
    assert greeting_service.image_prompt_for(0) == ''


def test_scenarios_screen_lists_her_own_and_universal_cards_with_frames():
    mine = _scenario('anna_01')
    shared = _scenario('all')
    _scenario('anna_01', prompt='')  # без кадра — на экране не нужен
    seen = {sc['id'] for sc in greeting_service.scenarios_for('anna_01')}
    assert seen == {mine, shared}


# ── Блок 4: принудительная замена набора и снос фото с карточек ─────────────

def test_sync_forcibly_replaces_universal_rows_and_strips_card_photos():
    with SessionLocal() as s:
        s.add(CharacterGreeting(character_id='all', mode='spicy', message_text='старый универсальный хук',
                                buttons_json='["Начать массаж"]', photo_file_id='f', photo_bytes=b'old'))
        s.add(CharacterGreeting(character_id='anna_01', mode='spicy', message_text='моя личная карточка',
                                buttons_json='[]', photo_file_id='keep-me', photo_bytes=b'mine'))
        s.commit()
    res = greeting_service.sync_universal_seed()
    # the old universal card left with its picture; the owner's own row stays,
    # only stripped of the photo the new mechanic no longer serves
    assert res['replaced'] == 1 and res['added'] == 15 and res['photos_stripped'] == 1
    with SessionLocal() as s:
        rows = list(s.scalars(select(CharacterGreeting)))
    assert len([r for r in rows if r.character_id == 'all']) == 15
    assert not any('старый универсальный' in r.message_text for r in rows)
    personal = next(r for r in rows if r.character_id == 'anna_01')
    assert personal.message_text == 'моя личная карточка'      # его строки живы
    assert personal.photo_bytes is None and personal.photo_file_id is None  # фото снесены
    assert all(r.image_prompt for r in rows if r.character_id == 'all')
    assert greeting_service.sync_universal_seed() == {'replaced': 0, 'added': 0, 'photos_stripped': 0}


# ── статика: промпт, маршрут, кухня, экономия ───────────────────────────────

def test_starter_scene_outranks_the_generic_wardrobe_line():
    import services.photo_service as ps
    note = 'kitchen background, wearing only a cooking apron, leaning on counter'
    with_note = ps._build_prompt(ps.PhotoRequest(scene='lingerie', starter_note=note), 0,
                                 seedream=True, relationship_level=2, character_id='anna_01')
    without = ps._build_prompt(ps.PhotoRequest(scene='lingerie'), 0,
                               seedream=True, relationship_level=2, character_id='anna_01')
    assert f'STARTER SCENE: {note}' in with_note
    assert 'STARTER SCENE' not in without


def test_starter_turn_is_free_but_still_burns_one_of_thirty():
    branch = MAIN[MAIN.index('async def _starter_frame_turn'):MAIN.index('def _pings_app_reply(turn):')]
    assert 'greeting_service.take_offer' in branch
    assert 'starter_photo_service.pick' in branch          # сначала кэш, потом генератор
    assert "PhotoRequest(scene='lingerie', starter_note=" in branch
    assert 'starter_photo_service.save' in branch
    assert "url = f'/webapp/starter/{cache_id}'" in branch
    assert 'daily_limit.note_message' in branch
    for money in ('spend_peaches', 'use_free_chat_photo', 'use_pool_photo', 'peaches'):
        assert money not in branch
    turn_start = MAIN.index('async def _webapp_chat_turn')
    turn = MAIN[turn_start:MAIN.index('\nasync def ', turn_start + 10)]
    assert 'starter = await _starter_frame_turn' in turn
    assert turn.index('starter = await _starter_frame_turn') < turn.index('_prelude()')


def test_starter_media_route_is_authorized_and_the_card_route_is_gone():
    assert "app.router.add_get('/webapp/starter/{cache_id}', _webapp_starter_photo)" in MAIN
    handler = MAIN[MAIN.index('async def _webapp_starter_photo'):MAIN.index('async def _webapp_card')]
    assert "webapp_service.validate_init_data" in handler
    assert 'is_adult_confirmed(telegram_id)' in handler
    assert 'starter_photo_service.body_for' in handler
    assert "_webapp_greeting_photo" not in MAIN
    assert "'/webapp/greeting/{greeting_id}'" not in MAIN


def test_starter_photo_kitchen_and_startup_sync_are_wired():
    assert "callback_data='admin:starter'" in MAIN
    for prefix in ("F.data == 'admin:starter'", "F.data.startswith('admin:starter:')",
                   "F.data.startswith('admin:startersc:')", "F.data.startswith('admin:starterdel:')"):
        assert prefix in MAIN
    kitchen = MAIN[MAIN.index("F.data == 'admin:starter'"):]
    assert kitchen.count('if cq.from_user.id not in ADMIN_TELEGRAM_IDS') >= 4
    assert "text='🗑 Удалить этот кадр'" in MAIN
    assert 'starter_photo_service.delete' in MAIN
    assert 'greeting_service.sync_universal_seed' in MAIN
