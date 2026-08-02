from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .waifu_models import Base


class UserCharacterRelationship(Base):
    __tablename__ = "user_character_relationships"
    __table_args__ = (
        UniqueConstraint("user_id", "character_id", name="uq_user_character_relationship"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    character_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    relationship_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    trust_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    intimacy_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    stage: Mapped[str] = mapped_column(String(32), default="stranger", nullable=False)

    first_interaction_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_interaction_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total_messages: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consecutive_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class RelationshipEvent(Base):
    __tablename__ = "relationship_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_character_id: Mapped[int] = mapped_column(
        ForeignKey("user_character_relationships.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    relationship_delta: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    trust_delta: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    intimacy_delta: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)
