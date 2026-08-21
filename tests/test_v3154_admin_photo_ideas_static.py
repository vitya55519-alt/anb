from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
IDEA_SERVICE = (ROOT / 'services' / 'photo_idea_service.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'photo_models.py').read_text(encoding='utf-8')
DB = (ROOT / 'services' / 'db.py').read_text(encoding='utf-8')


def test_admin_photo_idea_model_exists():
    assert 'class AdminPhotoIdea(Base)' in MODELS
    assert "__tablename__ = 'admin_photo_ideas'" in MODELS
    # db.py registers the model so create_all builds the table on startup.
    assert 'AdminPhotoIdea' in DB


def test_idea_service_admin_api():
    assert 'def idea_counts(' in IDEA_SERVICE
    assert 'def list_admin_ideas(' in IDEA_SERVICE
    assert 'def add_admin_idea(' in IDEA_SERVICE
    assert 'def delete_admin_idea(' in IDEA_SERVICE
    # Admin ideas are merged into the same pool as the curated bank.
    pool_line = [line for line in IDEA_SERVICE.splitlines() if '_load_bank() +' in line]
    assert pool_line and '_load_db_ideas()' in pool_line[0]


def test_admin_panel_ideas_section():
    assert "'admin:ideas'" in MAIN
    assert 'def admin_ideas_keyboard(' in MAIN
    assert 'async def admin_ideas(' in MAIN
    assert 'async def admin_idea_add_start(' in MAIN
    assert 'async def admin_idea_delete_list(' in MAIN
    assert 'async def admin_idea_delete(' in MAIN
    assert 'async def _admin_idea_text_step(' in MAIN


def test_admin_idea_flow_is_admin_only_and_validated():
    for handler in ('admin_ideas(', 'admin_idea_add_start(', 'admin_idea_delete_list(', 'admin_idea_delete('):
        block = MAIN[MAIN.index(f'async def {handler}'):]
        block = block.split('\n@dp.', 1)[0]
        assert 'ADMIN_TELEGRAM_IDS' in block, f'{handler} missing admin guard'
    # Scene input is validated against the known non-private scenes.
    assert 'ALLOWED_IDEA_SCENES' in MAIN
    assert "{'personal', 'lingerie', 'private_fashion'}" in MAIN
    # Text steps are consumed in the main text handler before regular chat.
    assert '_photo_idea_edit_sessions.get(message.from_user.id)' in MAIN
