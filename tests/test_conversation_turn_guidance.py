"""Synthetic turn guidance and the actual reply prompt; no network or live data."""
import asyncio
import copy
import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from services.dialogue_guard_service import (
    build_repetition_guard, build_turn_guidance, is_explicit_pause,
)


def msg(role, content):
    return SimpleNamespace(role=role, content=content, created_at=None)


def established(last='Мне нравится эта мысль.'):
    return [m for _ in range(4) for m in (msg('user', 'Обсуждаем кино.'), msg('assistant', last))]


@pytest.mark.parametrize('text', [
    'пока', 'Пока-пока', 'До завтра!', 'Спокойной ночи', 'ладно, я спать',
    'я пойду спать, пока', 'Мне пора, до встречи!', 'давай позже', 'давай сделаем паузу',
    'не пиши пока', 'не отвечай сейчас, пожалуйста', 'не хочу сейчас общаться',
    'хочу побыть один', 'спасибо, продолжим завтра', 'на сегодня всё, пока',
    'на сегодня всё', 'до связи', 'мне нужно идти', 'не хочу общаться сейчас',
    'я устал, давай позже', 'сейчас занят, поговорим потом',
    'bye', 'good night', 'I need a break',
])
def test_explicit_pause_has_priority_over_every_other_turn_rule(text):
    assert is_explicit_pause(text)
    note = build_turn_guidance([msg('assistant', 'А что ты любишь?'),
                                msg('assistant', 'Расскажешь?')], text)
    assert 'ПАУЗА:' in note
    assert 'Без нового вопроса' in note and 'требования ответить' in note
    assert 'ПЕРВЫЕ' not in note and 'ДВА ВОПРОСА' not in note


@pytest.mark.parametrize('text', [
    'не хочу спать', 'я не пойду спать', 'не надо паузу', 'не прощаюсь',
    'пока думаю', 'пока не знаю', 'я пока дома', 'пока есть время, поговорим',
    'он сказал «пока»', 'переведи «спокойной ночи»', 'объясни, почему хочется спать',
    'пришли фото, потом пойду спать', 'оплачу завтра', 'давай купим фото',
    'пока, но сначала пришли фото', 'давай', 'ага', 'не сейчас', 'мне нужно', 'я устал', '',
])
def test_non_pause_and_operations_are_not_mistaken_for_leave_taking(text):
    assert not is_explicit_pause(text)
    assert 'ПАУЗА:' not in build_turn_guidance(established(), text)


@pytest.mark.parametrize('turn', [1, 2, 3, 4])
def test_only_first_three_turns_get_an_opening_not_a_questionnaire(turn):
    history = established()[:2 * (turn - 1)]
    note = build_turn_guidance(history, 'Люблю неожиданные концовки.')
    assert ('ПЕРВЫЕ 1–3 ХОДА:' in note) == (turn <= 3)
    if turn <= 3:
        assert 'сначала ответь на мысль' in note and 'одну небанальную' in note
        assert 'Не начинай анкету' in note and 'меню тем' in note


@pytest.mark.parametrize('question,answer', [
    ('Из какого ты города?', 'Москва'), ('Кем ты работаешь?', 'Повар'),
    ('Сколько лет твоему коту?', '5'), ('Что сейчас читаешь?', 'Мастер и Маргарита'),
])
def test_concrete_short_answer_uses_the_latest_question(question, answer):
    history = established() + [msg('assistant', question)]
    before = copy.deepcopy(history)
    note = build_turn_guidance(history, answer)
    assert 'КОРОТКИЙ ОТВЕТ НА ВОПРОС:' in note
    assert 'не спрашивай то же заново' in note
    assert 'не додумывай факты' in note
    assert 'КОРОТКАЯ РЕАКЦИЯ:' not in note
    assert history == before
    assert build_turn_guidance(history, answer) == note


