"""V3.86.0: «Раздеть» is Premium-only (owner: no free trial, no peach route).
V3.132.0: owner added one «Раздеть» bought on its own for 50 ₽ (credit)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_gate_refuses_non_premium_before_any_paid_route():
    i = MAIN.index("from config import UNDRESS_PEACH_COST\n")
    body = MAIN[i:i + 1500]
    gate = body.index("return uid, ('premium_required', 403), None")
    assert body.index("if not is_premium(telegram_id):") < gate < body.index("'free'") < body.index("'peaches'")
    # the only route without Premium is a bought single credit
    assert body.index("undress_credits.balance(telegram_id) > 0") < gate
    assert "'trial'" not in body


def test_app_sends_non_premium_to_the_shop():
    assert "toast(action === 'undress' ? L.pa_undress_prem : L.need_premium);" in INDEX
    assert INDEX.count('pa_undress_prem:') >= 2
    assert "ME.undress_one_rub ? '<small>· ' + esc(ME.undress_one_rub) + ' ₽</small>'" in INDEX


WEB = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')


def _spicy_re():
    import re
    i = WEB.index('_PICTURE_SPICY_RE = re.compile(')
    j = WEB.index('\n)\n', i) + 3
    ns = {'re': re}
    exec(WEB[i:j], ns)
    return ns['_PICTURE_SPICY_RE']


def test_studio_spicy_prompts_detected_without_false_alarms():
    r = _spicy_re()
    for t in ('голая девушка на кровати', 'she is naked in the shower', 'девушка в нижнем белье',
              'red lingerie', 'girl striptease', 'сексуальная блондинка'):
        assert r.search(t), t
    for t in ('девушка в красном платье в кафе', 'girl in striped dress', 'связанный свитер, осень',
              'кончик носа', 'закончи рисунок', 'anime girl with sword', 'beach in bikini'):
        assert not r.search(t), t


def test_studio_explicit_is_premium_only():
    i = MAIN.index('async def _webapp_api_picture_generate(')
    body = MAIN[i:i + 6000]
    assert "if not prem_ok and webapp_service.picture_prompt_spicy(prompt):" in body
    assert "adult_ok = is_adult_confirmed(telegram_id) and prem_ok and ref_path is None" in body
    assert body.index('picture_prompt_spicy(prompt)') < body.index('generate_private_photo_t2i')
    assert "if (jp.error === 'premium_required') { toast(L.pic_spicy_prem); quickBuy('spicy'); return; }" in INDEX
