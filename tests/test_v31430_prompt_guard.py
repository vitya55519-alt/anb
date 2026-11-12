"""V3.143.0: owner ТЗ (Prompt-Engineering) — no dead ends, no invented facts
about his life, exactly one voice per reply, his gender stated before her
character card, and the generation cut where she starts typing his line."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

from services.character_service import (INITIATIVE_BLOCK, NO_INVENT_BLOCK,
                                        build_system_prompt, get_character,
                                        roleplay_block, stop_sequences,
                                        user_context_block)

ROOT = Path(__file__).resolve().parents[1]
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
LLM = (ROOT / 'services' / 'llm_provider_service.py').read_text(encoding='utf-8')
NAME = get_character('anna_01')['name']


def _prompt(**kw):
    return build_system_prompt(get_character('anna_01'), 'REL', [], character_id='anna_01', **kw)


# ── 1. [USER CONTEXT] leads the prompt ───────────────────────────────────────

def test_he_is_named_before_her_character_card():
    t = _prompt(user_name='Виктор')
    assert t.startswith('[USER CONTEXT]')
    assert 'User Gender: Male (Мужчина)' in t
    assert 'Твоя задача — обращаться к пользователю строго в мужском роде. ' \
           'Никогда не путай пол пользователя.' in t
    assert 'Имя пользователя: Виктор' in t
    assert t.index('[USER CONTEXT]') < t.index(f'Ты — {NAME}')


def test_the_gender_follows_the_account_not_a_guess():
    t = _prompt(user_gender='female')
    assert 'User Gender: Female (Женщина)' in t
    assert 'обращаться к пользователю строго в женском роде' in t
    assert 'в мужском роде' not in user_context_block(user_gender='female')
    assert 'Имя пользователя' not in user_context_block('')


# ── 2. [ROLEPLAY INSTRUCTIONS]: one character, never his voice ───────────────

def test_solo_she_is_one_person_and_never_him():
    t = _prompt()
    assert t.index('[ROLEPLAY INSTRUCTIONS]') < t.index(f'Ты — {NAME}')
    assert 'Ты отыгрываешь роль ТОЛЬКО ОДНОГО персонажа' in t
    assert f'Твоё текущее имя: {NAME}' in t
    assert 'ЗАПРЕЩЕНО генерировать реплики от лица пользователя или других девушек' in t
    assert 'Отвечай только от своего лица' in t
    assert 'Не пиши своё имя в начале реплики' in t


def test_duo_mode_keeps_the_names_it_needs():
    # the invited girl is only readable through her name at the line start,
    # so the solo ban on signatures must not reach a duo chat
    t = _prompt(duo=True)
    assert 'ТОЛЬКО ОДНОГО персонажа' not in t
    assert 'Не пиши своё имя в начале реплики' not in t
    assert 'В этом чате две девушки' in t
    assert f'«{NAME}: …»' in t
    assert 'ЗАПРЕЩЕНО генерировать реплики от лица пользователя' in roleplay_block(NAME, duo=True)


# ── 3. initiative and hooks ─────────────────────────────────────────────────

def test_every_reply_leaves_a_hook_and_never_a_dead_end():
    t = _prompt()
    assert INITIATIVE_BLOCK in t
    assert '[ДИАЛОГОВАЯ ИНИЦИАТИВА И КРЮЧКИ]' in t
    assert 'Никогда не заканчивай сообщение голым описанием действия' in t
    assert 'разденешь меня или заставишь ждать?' in t
    assert 'развивай сцену на один шаг вперёд' in t
    for short in ('«да»', '«не знаю»', '«круто»', '«окей»'):
        assert short in t


# ── 4. nothing invented about his life ───────────────────────────────────────

def test_she_never_invents_his_life():
    t = _prompt()
    assert NO_INVENT_BLOCK in t
    assert 'СТРОГО ЗАПРЕЩЕНО выдумывать факты из реальной жизни пользователя' in t
    assert 'НИКОГДА не генерируй события, о которых он не упоминал' in t
    assert 'спроси его самого' in t


# ── 5. stop sequences + sampling ─────────────────────────────────────────────

def test_stop_list_names_him_not_her():
    stops = stop_sequences('Виктор')
    assert stops[:2] == ['User:', 'Пользователь:']
    assert 'Виктор:' in stops
    # a bare name would cut a normal sentence that only mentions him, and in a
    # duo chat her own name opens every line
    assert 'Виктор' not in stops
    assert NAME not in stops
    assert stop_sequences('') == ['User:', 'Пользователь:']
    assert '\n' not in ''.join(stop_sequences('Виктор\nвторое имя'))


def _fake_llm(monkeypatch):
    from services import llm_provider_service as L
    seen = {}

    async def mm_create(**k):
        seen.update(k)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='а ты что будешь?'),
                                     finish_reason='stop')],
            usage=None)

    monkeypatch.setattr(L, '_minimax', SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=mm_create))))
    monkeypatch.setattr(L, '_gemini', None, raising=False)
    monkeypatch.setattr(L, '_openrouter', None, raising=False)
    return seen


def test_the_stop_list_reaches_the_provider(monkeypatch):
    from services import llm_provider_service as L
    seen = _fake_llm(monkeypatch)
    asyncio.run(L.generate_text([{'role': 'user', 'content': 'x'}], max_tokens=90, temperature=0.8,
                                purpose='dialogue', stop=['User:', 'Виктор:']))
    assert seen['stop'] == ['User:', 'Виктор:'] and seen['temperature'] == 0.8


def test_chat_writes_get_generic_stops_even_without_the_caller(monkeypatch):
    from services import llm_provider_service as L
    seen = _fake_llm(monkeypatch)
    asyncio.run(L.generate_text([{'role': 'user', 'content': 'x'}], max_tokens=90, purpose='proactive'))
    assert seen['stop'] == ['User:', 'Пользователь:']
    seen.clear()
    asyncio.run(L.generate_text([{'role': 'user', 'content': 'x'}], max_tokens=90, purpose='life_event'))
    assert 'stop' not in seen


def test_dialogue_sampling_wired_in_the_chat_pipeline():
    assert "stops = stop_sequences(user_name)" in CHAT
    assert "purpose='dialogue', stop=stops" in CHAT
    assert 'stop=stop_sequences(user_name)' in CHAT
    assert CHAT.count('user_name=user_name') == 4
    assert "user_name=user_name, duo=duo_chat" in CHAT
    assert "mm_kwargs['stop'] = stop" in LLM
    assert "kwargs['stop'] = stop" in LLM
    assert "**({'stop': stop} if stop else {})" in LLM
    assert "temperature=temperature," in LLM[LLM.index('# ── 2. Gemini'):LLM.index('# ── 3. OpenRouter')]
