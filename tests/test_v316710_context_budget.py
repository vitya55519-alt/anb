"""V3.167.10 (его ТЗ на хотфикс от 16.11): «в логе sent 30.3k — обрезки истории
нет, обрежь хвост до 20–30 сообщений / 3000–4000 токенов».

Замер по проду оказался важнее догадки, и он же задал границы релиза:

* хвост переписки обрезался и до нас — 16 реплик (Premium — 30), и по дампу
  16.11 это 7% запроса: 1.7k знаков из 25.9k на самой тяжёлой живой переписке.
  80% запроса — стоячая простыня правил, 13% — служебные вставки хода. Знаковый
  потолок ниже (его цифра — 4000) нужен самым длинным чатам: у 1% хвост весит
  больше 3.3k, у худшего — 7.5k;
* «sent 30.3k» — это ЗНАКИ, а не токены: по prod-журналу llm_usage один токен
  ≈ 2.4 знака, то есть 30.3k знаков — около 12.6k токенов. В причине падения
  теперь обе величины, чтобы «k» больше не читалось как тысячи токенов;
* RuntimeError в его логе — это текст ПРИЧИНЫ, которая приходит владельцу в
  личку, а не падение насквозь: и в Mini App, и в боте ход перехвачен и отдан
  той самой строкой «Секунду, связь подвисла… Напиши ещё раз ❤️».
"""
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

import services.chat_service as cs
import services.llm_provider_service as llm

ROOT = Path(__file__).resolve().parents[1]
CHAT_SRC = open(cs.__file__, encoding='utf-8').read()
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
logging.getLogger('services.llm_provider_service').setLevel(logging.CRITICAL)


def _msgs(line_len: int, lines: int):
    """Простыня правил, `lines` реплик хвоста, его сообщение и блок формата."""
    tail = []
    for i in range(lines):
        tail.append({'role': 'user' if i % 2 else 'assistant',
                     'content': ('он: ' if i % 2 else 'она: ') + 'х' * line_len})
    return ([{'role': 'system', 'content': 'ПРАВИЛА'}] + tail
            + [{'role': 'user', 'content': 'привет, ты чем занимаешься?'},
               {'role': 'system', 'content': 'ВАЖНО: ответ строго в два блока'}])


def _window(out):
    """Реплики, которые доехали до движка: между простынёй и блоком формата."""
    return [m for m in out[1:-1] if m['role'] in ('user', 'assistant')]


def test_the_dialogue_tail_is_capped_before_the_call(monkeypatch):
    monkeypatch.setattr(cs, 'LLM_HISTORY_TAIL_CHARS', 1200)
    src = _msgs(60, 20)
    out = cs._cap_history_tail(src)
    assert out[0]['content'] == 'ПРАВИЛА', 'её правила не режутся'
    assert out[-1]['content'].startswith('ВАЖНО'), 'правило формата живёт до конца'
    assert out[-2]['content'].startswith('привет'), 'его сообщение не режется'
    lines = [m['content'] for m in src if m['role'] in ('user', 'assistant')]
    kept = [m['content'] for m in _window(out)]
    assert len(kept) < len(lines), f'хвост не укоротился: {len(kept)} из {len(lines)}'
    assert kept == lines[-len(kept):], 'остался новый конец, а не выкидыши из середины'
    assert sum(len(k) for k in kept) <= 1200, sum(len(k) for k in kept)
    assert [m['role'] for m in out].count('system') == 2


def test_a_chat_inside_the_budget_is_not_touched(monkeypatch):
    monkeypatch.setattr(cs, 'LLM_HISTORY_TAIL_CHARS', 4000)
    src = _msgs(40, 6)
    assert cs._cap_history_tail(src) is src, 'короткий диалог не перечитывается'


def test_the_last_lines_cannot_bypass_the_cap(monkeypatch):
    monkeypatch.setattr(cs, 'LLM_HISTORY_TAIL_CHARS', 1000)
    out = cs._cap_history_tail(_msgs(506, 20))
    assert len(_window(out)) == 2
    assert sum(len(m['content']) for m in _window(out)) <= 1000


def test_the_char_cap_is_an_env_lever():
    assert "os.getenv('LLM_HISTORY_TAIL_CHARS', '4000')" in CHAT_SRC
    assert 'messages = _cap_history_tail(messages)' in CHAT_SRC.split('r = await _gen(messages')[0], \
        'потолок стоит до обращения к движку'


def test_the_reason_carries_both_signs_and_tokens(monkeypatch):
    class _Hang:
        async def create(self, **kwargs):
            await asyncio.sleep(5)

        @property
        def chat(self):
            return SimpleNamespace(completions=self)

    monkeypatch.setattr(llm, '_minimax', _Hang())
    monkeypatch.setattr(llm, '_gemini', None)
    monkeypatch.setattr(llm, 'LLM_RETRY_PAUSE_SECONDS', 0.0)
    monkeypatch.setattr(llm, 'LLM_SLICE_GUARD_SECONDS', 0.0)
    monkeypatch.setattr(llm, 'LLM_DIALOGUE_TIMEOUT_SECONDS', 0.05)
    monkeypatch.setattr(llm, 'LLM_RETRY_TIMEOUT_SECONDS', 0.05)
    monkeypatch.setattr(llm, 'LLM_CHAIN_BUDGET_SECONDS', 90.0)
    big = [{'role': 'system', 'content': 'х' * 6000} for _ in range(5)]
    # глохнут обе попытки диалога — это тот самый raise, чью строку он и прочитал
    with pytest.raises(RuntimeError) as got:
        asyncio.run(llm.generate_text(big, max_tokens=40, purpose='dialogue'))
    reason = str(got.value)
    assert 'LLM unavailable' in reason, reason[:220]
    assert '30.0k знаков' in reason, reason[:220]
    assert '≈12k токенов' in reason, reason[:220]
    assert 'sent' in reason, reason[:220]


def test_the_history_window_is_still_measured_in_lines():
    assert 'get_recent_messages(db_user_id, character_id, 30 if premium else 16)' in CHAT_SRC


def test_his_stub_line_is_the_one_on_both_platforms():
    assert cs.STUB_REPLY_RU == 'Секунду, связь подвисла… Напиши ещё раз ❤️'
    turn = MAIN[MAIN.index('async def _webapp_chat_turn'):]
    handler = turn[:turn.index('\nasync def ')]
    assert 'except Exception as exc:' in handler, 'ход в Mini App обязан ловить любое падение'
    assert 'stub_reply(' in handler, 'вместо тишины — её ответ-оправдание'
    assert "answer, thought, draft = stub_reply(stub_lang), '', ''" in CHAT_SRC, \
        'пустая цепочка в боте даёт ту же строку'
