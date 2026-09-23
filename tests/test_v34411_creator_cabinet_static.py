"""V3.44.11 static checks: the creator's cabinet in the Mini App profile.

The profile gains a «Кабинет создателя» row that opens a full-screen overlay:
every character the user built with the generated avatar, views and
per-character author earnings, plus a «На витрину» toggle that puts her on
the storefront (Community segment, visible to everyone) or back private.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CCS = (ROOT / 'services' / 'custom_character_service.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


# ── routes + handlers ──────────────────────────────────────────────────────

def test_creator_routes_registered():
    assert "app.router.add_get('/webapp/api/creator/cabinet', _webapp_api_creator_cabinet)" in MAIN
    assert "app.router.add_post('/webapp/api/creator/publish', _webapp_api_creator_publish)" in MAIN


def test_creator_cabinet_handler_auth():
    handler = MAIN[MAIN.index('async def _webapp_api_creator_cabinet('):MAIN.index('async def _webapp_api_creator_publish(')]
    assert 'validate_init_data' in handler
    assert 'init_data_user(pairs)' in handler
    assert 'api_creator_cabinet(telegram_id)' in handler
    assert "'Cache-Control': 'no-store'" in handler
    assert "status=401" in handler


def test_creator_publish_handler_auth_and_ownership():
    handler = MAIN[MAIN.index('async def _webapp_api_creator_publish('):MAIN.index('async def _webapp_api_comments(')]
    assert 'validate_init_data' in handler
    assert "body.get('character_id', '')" in handler
    assert "status=400" in handler
    assert 'publish_creator_character(' in handler
    assert "bool(body.get('publish'))" in handler


# ── service layer ──────────────────────────────────────────────────────────

def test_cabinet_service_collects_characters():
    assert 'def api_creator_cabinet(telegram_id: int) -> dict:' in WEBAPP_SVC
    body = WEBAPP_SVC[WEBAPP_SVC.index('def api_creator_cabinet('):WEBAPP_SVC.index('def publish_creator_character(')]
    assert 'get_all_custom_characters(telegram_id)' in body
    assert 'get_author_earnings_by_character(telegram_id)' in body
    assert "'published': bool(row.community_published)" in body
    assert "'views': views.get(row.character_id, 0)" in body
    assert "'earnings': round(earnings.get(row.character_id, 0.0), 2)" in body
    assert "'total_earnings'" in body


def test_publish_service_enforces_ownership():
    body = WEBAPP_SVC[WEBAPP_SVC.index('def publish_creator_character('):WEBAPP_SVC.index('# ── V3.38.0')]
    assert 'get_custom_character_by_id(character_id)' in body
    assert 'str(row.telegram_id) != str(telegram_id)' in body
    assert "'error': 'not_found'" in body
    assert 'set_community_published(character_id, publish)' in body
    assert 'update_card(character_id, is_visible=bool(publish))' in body


def test_custom_character_service_helpers():
    assert 'def set_community_published(character_id: str, published: bool) -> bool:' in CCS
    assert 'row.community_published = bool(published)' in CCS
    assert 'def get_author_earnings_by_character(telegram_id: int) -> dict[str, float]:' in CCS
    assert 'out[r.character_id] = out.get(r.character_id, 0.0) + r.author_earnings_stars' in CCS


# ── frontend ───────────────────────────────────────────────────────────────

def test_cabinet_overlay_markup():
    assert 'id="creatorview"' in INDEX
    assert 'id="creatorBack"' in INDEX
    assert 'id="creatorBody"' in INDEX
    assert 'id="menuCreator"' in INDEX


def test_cabinet_frontend_flow():
    assert 'function openCreatorOverlay()' in INDEX
    assert 'async function loadCreatorCabinet()' in INDEX
    assert 'async function togglePublish(id, publish, btn)' in INDEX
    assert "fetch('/webapp/api/creator/cabinet?init_data=' + encodeURIComponent(tg.initData || '')" in INDEX
    assert "fetch('/webapp/api/creator/publish?init_data=' + encodeURIComponent(tg.initData || '')" in INDEX
    assert "body: JSON.stringify({ character_id: id, publish: !!publish })" in INDEX
    # every backend-driven field is esc()'d at build time
    assert '${esc(c.photo)}' in INDEX
    assert '${esc(c.name)}' in INDEX
    assert 'data-pub-id="${esc(c.id)}"' in INDEX


def test_cabinet_i18n_both_languages():
    for key in (
        'creator_row', 'creator_title', 'creator_empty', 'creator_publish',
        'creator_unpublish', 'creator_on_vitrine', 'creator_private',
        'creator_published_toast', 'creator_unpublished_toast',
        'creator_earned', 'creator_total_earnings',
    ):
        assert f'{key}:' in INDEX, f'missing i18n key {key}'
