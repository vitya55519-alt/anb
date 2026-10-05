"""V3.53.0 — «Собери галерею» (rolling 50-photo gallery-set counter).

For each character, every photo the user actually receives (bot chat + Mini App
chat / private / circle / video) increments one counter. Every GALLERY_SET_SIZE
(50) photos completes a gallery set («quest done»), then the next 50 begins.
The Mini App character page shows a single «🖼 N/50 · 🏆 K сетов» bar and
celebrates each newly completed set.

Counting reads two DISJOINT, already-populated tables — the bot writes
PhotoDelivery but never UserGeneration, and the Mini App writes UserGeneration
but never PhotoDelivery — so summing them never double counts. No new write is
added to the delivery hot path just for counting, and no schema change is
needed (the set-announcement stamp rides dialog_sessions via a DialogStore).

Static pins only (no imports -> the suite runs without a DB or an LLM key)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
COLL = (ROOT / 'services' / 'collection_service.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_config_set_size_default_is_50():
    # one rolling set = 50 delivered photos, configurable
    assert 'GALLERY_SET_SIZE' in CONFIG
    assert 'os.getenv("GALLERY_SET_SIZE", "50")' in CONFIG


def test_counter_reads_both_disjoint_sources():
    # bot deliveries
    assert 'def collected_photo_count(' in COLL
    assert 'PhotoDelivery.user_id == uid' in COLL
    assert 'PhotoDelivery.character_id == character_id' in COLL
    # app generations — and only the character-bound photo kinds (never the
    # char-less 'picture' studio render)
    assert 'UserGeneration.telegram_id == tg' in COLL
    assert 'UserGeneration.character_id == character_id' in COLL
    assert "('photo', 'circle', 'video', 'hot', 'cosplay')" in COLL
    # summing the two disjoint counts
    assert 'return int(bot_n) + int(app_n)' in COLL


def test_progress_and_announcement_shape():
    # the rolling bar math
    assert 'def gallery_set_progress(' in COLL
    assert "sets_done = count // per" in COLL
    assert "progress = count % per" in COLL
    assert "'complete': progress == 0 and count > 0" in COLL
    # newly-completed detection is persisted in a DialogStore (redeploy-safe)
    assert "DialogStore('gallery_sets')" in COLL
    assert 'def note_gallery_set(' in COLL
    assert 'if sets_done > prior_n' in COLL


def test_webapp_api_collection_exposes_bar():
    assert 'def api_collection(' in WEBAPP_SVC
    assert 'gallery_set_progress(telegram_id, character_id)' in WEBAPP_SVC
    assert "prog['just_completed'] = note_gallery_set(telegram_id, character_id)" in WEBAPP_SVC


def test_main_routes_and_flags_completion():
    # the character-page data endpoint
    assert "app.router.add_get('/webapp/api/collection', _webapp_api_collection)" in MAIN
    assert 'async def _webapp_api_collection(' in MAIN
    # the two delivery responses carry the celebration flag so the SPA can toast
    assert MAIN.count("'set_completed':") >= 2
    # voice is not a photo and must never advance / celebrate the gallery
    assert "if kind != 'voice':" in MAIN


def test_spa_bar_fetch_and_celebrate():
    assert 'id="charCollectBar"' in SPA
    assert 'function renderCollectBar(' in SPA
    assert 'async function loadCollection(' in SPA
    assert '/webapp/api/collection?init_data=' in SPA
    # openCharPage refreshes the bar for the character being shown
    assert 'loadCollection(c.id);' in SPA
    # delivery responses celebrate a completed set
    assert SPA.count('j.set_completed > 0') >= 2


def test_spa_has_all_seven_locale_strings():
    # collect_lbl must exist in every locale block (en/ru base + es/it/fr/zh/ja)
    assert SPA.count('collect_lbl:') >= 7
    assert SPA.count('collect_done:') >= 7
    # the RU/EN base also needs the plural-aware sets label used by the bar
    assert SPA.count('collect_sets:') >= 7
