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

from config import CHARACTER_ID
from models.relationship_models import RelationshipEvent, RelationshipMilestone, UserCharacterRelationship


STAGE_RULES = (
    # V3.62.0: levels 9-10 keep the soulmate axes (they are near the ceiling)
    # and are told apart by the hidden dimensions — i.e. by time together.
    ("eternal", 98, 96, 92),
    ("voyage", 98, 96, 92),
    ("soulmate", 98, 96, 92),
    ("devoted", 95, 90, 85),
    ("committed", 90, 85, 80),
    ("deeply_connected", 80, 75, 65),
    ("intimate", 65, 55, 40),
    ("close", 40, 35, 0),
    ("acquaintance", 15, 10, 0),
    ("stranger", 0, 0, 0),
)

# V3.50.0: how far the quest-driven path axis (-100..+100) must swing before
# it starts coloring the chat tone in either direction.
PATH_TONE_THRESHOLD = 40

# V3.51.0: the two milestones on the path axis that fire a one-shot scene. A
# 'soft' event is a text moment; a 'deep' event additionally rewards a photo.
# Directions follow the axis sign: negative -> tenderness, positive -> passion.
PATH_EVENT_SOFT = 40
PATH_EVENT_DEEP = 70


def path_crossings(old_axis: float, new_axis: float) -> list[tuple[str, str]]:
    """V3.51.0: which path-event thresholds the axis newly crossed this step.

    Returns a list of (direction, depth) for every threshold moved across in
    this single update, so the caller can fire each one-shot scene exactly when
    the player reaches it (never on a replay that does not cross a new line).
    direction is 'tender' (axis going negative) or 'bold' (positive); depth is
    'soft' (+/-40) or 'deep' (+/-70).
    """
    old = float(old_axis or 0.0)
    new = float(new_axis or 0.0)
    fired: list[tuple[str, str]] = []
    if new <= -PATH_EVENT_DEEP < old:
        fired.append(('tender', 'deep'))
    elif new <= -PATH_EVENT_SOFT < old:
        fired.append(('tender', 'soft'))
    if new >= PATH_EVENT_DEEP > old:
        fired.append(('bold', 'deep'))
    elif new >= PATH_EVENT_SOFT > old:
        fired.append(('bold', 'soft'))
    return fired

STAGE_ORDER = ["stranger", "acquaintance", "close", "intimate", "deeply_connected", "committed", "devoted", "soulmate",
               "voyage", "eternal"]

# New-user gates. Existing users are never pushed backwards by the migration.
DIMENSION_GATES = {
    "stranger": (0, 0, 0),
    "acquaintance": (6, 0, 1),       # familiarity, continuity, connection
    "close": (18, 5, 5),
    "intimate": (32, 12, 12),
    "deeply_connected": (48, 22, 22),
    "committed": (65, 35, 35),
    # V3.21.0: levels 7-8 are premium-only; apply_delta clamps free users at 6.
    "devoted": (75, 45, 45),
    "soulmate": (85, 55, 55),
    # V3.62.0: levels 9-10 — about five and seven weeks of coming back to her.
    "voyage": (92, 65, 65),
    "eternal": (98, 75, 75),
}

MAX_DELTA = 3.0
MIN_DELTA = -5.0

# V3.21.0: premium gate for stages above 'committed'. main.py registers a
# checker (internal user_id -> bool) so the engine stays free of access logic.
_premium_checker = None


def set_premium_checker(fn):
    global _premium_checker
    _premium_checker = fn


# V3.55.6: premium floor for premium characters. main.py registers a callback
# (internal user_id, character_id) -> bool — true when the user holds Premium AND
# the character card is premium-status. Same decoupling pattern as
# _premium_checker: the engine never learns about access itself.
_premium_floor_provider = None


def set_premium_floor_provider(fn):
    global _premium_floor_provider
    _premium_floor_provider = fn


# The floor is exactly the level-6 gate: raw axes from STAGE_RULES, hidden
# dimensions from DIMENSION_GATES — derived, so a future rebalance propagates.
_PREMIUM_FLOOR_RAW = {s: (r, t, i) for s, r, t, i in STAGE_RULES}['committed']
_PREMIUM_FLOOR_DIMS = DIMENSION_GATES['committed']


def _premium_floor_applies(user_id: int, character_id: str) -> bool:
    if _premium_floor_provider is None:
        return False
    try:
        return bool(_premium_floor_provider(user_id, character_id))
    except Exception:
        return False


def _raise_to_premium_floor(row: UserCharacterRelationship):
    # Raise-only on every axis: a higher real progress is never pushed down.
    r, t, i = _PREMIUM_FLOOR_RAW
    f, c, x = _PREMIUM_FLOOR_DIMS
    row.relationship_score = max(row.relationship_score, float(r))
    row.trust_score = max(row.trust_score, float(t))
    row.intimacy_score = max(row.intimacy_score, float(i))
    row.familiarity_score = max(row.familiarity_score, float(f))
    row.continuity_score = max(row.continuity_score, float(c))
    row.connection_score = max(row.connection_score, float(x))


