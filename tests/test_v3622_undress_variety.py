import os
os.environ.setdefault('TELEGRAM_TOKEN', '123456:test-fake')
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / 'main.py').read_text(encoding='utf-8')


def test_undress_has_many_reveals_and_lingerie_only_on_low_levels():
    import main
    low = {main._undress_variant(1)[0] for _ in range(300)}
    assert low <= {k for k, _ in main.UNDRESS_VARIANTS_LINGERIE}
    assert len(low) >= 5
    high = {main._undress_variant(5)[0] for _ in range(400)}
    assert {'topless', 'shirt', 'crossed'} <= high


def test_undress_retries_and_reports_reason():
    assert 'refs[:1], scene=\'undress\'' in SRC
    assert "'reason': f'{type(exc).__name__}: {exc}'[:160] if admin else ''" in SRC


def test_wardrobe_mixes_generic_pool():
    from services.photo_service import _wardrobe_pool
    assert len(_wardrobe_pool('selfie', 1, 'autumn', character_id='vika_01')) > 3


def test_secret_moment_never_adds_a_third_hand():
    """V3.81.1: both-hands reveals get the secret without the finger-to-lips."""
    import main
    assert main.UNDRESS_BOTH_HANDS == {'shirt', 'crossed'}
    assert 'finger' not in main.UNDRESS_SECRET_NO_FINGER.split('the secret shows')[1].split('.')[0]
    assert 'exactly two arms and two hands' in main.UNDRESS_SECRET_NO_FINGER
    assert 'never a third hand' in main.UNDRESS_SECRET
    src = __import__('inspect').getsource(main._undress_prompt)
    assert 'UNDRESS_SECRET_NO_FINGER if variant in UNDRESS_BOTH_HANDS else UNDRESS_SECRET' in src
