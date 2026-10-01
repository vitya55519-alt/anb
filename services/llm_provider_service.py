from __future__ import annotations

import logging
from dataclasses import dataclass

from openai import AsyncOpenAI

from config import (
    OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL,
    GEMINI_API_KEY, GEMINI_API_KEY_VALID, GEMINI_CHAT_MODEL, GEMINI_OPENAI_BASE_URL,
    MINIMAX_API_KEY, MINIMAX_BASE_URL, MINIMAX_MODEL,
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

# ── Provider clients (chat: OpenRouter primary, Gemini fallback) ─────────
_openrouter = (
    AsyncOpenAI(api_key=OPENROUTER_API_KEY, base_url=OPENROUTER_BASE_URL)
    if OPENROUTER_API_KEY else None
)
_gemini = (
    AsyncOpenAI(api_key=GEMINI_API_KEY, base_url=GEMINI_OPENAI_BASE_URL)
    if GEMINI_API_KEY_VALID else None
)
# V3.45.0: MiniMax — primary chat provider (дешевле OpenRouter)
_minimax = (
    AsyncOpenAI(api_key=MINIMAX_API_KEY, base_url=MINIMAX_BASE_URL)
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


@dataclass(frozen=True)
class LLMResult:
    text: str
    provider: str
    model: str


import re
_THINK_RE = re.compile(r'<think(?:ing)?>.*?</think(?:ing)?>', re.DOTALL | re.IGNORECASE)

def _strip_thinking(text: str) -> str:
    """V3.45: remove / tags that MiniMax/reasoning models leak."""
    return _THINK_RE.sub('', text).strip()


async def generate_text(
    messages: list[dict],
    *,
    max_tokens: int,
    temperature: float = 0.9,
    purpose: str = 'dialogue',
) -> LLMResult:
    """Simple provider chain: OpenRouter → Gemini fallback.

    Raises RuntimeError with full diagnostic if all providers fail.
    """
    errors: list[str] = []

    # V3.44.18: the daily money brake. Only the mechanical helper calls are
    # skipped — the reply the user actually reads always goes through, so the
    # persona degrades (no memory capture, no auto-rewording) instead of dying.
    if purpose in spend_service.AUX_PURPOSES and not spend_service.llm_aux_allowed():
        logger.warning('LLM aux skipped by daily budget purpose=%s', purpose)
        return LLMResult('', 'budget', 'skipped')

    # ── 1. Gemini (V3.45: free, always works) ─────────────────────────
    if _gemini:
        try:
            r = await _gemini.chat.completions.create(
                model=GEMINI_CHAT_MODEL,
                messages=messages,
                max_tokens=max_tokens,
            )
            text = _strip_thinking((r.choices[0].message.content or '').strip())
            _record_usage(purpose, 'gemini', GEMINI_CHAT_MODEL, r)
            logger.info('LLM ok provider=gemini model=%s purpose=%s len=%d', GEMINI_CHAT_MODEL, purpose, len(text))
            return LLMResult(text, 'gemini', GEMINI_CHAT_MODEL)
        except Exception as exc:
            detail = f'Gemini({GEMINI_CHAT_MODEL}): {type(exc).__name__}: {_safe(str(exc))}'
            errors.append(detail)
            logger.warning('Gemini FAILED purpose=%s %s', purpose, detail)

    # ── 2. MiniMax (V3.45: needs correct key in Railway) ─────────────
    if _minimax:
        try:
            r = await _minimax.chat.completions.create(
                model=MINIMAX_MODEL,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            text = _strip_thinking((r.choices[0].message.content or '').strip())
            _record_usage(purpose, 'minimax', MINIMAX_MODEL, r)
            logger.info('LLM ok provider=minimax model=%s purpose=%s len=%d', MINIMAX_MODEL, purpose, len(text))
            return LLMResult(text, 'minimax', MINIMAX_MODEL)
        except Exception as exc:
            detail = f'MiniMax({MINIMAX_MODEL}): {type(exc).__name__}: {_safe(str(exc))}'
            errors.append(detail)
            logger.warning('MiniMax FAILED purpose=%s %s', purpose, detail)

    # ── 3. OpenRouter (fallback, needs balance) ──────────────────────
    if _openrouter:
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
            if extra:
                kwargs['extra_body'] = extra
            r = await _openrouter.chat.completions.create(**kwargs)
            text = _strip_thinking((r.choices[0].message.content or '').strip())
            _record_usage(purpose, 'openrouter', OPENROUTER_MODEL, r)
            logger.info('LLM ok provider=openrouter model=%s purpose=%s len=%d', OPENROUTER_MODEL, purpose, len(text))
            return LLMResult(text, 'openrouter', OPENROUTER_MODEL)
        except Exception as exc:
            detail = f'OpenRouter({OPENROUTER_MODEL}): {type(exc).__name__}: {_safe(str(exc))}'
            errors.append(detail)
            logger.warning('OpenRouter FAILED purpose=%s %s', purpose, detail)

    # ── All failed ─────────────────────────────────────────────────────
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
