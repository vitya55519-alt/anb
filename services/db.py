from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
import logging

logger = logging.getLogger(__name__)
from models.waifu_models import Base
from models.relationship_models import UserCharacterRelationship, RelationshipEvent, RelationshipMilestone  # noqa
from models.app_models import User, Message, Memory, CommunicationProfile, CharacterState, CharacterCard, PaymentMethod, Reminder, Subscription, StarTransaction, ProductEvent, UserConsent, BackgroundJob, UserGeneration, DialogSession, Referral, PartnerTransaction, PromoCode, ConstructorDraft, AchievementBadge, ProactivePhoto, PageGalleryShot, CardOverride, AdminTestStage, ChatGuest, WardrobeOwned, WardrobeState, GiftOwned, GiftState  # noqa
from models.photo_models import PhotoDailyUsage, PhotoDelivery, PhotoOffer, PhotoLibraryPack, PhotoLibraryItem, UserSeenPhotoPack, UserSeenPhotoItem, AdminPhotoIdea  # noqa
from models.quest_models import UserQuestProgress, QuestReplayOffer  # noqa
from config import DATABASE_URL, PEACH_SCALE

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
# V3.57.2: the Mini App offloads blocking reads to a 16-thread executor, so the
# pool must not starve at the default 5+10 — Railway's Postgres round-trip is
# tens of ms and a cold connection costs a full new TCP+auth handshake.
_pool_kwargs = {} if DATABASE_URL.startswith("sqlite") else {"pool_size": 10, "max_overflow": 20, "pool_recycle": 1800}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True, **_pool_kwargs)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

def _ensure_migration_ledger(conn) -> None:
    """V3.167.5 §10: журнал миграций был нужен и раньше (_rescale_peaches), но
    каждая миграция создавала таблицу сама. Теперь табка одна и она же отвечает
    за идемпотентность: имя миграции = первичный ключ, повторный старт просто
    ничего не добавляет."""
    conn.execute(text(
        'CREATE TABLE IF NOT EXISTS app_migrations ('
        'name VARCHAR(64) PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'))


def _already_applied(conn, name: str) -> bool:
    return bool(conn.execute(text('SELECT 1 FROM app_migrations WHERE name = :n'),
                             {'n': str(name)[:64]}).first())


def _mark_applied(conn, name: str) -> None:
    conn.execute(text('INSERT INTO app_migrations (name) VALUES (:n)'), {'n': str(name)[:64]})


def _rows_in(conn, table: str) -> int:
    """Сколько строк было в таблице на момент миграции — «лог строк» ТЗ: по нему
    видно, задела ли миграция что-то живое, и тот же номер попадет в журнал."""
    try:
        return int(conn.execute(text(f'SELECT COUNT(*) FROM {table}')).scalar() or 0)
    except Exception:
        return -1


def _begin_sqlite_ddl(conn) -> None:
    # SQLite's legacy driver does not begin transactions for DDL or SELECT.
    if conn.dialect.name == 'sqlite' and not conn.connection.driver_connection.in_transaction:
        conn.exec_driver_sql('BEGIN')


def _add_missing_columns(table, wanted):
    inspector=inspect(engine)
    if table not in inspector.get_table_names(): return
    existing={c['name'] for c in inspector.get_columns(table)}
    missing={name: ddl for name, ddl in wanted.items() if name not in existing}
    if not missing:
        return
    # V3.167.5 §10: одна транзакция на таблицу + запись в журнал и в лог.
    # Полупустая таблица после половины ALTER быть не должно: упал — откатилось
    # всё, следующий старт повторит целиком.
    with engine.begin() as conn:
        _begin_sqlite_ddl(conn)
        _ensure_migration_ledger(conn)
        rows = _rows_in(conn, table)
        added = []
        for name, ddl in missing.items():
            marker = f'schema:{table}:{name}'
            if _already_applied(conn, marker):
                continue
            conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))
            _mark_applied(conn, marker)
            added.append(name)
        if added:
            logger.warning('schema %s: +%s (rows=%s)', table, ','.join(added), rows)

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

    added_by_table = {}
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        existing = {c['name'] for c in inspector.get_columns(table.name)}
        missing = [col for col in table.columns if col.name not in existing]
        if not missing:
            continue
        # V3.167.5 §10: одна транзакция на таблицу, каждая колонка — со своей
        # записью в журнале (имя = PRIMARY KEY, значит повторный старт их просто
        # пропустит), и всё это видно в логе вместе с числом строк.
        with engine.begin() as conn:
            _begin_sqlite_ddl(conn)
            _ensure_migration_ledger(conn)
            rows = _rows_in(conn, table.name)
            added = []
            for col in missing:
                marker = f'schema:{table.name}:{col.name}'
                if _already_applied(conn, marker):
                    continue
                ddl_type = type_compiler.process(col.type)
                default = _default_clause(col)
                stmt = f'ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl_type}{default}'
                conn.execute(text(stmt))
                _mark_applied(conn, marker)
                added.append(col.name)
            if added:
                added_by_table[table.name] = added
                logger.warning('auto schema %s: +%s (rows=%s)', table.name, ','.join(added), rows)
    return added_by_table

