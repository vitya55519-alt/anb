"""V3.156.0: owner ТЗ (Фогель) — «Живые ситуации» и спон-фото за 400 🍑.

Она пишет из того места, где находится (утро в постели, пробка, клуб с
подругой, прихожая ночью), и обещает кадр отсюда же. Английский промпт кадра
лежит в отдельной колонке ``messages.image_prompt`` и не уезжает ни в историю,
ни в промпт диалога; картинка рисуется провайдеру только после списания 400
купленных 🍑, а не вышел кадр — деньги возвращаются.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from models.app_models import Base, Message, User
from services import live_situation_service as lss
from services.db import SessionLocal, engine
from config import (LIVE_SITUATION_MAX_PER_DAY, LIVE_SITUATION_MIN_LEVEL,
                    LIVE_SITUATION_PEACH_COST)

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
UI = (ROOT / 'services' / 'ui_lang.py').read_text(encoding='utf-8')

CID = 'anna_01'
TINY_JPEG = b'\xff\xd8\xff\xe0' + b'0' * 40
TEASER = ('THOUGHT: у меня сердце колотится, я стою у зеркала и боюсь, что войдут\n'
          'MESSAGE: сижу в примерочной, юбка вышла слишком короткой 🙈 хочу показать, '
          'самая честная вещь в моей жизни. хочешь, покажу фотку прямо отсюда, '
          'пока никто не видит?\n'
          'IMAGE_PROMPT: mall fitting room, mirror, first-person phone selfie in a '
          'very short skirt, bright spots, embarrassed smile')


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _pair(peaches: int = 1000, level: int = 6):
    """A fresh (user, girl) pair with a bought peach wallet and a fake LLM."""
    Base.metadata.create_all(engine)
    stamp = _now().strftime('%H%M%S%f')
    tid = int(f'93{stamp}')
    with SessionLocal() as s:
        s.add(User(id=None, telegram_id=str(tid), name='t', photo_credits=peaches,
                   bonus_peaches=0))
        s.commit()
        uid = s.scalar(_select_uid(tid))
    lss._state[tid] = {}
    _set_level(tid, level)
    return tid, uid


def _select_uid(tid: int):
    from sqlalchemy import select
    return select(User.id).where(User.telegram_id == str(tid))


def _set_level(tid: int, level: int) -> None:
    import services.photo_service as ps
    if not hasattr(ps, '_v31560_levels'):
        ps._v31560_levels = {}
        orig = ps.get_relationship_level

        def patched(telegram_id, character_id=CID, *_a, **_kw):
            return ps._v31560_levels.get(int(telegram_id), orig(telegram_id, character_id))
        ps.get_relationship_level = patched
    ps._v31560_levels[int(tid)] = level


class _FakeLLM:
    def __init__(self, text=TEASER, raise_it=False):
        self.text = text
        self.raise_it = raise_it
        self.calls = []

    async def __call__(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.raise_it:
            raise RuntimeError('no llm')
        return SimpleNamespace(text=self.text, complete=True)


def _fake_llm(monkeypatch, text=TEASER, raise_it=False):
    import services.llm_provider_service as llm
    fake = _FakeLLM(text, raise_it)
    monkeypatch.setattr(llm, 'generate_text', fake)
    return fake


class _FakeRender:
    def __init__(self, data=TINY_JPEG):
        self.data = data
        self.calls = []

    async def __call__(self, character_id, prompt, **_kw):
        self.calls.append((character_id, prompt))
        return self.data


def _fake_render(monkeypatch, data=TINY_JPEG):
    import services.private_photo_service as pps
    fake = _FakeRender(data)
    monkeypatch.setattr(pps, 'generate_live_situation_photo', fake)
    return fake


def _message_row(message_id: int) -> Message:
    with SessionLocal() as s:
        return s.get(Message, message_id)


# ── цена и хранение ────────────────────────────────────────────────────────

def test_the_owner_made_the_sponsor_photo_cost_400_peaches():
    # ТЗ писал 100 🍑, владелец поправил: «спон фото за 400 персиков».
    assert LIVE_SITUATION_PEACH_COST == 400
    assert lss.price() == 400


def test_the_paid_scene_has_its_own_column_not_the_message_body():
    cols = Base.metadata.tables['messages'].columns.keys()
    assert {'image_prompt', 'image_unlocked'} <= set(cols)
    tid, uid = _pair()
    mid = lss.store_teaser(tid, CID, {'thought': 'мысль', 'message': 'я в примерочной',
                                      'image_prompt': 'mall fitting room selfie'}, uid=uid)
    row = _message_row(mid)
    assert row.image_prompt == 'mall fitting room selfie'
    # движок новеллы: THOUGHT + MESSAGE в content, а English-сцены там нет
    assert row.content.startswith('THOUGHT:') and 'MESSAGE: я в примерочной' in row.content
    assert 'fitting room' not in row.content
    assert not row.image_unlocked


# ── матрица ситуаций по фазам дня ──────────────────────────────────────────

def test_every_phase_of_the_day_has_its_own_situations():
    for when in ('morning', 'day', 'evening', 'night'):
        pool = lss._pool(when)
        assert len(pool) >= 2, when
        for sit in pool:
            assert sit['seed'] and sit['place']
            # кадр всегда first-person selfie и всегда английский
            assert 'selfie' in sit['image'], sit['key']
            assert sit['image'].isascii(), sit['key']


def test_the_day_is_split_like_the_tz_says():
    assert lss.daypart(8) == 'morning'
    assert lss.daypart(14) == 'day'
    assert lss.daypart(21) == 'evening'
    assert lss.daypart(2) == 'night'


def test_the_club_is_a_friday_and_weekend_evening_only():
    friday = datetime(2026, 11, 13).date()
    tuesday = datetime(2026, 11, 10).date()
    assert all(s.get('friend') for s in lss._pool('evening', friday))
    assert any(s.get('friend') for s in lss._pool('evening', tuesday))
    assert not any(s.get('friend') for s in lss._pool('morning', friday))
    assert not any(s.get('friend') for s in lss._pool('night', friday))


def test_the_club_frame_promises_the_crossover_with_a_friend():
    club = [s for s in lss._pool('evening') if s['key'] == 'club'][0]
    assert 'two gorgeous women' in club['image']
    assert 'mini dresses' in club['image']


# ── разбор трёх блоков ─────────────────────────────────────────────────────

def test_three_blocks_come_back_in_the_right_order():
    thought, message, image = lss.split_teaser(TEASER)
    assert thought.startswith('у меня сердце колотится')
    assert 'примерочной' in message
    assert image.startswith('mall fitting room')


def test_a_plain_line_without_marks_is_still_just_her_message():
    thought, message, image = lss.split_teaser('я в маршрутке, тут дым коромыслом')
    assert (thought, image) == ('', '')
    assert message == 'я в маршрутке, тут дым коромыслом'


def test_bold_and_bullets_in_the_labels_do_not_break_the_split():
    thought, message, image = lss.split_teaser(
        '**THOUGHT:** мысль\nMESSAGE: слово\n- IMAGE PROMPT: selfie in bed')
    assert thought == 'мысль' and message == 'слово' and image == 'selfie in bed'


# ── генерация тизера ───────────────────────────────────────────────────────

def test_the_teaser_prompt_asks_for_the_event_and_the_photo_hook(monkeypatch):
    tid, uid = _pair()
    fake = _fake_llm(monkeypatch)
    teaser = asyncio.run(lss.build_teaser(tid, CID, 'day',
                                         situation=lss.DAY_SITUATIONS[0]))
    system = fake.calls[0][0][0]['content']
    assert fake.calls[0][1]['purpose'] == 'live_situation'
    assert '[SYSTEM EVENT: SITUATIONAL PHOTO TEASER]' in system
    assert 'IMAGE_PROMPT' in system and 'THOUGHT' in system and 'MESSAGE' in system
    assert lss.PEEK_QUESTION in system
    assert 'ПОСТОЯНСТВО ЛОКАЦИИ' in system          # LOCATION CONSISTENCY
    assert lss.DAY_SITUATIONS[0]['place'] in system


def test_the_teaser_takes_the_friends_name_into_the_club(monkeypatch):
    tid, uid = _pair()
    fake = _fake_llm(monkeypatch)
    monkeypatch.setattr(lss, '_friend_name', lambda *_a: 'Лана')
    asyncio.run(lss.build_teaser(tid, CID, 'evening', situation=lss.CLUB_SITUATIONS[0]))
    system = fake.calls[0][0][0]['content']
    assert 'Лана' in system
    assert 'her gorgeous friend' in system


def test_a_missing_image_prompt_falls_back_to_the_scene_of_the_situation(monkeypatch):
    tid, uid = _pair()
    _fake_llm(monkeypatch, text='THOUGHT: м\nMESSAGE: я в душе, вода холодная, покажу фотку?')
    teaser = asyncio.run(lss.build_teaser(tid, CID, 'morning',
                                         situation=lss.MORNING_SITUATIONS[1]))
    assert teaser['image_prompt'] == lss.MORNING_SITUATIONS[1]['image']


def test_an_empty_answer_never_becomes_a_plate(monkeypatch):
    tid, uid = _pair()
    _fake_llm(monkeypatch, text='')
    assert asyncio.run(lss.build_teaser(tid, CID, 'day')) is None
    _fake_llm(monkeypatch, raise_it=True)
    assert asyncio.run(lss.build_teaser(tid, CID, 'day')) is None


def test_push_leaves_the_row_and_only_the_price_on_the_surface(monkeypatch):
    tid, uid = _pair()
    _fake_llm(monkeypatch)
    offer = asyncio.run(lss.push(tid, CID, 'day', uid=uid))
    assert offer['price'] == 400 and offer['id']
    row = _message_row(offer['id'])
    assert row.image_prompt.startswith('mall fitting room')
    # история приложения: только id, цена и «заплачено/нет»
    from services import webapp_service
    history = webapp_service.api_chat_history(uid, CID, 10)
    entry = [h for h in history if h['id'] == offer['id']][0]
    assert entry['live'] == {'paid': False, 'price': 400}
    assert 'fitting room' not in json.dumps(history, ensure_ascii=False)


# ── гейты: когда она имеет право это прислать ──────────────────────────────

def test_the_same_phase_of_the_day_is_not_offered_twice(monkeypatch):
    tid, uid = _pair()
    _fake_llm(monkeypatch)
    assert asyncio.run(lss.push(tid, CID, 'day', uid=uid))
    assert asyncio.run(lss.push(tid, CID, 'day', uid=uid)) is None
    assert asyncio.run(lss.push(tid, CID, 'night', uid=uid))


def test_the_daily_budget_is_a_hard_cap(monkeypatch):
    tid, uid = _pair()
    _fake_llm(monkeypatch)
    phases = ['morning', 'day', 'evening', 'night'][:LIVE_SITUATION_MAX_PER_DAY + 2]
    fired = [asyncio.run(lss.push(tid, CID, p, uid=uid)) for p in phases]
    assert sum(1 for f in fired if f) == LIVE_SITUATION_MAX_PER_DAY


def test_the_teaser_waits_for_the_closeness_and_the_switch(monkeypatch):
    tid, uid = _pair(level=LIVE_SITUATION_MIN_LEVEL - 1)
    assert lss.can_fire(tid, CID, 'day') is False
    _set_level(tid, LIVE_SITUATION_MIN_LEVEL)
    assert lss.can_fire(tid, CID, 'day') is True
    monkeypatch.setattr(lss, 'LIVE_SITUATIONS_ENABLED', False)
    assert lss.can_fire(tid, CID, 'day') is False


def test_a_live_18_plus_scene_is_not_interrupted_by_a_photo_offer(monkeypatch):
    import services.fetish_mode as fm
    tid, uid = _pair()
    monkeypatch.setattr(fm, 'status', lambda *_a, **_kw: {'key': 'feet'})
    assert lss.can_fire(tid, CID, 'day') is False
    monkeypatch.setattr(fm, 'status', lambda *_a, **_kw: None)
    assert lss.can_fire(tid, CID, 'day') is True


def test_a_new_phase_is_what_makes_her_write_on_chat_open():
    tid, uid = _pair()
    assert lss.phase_changed(tid, 'day') is True        # ещё никакой фазы не было
    lss.note_fired(tid, 'day')
    assert lss.phase_changed(tid, 'day') is False
    assert lss.phase_changed(tid, 'night') is True


def test_no_llm_is_called_when_the_gate_says_no(monkeypatch):
    tid, uid = _pair(level=1)
    fake = _fake_llm(monkeypatch)
    assert asyncio.run(lss.push(tid, CID, 'day', uid=uid)) is None
    assert fake.calls == []


# ── оплата и ленивая генерация ─────────────────────────────────────────────

def _teaser_row(tid: int, uid: int, monkeypatch) -> int:
    _fake_llm(monkeypatch)
    return asyncio.run(lss.push(tid, CID, 'day', uid=uid))['id']


def test_the_picture_is_drawn_only_after_the_peaches_are_spent(monkeypatch):
    tid, uid = _pair()
    mid = _teaser_row(tid, uid, monkeypatch)
    render = _fake_render(monkeypatch)
    res = asyncio.run(lss.unlock_photo(tid, CID, mid, uid))
    assert res['ok'] and res['price'] == 400
    assert res['photo_url'].startswith('/webapp/media/')
    assert render.calls and render.calls[0][0] == CID
    assert 'LOCATION LOCK' in render.calls[0][1]
    assert res['left'] == 1000 - 400
    photo = [m for m in SessionLocal().query(Message).filter(
        Message.user_id == uid, Message.media_kind == 'photo').all()]
    assert photo[0].content == 'Только удали потом, ладно? 🤫'
    assert _message_row(mid).image_unlocked


def test_a_locked_plate_never_leaks_the_scene_into_the_history(monkeypatch):
    tid, uid = _pair()
    mid = _teaser_row(tid, uid, monkeypatch)
    _fake_render(monkeypatch)
    from services import webapp_service
    before = json.dumps(webapp_service.api_chat_history(uid, CID, 10), ensure_ascii=False)
    assert 'first-person phone selfie' not in before
    assert asyncio.run(lss.unlock_photo(tid, CID, mid, uid))['ok']
    after = json.dumps(webapp_service.api_chat_history(uid, CID, 10), ensure_ascii=False)
    assert 'first-person phone selfie' not in after


def test_two_taps_of_the_same_plate_pay_once(monkeypatch):
    tid, uid = _pair(peaches=400)
    mid = _teaser_row(tid, uid, monkeypatch)
    _fake_render(monkeypatch)
    first = asyncio.run(lss.unlock_photo(tid, CID, mid, uid))
    second = asyncio.run(lss.unlock_photo(tid, CID, mid, uid))
    assert first['ok'] and not second['ok']
    assert second['error'] == 'already_unlocked'
    assert lss.claim(tid, CID, mid, uid)['ok'] is False


def test_without_bought_peaches_nothing_is_claimed(monkeypatch):
    tid, uid = _pair(peaches=399)
    monkeypatch.setattr(lss, 'ADMIN_TELEGRAM_IDS', set())
    mid = _teaser_row(tid, uid, monkeypatch)
    _fake_render(monkeypatch)
    res = asyncio.run(lss.unlock_photo(tid, CID, mid, uid))
    assert res == {'ok': False, 'error': 'insufficient_peaches', 'cost': 400}
    assert not _message_row(mid).image_unlocked
    from services.payments import get_paid_peaches
    assert get_paid_peaches(tid) == 399


def test_bonus_peaches_do_not_buy_a_real_render(monkeypatch):
    tid, uid = _pair(peaches=0)
    with SessionLocal() as s:
        row = s.get(User, uid)
        row.bonus_peaches = 5000
        s.commit()
    mid = _teaser_row(tid, uid, monkeypatch)
    _fake_render(monkeypatch)
    res = asyncio.run(lss.unlock_photo(tid, CID, mid, uid))
    assert res['error'] == 'insufficient_peaches'


def test_a_failed_frame_goes_back_and_refunds(monkeypatch):
    from services.payments import get_paid_peaches
    tid, uid = _pair()
    mid = _teaser_row(tid, uid, monkeypatch)
    _fake_render(monkeypatch, data=None)
    res = asyncio.run(lss.unlock_photo(tid, CID, mid, uid))
    assert res == {'ok': False, 'error': 'render_failed', 'cost': 400}
    assert get_paid_peaches(tid) == 1000          # деньги вернулись
    assert not _message_row(mid).image_unlocked   # тарелка осталась
    with SessionLocal() as s:
        from models.app_models import StarTransaction
        grants = s.query(StarTransaction).filter(
            StarTransaction.telegram_charge_id == f'credit_grant:live_refund:{mid}:{tid}').count()
    assert grants == 1


def test_the_owner_eats_for_free(monkeypatch):
    tid, uid = _pair()
    monkeypatch.setattr(lss, 'ADMIN_TELEGRAM_IDS', {tid})
    mid = _teaser_row(tid, uid, monkeypatch)
    _fake_render(monkeypatch)
    res = asyncio.run(lss.unlock_photo(tid, CID, mid, uid))
    assert res['ok'] and res['free'] and res['price'] == 0
    from services.payments import get_paid_peaches
    assert get_paid_peaches(tid) == 1000


def test_someone_elses_plate_is_not_his_to_pay(monkeypatch):
    tid_a, uid_a = _pair()
    tid_b, uid_b = _pair()
    mid = _teaser_row(tid_a, uid_a, monkeypatch)
    _fake_render(monkeypatch)
    assert asyncio.run(lss.unlock_photo(tid_b, CID, mid, uid_b))['error'] == 'not_found'


# ── постоянство локации в диалоге ──────────────────────────────────────────

def test_the_dialog_is_told_where_she_actually_stands(monkeypatch):
    tid, uid = _pair()
    _fake_llm(monkeypatch)
    asyncio.run(lss.push(tid, CID, 'day', uid=uid))
    note = lss.directive_for(tid, CID)
    assert 'ПОСТОЯНСТВО ЛОКАЦИИ' in note
    assert 'LOCATION LOCK' in note
    assert 'СКРЫТЫЙ АРХИВ' in note and 'ПЕРЕЕЗД' in note
    assert 'mall fitting room' in note


def test_a_stale_or_someone_elses_situation_stops_steering_the_dialog(monkeypatch):
    tid, uid = _pair()
    _fake_llm(monkeypatch)
    asyncio.run(lss.push(tid, CID, 'day', uid=uid))
    assert lss.directive_for(tid, 'other_girl') == ''
    other_tid, other_uid = _pair()
    assert lss.directive_for(other_tid, CID) == ''
    with SessionLocal() as s:
        s.query(Message).filter(Message.user_id == uid).update(
            {'created_at': _now() - timedelta(hours=lss.HOLD_HOURS + 1)})
        s.commit()
    assert lss.directive_for(tid, CID) == ''


def test_the_directive_rides_the_system_prompt_never_her_voice():
    assert 'live_situation_service.directive_for' in CHAT
    assert '"role": "system", "content": live_note' in CHAT
    # озвучка читает только MESSAGE — служебный блок к ней не попадает
    assert 'live_situation' not in (ROOT / 'services' / 'voice_service.py').read_text(
        encoding='utf-8').lower()


# ── доставка: пуш, открытие чата, кнопка ───────────────────────────────────

def test_the_sponsor_button_exists_in_every_app_language():
    for lang in ('ru', 'en', 'es', 'it', 'fr', 'zh', 'ja', 'bn'):
        block = UI.split(f"'{lang}': {{", 1)[1].split('\n    }', 1)[0]
        for key in ('live_button', 'live_busy', 'live_no_peach', 'live_failed', 'live_gone'):
            assert f"'{key}'" in block, (lang, key)
    assert len(UI.split("'live_button'")) == 9


def test_the_push_lands_with_the_paid_plate_and_the_chat_open_waits_for_a_phase():
    assert 'live:unlock:' in MAIN and 'await live.unlock_photo' in MAIN
    assert '/webapp/api/chat/live' in MAIN
    assert "from services.live_situation_service import push as live_push" in SCHED
    assert "callback_data=f\"live:unlock:{live['id']}\"" in SCHED
    # открытие чата: ждём ровно «сколько она печатает», не больше
    assert '_live_situation_on_open' in MAIN
    assert 'LIVE_SITUATION_WAIT_SECONDS = 6.0' in MAIN
    assert 'asyncio.shield(task)' in MAIN


def test_the_app_draws_the_locked_frame_and_pays_in_place():
    assert 'function livePlate' in SPA and 'data-lplate' in SPA
    assert 'data-live=' in SPA and 'unlockLive' in SPA
    assert "chat/live?init_data=" in SPA
    assert 'lplate-img' in SPA            # размытая рамка вместо кадра
    assert 'j.live && j.live.id' in SPA   # тизер приехал с открытием чата
    for key in ('live_btn', 'live_busy', 'live_failed'):
        assert SPA.count(key) >= 3, key   # en + ru + bn хотя бы


def test_the_teaser_message_is_never_spoken_by_the_voice(monkeypatch):
    """Озвучка берёт текст её сообщения; промпт кадра живёт в своей колонке и
    в ``content`` не появляется ни при каких обстоятельствах."""
    tid, uid = _pair()
    _fake_llm(monkeypatch)
    mid = asyncio.run(lss.push(tid, CID, 'day', uid=uid))['id']
    row = _message_row(mid)
    from services.chat_service import message_block
    assert 'IMAGE_PROMPT' not in row.content
    assert 'selfie' not in message_block(row.content).lower()
