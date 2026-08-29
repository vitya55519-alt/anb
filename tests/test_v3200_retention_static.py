"""Static pins for v3.20.0: retention & monetization pack.

Owner request: animation for 50 Stars + 2 free daily animations on premium,
plus retention mechanics (streaks already existed) — emotional reminders,
jealousy, unfinished-conversation cliffhangers, morning/evening rituals,
3h demo premium, pleasure-blocking instead of feature-blocking, premium-only
video circles, a one-time 24h discount, and a level-6 progression plateau.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PAYMENTS = (ROOT / 'services' / 'payments.py').read_text(encoding='utf-8')
RETENTION = (ROOT / 'services' / 'retention_service.py').read_text(encoding='utf-8')
SCHEDULER = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')


def test_video_pricing_and_free_slots():
    assert 'VIDEO_COST_STARS", "50"' in CONFIG
    assert 'VIDEO_PREMIUM_FREE_DAILY", "2"' in CONFIG


def test_retention_config_flags():
    assert 'FREE_MESSAGES_PER_DAY", "20"' in CONFIG
    assert 'DEMO_PREMIUM_HOURS", "3"' in CONFIG
    assert 'PREMIUM_DISCOUNT_PERCENT", "30"' in CONFIG
    assert 'PREMIUM_DISCOUNT_HOURS", "24"' in CONFIG
    assert 'RETENTION_REMINDER_HOURS", "24"' in CONFIG
    assert 'RITUALS_ENABLED' in CONFIG
    assert 'PREMIUM_DISCOUNT_STARS = max(1, int(PREMIUM_MONTHLY_STARS' in CONFIG


def test_retention_service_helpers_and_pools():
    for name in (
        'def has_used_demo(', 'def grant_demo_premium(', 'def demo_hours_left(',
        'def offer_discount(', 'def discount_info(', 'def pick_text(',
    ):
        assert name in RETENTION
    # Demo is idempotent and implemented as a real Subscription row.
    assert 'if has_used_demo(telegram_id):' in RETENTION
    assert 'Subscription(' in RETENTION
    for pool in ('SLEEP_BLOCK_TEXTS', 'MISS_TEXTS', 'JEALOUSY_TEXTS',
                 'CLIFFHANGER_TEXTS', 'MORNING_TEXTS', 'EVENING_TEXTS'):
        assert pool in RETENTION
    assert 'задремала' in RETENTION
    assert 'ревновать' in RETENTION


def test_discount_product_and_column():
    assert '"premium_month_discount":PREMIUM_DISCOUNT_STARS' in PAYMENTS
    assert 'product in {"premium_month","premium_month_discount"}' in PAYMENTS
    assert 'discount_offered_at' in MODELS


def test_sleep_block_replaces_dry_limit_notice():
    # Pleasure block: she "falls asleep", admins are exempt, demo + premium CTAs.
    assert MAIN.count('await _sleep_block_reply(message)') >= 2
    assert 'message.from_user.id not in ADMIN_TELEGRAM_IDS and not can_send_message' in MAIN
    assert "pick_text('sleep')" in MAIN
    assert "callback_data='retention:demo'" in MAIN
    assert "callback_data='retention:premium'" in MAIN
    assert 'на сегодня бесплатный лимит сообщений закончился' not in MAIN


def test_demo_and_discount_callbacks():
    demo_block = MAIN[MAIN.index("@dp.callback_query(F.data == 'retention:demo')"):
                      MAIN.index("@dp.callback_query(F.data == 'retention:premium')")]
    assert 'grant_demo_premium(' in demo_block
    assert 'is_premium(' in demo_block
    assert 'demo_premium_granted' in demo_block
    assert 'premium_pitch_text(cq.from_user.id)' in MAIN
    assert "'premium_month_discount', discount['price']" in MAIN


def test_discount_payment_flow():
    assert "elif payload=='premium_month_discount':" in MAIN
    assert "elif payload=='circle':" in MAIN
    assert "if payload == 'premium_month_discount':" in MAIN
    assert "record_payment(message.from_user.id, 'premium_month_discount'" in MAIN
    assert "if payload == 'circle':" in MAIN


def test_circles_premium_exclusive():
    circle_block = MAIN[MAIN.index("@dp.callback_query(F.data == 'video:circle')"):
                        MAIN.index('async def _run_circle_background(')]
    assert 'not is_premium(cq.from_user.id)' in circle_block
    assert 'circle_paywall_view' in circle_block
    assert 'consume_premium_video_free(' in circle_block
    assert 'CIRCLE_PROMPT' in MAIN
    assert 'send_video_note(' in MAIN
    # A rejected video note still delivers as a normal video.
    assert 'в кружок не поместилось' in MAIN
    assert "callback_data='video:circle'" in MAIN


def test_scheduler_retention_tiers_and_rituals():
    assert 'RETENTION_REMINDER_HOURS' in SCHEDULER
    for kind in ("'cliffhanger'", "'jealousy'", "'miss'"):
        assert kind in SCHEDULER
    assert 'async def _rituals(' in SCHEDULER
    assert 'retention_service.pick_text(kind)' in SCHEDULER
    assert "scheduler.add_job(_rituals,'interval',minutes=30" in SCHEDULER
    assert 'не прерывай серию' in SCHEDULER


def test_premium_pitch_mentions_new_perks_and_plateau():
    pitch = MAIN[MAIN.index('def premium_pitch_text('):MAIN.index('def _sleep_block_markup(')]
    assert '2 бесплатных оживления фото каждый день' in pitch
    assert 'видео-кружочки' in pitch
    assert 'безлимит сообщений' in pitch
    # V3.21.0 renamed the plateau line to the two premium levels.
    assert '«Родственные души» и «Одно целое»' in pitch