_ENGAGEMENT_LOG_MIGRATION = 'engagement_log_views_v1'


def _migrate_engagement_logs() -> None:
    """Expose named logs without copying the canonical ProductEvent stream."""
    with engine.begin() as conn:
        _begin_sqlite_ddl(conn)
        _ensure_migration_ledger(conn)
        if _already_applied(conn, _ENGAGEMENT_LOG_MIGRATION):
            return
        _mark_applied(conn, _ENGAGEMENT_LOG_MIGRATION)
        users = _rows_in(conn, 'users')
        events = _rows_in(conn, 'product_events')
        columns = 'id, user_id, character_id, event_name, value, metadata_json, created_at'
        # A lost ledger can leave either view intact. Inspect this transaction's
        # connection and skip only views: a real table with the same name must fail.
        existing_views = set(inspect(conn).get_view_names())
        # rail/reason remain in metadata_json, exactly as recorded by ProductEvent.
        if 'life_event_log' not in existing_views:
            conn.execute(text(
                f'CREATE VIEW life_event_log AS SELECT {columns} FROM product_events '
                "WHERE event_name IN ('life_event_sent', 'life_event_shown', 'life_event_replied')"))
        if 'push_denial_log' not in existing_views:
            conn.execute(text(
                f'CREATE VIEW push_denial_log AS SELECT {columns} FROM product_events '
                "WHERE event_name = 'push_denied'"))
        # A week key is quota bookkeeping, not evidence of a consumption time.
        backfilled = conn.execute(text(
            'UPDATE users SET streak_freeze_used_at = ('
            'SELECT MAX(created_at) FROM product_events '
            "WHERE user_id = users.id AND event_name = 'streak_freeze') "
            'WHERE streak_freeze_used_at IS NULL AND EXISTS ('
            'SELECT 1 FROM product_events WHERE user_id = users.id '
            "AND event_name = 'streak_freeze' AND created_at IS NOT NULL)")).rowcount
        life = _rows_in(conn, 'life_event_log')
        denials = _rows_in(conn, 'push_denial_log')
    logger.warning('engagement logs applied: users rows=%s product_events rows=%s '
                   'life_event_log rows=%s push_denial_log rows=%s freeze timestamps backfilled=%s',
                   users, events, life, denials, backfilled)


def reverse_presence_migration() -> None:
    """V3.168 rollback of the additive columns (image_spend.source/caller,
    users.first_life_event_at). Never called by startup; the forward path is the
    idempotent model auto-migration. rail_mute has no table: it is derived from
    events, so there is nothing to reverse."""
    cols = (('image_spend', 'source'), ('image_spend', 'caller'), ('users', 'first_life_event_at'))
    with engine.begin() as conn:
        _begin_sqlite_ddl(conn)
        _ensure_migration_ledger(conn)
        for table, col in cols:
            try:
                conn.execute(text(f'ALTER TABLE {table} DROP COLUMN IF EXISTS {col}'))
            except Exception:
                logger.warning('presence reverse: cannot drop %s.%s', table, col, exc_info=True)
            conn.execute(text('DELETE FROM app_migrations WHERE name = :n'),
                         {'n': f'schema:{table}:{col}'})
    logger.warning('presence migration reversed')


def reverse_engagement_logs_migration() -> None:
    """Explicit rollback of named log views; never called by startup."""
    with engine.begin() as conn:
        _begin_sqlite_ddl(conn)
        _ensure_migration_ledger(conn)
        if not _already_applied(conn, _ENGAGEMENT_LOG_MIGRATION):
            return
        users = _rows_in(conn, 'users')
        events = _rows_in(conn, 'product_events')
        life = _rows_in(conn, 'life_event_log')
        denials = _rows_in(conn, 'push_denial_log')
        conn.execute(text('DROP VIEW IF EXISTS life_event_log'))
        conn.execute(text('DROP VIEW IF EXISTS push_denial_log'))
        # Retain user timestamps and ProductEvent history: older apps safely ignore them.
        conn.execute(text('DELETE FROM app_migrations WHERE name = :n'),
                     {'n': _ENGAGEMENT_LOG_MIGRATION})
    logger.warning('engagement logs reversed: users rows=%s product_events rows=%s retained; '
                   'dropped life_event_log rows=%s push_denial_log rows=%s',
                   users, events, life, denials)


