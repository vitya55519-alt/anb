"""V3.47.4 static checks: admin-set character-PAGE carousel visuals.

Owner decision: «только визуал, картинки разные ставить и все» — the photo
strip on the character page must be swappable straight from the admin panel
WITHOUT touching the canonical references (those keep driving every generated
photo). Shots live in PostgreSQL (survive Railway redeploys), URLs carry the
row id (instant cache-bust), and an empty override falls back to canon.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
WEB = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
DB = (ROOT / 'services' / 'db.py').read_text(encoding='utf-8')


# ── storage: DB-backed shots, auto-created on startup ──────────────────────
def test_page_gallery_model_and_registration():
    assert 'class PageGalleryShot(Base):' in MODELS
    assert '__tablename__ = "page_gallery_shots"' in MODELS
    assert 'character_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)' in MODELS
    assert 'PageGalleryShot' in DB


# ── service: CRUD + limits ──────────────────────────────────────────────────
def test_page_gallery_service_helpers():
    assert 'PAGE_GALLERY_MAX_SHOTS = 6' in WEB
    assert 'PAGE_GALLERY_MAX_BYTES = 8 * 1024 * 1024' in WEB
    assert 'def page_gallery_shots(character_id: str) -> list[dict]:' in WEB
    assert 'def add_page_gallery_shot(character_id: str, data: bytes, content_type: str = \'image/jpeg\') -> bool:' in WEB
    assert 'def delete_page_gallery_shot(shot_id: int) -> bool:' in WEB
    assert 'def clear_page_gallery(character_id: str) -> int:' in WEB
    assert 'def get_page_gallery_shot(shot_id: int) -> tuple[bytes, str] | None:' in WEB
    # the cap is enforced on add
    assert 'if len(existing) >= PAGE_GALLERY_MAX_SHOTS:' in WEB


# ── payload: override wins, empty falls back to the canonical strip ────────
def test_characters_payload_uses_override_first():
    start = WEB.index("'gallery': (")
    block = WEB[start:start + 400]
    assert '/webapp/pgal/{card.character_id}/' in block
    # fallback keeps the canonical ?i= strip untouched
    assert "f'/webapp/photo/{card.character_id}?i={idx}&v={ver}'" in block


# ── public route: id-carrying URL, week cache ──────────────────────────────
def test_pgal_route():
    assert "async def _webapp_pgal(request: web.Request) -> web.Response:" in MAIN
    assert "app.router.add_get('/webapp/pgal/{character_id}/{shot_id}', _webapp_pgal)" in MAIN
    route = MAIN[MAIN.index('async def _webapp_pgal('):MAIN.index('async def _webapp_gif(')]
    assert 'webapp_service.get_page_gallery_shot(shot_id)' in route
    assert "headers={'Cache-Control': 'public, max-age=604800'}" in route


# ── admin flow: entry button, screens, multi-upload, cancel ────────────────
def test_admin_page_gallery_flow():
    assert "callback_data=f'admin:pgal:{character_id}'" in MAIN
    assert 'def admin_pgal_keyboard(character_id: str):' in MAIN
    assert "@dp.callback_query(F.data.startswith('admin:pgal:add:'))" in MAIN
    assert "@dp.callback_query(F.data.startswith('admin:pgal:del:'))" in MAIN
    assert "@dp.callback_query(F.data.startswith('admin:pgal:clear:'))" in MAIN
    # the generic view handler must not swallow add:/del:/clear: (V3.47.1 lesson)
    assert "& ~F.data.startswith('admin:pgal:add:')" in MAIN
    assert "& ~F.data.startswith('admin:pgal:del:')" in MAIN
    assert "& ~F.data.startswith('admin:pgal:clear:')" in MAIN
    upload = MAIN[MAIN.index('async def admin_pgal_upload('):MAIN.index('def _admin_gender_keyboard(')]
    assert 'webapp_service.add_page_gallery_shot(character_id, buf.getvalue(), \'image/jpeg\')' in upload
    # the card summary states the storefront-only contract
    assert 'Карусель страницы' in MAIN
    assert 'на генерацию не влияет' in MAIN


# ── the canonical chain stays untouched: generation must not read the shots ─
def test_canonical_references_not_replaced():
    # character_gallery() still globs the reference PNGs (generation source)
    assert "folder.glob('*.png')" in WEB
    # and the new table is never consulted by the photo pipeline
    assert 'PageGalleryShot' not in (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
