from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
main = (ROOT / "main.py").read_text(encoding="utf-8")
photo = (ROOT / "services" / "photo_service.py").read_text(encoding="utf-8")
config = (ROOT / "config.py").read_text(encoding="utf-8")

assert "'gym': '🏋️ Зал'" in main
assert "'gym': 2" in photo
assert "'gym':'gym'" in photo
assert "omni-moderation-latest" in config
assert "_library_photo_is_allowed" in main
assert "sexual/minors" in main and "categories.get('sexual')" in main
assert "required = max(1, int(SCENE_LEVELS.get(scene, 1)))" in main
print("V3.9.3 safe library + gym static test passed")
