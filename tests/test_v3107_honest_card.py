"""V3.107.0 — «Без сюрпризов»: honest one-time card + crypto row via Platega."""
from pathlib import Path

from services import honest_card

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
HTML = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_facts_come_from_live_config():
    import config
    f = honest_card.facts()
    assert f['free_messages'] == config.FREE_MESSAGES_PER_DAY
    assert f['free_messages_later'] <= f['free_messages']
    assert f['free_photos'] == config.CHAT_FREE_PHOTOS_PER_DAY
    assert f['week_stars'] == config.PREMIUM_WEEKLY_STARS
    assert f['support'] == config.SUPPORT_BOT_USERNAME
    assert set(f) >= {'enabled', 'free_voice', 'week_rub', 'later_from_day'}


def test_no_fake_social_proof_on_the_card():
    src = (ROOT / 'services' / 'honest_card.py').read_text(encoding='utf-8')
    for bad in ('купили', 'покупают', 'users bought', 'из 5'):
        assert bad not in src
    block = HTML[HTML.index('function openHonest'):HTML.index('async function loadMe')]
    assert 'из 5' not in block and 'count' not in block


def test_me_payload_and_sheet_wiring():
    assert "me['honest'] = honest_card.facts()" in MAIN
    assert 'id="honestmodal"' in HTML and 'id="honestClose"' in HTML
    assert "localStorage.setItem('anbHonestSeen', '1')" in HTML
    assert 'maybeShowHonest();' in HTML and 'id="honestReopen"' in HTML
    assert "hn_title: 'Честно о нас 💜'" in HTML and "hn_title: 'Honestly about us 💜'" in HTML
    assert "hn_go: 'Ок, выбрать героиню'" in HTML and 'без автопродления' in HTML
    # owner: stars abroad, rubles at home
    assert "(LANG === 'ru' && f.week_rub) ? f.week_rub + ' ₽' : f.week_stars + ' ⭐'" in HTML


def test_crypto_row_goes_to_platega_page():
    assert "if method == 'sbp' or method == 'platega_crypto':" in MAIN
    assert 'data-m="platega_crypto"' in HTML
    assert "pay_crypto_pg: 'Криптовалюта'" in HTML
