"""Synthetic event participation, grounded continuity and integration checks."""
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from models.app_models import LifeEvent, LifeParticipant, Message, User
from models.waifu_models import Base
from services import db, life_experiment as E, life_scene as L, memory_service as M
from services import life_event_service as G, presence_service as P, webapp_service as W
from services import scheduler_service as S

CID = 'anna_01'
TG = 995190001


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + (tmp_path / 'scenes.sqlite').as_posix(),
                           connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    original = db.SessionLocal
    for name, module in list(sys.modules.items()):
        if (name.startswith('services.') or name == 'main') and getattr(module, 'SessionLocal', None) is original:
            monkeypatch.setattr(module, 'SessionLocal', sessions)
    monkeypatch.setattr(db, 'engine', engine)
    monkeypatch.setattr(E, 'ENABLED', True)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with sessions() as s:
        user = User(telegram_id=str(TG), name='Synthetic', selected_character=CID, spicy_mode=False)
        s.add(user)
        s.commit()
        uid = user.id
    context = E.assignment(uid)
    # Force an explicit test arm, never depend on a lucky hash bucket.
    with sessions() as s:
        participant = s.scalar(select(LifeParticipant).where(LifeParticipant.user_id == uid))
        participant.variant = 'treatment'
        s.commit()
    context['variant'] = 'treatment'
    context['mode_on'] = False
    try:
        yield SimpleNamespace(uid=uid, sessions=sessions, now=now, context=context)
    finally:
        monkeypatch.undo()
        for name, module in list(sys.modules.items()):
            if (name.startswith('services.') or name == 'main') and getattr(module, 'SessionLocal', None) is sessions:
                module.SessionLocal = original
        engine.dispose()


def deliver(env, *, cid=CID, text='Пирог подгорел. Спасаем или пицца?', mode=False):
    ctx = dict(env.context, mode_on=mode)
    mid = M.save_message(env.uid, cid, 'assistant', text, origin='life', life_context=ctx,
                         actions=[{'type': 'reply', 'label': 'Спасаем', 'text': 'Спасаем'},
                                  {'type': 'reply', 'label': 'Пицца', 'text': 'Пицца'}])
    with env.sessions() as s:
        event = s.scalar(select(LifeEvent).where(LifeEvent.message_id == mid))
        return event.id, mid


def turn(env, text='Давай пиццу', reply='Тогда убираю форму и выбираю пиццу.', state='active', cid=CID, mode=False):
    context = L.turn_context(env.uid, cid, text, mode_on=mode)
    assert context is not None
    uid = M.save_message(env.uid, cid, 'user', text, origin='user_input')
    context.update(user_message_id=uid, response_state=state)
    mid = M.save_message(env.uid, cid, 'assistant', reply, life_scene_context=context)
    return context, uid, mid


@pytest.mark.parametrize('raw', [
    'Нет вариантов', 'Текст события\nCHOICES: nope',
    'Текст события\nCHOICES: ["один"]', 'Текст события\nCHOICES: ["да", "да"]',
    'Текст события\nCHOICES: ["/pay", "нет"]',
    'Текст события\nCHOICES: ["<script>", "нет"]',
    'Текст события\nCHOICES: [true, "нет"]',
])
def test_invalid_choices_fail_silently(raw):
    assert L.parse_moment(raw) == ('', [])


def test_two_choices_use_the_existing_free_text_actions():
    text, actions = L.parse_moment('Пирог подгорел. Спасаем или пицца?\nCHOICES: ["Спасаем", "Пицца"]')
    assert text.endswith('пицца?')
    assert len(actions) == 2 and {a['type'] for a in actions} == {'reply'}
    assert all(a['label'] == a['text'] for a in actions)


@pytest.mark.parametrize('text,status', [('нет', 'closed'), ('не хочу', 'closed'),
    ('давай о другом', 'closed'), ('сменим тему', 'closed'), ('пока', 'closed'),
    ('давай продолжим завтра', 'paused'), ('не хочу спать', None),
    ('нет, лучше попробуем спасти', None), ('Он сказал «не хочу»', None)])
def test_refusal_pause_and_quoted_words_are_not_confused(text, status):
    assert L.direct_status(text) == status