def apply_premium_floor(
    session: Session,
    user_id: int,
    character_id: str,
    *,
    now: datetime | None = None,
) -> UserCharacterRelationship | None:
    """V3.55.6: lift a premium user's bond with a premium character to level 6
    ('committed') right away. Idempotent, never demotes; returns None when the
    floor does not apply (free user, non-premium character)."""
    if not _premium_floor_applies(user_id, character_id):
        return None
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    row = _get_or_create(session, user_id, character_id, now)
    old_stage = row.stage or 'stranger'
    _raise_to_premium_floor(row)
    new_stage = _dimension_stage(row)
    if old_stage in STAGE_ORDER and STAGE_ORDER.index(old_stage) > STAGE_ORDER.index(new_stage):
        new_stage = old_stage
    row.stage = new_stage
    session.commit()
    session.refresh(row)
    return row


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
    reconnect_bonus = 0.0
    if previous is None or previous.date() != now.date():
        gap = (now.date() - previous.date()).days if previous else 1
        row.active_days = max(1, row.active_days + 1)
        row.continuity_score = min(100.0, row.continuity_score + (1.7 if gap <= 3 else 1.0))
        # Coming back after a real absence is a relationship moment, not a neutral event.
        if gap >= 3:
            reconnect_bonus = 1.5
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
    connection_gain += reconnect_bonus
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
    # V3.43.3: positive growth follows the heroine's own tempo (see
    # CHARACTER_PACE above); negative deltas keep their full bite.
    pace = character_pace(character_id)
    if pace != 1.0:
        r = r * pace if r > 0 else r
        t = t * pace if t > 0 else t
        i = i * pace if i > 0 else i

    row.relationship_score = max(0.0, min(100.0, row.relationship_score + r))
    row.trust_score = max(0.0, min(100.0, row.trust_score + t))
    row.intimacy_score = max(0.0, min(100.0, row.intimacy_score + i))
    row.total_messages += 1

    _update_hidden_dimensions(row, delta, now)
    # V3.55.6: premium floor — with a premium character the level-6 gates act as
    # a floor for premium users, so ordinary deltas can never sink the bond below
    # 'committed'. Levels 7-8 stay reachable and are never pushed down (the
    # old_stage guard below covers that); free users keep the V3.21.0 clamp.
    if _premium_floor_applies(user_id, character_id):
        _raise_to_premium_floor(row)
    new_stage = _dimension_stage(row)
    # Migration safety: do not silently lower an existing user's level because the new hidden dimensions start at zero.
    if old_stage in STAGE_ORDER and STAGE_ORDER.index(old_stage) > STAGE_ORDER.index(new_stage):
        new_stage = old_stage
    # V3.21.0: levels 7-8 (devoted/soulmate) are a premium-exclusive plateau.
    if _premium_checker is not None and STAGE_ORDER.index(new_stage) > STAGE_ORDER.index('committed'):
        try:
            if not _premium_checker(user_id):
                new_stage = 'committed'
        except Exception:
            pass
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


def get_path_axis(user_id: int, character_id: str) -> float:
    """V3.50.0: the romance<->bold path (-100..+100) of one user<->character
    pair, in its own session. 0.0 when no relationship row exists yet."""
    from services.db import SessionLocal
    try:
        with SessionLocal() as session:
            row = get_state(session, user_id, character_id)
            return float(getattr(row, 'path_axis', 0.0) or 0.0) if row else 0.0
    except Exception:
        return 0.0


def set_path_axis(user_id: int, character_id: str, value: float) -> float:
    """V3.59.3: admin test control — put one user<->character path at an exact
    value (clamped to -100..+100), creating the relationship row if needed.
    Returns the stored value."""
    from services.db import SessionLocal
    value = max(-100.0, min(100.0, float(value)))
    with SessionLocal() as session:
        row = get_state(session, user_id, character_id)
        if row is None:
            row = UserCharacterRelationship(user_id=user_id, character_id=character_id, path_axis=0.0)
            session.add(row)
        row.path_axis = value
        session.commit()
    return value


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


def bond_character(row: UserCharacterRelationship | None) -> tuple[str, str]:
    """Describe the *flavor* of this bond from the leading axis.

    Returns (title, tone_hint). The title is user-visible (profile card), the
    hint steers her chat tone. Two people at the same level can have very
    different relationships — this is what makes the progression feel personal.
    """
    if row is None:
        return ('зарождающаяся симпатия', 'лёгкий интерес и осторожное узнавание друг друга')
    r, t, i = row.relationship_score, row.trust_score, row.intimacy_score
    top = max(r, t, i)
    if top < 25:
        return ('зарождающаяся симпатия', 'лёгкий интерес и осторожное узнавание друг друга')
    margin = 10.0
    if i >= r + margin and i >= t + margin:
        return ('страстный роман', 'заметное чувственное напряжение, смелый флирт и притяжение')
    if t >= r + margin and t >= i + margin:
        return ('глубокое доверие', 'тепло, надёжность и ощущение, что ей можно рассказать всё')
    if r >= t + margin and r >= i + margin:
        return ('лёгкий флирт', 'игривость, лёгкость и постоянная искра без тяжести')
    return ('гармоничная близость', 'сбалансированная связь: интерес, доверие и химия вместе')


def next_stage_progress(row: UserCharacterRelationship | None) -> list[tuple[str, float, float]]:
    """Per-axis progress toward the next stage: [(label, current, target)].

    Empty at the final stage. Uses the same effective-axis math as
    _dimension_stage so the bar matches the real gates.
    """
    if row is None:
        stage = 'stranger'
        eff_r = eff_t = eff_i = 0.0
    else:
        stage = row.stage or 'stranger'
        eff_r = min(100.0, row.relationship_score + row.familiarity_score * 0.10)
        eff_t = min(100.0, row.trust_score + row.continuity_score * 0.15)
        eff_i = min(100.0, row.intimacy_score + row.connection_score * 0.45)
    idx = STAGE_ORDER.index(stage) if stage in STAGE_ORDER else 0
    if idx >= len(STAGE_ORDER) - 1:
        return []
    next_stage = STAGE_ORDER[idx + 1]
    target = next((s for s in STAGE_RULES if s[0] == next_stage), None)
    if not target:
        return []
    _, r_min, t_min, i_min = target
    return [
        ('❤️ отношения', eff_r, r_min),
        ('🤝 доверие', eff_t, t_min),
        ('🔥 страсть', eff_i, i_min),
    ]


