from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from models.waifu_models import Base
from models.relationship_models import UserCharacterRelationship, RelationshipEvent, RelationshipMilestone  # noqa
from models.app_models import User, Message, Memory, CommunicationProfile, CharacterState, CharacterCard, PaymentMethod, Reminder, Subscription, StarTransaction, ProductEvent, UserConsent  # noqa
from models.photo_models import PhotoDailyUsage, PhotoDelivery, PhotoOffer, PhotoLibraryPack, PhotoLibraryItem, UserSeenPhotoPack, UserSeenPhotoItem, AdminPhotoIdea  # noqa
from models.quest_models import UserQuestProgress, QuestReplayOffer  # noqa
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

def _auto_migrate_all_tables():
    """Catch-all schema repair: add any model columns that are missing from existing tables.

    `Base.metadata.create_all()` only creates missing tables; it never alters existing
    tables. This function inspects every table that already exists in the DB, compares
    its columns to the SQLAlchemy model, and runs `ALTER TABLE ... ADD COLUMN` for any
    missing field. Scalar defaults are preserved as DB-level DEFAULTs so existing rows
    get sensible values; non-scalar/callable defaults are skipped and the column is
    added nullable.
    """
    from sqlalchemy import inspect as sa_inspect
    inspector = sa_inspect(engine)
    existing_tables = set(inspector.get_table_names())
    type_compiler = engine.dialect.type_compiler

    def _default_clause(col):
        d = col.default
        if d is None or not getattr(d, 'is_scalar', False):
            return ''
        val = d.arg
        if isinstance(val, bool):
            return ' DEFAULT TRUE' if val else ' DEFAULT FALSE'
        if isinstance(val, (int, float)):
            return f' DEFAULT {val}'
        if isinstance(val, str):
            escaped = val.replace("'", "''")
            return f" DEFAULT '{escaped}'"
        return ''

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        existing = {c['name'] for c in inspector.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            ddl_type = type_compiler.process(col.type)
            default = _default_clause(col)
            stmt = f'ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl_type}{default}'
            with engine.begin() as conn:
                conn.execute(text(stmt))

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
        'voice_anon_mode': f"BOOLEAN DEFAULT {bool_false}",
        'attention_points': 'INTEGER DEFAULT 0',
        'streak_count': 'INTEGER DEFAULT 0',
        'streak_last_date': 'TIMESTAMP',
        'video_free_date': "VARCHAR(10) DEFAULT ''",
        'video_free_used': 'INTEGER DEFAULT 0',
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
    _add_missing_columns('photo_library_items', {
        'linked_video_file_id': 'VARCHAR(512)',
        'linked_video_unique_id': 'VARCHAR(255)',
        'linked_video_caption': 'TEXT',
    })
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
    # V3.13+ card fields were added to the model after the table already existed
    # in production; create_all never alters existing tables, so add them here.
    _add_missing_columns('character_cards', {
        'gender': 'VARCHAR(16)',
        'age': 'INTEGER',
        'short_bio': 'TEXT',
    })
    # Final safety net: any model column missing from an existing table gets added
    # automatically. This prevents future "UndefinedColumn" crashes when new fields
    # are added to models but forgotten in explicit migrations.
    _auto_migrate_all_tables()

init_db()
