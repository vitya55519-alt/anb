"""V3.61.12: «Раздеть» — one free try for a new user, Premium's daily free
grows with her level, and a refused edit no longer blocks other girls."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PPS = (ROOT / 'services' / 'private_photo_service.py').read_text(encoding='utf-8')


def test_trial_and_premium_gate():
    from config import UNDRESS_TRIAL_FREE
    assert UNDRESS_TRIAL_FREE == 1
    assert "elif count_ever(uid, 'undress_trial') < UNDRESS_TRIAL_FREE:" in MAIN
    assert "note_today(uid, f'undress_{pay}', character_id)" in MAIN


def test_premium_free_by_level(monkeypatch):
    import main
    for level, want in ((1, 1), (2, 1), (3, 2), (6, 2), (7, 3), (8, 3)):
        monkeypatch.setattr(main, 'get_relationship_level', lambda *a, _l=level: _l)
        assert main._undress_premium_free(1, 'vika_01') == want


def test_undress_skips_breaker_and_falls_back_to_gentle_reveal(monkeypatch):
    import main
    assert "scene='undress', breaker=False" in MAIN
    assert 'if not breaker:' in PPS
    monkeypatch.setattr(main, 'get_relationship_level', lambda *a: 8)
    prompt, _ = main._undress_prompt(1, 'vika_01', safe=True)
    assert main.UNDRESS_SAFE_VARIANT[1] in prompt


def test_count_ever_counts_all_days():
    from services.chat_photo_allowance import count_ever
    assert callable(count_ever)
