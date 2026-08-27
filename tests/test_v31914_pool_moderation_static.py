"""Static pins for v3.19.14: owner moderation of the community photo pool.

Owner asked to see the shared gallery (all AI-generated public frames enter
the community pool) and remove bad photos so other users never receive them.
photo_service gains admin helpers; main.py gains a poolmod callback flow
reachable from the admin keyboard, gated to admins only.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def test_photo_service_admin_pool_helpers_exist():
    for name in (
        'def admin_pool_count(',
        'def admin_pool_get(',
        'def admin_pool_latest_id(',
        'def admin_pool_neighbor(',
        'def admin_pool_set_shared(',
    ):
        assert name in PHOTO


def test_pool_navigation_stays_inside_shared_pool():
    # Browsing and deletion must only touch community-shared deliveries.
    assert PHOTO.count('PhotoDelivery.community_shared.is_(True)') >= 4


def test_admin_keyboard_exposes_pool_moderation():
    assert "callback_data='poolmod:view'" in MAIN
    assert '🖼 Общая галерея (модерация)' in MAIN


def test_pool_moderation_handler_is_admin_gated_and_removes():
    block = MAIN[MAIN.index("@dp.callback_query(F.data.startswith('poolmod:'))"):
                 MAIN.index("def admin_home(")]
    assert 'cq.from_user.id not in ADMIN_TELEGRAM_IDS' in block
    # Removal is a flag flip, not a row delete: the original owner keeps it.
    assert 'admin_pool_set_shared(target, False)' in block
    assert 'session.delete' not in block
    # In-place photo navigation (no message spam).
    assert 'edit_media' in block
    assert 'admin_pool_neighbor(' in block


def test_pool_helpers_imported_into_main():
    assert 'admin_pool_set_shared,' in MAIN
    assert 'from services.photo_service import' in MAIN
