"""V3.56.0 static checks: the invisible SpicyAPI money cannon + premium reset.

The owner watched the SpicyAPI balance drain $1.75 → $0.06 in one hour
(15:01–16:05 MSK) while /stats reported «картинки $0.080». Root causes:

1. the 12:00-UTC scheduler job ``_daily_gift`` rendered a FRESH PAID SpicyAPI
   image for up to 50 users every day (12:00 UTC = 15:00 MSK — the exact burn
   window), and never ledgered or audited it;
2. ``_spicyapi_render`` never called ``spend_service.record_image_spend``, so
   every intimate render (Наедине/косплей/взрослая студия) was invisible in the
   money telemetry — the «$0.080» lie;
3. the adult studio path billed TWO SpicyAPI jobs on one failed request
   (t2i → i2i);
4. the admin generation feed only recorded app-initiated renders, so the gift
   cannon and the Telegram «наедине»/cosplay buttons were not visible.

Plus the owner's product call: the Premium subscriptions in this build are all
test/admin grants, so a one-shot mass-revoke tool ships with the release.

Every check below is a source-text pin (this suite runs without a DB/network).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
PPS = (ROOT / 'services' / 'private_photo_service.py').read_text(encoding='utf-8')
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
WEB = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PAY = (ROOT / 'services' / 'payments.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
DB = (ROOT / 'services' / 'db.py').read_text(encoding='utf-8')
HTML = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')

RENDER = PPS[PPS.index('async def _spicyapi_render('):PPS.index('async def generate_private_photo_real(')]
GIFT = PPS[PPS.index('async def send_daily_gift('):PPS.index('# ─── Голос + фото комбо')]
DAILY = SCHED[SCHED.index('async def _daily_gift(bot):'):SCHED.index('def _user_local_hour_simple(')]
HOT = MAIN[MAIN.index('async def _webapp_media_hot('):MAIN.index('async def _webapp_media_circle(')]


# ── item 3: honest SpicyAPI accounting ───────────────────────────────────────
def test_spicy_cost_knob_exists():
    assert 'SPICYAPI_ESTIMATED_COST_USD = float(os.getenv("SPICYAPI_ESTIMATED_COST_USD", "0.0345"))' in CONFIG


def test_render_ledgers_every_billed_job():
    # the money event is createTask; the ledger records once with the true
    # success flag whether or not the image ever came back
    assert 'from services import spend_service' in PPS
    assert 'SPICYAPI_ESTIMATED_COST_USD,' in PPS
    assert "spend_service.record_image_spend(\n        'spicyapi', scene, SPICYAPI_ESTIMATED_COST_USD," in RENDER
    assert 'billed=True, success=bool(result),' in RENDER
    # a missing key / no-taskId must NOT be billed (both return before the ledger)
    assert RENDER.index('if not SPICYAPI_KEY:') < RENDER.index('record_image_spend')
    assert RENDER.index('if not task_id:') < RENDER.index('record_image_spend')
    # scene is threaded from both wrappers
    assert "scene=str(request.category or 'private')" in PPS
    assert "scene='nude_t2i'" in PPS


# ── item 1: the gift cannon no longer spends money ────────────────────────────
def test_daily_gift_is_pool_only():
    assert 'retention_features_service.random_proactive_photo()' in GIFT
    # the paid render is gone from the gift path entirely
    assert 'generate_private_photo_real' not in GIFT
    assert 'return False  # no free pool image' in GIFT
    # gift date is stamped only after a successful send
    assert GIFT.index('await bot.send_photo(') < GIFT.index('user.last_daily_gift_date = today')
    # and the gift is audited into the feed for free
    assert "webapp_service.record_generation(" in GIFT
    assert "engine='pool', cost_usd=0.0," in GIFT


def test_daily_gift_targets_active_users_only():
    assert 'User.proactive_enabled == True' in DAILY
    assert 'User.last_active_at >= fresh_cutoff' in DAILY
    assert 'min(15, len(user_ids))' in DAILY
    assert 'except TelegramForbiddenError:' in DAILY
    assert '_mark_blocked(int(tid))' in DAILY


# ── item 4: no double-bill on the adult studio path ──────────────────────────
def test_adult_path_single_spicy_attempt():
    assert "engine_used = 'spicyapi_t2i'" in HOT
    assert "engine_used = 'spicyapi_i2i'" not in HOT
    assert "engine_used = 'fal_ai_t2i'" in HOT


def test_hot_engine_hint_reaches_the_feed():
    assert '_HOT_MEDIA_HINT: dict = {}' in MAIN
    # cache and pool hits are $0, fresh renders carry the real engine+cost
    assert "_HOT_MEDIA_HINT[telegram_id] = ('cache', 0.0)" in HOT
    assert "_HOT_MEDIA_HINT[telegram_id] = ('pool', 0.0)" in HOT
    assert "_HOT_MEDIA_HINT[telegram_id] = ('spicyapi', _spicy_cost)" in HOT
    assert "hint = _HOT_MEDIA_HINT.pop(telegram_id, None) if kind in ('hot', 'cosplay') else None" in MAIN


# ── item 2: the feed records everything, with the money trail ─────────────────
def test_record_generation_carries_engine_cost():
    assert 'def record_generation(telegram_id, kind, character_id, prompt, filename, *,\n                      engine=None, cost_usd=0.0) -> None:' in WEB
    assert 'engine=(str(engine)[:48] if engine else None),' in WEB
    assert "'engine': r.engine or ''," in WEB
    assert "'cost_usd': float(r.cost_usd or 0.0)," in WEB


def test_telegram_private_and_cosplay_buttons_are_audited():
    # both Telegram handlers now write a feed row (they used to be invisible)
    assert MAIN.count("webapp_service.record_generation(\n                cq.from_user.id, 'hot'") == 1
    assert MAIN.count("webapp_service.record_generation(\n                cq.from_user.id, 'cosplay'") == 1
    assert "engine=('spicyapi' if rendered else 'cache')," in MAIN


def test_admin_endpoint_reports_daily_burn():
    assert "'spent_today_usd': round(spent_today, 4)" in MAIN
    assert 'spent_today = spend_service.image_cost_today()' in MAIN


def test_feed_html_shows_money():
    assert 'renderGenFeed(j.generations || [], reset, j.spent_today_usd)' in HTML
    assert 'сожжено на картинки сегодня' in HTML
    assert 'const cost = Number(g.cost_usd || 0);' in HTML


# ── model + migration for the two new columns ─────────────────────────────────
def test_user_generation_new_columns():
    assert "engine: Mapped[str | None] = mapped_column(String(48), nullable=True)" in MODELS
    assert "cost_usd: Mapped[float] = mapped_column(default=0.0)" in MODELS
    assert "_add_missing_columns('user_generations', {" in DB
    assert "'engine': 'VARCHAR(48)'," in DB
    assert "'cost_usd': 'FLOAT DEFAULT 0'," in DB


# ── item 5: mass premium revoke ships as an admin tool ────────────────────────
def test_revoke_all_premium_tool():
    assert 'def revoke_all_premium()->int:' in PAY
    assert "sub.status='cancelled'; sub.expires_at=now" in PAY[PAY.index('def revoke_all_premium('):]
    assert "@dp.message(Command('revoke_all_premium'))" in MAIN
    assert 'from services.payments import revoke_all_premium' in MAIN
    # admin-gated
    block = MAIN[MAIN.index("@dp.message(Command('revoke_all_premium'))"):]
    assert 'if message.from_user.id not in ADMIN_TELEGRAM_IDS:' in block
