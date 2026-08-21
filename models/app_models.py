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
    voice_anon_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    proactive_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    appearance_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_credits: Mapped[int] = mapped_column(Integer, default=0)
    attention_points: Mapped[int] = mapped_column(Integer, default=0)
    streak_count: Mapped[int] = mapped_column(Integer, default=0)
    streak_last_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    video_free_date: Mapped[str] = mapped_column(String(10), default="")
    video_free_used: Mapped[int] = mapped_column(Integer, default=0)
    adult_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)

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


class CommunicationProfile(Base):
    __tablename__ = "communication_profiles"
    __table_args__ = (UniqueConstraint("user_id", "character_id", name="uq_communication_profile"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    character_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    preferred_language: Mapped[str] = mapped_column(String(16), default="auto")
    language_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_message_length: Mapped[float] = mapped_column(Float, default=0.0)
    emoji_rate: Mapped[float] = mapped_column(Float, default=0.0)
    question_rate: Mapped[float] = mapped_column(Float, default=0.0)
    uppercase_rate: Mapped[float] = mapped_column(Float, default=0.0)
    slang_level: Mapped[float] = mapped_column(Float, default=0.0)
    style_json: Mapped[str] = mapped_column(Text, default="{}")
    slang_json: Mapped[str] = mapped_column(Text, default="[]")
    token_counts_json: Mapped[str] = mapped_column(Text, default="{}")
    visual_json: Mapped[str] = mapped_column(Text, default="{}")
    last_analyzed_count: Mapped[int] = mapped_column(Integer, default=0)
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
    attention_points: Mapped[int] = mapped_column(Integer, default=0)
    activity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    outfit: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hairstyle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recent_outfits_json: Mapped[str] = mapped_column(Text, default='[]')
    recent_hairstyles_json: Mapped[str] = mapped_column(Text, default='[]')
    pending_hook: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_nudge_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class CharacterCard(Base):
    __tablename__ = "character_cards"
    character_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    gender: Mapped[str] = mapped_column(String(16), default="female")
    age: Mapped[int] = mapped_column(Integer, default=18)
    short_bio: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="soon")
    button_emoji: Mapped[str] = mapped_column(String(16), default="👩")
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    card_photo_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PaymentMethod(Base):
    __tablename__ = "payment_methods"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    method_key: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    method_type: Mapped[str] = mapped_column(String(24), default="qr")
    status: Mapped[str] = mapped_column(String(24), default="disabled")
    scope: Mapped[str] = mapped_column(String(32), default="external_only")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    qr_photo_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    instructions: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
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
    provider: Mapped[str] = mapped_column(String(32), default="stars")
    provider_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WalletPayTransaction(Base):
    __tablename__ = "wallet_pay_transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    invoice_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    product: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_usd: Mapped[float] = mapped_column(Float, nullable=False)
    stars_equivalent: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Achievement(Base):
    __tablename__ = "achievements"
    __table_args__ = (UniqueConstraint("user_id", "achievement_key", name="uq_user_achievement"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    achievement_key: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    unlocked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ProductEvent(Base):
    __tablename__ = "product_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    character_id: Mapped[str] = mapped_column(String(64), index=True, default="anna_01")
    event_name: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    value: Mapped[float] = mapped_column(Float, default=0.0)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

class UserConsent(Base):
    __tablename__ = 'user_consents'
    __table_args__ = (UniqueConstraint('user_id', name='uq_user_consent'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    terms_version: Mapped[str] = mapped_column(String(32), default='2026-08-14')
    privacy_version: Mapped[str] = mapped_column(String(32), default='2026-08-14')
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
