import asyncio
from types import SimpleNamespace

import pytest

from services import chat_service as chat
from services import draft_service, llm_provider_service as llm


@pytest.mark.parametrize('purpose', ['dialogue', 'life_event', 'proactive', 'rewrite'])
def test_m3_disables_thinking_without_changing_model(monkeypatch, purpose):
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content='Готовый ответ'), finish_reason='stop')], usage=None)

    monkeypatch.setattr(llm, '_minimax', SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create))))
    monkeypatch.setattr(llm, 'MINIMAX_MODEL', 'MiniMax-M3')
    monkeypatch.setattr(llm, 'MINIMAX_DIALOGUE_MODEL', 'MiniMax-M3')
    monkeypatch.setattr(llm.spend_service, 'llm_aux_allowed', lambda: True)
    result = asyncio.run(llm.generate_text(
        [{'role': 'user', 'content': 'Привет'}], max_tokens=320, purpose=purpose))
    assert result.text == 'Готовый ответ'
    assert calls[0]['model'] == 'MiniMax-M3'
    assert calls[0]['extra_body'] == {'thinking': {'type': 'disabled'}}
    assert calls[0]['max_tokens'] == 320
    assert 'reasoning_effort' not in calls[0]


def test_retry_does_not_reenable_thinking(monkeypatch):
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content='' if len(calls) == 1 else 'Ответ'),
            finish_reason='length' if len(calls) == 1 else 'stop')], usage=None)

    monkeypatch.setattr(llm, '_minimax', SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create))))
    monkeypatch.setattr(llm, 'MINIMAX_DIALOGUE_MODEL', 'MiniMax-M3')
    monkeypatch.setattr(llm, 'LLM_RETRY_PAUSE_SECONDS', 0)
    result = asyncio.run(llm.generate_text(
        [{'role': 'user', 'content': 'Привет'}], max_tokens=320))
    assert result.text == 'Ответ'
    assert len(calls) == 2
    for call in calls:
        assert call['extra_body']['thinking']['type'] == 'disabled'
        assert call['max_tokens'] == 320
        assert 'reasoning_effort' not in call


def test_flash_override_is_not_silently_replaced(monkeypatch):
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content='Ответ'), finish_reason='stop')], usage=None)

    monkeypatch.setattr(llm, '_minimax', SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create))))
    monkeypatch.setattr(llm, 'MINIMAX_DIALOGUE_MODEL', 'MiniMax-M3.1-Flash')
    asyncio.run(llm.generate_text([{'role': 'user', 'content': 'Привет'}], max_tokens=320))
    assert calls[0]['model'] == 'MiniMax-M3.1-Flash'
    assert 'extra_body' not in calls[0]
    assert calls[0]['reasoning_effort'] == 'low'
    assert llm.provider_status()['dialogue_thinking_disabled'] is False


@pytest.mark.parametrize('raw', [
    'THOUGHT: скрытый монолог', 'THOUGHT: скрытый монолог\nMESSAGE:',
    'DRAFT: платный текст\nMESSAGE:', 'DRAFT: платный текст',
])
def test_incomplete_format_never_leaks_private_blocks(raw):
    assert chat.message_block(raw) == ''


def test_plain_reply_and_stored_reply_have_only_visible_words():
    assert chat.message_block('Обычный ответ') == 'Обычный ответ'
    assert chat.message_block('THOUGHT: монолог\nDRAFT: платно\nMESSAGE: Привет') == 'Привет'


def test_prompt_does_not_request_a_monologue():
    for level in (1, 4, 8):
        prompt = chat.novel_engine_context(level, 'mar_married')
        assert 'THOUGHT' not in prompt
        assert '40–70' not in prompt
    assert 'THOUGHT:' not in chat.novel_format_suffix()
    assert 'THOUGHT' not in draft_service.DRAFT_FORMAT_SUFFIX
    assert 'DRAFT:' in draft_service.DRAFT_FORMAT_SUFFIX
    assert 'MESSAGE:' in draft_service.DRAFT_FORMAT_SUFFIX


def test_many_short_messages_still_have_a_count_limit():
    history = [{'role': 'assistant' if i % 2 else 'user', 'content': str(i)}
               for i in range(100)]
    result = chat._cap_history_tail(history)
    assert result == history[-20:]


def test_oversized_current_message_does_not_keep_old_history(monkeypatch):
    monkeypatch.setattr(chat, 'LLM_HISTORY_TAIL_CHARS', 1000)
    current = {'role': 'user', 'content': 'я' * 2000}
    result = chat._cap_history_tail([
        {'role': 'system', 'content': 'Правила'},
        {'role': 'assistant', 'content': 'Старая реплика'}, current,
        {'role': 'system', 'content': 'Формат'}])
    assert current in result
    assert [m for m in result if m['role'] != 'system'] == [current]
    assert [m['content'] for m in result if m['role'] == 'system'] == ['Правила', 'Формат']
