from datetime import datetime, timezone
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .waifu_models import Base

def utcnow(): return datetime.now(timezone.utc).replace(tzinfo=None)

class PhotoDailyUsage(Base):
    __tablename__='photo_daily_usage'
    __table_args__=(UniqueConstraint('user_id','character_id','usage_date',name='uq_photo_daily_usage'),)
    id:Mapped[int]=mapped_column(Integer,primary_key=True)
    user_id:Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True,nullable=False)
    character_id:Mapped[str]=mapped_column(String(64),index=True,nullable=False)
    usage_date:Mapped[Date]=mapped_column(Date,index=True,nullable=False)
    free_used:Mapped[int]=mapped_column(Integer,default=0,nullable=False)
    paid_used:Mapped[int]=mapped_column(Integer,default=0,nullable=False)

class PhotoDelivery(Base):
    __tablename__='photo_deliveries'
    id:Mapped[int]=mapped_column(Integer,primary_key=True)
    user_id:Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True,nullable=False)
    character_id:Mapped[str]=mapped_column(String(64),index=True,nullable=False)
    scene:Mapped[str]=mapped_column(String(32),nullable=False)
    delivery_type:Mapped[str]=mapped_column(String(16),nullable=False)
    telegram_file_id:Mapped[str|None]=mapped_column(String(512),nullable=True)
    image_url:Mapped[str|None]=mapped_column(Text,nullable=True)
    provider:Mapped[str|None]=mapped_column(String(32),nullable=True)
    estimated_cost_usd:Mapped[float]=mapped_column(Float,default=0.0,nullable=False)
    # Raw image bytes for paid full-resolution gallery downloads. Nullable so
    # existing rows (delivered before v3.16.7) keep working.
    full_resolution_bytes:Mapped[bytes|None]=mapped_column(LargeBinary,nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime,default=utcnow,nullable=False,index=True)

class PhotoOffer(Base):
    __tablename__='photo_offers'
    id:Mapped[int]=mapped_column(Integer,primary_key=True)
    user_id:Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True,nullable=False)
    character_id:Mapped[str]=mapped_column(String(64),index=True,nullable=False)
    scene:Mapped[str]=mapped_column(String(32),nullable=False)
    request_json:Mapped[str|None]=mapped_column(Text,nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime,default=utcnow,nullable=False)
    expires_at:Mapped[datetime]=mapped_column(DateTime,nullable=False)
    consumed:Mapped[bool]=mapped_column(Boolean,default=False,nullable=False)

class PhotoLibraryPack(Base):
    __tablename__ = 'photo_library_packs'
    __table_args__ = (UniqueConstraint('character_id', 'pack_key', name='uq_photo_library_pack_key'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    character_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    scene: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    relationship_level: Mapped[int] = mapped_column(Integer, default=1, index=True, nullable=False)
    pack_kind: Mapped[str] = mapped_column(String(16), default='progression', nullable=False)  # progression | collection
    pack_key: Mapped[str] = mapped_column(String(128), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)


class PhotoLibraryItem(Base):
    __tablename__ = 'photo_library_items'
    __table_args__ = (UniqueConstraint('pack_id', 'position', name='uq_photo_library_item_position'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pack_id: Mapped[int] = mapped_column(ForeignKey('photo_library_packs.id', ondelete='CASCADE'), index=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    tier: Mapped[str] = mapped_column(String(16), default='single', nullable=False)  # base | stylish | premium | single
    telegram_file_id: Mapped[str] = mapped_column(String(512), nullable=False)
    telegram_file_unique_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional owner-uploaded video paired with this exact library photo.
    # Telegram file_id keeps the media persistent across Railway redeploys.
    linked_video_file_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    linked_video_unique_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    linked_video_caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class UserSeenPhotoPack(Base):
    __tablename__ = 'user_seen_photo_packs'
    __table_args__ = (UniqueConstraint('user_id', 'pack_id', name='uq_user_seen_photo_pack'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False)
    pack_id: Mapped[int] = mapped_column(ForeignKey('photo_library_packs.id', ondelete='CASCADE'), index=True, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    times_seen: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

class UserSeenPhotoItem(Base):
    __tablename__ = 'user_seen_photo_items'
    __table_args__ = (UniqueConstraint('user_id', 'photo_item_id', name='uq_user_seen_photo_item'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False)
    photo_item_id: Mapped[int] = mapped_column(ForeignKey('photo_library_items.id', ondelete='CASCADE'), index=True, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    times_seen: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class AdminPhotoIdea(Base):
    """Photo ideas added through the Telegram admin panel.

    The curated JSON bank ships with the code; these rows live in PostgreSQL so
    admin additions survive Railway redeployments.
    """
    __tablename__ = 'admin_photo_ideas'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scene: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    location: Mapped[str] = mapped_column(Text, nullable=False)
    angle: Mapped[str] = mapped_column(Text, default='', nullable=False)
    created_by: Mapped[str] = mapped_column(String(32), default='', nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
