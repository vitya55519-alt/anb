from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHOTO = (ROOT / "services" / "photo_service.py").read_text(encoding="utf-8")
ANNA = (ROOT / "data" / "characters" / "anna.json").read_text(encoding="utf-8")


def test_dual_identity_blocks_present():
    assert "ANNA_FACE_IDENTITY" in PHOTO
    assert "ANNA_BODY_IDENTITY" in PHOTO
    assert "OPENAI_REFERENCE_PROTOCOL" in PHOTO
    assert "BODY_REINFORCEMENT" in PHOTO


def test_openai_uses_multiple_reference_images():
    assert "def _openai_reference_paths" in PHOTO
    assert "image=image_files" in PHOTO
    assert "01_anna_canonical_look_v3.png" in PHOTO


def test_safety_does_not_flatten_identity():
    assert "safety changes styling, not identity" in PHOTO
    assert "do not flatten, reduce, enlarge" in PHOTO
    assert "do not emphasize chest, hips, buttocks" not in PHOTO


def test_character_points_to_body_anchor():
    assert '"openai_body_anchor": "01_anna_canonical_look_v3.png"' in ANNA
    assert '"canonical_body_anchor": "01_anna_canonical_look_v3.png"' in ANNA
    assert (ROOT / "data" / "references" / "anna" / "01_anna_canonical_look_v3.png").exists()