def test_old_question_does_not_turn_every_short_message_into_an_answer():
    history = established('Из какого ты города?') + [msg('assistant', 'Мне нравится кино.')]
    assert 'КОРОТКИЙ ОТВЕТ НА ВОПРОС:' not in build_turn_guidance(history, 'Москва')
    assert 'КОРОТКИЙ ОТВЕТ НА ВОПРОС:' not in build_turn_guidance(established('Что читаешь?'), 'А ты?')


@pytest.mark.parametrize('text', ['не знаю', 'ага', 'норм', 'Ну, не знаю...', 'угу', 'нет'])
def test_minimal_reaction_continues_topic_without_interrogation(text):
    note = build_turn_guidance(established(), text)
    assert 'КОРОТКАЯ РЕАКЦИЯ:' in note
    assert 'продолжи текущую тему' in note and 'без скачка' in note
    assert 'не добавляй обязательный вопрос' in note
    assert 'согласие, отказ' in note


def test_two_recent_question_turns_require_her_own_reaction():
    history = established() + [msg('assistant', 'Тебе нравится кино?'), msg('user', 'Да'),
                               msg('assistant', 'А какое?')]
    note = build_turn_guidance(history, 'Не знаю')
    assert 'ДВА ВОПРОСА ПОДРЯД:' in note and 'без очередного вопроса' in note
    history.append(msg('assistant', 'Я люблю неожиданную развязку.'))
    assert 'ДВА ВОПРОСА ПОДРЯД:' not in build_turn_guidance(history, 'ага')
    assert 'ДВА ВОПРОСА ПОДРЯД:' not in build_turn_guidance([msg('assistant', 'Как? Почему?')], 'ага')


@pytest.mark.parametrize('offer', ['Прислать фото?', 'Фото стоит 10 персиков. Оплачиваем?'])
@pytest.mark.parametrize('answer', ['ага', 'давай', 'делай', 'нет', 'не знаю', 'не сейчас'])
def test_photo_and_paid_offer_answers_keep_their_meaning(offer, answer):
    note = build_turn_guidance([msg('assistant', offer)], answer)
    assert 'ОТВЕТ НА ПРЕДЛОЖЕНИЕ:' in note
    assert 'не новое разрешение' in note
    assert 'ПЕРВЫЕ' not in note and 'КОРОТКАЯ РЕАКЦИЯ:' not in note
    assert 'ПАУЗА:' not in note


@pytest.mark.parametrize('text', ['пришли фото', 'хочу купить фото', 'оплати покупку'])
def test_explicit_operations_do_not_get_small_talk_guidance(text):
    assert build_turn_guidance([], text) == ''


@pytest.mark.parametrize('text', ['Люблю купаться', 'Ценю юмор', 'У меня список любимых книг'])
def test_action_word_stems_do_not_swallow_ordinary_conversation(text):
    assert 'ПЕРВЫЕ 1–3 ХОДА:' in build_turn_guidance([], text)


@pytest.mark.parametrize('theme,first,second,user', [
    ('coffee/cafe', 'Пью кофе.', 'Беру латте.', 'Давай о кофе'),
    ('walk/city', 'Вернулась с прогулки.', 'Гуляла по набережной.', 'Расскажи о прогулках'),
    ('home/cozy', 'Укуталась пледом.', 'Люблю домашний уют.', 'Ты под пледом?'),
    ('gym', 'После тренировки.', 'Вышла из зала.', 'Расскажи о тренировках'),
    ('food/restaurant', 'Думаю об ужине.', 'После ресторана.', 'Что было на ужин?'),
    ('outfit/fashion', 'В новом платье.', 'Выбирала одежду.', 'Поговорим о платьях'),
])
def test_inflected_motifs_are_blocked_unless_user_brings_them_up(theme, first, second, user):
    history = [msg('assistant', first), msg('assistant', second)]
    assert theme in build_repetition_guard(history, 'У меня хорошая новость')
    assert theme not in build_repetition_guard(history, user)


