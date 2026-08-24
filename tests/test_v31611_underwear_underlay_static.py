"""Static regression tests for v3.16.11/v3.17.2: underwear color/style is
injected only where lingerie is meant to be seen, and every level rule
explicitly forbids lingerie worn on top of the outfit."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')


def _underlay_block():
    start = PHOTO.index('underlay_rule = LEVEL_UNDERLAY_RULES.get(level_key')
    return PHOTO[start:PHOTO.index('season = request.season', start)]


def test_underwear_injection_framed_as_under_layer():
    block = _underlay_block()
    # Under-layer framing present in the color injection.
    assert 'The lingerie she wears beneath her outfit is' in block
    assert 'always the under-layer, never outerwear' in block
    # Old phrasings that made the model render lingerie as outerwear are gone.
    assert 'Her underwear this set is' not in block
    assert 'Beneath her main outfit, directly against her skin, she wears' not in block
    assert "f'She is wearing a {request.underwear_style}. '" not in block


def test_color_injection_gated_to_visible_lingerie_contexts():
    block = _underlay_block()
    # Naming the bra/panties in ordinary low-level shots made the model draw
    # them on top of the outfit — the color is injected only at level 5+ or in
    # scenes that intentionally show lingerie.
    assert 'if request.underwear_color and (level_key >= 5 or request.scene in {' in block
    assert "'personal', 'lingerie', 'private_fashion', 'peek', 'dressing'" in block


def test_level_underlay_rule_still_follows_color_injection():
    block = _underlay_block()
    # The injected text is prepended to the existing level rule, not replacing it.
    assert ') + underlay_rule' in block


def test_every_level_rule_forbids_lingerie_over_outfit():
    start = PHOTO.index('LEVEL_UNDERLAY_RULES = {')
    rules = PHOTO[start:PHOTO.index('}\n', start)]
    # All six levels carry the explicit layering guard.
    assert rules.count('never on top of') >= 6
    assert 'clearly but subtly visible' not in rules
    assert 'intentionally visible' not in rules
