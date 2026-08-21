from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
ANNA_CARD = (ROOT / 'data' / 'characters' / 'anna.json').read_text(encoding='utf-8')

def _has_bust(block: str) -> bool:
    return 'silicone implants' in block and 'Russian size 4, D cup' in block


def test_bust_identity_covers_all_photo_routes():
    body = PHOTO.split('ANNA_BODY_IDENTITY = (', 1)[1].split(')\nOPENAI_REFERENCE_PROTOCOL', 1)[0]
    assert _has_bust(body)
    ordinary = PHOTO.split('ORDINARY_BODY_IDENTITY = (', 1)[1].split(')\nORDINARY_REFERENCE_PROTOCOL', 1)[0]
    assert _has_bust(ordinary)
    protocol = PHOTO.split('OPENAI_REFERENCE_PROTOCOL = (', 1)[1].split(')\n# V3.14.1', 1)[0]
    assert _has_bust(protocol)
    reinforcement = PHOTO.split('BODY_REINFORCEMENT = (', 1)[1].split(')\nEXPRESSION_IDENTITY', 1)[0]
    assert _has_bust(reinforcement)
    seedream = PHOTO.split('SEEDREAM_IDENTITY_LOCK = (', 1)[1].split(')\nBODY_REINFORCEMENT_SCENES', 1)[0]
    assert _has_bust(seedream)


def test_bust_identity_overrides_reference_if_smaller():
    # The canonical look reference may still show a smaller bust, so every
    # block must explicitly override it instead of matching the reference.
    body = PHOTO.split('ANNA_BODY_IDENTITY = (', 1)[1].split(')\nOPENAI_REFERENCE_PROTOCOL', 1)[0]
    assert 'even if the reference shows a smaller one' in body


def test_slim_fit_build_is_preserved_alongside_bust():
    body = PHOTO.split('ANNA_BODY_IDENTITY = (', 1)[1].split(')\nOPENAI_REFERENCE_PROTOCOL', 1)[0]
    assert 'slim' in body
    assert 'fit' in body
    assert 'slim waist' in body


def test_anna_card_lists_bust_as_canonical_trait():
    assert 'full bust with silicone implants (Russian size 4, D cup)' in ANNA_CARD
