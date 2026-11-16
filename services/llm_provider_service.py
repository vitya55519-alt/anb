from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass

from openai import AsyncOpenAI

from config import (
    GEMINI_API_KEY, GEMINI_API_KEY_VALID, GEMINI_CHAT_MODEL, GEMINI_OPENAI_BASE_URL,
    MINIMAX_API_KEY, MINIMAX_BASE_URL, MINIMAX_MODEL, MINIMAX_DIALOGUE_MODEL,
)
from services import spend_service

logger = logging.getLogger(__name__)


def _safe(s: str) -> str:
    """Make string safe for ASCII-only log outputs."""
    try:
        return s.encode('ascii', errors='replace').decode('ascii')
    except Exception:
        return repr(s)


def _record_usage(purpose: str, provider: str, model: str, response) -> None:
    """V3.44.18: the usage block used to be discarded — the bot literally could
    not tell its owner what a reply cost. When the provider puts a real bill in
    its usage block we store that; otherwise we price the tokens ourselves."""
    usage = getattr(response, 'usage', None)
    if usage is None:
        return
    prompt_tokens = int(getattr(usage, 'prompt_tokens', 0) or 0)
    completion_tokens = int(getattr(usage, 'completion_tokens', 0) or 0)
    details = getattr(usage, 'completion_tokens_details', None)
    reasoning_tokens = int(getattr(details, 'reasoning_tokens', 0) or 0) if details else 0
    # some providers put their own bill into the usage object as an extra field
    reported = None
    extra = getattr(usage, 'model_extra', None) or {}
    for key in ('cost', 'total_cost'):
        raw = extra.get(key) if isinstance(extra, dict) else None
        if raw is None and hasattr(usage, key):
            raw = getattr(usage, key, None)
        if raw is not None:
            try:
                reported = float(raw)
                break
            except (TypeError, ValueError):
                continue
    spend_service.record_llm_usage(
        purpose, provider, model,
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        reasoning_tokens=reasoning_tokens, cost_usd=reported,
    )
    logger.info(
        'LLM SPEND purpose=%s provider=%s in=%d out=%d reasoning=%d cost=%s',
        purpose, provider, prompt_tokens, completion_tokens, reasoning_tokens,
        f'${reported:.5f} (billed)' if reported is not None else 'estimated',
    )

# V3.57.8: explicit timeouts. The OpenAI SDK default is a 600 s read timeout
# with 2 automatic retries, so a hung provider kept the user waiting for
# minutes. Every client now fails fast with no SDK retries — the retry below is
# ours, bounded and visible in the log.
def _env_float(name: str, default: float) -> float:
    try:
        return max(5.0, min(120.0, float(os.getenv(name, default))))
    except (TypeError, ValueError):
        return default


LLM_TIMEOUT_SECONDS = _env_float('LLM_TIMEOUT_SECONDS', 30.0)

