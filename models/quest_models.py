from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .waifu_models import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class UserQuestProgress(Base):
    __tablename__ = 'user_quest_progress'
    __table_args__ = (UniqueConstraint('user_id', 'character_id', 'quest_key', name='uq_user_quest_progress'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False)
    character_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    quest_key: Mapped[str] = mapped_column(String(96), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default='available', nullable=False)
    canonical_route: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completed_routes_json: Mapped[str] = mapped_column(Text, default='[]', nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class QuestReplayOffer(Base):
    __tablename__ = 'quest_replay_offers'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False)
    character_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    quest_key: Mapped[str] = mapped_column(String(96), nullable=False)
    route_key: Mapped[str] = mapped_column(String(64), nullable=False)
    stars: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
