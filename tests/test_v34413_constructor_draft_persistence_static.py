"""V3.44.13 static checks: constructor drafts survive redeploys + avatar healing.

1. The wizard draft is persisted in Postgres (constructor_drafts) and flagged
   paid at the buy step — a Railway redeploy between payment and
   ``save_custom_character`` used to eat the paid persona (owner: «в итоге
   отображается только один персонаж, но я уже делаю второго»). The startup
   scan resumes paid-but-unfinished drafts, and ``_finish_constructor`` falls
   back to the persisted draft when the in-memory session is gone.
2. ``/webapp/photo/<id>`` re-downloads a custom persona's avatar from the
   persisted Telegram file_id when the ephemeral disk lost it — the
   storefront/cabinet photo must never 404 until the next boot.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CCS = (ROOT / 'services' / 'custom_character_service.py').read_text(encoding='utf-8')
WEBAPP = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')


def _finish_body() -> str:
    return MAIN[MAIN.index('async def _finish_constructor('):MAIN.index("@dp.callback_query(F.data == 'constructor:start')")]


def test_draft_model_exists():
    assert 'class ConstructorDraft(Base):' in MODELS
    assert '__tablename__ = "constructor_drafts"' in MODELS
    for col in ('params_json', 'photo_reference_base64', 'claimed_at', 'paid', 'done', 'source'):
        assert col in MODELS


def test_draft_helpers_exist():
    for fn in (
        'def save_constructor_draft(', 'def snapshot_constructor_draft(',
        'def get_constructor_draft(', 'def mark_constructor_draft_paid(',
        'def claim_constructor_draft(', 'def finish_constructor_draft(',
        'def pending_constructor_drafts(',
    ):
        assert fn in CCS
    # the payment-time snapshot must NOT reset paid/claimed (redelivery safety)
    snap = CCS[CCS.index('def snapshot_constructor_draft('):]
    snap = snap[:snap.index('\ndef ')]
    assert 'row.paid = False' not in snap
    assert 'row.claimed_at = None' not in snap


def test_draft_endpoint_persists():
    body = MAIN[MAIN.index('async def _webapp_api_constructor_draft('):MAIN.index('async def _webapp_api_constructor_buy(')]
    assert 'save_constructor_draft(telegram_id, params=params, photo_reference_base64=photo_reference_base64)' in body
    assert body.index('save_constructor_draft(') > body.index('_constructor_sessions[telegram_id] = session_data')


def test_buy_endpoint_marks_paid_before_spawning():
    body = MAIN[MAIN.index('async def _webapp_api_constructor_buy('):]
    body = body[:body.index('\nasync def ')]
    assert "mark_constructor_draft_paid(telegram_id, 'peaches')" in body
    assert "mark_constructor_draft_paid(telegram_id, 'webapp_admin')" in body
    assert "mark_constructor_draft_paid(telegram_id, 'webapp_credit')" in body
    # the paid flag lands BEFORE the job spawns, so a crash between them resumes
    peach_idx = body.index("mark_constructor_draft_paid(telegram_id, 'peaches')")
    spawn_idx = body.index("_spawn_job('constructor', telegram_id, _finish_constructor(telegram_id, None, telegram_id, source='peaches')")
    assert peach_idx < spawn_idx


def test_successful_payment_snapshots_draft():
    body = MAIN[MAIN.index("if payload.startswith('constructor:'):"):]
    body = body[:body.index('\nif ')]
    assert 'snapshot_constructor_draft(' in body
    assert "mark_constructor_draft_paid(message.from_user.id, 'stars')" in body
    snap_idx = body.index('snapshot_constructor_draft(')
    spawn_idx = body.index("_spawn_job('constructor'")
    assert snap_idx < spawn_idx


def test_finish_constructor_db_fallback_and_finish_mark():
    body = _finish_body()
    assert 'claim_constructor_draft(telegram_id)' in body
    assert "json.loads(draft.params_json or '{}')" in body
    assert "cons['photo_reference_base64'] = draft.photo_reference_base64" in body
    assert 'source = source or (draft.source' in body
    # a held draft means a resumed run owns her — stay silent
    assert 'elif get_constructor_draft(telegram_id) is not None:' in body
    # the completion mark comes after the save so the scan never double-creates
    assert 'finish_constructor_draft(telegram_id)' in body
    assert body.index('finish_constructor_draft(telegram_id)') > body.index('save_custom_character(')


def test_startup_resume_scan():
    idx = MAIN.index('pending = pending_constructor_drafts()')
    assert idx < MAIN.index('await dp.start_polling(bot)')
    # resumed creations ride the job registry like every other spawn
    assert "_spawn_job('constructor', int(_draft.telegram_id)" in MAIN


def test_webapp_photo_heals_custom_avatar():
    body = MAIN[MAIN.index('async def _webapp_photo('):]
    body = body[:body.index('\nasync def ')]
    assert 'if is_custom_character(character_id):' in body
    assert 'row and row.avatar_file_id' in body
    assert 'await ensure_custom_avatar_cached(bot, character_id)' in body
    assert 'webapp_service.invalidate_gallery_cache(character_id)' in body
    # lazy GENERATION stays in the chat flow — the route only re-downloads
    heal_idx = body.index('await ensure_custom_avatar_cached(bot, character_id)')
    guard_idx = body.index('row and row.avatar_file_id')
    assert guard_idx < heal_idx


def test_invalidate_gallery_cache_helper():
    assert 'def invalidate_gallery_cache(character_id: str) -> None:' in WEBAPP
    assert '_GALLERY_CACHE.pop(character_id, None)' in WEBAPP
