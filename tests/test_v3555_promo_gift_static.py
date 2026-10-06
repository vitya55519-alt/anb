"""V3.55.5 static checks: promo codes + daily streak gift (owner: «распиши билд»).

Replaces the V3.44.0 bonus wheel (float peaches 0.01–0.27 leaked into the
INTEGER photo_credits column and the wheel double-dipped next to the new
streak rail). Money rules pinned here structurally (the functional file
test_v3555_promo_gift_logic.py exercises them on temp sqlite):
* streak 1/1/1/1/1/1/3 🍑, day boundary 03:00 MSK == 00:00 UTC → key is the
  naive UTC date (NOT (now+3h).date() — that flips at midnight MSK);
* balance >= DAILY_GIFT_BALANCE_CAP refuses the claim WITHOUT consuming the
  day (cap check precedes the guarded UPDATE, gift_last_day is not written);
* once-per-day via one UPDATE ... WHERE gift_last_day IS NULL OR < key;
* grants ride payments.grant_photo_credits — idempotent per (reason, user):
  reason daily_gift_<iso> for the gift, promo_<CODE> for codes;
* promo: [A-Z0-9]{4,24} after upper/strip, atomic activation-cap reserve,
  slot handed back via _decrement_activation when the grant did not land;
* /promo command + gift:claim in /profile + admin «🎟 Промокоды» wizard with
  PROMO_MAX_CREDITS nominal cap (codes can never mint Premium days);
* Mini App: POST /webapp/api/gift/claim + /webapp/api/promo, api_me carries
  the read-only gift state, shop renders the 7-dot series + promo input.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
DB = (ROOT / 'services' / 'db.py').read_text(encoding='utf-8')
GIFT = (ROOT / 'services' / 'gift_service.py').read_text(encoding='utf-8')
WS = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


# ---------------------------------------------------------------- config
def test_gift_config_constants():
    assert 'DAILY_GIFT_ENABLED = os.getenv("DAILY_GIFT_ENABLED", "1") == "1"' in CONFIG
    assert 'DAILY_GIFT_DAY_AMOUNT = int(os.getenv("DAILY_GIFT_DAY_AMOUNT", "1"))' in CONFIG
    assert 'DAILY_GIFT_JACKPOT_DAY = int(os.getenv("DAILY_GIFT_JACKPOT_DAY", "7"))' in CONFIG
    assert 'DAILY_GIFT_JACKPOT_AMOUNT = int(os.getenv("DAILY_GIFT_JACKPOT_AMOUNT", "3"))' in CONFIG
    assert 'DAILY_GIFT_BALANCE_CAP = int(os.getenv("DAILY_GIFT_BALANCE_CAP", "15"))' in CONFIG
    assert 'PROMO_MAX_CREDITS = int(os.getenv("PROMO_MAX_CREDITS", "20"))' in CONFIG


def test_unified_video_peach_price():
    # one knob on the peach rail: config VIDEO_PEACH_COST (20 🍑) feeds the
    # Mini App studio video — no shadow per-surface prices anymore
    assert 'VIDEO_PEACH_COST = max(1, int(os.getenv("VIDEO_PEACH_COST", "20")))' in CONFIG
    assert 'WEBAPP_VIDEO_COST_CREDITS = VIDEO_PEACH_COST' in WS
    # the legal price list discloses the studio video price too
    LEGAL = (ROOT / 'services' / 'legal_service.py').read_text(encoding='utf-8')
    assert 'studio_video_peaches = webapp_service.WEBAPP_VIDEO_COST_CREDITS' in LEGAL
    assert 'в студии (Mini App) — {studio_video_peaches} 🍑' in LEGAL
    assert 'video generation (Mini App) — {studio_video_peaches} 🍑' in LEGAL


def test_welcome_promo_shelf():
    # 15 🍑 streak cap + 5 🍑 welcome code = the 20 🍑 studio video
    assert 'PROMO_WELCOME_ENABLED = os.getenv("PROMO_WELCOME_ENABLED", "1") == "1"' in CONFIG
    assert 'os.getenv("PROMO_WELCOME_CODE", "ANNA5")' in CONFIG
    assert 'min(PROMO_MAX_CREDITS, int(os.getenv("PROMO_WELCOME_CREDITS", "5")))' in CONFIG
    assert 'PROMO_WELCOME_CAP = max(0, int(os.getenv("PROMO_WELCOME_CAP", "1000")))' in CONFIG
    seed = GIFT[GIFT.index('def ensure_welcome_promo('):]
    assert 'if not PROMO_WELCOME_ENABLED:' in seed
    # format-gated and idempotent: existing row → no second insert
    assert 'PROMO_CODE_RE.match(code)' in seed
    assert 'if s.scalar(select(PromoCode).where(PromoCode.code == code)):' in seed
    assert "source_tag='welcome'" in seed
    # booted from main() next to the other ensure_default_* seeds
    assert 'gift_service.ensure_welcome_promo()' in MAIN


# ---------------------------------------------------------------- models
def test_user_gift_columns_and_promo_model():
    assert 'gift_last_day: Mapped[date | None] = mapped_column(Date, nullable=True)' in MODELS
    assert 'gift_streak: Mapped[int] = mapped_column(Integer, default=0)' in MODELS
    assert 'class PromoCode(Base):' in MODELS
    assert '__tablename__ = "promo_codes"' in MODELS
    assert 'code: Mapped[str] = mapped_column(String(24), unique=True, index=True)' in MODELS
    # cap semantics: 0 = unlimited, TTL nullable, attribution tag
    assert 'max_activations' in MODELS and 'expires_at' in MODELS and 'source_tag' in MODELS
    # db.py imports it so create_all/_auto_migrate_all_tables pick it up
    assert 'PromoCode' in DB


# ---------------------------------------------------------------- service
def test_day_key_is_utc_date_not_plus_three():
    # 03:00 MSK == 00:00 UTC (fixed offset, no DST) → the key is the naive UTC
    # date. The (now + 3h) variant flipped at 00:00 MSK and is forbidden.
    assert 'return now.date()' in GIFT
    assert 'timedelta(hours=3)' not in GIFT


def test_consent_gate_precedes_every_write():
    claim = GIFT[GIFT.index('def claim_daily_gift('):GIFT.index('def balance_amount(')]
    assert 'has_accepted(telegram_id)' in claim
    assert claim.index('has_accepted(telegram_id)') < claim.index('update(User)')
    promo = GIFT[GIFT.index('def redeem_promo('):]
    assert promo.index('has_accepted(telegram_id)') < promo.index('update(PromoCode)')


def test_cap_blocks_grant_without_consuming_the_day():
    claim = GIFT[GIFT.index('def claim_daily_gift('):GIFT.index('def balance_amount(')]
    # the >= cap early-return must happen BEFORE the streak UPDATE
    assert '>= DAILY_GIFT_BALANCE_CAP' in claim
    assert claim.index('>= DAILY_GIFT_BALANCE_CAP') < claim.index('update(User)')
    assert "'capped': True" in claim


def test_once_per_day_guarded_update():
    assert 'or_(User.gift_last_day.is_(None), User.gift_last_day < key)' in GIFT
    assert 'if not res.rowcount:' in GIFT and "'duplicate'" in GIFT
    # yesterday's key extends the series, anything else restarts at 1
    assert 'user.gift_last_day == key - timedelta(days=1)' in GIFT


def test_grant_rails_and_reasons():
    assert "reason=f'daily_gift_{key.isoformat()}'" in GIFT
    assert "reason=f'promo_{code}'" in GIFT
    assert 'from services.payments import grant_photo_credits' in GIFT
    assert "track_event(ensure_user(telegram_id), 'daily_gift'" in GIFT
    assert "track_event(ensure_user(telegram_id), 'promo_redeem'" in GIFT


def test_promo_validation_and_atomic_cap():
    assert r"re.compile(r'^[A-Z0-9]{4,24}$')" in GIFT
    assert "_normalize_code" in GIFT and ".strip().upper()" in GIFT
    # reserve only while the global cap has room (0 = unlimited)
    assert 'PromoCode.max_activations == 0' in GIFT
    assert 'PromoCode.activated_count < PromoCode.max_activations' in GIFT
    assert 'values(activated_count=PromoCode.activated_count + 1)' in GIFT
    # a failed grant gives the reserved slot back (duplicate/unknown user)
    assert '_decrement_activation(pc_id)' in GIFT
    assert 'PromoCode.activated_count > 0' in GIFT
    # expiry checked against naive UTC now
    assert 'pc.expires_at < _utcnow()' in GIFT


def test_streak_slot_normalization():
    # raw streak grows forever; every displayed value must fold to 1..7
    assert 'def _slot(streak: int) -> int:' in GIFT
    assert 'slot = streak % DAILY_GIFT_JACKPOT_DAY' in GIFT
    assert '_slot(streak)' in GIFT and '_slot(user.gift_streak)' in GIFT


# ---------------------------------------------------------------- bot
def test_promo_command_and_gift_button():
    assert "@dp.message(Command('promo'))" in MAIN
    assert "types.BotCommand(command='promo'" in MAIN
    assert "@dp.callback_query(F.data == 'gift:claim')" in MAIN
    assert 'gift_service.claim_daily_gift(cq.from_user.id)' in MAIN
    assert 'gift_service.redeem_promo(message.from_user.id, code)' in MAIN


def test_admin_promo_section():
    assert "callback_data='admin:promos'" in MAIN
    assert "@dp.callback_query(F.data == 'admin:promoadd:start')" in MAIN
    assert "@dp.callback_query(F.data.startswith('admin:promotgl:'))" in MAIN
    # nominal cap in the wizard: Premium days can never be minted as codes
    assert '1 <= int(value) <= PROMO_MAX_CREDITS' in MAIN
    # uniqueness pre-check + wizard state store + /cancel pop
    assert '_admin_promo_sessions: dict[int, dict] = {}' in MAIN
    assert 'select(PromoCode).where(PromoCode.code == code)' in MAIN
    assert '_admin_promo_sessions.pop(message.from_user.id, None)' in MAIN


def test_webapp_endpoints_and_routes():
    assert 'async def _webapp_api_gift_claim(' in MAIN
    assert 'async def _webapp_api_promo(' in MAIN
    assert "app.router.add_post('/webapp/api/gift/claim', _webapp_api_gift_claim)" in MAIN
    assert "app.router.add_post('/webapp/api/promo', _webapp_api_promo)" in MAIN
    assert "GIFT_PROMO_ERROR_HTTP = {'auth': 401, 'consent': 403, 'unknown': 404," in MAIN
    assert "'expired': 410" in MAIN and "'exhausted': 429" in MAIN and "'duplicate': 409" in MAIN
    # both endpoints authenticate via init_data like the rest of the API
    ep = MAIN[MAIN.index('async def _webapp_api_promo('):MAIN.index('async def _webapp_api_promo(') + 900]
    assert "webapp_service.validate_init_data(request.query.get('init_data', ''))" in ep


def test_bonus_wheel_is_fully_retired():
    # routes/service functions gone; only NotificationPref flag + legacy table
    # + retirement comments remain by design
    assert '/webapp/api/daily_bonus' not in MAIN
    assert 'def spin_daily_bonus' not in WS
    assert 'def get_daily_bonus_status' not in WS
    assert 'spin_daily_bonus' not in SCHED and 'get_daily_bonus_status' not in SCHED
    # the DailyBonus model is no longer imported by the webapp service (only a
    # retirement comment may mention it)
    assert all('DailyBonus' not in line for line in WS.splitlines()
               if line.strip().startswith(('from ', 'import ')))


# ---------------------------------------------------------------- webapp api payload
def test_api_me_carries_gift_state():
    assert 'def _gift_me_fields(telegram_id: int) -> dict:' in WS
    assert '**_gift_me_fields(telegram_id),' in WS
    assert "'gift_available'" in WS and "'gift_capped'" in WS and "'gift_amount'" in WS
    # failure hides the block instead of breaking api_me
    assert "return {'gift_available': False, 'gift_enabled': False, 'gift_streak': 0," in WS


# ---------------------------------------------------------------- SPA
def test_spa_gift_block_and_promo():
    assert '<div id="giftBlock"></div>' in SPA
    assert 'function renderGiftBlock()' in SPA
    assert 'async function claimDailyGift()' in SPA
    assert 'async function redeemPromoCode()' in SPA
    assert '/webapp/api/gift/claim?init_data=' in SPA
    assert '/webapp/api/promo?init_data=' in SPA
    assert "'duplicate'" in SPA and 'L.gift_taken' in SPA
    # wheel fetches are gone from the client too
    assert 'daily_bonus' not in SPA


def test_spa_i18n_all_seven_locales():
    for key in ('gift_title:', 'gift_taken:', 'gift_capped:', 'promo_btn:', 'promo_err_unknown:'):
        assert SPA.count(key) >= 7, f'{key} missing from some locale'
    # EN + RU both promise the 03:00 refresh and the 15 🍑 cap
    assert 'Already claimed — refreshes at 03:00' in SPA
    assert 'Уже взято — обновится в 03:00' in SPA
    assert 'Копилка полная (15 🍑)' in SPA


def test_spa_openwizard_click_fix():
    # V3.44.13 regression: the click event was passed as premiumMode
    assert "cc.addEventListener('click', () => openWizard());" in SPA
    assert "addEventListener('click', openWizard)" not in SPA


# ---------------------------------------------------------------- scheduler
def test_scheduler_points_at_the_gift():
    assert 'gift_service.gift_status' in SCHED
    assert 'забирай дневной подарок' in SCHED
