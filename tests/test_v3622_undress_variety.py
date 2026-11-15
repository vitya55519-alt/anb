import os
os.environ.setdefault('TELEGRAM_TOKEN', '123456:test-fake')
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / 'main.py').read_text(encoding='utf-8')


def test_undress_always_nude_and_never_the_same_pose():
    """V3.166.5 (владелец): «полная нагота всегда» — the relationship level no
    longer decides what is in the frame, only the engine's refusal does."""
    import main
    picks = {main._undress_variant()[0] for _ in range(600)}
    assert picks == {k for k, _ in main.UNDRESS_VARIANTS_NUDE}
    assert {'ass', 'palm', 'squeeze', 'spread'} <= picks  # the four he named
    for _ in range(60):
        text, _secret = main._undress_prompt(1, 'anna_01')
        assert 'COMPLETELY NAKED' in text and 'REVEAL:' in text
    # the lingerie set is no longer a frame he pays for — it lives on only as
    # the gentlest last try when the engine refuses the bold one.
    assert main.UNDRESS_SAFE_VARIANT[0] in {k for k, _ in main.UNDRESS_VARIANTS_LINGERIE}
    text, _secret = main._undress_prompt(1, 'anna_01', safe=True)
    assert 'COMPLETELY NAKED' not in text and main.UNDRESS_SAFE_VARIANT[1] in text


def test_undress_retries_and_reports_reason():
    assert 'refs[:1], scene=\'undress\'' in SRC
    assert "'reason': f'{type(exc).__name__}: {exc}'[:160] if admin else ''" in SRC


def test_wardrobe_mixes_generic_pool():
    from services.photo_service import _wardrobe_pool
    assert len(_wardrobe_pool('selfie', 1, 'autumn', character_id='vika_01')) > 3


def test_secret_moment_never_adds_a_third_hand():
    """V3.81.1: both-hands reveals get the secret without the finger-to-lips."""
    import main
    # V3.166.5: the both-hands set belongs to the nude pool now — those poses
    # leave her no free hand for the finger-to-lips.
    assert main.UNDRESS_BOTH_HANDS <= {k for k, _ in main.UNDRESS_VARIANTS_NUDE}
    assert 'palm' not in main.UNDRESS_BOTH_HANDS
    assert 'finger' not in main.UNDRESS_SECRET_NO_FINGER.split('the secret shows')[1].split('.')[0]
    assert 'exactly two arms and two hands' in main.UNDRESS_SECRET_NO_FINGER
    assert 'never a third hand' in main.UNDRESS_SECRET
    src = __import__('inspect').getsource(main._undress_prompt)
    assert 'UNDRESS_SECRET_NO_FINGER if variant in UNDRESS_BOTH_HANDS else UNDRESS_SECRET' in src
