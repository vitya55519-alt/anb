from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
main = (ROOT / 'main.py').read_text(encoding='utf-8')
models = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
service = (ROOT / 'services' / 'character_card_service.py').read_text(encoding='utf-8')
db = (ROOT / 'services' / 'db.py').read_text(encoding='utf-8')

assert 'class CharacterCard(Base):' in models
assert 'character_cards' in models
assert 'CharacterCard' in db
assert "Command('admin')" in main
# V3.22.0: keyboard labels live in services/ui_lang.py as (ru, en) pairs.
from services.ui_lang import KB_LABELS
assert KB_LABELS['admin'][0] == '🛠 Админка'
assert "F.text.in_(kb_pair('admin'))" in main
assert "admin:cards" in main
assert "admin:cardedit:" in main
assert "admin:setstatus:" in main
assert "card_photo_file_id" in main
assert "character:view:" in main
assert 'DEFAULT_CARDS' in service
assert 'update_card' in service and 'reset_card' in service
print('V3.10.0 character cards static test passed')
