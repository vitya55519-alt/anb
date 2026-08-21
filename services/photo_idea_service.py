"""Photo idea engine: curated bank + admin ideas + LLM variations.

Gives ordinary photo requests Pinterest-style variety (gym, bar, park, cafe...)
without scraping any external site. The curated bank lives in
``data/photo_ideas.json`` and can be extended manually; admins can add ideas
through the Telegram admin panel (stored in PostgreSQL); the LLM occasionally
invents fresh variations of a seed. Private scenes and explicit user requests
are never touched.
"""

import asyncio
import json
import logging
import random
import re
from collections import deque
from dataclasses import replace
from pathlib import Path

from sqlalchemy import select

from config import PHOTO_IDEAS_ENABLED, PHOTO_IDEA_LLM_CHANCE
from services.db import SessionLocal
from models.photo_models import AdminPhotoIdea

logger = logging.getLogger(__name__)

IDEAS_PATH = Path(__file__).resolve().parents[1] / 'data' / 'photo_ideas.json'

# Never rewrite intimate scenes: their wording is moderation-sensitive.
_PRIVATE_SCENES = {'personal', 'lingerie', 'private_fashion'}

# Per-user short memory of recently used ideas to avoid repetition.
_RECENT_LIMIT = 16
_recent_ideas: dict[int, deque[str]] = {}

_bank_cache: list[dict] | None = None


def _load_bank() -> list[dict]:
    global _bank_cache
    if _bank_cache is None:
        try:
            raw = json.loads(IDEAS_PATH.read_text(encoding='utf-8'))
            _bank_cache = [
                item for item in raw
                if isinstance(item, dict) and item.get('scene') and item.get('location')
            ]
        except Exception:
            logger.exception('photo idea bank failed to load path=%s', IDEAS_PATH)
            _bank_cache = []
        logger.info('photo idea bank loaded count=%s', len(_bank_cache))
    return _bank_cache


def _idea_key(idea: dict) -> str:
    return f"{idea.get('scene')}|{idea.get('location')}|{idea.get('angle', '')}"


def _load_db_ideas() -> list[dict]:
    """Admin-added ideas from PostgreSQL (survive Railway redeployments)."""
    try:
        with SessionLocal() as session:
            rows = session.scalars(select(AdminPhotoIdea).order_by(AdminPhotoIdea.id.desc())).all()
            return [
                {'scene': row.scene, 'location': row.location, 'angle': row.angle or '', 'id': row.id, 'source': 'admin'}
                for row in rows
            ]
    except Exception:
        logger.exception('admin photo ideas failed to load')
        return []


def pick_idea(telegram_id: int, scene: str) -> dict | None:
    """Random idea for the scene (JSON bank + admin ideas), preferring fresh ones."""
    pool = [item for item in (_load_bank() + _load_db_ideas()) if item.get('scene') == scene]
    if not pool:
        return None
    recent = _recent_ideas.get(telegram_id)
    fresh = [item for item in pool if _idea_key(item) not in (recent or ())] or pool
    return random.choice(fresh)


def _mark_used(telegram_id: int, idea: dict) -> None:
    recent = _recent_ideas.setdefault(telegram_id, deque(maxlen=_RECENT_LIMIT))
    recent.append(_idea_key(idea))


# ── Admin panel management (ideas live in PostgreSQL) ─────────────────────

def idea_counts() -> tuple[int, int]:
    """(curated JSON ideas, admin-added DB ideas)."""
    return len(_load_bank()), len(_load_db_ideas())


def list_admin_ideas(limit: int = 10) -> list[dict]:
    try:
        with SessionLocal() as session:
            rows = session.scalars(
                select(AdminPhotoIdea).order_by(AdminPhotoIdea.id.desc()).limit(max(1, min(50, limit)))
            ).all()
            return [{'id': row.id, 'scene': row.scene, 'location': row.location, 'angle': row.angle or ''} for row in rows]
    except Exception:
        logger.exception('admin photo ideas list failed')
        return []


