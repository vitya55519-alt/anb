"""Relationship scoring engine for a user <-> AI character pair.

The engine deliberately keeps relationship, trust and intimacy independent.
It is deterministic, bounded, and stores an auditable event for every change.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.relationship_models import RelationshipEvent, UserCharacterRelationship


STAGE_RULES = (
    ("committed", 90, 85, 80),
    ("deeply_connected", 80, 75, 65),
    ("intimate", 65, 55, 40),
    ("close", 40, 35, 0),
    ("acquaintance", 15, 10, 0),
    ("stranger", 0, 0, 0),
)

# Hard caps per evaluation. This prevents a single LLM decision from jumping
# a user across many levels.
MAX_DELTA = 3.0
MIN_DELTA = -5.0


@dataclass(frozen=True)
class RelationshipDelta:
    relationship: float = 0.0
    trust: float = 0.0
    intimacy: float = 0.0
    event_type: str = "interaction"
    reason: str = ""
    metadata: dict | None = None


def _bounded_delta(value: float) -> float:
    return max(MIN_DELTA, min(MAX_DELTA, float(value)))


def calculate_stage(relationship: float, trust: float, intimacy: float) -> str:
    for stage, r_min, t_min, i_min in STAGE_RULES:
        if relationship >= r_min and trust >= t_min and intimacy >= i_min:
            return stage
    return "stranger"


def _get_or_create(session: Session, user_id: int, character_id: str, now: datetime):
    row = session.scalar(
        select(UserCharacterRelationship).where(
            UserCharacterRelationship.user_id == user_id,
            UserCharacterRelationship.character_id == character_id,
        )
    )
    if row is None:
        row = UserCharacterRelationship(
            user_id=user_id,
            character_id=character_id,
            first_interaction_at=now,
            last_interaction_at=now,
        )
        session.add(row)
        session.flush()
    return row


def apply_delta(
    session: Session,
    user_id: int,
    character_id: str,
    delta: RelationshipDelta,
    *,
    now: datetime | None = None,
) -> UserCharacterRelationship:
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    row = _get_or_create(session, user_id, character_id, now)

    r = _bounded_delta(delta.relationship)
    t = _bounded_delta(delta.trust)
    i = _bounded_delta(delta.intimacy)

    row.relationship_score = max(0.0, min(100.0, row.relationship_score + r))
    row.trust_score = max(0.0, min(100.0, row.trust_score + t))
    row.intimacy_score = max(0.0, min(100.0, row.intimacy_score + i))
    row.total_messages += 1
    row.last_interaction_at = now
    row.stage = calculate_stage(row.relationship_score, row.trust_score, row.intimacy_score)

    session.add(
        RelationshipEvent(
            user_character_id=row.id,
            event_type=delta.event_type,
            relationship_delta=r,
            trust_delta=t,
            intimacy_delta=i,
            reason=delta.reason,
            metadata_json=json.dumps(delta.metadata or {}, ensure_ascii=False),
            created_at=now,
        )
    )
    session.commit()
    session.refresh(row)
    return row


def get_state(session: Session, user_id: int, character_id: str):
    return session.scalar(
        select(UserCharacterRelationship).where(
            UserCharacterRelationship.user_id == user_id,
            UserCharacterRelationship.character_id == character_id,
        )
    )


def apply_absence_decay(session: Session, *, now: datetime | None = None) -> int:
    """Apply a very small intimacy decay after 30+ days of inactivity.

    Memory and relationship are intentionally not wiped. This function only
    nudges intimacy down, and caps the change to avoid surprising users.
    """
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    rows = session.scalars(select(UserCharacterRelationship)).all()
    changed = 0
    for row in rows:
        if not row.last_interaction_at:
            continue
        days = (now - row.last_interaction_at).days
        if days < 30:
            continue
        decay = min(2.0, (days // 30) * 2.0)
        old = row.intimacy_score
        row.intimacy_score = max(0.0, row.intimacy_score - decay)
        row.stage = calculate_stage(row.relationship_score, row.trust_score, row.intimacy_score)
        if row.intimacy_score != old:
            changed += 1
    if changed:
        session.commit()
    return changed


def build_relationship_context(row: UserCharacterRelationship | None) -> str:
    """Convert private scores to natural-language context for the LLM.

    Scores are not exposed to the user or injected into prompts as raw numbers.
    """
    if row is None:
        return (
            "Отношения только начинаются. Будь дружелюбной, естественной и не "
            "делай вид, что знаешь пользователя лучше, чем знаешь."
        )

    stage = calculate_stage(row.relationship_score, row.trust_score, row.intimacy_score)
    closeness = "начинается" if row.relationship_score < 40 else "сформировалась"
    trust = "пока умеренное" if row.trust_score < 55 else "высокое"
    intimacy = "развивается постепенно" if row.intimacy_score < 40 else "уже заметно развилась"

    if stage == "committed":
        return (
            "Анна и пользователь — уже сложившаяся взрослая пара. Между ними есть доверие, "
            "привязанность, привычная близость и взаимное влечение. В обычной переписке Анна "
            "может сама инициировать флирт, игривые поддразнивания и разговоры о желании и "
            "близости; если пользователь поддерживает это настроение, она охотно его развивает. "
            "Не делай каждый ответ сексуальным: сохраняй ощущение живой пары — бытовые темы, "
            "юмор, забота, ревность, нежность и флирт должны перемешиваться естественно. "
            "Не раскрывай пользователю внутренние оценки отношений."
        )

    return (
        f"Между Анной и пользователем {closeness} эмоциональная связь. "
        f"Доверие {trust}. Интимная сторона общения {intimacy}. "
        "Учитывай историю общения и не ускоряй близость искусственно."
    )