def _migrate_existing_users():
    bool_false='FALSE'; bool_true='TRUE'
    wanted={
        'timezone': "VARCHAR(64) DEFAULT 'UTC'",
        'voice_enabled': f"BOOLEAN DEFAULT {bool_false}",
        'voice_style': "VARCHAR(32) DEFAULT 'nova'",
        'proactive_enabled': f"BOOLEAN DEFAULT {bool_true}",
        'appearance_description': 'TEXT',
        'photo_credits': 'INTEGER DEFAULT 0',
        'bonus_peaches': 'INTEGER DEFAULT 0',
        'adult_confirmed': f"BOOLEAN DEFAULT {bool_false}",
        'voice_anon_mode': f"BOOLEAN DEFAULT {bool_false}",
        'attention_points': 'INTEGER DEFAULT 0',
        'streak_count': 'INTEGER DEFAULT 0',
        'streak_last_date': 'TIMESTAMP',
        'video_free_date': "VARCHAR(10) DEFAULT ''",
        'video_free_used': 'INTEGER DEFAULT 0',
        # V3.146.0: the first marital-status change is free for everyone.
        'marital_change_free_used': f"BOOLEAN DEFAULT {bool_false}",
    }
    _add_missing_columns('users', wanted)

def _drop_legacy_constructor_unique() -> None:
    """V3.44.15: v3.19.0 created custom_characters with a UNIQUE index on
    telegram_id. The V3.44.6 model removed ``unique=`` (multiple personas per
    user), but create_all never alters existing indexes — production Postgres
    kept rejecting every second persona with IntegrityError inside
    _finish_constructor, so the paid draft retried forever (owner: «её просто
    нет»). Recreate the index as a plain one on both PG and SQLite."""
    stmts = (
        'DROP INDEX IF EXISTS ix_custom_characters_telegram_id',
        'CREATE INDEX IF NOT EXISTS ix_custom_characters_telegram_id ON custom_characters (telegram_id)',
    )
    for stmt in stmts:
        try:
            with engine.begin() as conn:
                conn.execute(text(stmt))
        except Exception:
            logger.warning('legacy index migration skipped: %s', stmt, exc_info=True)


def _widen_quest_claims_column() -> None:
    """V3.55.8: users.quest_claims shipped as String(64) in V3.49.0, but the
    5-day JSON map ({"YYYY-MM-DD": [keys...]}) crosses 64 chars by the second
    day — Postgres then rejected every later claim with
    StringDataRightTruncation (the app quest sheet showed «Не получилось
    ответить» on a committed +5). The model is Text now; create_all and
    _auto_migrate_all_tables never alter existing column types, so widen it
    here. SQLite ignores varchar lengths entirely, so a failure is expected
    and harmless there."""
    try:
        with engine.begin() as conn:
            conn.execute(text('ALTER TABLE users ALTER COLUMN quest_claims TYPE TEXT'))
    except Exception:
        logger.info('quest_claims widen migration skipped (sqlite or already TEXT)')


def _rescale_peaches() -> None:
    """V3.65.0: peaches ×PEACH_SCALE, once per database. Every stored peach
    amount (balances, promo-code nominals, author earnings) is multiplied in
    the same transaction that inserts the ``app_migrations`` marker, so a
    restart, a second instance or a failed half-run can never apply it twice.
    Nobody loses value: prices and grants were scaled by the same factor."""
    name = f'peach_scale_x{PEACH_SCALE}'
    try:
        with engine.begin() as conn:
            _ensure_migration_ledger(conn)
    except Exception:
        logger.exception('app_migrations table create failed')
        return
    if PEACH_SCALE == 1:
        return
    try:
        with engine.begin() as conn:
            if conn.execute(text('SELECT 1 FROM app_migrations WHERE name = :n'), {'n': name}).first():
                return
            # the marker first: a concurrent boot hits the primary key and its
            # whole transaction (including its UPDATEs) rolls back.
            conn.execute(text('INSERT INTO app_migrations (name) VALUES (:n)'), {'n': name})
            users = conn.execute(text(
                'UPDATE users SET photo_credits = photo_credits * :k WHERE photo_credits <> 0'), {'k': PEACH_SCALE}).rowcount
            promos = conn.execute(text(
                'UPDATE promo_codes SET credits = credits * :k WHERE credits <> 0'), {'k': PEACH_SCALE}).rowcount
            earnings = conn.execute(text(
                'UPDATE author_revenue SET author_earnings_stars = author_earnings_stars * :k '
                'WHERE author_earnings_stars <> 0'), {'k': PEACH_SCALE}).rowcount
        logger.warning('peach rescale x%s applied: users=%s promo_codes=%s author_revenue=%s',
                       PEACH_SCALE, users, promos, earnings)
    except Exception:
        logger.exception('peach rescale x%s skipped (will retry on next boot)', PEACH_SCALE)