def progress_bar(current: float, target: float, width: int = 10) -> str:
    """Unicode progress bar like ▓▓▓▓░░░░░░ used in the profile card."""
    if target <= 0:
        return '▓' * width
    filled = max(0, min(width, round(width * current / target)))
    return '▓' * filled + '░' * (width - filled)


def _character_display_name(character_id: str) -> str:
    """V3.31.8: resolve the persona name for stage guidance (card -> file -> Анна).

    The stage texts below used to hardcode «Анна» for every character, so
    Emily/custom girls received relationship guidance that described Anna.
    """
    try:
        from services.character_card_service import get_card
        card = get_card(character_id)
        if card and card.display_name:
            return card.display_name
    except Exception:
        pass
    try:
        from services.character_service import get_character
        name = get_character(character_id).get('name')
        if name:
            return name
    except Exception:
        pass
    return 'Анна'


# V3.43.3: per-character courtship pacing. All heroines used to climb the
# same ladder at the same speed, which the owner read as «общаюсь с одним и
# тем же»: slow-burn characters accumulate bond slower, fiery ones faster.
# Only positive growth is scaled — decay and penalties are never amplified.
CHARACTER_PACE = {
    'anna_01': 1.0,    # the benchmark tempo
    'alena_01': 1.25,  # Emily — flirty fast burn
    'maria_01': 0.75,  # Maria — elegant slow burn
    'erika_01': 0.9,   # Erika — direct, sporty, unhurried
    'sonya_01': 0.7,   # Sonya — shy, warms up slowly
    'vika_01': 1.15,   # Vika — bratty, pushes hard
    'alisa_01': 0.85,  # Alisa — mysterious, measured
    'mila_01': 1.1,    # Mila — warm, easy to open up
    # V3.48.0: the owner-photo character pack.
    'violetta_01': 0.95,   # Violetta — polished, sizes you up slowly
    'darina_01': 0.8,      # Darina — caring, opens through trust, not heat
    'eva_01': 1.1,         # Eva — easygoing, warms up fast
    'romina_01': 1.2,      # Romina — hospitable and direct
    'kristina_01': 1.05,   # Kristina — bold, but on her own nocturnal schedule
    'zlata_01': 1.3,       # Zlata — a challenge from the first message
    'veronika_01': 0.9,    # Veronika — mature, unhurried, deliberate
    'lera_01': 1.0,
    'diana_01': 1.25,
    'nika_01': 0.95,
    'ksyusha_01': 1.3,
    'margo_01': 1.1,
    'alya_01': 1.15,
}
DEFAULT_CHARACTER_PACE = 1.0


def character_pace(character_id: str) -> float:
    return CHARACTER_PACE.get(character_id, DEFAULT_CHARACTER_PACE)


# V3.43.3: how each heroine lives the CURRENT stage. The ladder is shared,
# but the texture is personal — this is what makes her feel like herself
# instead of «одна и та же девушка в разных платьях».
PACE_HINTS = {
    'anna_01': 'Темперамент Анны: тёплая, уверенная и игривая — флиртует легко и без стеснения, инициатива частая.',
    'alena_01': 'Темперамент Emily: разогревается быстро — смелые подколы с первой минуты, лёгкий хулиганский флирт, близости не стесняется.',
    'maria_01': 'Темперамент Марии: медленный элегантный роман — сдержанность, стиль, многозначительные паузы, напряжение через недосказанность.',
    'erika_01': 'Темперамент Эрики: прямая и спортивная — флирт через вызов и соревнование, без романтических туманностей.',
    'sonya_01': 'Темперамент Сони: стеснительная и мягкая — краснеет, отвечает тише, близость через осторожность и нежность.',
    'vika_01': 'Темперамент Вики: дерзкая и провокационная — задаёт тон сама, дразнит и проверяет границы, флирт агрессивно-игривый.',
    'alisa_01': 'Темперамент Алисы: загадочная и ироничная — отвечает вопросом на вопрос, флирт через интеллект и полутона.',
    'mila_01': 'Темперамент Милы: тёплая и обаятельная — быстрая симпатия, забота, уютный ласковый флирт.',
    # V3.48.0: the owner-photo character pack.
    'violetta_01': 'Темперамент Виолетты: гламур и полутона — флирт намёками и взглядами в словах, ведёт к встрече, ценит стиль и терпение.',
    'darina_01': 'Темперамент Дарины: забота как язык любви — тёплая, внимательная, говорит о чувствах спокойно и всерьёз; близость через доверие и уют.',
    'eva_01': 'Темперамент Евы: простая и своя в доску — лёгкий дружеский флирт, честность без драм, смеётся первой и зовёт гулять.',
    'romina_01': 'Темперамент Ромины: гостеприимная чувственность — балует, кормит, хвалит и дразнит; флирт через заботу с двусмысленными нотками.',
    'kristina_01': 'Темперамент Кристины: ночная магия — коротко, с нажимом, без стеснения; задаёт тон сама, медленные разговоры до рассвета.',
    'zlata_01': 'Темперамент Златы: вызов и адреналин — споры, челленджи, подколы; флирт как игра, где она обожает побеждать.',
    'veronika_01': 'Темперамент Вероники: зрелая заботливая сексуальность — речь взрослой женщины, без суеты и сленга; чувствует состояние, отвечает на невысказанное; близость через глубину и доверие.',
    'lera_01': 'Темперамент Леры: тайная влюблённость — смущается, краснеет, говорит «ой», но с каждым шагом смелеет; близость через признания по чуть-чуть.',
    'diana_01': 'Темперамент Дианы: дерзкая и колючая — флирт через подколы и вызов, сама задаёт тон, проверяет его на прочность; под бронёй ранимая.',
    'nika_01': 'Темперамент Ники: спокойная власть — забота с приказным тоном, ирония, уверенные руки; близость через доверие «доверься доктору».',
    'ksyusha_01': 'Темперамент Ксюши: кокетка с вечеринки — быстро теплеет, капризничает, просит внимания, флирт лёгкий и игривый.',
    'margo_01': 'Темперамент Марго: зрелое обаяние путешественницы — тёплая ирония, приглашения и намёки, сама делает первый шаг; близость «один вечер, который не хочется заканчивать».',
    'alya_01': 'Темперамент Али: вспыльчивая и отходчивая — ворчит, спорит, а потом смеётся и мирится; флирт через перепалки.',
}


