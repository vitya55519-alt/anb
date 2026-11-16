"""V3.166.7 (владелец): одна голова.

Она отвечает одним вызовом модели, и последней строкой этого же вызова пишет
служебную анкету кадра — где стоит, кто физически в этой же комнате, как это
выглядит. Отсюда локацию берёт генератор картинок, отсюда же «Раздеть» решает,
быть ли человеку за её спиной («муж в гараже» — в кадре никого). Его строку
анкета не видит: она вырезается до истории, до озвучки и до пузыря.

Здесь pinned: разбор анкеты, что она никогда не сохраняется как её текст, что
генератор берёт место только из неё, что приватная комната больше не выдумывается
наугад — и что экономика кадров после первого кадра осталась нетронутой.
"""
import os
import time
from pathlib import Path

os.environ.setdefault('TELEGRAM_TOKEN', '123456:test-fake-token-for-static-tests-only')
os.environ.setdefault('OPENAI_API_KEY', 'sk-test-fake-for-static-tests-only')
os.environ.setdefault('GEMINI_API_KEY', 'x')
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from services.db import SessionLocal  # noqa: E402,F401  (creates the schema)
from models.app_models import DialogSession  # noqa: E402

import services.chat_service as cs  # noqa: E402
import services.photo_service as ps  # noqa: E402
import services.scene_card_service as sc  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
IDEA = (ROOT / 'services' / 'photo_idea_service.py').read_text(encoding='utf-8')
STATE = (ROOT / 'services' / 'state_service.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')

# Unique id band: 9967xx.
_TIDS = []


def _tid(n: int) -> int:
    tid = 996700 + n
    _TIDS.append(tid)
    return tid


def teardown_module(module):
    with SessionLocal() as s:
        s.query(DialogSession).filter(DialogSession.telegram_id.in_(_TIDS)).delete()
        s.commit()


# ── анкета: разбор ─────────────────────────────────────────────────────────

def test_the_card_splits_into_fields():
    card = sc.parse('где=примерочная | рядом=нет | кто= | сцена=a boutique fitting room, '
                    'warm downlights, a mirror and a curtain behind her')
    assert card['place'] == 'примерочная'
    assert card['near'] is False
    assert 'with' not in card
    assert card['scene'].startswith('a boutique fitting room')


def test_a_man_in_the_garage_is_not_in_the_room():
    # «Платон в гараже» — он не рядом, и выдуманного зрителя в кадр она не пускает.
    card = sc.parse('где=примерочная | рядом=нет | кто=her husband | сцена=a fitting room')
    assert card['near'] is False and 'with' not in card
    both = sc.parse('где=ванная | рядом=да | кто=her husband | сцена=a bathroom at night')
    assert both['near'] is True and both['with'] == 'her husband'


def test_the_card_never_reaches_his_eyes():
    raw = ('THOUGHT: он ждёт\nMESSAGE: я в примерочной, лови 📸\n'
           'КАДР: где=примерочная | рядом=нет | кто= | сцена=a boutique fitting room')
    assert sc.card_line(raw).startswith('где=примерочная')
    stripped = sc.strip_card(raw)
    assert 'КАДР' not in stripped
    assert stripped.splitlines()[1] == 'MESSAGE: я в примерочной, лови 📸'
    thought, draft, message = cs._blocks(raw)
    assert 'КАДР' not in message and 'КАДР' not in thought and 'КАДР' not in draft
    assert message == 'я в примерочной, лови 📸'
    assert 'КАДР' not in cs.message_block(raw)


def test_a_line_about_a_shot_is_not_a_card():
    # «любимый кадр: вот этот» — её слова, а не служебная строка.
    raw = 'MESSAGE: любимый кадр: вот этот 😌'
    assert sc.card_line(raw) == '' and sc.strip_card(raw) == raw


# ── анкета: хранение ───────────────────────────────────────────────────────