@pytest.mark.parametrize('state', ['active', 'paused', 'closed', 'unrelated'])
def test_routing_is_hidden_even_from_history_and_voice(state):
    from services.chat_service import message_block
    raw = 'Хорошо, так и сделаем.\nLIFE_STATE: ' + state
    assert L.response_state(raw) == state
    assert message_block(raw) == 'Хорошо, так и сделаем.'
    assert 'LIFE_STATE' not in L.strip_state(raw)


def test_unknown_or_duplicate_routing_cannot_keep_a_scene_alive():
    assert L.response_state('LIFE_STATE: invented') == 'unrelated'
    assert L.response_state('LIFE_STATE: active\nLIFE_STATE: active') == 'unrelated'
    assert L.strip_state('Текст\nLIFE_STATE: secret bogus') == 'Текст'


def test_continuation_uses_owned_visible_source_and_actual_choice(env):
    eid, source = deliver(env)
    context, uid, mid = turn(env)
    assert 'Пирог подгорел' in context['note']
    resumed = L.turn_context(env.uid, CID, 'С грибами', mode_on=False)
    assert 'Давай пиццу' in resumed['note']
    assert 'убираю форму' in resumed['note']
    with env.sessions() as s:
        e = s.get(LifeEvent, eid)
        assert e.choice_message_id == uid and e.reply_message_id == mid
        assert e.scene_status == 'active' and e.reply_count == 1
        assert s.get(Message, source).actions_json is None


def test_different_choices_leave_different_grounded_continuations(env):
    eid, _ = deliver(env)
    turn(env, 'Спасаем', 'Срезаю корочку, мякиш ещё мягкий.')
    note_a = L.turn_context(env.uid, CID, 'И что дальше?', mode_on=False)['note']
    turn(env, 'Нет, лучше пиццу', 'Убираю пирог и выбираю начинку.')
    note_b = L.turn_context(env.uid, CID, 'И что дальше?', mode_on=False)['note']
    assert 'Срезаю корочку' in note_a and 'Срезаю корочку' not in note_b
    assert 'лучше пиццу' in note_b and 'выбираю начинку' in note_b


def test_refusal_closes_even_without_a_successful_assistant_reply(env):
    eid, _ = deliver(env)
    M.save_message(env.uid, CID, 'user', 'не хочу', origin='user_input')
    assert L.turn_context(env.uid, CID, 'привет', mode_on=False) is None
    with env.sessions() as s:
        assert s.get(LifeEvent, eid).scene_status == 'closed'
        assert s.get(LifeEvent, eid).reply_count == 1  # refusal is still his real message


def test_unrelated_free_text_closes_and_cannot_be_reoffered(env):
    eid, _ = deliver(env)
    turn(env, 'Как устроена радуга?', 'Свет преломляется в каплях.', state='unrelated')
    assert L.turn_context(env.uid, CID, 'привет', mode_on=False) is None
    with env.sessions() as s:
        assert L.welcome_back(s, env.uid, CID, env.now + timedelta(hours=4)) == (True, None)


def test_pause_and_one_offer_replace_existing_welcome_slot(env):
    eid, _ = deliver(env)
    context, uid, mid = turn(env, 'давай продолжим завтра', 'Хорошо, до завтра.', state='paused')
    with env.sessions() as s:
        e = s.get(LifeEvent, eid)
        assert e.scene_status == 'paused' and e.reply_message_id == mid
    when = env.now + timedelta(hours=5)
    line = P.maybe_welcome_back(env.uid, CID, now=when)
    assert 'продолжим завтра' in line
    assert P.maybe_welcome_back(env.uid, CID, now=when + timedelta(hours=5)) is None
    with env.sessions() as s:
        offers = s.scalars(select(Message).where(Message.origin == 'life_continuation')).all()
        assert len(offers) == 1
        assert s.get(LifeEvent, eid).offered_at == when


def test_ignored_event_gets_no_extra_welcome_message(env):
    eid, _ = deliver(env)
    assert P.maybe_welcome_back(env.uid, CID, now=env.now + timedelta(hours=5)) is None
    with env.sessions() as s:
        assert len(s.scalars(select(Message)).all()) == 1