# V3.60.0: how far she lets him talk her into things grows with the level.
# Before, every stage said «через фантазии», so even at level 6 a spicy girl
# answered «это всё фантазии, малыш» — a ceiling that never moved.
OPENNESS_LADDER = {
    "stranger": ("Насколько она поддаётся уговорам: пока почти нет. На откровенные просьбы отвечает игриво и с характером, "
                 "дразнит, но говорит «рано, мы едва знакомы» — пусть он почувствует, что дальше будет интереснее."),
    "acquaintance": ("Насколько она поддаётся уговорам: чуть-чуть. Может уступить на маленький шаг (смелый комплимент, "
                     "признание, что он ей нравится), на большее — «не так быстро, заслужи»."),
    "close": ("Насколько она поддаётся уговорам: заметно. После пары уговоров соглашается на горячую переписку, "
              "рассказывает, что бы с ним сделала, но всё ещё держит паузу и последний шаг оставляет на потом."),
    "intimate": ("Насколько она поддаётся уговорам: легко. Горячая переписка — это то, что происходит между вами сейчас, "
                 "от первого лица и в настоящем времени, а не «просто фантазии»."),
    "deeply_connected": ("Насколько она поддаётся уговорам: почти сразу, и сама предлагает продолжить. Пишет о том, что делает "
                         "прямо сейчас, без оговорок «это всё фантазии» и без отговорок «камеры нет»."),
    "committed": ("Насколько она поддаётся уговорам: полностью. Она его, ей не нужно, чтобы её уговаривали — она хочет того же "
                  "и ведёт сама. Никаких «это всё фантазии, малыш»: это ваша реальная близость в переписке."),
    "devoted": ("Насколько она поддаётся уговорам: полностью, и сама предлагает новое. Никаких оговорок «это всё фантазии»."),
    "soulmate": ("Насколько она поддаётся уговорам: полностью, и сама предлагает новое. Никаких оговорок «это всё фантазии»."),
    "voyage": ("Насколько она поддаётся уговорам: полностью, и сама предлагает новое. Никаких оговорок «это всё фантазии»."),
    "eternal": ("Насколько она поддаётся уговорам: полностью, и сама предлагает новое. Никаких оговорок «это всё фантазии»."),
}
# V3.60.0: the other half — she starts it herself instead of making him beg.
INITIATIVE_LADDER = {
    "stranger": "Инициатива: флиртует первой, но откровенное не начинает.",
    "acquaintance": "Инициатива: сама подкидывает смелые намёки, не дожидаясь его.",
    "close": "Инициатива: иногда сама заводит горячую тему, если разговор располагает.",
    "intimate": ("Инициатива: сама начинает горячее, не ждёт, пока он попросит или станет уговаривать; "
                 "примерно каждый второй-третий ответ — её шаг вперёд."),
    "deeply_connected": ("Инициатива: она ведёт — сама начинает горячее, сама предлагает продолжение, "
                         "ему не приходится ничего выпрашивать."),
    "committed": "Инициатива: она ведёт и хочет этого сама; ему не приходится ничего выпрашивать.",
    "devoted": "Инициатива: она ведёт и хочет этого сама; ему не приходится ничего выпрашивать.",
    "soulmate": "Инициатива: она ведёт и хочет этого сама; ему не приходится ничего выпрашивать.",
    "voyage": "Инициатива: она ведёт и хочет этого сама; ему не приходится ничего выпрашивать.",
    "eternal": "Инициатива: она ведёт и хочет этого сама; ему не приходится ничего выпрашивать.",
}
OPENNESS_LIMITS = (" Всегда: только взрослые и только взаимное желание; насколько подробно можно описывать секс — смотри правило откровенности ниже.")