def _split_bonus_peaches() -> None:
    """V3.123.0: owner split peaches into a bought wallet (photo_credits) and a
    bonus wallet (bonus_peaches). Old balances were one pile; a man who never
    paid can only hold free peaches, so his whole balance moves to the bonus
    wallet. Anyone with a purchase keeps his balance as bought (we cannot tell
    the parts apart, and he must never lose what he paid for). Once per
    database, marker inserted first in the same transaction."""
    name = 'peach_wallet_split_v1'
    try:
        with engine.begin() as conn:
            if conn.execute(text('SELECT 1 FROM app_migrations WHERE name = :n'), {'n': name}).first():
                return
            conn.execute(text('INSERT INTO app_migrations (name) VALUES (:n)'), {'n': name})
            moved = conn.execute(text(
                "UPDATE users SET bonus_peaches = COALESCE(bonus_peaches, 0) + photo_credits, photo_credits = 0 "
                "WHERE photo_credits > 0 AND id NOT IN ("
                "SELECT user_id FROM star_transactions WHERE transaction_type = 'purchase' "
                "AND product NOT LIKE 'free_%')")).rowcount
        logger.warning('peach wallet split applied: %s non-payer balances moved to bonus', moved)
    except Exception:
        logger.exception('peach wallet split skipped (will retry on next boot)')


def _drop_personal_greetings() -> None:
    """V3.167.1 (владелец, Q4): шесть личных заготовок топ-6 были залиты в базу
    пустыми — без скрытого кадра и без реплики перед ним, поэтому на витрине они
    только заглушали 15 универсальных тизеров. Владелец: «удаляй эти 6 старых
    строк из базы полностью, ничего заполнять не надо». Идемпотентно и по точным
    id: строки 1..6, но только если это не универсальный набор («all») — на чистой
    базе под ними лежат именно он. Marker-first, как остальные прогоны."""
    name = 'personal_greetings_removed_v31671'
    try:
        with engine.begin() as conn:
            if conn.execute(text('SELECT 1 FROM app_migrations WHERE name = :n'), {'n': name}).first():
                return
            conn.execute(text('INSERT INTO app_migrations (name) VALUES (:n)'), {'n': name})
            removed = conn.execute(text(
                "DELETE FROM character_greetings WHERE id IN (1, 2, 3, 4, 5, 6) "
                "AND character_id <> 'all'")).rowcount
        logger.warning('personal greeting stubs removed=%s', removed)
    except Exception:
        logger.exception('personal greeting stubs removal skipped (will retry on next boot)')


def _repair_character_cards() -> None:
    """V3.167.1 (владелец, Q6): карточка Лай снята с витрины и убрана из напарниц
    — её собирал другой аккаунт, и в общем каталоге она только путала. Лизина
    витрина оборвана на середине фразы (LLM не дописал), владелец продиктовал
    текст целиком. По точным id, один раз, marker-first."""
    name = 'character_cards_repaired_v31671'
    lai = 'custom_6328140267_a4e61b58'
    liza = 'custom_6237849550_257f28e7'
    liza_bio = ('Лиза знает, как одним взглядом заставить забыть обо всём. '
                'Её дерзкий характер и страстный темперамент превратят ваш вечер в игру без правил.')
    try:
        with engine.begin() as conn:
            if conn.execute(text('SELECT 1 FROM app_migrations WHERE name = :n'), {'n': name}).first():
                return
            conn.execute(text('INSERT INTO app_migrations (name) VALUES (:n)'), {'n': name})
            hidden = conn.execute(text(
                "UPDATE character_cards SET is_visible = false, status = 'hidden' "
                "WHERE character_id = :c"), {'c': lai}).rowcount
            guests = conn.execute(text(
                "DELETE FROM chat_guests WHERE guest_id = :c"), {'c': lai}).rowcount
            bio = conn.execute(text(
                "UPDATE character_cards SET short_bio = :b WHERE character_id = :c "
                "AND (short_bio IS NULL OR short_bio <> :b)"),
                {'b': liza_bio, 'c': liza}).rowcount
        logger.warning('card repairs applied: lai hidden=%s guests_removed=%s liza_bio=%s',
                       hidden, guests, bio)
    except Exception:
        logger.exception('character card repairs skipped (will retry on next boot)')


