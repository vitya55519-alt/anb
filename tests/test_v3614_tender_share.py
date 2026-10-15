"""V3.61.4: tenderness-path photos and sharing the photo itself."""
from pathlib import Path

from services import photo_service as ps

ROOT = Path(__file__).resolve().parents[1]


def test_tender_path_has_its_own_poses_and_threshold():
    assert ps.TENDER_PATH_THRESHOLD == -20.0
    assert len(ps.TENDER_POSE_POOL) >= 5
    assert all('same face as reference image 1' in p for p in ps.TENDER_POSE_POOL)
    src = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
    assert 'poses = list(TENDER_POSE_POOL)' in src
    assert 'tender = not passion and _path_is_tender(' in src


def test_share_sends_a_prepared_photo_message():
    main = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert "'/webapp/api/gallery/prepare-share'" in main
    assert 'save_prepared_inline_message' in main and 'InlineQueryResultPhoto' in main
    assert "'/webapp/shared/{uid}/{image_id}/{sig}.jpg'" in main
    html = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
    assert 'tg.shareMessage(j.id)' in html
    assert 'sharePhotoImage(b.dataset.share, b.dataset.id)' in html


def test_share_signature_is_stable_and_per_image():
    import main
    a = main._share_sig(1, 2)
    assert a == main._share_sig(1, 2)
    assert a != main._share_sig(1, 3) and a != main._share_sig(2, 2)
