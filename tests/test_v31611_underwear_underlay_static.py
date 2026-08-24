"""Static regression tests for v3.16.11: underwear color/style must be framed
strictly as the under-layer beneath the main outfit, never as outerwear, so
the image model does not render the lingerie on top of the clothes."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')


def _underlay_block():
    start = PHOTO.index('underlay_rule = LEVEL_UNDERLAY_RULES.get(level_key')
    return PHOTO[start:PHOTO.index('season = request.season', start)]


def test_underwear_injection_framed_as_under_layer():
    block = _underlay_block()
    # New under-layer framing present.
    assert 'Beneath her main outfit, directly against her skin, she wears' in block
    assert 'It is strictly the under-layer under her clothes and never replaces them' in block
    assert 'the main outfit stays fully on' in block
    # Old standalone phrasing that made the model render lingerie as outerwear is gone.
    assert 'Her underwear this set is' not in block
    assert "f'She is wearing a {request.underwear_style}. '" not in block


def test_level_underlay_rule_still_follows_color_injection():
    block = _underlay_block()
    # The injected text is prepended to the existing level rule, not replacing it.
    assert ') + underlay_rule' in block
