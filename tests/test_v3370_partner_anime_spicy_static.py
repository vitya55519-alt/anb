"""V3.37.0 static checks: the money affiliate («партнёрка») program cloned
from the competitor's playbook — 40% commission off EVERY purchase a referred
user ever makes (not a one-time bonus), a 500 ₽ minimum manual withdrawal
with owner confirm/reject buttons, the 💰 Партнёрка button + bot screen +
5th Mini App tab; the public character constructor gains an ANIME art-style
first step (realistic stays the default for legacy personas); and a
Premium-gated «пошлый режим» toggle in Settings lifts the flirt ceiling in
the shared chat pipeline (bot + Mini App).
"""
import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
DB = (ROOT / 'services' / 'db.py').read_text(encoding='utf-8')
CCS = (ROOT / 'services' / 'custom_character_service.py').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
PAYMENTS = (ROOT / 'services' / 'payments.py').read_text(encoding='utf-8')
REFERRAL = (ROOT / 'services' / 'referral_service.py').read_text(encoding='utf-8')
PARTNER = (ROOT / 'services' / 'partner_service.py').read_text(encoding='utf-8')
UI_LANG = (ROOT / 'services' / 'ui_lang.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_version_bumped():
    assert VERSION in ('3.42.0', '3.41.0', '3.40.0', '3.37.0', '3.38.0', '3.39.0')


# ── config: the program dials live behind env vars ─────────────────────────

def test_partner_config_knobs():
    assert 'PARTNER_ENABLED = os.getenv("PARTNER_ENABLED", "1") == "1"' in CONFIG
    assert 'REFERRAL_COMMISSION_PCT = float(os.getenv("REFERRAL_COMMISSION_PCT", "30"))' in CONFIG
    assert 'PARTNER_MIN_PAYOUT_RUB = int(os.getenv("PARTNER_MIN_PAYOUT_RUB", "500"))' in CONFIG
    assert 'PARTNER_PAYOUT_METHODS = os.getenv(' in CONFIG
    cfg = importlib.import_module('config')
    assert cfg.REFERRAL_COMMISSION_PCT == 30.0
    assert cfg.PARTNER_MIN_PAYOUT_RUB == 500


# ── models: the permanent referral link + the money ledger ─────────────────

def test_partner_models_and_migration():
    assert 'class Referral(Base):' in MODELS
    assert 'UniqueConstraint("invitee_user_id", name="uq_referral_invitee")' in MODELS
    assert 'class PartnerTransaction(Base):' in MODELS
    assert 'source_charge_id' in MODELS
    assert 'unique=True' in MODELS
    # the spicy-mode user flag rides the auto-migration
    assert 'spicy_mode: Mapped[bool] = mapped_column(Boolean, default=False)' in MODELS
    assert 'from models.app_models import' in DB
    assert 'PartnerTransaction' in DB and 'Referral' in DB


# ── partner_service: idempotent commission ledger ──────────────────────────

def test_partner_service_surface():
    for fn in ('def register_referral_link(', 'def referrer_of_user(',
               'def referred_count(', 'def payment_rub_value(',
               'def accrue_commission(', 'def partner_stats(',
               'def request_payout(', 'def get_payout(', 'def settle_payout('):
        assert fn in PARTNER, fn
    # 40% of the ruble value; freekassa webhooks parse amount= out of payload
    assert 'REFERRAL_COMMISSION_PCT / 100.0' in PARTNER
    assert 'def _freekassa_amount_rub(' in PARTNER
    # idempotency: unique charge id + IntegrityError fallback
    assert 'PartnerTransaction.source_charge_id == str(charge_id)' in PARTNER
    assert 'except IntegrityError:' in PARTNER
    # legacy referrals (pre-v3.37 analytics markers) still earn commission
    assert 'referrer_telegram_id' in PARTNER
    # guarded single transition + balance math only counts pending+paid
    assert 'row.status != "pending"' in PARTNER
    assert 'status.in_(("pending", "paid"))' in PARTNER
    # below-min / one-pending-payout refusals
    assert '"below_min"' in PARTNER and '"pending_exists"' in PARTNER


def test_commission_hooked_into_payments_choke_point():
    # record_payment is the single path for Stars + FreeKassa; the accrual
    # runs AFTER the commit and must never roll back a purchase.
    assert 'from services import partner_service' in PAYMENTS
    assert 'partner_service.accrue_commission(' in PAYMENTS
    assert 'payer_user_id' in PAYMENTS
    assert 'logger.exception' in PAYMENTS


def test_referral_link_registered_on_conversion():
    assert 'register_referral_link' in REFERRAL


# ── bot UI: screen, FAQ, withdrawal, owner buttons ─────────────────────────

def test_partner_bot_screen_and_callbacks():
    assert "Command('referral', 'invite', 'partner')" in MAIN
    assert 'partner_service.partner_stats(' in MAIN
    assert "'partner:withdraw'" in MAIN
    for i in range(5):
        assert f"'partner:faq:{i}'" in MAIN
    assert '_PARTNER_FAQ_RU' in MAIN and '_PARTNER_FAQ_EN' in MAIN
    # owner-side confirm/reject with the admin guard
    assert "F.data.startswith('payout:done:')" in MAIN
    assert "F.data.startswith('payout:cancel:')" in MAIN
    assert 'cq.from_user.id not in ADMIN_TELEGRAM_IDS' in MAIN
    assert 'settle_payout(payout_id, ' in MAIN
    assert "command='partner'" in MAIN


def test_partner_keyboard_button():
    assert "'partner': ('💰 Партнёрская программа', '💰 Partner program')" in UI_LANG
    # V3.42.0: the partner program is a BIG full-width row; support shares the
    # bottom row with the legal documents.
    assert "['partner']" in UI_LANG
    assert "['support', 'legal']" in UI_LANG


# ── Mini App: 5th tab + endpoints ──────────────────────────────────────────

def test_partner_webapp_endpoints():
    assert "app.router.add_get('/webapp/api/partner'" in MAIN
    assert "app.router.add_post('/webapp/api/partner/withdraw'" in MAIN
    assert 'def api_partner(' in WEBAPP_SVC
    assert 'webapp_service.api_partner(uid, telegram_id)' in MAIN
    assert "result.get('reason') == 'pending_exists'" in MAIN


def test_partner_miniapp_tab():
    # V3.38.0: the partner tab became a full-screen overlay opened from the
    # profile «Партнёрка» row; the render/load/withdraw functions are intact.
    assert 'id="partnerview"' in INDEX
    assert 'id="menuPartner"' in INDEX
    assert 'async function loadPartner()' in INDEX
    assert 'function renderPartner()' in INDEX
    assert 'async function withdrawPartner()' in INDEX
    assert '/webapp/api/partner' in INDEX
    assert '/webapp/api/partner/withdraw' in INDEX
    assert 'partner_sub: pct =>' in INDEX
    assert 'navigator.clipboard.writeText' in INDEX


# ── anime constructor step ─────────────────────────────────────────────────

def test_anime_style_first_step():
    assert "('style_real', 'Реалистичная', 'photorealistic')" in CCS
    assert "('style_anime', 'Аниме', 'anime style, 2D cel-shaded illustration" in CCS
    assert "'style': 'Her style?'" in CCS
    assert "'style_anime': 'Anime'" in CCS
    # the avatar prompt branches on the style param
    assert "anime = str(params.get('style', '')) == 'style_anime'" in CCS
    assert 'Beautiful anime illustration of an adult woman' in CCS
    assert 'faithfully translated into anime style' in CCS
    ccs = importlib.import_module('services.custom_character_service')
    keys = [step['key'] for step in ccs.CONSTRUCTOR_STEPS]
    assert keys[0] == 'style' and len(keys) == 12
    # legacy personas without 'style' stay photorealistic
    assert ccs.build_avatar_prompt({'age': 'age_mid', 'name': 'Оля'}).startswith('Photorealistic portrait')
    assert ccs.build_avatar_prompt({'style': 'style_anime', 'name': 'Юки'}).startswith('Beautiful anime illustration')


# ── premium-gated spicy toggle ─────────────────────────────────────────────

def test_spicy_toggle_and_chat_gate():
    assert "F.data == 'toggle:spicy'" in MAIN
    assert 'update_user_settings(cq.from_user.id, spicy_mode=new)' in MAIN
    # enabling requires Premium; disabling is always allowed
    assert 'not current and not is_premium(' in MAIN
    # the chat injection rides the shared pipeline and re-checks Premium
    assert 'spicy_line' in CHAT
    assert "getattr(user_row, 'spicy_mode', False)" in CHAT
    assert 'premium and user_row' in CHAT
    assert 'ПОШЛЫЙ РЕЖИМ ВКЛЮЧЁН' in CHAT