def test_the_card_survives_per_girl_and_expires():
    tid = _tid(1)
    sc.remember(tid, 'lana_01', 'где=кухня | рядом=нет | кто= | сцена=a kitchen in the morning light')
    assert sc.scene_for(tid, 'lana_01').startswith('a kitchen')
    assert sc.scene_for(tid, 'anna_01') == ''          # другая героиня — своя сцена
    assert sc.together_with(tid, 'lana_01') == (False, '')
    assert 'она кухня' in sc.continuation(sc.current(tid, 'lana_01'))
    stored = sc._store.get(tid)
    row = stored['lana_01']
    row['at'] = int(time.time()) - sc.TTL_SECONDS - 60  # шестой час пошёл
    sc._store[tid] = dict(stored)
    assert sc.current(tid, 'lana_01') == {} and sc.scene_for(tid, 'lana_01') == ''


def test_an_empty_card_keeps_the_previous_scene():
    tid = _tid(2)
    sc.remember(tid, 'lana_01', 'где=кухня | рядом=нет | кто= | сцена=a kitchen at night')
    sc.remember(tid, 'lana_01', sc.card_line('MESSAGE: погоди'))  # модель строку не написала
    assert sc.scene_for(tid, 'lana_01').startswith('a kitchen')


# ── Блок 1: одна голова ────────────────────────────────────────────────────

def test_the_reply_carries_the_card_rule_and_the_remember_runs_first():
    assert 'from services import scene_card_service' in CHAT
    assert 'scene_card_service.SCENE_CARD_DIRECTIVE' in CHAT
    assert 'scene_card_service.continuation(' in CHAT
    turn = CHAT[CHAT.index('def _blocks('):]
    assert 'scene_card_service.strip_card(t)' in turn[:turn.index('marks =')]
    reply = CHAT[CHAT.index('async def reply('):]
    assert reply.index('scene_card_service.remember') < reply.index('save_message(db_user_id, character_id, "user"')


def test_the_photo_now_comes_after_her_words():
    # раньше кадр рисовался до вызова модели: «одна голова» была невозможна.
    turn = MAIN[MAIN.index('async def _webapp_chat_turn('):]
    assert turn.index('answer = await anna_reply(') < turn.index('if photo_scene:')
    assert '_photo_turn(photo_scene, photo_req, said=said, pay=photo_pay)' in turn
    assert 'await _photo_turn(photo_scene, photo_req, pay=photo_pay)' not in turn


# ── Блок 3: генератор берёт место только из анкеты ─────────────────────────

def test_the_generator_locates_the_frame_from_the_card():
    tid = _tid(3)
    sc.remember(tid, 'lana_01', 'где=примерочная | рядом=нет | кто= | '
                                 'цена= | сцена=a boutique fitting room, curtain and mirror')
    resolved = ps._resolve_request(tid, ps.PhotoRequest(scene='selfie'), character_id='lana_01')
    assert 'PLACE FROM HER MESSAGE: a boutique fitting room' in resolved.location
    prompt = ps._build_prompt(resolved, 0, seedream=True, relationship_level=5, character_id='lana_01')
    assert 'PLACE FROM HER MESSAGE: a boutique fitting room' in prompt
    for stale in ('в спальне', 'her bedroom', 'current fictional day context'):
        assert stale not in prompt, stale


def test_his_own_words_beat_the_card():
    tid = _tid(4)
    sc.remember(tid, 'lana_01', 'где=кухня | рядом=нет | кто= | сцена=a kitchen')
    req = ps.PhotoRequest(scene='selfie', location='on the balcony over the yard', customized=True)
    assert 'PLACE FROM HER MESSAGE' not in ps._resolve_request(tid, req, character_id='lana_01').location


def test_the_idea_bank_stands_down_when_the_card_has_spoken():
    assert 'async def enrich_request_with_idea(telegram_id: int, request, *, character_id: str)' in IDEA
    assert 'scene_card_service.scene_for(telegram_id, character_id)' in IDEA
    src = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
    assert 'enrich_request_with_idea(telegram_id, request, character_id=character_id)' in src


# ── Блок 3: приватная комната больше не выдумывается ───────────────────────

def test_a_named_room_is_kept_instead_of_a_random_bedroom():
    card = ('SCENE: bar. PLACE FROM HER MESSAGE: a crowded sports bar, '
            'the match on the screen behind her.\nWARDROBE: black lace lingerie')
    moved = ps.enforce_private_location(card)
    assert moved.startswith('PRIVATE PLACE OVERRIDE:')
    assert 'a crowded sports bar' in moved
    assert 'her bedroom' not in moved and 'a hotel room' not in moved
    assert 'Nobody but her is in the room' in moved


