"""Relationship pulse: periodic LLM quality evaluation of the conversation.

The regex signal classifier (relationship_signals.infer_delta) only sees
keyword hits, so a genuinely deep conversation without trigger words used to
earn almost nothing. Every PULSE_EVERY messages this module asks the chat LLM
to score the recent excerpt (warmth/trust/intimacy 0-3 plus notable events
like callbacks and inside jokes) and applies a small extra delta. Events map
onto the engine's connection-boosting types, so quality talk finally grows
the hidden dimensions too.

Fail-silent by design: any provider/parse error just skips the pulse.
"""
from __future__ import annotations

import json
import logging
import re

from config import CHARACTER_ID, RELATIONSHIP_PULSE_ENABLED
from services.user_service import ensure_user

logger = logging.getLogger(__name__)

PULSE_EVERY = 8
_PULSE_EVENTS = {'callback', 'inside_joke', 'meaningful_share', 'care', 'warm_flirt'}

_PULSE_PROMPT = (
    'Оцени последний фрагмент переписки пользователя с девушкой (AI-компаньон). '
    'Ответь СТРОГО одним JSON-объектом без пояснений: '
    '{"warmth": 0-3, "trust": 0-3, "intimacy": 0-3, "events": []}. '
    'warmth — теплота и вовлечённость; trust — личная открытость и доверие; intimacy — взаимный флирт. '
    'В events добавляй из списка: callback (вернулся к прошлой теме), inside_joke (общая шутка), '
    'meaningful_share (поделился личным), care (забота), warm_flirt (тёплый флирт).'
)

_JSON_RE = re.compile(r'\{.*\}', re.S)


def _parse_pulse(raw: str) -> dict | None:
    match = _JSON_RE.search(raw or '')
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    def _axis(name: str) -> float:
        try:
            return max(0.0, min(3.0, float(data.get(name, 0))))
        except (ValueError, TypeError):
            return 0.0

    events = [e for e in data.get('events', []) if isinstance(e, str) and e in _PULSE_EVENTS]
    return {'warmth': _axis('warmth'), 'trust': _axis('trust'), 'intimacy': _axis('intimacy'), 'events': events[:2]}


async def maybe_pulse(telegram_id: int, user_name: str, character_id: str = CHARACTER_ID) -> None:
    """Run one LLM pulse when this user's message count hits the interval."""
    if not RELATIONSHIP_PULSE_ENABLED:
        return
    try:
        uid = ensure_user(telegram_id, user_name)
        from services.db import SessionLocal
        from models.relationship_models import UserCharacterRelationship
        from sqlalchemy import select
        with SessionLocal() as session:
            row = session.scalar(select(UserCharacterRelationship).where(
                UserCharacterRelationship.user_id == uid,
                UserCharacterRelationship.character_id == character_id,
            ))
        if not row or row.total_messages < PULSE_EVERY or row.total_messages % PULSE_EVERY != 0:
            return

        from services.memory_service import get_recent_messages
        history = get_recent_messages(uid, character_id, 12)
        excerpt = '\n'.join(
            f"{'Пользователь' if m.get('role') == 'user' else 'Она'}: {m.get('content', '')[:200]}"
            for m in history if isinstance(m, dict) and m.get('content')
        )
        if not excerpt.strip():
            return

        from services.llm_provider_service import generate_text
        result = await generate_text(
            [{'role': 'user', 'content': _PULSE_PROMPT + '\n\nФрагмент:\n' + excerpt}],
            max_tokens=120, temperature=0.3, purpose='relationship_pulse',
        )
        pulse = _parse_pulse(getattr(result, 'text', ''))
        if not pulse:
            return
        if pulse['warmth'] == 0 and pulse['trust'] == 0 and pulse['intimacy'] == 0 and not pulse['events']:
            return

        from services.relationship_service import record_user_message
        event_type = pulse['events'][0] if pulse['events'] else 'interaction'
        await record_user_message(
            telegram_id, user_name,
            relationship=pulse['warmth'] * 0.4,
            trust=pulse['trust'] * 0.4,
            intimacy=pulse['intimacy'] * 0.4,
            event_type=event_type,
            reason='llm_pulse',
            character_id=character_id,
        )
        logger.info('relationship pulse user=%s warmth=%.1f trust=%.1f intimacy=%.1f events=%s',
                    telegram_id, pulse['warmth'], pulse['trust'], pulse['intimacy'], pulse['events'])
    except Exception as exc:
        logger.warning('relationship pulse failed user=%s error=%s', telegram_id, type(exc).__name__)
