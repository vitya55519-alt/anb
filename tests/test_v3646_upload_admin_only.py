"""V3.64.6: generating from an uploaded real photo is admin-only."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
WEB = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_studio_upload_refused_for_users():
    assert MAIN.count("if body.get('image') and telegram_id not in ADMIN_TELEGRAM_IDS:") == 2
    assert "'error': 'upload_admin_only'" in MAIN


def test_constructor_drops_uploaded_refs_for_users():
    assert "if k not in ('photo_reference_base64', 'face_bytes', 'face_file_id')}" in MAIN
    assert "if step.get('photo_upload') and not admin:" in WEB
    assert "api_constructor_steps, request.query.get('lang', 'ru'), admin=free)" in MAIN


def test_upload_button_hidden_for_users():
    assert "if (!(ME && ME.admin)) document.querySelector('.uplRow').style.display = 'none';" in INDEX
