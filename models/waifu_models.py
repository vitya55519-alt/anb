from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Float
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Users(Base):
    __tablename__ = "tb_users"

    idUser = Column(Integer, primary_key=True)
    name = Column(String(length=255))
    telegram_id = Column(String(length=255), index=True)
    email = Column(String(length=255))
    waifu_name = Column(String(length=255))
    selected_waifu_role = Column(Integer)
    voice_enabled = Column(Boolean, default=False)
    voice_style = Column(String(length=20), default='nova')
    appearance_description = Column(Text)
    last_active = Column(DateTime)
    proactive_enabled = Column(Boolean, default=True)

class ChatLog(Base):
    __tablename__ = "tb_chat_log"
    idChatLog = Column(Integer, primary_key=True)
    relIdUser = Column(Integer, index=True)
    text = Column(Text)
    timestamp = Column(String(length=50))

class WaifuRoles(Base):
    __tablename__ = "tb_waifu_roles"
    idWaifuRole = Column(Integer, primary_key=True)
    WaifuRole = Column(Text)
    WaifuRoleDescription = Column(String(length=255))

class MemorySummary(Base):
    __tablename__ = "tb_memory_summaries"
    idSummary = Column(Integer, primary_key=True)
    relIdUser = Column(Integer, index=True)
    summary = Column(Text)
    period_start = Column(DateTime)
    period_end = Column(DateTime)
    created_at = Column(DateTime)

class RelationshipState(Base):
    __tablename__ = "tb_relationship_state"
    idRelationship = Column(Integer, primary_key=True)
    relIdUser = Column(Integer, index=True, unique=True)
    total_messages = Column(Integer, default=0)
    first_interaction = Column(DateTime)

class CharacterState(Base):
    """Persistent lightweight state for the character; safe to add with create_all."""
    __tablename__ = "tb_character_state"
    idState = Column(Integer, primary_key=True)
    relIdUser = Column(Integer, index=True, unique=True)
    mood = Column(String(40), default="neutral")
    energy = Column(Float, default=0.7)
    affection = Column(Float, default=0.5)
    playfulness = Column(Float, default=0.5)
    irritation = Column(Float, default=0.0)
    current_activity = Column(String(255), nullable=True)
    current_topic = Column(String(500), nullable=True)
    pending_hook = Column(String(1000), nullable=True)
    language = Column(String(20), default="auto")
    timezone = Column(String(64), default="UTC")
    last_character_action = Column(DateTime, nullable=True)
    last_nudge_at = Column(DateTime, nullable=True)

class MemoryFact(Base):
    __tablename__ = "tb_memory_facts"
    idFact = Column(Integer, primary_key=True)
    relIdUser = Column(Integer, index=True)
    category = Column(String(40), default="fact")
    fact = Column(Text)
    importance = Column(Integer, default=1)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

class Reminder(Base):
    __tablename__ = "tb_reminders"
    idReminder = Column(Integer, primary_key=True)
    relIdUser = Column(Integer, index=True)
    reminder_type = Column(String(30), default="reminder")
    text = Column(Text)
    due_at_utc = Column(DateTime, index=True)
    timezone = Column(String(64), default="UTC")
    active = Column(Boolean, default=True)
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=1)
    last_sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime)
