from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
for p in ROOT.rglob('*.py'):
    ast.parse(p.read_text(encoding='utf-8'), filename=str(p))

main = (ROOT/'main.py').read_text(encoding='utf-8')
photo = (ROOT/'services/photo_service.py').read_text(encoding='utf-8')
lib = (ROOT/'services/photo_library_service.py').read_text(encoding='utf-8')
rel = (ROOT/'services/relationship_engine.py').read_text(encoding='utf-8')
models = (ROOT/'models/photo_models.py').read_text(encoding='utf-8') + (ROOT/'models/relationship_models.py').read_text(encoding='utf-8')
state = (ROOT/'services/state_service.py').read_text(encoding='utf-8')

assert "frame_elapsed = time.monotonic() - frame_started" in photo
assert "value=elapsed" not in photo
assert "Seedream safe retry" in photo and "HTTP 422" in photo
assert "telegram_library" in photo and "choose_unseen_pack" in photo
assert "class PhotoLibraryPack" in models and "class UserSeenPhotoPack" in models
assert "import_buffered_photos" in lib and "progression" in lib and "collection" in lib
assert "Command('libraryimport')" in main and "Command('library')" in main
assert "libimp:save" in main and "libimp:undo" in main and "10 / 10" in main
assert "alena_character" in main and "fake_door_click" in main
assert "familiarity_score" in rel and "continuity_score" in rel and "connection_score" in rel
assert "RelationshipMilestone" in models and "apply_absence_decay" in rel and "return 0" in rel
assert "apply_life_choice" in state and "_contextualize_vague_photo" in main
assert (ROOT/'PHOTO_LIBRARY_SEEDREAM5_PROMPTS.md').exists()
print('V391_LIBRARY_RELATIONSHIP_STATIC_OK')
