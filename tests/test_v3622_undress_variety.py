import os
os.environ.setdefault('TELEGRAM_TOKEN', '123456:test-fake')
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / 'main.py').read_text(encoding='utf-8')


def test_undress_always_nude_and_never_the_same_pose():
    """V3.167.17 (владелец): «раздеть» = НОВЫЙ кадр — другая поза и место, но та же она.
    Полная нагота осталась, мягкий заход — белье."""
    import main
    assert not hasattr(main, 'UNDRESS_VARIANTS_NUDE')
    assert not hasattr(main, 'UNDRESS_VARIANTS_LINGERIE')
    assert not hasattr(main, '_undress_variant')
    for _ in range(60):
        text, _secret = main._undress_prompt(1, 'anna_01')
        assert 'COMPLETELY NAKED' in text and 'CLOTHES:' in text
        # V3.167.17: «UNDRESS REVEAL:» — маркер раздела, а не поза из старого пула.
        assert 'REVEAL:' in text  # UNDRESS REVEAL: is now part of the prompt
    # the lingerie set is no longer a frame he pays for — it lives on only as
    # the gentlest last try when the engine refuses the bold one.
    assert main.UNDRESS_SAFE_VARIANT[0] == 'lace'
    text, _secret = main._undress_prompt(1, 'anna_01', safe=True)
    assert 'COMPLETELY NAKED' not in text and main.UNDRESS_SAFE_VARIANT[1] in text


def test_undress_retries_and_reports_reason():
    assert 'refs[:1], scene=\'undress\'' in SRC
    assert "'reason': f'{type(exc).__name__}: {exc}'[:160] if admin else ''" in SRC


def test_wardrobe_mixes_generic_pool():
    from services.photo_service import _wardrobe_pool
    assert len(_wardrobe_pool('selfie', 1, 'autumn', character_id='vika_01')) > 3


def test_secret_moment_never_adds_a_third_hand():
    """V3.81.1: «3 руки» — the secret never moves a hand; V3.167.17 made that the
    only secret line, since the frame itself no longer moves either."""
    import main
    assert not hasattr(main, 'UNDRESS_SECRET')
    assert not hasattr(main, 'UNDRESS_BOTH_HANDS')
    assert 'finger' not in main.UNDRESS_SECRET_NO_FINGER.split('the secret shows')[1].split('.')[0]
    assert 'exactly two arms and two hands' in main.UNDRESS_SECRET_NO_FINGER
    # V3.167.17: руки описаны в позе выше, поэтому секрет говорит только про голову.
    assert 'without moving her head or her pose' in main.UNDRESS_SECRET_NO_FINGER
    src = __import__('inspect').getsource(main._undress_prompt)
    assert 'prompt += UNDRESS_SECRET_NO_FINGER.format(who=who)' in src
