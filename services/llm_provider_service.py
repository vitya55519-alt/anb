from __future__ import annotations

import logging
from dataclasses import dataclass

from openai import AsyncOpenAI

from config import (
    AI_KEY, AI_MODEL, AI_BASE_URL,
    OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL,
    GEMINI_API_KEY, GEMINI_CHAT_MODEL, GEMINI_OPENAI_BASE_URL, GEMINI_THINKING_LEVEL,
    CHAT_PROVIDER, CHAT_FALLBACK_GEMINI, CHAT_FALLBACK_OPENAI,
)

logger = logging.getLogger(__name__)

# ── Provider clients ───────────────────────────────────────────────────────
_openrouter = (
    AsyncOpenAI(api_key=OPENROUTER_API_KEY, base_url=OPENROUTER_BASE_URL)
    if OPENROUTER_API_KEY else None
)
_openai = AsyncOpenAI(api_key=AI_KEY, base_url=AI_BASE_URL) if AI_KEY else None
_gemini = AsyncOpenAI(api_key=GEMINI_API_KEY, base_url=GEMINI_OPENAI_BASE_URL) if GEMINI_API_KEY else None


@dataclass(frozen=True)
class LLMResult:
    text: str
    provider: str
    model: str


async def _call_openrouter(messages: list[dict], *, max_tokens: int, temperature: float) -> LLMResult:
    if not _openrouter:
        raise RuntimeError('OPENEROUTER_API_KEY is not configured')
    r = await _openrouter.chat.completions.create(
        model=OPENROUTER_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return LLMResult((r.choices[0].message.content or '').strip(), 'openrouter', OPENROUTER_MODEL)


async def _call_openai(messages: list[dict], *, max_tokens: int, temperature: float) -> LLMResult:
    if not _openai:
        raise RuntimeError('OPENAI_API_KEY is not configured')
    r = await _openai.chat.completions.create(
        model=AI_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return LLMResult((r.choices[0].message.content or '').strip(), 'openai', AI_MODEL)


async def _call_gemini(messages: list[dict], *, max_tokens: int) -> LLMResult:
    if not _gemini:
        raise RuntimeError('GEMINI_API_KEY is not configured')
    # Current Gemini 3.x Flash models deprecate temperature/top_p/top_k. Keep natural creativity in
    # the character prompt and use minimal thinking to reduce latency/overthinking.
    kwargs = dict(
        model=GEMINI_CHAT_MODEL,
        messages=messages,
        max_tokens=max_tokens,
    )
    if GEMINI_THINKING_LEVEL in {'none', 'minimal', 'low', 'medium', 'high'}:
        kwargs['reasoning_effort'] = GEMINI_THINKING_LEVEL
    r = await _gemini.chat.completions.create(**kwargs)
    return LLMResult((r.choices[0].message.content or '').strip(), 'gemini', GEMINI_CHAT_MODEL)


async def generate_text(
    messages: list[dict],
    *,
    max_tokens: int,
    temperature: float = 0.9,
    purpose: str = 'dialogue',
) -> LLMResult:
    """Provider chain: primary → fallback_gimini → fallback_openai."""
    primary = CHAT_PROVIDER

    # ── OpenRouter primary ─────────────────────────────────────────────
    if primary == 'openrouter' and _openrouter:
        try:
            result = await _call_openrouter(messages, max_tokens=max_tokens, temperature=temperature)
            logger.info('LLM success provider=openrouter model=%s purpose=%s', result.model, purpose)
            return result
        except Exception as exc:
            logger.warning('OpenRouter failed purpose=%s error=%s', purpose, type(exc).__name__)
            # fall through to Gemini / OpenAI

    # ── Gemini ─────────────────────────────────────────────────────────
    if (primary == 'gemini' or (primary == 'openrouter' and CHAT_FALLBACK_GEMINI)) and _gemini:
        try:
            result = await _call_gemini(messages, max_tokens=max_tokens)
            logger.info('LLM success provider=gemini model=%s purpose=%s', result.model, purpose)
            return result
        except Exception as exc:
            logger.warning('Gemini failed purpose=%s error=%s', purpose, type(exc).__name__)
            if not CHAT_FALLBACK_OPENAI:
                raise

    # ── OpenAI (legacy fallback, only if key present) ─────────────────
    if _openai and CHAT_FALLBACK_OPENAI:
        result = await _call_openai(messages, max_tokens=max_tokens, temperature=temperature)
        logger.info('LLM fallback success provider=openai model=%s purpose=%s', result.model, purpose)
        return result

    raise RuntimeError('All LLM providers failed')


def provider_status() -> dict:
    return {
        'configured_provider': CHAT_PROVIDER,
        'openrouter_key_present': bool(OPENROUTER_API_KEY),
        'openrouter_model': OPENROUTER_MODEL,
        'gemini_key_present': bool(GEMINI_API_KEY),
        'gemini_model': GEMINI_CHAT_MODEL,
        'fallback_gemini': CHAT_FALLBACK_GEMINI,
        'fallback_openai': CHAT_FALLBACK_OPENAI,
        'thinking_level': GEMINI_THINKING_LEVEL,
        'openai_model': AI_MODEL,
    }
