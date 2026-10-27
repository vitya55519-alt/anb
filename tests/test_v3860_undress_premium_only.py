"""V3.86.0: «Раздеть» is Premium-only (owner: no free trial, no peach route)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_gate_refuses_non_premium_before_any_paid_route():
    i = MAIN.index("from config import UNDRESS_PEACH_COST\n")
    body = MAIN[i:i + 900]
    gate = body.index("if not is_premium(telegram_id):\n            return uid, ('premium_required', 403), None")
    assert gate < body.index("'free'") < body.index("'peaches'")
    assert "'trial'" not in body


def test_app_sends_non_premium_to_the_shop():
    assert "toast(action === 'undress' ? L.pa_undress_prem : L.need_premium);" in INDEX
    assert INDEX.count('pa_undress_prem:') >= 2
    assert "esc(L.pa_undress + (ME && ME.premium ? '' : ' ⭐'))" in INDEX
