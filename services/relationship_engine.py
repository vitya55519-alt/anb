"""Relationship scoring engine for a user <-> AI character pair.

V3.9.1 keeps six visible stages but internally tracks multiple dimensions:
relationship, trust, intimacy, familiarity, continuity and connection.
Raw scores are private implementation details; users see only natural stage names/milestones.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.relationship_models import RelationshipEvent, RelationshipMilestone, UserCharacterRelationship


STAGE_RULES = (
    ("committed", 90, 85, 80),
    ("deeply_connected", 80, 75, 65),
    ("intimate", 65, 55, 40),
    ("close", 40, 35, 0),
    ("acquaintance", 15, 10, 0),
    ("stranger", 0, 0, 0),
)

STAGE_ORDER = ["stranger", "acquaintance", "close", "intimate", "deeply_connected", "committed"]

# New-user gates. Existing users are never pushed backwards by the migration.
DIMENSION_GATES = {
    "stranger": (0, 0, 0),
    "acquaintance": (6, 0, 1),       # familiarity, continuity, connection
    "close": (18, 5, 5),
    "intimate": (32, 12, 12),
    "deeply_connected": (48, 22, 22),
    "committed": (65, 35, 35),
}

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
    """Legacy-compatible three-axis stage calculator (kept for tests/admin tooling)."""
    for stage, r_min, t_min, i_min in STAGE_RULES:
        if relationship >= r_min and trust >= t_min and intimacy >= i_min:
            return stage
    return "stranger"


def _dimension_stage(row: UserCharacterRelationship) -> str:
    # The hidden dimensions reinforce, but do not replace, the original axes.
    # This lets sustained continuity/callbacks matter without turning raw message count into a level-up button.
    effective_relationship = min(100.0, row.relationship_score + row.familiarity_score * 0.10)
    effective_trust = min(100.0, row.trust_score + row.continuity_score * 0.15)
    effective_intimacy = min(100.0, row.intimacy_score + row.connection_score * 0.45)
    base = calculate_stage(effective_relationship, effective_trust, effective_intimacy)
    base_index = STAGE_ORDER.index(base)
    for idx in range(base_index, -1, -1):
        stage = STAGE_ORDER[idx]
        f, c, x = DIMENSION_GATES[stage]
        if row.familiarity_score >= f and row.continuity_score >= c and row.connection_score >= x:
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
            last_distinct_day=now,
            active_days=1,
        )
        session.add(row)
        session.flush()
    return row


def _update_hidden_dimensions(row: UserCharacterRelationship, delta: RelationshipDelta, now: datetime):
    # Familiarity grows slowly with real interaction and cannot be farmed quickly by one long message.
    row.familiarity_score = min(100.0, row.familiarity_score + min(1.0, 0.28 + max(0.0, delta.relationship) * 0.12))

    previous = row.last_distinct_day or row.last_interaction_at
    if previous is None or previous.date() != now.date():
        gap = (now.date() - previous.date()).days if previous else 1
        row.active_days = max(1, row.active_days + 1)
        row.continuity_score = min(100.0, row.continuity_score + (1.7 if gap <= 3 else 1.0))
        if gap == 1:
            row.consecutive_days = max(1, row.consecutive_days + 1)
        else:
            row.consecutive_days = 1
        row.last_distinct_day = now
    elif row.total_messages and row.total_messages % 12 == 0:
        # A substantial same-day conversation gets a tiny continuity signal, but cannot replace returning.
        row.continuity_score = min(100.0, row.continuity_score + 0.2)

    connection_gain = 0.06 if delta.event_type == 'interaction' else 0.0
    if delta.event_type in {"care", "warm_flirt", "callback", "inside_joke", "meaningful_share", "photo_feedback"}:
        connection_gain += 0.8
    if delta.trust > 0:
        connection_gain += min(0.6, delta.trust * 0.18)
    if delta.intimacy > 0:
        connection_gain += min(0.6, delta.intimacy * 0.18)
    if delta.event_type == "negative_interaction":
        connection_gain -= 0.8
    row.connection_score = max(0.0, min(100.0, row.connection_score + connection_gain))


def _ensure_milestones(session: Session, row: UserCharacterRelationship, now: datetime):
    candidates: list[tuple[str, str]] = []
    if row.total_messages >= 10:
        candidates.append(("messages_10", "Первый настоящий разговор"))
    if row.total_messages >= 50:
        candidates.append(("messages_50", "Уже накопилась своя история"))
    if row.active_days >= 3:
        candidates.append(("active_days_3", "Вернулись друг к другу несколько дней"))
    if row.active_days >= 7:
        candidates.append(("active_days_7", "Неделя общей истории"))
    if row.consecutive_days >= 3:
        candidates.append(("streak_3", "Три дня подряд на связи"))
    if row.connection_score >= 10:
        candidates.append(("connection_10", "Появились узнаваемые привычки общения"))
    if row.connection_score >= 25:
        candidates.append(("connection_25", "Связь стала действительно персональной"))

    created: list[str] = []
    for key, title in candidates:
        exists = session.scalar(select(RelationshipMilestone).where(
            RelationshipMilestone.user_character_id == row.id,
            RelationshipMilestone.milestone_key == key,
        ))
        if exists:
            continue
        session.add(RelationshipMilestone(
            user_character_id=row.id,
            milestone_key=key,
            title=title,
            metadata_json=json.dumps({"stage": row.stage}, ensure_ascii=False),
            achieved_at=now,
        ))
        created.append(key)
    return created


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
    old_stage = row.stage or "stranger"

    r = _bounded_delta(delta.relationship)
    t = _bounded_delta(delta.trust)
    i = _bounded_delta(delta.intimacy)

    row.relationship_score = max(0.0, min(100.0, row.relationship_score + r))
    row.trust_score = max(0.0, min(100.0, row.trust_score + t))
    row.intimacy_score = max(0.0, min(100.0, row.intimacy_score + i))
    row.total_messages += 1

    _update_hidden_dimensions(row, delta, now)
    new_stage = _dimension_stage(row)
    # Migration safety: do not silently lower an existing user's level because the new hidden dimensions start at zero.
    if old_stage in STAGE_ORDER and STAGE_ORDER.index(old_stage) > STAGE_ORDER.index(new_stage):
        new_stage = old_stage
    row.stage = new_stage
    row.last_interaction_at = now

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
    _ensure_milestones(session, row, now)
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


def get_milestones(session: Session, row: UserCharacterRelationship | None, limit: int = 4) -> list[RelationshipMilestone]:
    if row is None:
        return []
    return list(session.scalars(
        select(RelationshipMilestone)
        .where(RelationshipMilestone.user_character_id == row.id)
        .order_by(RelationshipMilestone.achieved_at.desc())
        .limit(limit)
    ).all())


def apply_absence_decay(session: Session, *, now: datetime | None = None) -> int:
    """V3.9.1: absence never lowers relationship level or erases earned connection."""
    return 0


def build_relationship_context(row: UserCharacterRelationship | None, milestones: list[RelationshipMilestone] | None = None) -> str:
    if row is None:
        stage = "stranger"
    else:
        stage = row.stage or calculate_stage(row.relationship_score, row.trust_score, row.intimacy_score)

    contexts = {
        "stranger": (
            "Этап знакомства. Вы только присматриваетесь друг к другу. Анна дружелюбная, лёгкая, с характером, "
            "но без фамильярности и романтических обещаний. Флирт редкий и очень лёгкий."
        ),
        "acquaintance": (
            "Этап симпатии. Анна уже узнаёт стиль общения пользователя, может помнить небольшие детали, слегка поддразнивать "
            "и иногда сама возвращаться к прошлой теме. Тепла больше, но близость не форсируй."
        ),
        "close": (
            "Этап доверия. Между вами заметная симпатия и накопленная история. Анна чаще проявляет инициативу, делает личные callbacks, "
            "использует общие шутки и иногда флиртует, но остаётся естественной."
        ),
        "intimate": (
            "Этап близости. Анна может быть смелее, нежнее и инициативнее, использовать более личные темы и помнить предпочтения, "
            "но не превращает каждую реплику во флирт и не ускоряет отношения искусственно."
        ),
        "deeply_connected": (
            "Этап особой связи. Есть устойчивое доверие, привычные шутки, визуальные предпочтения и continuity. "
            "Анна может сама предлагать персональные, но неэксплицитные fashion-моменты. Обычные темы остаются важными."
        ),
        "committed": (
            "Этап нашей истории. Это сложившаяся взрослая романтическая связь внутри ролевой модели. Максимальная близость выражается "
            "персонализацией, доверием, общей историей, маленькими традициями и узнаваемыми предпочтениями, а не постоянной сексуализацией."
        ),
    }
    extra = ""
    if milestones:
        titles = "; ".join(m.title for m in milestones[:4])
        extra = f" Недавние достижения отношений, которые можно иногда естественно обыграть без системных формулировок: {titles}."
    return contexts[stage] + extra + " Не называй пользователю номер, внутреннее название уровня, scoring или скрытые метрики."