def test_repetition_is_character_neutral_and_only_counts_her_recent_lines():
    history = [msg('assistant', 'Обсуждали образование и залив.'), msg('assistant', 'Вспомнила сказку.')]
    note = build_repetition_guard(history, 'Продолжай')
    assert 'АНТИ-ПОВТОР' not in note
    assert 'Анн' not in note
    assert 'Анн' not in build_repetition_guard([msg('assistant', 'Пью кофе')], '')
    assert build_repetition_guard([msg('user', 'Пью кофе')], '') == ''
    history = [msg('assistant', 'Пью кофе')] + history
    assert 'coffee/cafe' not in build_repetition_guard(history, '', window=2)


def test_user_topic_exception_does_not_unblock_other_repetitive_motifs():
    history = [msg('assistant', 'Кофе после прогулки.'), msg('assistant', 'Гуляла в парке.')]
    note = build_repetition_guard(history, 'А какой кофе?')
    assert 'coffee/cafe' not in note and 'walk/city' in note


def test_dict_history_and_system_notes_are_safe_and_deterministic():
    history = [{'role': 'system', 'content': 'Задай вопрос?'},
               {'role': 'assistant', 'content': 'Из какого ты города?'}]
    before = copy.deepcopy(history)
    assert 'КОРОТКИЙ ОТВЕТ' in build_turn_guidance(history, 'Москва')
    assert 'ДВА ВОПРОСА' not in build_turn_guidance(history, 'Москва')
    assert build_turn_guidance(history, '') == ''
    assert history == before