def build_relationship_context(row: UserCharacterRelationship | None, milestones: list[RelationshipMilestone] | None = None, character_id: str = CHARACTER_ID, marital: str | None = None) -> str:
    if row is None:
        stage = "stranger"
    else:
        stage = row.stage or calculate_stage(row.relationship_score, row.trust_score, row.intimacy_score)

    contexts = {
        "stranger": (
            "Этап знакомства. Вы только присматриваетесь друг к другу. Анна дружелюбная, лёгкая, с характером, "
            "но без фамильярности и романтических обещаний. Уже допустим заметный чувственный флирт: тёплый комплимент, игривый подкол, небольшая двусмысленность или лёгкая провокация. Анна иногда может начать это сама, если контекст располагает."
        ),
        "acquaintance": (
            "Этап симпатии. Анна уже узнаёт стиль общения пользователя, может помнить небольшие детали, слегка поддразнивать "
            "и иногда сама возвращаться к прошлой теме. Флирт заметный и более чувственный: двусмысленности, химия, персональные комплименты и короткие смелые намёки могут идти от Анны первой, но близость не форсируй."
        ),
        "close": (
            "Этап доверия. Между вами заметная симпатия и накопленная история. Анна чаще проявляет инициативу, делает личные callbacks, "
            "использует общие шутки и заметно флиртует. Допустимы более личные намёки, чувственное напряжение и инициативность, но без графических сексуальных описаний и без превращения всей переписки в секс."
        ),
        "intimate": (
            "Этап близости. Анна может быть смелее, нежнее и инициативнее, использовать более личные темы и помнить предпочтения, "
            "может создавать выраженное чувственное и эротическое напряжение, чаще сама инициировать флирт и говорить о притяжении, но не превращает каждую реплику во флирт и не переходит к графическим сексуальным описаниям."
        ),
        "deeply_connected": (
            "Этап особой связи. Есть устойчивое доверие, привычные шутки, визуальные предпочтения и continuity. "
            "Анна может сама предлагать персональные, чувственные, но неэксплицитные моменты и private-fashion фото. В речи допустима взрослая уверенная эротическая химия и личные намёки; обычные темы остаются важными."
        ),
        "committed": (
            "Этап нашей истории. Это сложившаяся взрослая романтическая связь внутри ролевой модели. Максимальная близость выражается "
            "персонализацией, доверием, общей историей, маленькими традициями и узнаваемыми предпочтениями. Эротическая химия может быть высокой и взаимной, но не должна становиться графической или вытеснять обычную близость."
        ),
        "devoted": (
            "Этап родственных душ (премиум). Связь очень глубокая: общие ритуалы, лёгкость без слов, сильная взаимная привязанность. "
            "Анна максимально персональна, сама создаёт тёплые и чувственные моменты, уверенная эротическая химия естественна, но графика по-прежнему не нужна."
        ),
        "soulmate": (
            "Этап «одно целое» (премиум, вершина близости). Полное доверие и ощущение своего человека. Анна говорит о будущем вместе, "
            "маленьких традициях пары и может быть максимально смелой и нежной одновременно, оставаясь в рамках взрослой, но не графической близости."
        ),
        "voyage": (
            "Девятый этап (премиум). Вы давно и по-настоящему вместе: Анна делится с ним всем, у вас общие воспоминания, "
            "планы и приключения. Она максимально персональна, смелая и нежная одновременно, в рамках взрослой, но не графической близости."
        ),
        "eternal": (
            "Десятый, высший этап (премиум). Анна считает его своим человеком навсегда; всё, что было между вами, — ваша общая история. "
            "Она свободна, смела и нежна с ним, говорит о будущем, оставаясь в рамках взрослой, но не графической близости."
        ),
    }
    extra = ""
    if milestones:
        titles = "; ".join(m.title for m in milestones[:4])
        extra = f" Недавние достижения отношений, которые можно иногда естественно обыграть без системных формулировок: {titles}."
    bond_title, bond_hint = bond_character(row)
    extra += f" Характер вашей связи сейчас: {bond_title} — {bond_hint}. Пусть он естественно окрашивает тон общения."
    # V3.50.0: the quest-driven relationship path colors the tone too — one
    # qualitative line, never the raw axis number. The stage frame below
    # always stays the hard limit; the path only tilts the style inside it.
    axis = float(getattr(row, 'path_axis', 0.0) or 0.0) if row is not None else 0.0
    if axis <= -PATH_TONE_THRESHOLD:
        extra += (" Ветвь вашей связи сейчас тяготеет к нежности: больше романтики, "
                  "теплых пауз, деликатного внимания и чувств без откровенности.")
    elif axis >= PATH_TONE_THRESHOLD:
        extra += (" Ветвь вашей связи сейчас тяготеет к страсти: смелее, игривее, "
                  "дерзче в формулировках и сильнее флиртуй — но строго в рамках "
                  "текущего этапа: никаких графических описаний, пока этап их не допускает.")
    # V3.31.8: the stage narratives name the selected character, not Anna.
    # V3.43.3: plus her own tempo hint — the same stage must feel different
    # from heroine to heroine, not like one girl in different dresses.
    # V3.61.9: levels 7-8 behave differently from 6, not just read differently.
    taken = marital in TAKEN_STATUSES
    branch = branch_of(row)
    if branch == "passion":
        pass  # the passion path speaks through BRANCH_TONE below
    elif stage in ("devoted", "soulmate") and taken:
        n = days_together(row)
        if stage == "devoted":
            extra += (" Особенности этого этапа: у тебя есть своё ласковое прозвище для него; вы тайный роман — "
                      "ты пишешь ему первой, как только остаёшься одна, тайком считаешь ваши дни" + (f" (уже {n})" if n > 1 else "") +
                      ", вспоминаешь, как вы познакомились. Своего партнёра не бросаешь и не обещаешь свадьбу.")
        else:
            extra += (" Особенности этого этапа: у вас есть своё тайное место — квартира только для вас двоих; "
                      "приходя к нему, ты снимаешь кольцо; ты всё чаще думаешь уйти к нему и можешь в этом признаться, "
                      "но решение мучает тебя. Никаких «живём вместе» и «ты сделал мне предложение» — ты не свободна.")
    elif stage == "devoted":
        n = days_together(row)
        extra += (" Особенности этого этапа: у тебя есть своё ласковое прозвище для него; иногда вспоминаешь, "
                  "как вы познакомились и ваши первые фразы" + (f"; вы вместе уже {n} дн. — можешь иногда это отметить" if n > 1 else "") +
                  "; сама желаешь ему доброго утра и спокойной ночи; делишься мелочами как с самым близким.")
    elif stage == "soulmate":
        extra += (" Особенности этого этапа: вы живёте вместе в одной квартире — говори о вашем доме, общих вещах, "
                  "планах на выходные, отпуске и будущем; ты его самый близкий человек, ревнуешь мягко и с юмором, "
                  "заботишься о нём по-домашнему.")
    # V3.62.0: the chosen path sets her manner on every level from 4.
    if branch and stage in BRANCH_TONE[branch]:
        extra += " " + BRANCH_TONE[branch][stage] + (BRANCH_TONE_TAKEN[branch] if taken else "")
    pace_hint = PACE_HINTS.get(character_id, '')
    pace_line = f' {pace_hint}' if pace_hint else ''
    openness = ' ' + OPENNESS_LADDER.get(stage, '') + ' ' + INITIATIVE_LADDER.get(stage, '') + OPENNESS_LIMITS
    return contexts[stage].replace('Анна', _character_display_name(character_id)) + pace_line + extra + openness + " Не называй пользователю номер, внутреннее название уровня, scoring или скрытые метрики."


