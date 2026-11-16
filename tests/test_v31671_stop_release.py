"""V3.167.1 — СРОЧНЫЙ ХОТФИКС «Стоп по новым релизам», пункты 1 и 2.

Про цепочку (владелец, Q1/Q2): «Gemini вырубаем совсем… Выпиливай и OpenRouter,
и Gemini. В цепочке остается ТОЛЬКО официальный прямой MiniMax. Если он падает
после ретрая — сразу срабатывает наша нейтральная заглушка про связь» и
«подними общий лимит на ход до 90 секунд. Схема: Прямой MiniMax (30с) ->
авто-повтор MiniMax (30с) -> если глухо, отдаем текст-заглушку».

Про заглушку: «нейтральная фраза "Секунду, связь подвисла… Напиши ещё раз ❤️"
без сохранения в БД — это идеальный вариант».
"""
import asyncio
import logging
import time
from pathlib import Path
from types import SimpleNamespace

import services.chat_service as cs
import services.llm_provider_service as llm
from services.chat_service import STUB_REPLY_EN, STUB_REPLY_RU
from services.llm_provider_service import LLMResult
from services.memory_service import save_message
from services.user_service import ensure_user

logging.getLogger('services.llm_provider_service').setLevel(logging.CRITICAL)
logging.getLogger('services.chat_service').setLevel(logging.CRITICAL)

ROOT = Path(cs.__file__).resolve().parent.parent
CONFIG = open(ROOT / 'config.py', encoding='utf-8').read()
LLM_SRC = open(llm.__file__, encoding='utf-8').read()
CHAT = open(cs.__file__, encoding='utf-8').read()
ENV = open(ROOT / '.env.example', encoding='utf-8').read()


def _resp(text: str, finish: str = 'stop'):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=finish)],
        usage=None,
    )


class _Recorder:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.at = []

    async def create(self, **kwargs):
        self.at.append(time.monotonic())
        self.calls.append(kwargs)
        out = self.outcomes[min(len(self.calls) - 1, len(self.outcomes) - 1)]
        if isinstance(out, BaseException):
            raise out
        return out

    @property
    def chat(self):
        return SimpleNamespace(completions=self)


# ── 1. в цепочке остался только прямой MiniMax ────────────────────────

def test_the_aggregator_is_gone_from_config_and_code():
    assert 'OPENROUTER_API_KEY' not in CONFIG
    assert 'OPENROUTER_BASE_URL' not in CONFIG
    assert 'OPENROUTER_MODEL' not in CONFIG
    assert 'OPENEROUTER_API_KEY' not in CONFIG
    assert '_openrouter' not in LLM_SRC
    assert 'LLM_FALLBACK_TIMEOUT_SECONDS' not in LLM_SRC


def test_the_direct_minimax_endpoint_and_a_bare_model_name():
    assert 'MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.io/v1")' in CONFIG
    assert 'MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-M3")' in CONFIG
    # «minimax/minimax-m3» — это id агрегатора: с ним прямой endpoint отвечает 404.
    assert '/' not in llm.MINIMAX_MODEL


def test_gemini_reads_photos_only_and_never_her_words():
    assert llm.VISION_PURPOSES == frozenset({'photo_reaction', 'evening_photo_qc'})
    assert 'if _minimax and purpose not in VISION_PURPOSES:' in LLM_SRC
    assert 'if purpose in VISION_PURPOSES:' in LLM_SRC


def test_provider_status_describes_the_new_shape():
    st = llm.provider_status()
    assert st['minimax_attempts'] == 2
    assert st['turn_budget_seconds'] == 90.0
    assert st['minimax_timeout_seconds'] == 30.0
    assert st['retry_pause_seconds'] == 1.5
    assert 'openrouter' not in str(st).lower()


def test_env_example_tells_the_owner_the_chat_key_is_minimax():
    assert 'MINIMAX_API_KEY' in ENV
    assert 'OPENROUTER_API_KEY=' not in ENV


# ── 2. схема хода: попытка, пауза, авто-повтор, заглушка ──────────────

def test_two_attempts_are_split_by_the_pause(monkeypatch):
    mm = _Recorder([_resp('', 'length'), _resp('да, приезжай 🙈')])
    monkeypatch.setattr(llm, '_minimax', mm)
    monkeypatch.setattr(llm, '_gemini', None)
    monkeypatch.setattr(llm, 'LLM_RETRY_PAUSE_SECONDS', 0.25)
    out = asyncio.run(llm.generate_text([{'role': 'user', 'content': 'x'}],
                                        max_tokens=40, purpose='dialogue'))
    assert out.text == 'да, приезжай 🙈' and out.provider == 'minimax'
    assert len(mm.calls) == 2
    assert mm.at[1] - mm.at[0] >= 0.2, 'повтор идёт через паузу, не влёт'


