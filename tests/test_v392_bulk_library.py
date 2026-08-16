import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

fd, db_path = tempfile.mkstemp(prefix='annabot_v392_', suffix='.db')
os.close(fd)
os.environ['DATABASE_URL'] = f'sqlite:///{db_path}'
os.environ.setdefault('TELEGRAM_TOKEN', '123456:TEST_TOKEN')
os.environ.setdefault('OPENAI_API_KEY', 'test-key')

try:
    from services.photo_library_service import import_buffered_photos, regroup_collection_packs, library_stats

    photos = [
        {'file_id': f'file_{i}', 'unique_id': f'unique_{i}', 'caption': None}
        for i in range(7)
    ]
    first = import_buffered_photos('anna_01', 'selfie', 1, 'collection', photos)
    assert first['packs_created'] == 7
    assert first['photos_saved'] == 7

    result = regroup_collection_packs('anna_01', 'selfie', 1)
    assert result == {
        'packs_created': 2,
        'photos_regrouped': 6,
        'leftover_single_photos': 1,
    }

    snap = library_stats('anna_01')
    row = snap['by_scene'][('anna_01', 'selfie', 1)]
    assert row['photos'] == 7
    assert row['packs'] == 3  # two 3-photo progression packs + one untouched single

    progression = import_buffered_photos('anna_01', 'park', 2, 'progression', photos[:6])
    assert progression['packs_created'] == 2
    assert progression['photos_saved'] == 6
    assert progression['tail_unsaved'] == 0

    print('V392_BULK_LIBRARY_OK')
finally:
    try:
        os.remove(db_path)
    except OSError:
        pass
