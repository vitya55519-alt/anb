"""V3.60.1: «Наедине» keeps her face, reuses only fresh renders, shows varied bras."""
from pathlib import Path

from services import private_photo_service as pp
from services.private_photo_service import PrivatePhotoRequest, build_private_photo_prompt

ROOT = Path(__file__).resolve().parents[1]


def test_no_tiny_face_framings():
    for cam in pp.PRIVATE_CAMERA_POOL:
        assert 'whole room' not in cam and 'full body' not in cam and 'full-body' not in cam
    assert not any('eyes closed' in p for p in pp.PRIVATE_POSE_POOL)


def test_face_lock_is_last_with_references():
    req = PrivatePhotoRequest(category='lingerie', type_id='lace', location_id='bedroom', mood_id='', character_id='anna_01')
    prompt = build_private_photo_prompt(req, 'x')
    assert prompt.strip().splitlines()[-1].startswith('FACE LOCK')
    nude = build_private_photo_prompt(PrivatePhotoRequest(category='fully_nude', type_id='bed', location_id='bedroom', mood_id='', character_id='anna_01'), 'x', use_reference=False)
    assert 'FACE LOCK' not in nude


def test_pool_only_reuses_fresh_renders_and_admin_skips_it():
    src = (ROOT / 'services' / 'private_photo_service.py').read_text(encoding='utf-8')
    assert 'PrivateGallery.created_at >= datetime.fromisoformat(PRIVATE_POOL_SINCE)' in src
    main = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert 'pooled = None if telegram_id in ADMIN_TELEGRAM_IDS else pool_get(' in main


def test_lifted_top_types_and_bra_variety():
    ids = {t['id'] for t in pp.PRIVATE_PHOTO_CATEGORIES['suggestive']['types']}
    assert {'top_up', 'top_down', 'open_shirt', 'tank_strap'} <= ids
    req = PrivatePhotoRequest(category='suggestive', type_id='top_up', location_id='bedroom', mood_id='', character_id='anna_01')
    prompt = build_private_photo_prompt(req, 'x')
    assert 'SCENE: she pulls her tight thin top up' in prompt and 'BRA: ' in prompt
    assert len(pp.BRA_CUT_POOL) >= 8 and len(pp.BRA_COLOR_POOL) >= 8


def test_no_black_void_location():
    req = PrivatePhotoRequest(category='studio', type_id='custom', location_id='', mood_id='', character_id='anna_01')
    assert 'never a plain black or empty backdrop' in build_private_photo_prompt(req, 'x')
    studio = next(l for l in pp.LOCATIONS if l['id'] == 'studio')
    assert 'black background' not in studio['name_en']


def test_hot_pass_shares_two_free_photos_then_requires_payment():
    from sqlalchemy import select
    from models.app_models import Base, User
    from services.db import SessionLocal, engine
    from services.user_service import ensure_user

    Base.metadata.create_all(engine)
    telegram_id = 360102
    uid = ensure_user(telegram_id)
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.id == uid))
        user.achievements = ''
        user.private_photo_used = 0
        user.cosplay_photo_used = 0
        user.private_photo_date = None
        user.cosplay_photo_date = None
        session.commit()

    pp.activate_hot_pass(telegram_id, 1)
    assert pp.consume_free_private_photo(telegram_id, 'lingerie')
    assert pp.consume_free_private_photo(telegram_id, 'cosplay')
    assert not pp.consume_free_private_photo(telegram_id, 'roleplay')
    usage = pp.get_private_photo_usage(telegram_id)
    assert usage['hot_pass_left'] == 0
    assert usage['private_used'] == 1
    assert usage['cosplay_used'] == 1

    main = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert "if not is_free and not usage['hot_pass_active']" not in main
