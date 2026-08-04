from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from models.waifu_models import Base
from models.relationship_models import UserCharacterRelationship, RelationshipEvent  # noqa
from models.app_models import User, Message, Memory, CharacterState, Reminder, Subscription, StarTransaction  # noqa
from models.photo_models import PhotoDailyUsage, PhotoDelivery, PhotoOffer  # noqa
from config import DATABASE_URL

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

def _add_missing_columns(table, wanted):
    inspector=inspect(engine)
    if table not in inspector.get_table_names(): return
    existing={c['name'] for c in inspector.get_columns(table)}
    with engine.begin() as conn:
        for name,ddl in wanted.items():
            if name not in existing:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))

def _migrate_existing_users():
    bool_false='FALSE'; bool_true='TRUE'
    wanted={
        'timezone': "VARCHAR(64) DEFAULT 'UTC'",
        'voice_enabled': f"BOOLEAN DEFAULT {bool_false}",
        'voice_style': "VARCHAR(32) DEFAULT 'nova'",
        'proactive_enabled': f"BOOLEAN DEFAULT {bool_true}",
        'appearance_description': 'TEXT',
        'photo_credits': 'INTEGER DEFAULT 0',
    }
    _add_missing_columns('users', wanted)

def init_db():
    Base.metadata.create_all(engine)
    _migrate_existing_users()
    _add_missing_columns('photo_offers', {'request_json': 'TEXT'})

init_db()