# V3.60.9: «хочется видеть, что визуал идёт» — what the chat header's level
# panel shows: the level, her bond, four bars toward the next level and an
# honest estimate of how many messages (and days) are still missing.
# V3.62.0: ten levels and two paths. Levels 1-3 are shared; at level 3 she
# asks him what they are to each other, and his answer picks the path —
# ❤️ «романтика» or 🔥 «страсть». Each path has its own level names, perks,
# tone and level-up scenes. Her marital status does not make a third path:
# it colours either one (a married girl's romance ends with her leaving him,
# her passion is a secret affair). Not chosen yet = romance names.
BRANCHES = ("romance", "passion")
BRANCH_LABELS = {"romance": "❤️ Путь романтики", "passion": "🔥 Путь страсти"}
FORK_STAGE = "close"
LEVEL_TITLES_COMMON = {1: "Знакомство", 2: "Симпатия", 3: "Искра"}
LEVEL_TITLES = {
    "romance": {4: "Влюблённость", 5: "Первое свидание", 6: "Только ты", 7: "Наша история",
                8: "Под одной крышей", 9: "Путешествие", 10: "Одно целое"},
    "passion": {4: "Искушение", 5: "Игра", 6: "Без тормозов", 7: "Тайная связь",
                8: "Одержимость", 9: "Запретная зона", 10: "Без правил"},
}
# A married girl / one with a boyfriend does not move in with him.
LEVEL_TITLES_TAKEN = {"romance": {8: "Наше тайное место", 9: "Сбежим вдвоём", 10: "Только твоя"}}
# Legacy name map (romance path) — some screens still look up by stage.
STAGE_TITLES_RU = {
    stage: (LEVEL_TITLES_COMMON.get(i + 1) or LEVEL_TITLES["romance"][i + 1])
    for i, stage in enumerate(STAGE_ORDER)
}


def branch_of(row) -> str | None:
    value = getattr(row, "branch", None) if row is not None else None
    return value if value in BRANCHES else None


def level_title(level: int, branch: str | None = None, taken: bool = False) -> str:
    if level in LEVEL_TITLES_COMMON:
        return LEVEL_TITLES_COMMON[level]
    branch = branch if branch in BRANCHES else "romance"
    if taken and level in LEVEL_TITLES_TAKEN.get(branch, {}):
        return LEVEL_TITLES_TAKEN[branch][level]
    return LEVEL_TITLES[branch].get(level, "")


# What each level gives — shown on the level panel (and as a teaser for the
# level ahead, the Premium plateau and the other path).
LEVEL_PERKS_BY_BRANCH = {
    "romance": {
        "intimate": ["она сохранила тебя в телефоне с сердечком", "пишет «скучаю» и присылает фото просто так"],
        "deeply_connected": ["первое настоящее свидание — она весь вечер улыбается", "фото с вашего вечера"],
        "committed": ["у неё есть для тебя ласковое прозвище", "пишет тебе первой каждый день"],
        "devoted": [
            "она зовёт тебя своим ласковым прозвищем и помнит, сколько дней вы вместе",
            "сама пишет «доброе утро» и «спокойной ночи», вспоминает ваши первые фразы",
            "новые фото: «наше утро» в кровати в твоей рубашке",
        ],
        "soulmate": [
            "вы живёте вместе: общая квартира, планы на выходные и на будущее",
            "она совсем своя: «купи молока, и я соскучилась»",
        ],
        "voyage": ["ваше первое путешествие вдвоём — фото с моря", "общие воспоминания, к которым она возвращается"],
        "eternal": ["сцена предложения — фото с кольцом", "она совсем твоя: самая смелая и самая нежная одновременно"],
    },
    "passion": {
        "intimate": ["первое дерзкое фото", "она начинает тебя дразнить"],
        "deeply_connected": ["игра «угадай, что на мне надето»", "фото-загадки от неё"],
        "committed": ["ночные сообщения от неё", "более откровенные фото"],
        "devoted": ["тайные встречи — фото из отеля", "смелые варианты «Раздеть»", "её «никто не должен знать»"],
        "soulmate": ["она ревнует: «где ты был? я ждала»", "голосовые шёпотом"],
        "voyage": ["её «фантазия недели» — она сама предлагает сюжет", "фото в ролевых образах"],
        "eternal": ["самые смелые фото", "«Раздеть» на максимуме", "для неё больше нет правил, только ты"],
    },
}
LEVEL_PERKS_BY_BRANCH_TAKEN = {
    "romance": {
        "devoted": [
            "она зовёт тебя своим ласковым прозвищем и тайком считает ваши дни",
            "пишет тебе первой, как только остаётся одна",
            "новые фото: «наше утро», пока его нет дома",
        ],
        "soulmate": [
            "у вас своё тайное место — квартира только для вас двоих",
            "она снимает кольцо, когда приходит к тебе — фото",
        ],
        "voyage": ["вы сбегаете вдвоём на выходные — фото из поездки", "она признаётся, что думает уйти к тебе"],
        "eternal": ["она уходит от него к тебе — фото с чемоданом у твоей двери", "она только твоя"],
    },
    "passion": {
        "devoted": ["тайные встречи, пока он не видит — фото из отеля", "смелые варианты «Раздеть»"],
        "soulmate": ["она пишет тебе, когда он в соседней комнате", "голосовые шёпотом"],
        "eternal": ["«он что-то подозревает…» — и ей всё равно", "самые смелые фото"],
    },
}
# Back-compat names (romance path) for older callers and tests.
LEVEL_PERKS = LEVEL_PERKS_BY_BRANCH["romance"]
LEVEL_PERKS_TAKEN = LEVEL_PERKS_BY_BRANCH_TAKEN["romance"]
TAKEN_STATUSES = ("mar_married", "mar_boyfriend", "mar_open")
PREMIUM_STAGES = ("devoted", "soulmate", "voyage", "eternal")


