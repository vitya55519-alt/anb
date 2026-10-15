from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_testlevel_accepts_all_eight_levels():
    src = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert "1 <= int(arg) <= len(STAGES)" in src
    assert '/testlevel 1..10' in src
    from services.test_mode import STAGES
    assert len(STAGES) == 10 and STAGES[-1] == 'eternal'  # V3.62.0
