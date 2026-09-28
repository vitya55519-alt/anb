"""V3.44.18: money telemetry and daily brakes.

Why this exists: the owner watched $14 disappear in five days while the bot
served ~46 chat messages a day, and /stats could not explain a single cent.
Three blind spots made that inevitable:

1. ``llm_provider_service.generate_text`` read only ``choices[0]`` and threw the
   provider ``usage`` block away — no token or cost record for any LLM call.
2. ``photo_deliveries.estimated_cost_usd`` is written only for a SUCCESSFUL
   delivery, so a failed studio render (49% of them) burned money invisibly.
3. ``GEMINI_IMAGE_ESTIMATED_COST_USD`` defaulted to 0 while Gemini is the main
   photo engine — «себестоимость фото: $0.00» was a rounding artifact, not truth.

This module stores one row per LLM completion and per billed image call, sums
them for /stats, and enforces two daily brakes: auxiliary LLM work stops when
the chat budget is gone (the visible reply is never blocked), and image
generation is refused BEFORE the provider is called when the media budget is
gone, so the existing refund path gives the user their money back.

Every function is fail-silent by design: a broken ledger must never take the
bot down, it may only lose us the accounting.
"""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import func, select

from config import (
    GEMINI_LLM_USD_PER_M_INPUT, GEMINI_LLM_USD_PER_M_OUTPUT,
    LLM_USD_PER_M_INPUT, LLM_USD_PER_M_OUTPUT,
    SPEND_IMAGE_DAILY_BUDGET_USD, SPEND_LLM_DAILY_BUDGET_USD,
)
from models.app_models import ImageSpend, LlmUsage, utcnow
from services.db import SessionLocal

logger = logging.getLogger(__name__)

# Mechanical helpers, not the answer the user reads. These are the first things
# switched off by the brake — the persona survives without them, only gets less
# polished (no memory extraction, no auto-rewording, no LLM photo ideas).
AUX_PURPOSES = frozenset({
    'memory_extraction', 'adaptation_analysis', 'relationship_pulse',
    'photo_idea', 'photo_reaction', 'rewrite',
})


