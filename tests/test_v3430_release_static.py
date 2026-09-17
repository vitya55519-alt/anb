"""V3.43.0 static checks — the Come Closer catch-up release.

Owner requests bundled here:
- support buttons deep-link to the dedicated support bot @Anna67901support_bot;
- +100 🍑 for subscribing to the owner's channel (@Anna634212) with revoke;
- Mini App auth hardening (7-day initData window, rejection reasons, retry UI);
- 3-tier tariff card (299/899/1799 ₽) + the quarter product end-to-end;
- character page carousel + like button, chat photo lightbox;
- gallery variety (00_–05_ reference prefixes);
- the Come Closer pay menu: tap a shop square → Stars / card-SBP / crypto modal.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
PAYMENTS = (ROOT / 'services' / 'payments.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


def test_version_bumped():
    assert VERSION in ('3.43.7', '3.43.6', '3.43.5', '3.43.4', '3.43.3', '3.43.2', '3.43.1', '3.43.0', '3.42.2', '3.42.1', '3.42.0', '3.41.0')


# ── 1. support lives in the dedicated support bot ──────────────────────────

def test_support_buttons_deep_link_the_support_bot():
    assert 'SUPPORT_BOT_USERNAME = os.getenv("SUPPORT_BOT_USERNAME", "Anna67901support_bot")' in CONFIG
    # welcome row + reply-button handler both hand a t.me url button
    assert "text=kb_label('support', lang), url=f'https://t.me/{SUPPORT_BOT_USERNAME}'" in MAIN
    body = MAIN[MAIN.index('async def support_button(message: types.Message):'):]
    body = body[:body.index('async def _deliver_support_message(')]
    assert "url=f'https://t.me/{SUPPORT_BOT_USERNAME}'" in body
    # the dead in-bot ticket callback is gone
    assert "@dp.callback_query(F.data == 'support:open')" not in MAIN


# ── 2. channel-subscribe peach bonus ───────────────────────────────────────

def test_channel_bonus_config_and_helpers():
    assert 'CHANNEL_SUBSCRIBE_USERNAME = os.getenv("CHANNEL_SUBSCRIBE_USERNAME", "Anna634212")' in CONFIG
    assert 'CHANNEL_SUBSCRIBE_BONUS_CREDITS = int(os.getenv("CHANNEL_SUBSCRIBE_BONUS_CREDITS", "100"))' in CONFIG
    # grant is idempotent, revoke mirrors it (unsubscribe annuls the bonus)
    assert 'def has_credit_grant(telegram_id:int, reason:str)->bool:' in PAYMENTS
    assert 'def revoke_photo_credits(telegram_id:int, amount:int, reason:str)->int:' in PAYMENTS


def test_channel_bonus_endpoint():
    handler = MAIN[MAIN.index('async def _webapp_api_channel_bonus('):]
    handler = handler[:handler.index('async def _webapp_api_char_like(')]
    assert 'get_chat_member(' in handler
    assert 'grant_photo_credits(' in handler
    assert 'revoke_photo_credits(' in handler
    assert "add_route('*', '/webapp/api/channel_bonus', _webapp_api_channel_bonus)" in MAIN
    # frontend banner + gift modal
    assert 'id="chanBanner"' in INDEX or 'chanbanner' in INDEX
    assert 'id="chanmodal"' in INDEX
    assert 'chanCheck' in INDEX and 'chanGo' in INDEX


# ── 3. Mini App auth hardening ──────────────────────────────────────────────

def test_webapp_auth_window_and_reasons():
    assert 'WEBAPP_INIT_DATA_MAX_AGE = int(os.getenv("WEBAPP_INIT_DATA_MAX_AGE", "604800"))' in CONFIG
    assert 'max_age_seconds: int | None = None' in WEBAPP_SVC
    me = MAIN[MAIN.index('async def _webapp_api_me('):]
    me = me[:me.index('\nasync def ', 10)]
    assert "reason = 'missing'" in me or "'missing'" in me
    assert 'webapp auth rejected reason=%s' in MAIN
    # the frontend explains WHY and offers a retry instead of a dead end
    assert 'function authErrHtml()' in INDEX
    assert 'err_auth_retry' in INDEX and 'err_auth_out' in INDEX


# ── 4. quarter product + 3-tier tariff card ─────────────────────────────────

def test_quarter_product_end_to_end():
    assert 'PREMIUM_QUARTERLY_STARS = int(os.getenv("PREMIUM_QUARTERLY_STARS", "1200"))' in CONFIG
    assert 'FREEKASSA_PREMIUM_QUARTERLY_PRICE_RUB = max(1, int(os.getenv("FREEKASSA_PREMIUM_QUARTERLY_PRICE_RUB", "1799")))' in CONFIG
    assert '"premium_quarter":PREMIUM_QUARTERLY_STARS' in PAYMENTS
    assert 'days, credits = 90, PREMIUM_QUARTERLY_PHOTO_CREDITS' in PAYMENTS
    assert "@dp.callback_query(F.data == 'buy:premium_quarter')" in MAIN
    # the tariff card shows all three tiers with the competitor's rub prices
    assert 'FREEKASSA_PREMIUM_WEEKLY_PRICE_RUB, FREEKASSA_PREMIUM_PRICE_RUB, FREEKASSA_PREMIUM_QUARTERLY_PRICE_RUB' in MAIN
    # card/SBP price lookup knows the quarter plan too
    fk = MAIN[MAIN.index('def _fk_amount_for('):]
    fk = fk[:fk.index('@dp.callback_query(F.data.startswith(\'fkapi:\'))')]
    assert "if product == 'premium_quarter':" in fk
    assert 'FREEKASSA_PREMIUM_QUARTERLY_PRICE_RUB' in fk


# ── 5. menu button install retry ────────────────────────────────────────────

def test_menu_button_install_retries():
    assert 'for attempt in range(1, 4):' in MAIN
    assert 'set_chat_menu_button(' in MAIN
    assert 'await asyncio.sleep(3 * attempt)' in MAIN


# ── 6. character page carousel + like, chat lightbox ────────────────────────

def test_carousel_like_lightbox():
    assert 'class CharacterLike(Base):' in MODELS
    assert '__tablename__ = "character_likes"' in MODELS
    assert 'likes: Mapped[int]' in MODELS
    assert 'def toggle_character_like(' in WEBAPP_SVC
    assert "add_route('*', '/webapp/api/char_like', _webapp_api_char_like)" in MAIN
    # frontend: arrows + dots carousel, like badge, global lightbox delegate
    assert 'id="charPrev"' in INDEX and 'id="charNext"' in INDEX and 'id="charDots"' in INDEX
    assert 'id="charLike"' in INDEX
    assert "closest('img[data-lb]')" in INDEX
    assert 'id="lightbox"' in INDEX


# ── 7. gallery variety ──────────────────────────────────────────────────────

def test_gallery_globs_all_reference_prefixes():
    assert "'00_', '01_', '02_', '03_', '04_', '05_'" in WEBAPP_SVC


# ── 8. the Come Closer pay menu (tap a square → Stars/SBP/crypto) ───────────

def test_pay_method_modal_backend():
    handler = MAIN[MAIN.index('async def _webapp_api_pay_link('):]
    handler = handler[:handler.index('async def _webapp_api_select(')]
    assert 'validate_init_data' in handler
    # sbp → FreeKassa REST order pinned to the SBP payment-system id
    assert "method == 'sbp'" in handler
    assert 'freekassa_service.create_api_order(' in handler
    assert 'payment_system=freekassa_service.FK_SBP_QR_PAYMENT_ID' in handler
    assert 'freekassa_service.payment_url(' in handler
    # crypto → Wallet Pay invoice (TON/USDT)
    assert "method == 'crypto'" in handler
    assert 'from services.wallet_pay_service import create_invoice' in handler
    # order product keys the granting chain (record_payment) understands
    assert "'photo_credit': 'photo'" in handler
    assert "add_post('/webapp/api/pay_link', _webapp_api_pay_link)" in MAIN
    # the shop payload tells the frontend which rows it may offer
    assert "'freekassa': FREEKASSA_ENABLED," in WEBAPP_SVC
    assert "'wallet_pay': WALLET_PAY_ENABLED," in WEBAPP_SVC
    # ruble-paid photo credit + quarter confirmations in the notify chain
    notify = MAIN[MAIN.index('async def _fk_notify('):]
    notify = notify[:notify.index('async def _fk_success(')]
    assert "elif product == 'photo':" in notify
    assert 'Фото-кредит оплачен картой!' in notify
    assert 'Premium активирован на 90 дней' in notify


def test_pay_method_modal_frontend():
    # pack squares replace the old hero CTA buttons
    assert 'class="pack" data-pay="${esc(x.id)}"' in INDEX
    assert 'openPay(b.dataset.pay)' in INDEX
    # the modal rows: Stars always, SBP and crypto only when the backend sells them
    assert 'id="paymodal"' in INDEX and 'id="payRows"' in INDEX
    assert 'data-m="stars"' in INDEX and 'data-m="sbp"' in INDEX and 'data-m="crypto"' in INDEX
    assert 'if (x.rub && s.freekassa)' in INDEX
    assert 'if (s.wallet_pay)' in INDEX
    # Stars reuses the invoice flow; the others open the external payment link
    assert 'buy(id, btn)' in INDEX
    assert "/webapp/api/pay_link?init_data=" in INDEX
    assert 'tg.openTelegramLink(j.url)' in INDEX
    # localized row labels in both languages
    assert "pay_sbp: 'СБП / карта'" in INDEX and "pay_sbp: 'SBP / card'" in INDEX
    assert "pay_crypto: 'Крипта (TON/USDT)'" in INDEX and "pay_crypto: 'Crypto (TON/USDT)'" in INDEX
