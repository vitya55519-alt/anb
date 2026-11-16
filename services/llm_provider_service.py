from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass

from openai import AsyncOpenAI

from config import (
    OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL,
    GEMINI_API_KEY, GEMINI_API_KEY_VALID, GEMINI_CHAT_MODEL, GEMINI_OPENAI_BASE_URL,
    MINIMAX_API_KEY, MINIMAX_BASE_URL, MINIMAX_MODEL, MINIMAX_DIALOGUE_MODEL,
    LLM_REPORT_USAGE,
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
    not tell its owner what a reply cost. OpenRouter reports a real bill when
    asked with ``usage.include``; otherwise we price the tokens ourselves."""
    usage = getattr(response, 'usage', None)
    if usage is None:
        return
    prompt_tokens = int(getattr(usage, 'prompt_tokens', 0) or 0)
    completion_tokens = int(getattr(usage, 'completion_tokens', 0) or 0)
    details = getattr(usage, 'completion_tokens_details', None)
    reasoning_tokens = int(getattr(details, 'reasoning_tokens', 0) or 0) if details else 0
    # OpenRouter puts its own bill into the usage object as an extra field.
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
# with 2 automatic retries, so a hung primary provider kept the user waiting
# for minutes before the fallback chain even started. The primary now fails
# fast with no SDK retries — the next provider in the chain is the retry.
def _env_float(name: str, default: float) -> float:
    try:
        return max(5.0, min(120.0, float(os.getenv(name, default))))
    except (TypeError, ValueError):
        return default


LLM_TIMEOUT_SECONDS = _env_float('LLM_TIMEOUT_SECONDS', 25.0)
LLM_FALLBACK_TIMEOUT_SECONDS = _env_float('LLM_FALLBACK_TIMEOUT_SECONDS', 40.0)

# V3.167.9 (владелец 16.11, «долго ответ идет»): у каждого провайдера свой
# таймаут, но ход чата — это до четырёх попыток подряд, и висящий MiniMax с
# запасным держал его в «печатает…» полторы минуты. Теперь у всего хода есть
# общий бюджет: каждый следующий провайдер получает только то, что от него
# осталось, а после конца бюджета цепочка обрывается, а не тянется дальше.
LLM_CHAIN_BUDGET_SECONDS = _env_float('LLM_CHAIN_BUDGET_SECONDS', 55.0)
# Запас, который у primary не вычитается из времени следующего провайдера.
LLM_FALLBACK_RESERVE_SECONDS = _env_float('LLM_FALLBACK_RESERVE_SECONDS', 15.0)
MIN_PROVIDER_SLICE_SECONDS = 3.0

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
# попытка с тем же усилием думала ровно так же. Повтор теперь просит у провайдера
# низкую глубину размышления (reasoning_effort — параметр OpenAI SDK, его принимают
# и MiniMax-M3, и M3.1-Flash; модель та же). Если провайдер параметр не знает,
# повтор случается по-старому.
MINIMAX_RETRY_EFFORT = os.getenv('MINIMAX_RETRY_EFFORT', 'low').strip()
# V3.143.0: owner ТЗ — she sometimes kept writing after his turn («User: …») and
# sent a dialogue where she answered for both. Every call that produces a chat
# message is cut at these markers; the caller adds the client's own name.
DEFAULT_STOP = ('User:', 'Пользователь:')
STOP_PURPOSES = frozenset({'dialogue', 'proactive', 'rewrite'})
STOP_MAX = 4
# V3.64.8: Gemini 3.x counts its hidden thinking inside max_tokens too, so a
# 90-token life moment came back as 2–4 words («Надела сегодня тот»).
GEMINI_REASONING_HEADROOM = max(0, int(os.getenv('GEMINI_REASONING_HEADROOM', '512')))

# ── Provider clients (chat: MiniMax primary, Gemini → OpenRouter fallback) ─
_openrouter = (
    AsyncOpenAI(api_key=OPENROUTER_API_KEY, base_url=OPENROUTER_BASE_URL,
                timeout=LLM_FALLBACK_TIMEOUT_SECONDS, max_retries=1)
    if OPENROUTER_API_KEY else None
)
_gemini = (
    AsyncOpenAI(api_key=GEMINI_API_KEY, base_url=GEMINI_OPENAI_BASE_URL,
                timeout=LLM_TIMEOUT_SECONDS, max_retries=0)
    if GEMINI_API_KEY_VALID else None
)
# V3.45.0: MiniMax — primary chat provider (дешевле OpenRouter)
_minimax = (
    AsyncOpenAI(api_key=MINIMAX_API_KEY, base_url=MINIMAX_BASE_URL,
                timeout=LLM_TIMEOUT_SECONDS, max_retries=0)
    if MINIMAX_API_KEY else None
)

logger.info(
    'LLM providers: OpenRouter=%s model=%s | Gemini=%s model=%s | MiniMax=%s model=%s',
    'READY' if _openrouter else 'NO KEY',
    OPENROUTER_MODEL,
    'READY' if _gemini else 'NO KEY',
    GEMINI_CHAT_MODEL,
    'READY' if _minimax else 'NO KEY',
    MINIMAX_MODEL,
)


# V3.96.0: calls that carry an image part.
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
    """Simple provider chain: OpenRouter → Gemini fallback.

    Raises RuntimeError with full diagnostic if all providers fail.
    """
    errors: list[str] = []
    # V3.167.9: общий бюджет хода. _slice(cap, reserve) — сколько секунд можно
    # отдать этому провайдеру, оставив запас на следующего; меньше секунды не
    # просим, запрос с таким таймаутом всё равно ничего не успеет.
    _deadline = time.monotonic() + LLM_CHAIN_BUDGET_SECONDS

    def _left() -> float:
        return _deadline - time.monotonic()

    def _slice(cap: float, reserve: float = 0.0) -> float:
        return max(1.0, min(cap, _left() - reserve))

    def _summary() -> str:
        return '; '.join(errors) if errors else 'no providers configured'

    if stop is None and purpose in STOP_PURPOSES:
        stop = list(DEFAULT_STOP)
    stop = [s for s in (str(x).strip() for x in (stop or [])) if s][:STOP_MAX]

    # V3.44.18: the daily money brake. Only the mechanical helper calls are
    # skipped — the reply the user actually reads always goes through, so the
    # persona degrades (no memory capture, no auto-rewording) instead of dying.
    if purpose in spend_service.AUX_PURPOSES and not spend_service.llm_aux_allowed():
        logger.warning('LLM aux skipped by daily budget purpose=%s', purpose)
        return LLMResult('', 'budget', 'skipped', error='daily budget')

    minimax_empty = False
    # ── 1. MiniMax (V3.45: primary chat provider) ─────────────────────
    # V3.96.0: a photo he sends needs eyes — MiniMax chat models are text-only,
    # so vision calls go straight to Gemini.
    if _minimax and purpose not in VISION_PURPOSES:
        mm_model = MINIMAX_DIALOGUE_MODEL if purpose == 'dialogue' else MINIMAX_MODEL
        mm_kwargs = {}
        if purpose == 'dialogue':
            # V3.63.12: MiniMax's own guidance for chat is temperature 1.0 with
            # top_p 0.95; below that M3 drifts into the same safe phrasing.
            # V3.143.0: the owner asked for 0.7–0.85 anyway — at 1.0 the dead
            # ends and invented facts about his life peaked. top_p stays wide so
            # the wording keeps varying at the lower temperature.
            mm_kwargs['top_p'] = 0.95
        if stop:
            mm_kwargs['stop'] = stop
        try:
            r = await asyncio.wait_for(
                _minimax.chat.completions.create(
                    model=mm_model,
                    messages=messages,
                    temperature=temperature,
                    # V3.63.4: MiniMax-M3 spends ~90 reasoning tokens inside the
                    # same budget — short calls (life moments, proactive, rewrite,
                    # adaptation) came back EMPTY. Give the thinking its own room.
                    max_tokens=max_tokens + max(MINIMAX_REASONING_HEADROOM, _MINIMAX_HEADROOM_BY_PURPOSE.get(purpose, 0)),
                    **mm_kwargs,
                ),
                timeout=_slice(LLM_TIMEOUT_SECONDS, LLM_FALLBACK_RESERVE_SECONDS),
            )
            text = _strip_thinking((r.choices[0].message.content or '').strip())
            _record_usage(purpose, 'minimax', mm_model, r)
            logger.info('LLM ok provider=minimax model=%s purpose=%s len=%d', mm_model, purpose, len(text))
            if text:
                return LLMResult(text, 'minimax', mm_model, _complete(r))
            # V3.167.9: «finish=length» на пустом тексте и есть признак того, что
            # thinking съел весь ответ — без этой строки в журнале хода различить
            # нечем.
            _finish = getattr(r.choices[0], 'finish_reason', '?') if getattr(r, 'choices', None) else '?'
            # V3.97.0: in a dialogue an EMPTY M3 answer means the reasoning ate
            # the whole cap (out == reasoning == cap in the logs). The free
            # Gemini fallback then often comes back empty too on adult chats,
            # and she answered «я зависла» 141 times a week. One retry with
            # a much larger room for the thinking comes first.
            # V3.167.9: то же самое молчание дважды подряд — молчание, поэтому
            # сначала повтор с коротким размышлением, и только если провайдер не
            # понял параметра — повтор ровно как раньше.
            if purpose in RETRY_EMPTY_PURPOSES and _left() > MIN_PROVIDER_SLICE_SECONDS + LLM_FALLBACK_RESERVE_SECONDS:
                variants = []
                if MINIMAX_RETRY_EFFORT:
                    variants.append(({**mm_kwargs, 'reasoning_effort': MINIMAX_RETRY_EFFORT}, f'effort={MINIMAX_RETRY_EFFORT}'))
                variants.append((dict(mm_kwargs), 'plain'))
                for mm_retry_kwargs, tag in variants:
                    try:
                        r = await asyncio.wait_for(
                            _minimax.chat.completions.create(
                                model=mm_model,
                                messages=messages,
                                temperature=temperature,
                                max_tokens=max_tokens + MINIMAX_EMPTY_RETRY_HEADROOM,
                                **mm_retry_kwargs,
                            ),
                            timeout=_slice(LLM_TIMEOUT_SECONDS, LLM_FALLBACK_RESERVE_SECONDS),
                        )
                        text = _strip_thinking((r.choices[0].message.content or '').strip())
                        _record_usage(purpose, 'minimax', mm_model, r)
                        logger.info('LLM retry provider=minimax purpose=%s %s len=%d', purpose, tag, len(text))
                        if text:
                            return LLMResult(text, 'minimax', mm_model, _complete(r))
                        errors.append(f'MiniMax({mm_model}) retry {tag}: empty text')
                        break  # второй раз за ход та же пустота — дальше только время
                    except Exception as exc:
                        detail = f'MiniMax({mm_model}) retry {tag}: {type(exc).__name__}: {_safe(str(exc))}'
                        errors.append(detail)
                        logger.warning('MiniMax retry FAILED purpose=%s %s', purpose, detail)
            # empty answer: let the free Gemini fallback try instead
            errors.append(f'MiniMax({mm_model}): empty text (finish={_finish})')
            minimax_empty = True
            logger.warning('MiniMax EMPTY purpose=%s, trying fallback', purpose)
        except Exception as exc:
            detail = f'MiniMax({mm_model}): {type(exc).__name__}: {_safe(str(exc))}'
            errors.append(detail)
            logger.warning('MiniMax FAILED purpose=%s %s', purpose, detail)

    # ── 2. Gemini (free fallback) ────────────────────────────────────
    if _gemini and _left() > MIN_PROVIDER_SLICE_SECONDS:
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
            logger.warning('Gemini FAILED purpose=%s %s', purpose, detail)

    # ── 3. OpenRouter (fallback, needs balance) ──────────────────────
    if _openrouter and _left() > MIN_PROVIDER_SLICE_SECONDS:
        try:
            extra = {}
            if purpose == 'dialogue':
                extra['reasoning'] = {'enabled': True}
            if LLM_REPORT_USAGE:
                extra['usage'] = {'include': True}
            kwargs = dict(
                model=OPENROUTER_MODEL,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if stop:
                kwargs['stop'] = stop
            if extra:
                kwargs['extra_body'] = extra
            r = await asyncio.wait_for(
                _openrouter.chat.completions.create(**kwargs),
                timeout=_slice(LLM_FALLBACK_TIMEOUT_SECONDS),
            )
            text = _strip_thinking((r.choices[0].message.content or '').strip())
            _record_usage(purpose, 'openrouter', OPENROUTER_MODEL, r)
            logger.info('LLM ok provider=openrouter model=%s purpose=%s len=%d', OPENROUTER_MODEL, purpose, len(text))
            return LLMResult(text, 'openrouter', OPENROUTER_MODEL, True, '' if text else _summary())
        except Exception as exc:
            detail = f'OpenRouter({OPENROUTER_MODEL}): {type(exc).__name__}: {_safe(str(exc))}'
            errors.append(detail)
            logger.warning('OpenRouter FAILED purpose=%s %s', purpose, detail)

    # ── All failed ─────────────────────────────────────────────────────
    if minimax_empty:
        # callers already handle an empty answer; keep that, not a crash.
        # V3.167.9: этот путь не raise, поэтому без причины в error ход выглядел
        # как её запасная фраза и никто не знал, кто именно молчит.
        return LLMResult('', 'minimax', MINIMAX_MODEL, True, _summary())
    summary = '; '.join(errors) if errors else 'no providers configured'
    logger.error('ALL LLM PROVIDers FAILED purpose=%s errors=[%s]', purpose, summary)
    raise RuntimeError(f'LLM unavailable: {summary}')


def provider_status() -> dict:
    return {
        'minimax_key_present': bool(MINIMAX_API_KEY),
        'minimax_model': MINIMAX_MODEL,
        'minimax_base_url': MINIMAX_BASE_URL,
        'openrouter_key_present': bool(OPENROUTER_API_KEY),
        'openrouter_model': OPENROUTER_MODEL,
        'openrouter_base_url': OPENROUTER_BASE_URL,
        'gemini_key_present': bool(GEMINI_API_KEY_VALID),
        'gemini_model': GEMINI_CHAT_MODEL,
    }