# V3.167.1 (владелец, 16.11): в цепочке остался ОДИН провайдер — прямой MiniMax,
# поэтому схема хода теперь такая: запрос (30 с) → авто-повтор через паузу (30 с)
# → глухо, и ход отдаёт нейтральную заглушку про связь. Общий бюджет 90 с держит
# весь ход, третьей попытки нет: она только удлиняла «печатает…».
LLM_CHAIN_BUDGET_SECONDS = _env_float('LLM_CHAIN_BUDGET_SECONDS', 90.0)
LLM_RETRY_PAUSE_SECONDS = max(0.0, min(10.0, float(os.getenv('LLM_RETRY_PAUSE_SECONDS', '1.5'))))
# V3.167.3: повтор — единственная попытка, которая в его сигнале упёрлась в
# таймаут (30 с). Первая уже провалена, поэтому повтору даётся чуть больше
# времени, но в пределах тех же 90 с на весь ход: 30 + пауза + 40. Ровно его
# схема обратно — LLM_RETRY_TIMEOUT_SECONDS=30 в Railway.
LLM_RETRY_TIMEOUT_SECONDS = _env_float('LLM_RETRY_TIMEOUT_SECONDS', 40.0)
# V3.167.4 (владелец, «сделай так, чтобы общалась»): диалог ждёт дольше
# вспомогательных вызовов — его читает человек, а не планировщик. 40 + 2 + 1.5
# + 40 + 2 = 85.5 с, в его же бюджете 90 с. Остальные purposes сидят на 30 с.
LLM_DIALOGUE_TIMEOUT_SECONDS = _env_float('LLM_DIALOGUE_TIMEOUT_SECONDS', 40.0)
# Страховка поверх среза: коннект и разбор ответа SDK. Наружный wait_for без
# неё мог бы снять попытку раньше, чем таймаут провайдера успел сработать.
LLM_SLICE_GUARD_SECONDS = _env_float('LLM_SLICE_GUARD_SECONDS', 2.0)
MINIMAX_ATTEMPTS = 2
MIN_PROVIDER_SLICE_SECONDS = 3.0
# Знаков на один токен в русском промпте — по prod-журналу llm_usage (дампы
# 05–16.11): 5.8k–10.5k токенов входа при 14k–26k знаков. Нужно, чтобы «k» в
# причине падения больше не читалось как тысячи токенов.
_CHARS_PER_TOKEN = 2.4

# V3.63.4: reasoning tokens MiniMax may spend before the visible answer.
MINIMAX_REASONING_HEADROOM = max(0, int(os.getenv('MINIMAX_REASONING_HEADROOM', '512')))
# V3.64.8: for the one-liners she sends first M3 often thinks ~600 tokens and
# came back EMPTY every other time; those calls get more room.
_MINIMAX_HEADROOM_BY_PURPOSE = {'life_event': 1200, 'proactive': 1200}
# V3.97.0: dialogue replies got EMPTY with out=reasoning=832 (320 + 512):
# more room for the thinking up front, and one retry with a lot more room.
_MINIMAX_HEADROOM_BY_PURPOSE['dialogue'] = max(0, int(os.getenv('MINIMAX_DIALOGUE_HEADROOM', '1024')))
MINIMAX_EMPTY_RETRY_HEADROOM = max(512, int(os.getenv('MINIMAX_EMPTY_RETRY_HEADROOM', '2400')))
RETRY_EMPTY_PURPOSES = frozenset({'dialogue'})
# V3.167.9 (владелец 16.11, «мыслей нет, общение падает»): пустой ответ M3 в логах
# — это thinking, съевший весь лимит: модель думает, видимого текста нет, и вторая
# попытка с тем же усилием думала ровно так же. Авто-повтор в диалоге теперь просит
# низкую глубину размышления (reasoning_effort — параметр OpenAI SDK с v2, его
# принимают и MiniMax-M3, и M3.1-Flash; модель та же) и больше места под ответ.
MINIMAX_RETRY_EFFORT = os.getenv('MINIMAX_RETRY_EFFORT', 'low').strip()
# V3.167.3 (владелец, 16.11, сигнал «🛑 ход чата: провайдеры молчат: ask: empty
# text (finish=length); retry: TimeoutError»): первая попытка в диалоге и так
# уходила в молчание — thinking съедал весь лимит и видимого текста не оставалось
# (finish=length на пустом ответе), а повтор бился в свой таймаут. Раз low усилие
# спасает повтор, та же глубина теперь просится и на первую попытку диалога:
# модель та же, меняется только то, сколько она думает до ответа. Пусто в env —
# вернуть прежнее поведение без правки кода (MINIMAX_DIALOGUE_EFFORT=).
MINIMAX_DIALOGUE_EFFORT = os.getenv('MINIMAX_DIALOGUE_EFFORT', 'low').strip()
# V3.143.0: owner ТЗ — she sometimes kept writing after his turn («User: …») and
# sent a dialogue where she answered for both. Every call that produces a chat
# message is cut at these markers; the caller adds the client's own name.
DEFAULT_STOP = ('User:', 'Пользователь:')
STOP_PURPOSES = frozenset({'dialogue', 'proactive', 'rewrite'})
STOP_MAX = 4
# V3.64.8: Gemini 3.x counts its hidden thinking inside max_tokens too, so a
# 90-token life moment came back as 2–4 words («Надела сегодня тот»).
GEMINI_REASONING_HEADROOM = max(0, int(os.getenv('GEMINI_REASONING_HEADROOM', '512')))

