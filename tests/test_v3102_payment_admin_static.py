from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
MODELS = (ROOT / "models" / "app_models.py").read_text(encoding="utf-8")
SERVICE = (ROOT / "services" / "payment_method_service.py").read_text(encoding="utf-8")
DB = (ROOT / "services" / "db.py").read_text(encoding="utf-8")


def test_payment_method_model_and_db_registration():
    assert "class PaymentMethod(Base):" in MODELS
    assert 'method_key' in MODELS
    assert 'qr_photo_file_id' in MODELS
    assert 'external_url' in MODELS
    assert 'PaymentMethod' in DB


def test_admin_payment_methods_are_configurable_without_deploy():
    assert "💳 Способы оплаты" in MAIN
    assert "admin:paymentadd:qr" in MAIN
    assert "admin:paymentadd:link" in MAIN
    assert "admin:paymentedit:" in MAIN
    assert "qr_photo_file_id=ph.file_id" in MAIN
    assert "create_payment_method('link'" in MAIN


def test_stars_are_protected_for_digital_checkout():
    assert '"telegram_stars"' in SERVICE
    assert '"digital_stars"' in SERVICE
    assert 'clean.pop("status", None)' in SERVICE
    assert "currency='XTR'" in MAIN


def test_future_features_are_visible_but_locked():
    assert "🔒 🎬 Оживить фото · скоро" in MAIN
    # Renamed from «Звонок с Анной» when multi-character selection was introduced.
    assert "🔒 📞 Звонок с персонажем · скоро" in MAIN
    assert "future_feature_locked" in MAIN


def test_payment_support_is_present():
    assert "Command('paysupport')" in MAIN
    assert "payment_support_request" in MAIN
