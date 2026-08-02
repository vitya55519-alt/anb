from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models.waifu_models import Base
from models.relationship_models import UserCharacterRelationship, RelationshipEvent  # noqa: F401
from models.app_models import User, Message, Memory, Subscription, StarTransaction  # noqa: F401
from models.photo_models import PhotoDailyUsage, PhotoDelivery, PhotoOffer  # noqa: F401
from config import DATABASE_URL

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
Base.metadata.create_all(engine)