# ── Provider clients ───────────────────────────────────────────────────
# V3.167.1 (владелец): текст пишет только официальный прямой MiniMax — свой ключ,
# свой endpoint (api.minimax.io), имя модели без слеша. Чат-агрегатор выпилен:
# его лег в проде отвечал ровно 401 («Invalid API key»), потому что тот же ключ
# лежал в его переменной, а model id «minimax/minimax-m3» — его, не MiniMax.
_minimax = (
    AsyncOpenAI(api_key=MINIMAX_API_KEY, base_url=MINIMAX_BASE_URL,
                # V3.167.4: дефолт клиента — самый длинный срез, какой вообще
                # просим. Раньше тут стояло 30 с, и он молча перебивал срез
                # повтора: тот умирал на 30.1 с с APITimeoutError. Каждый вызов
                # теперь приносит свой timeout сам.
                timeout=max(LLM_TIMEOUT_SECONDS, LLM_DIALOGUE_TIMEOUT_SECONDS,
                            LLM_RETRY_TIMEOUT_SECONDS) + LLM_SLICE_GUARD_SECONDS,
                max_retries=0)
    if MINIMAX_API_KEY else None
)
# Gemini из диалога убран (429 на каждую вторую реплику). Он остался ровно там,
# где у MiniMax нет глаз: два vision-вызова — её реакция на присланное фото и
# приёмка вечернего кадра. Ни один текстовый ход через него не идёт.
_gemini = (
    AsyncOpenAI(api_key=GEMINI_API_KEY, base_url=GEMINI_OPENAI_BASE_URL,
                timeout=LLM_TIMEOUT_SECONDS, max_retries=0)
    if GEMINI_API_KEY_VALID else None
)

logger.info(
    'LLM providers: MiniMax=%s model=%s base=%s | Gemini vision=%s model=%s',
    'READY' if _minimax else 'NO KEY',
    MINIMAX_MODEL,
    MINIMAX_BASE_URL,
    'READY' if _gemini else 'NO KEY',
    GEMINI_CHAT_MODEL,
)


# V3.96.0: calls that carry an image part. V3.167.1: эти два вызова — всё, что
# у MiniMax просить нельзя (его чат-модели читают только текст), поэтому они и
# только они уходят в Gemini.
VISION_PURPOSES = frozenset({'photo_reaction', 'evening_photo_qc'})


@dataclass(frozen=True)
class LLMResult:
    text: str
    provider: str
    model: str
    # False when the provider stopped on the token cap: the text is cut off.
    complete: bool = True
    # V3.167.9: почему текста нет. Пустой ответ раньше был тихим — ход уходил в
    # запасную фразу, а владелец так и не узнавал, кто именно из провайдеров
    # молчит. Заполнено только на пустом результате.
    error: str = ''


def _complete(r) -> bool:
    try:
        return (r.choices[0].finish_reason or 'stop') != 'length'
    except Exception:
        return True


import re
_THINK_RE = re.compile(r'<think(?:ing)?>.*?</think(?:ing)?>', re.DOTALL | re.IGNORECASE)

_OPEN_THINK_RE = re.compile(r'<think(?:ing)?>.*\Z', re.DOTALL | re.IGNORECASE)
_CLOSE_THINK_RE = re.compile(r'\A.*?</think(?:ing)?>', re.DOTALL | re.IGNORECASE)


def _strip_thinking(text: str) -> str:
    """V3.45: remove / tags that MiniMax/reasoning models leak.
    V3.113.0: also a thinking block cut on the token cap (no closing tag) and
    an answer that starts right after a lone closing tag."""
    text = _THINK_RE.sub('', text or '')
    text = _CLOSE_THINK_RE.sub('', text)
    text = _OPEN_THINK_RE.sub('', text)
    return text.strip()