@pytest.fixture
def prompt_env(tmp_path, monkeypatch):
    # Nothing that imports config/db is loaded above. A standalone run also
    # bootstraps safely; the test command supplies the same isolation at startup.
    monkeypatch.setenv('PYTHON_DOTENV_DISABLED', '1')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + (tmp_path / 'bootstrap.sqlite').as_posix())
    monkeypatch.delenv('MYSQL_URL', raising=False)
    for key in list(os.environ):
        if key.lower().endswith('_proxy'):
            monkeypatch.delenv(key)
    for key in ('MINIMAX_API_KEY', 'GEMINI_API_KEY', 'OPENAI_API_KEY', 'AI_KEY',
                'SPICYAPI_KEY', 'IMAGE_API_KEY', 'TTS_API_KEY', 'FAL_KEY', 'REPLICATE_API_TOKEN'):
        monkeypatch.setenv(key, 'synthetic-test-key')
    monkeypatch.setenv('TELEGRAM_TOKEN', '123456:synthetic-test-token')

    import dotenv
    import httpx
    monkeypatch.setattr(dotenv, 'load_dotenv', lambda *a, **kw: False)

    def no_network(*args, **kwargs):
        pytest.fail('Network is forbidden in synthetic prompt tests')

    monkeypatch.setattr(httpx.Client, 'send', no_network)
    monkeypatch.setattr(httpx.AsyncClient, 'send', no_network)

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from services import db, chat_service as chat, character_service, llm_provider_service as llm
    from services import (care_followup, chat_guest_service, custom_character_service, draft_service,
                          her_story, invite_funnel, lang_guard, live_situation_service, live_talk,
                          marital_arcs, memory_gift, onboarding_demo, scenario_cards, storylines)
    from services.behavior_service import Behavior

    engine = create_engine('sqlite:///' + (tmp_path / 'turn.sqlite').as_posix(),
                           connect_args={'check_same_thread': False})
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    old = db.SessionLocal
    for module in list(sys.modules.values()):
        if (getattr(module, '__name__', '').startswith('services.')
                and getattr(module, 'SessionLocal', None) is old):
            monkeypatch.setattr(module, 'SessionLocal', sessions)
    monkeypatch.setattr(db, 'engine', engine)
    db.Base.metadata.create_all(engine)

    history = established()
    memories = [msg('memory', 'Пользователь сам сказал, что учится играть на гитаре.')]
    monkeypatch.setattr(chat, 'get_recent_messages', lambda *a: history)
    monkeypatch.setattr(chat, 'get_memories', lambda *a: memories)
    monkeypatch.setattr(chat, 'get_character', lambda *a: {'name': 'Тестовая героиня', 'age': 30})
    monkeypatch.setattr(custom_character_service, 'custom_base_character', lambda *a: None)
    monkeypatch.setattr(chat, 'get_test_stage', lambda *a: 'stranger')
    monkeypatch.setattr(chat, 'choose_behavior', lambda *a: Behavior('opinion', 2, 'low', 'нейтрально'))
    monkeypatch.setattr(chat, 'is_premium', lambda *a: False)
    monkeypatch.setattr(chat, '_adult_ok', lambda *a: False)
    monkeypatch.setattr(chat, '_is_card_girl', lambda *a: False)
    monkeypatch.setattr(chat, '_time_context', lambda *a, **kw: '')
    monkeypatch.setattr(chat, '_spawn_background', lambda coro, label: coro.close())
    monkeypatch.setattr(chat, 'softly_evolve_state', lambda *a: None)
    monkeypatch.setattr(chat.anchor_service, 'anchors_block', lambda *a, **kw: '')
    monkeypatch.setattr(character_service, 'voice_samples_block', lambda *a: '')
    monkeypatch.setattr(onboarding_demo, 'maybe_intercept', lambda *a: None)
    monkeypatch.setattr(invite_funnel, 'upsell_due', lambda *a: False)
    monkeypatch.setattr(storylines, 'heat', lambda *a: None)
    for module in (scenario_cards, storylines, marital_arcs):
        monkeypatch.setattr(module, 'direction_for', lambda *a, **kw: '')
    monkeypatch.setattr(marital_arcs, 'caught_note', lambda *a: '')
    monkeypatch.setattr(chat_guest_service, 'get_guest', lambda *a: '')
    monkeypatch.setattr(live_situation_service, 'directive_for', lambda *a: '')
    monkeypatch.setattr(lang_guard, 'detect_lang', lambda *a: 'ru')
    monkeypatch.setattr(lang_guard, 'RU_PURITY_ENABLED', True)
    monkeypatch.setattr(live_talk, 'ENABLED', True)

    hook = Mock(return_value='SYNTHETIC_HOOK: задай ещё вопрос')
    story = Mock(return_value='SYNTHETIC_STORY: начни новую историю')
    care = Mock(return_value=('', ''))
    draft = Mock(return_value=False)
    gift = Mock(return_value=(1, memories[0].content))
    monkeypatch.setattr(chat, 'next_hook', hook)
    monkeypatch.setattr(her_story, 'directive', story)
    monkeypatch.setattr(care_followup, 'directive_for', care)
    monkeypatch.setattr(draft_service, 'will_trigger', draft)
    monkeypatch.setattr(memory_gift, 'is_due', lambda *a: True)
    monkeypatch.setattr(memory_gift, 'pick', gift)
    monkeypatch.setattr(memory_gift, 'directive', lambda text: 'SYNTHETIC_MEMORY: ' + text)
    monkeypatch.setattr(memory_gift, 'mark_used', lambda *a: None)

    calls = []

    async def fake_generate(messages, **kwargs):
        calls.append((copy.deepcopy(messages), kwargs))
        assert kwargs['purpose'] == 'dialogue', 'No additional LLM generation is allowed'
        return llm.LLMResult('Поняла, спасибо за разговор.', 'synthetic', 'synthetic')

    monkeypatch.setattr(chat, 'generate_text', fake_generate)
    monkeypatch.setattr(llm, 'generate_text', fake_generate)

    def run(text, **kwargs):
        answer = asyncio.run(chat.reply(915990, 'Synthetic', text, language_code='ru',
                                        character_id='turn_test_character', **kwargs))
        assert 'спасибо за разговор' in answer
        assert len(calls) == 1, 'Exactly the existing dialogue generation, no extra calls'
        return calls[0][0]

    yield SimpleNamespace(run=run, chat=chat, history=history, memories=memories, calls=calls,
                          hook=hook, story=story, gift=gift, care=care, draft=draft,
                          guests=chat_guest_service, scenarios=scenario_cards, lang=lang_guard)
    engine.dispose()


