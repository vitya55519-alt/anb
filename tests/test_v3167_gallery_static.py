"""Static regression tests for v3.16.7: paid photo gallery.

Every AI-delivered photo is archived in PhotoDelivery with its raw bytes,
and the user can open /gallery to page through the collection and buy a
full-resolution download for GALLERY_DOWNLOAD_STARS."""
import ast
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
    payment = next(node for node in ast.parse(MAIN).body
                   if isinstance(node, ast.AsyncFunctionDef) and node.name == 'successful_payment')
    gallery = next(node for node in payment.body if isinstance(node, ast.If)
                   and ast.unparse(node.test) == "payload.startswith('gallery_dl:')")
    calls = [node for node in ast.walk(gallery) if isinstance(node, ast.Call)]
    assert any(ast.unparse(node) == 'get_gallery_item_bytes(message.from_user.id, delivery_id)'
               for node in calls)

    # Keep the original bytes and their MIME in app storage, with one photo
    # Message in the source heroine's dialogue, never a Telegram media upload.
    storage = [node for node in calls if ast.unparse(node.func) == 'asyncio.to_thread'
               and ast.unparse(node.args[0]) == 'webapp_service.save_chat_media']
    assert len(storage) == 1
    assert [ast.unparse(arg) for arg in storage[0].args[1:]] == [
        'message.from_user.id', "snap['bytes']", 'ext', 'mime']
    rows = [node for node in calls if ast.unparse(node.func) == 'asyncio.to_thread'
            and ast.unparse(node.args[0]) == 'save_message']
    assert len(rows) == 1
    assert [ast.unparse(arg) for arg in rows[0].args[1:4]] == [
        'ensure_user(message.from_user.id)', 'character_id', "'assistant'"]
    assert {kw.arg: ast.unparse(kw.value) for kw in rows[0].keywords} == {
        'media_kind': "'photo'", 'media_url': "f'/webapp/media/{filename}'"}
    assert any(isinstance(node, ast.Assign) and ast.unparse(node) ==
               "character_id = (delivery or {}).get('character_id') or get_user_character(message.from_user.id)"
               for node in ast.walk(gallery))
    assert any(ast.unparse(node) == "_app_ping(message.from_user.id, character_id, '', 'photo')"
               for node in calls)
    assert not any(isinstance(node.func, ast.Attribute) and node.func.attr in {
        'send_document', 'send_photo', 'send_video', 'send_media_group',
        'answer_document', 'answer_photo', 'answer_video', 'answer_media_group'} for node in calls)

    # Missing source bytes and app-storage failures both retain the refund.
    missing = next(node for node in gallery.body if isinstance(node, ast.If)
                   and ast.unparse(node.test) == 'not snap')
    delivery = next(node for node in gallery.body if isinstance(node, ast.Try)
                    and storage[0] in list(ast.walk(node)))
    for failure in (missing, delivery.handlers[0]):
        refunds = [node for node in ast.walk(failure) if isinstance(node, ast.Call)
                   and ast.unparse(node.func) == 'bot.refund_star_payment']
        assert len(refunds) == 1
        assert {kw.arg: ast.unparse(kw.value) for kw in refunds[0].keywords} == {
            'user_id': 'message.from_user.id', 'telegram_payment_charge_id': 'charge'}
        assert any(isinstance(node, ast.Call) and ast.unparse(node) ==
                   "record_refund(message.from_user.id, charge, payment.total_amount, product='gallery_download')"
                   for node in ast.walk(failure))


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