def test_the_room_the_card_named_is_never_moved():
    kept = ('SCENE: home. PLACE FROM HER MESSAGE: her bathroom at night.\n'
            'WARDROBE: nothing but a towel')
    assert ps.enforce_private_location(kept) == kept
    # примерочная — тоже комната за дверью: её слова остаются, спальня не нужна
    fitting = ('SCENE: shop. PLACE FROM HER MESSAGE: a boutique fitting room, '
               'a curtain and a mirror.\nWARDROBE: black lace lingerie')
    assert ps.enforce_private_location(fitting) == fitting


def test_a_venue_with_a_guest_keeps_the_guest():
    card = ('SCENE: bar. PLACE FROM HER MESSAGE: a crowded sports bar; '
            'in the same room: her husband.\nWARDROBE: lace bra')
    moved = ps.enforce_private_location(card)
    assert 'a crowded sports bar' in moved
    assert 'her husband is the only other person in that room' in moved
    assert 'Nobody but her is in the room' not in moved


def test_a_place_without_walls_still_moves_inside():
    card = ('SCENE: street. PLACE FROM HER MESSAGE: a night street with passers-by.\n'
            'WARDROBE: only lingerie')
    moved = ps.enforce_private_location(card)
    assert moved.startswith('PRIVATE PLACE OVERRIDE: she wears only lingerie')
    assert 'PLACE FROM HER MESSAGE: a night street' in moved.split('\n', 1)[1]


# ── Блоки 4-5: «Раздеть» правит тот же кадр ────────────────────────────────

def _undress_prompt(tid, monkeypatch, who_status='mar_married'):
    import main
    import services.webapp_service as ws
    monkeypatch.setattr(ws, '_batch_marital', lambda t, ids: {ids[0]: who_status})
    monkeypatch.setattr(main, 'get_relationship_level', lambda *a: 2)
    return main._undress_prompt(tid, 'lana_01')


def test_the_undress_edit_takes_the_room_from_her_words(monkeypatch):
    tid = _tid(5)
    sc.remember(tid, 'lana_01', 'где=кухня | рядом=нет | кто= | сцена=a kitchen, evening light')
    prompt, _ = _undress_prompt(tid, monkeypatch)
    assert 'PLACE FROM HER OWN WORDS' in prompt and 'a kitchen, evening light' in prompt
    assert 'move her into her bedroom or a hotel room' not in prompt
    assert 'never take its room, background, furniture' in prompt  # image 2 = only her face


def test_the_husband_stands_behind_her_only_while_he_is_in_the_room(monkeypatch):
    away = _tid(6)
    sc.remember(away, 'lana_01', 'где=кухня | рядом=нет | кто= | сцена=a kitchen')
    prompt, secret = _undress_prompt(away, monkeypatch)
    assert 'husband' not in prompt and secret is False

    near = _tid(7)
    sc.remember(near, 'lana_01', 'где=кухня | рядом=да | кто=her husband | сцена=a kitchen')
    prompt, secret = _undress_prompt(near, monkeypatch)
    assert 'her husband (an adult man, fully clothed)' in prompt and secret is True

    # анкеты нет — прежняя механика остаётся (никто её не отменял)
    silent = _tid(8)
    prompt, secret = _undress_prompt(silent, monkeypatch)
    assert secret is True and 'husband' in prompt
    single = _tid(9)
    prompt, secret = _undress_prompt(single, monkeypatch, who_status='mar_single')
    assert secret is False and 'husband' not in prompt


# ── экономика после первого кадра не тронута ───────────────────────────────

def test_the_frame_economy_is_untouched():
    assert 'EXPLICIT_PHOTO_PEACH_COST = _peaches("EXPLICIT_PHOTO_PEACH_COST", 250)' in CONFIG
    assert 'UNDRESS_PEACH_COST = _peaches("UNDRESS_PEACHES_V165", EXPLICIT_PHOTO_PEACH_COST)' in CONFIG
    assert "pay in ('undress_credit', 'undress_peaches', 'explicit_peaches'" in MAIN
    for price in ('EXPLICIT_PHOTO_PEACH_COST', 'UNDRESS_PEACH_COST', 'CHAT_PHOTO_PEACH_COST'):
        assert price in MAIN