def guidance_in(messages):
    return [m['content'] for m in messages if m['role'] == 'system' and m['content'].startswith('ХОД ДИАЛОГА')]


def test_actual_prompt_places_guidance_after_hook_rhythm_memory_before_language_user(prompt_env):
    env = prompt_env
    env.history[:] = [msg('assistant', 'Из какого ты города?')]
    messages = env.run('Москва')
    notes = guidance_in(messages)
    assert len(notes) == 1 and 'КОРОТКИЙ ОТВЕТ НА ВОПРОС:' in notes[0]
    assert 'ПЕРВЫЕ 1–3 ХОДА:' in notes[0]
    contents = [m['content'] for m in messages]
    at = contents.index(notes[0])
    assert contents.index(env.hook.return_value) < at
    assert contents.index(env.story.return_value) < at
    assert next(i for i, c in enumerate(contents) if 'он написал совсем коротко' in c) < at
    assert next(i for i, c in enumerate(contents) if c.startswith('SYNTHETIC_MEMORY')) < at
    assert at < contents.index(env.lang.RU_DIRECTIVE) < contents.index('Москва')
    assert env.memories[0].content in contents[0]


@pytest.mark.parametrize('text', ['пока', 'я пойду спать', 'давай позже', 'не пиши пока'])
def test_actual_pause_skips_hooks_story_rhythm_memory_and_draft(prompt_env, text):
    env = prompt_env
    env.draft.return_value = True
    messages = env.run(text)
    assert 'ПАУЗА:' in guidance_in(messages)[0]
    for producer in (env.hook, env.story, env.gift, env.draft):
        producer.assert_not_called()
    assert not any('SYNTHETIC_HOOK' in m['content'] or 'SYNTHETIC_STORY' in m['content']
                   or 'SYNTHETIC_MEMORY' in m['content'] or 'он написал совсем коротко' in m['content']
                   for m in messages)


def test_non_pause_keeps_existing_draft_trigger_without_extra_generation(prompt_env):
    from services import draft_service
    env = prompt_env
    env.draft.return_value = True
    messages = env.run('Не хочу спать')
    env.draft.assert_called_once()
    assert draft_service.trigger_directive() in [m['content'] for m in messages]


@pytest.mark.parametrize('mode', ['scene', 'stored_scene', 'guest', 'care', 'task'])
def test_guidance_only_applies_to_ordinary_dialogue(prompt_env, monkeypatch, mode):
    env = prompt_env
    kwargs = {}
    if mode == 'scene':
        kwargs['scene'] = 'SYNTHETIC_SCENE'
    elif mode == 'stored_scene':
        monkeypatch.setattr(env.scenarios, 'direction_for', lambda *a: 'SYNTHETIC_SCENE')
    elif mode == 'guest':
        monkeypatch.setattr(env.guests, 'get_guest', lambda *a: 'synthetic_guest')
        monkeypatch.setattr(env.guests, 'guest_prompt', lambda *a: 'SYNTHETIC_GUEST')
        monkeypatch.setattr(env.guests, 'character_name', lambda *a: 'Вторая')
    elif mode == 'care':
        env.care.return_value = ('SYNTHETIC_CARE', 'support')
    else:
        from services.behavior_service import Behavior
        monkeypatch.setattr(env.chat, 'choose_behavior', lambda *a: Behavior('task_execute', 10, 'none', 'задача'))
    assert guidance_in(env.run('пока', **kwargs)) == []
    if mode == 'task':
        # Pause suppression must not alter a task whose payload says «пока».
        env.story.assert_called_once()
        env.hook.assert_called_once()