def test_both_attempts_silent_raise_once_for_the_turn_to_take(monkeypatch):
    mm = _Recorder([_resp('', 'length'), _resp('', 'length')])
    monkeypatch.setattr(llm, '_minimax', mm)
    monkeypatch.setattr(llm, '_gemini', None)
    monkeypatch.setattr(llm, 'LLM_RETRY_PAUSE_SECONDS', 0.0)
    out = asyncio.run(llm.generate_text([{'role': 'user', 'content': 'x'}],
                                        max_tokens=40, purpose='dialogue'))
    assert out.text == '' and 'empty text' in out.error


def test_the_whole_turn_never_waits_more_than_the_budget(monkeypatch):
    async def hang(**kwargs):
        await asyncio.sleep(30)
        return _resp('не дойдёт')

    mm = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=hang)))
    monkeypatch.setattr(llm, '_minimax', mm)
    monkeypatch.setattr(llm, '_gemini', None)
    monkeypatch.setattr(llm, 'LLM_TIMEOUT_SECONDS', 30.0)
    monkeypatch.setattr(llm, 'LLM_CHAIN_BUDGET_SECONDS', 2.0)
    monkeypatch.setattr(llm, 'LLM_RETRY_PAUSE_SECONDS', 0.0)
    started = time.monotonic()
    try:
        asyncio.run(llm.generate_text([{'role': 'user', 'content': 'x'}], max_tokens=40))
        raised = ''
    except RuntimeError as exc:
        raised = str(exc)
    waited = time.monotonic() - started
    assert waited < 5.0, f'ход ждал {waited:.1f} с'
    assert 'TimeoutError' in raised and 'turn budget' in raised, raised


# ── 3. заглушка: одна, нейтральная, в диалог не пишется ───────────────

def test_the_stub_is_the_approved_line_verbatim():
    assert STUB_REPLY_RU == 'Секунду, связь подвисла… Напиши ещё раз ❤️'
    assert cs.stub_reply('ru') == STUB_REPLY_RU
    assert cs.stub_reply('en') == STUB_REPLY_EN
    assert cs.stub_reply('') == STUB_REPLY_RU


def test_the_old_excuse_pool_is_not_delivered_any_more():
    # живые фразы-оправошники из пула больше не производятся: в коде от них
    # остался только фильтр legacy-истории.
    assert 'STALL_LINES_RU' not in CHAT
    assert 'def stall_line(' not in CHAT
    assert 'def is_stall_line(' in CHAT


def _seed(tid: int, name: str) -> int:
    uid = ensure_user(tid, name, language_code='ru')
    for i in range(8):
        save_message(uid, 'anna_01', 'user', f'привет {i}')
    return uid


def _silent(monkeypatch):
    async def fake(messages, **kw):
        return LLMResult('', 'minimax', 'MiniMax-M3', True, 'MiniMax(MiniMax-M3): TimeoutError')

    monkeypatch.setattr(cs, 'generate_text', fake)


def _counters(monkeypatch):
    hits = {'daily': 0, 'series': 0, 'gift': 0, 'interrupt': 0}

    from services import daily_limit, gift_shop_service, interrupt_service, series_reward

    def _daily(*a, **kw):
        hits['daily'] += 1
        return None

    def _series(*a, **kw):
        hits['series'] += 1
        return None

    def _gift(*a, **kw):
        hits['gift'] += 1

    def _interrupt(*a, **kw):
        hits['interrupt'] += 1

    monkeypatch.setattr(daily_limit, 'note_message', _daily)
    monkeypatch.setattr(series_reward, 'note_his_message', _series)
    monkeypatch.setattr(gift_shop_service, 'tick', _gift)
    monkeypatch.setattr(interrupt_service, 'note_turn', _interrupt)
    return hits


def test_a_stalled_turn_burns_nothing(monkeypatch):
    tid = 559201
    _seed(tid, 'stalledcounter')
    _silent(monkeypatch)
    hits = _counters(monkeypatch)
    answer = asyncio.run(cs.reply(tid, 'stalledcounter', 'ты там?', language_code='ru'))
    assert answer == STUB_REPLY_RU
    assert hits == {'daily': 0, 'series': 0, 'gift': 0, 'interrupt': 0}, \
        'заглушка не тратит лимит дня, серию, подарок и перебивку'


def test_a_live_turn_still_burns_them(monkeypatch):
    tid = 559202
    _seed(tid, 'liveturn')

    async def fake(messages, **kw):
        return LLMResult('да, я тут 🙈', 'minimax', 'MiniMax-M3', True)

    monkeypatch.setattr(cs, 'generate_text', fake)
    hits = _counters(monkeypatch)
    answer = asyncio.run(cs.reply(tid, 'liveturn', 'ты там?', language_code='ru'))
    assert 'тут' in answer
    assert hits['daily'] == 1 and hits['series'] == 1 and hits['gift'] == 1