def test_mode_change_cannot_reopen_old_scene(env):
    eid, _ = deliver(env)
    turn(env)
    assert L.turn_context(env.uid, CID, 'привет', mode_on=True) is None
    assert L.turn_context(env.uid, CID, 'привет', mode_on=False) is None


def test_both_modes_keep_the_selected_flag(env):
    with env.sessions() as s:
        s.get(User, env.uid).spicy_mode = True
        s.commit()
    eid, _ = deliver(env, mode=True)
    turn(env, mode=True)
    assert L.turn_context(env.uid, CID, 'дальше', mode_on=True)
    with env.sessions() as s:
        assert s.get(User, env.uid).spicy_mode is True
        assert s.get(LifeEvent, eid).mode_on is True


def test_other_character_has_no_access_to_scene(env):
    deliver(env)
    assert L.turn_context(env.uid, 'another_character', 'привет', mode_on=False) is None
    assert L.turn_context(env.uid + 1, CID, 'привет', mode_on=False) is None


def test_deleted_source_and_corrupt_choice_do_not_leak_other_chat(env):
    eid, source = deliver(env)
    _, uid, mid = turn(env)
    with env.sessions() as s:
        other = Message(user_id=env.uid, character_id='other', role='user', content='OTHER_SECRET')
        s.add(other)
        s.flush()
        s.get(LifeEvent, eid).choice_message_id = other.id
        s.commit()
    context = L.turn_context(env.uid, CID, 'привет', mode_on=False)
    assert 'OTHER_SECRET' not in context['note']
    with env.sessions() as s:
        s.delete(s.get(Message, source))
        s.commit()
    assert L.turn_context(env.uid, CID, 'привет', mode_on=False) is None


def test_new_event_or_stop_prevents_late_reply_from_restoring_scene(env):
    old, _ = deliver(env)
    context = L.turn_context(env.uid, CID, 'Пицца', mode_on=False)
    uid = M.save_message(env.uid, CID, 'user', 'Пицца', origin='user_input')
    context.update(user_message_id=uid, response_state='active')
    new, _ = deliver(env, text='Выбираю книгу. Детектив или комедия?')
    M.save_message(env.uid, CID, 'assistant', 'Выбираю пиццу.', life_scene_context=context)
    with env.sessions() as s:
        assert s.get(LifeEvent, old).scene_status == 'closed'
        assert s.get(LifeEvent, new).choice_message_id is None
    E.stop()
    assert L.turn_context(env.uid, CID, 'Комедия', mode_on=False) is None


def test_expired_scene_is_not_current_location(env):
    deliver(env)
    assert L.turn_context(env.uid, CID, 'Привет', mode_on=False,
                          now=env.now + timedelta(days=8)) is None


def test_new_delivery_cannot_claim_already_saved_input(env):
    old, _ = deliver(env)
    M.save_message(env.uid, CID, 'user', 'Да', origin='user_input')
    new, _ = deliver(env, text='Появилась другая ситуация.')
    with env.sessions() as s:
        assert s.get(LifeEvent, old).reply_count == 1
        assert s.get(LifeEvent, new).reply_count == 0


def test_history_poll_is_not_an_open(env, monkeypatch):
    eid, _ = deliver(env)
    from services import message_voice_service
    monkeypatch.setattr(message_voice_service, 'ready_by_messages', lambda *a: {})
    W.api_chat_history(env.uid, CID, opened=False)
    with env.sessions() as s:
        assert s.get(LifeEvent, eid).opened_at is None
    W.api_chat_history(env.uid, CID, opened=True)
    with env.sessions() as s:
        assert s.get(LifeEvent, eid).opened_at is not None
        assert s.get(LifeEvent, eid).reply_count == 0


def test_delivery_rolls_back_if_identity_cannot_be_saved(env, monkeypatch):
    def fail(*args):
        raise RuntimeError('synthetic attribution failure')
    monkeypatch.setattr(E, 'record_delivery', fail)
    with pytest.raises(RuntimeError):
        deliver(env)
    with env.sessions() as s:
        assert not s.scalars(select(Message)).all()


def test_synthetic_scene_does_not_count_as_user_reply(env):
    eid, _ = deliver(env)
    M.save_message(env.uid, CID, 'user', 'scripted purchase reaction', origin='synthetic')
    with env.sessions() as s:
        assert s.get(LifeEvent, eid).reply_count == 0


