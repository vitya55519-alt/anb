from datetime import datetime, timezone
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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
