"""V3.44.15 static checks: legacy unique index dropped, save failure bounded, shop tab loads.

Root causes fixed here (owner: «персонаж не появляется, магазин не грузится вообще»):
1. v3.19.0 created custom_characters with a UNIQUE index on telegram_id; the
   V3.44.6 model removed ``unique=`` but create_all never alters existing
   indexes — production Postgres rejected every SECOND persona with
   IntegrityError, the run crashed after drawing the avatar and the sweep
   re-drew her forever. The migration recreates the index as a plain one.
2. The persona save is the guarded step now: message + refund + draft closed,
   and drafts stop resuming after MAX_CONSTRUCTOR_ATTEMPTS tries.
3. The Mini App shop tab sat on «...» since V3.44.2 — the lazy-load wrapper
   assigned an undefined `switchTab`, the ReferenceError killed the wiring at
   boot. lazyLoadTab is wired into the nav handler AND showTab().
4. One chat photo delivery is capped by PHOTO_TOTAL_BUDGET_SECONDS — fal's
   worst-case silent chain could grind ~30 minutes with nothing arriving.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
DBS = (ROOT / 'services' / 'db.py').read_text(encoding='utf-8')
CCS = (ROOT / 'services' / 'custom_character_service.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
HTML = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def _finish_body() -> str:
    return MAIN[MAIN.index('async def _finish_constructor('):MAIN.index('@dp.callback_query(F.data == \'constructor:start\')')]


def test_legacy_unique_index_migration():
    # the v3.19.0 schema shipped telegram_id as unique — drop and recreate plain
    assert 'DROP INDEX IF EXISTS ix_custom_characters_telegram_id' in DBS
    assert 'CREATE INDEX IF NOT EXISTS ix_custom_characters_telegram_id' in DBS
    # the migration runs on every boot, after create_all
    init_block = DBS[DBS.index('def init_db():'):]
    assert '_drop_legacy_constructor_unique()' in init_block
    assert init_block.index('Base.metadata.create_all(engine)') < init_block.index('_drop_legacy_constructor_unique()')
    # a failed statement must never block boot
    assert 'legacy index migration skipped' in DBS


def test_draft_attempts_column_and_guards():
    assert 'attempts: Mapped[int] = mapped_column(Integer, default=0)' in MODELS
    assert 'MAX_CONSTRUCTOR_ATTEMPTS = 5' in CCS
    # every claim counts, and exhausted drafts are unclaimable
    claim = CCS[CCS.index('def claim_constructor_draft('):CCS.index('def finish_constructor_draft(')]
    assert 'row.attempts = int(row.attempts or 0) + 1' in claim
    assert '(row.attempts or 0) >= MAX_CONSTRUCTOR_ATTEMPTS' in claim
    # the sweep only resumes drafts that still have attempts left
    pending = CCS[CCS.index('def pending_constructor_drafts('):CCS.index('def abandoned_constructor_drafts(')]
    assert '(r.attempts or 0) < MAX_CONSTRUCTOR_ATTEMPTS' in pending
    # exhausted drafts are closed with (telegram_id, source, name) for refunds
    assert 'def abandoned_constructor_drafts() -> list[tuple[int, str, str]]:' in CCS
    assert 'row.done = True' in CCS[CCS.index('def abandoned_constructor_drafts('):]


def test_save_failure_is_bounded_not_silent():
    body = _finish_body()
    save_block = body[body.index('try:\n        row = save_custom_character('):]
    assert 'constructor persona save failed' in body
    # user-facing apology, refund, and the draft closes — no silent crash loop
    assert 'не получилось сохранить' in body
    assert save_block.index('grant_photo_credits(') < save_block.index('finish_constructor_draft(telegram_id)')
    assert 'return' in save_block[:save_block.index('# V3.44.7: save avatar to disk immediately')]


def test_sweep_abandons_exhausted_drafts():
    sweep = MAIN[MAIN.index('async def _constructor_draft_sweep('):MAIN.index('async def _finish_constructor(')]
    assert 'abandoned_constructor_drafts()' in sweep
    assert "grant_photo_credits(" in sweep
    assert 'не получилось создать' in sweep
    # abandonment runs BEFORE new resumes in each cycle
    assert sweep.index('abandoned_constructor_drafts()') < sweep.index('pending_constructor_drafts()')


def test_status_banner_hides_after_giveup():
    body = MAIN[MAIN.index('async def _webapp_api_constructor_status('):]
    body = body[:body.index('\nasync def ')]
    assert 'MAX_CONSTRUCTOR_ATTEMPTS' in body
    assert 'int(draft.attempts or 0) < MAX_CONSTRUCTOR_ATTEMPTS' in body


def test_photo_delivery_capped():
    assert 'PHOTO_TOTAL_BUDGET_SECONDS = max(60, int(os.getenv("PHOTO_TOTAL_BUDGET_SECONDS", "300")))' in CONFIG
    assert 'PHOTO_TOTAL_BUDGET_SECONDS,' in MAIN
    photo = MAIN[MAIN.index('async def _run_photo_background('):MAIN.index('async def _start_photo_background(')]
    assert 'asyncio.wait_for(' in photo
    assert 'timeout=PHOTO_TOTAL_BUDGET_SECONDS,' in photo
    # a timeout is a first-class failure: refund + honest retry message
    assert 'except asyncio.TimeoutError:' in photo
    assert 'фото делалось слишком долго' in photo


def test_shop_tab_lazy_load_wired():
    # the V3.44.2 wrapper referenced an undefined switchTab — that died at boot
    assert 'const _origSwitchTab' not in HTML
    assert 'switchTab=function' not in HTML
    assert 'function lazyLoadTab(id){' in HTML
    # wired into the bottom-nav clicks AND programmatic showTab('shop') gates
    assert 'lazyLoadTab(btn.dataset.tab);' in HTML
    assert 'lazyLoadTab(name);' in HTML


def test_shop_load_retries_after_failure():
    assert '_shopLoaded = false;' in HTML
    assert 'AbortSignal.timeout(20000)' in HTML
    # cabinet rows keep a visible placeholder when the avatar photo 404s
    cabinet = HTML[HTML.index('async function loadCreatorCabinet('):HTML.index('async function togglePublish(')]
    assert "this.nextElementSibling.style.display='flex';" in cabinet


def test_draft_imports_cover_new_helpers():
    assert 'abandoned_constructor_drafts, MAX_CONSTRUCTOR_ATTEMPTS,' in MAIN


def test_migration_actually_unblocks_second_persona():
    # runtime proof: recreate the v3.19.0 schema (UNIQUE index, same name the
    # ORM generates), confirm it blocks a second persona, then run the exact
    # statements db.py ships and confirm both rows coexist.
    import sqlite3
    con = sqlite3.connect(':memory:')
    try:
        con.execute('CREATE TABLE custom_characters (id INTEGER PRIMARY KEY, telegram_id VARCHAR(64), character_id VARCHAR(64))')
        con.execute('CREATE UNIQUE INDEX ix_custom_characters_telegram_id ON custom_characters (telegram_id)')
        con.execute("INSERT INTO custom_characters (telegram_id, character_id) VALUES ('1', 'custom_1_a')")
        blocked = False
        try:
            con.execute("INSERT INTO custom_characters (telegram_id, character_id) VALUES ('1', 'custom_1_b')")
        except sqlite3.IntegrityError:
            blocked = True
        assert blocked, 'the legacy unique index must block the second persona (Alina)'
        con.execute('DROP INDEX IF EXISTS ix_custom_characters_telegram_id')
        con.execute('CREATE INDEX IF NOT EXISTS ix_custom_characters_telegram_id ON custom_characters (telegram_id)')
        con.execute("INSERT INTO custom_characters (telegram_id, character_id) VALUES ('1', 'custom_1_b')")
        assert con.execute('SELECT COUNT(*) FROM custom_characters WHERE telegram_id = ?', ('1',)).fetchone()[0] == 2
    finally:
        con.close()
