from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from models.waifu_models import Base
from models.relationship_models import UserCharacterRelationship, RelationshipEvent, RelationshipMilestone  # noqa
from models.app_models import User, Message, Memory, CommunicationProfile, CharacterState, Reminder, Subscription, StarTransaction, ProductEvent  # noqa
from models.photo_models import PhotoDailyUsage, PhotoDelivery, PhotoOffer, PhotoLibraryPack, PhotoLibraryItem, UserSeenPhotoPack  # noqa
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
        'adult_confirmed': f"BOOLEAN DEFAULT {bool_false}",
    }
    _add_missing_columns('users', wanted)

def init_db():
    Base.metadata.create_all(engine)
    _migrate_existing_users()
    _add_missing_columns('character_states', {
        'recent_outfits_json': "TEXT DEFAULT '[]'",
        'recent_hairstyles_json': "TEXT DEFAULT '[]'",
    })
    _add_missing_columns('communication_profiles', {'visual_json': "TEXT DEFAULT '{}'"})
    _add_missing_columns('photo_offers', {'request_json': 'TEXT'})
    _add_missing_columns('photo_deliveries', {
        'provider': 'VARCHAR(32)',
        'estimated_cost_usd': 'FLOAT DEFAULT 0',
    })
    _add_missing_columns('user_character_relationships', {
        'familiarity_score': 'FLOAT DEFAULT 0',
        'continuity_score': 'FLOAT DEFAULT 0',
        'connection_score': 'FLOAT DEFAULT 0',
        'last_distinct_day': 'TIMESTAMP',
        'active_days': 'INTEGER DEFAULT 0',
    })

init_db()