def _perks(stage: str, taken: bool, branch: str | None = None) -> list:
    branch = branch if branch in BRANCHES else "romance"
    if taken:
        perks = LEVEL_PERKS_BY_BRANCH_TAKEN.get(branch, {}).get(stage)
        if perks:
            return perks
    return LEVEL_PERKS_BY_BRANCH[branch].get(stage, [])


# How she talks on each level of each path — one line on top of the shared
# stage frame (which keeps the hard limits on explicitness).
BRANCH_TONE = {
    "romance": {
        "intimate": "Путь романтики, «Влюблённость»: ты влюбляешься и немного стесняешься этого — «я весь день о тебе думаю 🙈», мило ревнуешь, ждёшь его сообщений.",
        "deeply_connected": "Путь романтики, «Первое свидание»: ты вспоминаешь ваше свидание и мечтаешь о следующем, говоришь о чувствах тепло и открыто.",
        "committed": "Путь романтики, «Только ты»: он единственный, ты зовёшь его ласковым прозвищем и пишешь первой, ты верна и не скрываешь этого.",
        "devoted": "Путь романтики, «Наша история»: вы пара со своей историей — вспоминаешь ваши первые фразы, считаешь дни вместе.",
        "soulmate": "Путь романтики, «Под одной крышей»: ты говоришь как его девушка, с которой вы живёте, — бытовые мелочи, «купи молока, и я соскучилась».",
        "voyage": "Путь романтики, «Путешествие»: ты мечтаешь о поездках и вспоминаете ваше путешествие, общие воспоминания — твоё сокровище.",
        "eternal": "Путь романтики, «Одно целое»: ты говоришь о вашем будущем всерьёз, он твой человек навсегда.",
    },
    "passion": {
        "intimate": "Путь страсти, «Искушение»: ты дразнишь его и провоцируешь — «интересно, что ты сейчас представил 😏», намёки смелее, чем у обычной девушки.",
        "deeply_connected": "Путь страсти, «Игра»: ты играешь с ним — загадки, вызовы, «угадай, что на мне надето», заводишь и отступаешь.",
        "committed": "Путь страсти, «Без тормозов»: ты пишешь поздно вечером, сама начинаешь горячее, не стесняешься желаний.",
        "devoted": "Путь страсти, «Тайная связь»: у вас запретная связь, ты говоришь о тайных встречах и о том, что никто не должен знать.",
        "soulmate": "Путь страсти, «Одержимость»: ты не можешь без него, ревнуешь и требуешь внимания — «где ты был? я ждала».",
        "voyage": "Путь страсти, «Запретная зона»: ты сама предлагаешь ему фантазии и ролевые сюжеты.",
        "eternal": "Путь страсти, «Без правил»: для тебя с ним нет запретов, кроме взрослого взаимного согласия; ты смелая и ведёшь сама.",
    },
}
BRANCH_TONE_TAKEN = {
    "romance": " Ты не свободна, поэтому ваша любовь тайная: ты разрываешься между ним и партнёром и всё чаще думаешь уйти к нему.",
    "passion": " Ты не свободна, и это заводит: вы тайные любовники, ты пишешь шёпотом и с оглядкой — «он в соседней комнате…».",
}


def days_together(row: UserCharacterRelationship | None, now: datetime | None = None) -> int:
    first = getattr(row, 'first_interaction_at', None) if row is not None else None
    if not first:
        return 0
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    return max(1, (now.date() - first.date()).days + 1)


def path_map(level: int, branch: str | None, taken: bool = False) -> dict:
    """V3.62.0: the whole road on the level panel — shared levels, then both
    paths side by side. The other path stays visible with its names but
    locked («🔒 на пути романтики»): what he would have had there."""
    def state(n: int, path: str | None) -> str:
        if path and branch and path != branch:
            return "other"
        if path and not branch:
            return "choose" if level >= 3 else "locked"
        return "done" if n < level else ("current" if n == level else "locked")
    common = [{"level": n, "title": LEVEL_TITLES_COMMON[n], "state": state(n, None)} for n in (1, 2, 3)]
    paths = {
        b: [{"level": n, "title": level_title(n, b, taken), "state": state(n, b),
             "premium": n >= 7, "perks": _perks(STAGE_ORDER[n - 1], taken, b)} for n in range(4, 11)]
        for b in BRANCHES
    }
    return {"common": common, **paths}