@pytest.mark.parametrize('mode', [False, True])
def test_generator_two_paths_one_call_and_existing_mode(env, monkeypatch, mode):
    from services import llm_provider_service
    seen = []
    async def generate(messages, **kwargs):
        seen.append((messages, kwargs))
        return SimpleNamespace(text='Пирог подгорел. Спасаем или пицца?\nCHOICES: ["Спасаем", "Пицца"]', complete=True)
    monkeypatch.setattr(llm_provider_service, 'generate_text', generate)
    monkeypatch.setattr(G, '_character_ingredients', lambda *a: ('Тестовая', [], ''))
    monkeypatch.setattr(G, '_memory_callback', lambda *a: '')
    monkeypatch.setattr(G, '_pending_hook', lambda *a: 'OTHER_CHARACTER_HOOK')
    monkeypatch.setattr(G, '_recent_her_lines', lambda *a: [])
    monkeypatch.setattr(G, '_relationship_frame', lambda *a: (3, mode))
    monkeypatch.setattr(G, 'LIFE_EVENTS_PHOTO_CHANCE', 0)
    result = asyncio.run(G.build_life_moment(TG, CID))
    assert len(seen) == 1 and seen[0][1]['purpose'] == 'life_event'
    assert len(result['actions']) == 2 and result['experiment']['mode_on'] == mode
    assert 'OTHER_CHARACTER_HOOK' not in seen[0][0][0]['content']
    assert ('Без цензуры 18+' in seen[0][0][0]['content']) == mode
    assert 'CHOICES' not in result['text']


def test_control_prompt_and_action_are_unchanged(env, monkeypatch):
    from services import llm_provider_service
    with env.sessions() as s:
        s.scalar(select(LifeParticipant).where(LifeParticipant.user_id == env.uid)).variant = 'control'
        s.commit()
    monkeypatch.setattr(G, 'LIFE_EVENTS_PHOTO_CHANCE', 0)
    monkeypatch.setattr(llm_provider_service, 'generate_text', AsyncMock(
        return_value=SimpleNamespace(text='Пирог подгорел, и тут позвонила подруга.', complete=True)))
    result = asyncio.run(G.build_life_moment(TG, CID))
    assert result['actions'] is None and len(result['options']) == 1
    call = llm_provider_service.generate_text.call_args
    assert call.kwargs['max_tokens'] == 90
    assert 'CHOICES:' not in call.args[0][0]['content']


def test_delivery_ping_failure_does_not_erase_actual_exposure(env, monkeypatch):
    from services import app_ping
    monkeypatch.setattr(app_ping, 'note', Mock(side_effect=RuntimeError('synthetic ping failure')))
    mid = S._app_delivery(object(), env.uid, TG, CID, 'Пирог подгорел. Что делаем?',
                          origin='life', life_context=env.context)
    assert mid
    with env.sessions() as s:
        assert s.scalar(select(LifeEvent).where(LifeEvent.message_id == mid))


def test_old_action_does_not_answer_the_new_event(env):
    eid, source = deliver(env)
    deliver(env, text='Выбираю книгу. Детектив или комедия?')
    with env.sessions() as s:
        assert not L.action_available(s, s.get(Message, source))


def test_history_hides_stale_buttons_but_keeps_the_current_ones(env, monkeypatch):
    from services import message_voice_service
    monkeypatch.setattr(message_voice_service, 'ready_by_messages', lambda *a: {})
    _, old = deliver(env)
    _, fresh = deliver(env, text='Выбираю книгу. Детектив или комедия?')
    rows = W.api_chat_history(env.uid, CID)
    by_id = {r['id']: r for r in rows}
    assert by_id[old]['actions'] == []
    assert len(by_id[fresh]['actions']) == 2


def test_reset_wipes_the_dialog_and_closes_the_scene(env):
    eid, _ = deliver(env)
    turn(env)
    M.reset_conversation(env.uid, CID)
    assert L.turn_context(env.uid, CID, 'привет', mode_on=False) is None
    with env.sessions() as s:
        assert not s.scalars(select(Message)).all()
        e = s.get(LifeEvent, eid)
        assert e.scene_status == 'closed' and e.closed_reason == 'conversation_reset'
        assert e.reply_count == 1
