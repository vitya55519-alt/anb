"""V3.104.0: «память как подарок» — she brings up what he told her, herself.

The bot already keeps ~900 memories (name, work, plans, worries), but they only
sit in the prompt as a list, and she rarely uses them unasked. The strongest
«she knows me» signal is when she returns to a thing on her own: «кстати, как
прошло собеседование?». So:

- when he comes back after a pause (GAP_HOURS or more since his last message),
  at most once per COOLDOWN_HOURS, she gets a director note with ONE concrete
  memory to bring up in this reply — plans and worries first, then work and
  the people close to him, then tastes and jokes;
- a memory is not used again for REPEAT_DAYS and must be at least
  MIN_AGE_HOURS old (no «ты же только что сказал»);
- his name is never «the memory» (it is in the prompt anyway) — but the
  extraction prompt now asks for it, his work and his worries explicitly.

The memory text is quoted to the model only; the event stores the memory id,
never his words. Flag: MEMORY_GIFT_ENABLED.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from models.app_models import Memory, ProductEvent
from services.db import SessionLocal

ENABLED = os.getenv('MEMORY_GIFT_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')
GAP_HOURS = max(1, int(os.getenv('MEMORY_GIFT_GAP_HOURS', '3')))
COOLDOWN_HOURS = max(1, int(os.getenv('MEMORY_GIFT_COOLDOWN_HOURS', '20')))
REPEAT_DAYS = max(1, int(os.getenv('MEMORY_GIFT_REPEAT_DAYS', '7')))
MIN_AGE_HOURS = max(0, int(os.getenv('MEMORY_GIFT_MIN_AGE_HOURS', '4')))
EVENT = 'memory_gift_used'

# lower = brought up first
_TYPE_RANK = {'pending': 0, 'worry': 0, 'promise': 1, 'fact': 2, 'person': 2, 'preference': 3, 'inside_joke': 3}
_NAME_KEY = re.compile(r'(^|_)(name|имя|nickname)($|_)', re.I)

DIRECTIVE = (
    'Режиссёр (собеседнику не показывай и не упоминай): он вернулся после паузы. Сама, без его подсказки, '
    'вспомни то, что он тебе рассказывал: «{memory}». Вплети это в ответ естественно, как девушка, которая '
    'думала о нём, и задай по этому один живой вопрос (как прошло, что решил, как он с этим). Не говори '
    'шаблонно «я помню, ты говорил», не перечисляй факты, не выдумывай подробностей, которых не было. '
    'Если это что-то тяжёлое для него — спроси бережно. Сначала ответь на то, что он написал сейчас.'
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def is_due(last_user_message_at: datetime | None, now: datetime | None = None) -> bool:
    """He is back after a pause (we know when he wrote last)."""
    if not ENABLED or last_user_message_at is None:
        return False
    return (now or _now()) - last_user_message_at >= timedelta(hours=GAP_HOURS)


def _used(session, user_id: int, character_id: str, since: datetime) -> list[ProductEvent]:
    return list(session.scalars(select(ProductEvent).where(
        ProductEvent.user_id == user_id, ProductEvent.character_id == character_id,
        ProductEvent.event_name == EVENT, ProductEvent.created_at >= since)).all())


def pick(user_id: int, character_id: str, now: datetime | None = None) -> tuple[int, str] | None:
    """(memory id, memory text) to bring up now, or None (cooldown / nothing fresh)."""
    if not ENABLED:
        return None
    now = now or _now()
    with SessionLocal() as s:
        recent = _used(s, user_id, character_id, now - timedelta(days=REPEAT_DAYS))
        if any(e.created_at >= now - timedelta(hours=COOLDOWN_HOURS) for e in recent):
            return None
        skip = set()
        for e in recent:
            try:
                skip.add(int(json.loads(e.metadata_json or '{}').get('memory_id') or 0))
            except (ValueError, TypeError):
                continue
        rows = s.scalars(select(Memory).where(
            Memory.user_id == user_id, Memory.character_id == character_id)).all()
        best = None
        for m in rows:
            if m.id in skip or _NAME_KEY.search(m.memory_key or ''):
                continue
            text = (m.content or '').strip()
            if len(text) < 8:
                continue
            created = m.created_at or m.updated_at
            if created and created > now - timedelta(hours=MIN_AGE_HOURS):
                continue
            rank = (_TYPE_RANK.get((m.memory_type or 'fact').lower(), 3), -(m.importance or 0),
                    -((m.updated_at or now).timestamp()))
            if best is None or rank < best[0]:
                best = (rank, m.id, text[:300])
        return (best[1], best[2]) if best else None


def directive(memory_text: str) -> str:
    return DIRECTIVE.format(memory=memory_text.replace('«', '"').replace('»', '"'))


def mark_used(user_id: int, character_id: str, memory_id: int) -> None:
    with SessionLocal() as s:
        s.add(ProductEvent(user_id=user_id, character_id=character_id, event_name=EVENT,
                           metadata_json=json.dumps({'memory_id': int(memory_id)}), created_at=_now()))
        s.commit()