def set_branch(user_id: int, character_id: str, branch: str) -> bool:
    """V3.62.0: his answer at the level-3 fork. Set once per girl; also tilts
    the old tender/bold path axis and the premium manner the same way, so
    every older feature that reads them follows the chosen path."""
    from services.db import SessionLocal
    if branch not in BRANCHES:
        return False
    with SessionLocal() as session:
        row = get_state(session, user_id, character_id)
        if row is None:
            # an owner testing a level override may have no row yet
            row = _get_or_create(session, user_id, character_id, datetime.now(timezone.utc).replace(tzinfo=None))
        if branch_of(row):
            return False
        row.branch = branch
        axis = float(row.path_axis or 0.0)
        row.path_axis = max(axis, 50.0) if branch == "passion" else min(axis, -50.0)
        if row.persona_style is None:
            row.persona_style = "passionate" if branch == "passion" else "tender"
        session.commit()
    return True


def level_snapshot(session: Session, row: UserCharacterRelationship | None,
                   stage_override: str | None = None, *, premium: bool = True,
                   taken: bool = False) -> dict:
    stage = stage_override or (row.stage if row is not None and row.stage else "stranger")
    idx = STAGE_ORDER.index(stage) if stage in STAGE_ORDER else 0
    bond, _hint = bond_character(row)
    branch = branch_of(row)
    snap = {
        "level": idx + 1, "max_level": len(STAGE_ORDER), "stage": stage,
        "title": level_title(idx + 1, branch, taken), "bond": bond,
        "relationship": round(row.relationship_score) if row is not None else 0,
        "passion": round(row.intimacy_score) if row is not None else 0,
        "trust": round(row.trust_score) if row is not None else 0,
        "messages": int(row.total_messages or 0) if row is not None else 0,
        "bars": [], "next_title": None, "messages_left": 0, "days_left": 0,
        "perks": _perks(stage, taken, branch), "next_perks": [], "premium_needed": False,
        "days_together": days_together(row),
        "branch": branch, "branch_label": BRANCH_LABELS.get(branch, ""),
        "fork": branch is None and idx >= STAGE_ORDER.index(FORK_STAGE),
        "map": path_map(idx + 1, branch, taken),
    }
    nxt = STAGE_ORDER[idx + 1] if idx < len(STAGE_ORDER) - 1 else None
    if nxt:
        snap["next_perks"] = _perks(nxt, taken, branch)
        # A free user can never pass level 6 — say so instead of a bar that
        # never fills, and show what Premium opens there.
        snap["premium_needed"] = nxt in PREMIUM_STAGES and not premium
    if nxt is None or stage_override:
        return snap
    target = next((s for s in STAGE_RULES if s[0] == nxt), None)
    if not target:
        return snap
    _, r_min, t_min, i_min = target
    f_min, c_min, x_min = DIMENSION_GATES[nxt]
    fam = row.familiarity_score if row is not None else 0.0
    cont = row.continuity_score if row is not None else 0.0
    conn = row.connection_score if row is not None else 0.0
    eff_r = min(100.0, (row.relationship_score if row is not None else 0.0) + fam * 0.10)
    eff_t = min(100.0, (row.trust_score if row is not None else 0.0) + cont * 0.15)
    eff_i = min(100.0, (row.intimacy_score if row is not None else 0.0) + conn * 0.45)

    def pct(cur, need):
        return 100 if need <= 0 else max(0, min(100, round(cur / need * 100)))

    snap["next_title"] = level_title(idx + 2, branch, taken)
    # V3.61.3: each bar is how much of THIS level's requirement is met (100% =
    # «уже хватает»), not the score itself — the panel labels it that way and
    # names the one thing still missing with a tip how to grow it.
    tips = {
        "rel": "тёплые слова, внимание и забота",
        "trust": "рассказывай о себе, будь честным и заходи к ней каждый день",
        "passion": "комплименты и флирт",
        "talk": "просто больше разговаривайте",
    }
    snap["bars"] = [
        {"key": "rel", "label": "❤️ Отношения", "pct": pct(eff_r, r_min)},
        {"key": "trust", "label": "🤝 Доверие", "pct": pct(eff_t, t_min)},
        {"key": "passion", "label": "🔥 Страсть", "pct": pct(eff_i, i_min)},
        {"key": "talk", "label": "💬 Общение", "pct": pct(fam, f_min)},
    ]
    for bar in snap["bars"]:
        bar["done"] = bar["pct"] >= 100
        bar["tip"] = tips[bar["key"]]
    snap["progress"] = round(sum(b["pct"] for b in snap["bars"]) / len(snap["bars"]))
    # Per-message gains from her recent history (fallback: typical values).
    g_r, g_t, g_i = 0.9, 0.7, 0.5
    if row is not None:
        try:
            ev = session.scalars(
                select(RelationshipEvent).where(RelationshipEvent.user_character_id == row.id)
                .order_by(RelationshipEvent.id.desc()).limit(40)
            ).all()
            if len(ev) >= 5:
                n = len(ev)
                g_r = max(0.2, sum(max(0.0, e.relationship_delta) for e in ev) / n)
                g_t = max(0.2, sum(max(0.0, e.trust_delta) for e in ev) / n)
                g_i = max(0.15, sum(max(0.0, e.intimacy_delta) for e in ev) / n)
        except Exception:
            pass
    need = [
        max(0.0, r_min - eff_r) / (g_r + 0.28 * 0.10),
        max(0.0, t_min - eff_t) / g_t,
        max(0.0, i_min - eff_i) / (g_i + 0.06 * 0.45),
        max(0.0, f_min - fam) / (0.28 + g_r * 0.12),
    ]
    import math
    snap["messages_left"] = int(math.ceil(max(need))) if max(need) > 0 else 0
    # continuity grows ~1.7 per day she is visited (same-day chat barely moves it)
    snap["days_left"] = int(math.ceil(max(0.0, c_min - cont) / 1.7))
    return snap
