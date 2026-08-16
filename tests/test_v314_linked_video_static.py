from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_linked_video_schema_and_migration_present():
    model = (ROOT / 'models' / 'photo_models.py').read_text(encoding='utf-8')
    db = (ROOT / 'services' / 'db.py').read_text(encoding='utf-8')
    assert 'linked_video_file_id' in model
    assert 'linked_video_unique_id' in model
    assert 'linked_video_caption' in model
    assert "_add_missing_columns('photo_library_items'" in db


def test_importer_pairs_video_with_previous_photo():
    main = (ROOT / 'main.py').read_text(encoding='utf-8')
    service = (ROOT / 'services' / 'photo_library_service.py').read_text(encoding='utf-8')
    assert 'Схема: фото → видео → следующее фото → видео' in main
    assert '@dp.message(F.video)' in main
    assert "target['video_file_id'] = file_id" in main
    assert "linked_video_file_id=photo.get('video_file_id')" in service
    assert "'videos_saved': sum(1 for p in photos if p.get('video_file_id'))" in service


def test_photo_delivery_exposes_linked_video_button():
    photo_service = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
    main = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert "text='🎬 Смотреть видео'" in photo_service
    assert "callback_data=f'libvideo:{item.item_id}'" in photo_service
    assert "@dp.callback_query(F.data.startswith('libvideo:'))" in main
    assert 'get_linked_video(' in main
    assert 'await bot.send_video(' in main


def test_tenth_photo_does_not_force_preview_before_optional_video():
    main = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert 'Do not auto-enter preview at 10/10' in main
    assert "if count in {1, 5, 10}:" in main
