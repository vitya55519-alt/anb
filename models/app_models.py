from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .waifu_models import Base

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_active_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    memory_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    voice_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    voice_style: Mapped[str] = mapped_column(String(32), default="nova")
    proactive_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    appearance_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_credits: Mapped[int] = mapped_column(Integer, default=0)

class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    character_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

class Memory(Base):
    __tablename__ = "memories"
    __table_args__ = (UniqueConstraint("user_id", "character_id", "memory_key", name="uq_memory_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    character_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    memory_type: Mapped[str] = mapped_column(String(32), default="fact")
    memory_key: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.7)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

class CharacterState(Base):
    __tablename__ = "character_states"
    __table_args__ = (UniqueConstraint("user_id", "character_id", name="uq_character_state"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    character_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    mood: Mapped[str] = mapped_column(String(32), default="neutral")
    energy: Mapped[float] = mapped_column(Float, default=0.65)
    affection: Mapped[float] = mapped_column(Float, default=0.45)
    playfulness: Mapped[float] = mapped_column(Float, default=0.55)
    irritation: Mapped[float] = mapped_column(Float, default=0.0)
    activity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    outfit: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hairstyle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pending_hook: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_nudge_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

class Reminder(Base):
    __tablename__ = "reminders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    reminder_type: Mapped[str] = mapped_column(String(32), default="reminder")
    text: Mapped[str] = mapped_column(Text)
    due_at_utc: Mapped[datetime] = mapped_column(DateTime, index=True)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    plan: Mapped[str] = mapped_column(String(32), default="premium")
    status: Mapped[str] = mapped_column(String(32), default="active")
    stars_amount: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    telegram_charge_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

class StarTransaction(Base):
    __tablename__ = "star_transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(32), nullable=False)
    product: Mapped[str] = mapped_column(String(64), nullable=False)
    stars: Mapped[int] = mapped_column(Integer, nullable=False)
    telegram_charge_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
