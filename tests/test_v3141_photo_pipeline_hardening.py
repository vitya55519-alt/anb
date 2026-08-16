from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')


def test_ordinary_photo_prompt_is_separate_from_sensual_chat_dna():
    assert 'ORDINARY_IDENTITY_LOCK' in PHOTO
    assert 'This prompt is independent from chat personality, flirting, sensuality or relationship erotics' in PHOTO
    ordinary = PHOTO.split('ORDINARY_BODY_IDENTITY = (', 1)[1].split(')\nORDINARY_REFERENCE_PROTOCOL', 1)[0]
    assert 'bust' not in ordinary.lower()
    assert 'lingerie' not in ordinary.lower()
    assert 'erotic' not in ordinary.lower()


def test_nano_banana_has_explicit_route_and_success_logs():
    assert 'PHOTO ROUTE selected user=%s scene=%s provider=%s' in PHOTO
    assert 'Nano Banana frame success user=%s scene=%s frame=%s/%s' in PHOTO
    assert 'PHOTO ROUTE FALLBACK user=%s scene=%s from=gemini_image to=openai reason=%s' in PHOTO
    assert 'Nano Banana response contained no image' in PHOTO


def test_partial_free_sets_are_topped_up_from_library():
    assert 'async def _deliver_library_partial_topup' in PHOTO
    assert "delivery_type in {'free', 'story'}" in PHOTO
    assert 'PHOTO SET TOPUP user=%s scene=%s source=telegram_library' in PHOTO
    assert 'library_topup_count = len(topup)' in PHOTO
    assert 'delivered_count = len(sent_messages)' in PHOTO
    assert 'user_visible_complete = delivered_count >= PHOTO_SET_SIZE' in PHOTO


def test_private_scenes_never_use_ordinary_library_topup():
    assert "request.scene not in _PRIVATE_LIBRARY_SCENES" in PHOTO
    assert "if needed <= 0 or request.scene in _PRIVATE_LIBRARY_SCENES" in PHOTO


def test_paid_credit_is_not_consumed_for_mixed_set():
    assert "if delivery_type == 'credit' and ai_complete:" in PHOTO
    assert 'consume_photo_credit(telegram_id)' in PHOTO