async def generate_text(
    messages: list[dict],
    *,
    max_tokens: int,
    temperature: float = 0.9,
    purpose: str = 'dialogue',
    stop: list[str] | None = None,
) -> LLMResult:
    """One provider, two attempts: прямой MiniMax → авто-повтор → пусто.

    Raises RuntimeError with the full diagnostic when MiniMax stayed silent on
    both attempts — the chat turn turns that into her neutral «связь подвисла»
    line. Vision calls (VISION_PURPOSES) go to Gemini and never raise.
    """
    errors: list[str] = []
    # V3.167.9: общий бюджет хода. _slice(cap) — сколько секунд осталось на
    # этот запрос. Меньше трёх секунд не просим: с таким таймаутом провайдер
    # ничего не успеет ответить, а ход только упрётся в «печатает…».
    _deadline = time.monotonic() + LLM_CHAIN_BUDGET_SECONDS

    def _left() -> float:
        return _deadline - time.monotonic()

    def _slice(cap: float) -> float:
        return max(1.0, min(cap, _left()))

    def _summary() -> str:
        return '; '.join(errors) if errors else 'no provider configured'

    if stop is None and purpose in STOP_PURPOSES:
        stop = list(DEFAULT_STOP)
    stop = [s for s in (str(x).strip() for x in (stop or [])) if s][:STOP_MAX]

    # V3.44.18: the daily money brake. Only the mechanical helper calls are
    # skipped — the reply the user actually reads always goes through, so the
    # persona degrades (no memory capture, no auto-rewording) instead of dying.
    if purpose in spend_service.AUX_PURPOSES and not spend_service.llm_aux_allowed():
        logger.warning('LLM aux skipped by daily budget purpose=%s', purpose)
        return LLMResult('', 'budget', 'skipped', error='daily budget')

    mm_model = MINIMAX_DIALOGUE_MODEL if purpose == 'dialogue' else MINIMAX_MODEL
    minimax_empty = False
    # ── 1. MiniMax — единственный, кто ей отвечает текстом ────────────
    # V3.96.0: на присланное фото нужны глаза, а чат-модели MiniMax читают только
    # текст, поэтому vision-вызовы идут мимо этой ветки в Gemini.
    if _minimax and purpose not in VISION_PURPOSES:
        mm_kwargs = {}
        if purpose == 'dialogue':
            # V3.63.12: MiniMax's own guidance for chat is temperature 1.0 with
            # top_p 0.95; below that M3 drifts into the same safe phrasing.
            # V3.143.0: the owner asked for 0.7–0.85 anyway — at 1.0 the dead
            # ends and invented facts about his life peaked. top_p stays wide so
            # the wording keeps varying at the lower temperature.
            mm_kwargs['top_p'] = 0.95
            # V3.167.3: думать меньше — с первого запроса, а не только с повтора.
            if MINIMAX_DIALOGUE_EFFORT:
                mm_kwargs['reasoning_effort'] = MINIMAX_DIALOGUE_EFFORT
        if stop:
            mm_kwargs['stop'] = stop
        # V3.63.4: M3 spends its reasoning inside the same answer budget — short
        # calls (life moments, proactive, rewrite, adaptation) came back EMPTY.
        # The thinking gets its own room on top of max_tokens.
        headroom = max(MINIMAX_REASONING_HEADROOM, _MINIMAX_HEADROOM_BY_PURPOSE.get(purpose, 0))
        retry_kwargs = dict(mm_kwargs)
        retry_headroom = headroom
        # V3.97.0: пустой ответ в диалоге — это thinking, съевший весь лимит
        # (out == reasoning == cap в журнале). Повтор просит короткое
        # размышление и даёт под ответ заметно больше места.
        if purpose in RETRY_EMPTY_PURPOSES:
            retry_headroom = MINIMAX_EMPTY_RETRY_HEADROOM
            if MINIMAX_RETRY_EFFORT:
                retry_kwargs['reasoning_effort'] = MINIMAX_RETRY_EFFORT
        # V3.167.4: размер отправленного запроса в причинах — «M3 молчит» и
        # «M3 молчит под промптом в 40 тыс. знаков» для владельца выглядят
        # одинаково, пока не запишешь эту цифру.
        # V3.167.10: цифра была в ЗНАКАХ, и «sent 30.3k» прочиталось как
        # «30 тысяч токенов». По prod-журналу llm_usage 25.9k знаков = 10.5k
        # токенов, то есть один токен ≈ 2.4 знака. Теперь рядом обе величины.
        _chars = sum(len(str(m.get('content') or '')) for m in messages)
        _sent = (f'{_chars / 1000:.1f}k знаков ≈{int(_chars / _CHARS_PER_TOKEN / 1000)}k токенов'
                 if _chars >= 2400 else f'{_chars} знаков')
        for attempt, (tag, kwargs, room) in enumerate((
            ('ask', mm_kwargs, headroom),
            ('retry', retry_kwargs, retry_headroom),
        )[:MINIMAX_ATTEMPTS]):
            if attempt:
                # V3.167.1 (владелец): авто-повтор MiniMax через паузу — та же
                # модель и тот же запрос. Третьей попытки нет: после глухого
                # повтора ход отдаёт нейтральную заглушку про связь.
                if _left() <= MIN_PROVIDER_SLICE_SECONDS:
                    errors.append(f'MiniMax({mm_model}): the turn budget ran out')
                    break
                await asyncio.sleep(LLM_RETRY_PAUSE_SECONDS)
            # V3.167.3: в причину всегда попадает, сколько её ждали — «молчит» и
            # «отвечает 29 секунд и пустой» для владельца выглядят одинаково,
            # пока не запишешь секунды.
            # V3.167.4 (его сигнал 16.11: «ask: TimeoutError [waited 30.0s of
            # 30s]; retry: APITimeoutError [waited 30.1s of 40s]»): повтор умер
            # ровно на 30 с, хотя его срез — 40. Это таймаут КЛИЕНТА
            # (AsyncOpenAI(timeout=30)), а не мой: create() без своего timeout
            # наследует 30 с, и «дать повтору больше времени» значило ровно
            # ничего. Теперь срез уходит и в SDK, и наружу (страховка на
            # коннект), а в причину — ещё размер отправленного запроса:
            # медленный ответ от длинного промпта отличается только этой цифрой.
            slice_seconds = ((LLM_DIALOGUE_TIMEOUT_SECONDS if purpose == 'dialogue' else LLM_TIMEOUT_SECONDS)
                             if not attempt else LLM_RETRY_TIMEOUT_SECONDS)
            _started = time.monotonic()
            try:
                r = await asyncio.wait_for(
                    _minimax.chat.completions.create(
                        model=mm_model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens + room,
                        timeout=slice_seconds,
                        **kwargs,
                    ),
                    timeout=_slice(slice_seconds + LLM_SLICE_GUARD_SECONDS),
                )
            except Exception as exc:
                waited = time.monotonic() - _started
                detail = (f'MiniMax({mm_model}) {tag}: {type(exc).__name__}: {_safe(str(exc))} '
                          f'[waited {waited:.1f}s of {slice_seconds:g}s, sent {_sent}]')
                errors.append(detail)
                logger.warning('MiniMax FAILED purpose=%s %s', purpose, detail)
                continue
            waited = time.monotonic() - _started
            text = _strip_thinking((r.choices[0].message.content or '').strip())
            _record_usage(purpose, 'minimax', mm_model, r)
            if text:
                logger.info('LLM ok provider=minimax model=%s purpose=%s attempt=%s len=%d %.1fs sent=%s',
                            mm_model, purpose, tag, len(text), waited, _sent)
                return LLMResult(text, 'minimax', mm_model, _complete(r))
            # «finish=length» на пустом тексте и есть признак того, что thinking
            # съел весь ответ; без этой строки два молчания в журнале не отличить.
            finish = getattr(r.choices[0], 'finish_reason', '?') if getattr(r, 'choices', None) else '?'
            minimax_empty = True
            errors.append(f'MiniMax({mm_model}) {tag}: empty text (finish={finish}) '
                          f'[waited {waited:.1f}s of {slice_seconds:g}s, sent {_sent}]')
            logger.warning('MiniMax EMPTY purpose=%s attempt=%s finish=%s waited=%.1fs',
                           purpose, tag, finish, waited)

    # ── 2. Gemini vision: the two calls that carry a photo ───────────
    if purpose in VISION_PURPOSES:
        if not _gemini:
            reason = 'no Gemini vision key'
        elif _left() <= MIN_PROVIDER_SLICE_SECONDS:
            reason = 'the turn budget ran out'
        else:
            reason = ''
        if reason:
            errors.append(reason)
            logger.warning('LLM vision skipped purpose=%s %s', purpose, reason)
            return LLMResult('', 'gemini', GEMINI_CHAT_MODEL, True, _summary())
        try:
            r = await asyncio.wait_for(
                _gemini.chat.completions.create(
                    model=GEMINI_CHAT_MODEL,
                    messages=messages,
                    # V3.143.0: the fallback used to ignore the caller's temperature,
                    # so the same reply came back hotter than the one asked for.
                    temperature=temperature,
                    max_tokens=max_tokens + GEMINI_REASONING_HEADROOM,
                    **({'stop': stop} if stop else {}),
                ),
                timeout=_slice(LLM_TIMEOUT_SECONDS),
            )
            text = _strip_thinking((r.choices[0].message.content or '').strip())
            _record_usage(purpose, 'gemini', GEMINI_CHAT_MODEL, r)
            logger.info('LLM ok provider=gemini model=%s purpose=%s len=%d', GEMINI_CHAT_MODEL, purpose, len(text))
            return LLMResult(text, 'gemini', GEMINI_CHAT_MODEL, _complete(r),
                             '' if text else _summary())
        except Exception as exc:
            detail = f'Gemini({GEMINI_CHAT_MODEL}): {type(exc).__name__}: {_safe(str(exc))}'
            errors.append(detail)
            logger.warning('Gemini vision FAILED purpose=%s %s', purpose, detail)
            # Реакция на фото и приёмка кадра — не та реплика, ради которой
            # стоит ронять ход: молчание здесь тоже ответ, и он пустой.
            return LLMResult('', 'gemini', GEMINI_CHAT_MODEL, True, _summary())

    # ── Глухо ─────────────────────────────────────────────────────────
    if minimax_empty:
        # callers already handle an empty answer; keep that, not a crash.
        # V3.167.9: этот путь не raise, поэтому без причины в error ход выглядел
        # как её запасная фраза и никто не знал, кто именно молчит.
        return LLMResult('', 'minimax', mm_model, True, _summary())
    summary = _summary()
    logger.error('LLM SILENT purpose=%s errors=[%s]', purpose, summary)
    raise RuntimeError(f'LLM unavailable: {summary}')


def provider_status() -> dict:
    return {
        'minimax_key_present': bool(MINIMAX_API_KEY),
        'minimax_model': MINIMAX_MODEL,
        'minimax_dialogue_model': MINIMAX_DIALOGUE_MODEL,
        'minimax_base_url': MINIMAX_BASE_URL,
        'minimax_timeout_seconds': LLM_TIMEOUT_SECONDS,
        'dialogue_timeout_seconds': LLM_DIALOGUE_TIMEOUT_SECONDS,
        'retry_timeout_seconds': LLM_RETRY_TIMEOUT_SECONDS,
        'dialogue_reasoning_effort': MINIMAX_DIALOGUE_EFFORT or 'default',
        'minimax_attempts': MINIMAX_ATTEMPTS,
        'retry_pause_seconds': LLM_RETRY_PAUSE_SECONDS,
        'turn_budget_seconds': LLM_CHAIN_BUDGET_SECONDS,
        'gemini_vision_key_present': bool(GEMINI_API_KEY_VALID),
        'gemini_model': GEMINI_CHAT_MODEL,
    }
