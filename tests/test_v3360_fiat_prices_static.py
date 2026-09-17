"""V3.36.0 static checks: every Telegram Stars price in the product carries
its ruble and dollar equivalent — the owner asked for «напротив каждой цены
звездочек добавь цену в рублях и долларах». The fiat display rides on a
config ladder (roughly what Stars cost to top up); premium and the character
constructor reuse their REAL card prices (FREEKASSA_PREMIUM_PRICE_USD is the
actual Visa/MC charge, not a marketing number).
"""
import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
LEGAL = (ROOT / 'services' / 'legal_service.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_version_bumped():
    assert VERSION in ('3.43.5', '3.43.4', '3.43.3', '3.43.2', '3.43.1', '3.43.0', '3.42.2', '3.42.1', '3.42.0', '3.41.0', '3.40.0', '3.36.0', '3.37.0', '3.38.0', '3.39.0')


def test_config_fiat_helpers():
    assert 'STARS_FIAT_RUB: dict[int, int]' in CONFIG
    assert 'STARS_FIAT_USD: dict[int, float]' in CONFIG
    assert 'def usd_str(value: float) -> str:' in CONFIG
    assert 'def fiat_values(stars: int)' in CONFIG
    assert 'def fiat_suffix(stars: int' in CONFIG
    # rub part hides when rub_enabled=False — a real charge that is off;
    # the dollar equivalent still shows.
    assert 'if rub_enabled:' in CONFIG
    assert "parts.append(f'{rub} ₽')" in CONFIG
    assert 'parts.append(usd_str(usd))' in CONFIG


def test_config_fiat_ladder_covers_catalog():
    cfg = importlib.import_module('config')
    # every priced product maps to a ladder entry or a sane fallback
    for stars in (cfg.PHOTO_COST_STARS, cfg.CHAT_PHOTO_OFFER_STARS,
                  cfg.CUSTOM_PHOTO_COST_STARS, cfg.QUEST_REPLAY_STARS,
                  cfg.VIDEO_COST_STARS, cfg.GALLERY_DOWNLOAD_STARS,
                  cfg.CONSTRUCTOR_COST_STARS):
        rub, usd = cfg.fiat_values(stars)
        assert rub is None or rub >= 1
        assert usd is None or usd >= 0.05
    # premium month dollars are the REAL card price, weekly/ctor are marketing
    assert cfg.PREMIUM_WEEKLY_PRICE_USD >= 1
    assert cfg.CONSTRUCTOR_PRICE_USD >= 1
    assert 'PREMIUM_WEEKLY_PRICE_USD = float(os.getenv' in CONFIG
    assert 'CONSTRUCTOR_PRICE_USD = float(os.getenv' in CONFIG


def test_fiat_suffix_runtime_shapes():
    cfg = importlib.import_module('config')
    rub, usd = cfg.fiat_values(25)
    assert cfg.fiat_suffix(25) == f' · {rub} ₽ · {cfg.usd_str(usd)}'
    # explicit overrides win over the ladder
    assert cfg.fiat_suffix(50, rub=200, usd=2.5) == ' · 200 ₽ · $2.5'
    # rub hidden, dollars stay
    assert cfg.fiat_suffix(500, rub=299, usd=5, rub_enabled=False) == ' · $5'
    # unknown star counts fall back to ~2 ₽ / ~$0.024 per Star
    assert '₽' in cfg.fiat_suffix(777)
    assert '$' in cfg.fiat_suffix(777)


def test_main_every_star_price_has_fiat():
    # chat photo offer, quest replay, constructor menu, premium pitch +
    # keyboard (both plans), video animate, custom photo, photo paywall,
    # gallery texts/buttons, spicy menus, gifts menu, dates menu
    for needle in (
        'fiat_suffix(CHAT_PHOTO_OFFER_STARS)',
        'fiat_suffix(QUEST_REPLAY_STARS)',
        'fiat_suffix(CONSTRUCTOR_COST_STARS, rub=CONSTRUCTOR_COST_RUB, usd=CONSTRUCTOR_PRICE_USD)',
        'fiat_suffix(PREMIUM_WEEKLY_STARS, rub=FREEKASSA_PREMIUM_WEEKLY_PRICE_RUB, usd=PREMIUM_WEEKLY_PRICE_USD',
        'fiat_suffix(PREMIUM_MONTHLY_STARS, rub=FREEKASSA_PREMIUM_PRICE_RUB, usd=FREEKASSA_PREMIUM_PRICE_USD',
        'fiat_suffix(VIDEO_COST_STARS)',
        'fiat_suffix(CUSTOM_PHOTO_COST_STARS)',
        'fiat_suffix(PHOTO_COST_STARS)',
        'fiat_suffix(GALLERY_DOWNLOAD_STARS)',
        'fiat_suffix(item.cost)',
        'fiat_suffix(gift.cost)',
        'fiat_suffix(gifts_service.effective_cost(g))',
        'fiat_suffix(d.cost)',
    ):
        assert needle in MAIN, needle
    # the wizard's options payload carries rub + usd for the price note
    assert "'rub': CONSTRUCTOR_COST_RUB," in MAIN
    assert "'usd': CONSTRUCTOR_PRICE_USD," in MAIN


def test_main_imports_fiat_helpers():
    head = MAIN[:MAIN.index('def ') if 'def ' in MAIN else 8000]
    assert 'fiat_suffix,' in head or 'fiat_suffix' in MAIN[:6000]


def test_webapp_service_items_carry_fiat():
    assert "'constructor_usd': CONSTRUCTOR_PRICE_USD," in WEBAPP_SVC
    assert "'usd': FREEKASSA_PREMIUM_PRICE_USD," in WEBAPP_SVC
    assert "'usd': PREMIUM_WEEKLY_PRICE_USD," in WEBAPP_SVC
    # V3.43.1: the single-credit fiat pair became the peach pack fiat pairs.
    assert "'rub': p10_rub," in WEBAPP_SVC and "'usd': p100_usd," in WEBAPP_SVC
    assert "'rub': rub if rub is not None else fiat_values(s)[0]," in WEBAPP_SVC
    # the constructor item carries its REAL card prices, not the ladder
    assert 'CONSTRUCTOR_COST_RUB if FREEKASSA_ENABLED else None, CONSTRUCTOR_PRICE_USD),' in WEBAPP_SVC


def test_frontend_renders_fiat_next_to_stars():
    # the shared formatter esc()-wraps backend fields before they hit innerHTML
    assert 'const fiat = o =>' in INDEX
    assert '(o.rub ? ` · ${esc(o.rub)} ₽` : \'\') + (o.usd ? ` · $${esc(o.usd)}` : \'\')' in INDEX
    assert 'fiat(i)' in INDEX
    # V3.43.0: the shop pack squares print the rub price inline from the same
    # payload (the old hero/credit rows that used fiat(p)/fiat(credit) are gone)
    assert "esc(x.rub) + ' ₽'" in INDEX
    # the constructor wizard price note shows all three tiers
    assert "WIZ.rub ? ' · ' + esc(WIZ.rub) + ' ₽' : ''" in INDEX
    assert "WIZ.usd ? ' · $' + esc(WIZ.usd) : ''" in INDEX


def test_legal_tariffs_fiat_both_languages():
    assert 'fiat_suffix(PHOTO_COST_STARS)' in LEGAL
    assert 'fiat_suffix(CHAT_PHOTO_OFFER_STARS)' in LEGAL
    assert 'fiat_suffix(CUSTOM_PHOTO_COST_STARS)' in LEGAL
    assert 'fiat_suffix(GALLERY_DOWNLOAD_STARS)' in LEGAL
    assert 'fiat_suffix(VIDEO_COST_STARS)' in LEGAL
    assert 'fiat_suffix(QUEST_REPLAY_STARS)' in LEGAL
    assert 'fiat_suffix(CONSTRUCTOR_COST_STARS, rub=CONSTRUCTOR_COST_RUB, usd=CONSTRUCTOR_PRICE_USD' in LEGAL
    assert 'fiat_suffix(gift_min)' in LEGAL and 'fiat_suffix(gift_max)' in LEGAL
    # premium lines reuse the real card prices in both languages
    assert LEGAL.count('fiat_suffix(PREMIUM_MONTHLY_STARS, rub=FREEKASSA_PREMIUM_PRICE_RUB, usd=FREEKASSA_PREMIUM_PRICE_USD') == 2
    assert LEGAL.count('fiat_suffix(PREMIUM_WEEKLY_STARS, rub=FREEKASSA_PREMIUM_WEEKLY_PRICE_RUB, usd=PREMIUM_WEEKLY_PRICE_USD') == 2
    # the old bare 'Telegram Stars' wording is gone from the tariff list
    assert 'Telegram Stars' not in LEGAL


def test_runtime_tariffs_render_fiat():
    import services.legal_service as legal
    ru = legal.tariffs_text('ru')
    en = legal.tariffs_text('en')
    # every priced line shows the rub + dollar equivalent of the star count
    for text in (ru, en):
        for line in text.splitlines():
            if '⭐' not in line:
                continue
            assert '$' in line, f'no dollar price: {line}'
    assert '₽' in ru  # rubs show when FreeKassa is enabled in production
