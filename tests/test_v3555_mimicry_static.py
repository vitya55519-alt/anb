"""V3.55.5 — mimicry expansion + tongue realism anchors (owner feedback).

The owner loved the playful tongue-out selfie but the rendered tongue looked
fake («язык не реальный, надо лучше качество»). Two-part fix, pinned statically:

1. Every tongue/mouth expression now carries an explicit anatomical anchor —
   a single anatomically correct tongue, tip only, natural pink moist texture —
   plus a never-fully-protruding clause; the NEGATIVE_BLOCK rejects protruding/
   extra/plastic tongues and deformed mouths outright.
2. The bank grew: tongue_out_playful / wink / shush join the default sensual
   rotation, wink / surprised / sleepy_soft join the everyday variety pool.

Static pins (no imports -> the suite runs without a DB/LLM key)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPR = (ROOT / 'services' / 'photo_expression_service.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')


def _block(key: str) -> str:
    """Slice of the EXPRESSIONS dict text belonging to one key only."""
    start = EXPR.index(f"'{key}': (")
    end = EXPR.index('\n    ),\n', start) + len('\n    ),\n')
    return EXPR[start:end]


def test_new_mimicry_keys_defined():
    for key in ('tongue_out_playful', 'wink', 'shush', 'surprised', 'sleepy_soft'):
        assert f"'{key}': (" in EXPR


def test_playful_keys_join_the_rotations():
    sensual = EXPR[EXPR.index('SENSUAL_KEYS'):EXPR.index('VARIETY_KEYS')]
    variety = EXPR[EXPR.index('VARIETY_KEYS'):EXPR.index('def shuffled_variety_keys')]
    assert "'tongue_out_playful'" in sensual and "'wink'" in sensual and "'shush'" in sensual
    assert "'wink'" in variety and "'surprised'" in variety and "'sleepy_soft'" in variety


def test_tongue_expressions_carry_anatomy_anchors():
    # every tongue-bearing description pins a single anatomically correct tongue
    for key in ('desire', 'licking_lips', 'tongue_out_playful'):
        block = _block(key)
        assert 'anatomically' in block, key
        assert 'tongue' in block, key
    # and each one caps how far the tongue goes
    assert 'never a long fully protruding tongue' in _block('desire')
    assert 'never sticking far out' in _block('licking_lips')
    assert 'not a long hanging tongue' in _block('tongue_out_playful')


def test_shush_pins_a_correct_hand():
    assert 'five correct fingers' in _block('shush')


def test_negative_block_rejects_tongue_artifacts():
    neg = PHOTO[PHOTO.index('NEGATIVE_BLOCK = ('):PHOTO.index('@dataclass(frozen=True)\nclass GeneratedPhoto')]
    assert 'protruding or extra tongue' in neg
    assert 'fake plastic-looking tongue' in neg
    assert 'deformed mouth interior' in neg