def add_admin_idea(scene: str, location: str, angle: str, created_by: int | str) -> int | None:
    try:
        with SessionLocal() as session:
            row = AdminPhotoIdea(
                scene=scene.strip().lower(),
                location=location.strip(),
                angle=(angle or '').strip(),
                created_by=str(created_by),
            )
            session.add(row)
            session.commit()
            logger.info('admin photo idea added id=%s scene=%s by=%s', row.id, row.scene, created_by)
            return row.id
    except Exception:
        logger.exception('admin photo idea add failed scene=%s by=%s', scene, created_by)
        return None


def delete_admin_idea(idea_id: int) -> bool:
    try:
        with SessionLocal() as session:
            row = session.get(AdminPhotoIdea, idea_id)
            if not row:
                return False
            session.delete(row)
            session.commit()
            logger.info('admin photo idea deleted id=%s scene=%s', idea_id, row.scene)
            return True
    except Exception:
        logger.exception('admin photo idea delete failed id=%s', idea_id)
        return False


async def _llm_variation(seed: dict) -> dict | None:
    """Ask the chat LLM for one fresh variation of a bank seed idea."""
    from services.llm_provider_service import generate_text
    prompt = (
        'You invent photo shoot ideas for a fictional adult woman\'s personal smartphone photos.\n'
        f"Seed idea: scene={seed.get('scene')}; location={seed.get('location')}; camera={seed.get('angle', '')}.\n"
        'Invent ONE new variation: keep the same place type but change concrete details '
        '(light, props, spot, framing) so it feels like a different day.\n'
        'Return ONLY a JSON object: {"location": "...", "angle": "..."}\n'
        'Rules: mainstream general-audience, fully clothed, natural personal-photo aesthetic, '
        'one short sentence per field, no intimate, lingerie or sexual wording.'
    )
    try:
        result = await asyncio.wait_for(
            generate_text(
                [{'role': 'user', 'content': prompt}],
                max_tokens=160,
                temperature=0.95,
                purpose='photo_idea',
            ),
            timeout=25.0,
        )
    except Exception as exc:
        logger.warning('photo idea LLM variation failed type=%s', type(exc).__name__)
        return None
    text = (result.text or '').strip()
    text = re.sub(r'^```(?:json)?|```$', '', text, flags=re.MULTILINE).strip()
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start:
        logger.warning('photo idea LLM variation not JSON: %.120s', text)
        return None
    try:
        data = json.loads(text[start:end + 1])
    except Exception:
        logger.warning('photo idea LLM variation bad JSON: %.120s', text)
        return None
    location = str(data.get('location', '')).strip()
    angle = str(data.get('angle', '')).strip()
    if not location or len(location) > 400 or len(angle) > 300:
        return None
    return {'scene': seed.get('scene'), 'location': location, 'angle': angle}


async def enrich_request_with_idea(telegram_id: int, request):
    """Fill an underspecified ordinary photo request with a fresh idea.

    Returns ``(request, source)`` where source is 'bank', 'llm' or None.
    Explicit/custom requests and private scenes pass through unchanged.
    """
    if not PHOTO_IDEAS_ENABLED or getattr(request, 'customized', False):
        return request, None
    scene = getattr(request, 'scene', '') or 'selfie'
    if scene in _PRIVATE_SCENES or getattr(request, 'location', '') or getattr(request, 'angle', ''):
        return request, None

    idea = pick_idea(telegram_id, scene)
    if not idea:
        return request, None

    source = 'bank'
    if PHOTO_IDEA_LLM_CHANCE > 0 and random.random() < PHOTO_IDEA_LLM_CHANCE:
        variation = await _llm_variation(idea)
        if variation:
            idea, source = variation, 'llm'

    _mark_used(telegram_id, idea)
    changes = {'location': idea['location']}
    if idea.get('angle'):
        changes['angle'] = idea['angle']
    logger.info('photo idea applied user=%s scene=%s source=%s', telegram_id, scene, source)
    return replace(request, **changes), source