@pytest.mark.parametrize('text', ['не хочу спать', 'пришли фото, потом пойду спать'])
def test_non_pause_does_not_suppress_existing_prompt_producers(prompt_env, text):
    env = prompt_env
    messages = env.run(text)
    assert not any('ПАУЗА:' in n for n in guidance_in(messages))
    env.hook.assert_called_once()
    env.story.assert_called_once()
    env.gift.assert_called_once()


@pytest.mark.parametrize('offer', ['Прислать фото?', 'Оплатить фото за 10 персиков?'])
def test_actual_offer_acceptance_is_not_reinterpreted_as_boredom(prompt_env, offer):
    env = prompt_env
    env.history[:] = [msg('assistant', offer)]
    messages = env.run('ага')
    assert 'ОТВЕТ НА ПРЕДЛОЖЕНИЕ:' in guidance_in(messages)[0]
    assert 'КОРОТКАЯ РЕАКЦИЯ:' not in guidance_in(messages)[0]
    assert any(m == {'role': 'user', 'content': 'ага'} for m in messages)
    env.hook.assert_called_once()


def test_actual_prompt_counts_only_visible_questions_not_thought_or_draft(prompt_env):
    env = prompt_env
    env.history[:] = established() + [
        msg('assistant', 'THOUGHT: HIDDEN_QUESTION?\nMESSAGE: Мне нравится эта мысль.'),
        msg('user', 'ага'),
        msg('assistant', 'DRAFT: HIDDEN_DRAFT?\nMESSAGE: У меня такое тоже бывало.'),
    ]
    messages = env.run('норм')
    assert 'КОРОТКАЯ РЕАКЦИЯ:' in guidance_in(messages)[0]
    assert 'ДВА ВОПРОСА' not in guidance_in(messages)[0]
    assert not any('HIDDEN_' in m['content'] for m in messages)


def test_actual_two_question_prompt_gets_a_no_question_turn(prompt_env):
    env = prompt_env
    env.history[:] = established() + [msg('assistant', 'Любишь кино?'), msg('user', 'Да'),
                                      msg('assistant', 'Какое?')]
    messages = env.run('Не знаю')
    assert 'ДВА ВОПРОСА ПОДРЯД:' in guidance_in(messages)[0]
    assert 'без очередного вопроса' in guidance_in(messages)[0]


def test_actual_prompt_continues_a_delivered_life_event_without_extra_producers(prompt_env):
    env = prompt_env
    from sqlalchemy import select
    from models.app_models import LifeEvent, LifeParticipant, Message
    from services import db, life_experiment as E, memory_service as M
    from services.user_service import ensure_user
    uid = ensure_user(915990, 'Synthetic')
    ctx = E.assignment(uid)
    with db.SessionLocal() as s:
        participant = s.scalar(select(LifeParticipant).where(LifeParticipant.user_id == uid))
        participant.variant = 'treatment'
        s.commit()
    ctx.update(variant='treatment', mode_on=False)
    M.save_message(uid, 'turn_test_character', 'assistant',
                   'Пирог подгорел. Спасаем или пицца?', origin='life', life_context=ctx)
    messages = env.run('Давай пиццу')
    notes = [m['content'] for m in messages if m['role'] == 'system' and 'ЕЁ ДЕНЬ' in m['content']]
    assert len(notes) == 1 and 'Пирог подгорел' in notes[0]
    env.hook.assert_not_called()
    env.story.assert_not_called()
    env.gift.assert_not_called()
    with db.SessionLocal() as s:
        rows = s.scalars(select(Message).where(Message.user_id == uid)).all()
        assert any(m.role == 'user' and m.content == 'Давай пиццу' and m.origin == 'user_input'
                   for m in rows)
        event = s.scalar(select(LifeEvent).where(LifeEvent.user_id == uid))
        assert event.reply_count == 1
        # The synthetic answer carries no routing marker: unclear → no revival.
        assert event.scene_status == 'closed'