def estimate_llm_cost_usd(provider: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Fallback price when the provider does not report its own bill."""
    if provider == 'gemini':
        per_in, per_out = GEMINI_LLM_USD_PER_M_INPUT, GEMINI_LLM_USD_PER_M_OUTPUT
    else:
        per_in, per_out = LLM_USD_PER_M_INPUT, LLM_USD_PER_M_OUTPUT
    return (prompt_tokens / 1_000_000.0) * per_in + (completion_tokens / 1_000_000.0) * per_out


def record_llm_usage(purpose: str, provider: str, model: str, *,
                     prompt_tokens: int = 0, completion_tokens: int = 0,
                     reasoning_tokens: int = 0, cost_usd: float | None = None) -> None:
    """One ledger row per completion. ``cost_usd`` is the provider-reported bill
    when OpenRouter returns one; otherwise we estimate from token counts."""
    try:
        prompt_tokens = max(0, int(prompt_tokens or 0))
        completion_tokens = max(0, int(completion_tokens or 0))
        reasoning_tokens = max(0, int(reasoning_tokens or 0))
        billed = cost_usd is not None
        if not billed:
            cost_usd = estimate_llm_cost_usd(provider, prompt_tokens, completion_tokens)
        with SessionLocal() as s:
            s.add(LlmUsage(
                day=utcnow().date(),
                purpose=str(purpose)[:32],
                provider=str(provider)[:16],
                model=str(model)[:64],
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                reasoning_tokens=reasoning_tokens,
                cost_usd=max(0.0, float(cost_usd or 0.0)),
                billed_cost=billed,
            ))
            s.commit()
    except Exception:
        logger.warning('llm usage record failed purpose=%s provider=%s', purpose, provider, exc_info=True)


def record_image_spend(engine: str, scene: str, cost_usd: float, *,
                       billed: bool = True, success: bool = True) -> None:
    """One ledger row per image API call that the provider may charge for —
    including the ones whose picture we later threw away."""
    try:
        with SessionLocal() as s:
            s.add(ImageSpend(
                day=utcnow().date(),
                engine=str(engine)[:48],
                scene=str(scene or '-')[:48],
                billed=bool(billed),
                success=bool(success),
                cost_usd=max(0.0, float(cost_usd or 0.0)),
            ))
            s.commit()
    except Exception:
        logger.warning('image spend record failed engine=%s scene=%s', engine, scene, exc_info=True)


def _sum_today(model, column, *, day: dt.date, **where) -> float:
    try:
        with SessionLocal() as s:
            stmt = select(func.coalesce(func.sum(column), 0.0)).where(model.day == day)
            for field, value in where.items():
                stmt = stmt.where(getattr(model, field) == value)
            return float(s.scalar(stmt) or 0.0)
    except Exception:
        logger.warning('spend sum failed model=%s', getattr(model, '__tablename__', '?'), exc_info=True)
        return 0.0


def llm_cost_today() -> float:
    return _sum_today(LlmUsage, LlmUsage.cost_usd, day=utcnow().date())


def image_cost_today() -> float:
    return _sum_today(ImageSpend, ImageSpend.cost_usd, day=utcnow().date(), billed=True)


def llm_aux_allowed() -> bool:
    """The chat brake: auxiliary LLM work only, never the visible reply."""
    if SPEND_LLM_DAILY_BUDGET_USD <= 0:
        return True
    return llm_cost_today() < SPEND_LLM_DAILY_BUDGET_USD


def image_generation_allowed() -> bool:
    if SPEND_IMAGE_DAILY_BUDGET_USD <= 0:
        return True
    return image_cost_today() < SPEND_IMAGE_DAILY_BUDGET_USD


def spend_snapshot() -> dict:
    """Everything /stats needs: today's split by purpose and by photo engine,
    plus how close each brake is to tripping."""
    day = utcnow().date()
    out = {
        'llm_usd': llm_cost_today(),
        'image_usd': image_cost_today(),
        'image_fail_usd': _sum_today(ImageSpend, ImageSpend.cost_usd, day=day, billed=True, success=False),
        'llm_budget': SPEND_LLM_DAILY_BUDGET_USD,
        'image_budget': SPEND_IMAGE_DAILY_BUDGET_USD,
        'llm_calls': 0, 'by_purpose': [], 'by_engine': [],
        'reasoning_tokens': 0, 'prompt_tokens': 0, 'completion_tokens': 0,
    }
    try:
        with SessionLocal() as s:
            out['llm_calls'] = int(s.scalar(select(func.count(LlmUsage.id)).where(LlmUsage.day == day)) or 0)
            out['reasoning_tokens'] = int(s.scalar(select(func.coalesce(func.sum(LlmUsage.reasoning_tokens), 0)).where(LlmUsage.day == day)) or 0)
            out['prompt_tokens'] = int(s.scalar(select(func.coalesce(func.sum(LlmUsage.prompt_tokens), 0)).where(LlmUsage.day == day)) or 0)
            out['completion_tokens'] = int(s.scalar(select(func.coalesce(func.sum(LlmUsage.completion_tokens), 0)).where(LlmUsage.day == day)) or 0)
            rows = s.execute(select(LlmUsage.purpose, func.sum(LlmUsage.cost_usd), func.count(LlmUsage.id))
                              .where(LlmUsage.day == day)
                              .group_by(LlmUsage.purpose)
                              .order_by(func.sum(LlmUsage.cost_usd).desc()).limit(4)).all()
            out['by_purpose'] = [(str(p), float(c or 0.0), int(n or 0)) for p, c, n in rows]
            rows = s.execute(select(ImageSpend.engine, func.sum(ImageSpend.cost_usd), func.count(ImageSpend.id))
                             .where(ImageSpend.day == day, ImageSpend.billed.is_(True))
                             .group_by(ImageSpend.engine)
                             .order_by(func.sum(ImageSpend.cost_usd).desc()).limit(4)).all()
            out['by_engine'] = [(str(e), float(c or 0.0), int(n or 0)) for e, c, n in rows]
    except Exception:
        logger.warning('spend snapshot failed', exc_info=True)
    return out


def format_spend_lines(snap: dict) -> list[str]:
    """Admin-facing rendering: the two money streams, the invisible half of the
    photo bill, and who exactly ate the budget."""
    lines = [
        f'💸 расход за сегодня: LLM ${snap["llm_usd"]:.3f} '
        f'({snap["llm_calls"]} вызовов) · картинки ${snap["image_usd"]:.3f} '
        f'из них на фейлы ${snap["image_fail_usd"]:.3f}',
    ]
    if snap.get('by_purpose'):
        parts = [f'{p} ${c:.3f}/{n}' for p, c, n in snap['by_purpose']]
        lines.append('· LLM по задачам: ' + ' · '.join(parts))
    if snap.get('by_engine'):
        parts = [f'{e} ${c:.3f}/{n}' for e, c, n in snap['by_engine']]
        lines.append('· картинки по движкам: ' + ' · '.join(parts))
    lines.append(
        f'· токены: вход {snap.get("prompt_tokens", 0)} · выход {snap.get("completion_tokens", 0)} '
        f'· reasoning {snap.get("reasoning_tokens", 0)}'
    )
    if snap.get('llm_budget'):
        lines.append(
            f'· тормоза: LLM лимит ${snap["llm_budget"]:.2f}/сутки '
            f'({"выключен" if not llm_aux_allowed() else "активен"}), '
            f'картинки ${snap["image_budget"]:.2f}/сутки '
            f'({"выключен" if not image_generation_allowed() else "активен"})'
        )
    return lines
