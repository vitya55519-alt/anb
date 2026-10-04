"""V3.47.1 static checks: admin-uploaded achievement/mission art (badges),
the chat-missions click fix, and the reliable desktop photo-share path.

Owner decisions this release encodes:
- The admin uploads one image per achievement/mission (like the storefront
  card media), stored as bytes in PostgreSQL so it survives Railway redeploys.
- The art rides on the unlock notification AND shows on the achievements
  board (Mini App thumbnails + a «🖼» reveal button in the bot).
- Every still-locked chat mission now carries a working CTA, and the roadmap
  always keeps a navigation row so a tap lands somewhere real.
- Telegram Desktop has no web file-share, so «📥 Сохранить» has the bot post
  the watermarked export into the user's own chat to be forwarded onward.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
GAM = (ROOT / 'services' / 'gamification_service.py').read_text(encoding='utf-8')
WEB = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
DB = (ROOT / 'services' / 'db.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


# ── storage: DB-backed badge model, auto-created on startup ────────────────
def test_badge_model_and_registration():
    assert 'class AchievementBadge(Base):' in MODELS
    assert '__tablename__ = "achievement_badges"' in MODELS
    assert 'image_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)' in MODELS
    # imported in db.py so Base.metadata.create_all sees the new table
    assert 'AchievementBadge' in DB


# ── service helpers ────────────────────────────────────────────────────────
def test_badge_service_helpers():
    assert 'def badge_keys() -> set[str]:' in GAM
    assert 'def get_badge(key: str) -> tuple[bytes, str] | None:' in GAM
    assert 'def set_badge(key: str, data: bytes, content_type: str = \'image/jpeg\') -> bool:' in GAM
    assert 'def clear_badge(key: str) -> bool:' in GAM
    assert 'def badge_catalog() -> list[tuple[str, str]]:' in GAM
    # the board marks which achievements carry art
    assert "'has_badge': key in badges" in GAM


# ── delivery: unlock notification + achievements screen reveal ─────────────
def test_badge_delivery_in_bot():
    assert 'badge = get_badge(key)' in MAIN
    assert "await bot.send_photo(chat_id, types.BufferedInputFile(badge[0], filename='badge.jpg'), caption=text)" in MAIN
    # unlocked achievements with art expose a «🖼» button
    assert "callback_data=f'ach:badge:{it[\"key\"]}'" in MAIN
    assert "async def achievement_badge_view(cq: types.CallbackQuery):" in MAIN


# ── admin upload flow (mirrors the storefront card media pattern) ──────────
def test_admin_badge_upload_flow():
    assert "[InlineKeyboardButton(text='🏆 Арт достижений/миссий', callback_data='admin:badges')]" in MAIN
    assert 'def admin_badges_keyboard():' in MAIN
    assert "@dp.callback_query(F.data == 'admin:badges')" in MAIN
    assert "@dp.callback_query(F.data.startswith('admin:badge:set:'))" in MAIN
    assert "@dp.callback_query(F.data.startswith('admin:badge:clear:'))" in MAIN
    assert 'async def admin_badge_upload(message: types.Message):' in MAIN
    assert 'ok = set_badge(key, buf.getvalue(), \'image/jpeg\')' in MAIN
    # the plain «admin:badge:<key>» handler must not swallow set:/clear:
    assert "& ~F.data.startswith('admin:badge:set:')" in MAIN
    assert "& ~F.data.startswith('admin:badge:clear:')" in MAIN


# ── chat missions: every actionable row + a persistent nav row ─────────────
def test_chat_missions_click_fix():
    assert "'premium_member': ('⭐ Оформить Premium', 'buy:premium')" in GAM
    assert 'MISSION_NAV: tuple[tuple[str, str], ...] = (' in GAM
    assert 'from services.gamification_service import get_missions, MISSION_NAV' in MAIN
    assert 'rows.extend(nav)' in MAIN


# ── desktop photo share: save-to-chat endpoint + Mini App button ───────────
def test_gallery_save_and_badge_endpoints():
    assert "async def _webapp_gallery_save(request: web.Request) -> web.Response:" in MAIN
    assert "app.router.add_post('/webapp/api/gallery/save', _webapp_gallery_save)" in MAIN
    assert "async def _webapp_badge(request: web.Request) -> web.Response:" in MAIN
    assert "app.router.add_get('/webapp/badge/{key}', _webapp_badge)" in MAIN
    assert "it['badge_url'] = f\"/webapp/badge/{it['key']}\" if it.get('has_badge') else ''" in WEB


# ── Mini App surface: lightbox tap, save tile, achievement thumbnails ──────
def test_webapp_badge_and_save_surface():
    # the V3.47.0 gallery regression: tiles must open the lightbox again
    assert '<img loading="lazy" data-lb="1" src=' in INDEX
    assert 'async function savePhotoToChat(imageId) {' in INDEX
    assert 'class="galsave"' in INDEX
    assert "savePhotoToChat(b.dataset.id)" in INDEX
    # achievement art thumbnails on the board
    assert 'class="achimg"' in INDEX
    assert 'it.badge_url' in INDEX
    assert "save_img:" in INDEX and "save_ok:" in INDEX
