"""V3.125.0: backup 7 Nov — the one man who pays most runs past his Premium
photos at once; English speakers leave on the Russian welcome banner."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
HTML = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_english_banner_asset_exists():
    p = ROOT / 'data' / 'media' / 'welcome_banner_en.png'
    assert p.exists() and p.stat().st_size > 100_000


def test_start_picks_banner_by_language():
    assert 'WELCOME_BANNER_EN_PATH' in MAIN
    assert 'def _welcome_banner_file(lang: str = RU):' in MAIN
    assert 'if lang == EN and WELCOME_BANNER_EN_PATH.exists():' in MAIN
    # V3.142.0: the single send helper picks the banner (gif first, then PNGs)
    assert MAIN.count('banner = _welcome_banner_file(lang)') == 1


def test_paid_photo_reports_price_and_balance():
    assert "paid_note = {'price': CHAT_PHOTO_PEACH_COST, 'left': get_paid_peaches(telegram_id)}" in MAIN
    assert "**({'paid_photo': paid_note} if paid_note else {})," in MAIN
    assert 'if (j.paid_photo) {' in HTML
    assert 'photo_paid: (p, left) =>' in HTML


def test_out_of_peaches_opens_pack_sheet():
    assert "setTimeout(() => quickBuy('photo'), 900);" in HTML
    assert "kind === 'photo' ? ['peach_pack_30', 'peach_pack_100', 'peach_pack_10']" in HTML
    assert 'только купленные персики, бонусные на фото не идут' in MAIN


def test_both_languages_have_photo_strings():
    for key in ('qb_photo:', 'photo_topup:', 'photo_paid:'):
        assert HTML.count(key) == 2, key
