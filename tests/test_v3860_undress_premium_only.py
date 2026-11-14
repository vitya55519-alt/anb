"""V3.86.0: «Раздеть» is Premium-only (owner: no free trial, no peach route).
V3.132.0: owner added one «Раздеть» bought on its own for 50 ₽ (credit).
V3.138.0: owner — «не за 50 руб, а за 25, только цену в персиках»: without
Premium the button costs peaches (250 🍑 ≈ 25 ₽), a credit he already bought
still spends first."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_gate_without_premium_goes_through_credit_then_peaches():
    body = MAIN[MAIN.index('async def _webapp_api_photo_action('):]
    body = body[:body.index('    uid, err, pay = await')]
    assert body.index("if not is_premium(telegram_id):") < body.index("undress_credits.balance(telegram_id) > 0")
    # no money paywall any more: short of peaches is a 402, the peach sheet
    assert "return uid, ('credits', 402), None" in body
    assert "return uid, ('premium_required', 403), None" not in body
    assert "'trial'" not in body


def test_app_prices_undress_in_peaches():
    # V3.154.0: owner — «не 250 а 400 персиков». V3.165.0: the owner moved the
    # frame to 300 🍑, and the page stopped carrying a literal at all — the
    # number comes from /me (undress_peaches), PP('undress') is only the
    # first-paint fallback out of ME.peach_prices.
    assert "esc(peachNum(ME.undress_peaches || PP('undress'))) + ' 🍑</small>'" in INDEX
    assert "const undressPeaches = (ME && ME.undress_peaches) || PP('undress');" in INDEX
    assert "ME.undress_one_rub ? '<small>· " not in INDEX
    for stale in ('|| 400', '|| 4000'):
        assert stale not in INDEX, stale


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
