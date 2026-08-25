"""Static regression tests for v3.16.7: paid photo gallery.

Every AI-delivered photo is archived in PhotoDelivery with its raw bytes,
and the user can open /gallery to page through the collection and buy a
full-resolution download for GALLERY_DOWNLOAD_STARS."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
PHOTO_MODELS = (ROOT / 'models' / 'photo_models.py').read_text(encoding='utf-8')
DB = (ROOT / 'services' / 'db.py').read_text(encoding='utf-8')


def test_photo_delivery_stores_full_resolution_bytes():
    assert 'full_resolution_bytes:Mapped[bytes|None]' in PHOTO_MODELS
    assert 'LargeBinary' in PHOTO_MODELS
    # The explicit migration entry documents the column change.
    assert "'full_resolution_bytes': 'BYTEA'" in DB
    # The insert helper persists the bytes and the AI delivery path fills them.
    assert 'full_bytes: bytes | None = None' in PHOTO
    assert 'full_resolution_bytes=full_bytes' in PHOTO
    assert '_download_result_bytes(result)' in PHOTO


def test_gallery_config_and_helpers():
    assert 'GALLERY_DOWNLOAD_STARS = max(1, int(os.getenv("GALLERY_DOWNLOAD_STARS", "30")))' in CONFIG
    assert 'GALLERY_PAGE_SIZE = 6' in PHOTO
    assert 'def get_gallery_page(' in PHOTO
    assert 'def get_gallery_item_bytes(' in PHOTO
    assert 'full_resolution_bytes' in PHOTO


def test_gallery_commands_and_callbacks():
    assert "Command('gallery', 'photos')" in MAIN
    assert "async def gallery_cmd(" in MAIN
    assert "gallery:view:" in MAIN
    assert "gallery:dl:" in MAIN
    assert "gallery:animate:" in MAIN
    assert "gallery:page:" in MAIN
    assert "gallery:back" in MAIN
    assert "gallery:no_dl:" in MAIN
    assert "gallery:noop" in MAIN
    # /gallery is registered in the public command list too.
    assert "BotCommand(command='gallery', description='🖼 Моя галерея')" in MAIN


def test_gallery_download_invoice_and_delivery():
    # Invoice uses the gallery_dl:<delivery_id> payload at GALLERY_DOWNLOAD_STARS.
    assert "f'gallery_dl:{delivery_id}'" in MAIN
    assert "GALLERY_DOWNLOAD_STARS," in MAIN
    # Pre-checkout validates the payload and the bytes are still available.
    assert "payload.startswith('gallery_dl:')" in MAIN
    assert "ok = amount == GALLERY_DOWNLOAD_STARS and bool(get_gallery_item_bytes(query.from_user.id, delivery_id))" in MAIN
    # Successful payment re-loads bytes and sends them as a Telegram document.
    assert "await bot.send_document(" in MAIN
    assert "BufferedInputFile(snap['bytes'], filename=snap['filename'])" in MAIN
    # If bytes are gone between invoice and payment, the purchase is auto-refunded.
    assert "product='gallery_download'" in MAIN


def test_gallery_animate_reuses_video_gate():
    # The gallery "🎬" button must route through the same admin/Premium/Stars
    # video gate as the per-photo animate button. V3.19.0: both go through the
    # motion preset picker first; the preset callback then calls the gate.
    animate = MAIN[MAIN.index("async def gallery_animate_cb("):]
    animate = animate.split('\n\n\n@dp.', 1)[0]
    assert '_show_video_preset_menu(cq.message.chat.id' in animate
    assert 'get_photo_delivery_for_user(cq.from_user.id, delivery_id)' in animate
    preset = MAIN[MAIN.index("async def video_preset_cb("):]
    preset = preset.split('\n\n\n@dp.', 1)[0]
    assert '_video_gate(cq, delivery' in preset
