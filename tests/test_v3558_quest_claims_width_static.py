"""V3.55.8 static pins: users.quest_claims must not cap the 5-day JSON map.

Railway logs showed the real cause behind the app quest error: psycopg
StringDataRightTruncation «value too long for type character varying(64)» on
UPDATE users ... quest_claims=... — the {"YYYY-MM-DD": [keys...]} map crosses
64 chars by the second day, so every later claim of the day died inside
claim_quest's commit. Model column is Text now, and because create_all /
_auto_migrate_all_tables never alter existing column types, services/db.py
carries an explicit ALTER COLUMN TYPE TEXT for Postgres.

Static pins only (sqlite ignores varchar lengths, so no logic test can show
the failure locally)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
DB = (ROOT / 'services' / 'db.py').read_text(encoding='utf-8')


def test_quest_claims_model_column_is_text():
    assert "quest_claims: Mapped[str] = mapped_column(Text, default=\"\")" in MODELS
    assert "quest_claims: Mapped[str] = mapped_column(String(64)" not in MODELS


def test_db_widens_the_existing_postgres_column():
    assert 'def _widen_quest_claims_column() -> None:' in DB
    assert "ALTER TABLE users ALTER COLUMN quest_claims TYPE TEXT" in DB
    # create_all never alters types, so the call must run on every init_db
    init = DB[DB.index('def init_db():'):DB.index('init_db()\n')]
    assert '_widen_quest_claims_column()' in init
    # fail-silent: SQLite has no ALTER COLUMN TYPE and no length enforcement
    fn = DB[DB.index('def _widen_quest_claims_column'):DB.index('def init_db()')]
    assert 'except Exception:' in fn
