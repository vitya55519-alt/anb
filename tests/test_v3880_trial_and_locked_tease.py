"""V3.88.0: the 99 ₽ / 3-day first-purchase trial, the early locked photo in
the chat, and Premium (not the relationship level) opening spicy scenes."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PAY = (ROOT / 'services' / 'payments.py').read_text(encoding='utf-8')
WEB = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
CFG = (ROOT / 'config.py').read_text(encoding='utf-8')
LT = (ROOT / 'services' / 'locked_tease.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_trial_config_and_grant():
    assert 'PREMIUM_TRIAL_DAYS = max(1, int(os.getenv("PREMIUM_TRIAL_DAYS", "3")))' in CFG
    assert 'PLATEGA_PREMIUM_TRIAL_PRICE_RUB = max(1, int(os.getenv("PLATEGA_PREMIUM_TRIAL_PRICE_RUB", "99")))' in CFG
    assert '"premium_trial":PREMIUM_TRIAL_STARS' in PAY
    assert 'days, credits = PREMIUM_TRIAL_DAYS, 0' in PAY
    assert 'def trial_eligible(telegram_id: int) -> bool:' in PAY
    assert "StarTransaction.product.like('premium%')" in PAY


def test_trial_wired_on_every_payment_path():
    assert "ok=amount==PREMIUM_TRIAL_STARS and trial_eligible(query.from_user.id)" in MAIN
    assert "if payload == 'premium_trial':" in MAIN
    assert "if product == 'premium_trial':\n        # V3.88.0: the 99 ₽ first-purchase trial.\n        return PLATEGA_PREMIUM_TRIAL_PRICE_RUB" in MAIN
    assert "'premium_trial': 'premium_trial'," in MAIN
    assert MAIN.count("if product_id == 'premium_trial' and not await asyncio.to_thread(trial_eligible, telegram_id):") == 2
    assert "@dp.callback_query(F.data == 'buy:premium_trial')" in MAIN
    assert "callback_data='buy:premium_trial'" in MAIN
    assert "'id': 'premium_trial'," in WEB and "'trial_eligible': _trial_eligible(telegram_id)," in WEB


def test_app_offers_trial_first():
    assert "const trialFirst = (ME && ME.trial_eligible && !ME.premium) ? ['premium_trial'] : [];" in INDEX
    assert "(trialOk ? ['premium_trial'] : []).concat(['premium_week', 'premium', 'premium_quarter'])" in INDEX
    assert INDEX.count('plan_trial:') >= 2


def test_locked_tease_fires_once_at_third_message():
    assert 'TEASE_AT = 3' in LT
    assert "payload['locked_tease'] = tease" in MAIN
    assert "app.router.add_get('/webapp/locked/{character_id}.jpg', _webapp_locked_card)" in MAIN
    assert "if (j.locked_tease && j.locked_tease.url) {" in INDEX
    assert "quickBuy('spicy', () => { if (CHAT) requestMedia('photo', 'lingerie'); })" in INDEX


def test_premium_not_level_opens_spicy_scenes():
    assert MAIN.count('not spicy_needs_premium(PhotoRequest(scene=scene))') >= 3
    assert "if not spicy_needs_premium(request) and not scene_allowed_for_stage(request.scene, stage):" in MAIN