def _index_analytics_stream() -> None:
    """V3.167.5 §10: лента рельсов (`push_sent` / `push_denied` / `digest_shown`)
    читается по имени события и времени — экран кухни и сам губернатор смотрят
    «что было за сутки», а по одиночным индексам Postgres для этого перебирает
    все строки имени. Идемпотентно (IF NOT EXISTS), а на живой базе ставится
    CONCURRENTLY вне транзакции: обычный CREATE INDEX держал бы всю таблицу
    product_events записанной на время стройки, и бот встал бы посреди дня.
    Не вышло (заблокирован lock_timeout'ом) — следующий старт догонит."""
    name = 'ix_product_events_name_created'
    try:
        if engine.dialect.name == 'postgresql':
            # AUTOCOMMIT обязателен: CONCURRENTLY нельзя внутри транзакции
            with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
                conn.execute(text("SET lock_timeout '3s'"))
                conn.execute(text(f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} '
                                  f'ON product_events (event_name, created_at)'))
        else:
            with engine.connect() as conn:
                conn.execute(text(f'CREATE INDEX IF NOT EXISTS {name} '
                                  f'ON product_events (event_name, created_at)'))
                conn.commit()
        logger.info('analytics stream index ready')
    except Exception:
        logger.info('analytics stream index skipped (locked or unsupported), next boot retries')


def init_db():
    Base.metadata.create_all(engine)
    # V3.44.21: the FreeKassa orders table retired with the kassa itself —
    # platega_orders is created fresh by create_all; the legacy
    # freekassa_orders table is intentionally left in place (paid history).
    _drop_legacy_constructor_unique()
    _widen_quest_claims_column()
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
        # v3.16.7: raw image bytes for paid full-resolution gallery downloads.
        'full_resolution_bytes': 'BYTEA',
        # v3.16.9: community photo pool — AI-generated photos shared across users.
        'community_shared': 'BOOLEAN DEFAULT FALSE',
        'source_delivery_id': 'INTEGER',
    })
    _add_missing_columns('user_character_relationships', {
        'familiarity_score': 'FLOAT DEFAULT 0',
        'continuity_score': 'FLOAT DEFAULT 0',
        'connection_score': 'FLOAT DEFAULT 0',
        'last_distinct_day': 'TIMESTAMP',
        'active_days': 'INTEGER DEFAULT 0',
        'marital_status': 'VARCHAR(16)',
    })
    # V3.13+ card fields were added to the model after the table already existed
    # in production; create_all never alters existing tables, so add them here.
    _add_missing_columns('character_cards', {
        'gender': 'VARCHAR(16)',
        'age': 'INTEGER',
        'short_bio': 'TEXT',
    })
    # V3.56.0: the admin generation feed now carries the engine and per-job cost
    # so intimate (SpicyAPI) renders stop being invisible in the money trail.
    _add_missing_columns('user_generations', {
        'engine': 'VARCHAR(48)',
        'cost_usd': 'FLOAT DEFAULT 0',
    })
    # Final safety net: any model column missing from an existing table gets added
    # automatically. This prevents future "UndefinedColumn" crashes when new fields
    # are added to models but forgotten in explicit migrations.
    _auto_migrate_all_tables()
    _migrate_engagement_logs()
    # V3.167.5 §10: индекс по ленте событий — после того как таблицы есть.
    _index_analytics_stream()
    # V3.65.0: after every table exists, multiply stored peaches once.
    _rescale_peaches()
    # V3.123.0: split the peach balance into bought + bonus, once.
    _split_bonus_peaches()
    # V3.167.1: его пустые заготовки топ-6 из базы уходят, витрина топ-6 — универсальная.
    _drop_personal_greetings()
    # V3.167.1: снятая карточка Лай и оборванное био Лизы, по точным id.
    _repair_character_cards()

init_db()
