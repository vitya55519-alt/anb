from __future__ import annotations

import logging
from dataclasses import dataclass

from openai import AsyncOpenAI

from config import (
    OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL,
    GEMINI_API_KEY, GEMINI_CHAT_MODEL, GEMINI_OPENAI_BASE_URL,
)

logger = logging.getLogger(__name__)


def _safe(s: str) -> str:
    """Make string safe for ASCII-only log outputs."""
    try:
        return s.encode('ascii', errors='replace').decode('ascii')
    except Exception:
        return repr(s)

# ── Provider clients (chat: OpenRouter primary, Gemini fallback) ─────────
_openrouter = (
    AsyncOpenAI(api_key=OPENROUTER_API_KEY, base_url=OPENROUTER_BASE_URL)
    if OPENROUTER_API_KEY else None
)
_gemini = (
    AsyncOpenAI(api_key=GEMINI_API_KEY, base_url=GEMINI_OPENAI_BASE_URL)
    if GEMINI_API_KEY else None
)

logger.info(
    'LLM providers: OpenRouter=%s model=%s | Gemini=%s model=%s',
    'READY' if _openrouter else 'NO KEY',
    OPENROUTER_MODEL,
    'READY' if _gemini else 'NO KEY',
    GEMINI_CHAT_MODEL,
)


@dataclass(frozen=True)
class LLMResult:
    text: str
    provider: str
    model: str


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

    # ── 1. OpenRouter (MiniMax M2) ────────────────────────────────────
    if _openrouter:
        try:
            r = await _openrouter.chat.completions.create(
                model=OPENROUTER_MODEL,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            text = (r.choices[0].message.content or '').strip()
            logger.info('LLM ok provider=openrouter model=%s purpose=%s len=%d', OPENROUTER_MODEL, purpose, len(text))
            return LLMResult(text, 'openrouter', OPENROUTER_MODEL)
        except Exception as exc:
            detail = f'OpenRouter({OPENROUTER_MODEL}): {type(exc).__name__}: {_safe(str(exc))}'
            errors.append(detail)
            logger.warning('OpenRouter FAILED purpose=%s %s', purpose, detail)

    # ── 2. Gemini fallback ────────────────────────────────────────────
    if _gemini:
        try:
            r = await _gemini.chat.completions.create(
                model=GEMINI_CHAT_MODEL,
                messages=messages,
                max_tokens=max_tokens,
            )
            text = (r.choices[0].message.content or '').strip()
            logger.info('LLM ok provider=gemini model=%s purpose=%s len=%d', GEMINI_CHAT_MODEL, purpose, len(text))
            return LLMResult(text, 'gemini', GEMINI_CHAT_MODEL)
        except Exception as exc:
            detail = f'Gemini({GEMINI_CHAT_MODEL}): {type(exc).__name__}: {_safe(str(exc))}'
            errors.append(detail)
            logger.warning('Gemini FAILED purpose=%s %s', purpose, detail)

    # ── All failed ─────────────────────────────────────────────────────
    summary = '; '.join(errors) if errors else 'no providers configured'
    logger.error('ALL LLM PROVIDers FAILED purpose=%s errors=[%s]', purpose, summary)
    raise RuntimeError(f'LLM unavailable: {summary}')


def provider_status() -> dict:
    return {
        'openrouter_key_present': bool(OPENROUTER_API_KEY),
        'openrouter_model': OPENROUTER_MODEL,
        'openrouter_base_url': OPENROUTER_BASE_URL,
        'gemini_key_present': bool(GEMINI_API_KEY),
        'gemini_model': GEMINI_CHAT_MODEL,
    }
