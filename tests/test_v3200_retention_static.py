"""Static pins for v3.20.0: retention & monetization pack.

Owner request: animation for 50 Stars with no free Premium animations,
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


def test_video_pricing_and_no_free_slots():
    assert 'VIDEO_COST_STARS", "50"' in CONFIG
    assert 'VIDEO_PREMIUM_FREE_DAILY", "0"' in CONFIG


def test_retention_config_flags():
    # V3.166.2: the ceiling is a hard account number again (30 a day for both
    # modes on both platforms), and the free demo premium left with it.
    assert 'FREE_MESSAGES_PER_DAY = CHAT_MSGS_PER_DAY' in CONFIG
    assert 'CHAT_MSGS_PER_DAY_V166' in CONFIG
    # сам constant исчез (в config осталась только строчка, которая это
    # объясняет), поэтому проверяем форму объявления, а не слово
    assert 'DEMO_PREMIUM_HOURS =' not in CONFIG
    assert 'PREMIUM_DISCOUNT_PERCENT", "30"' in CONFIG
    assert 'PREMIUM_DISCOUNT_HOURS", "24"' in CONFIG
    assert 'RETENTION_REMINDER_HOURS", "24"' in CONFIG
    assert 'RITUALS_ENABLED' in CONFIG
    assert 'PREMIUM_DISCOUNT_STARS = max(1, int(PREMIUM_MONTHLY_STARS' in CONFIG


def test_retention_service_helpers_and_pools():
    # V3.166.2: the demo trio is deleted, the discount keeps only its reader —
    # nothing opens a window, an already open one still resolves.
    for name in ('def discount_info(', 'def pick_text('):
        assert name in RETENTION
    for gone in ('def has_used_demo(', 'def grant_demo_premium(', 'def demo_hours_left(',
                 'def offer_discount(', 'def _demo_marker('):
        assert gone not in RETENTION
    assert 'user.discount_offered_at' in RETENTION
    for pool in ('SLEEP_BLOCK_TEXTS', 'MISS_TEXTS', 'JEALOUSY_TEXTS',
                 'CLIFFHANGER_TEXTS', 'MORNING_TEXTS', 'EVENING_TEXTS'):
        assert pool in RETENTION
    assert 'задремала' in RETENTION
    assert 'ревновать' in RETENTION


def test_discount_product_and_column():
    assert '"premium_month_discount":PREMIUM_DISCOUNT_STARS' in PAYMENTS
    # V3.34.1: the premium grant set also carries the weekly plan;
    # V3.43.0: ...and the quarterly one.
    assert 'product in {"premium_month","premium_month_discount","premium_week","premium_quarter","premium_trial"}' in PAYMENTS
    assert 'discount_offered_at' in MODELS


def test_limit_wall_replaces_the_dry_notice():
    # App dialogue uses the shared limit gate, with admins exempt. Bot
    # redirects must not need a legacy in-character wall or consume a turn.
    gate = MAIN[MAIN.index('def _webapp_chat_gate('):MAIN.index('def _tts_text(')]
    assert 'telegram_id not in ADMIN_TELEGRAM_IDS and not can_send_message(telegram_id)' in gate
    assert "'error': 'limit'" in gate and 'status=429' in gate
    assert "'chat_limit_wall'" in gate
    index = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
    assert 'if (r.status === 429)' in index
    assert "showLimitWall(() => { const i = document.getElementById('chatText')" in index
    assert "quickBuy('limit', retry)" in index
    assert '_sleep_block_reply' not in MAIN and '_sleep_block_markup' not in MAIN
    assert "pick_text('sleep')" not in MAIN
    assert "callback_data='retention:demo'" not in MAIN
    # сама кнопка с wall убрана (остаётся только обработчик — по нему ещё
    # открываются пузы, доставленные до релиза)
    assert "callback_data='retention:premium'" not in MAIN
    assert "F.data == 'retention:premium'" in MAIN
    assert 'на сегодня бесплатный лимит сообщений закончился' not in MAIN
    # V3.166.2: she asks him to stay in her own words and the one button opens
    # the app straight on the purchase screen — no system error, no second offer.
    wall = MAIN[MAIN.index('def _limit_wall_markup('):MAIN.index('# V3.27.0: ruble-shop balances')]
    assert 'лимит на сегодня исчерпан' in wall and 'не хочу останавливаться' in wall
    assert '/webapp?pay=1' in wall
    assert 'grant_demo_premium' not in wall and 'premium_vip' not in wall


def test_the_free_demo_callback_is_gone():
    assert "F.data == 'retention:demo'" not in MAIN
    assert 'grant_demo_premium(' not in MAIN
    assert 'demo_premium_granted' not in MAIN
    # the discount product still pays out for an order made before V3.166.2
    assert 'premium_pitch_text(cq.from_user.id)' in MAIN
    assert "'premium_month_discount', discount['price']" in MAIN


def test_discount_payment_flow():
    assert "elif payload=='premium_month_discount':" in MAIN
    assert "elif payload=='circle':" in MAIN
    assert "if payload == 'premium_month_discount':" in MAIN
    assert "record_payment(message.from_user.id, 'premium_month_discount'" in MAIN
    assert "if payload == 'circle':" in MAIN


def test_circles_paid_in_peaches():
    # V3.71.0: circles left Premium — everyone pays CIRCLE_PEACH_COST peaches.
    circle_block = MAIN[MAIN.index("@dp.callback_query(F.data == 'video:circle')"):
                        MAIN.index('async def _run_circle_background(')]
    assert 'spend_peaches(cq.from_user.id, CIRCLE_PEACH_COST, paid_only=True)' in circle_block
    assert 'circle_paywall_view' in circle_block
    assert 'consume_premium_video_free(' not in circle_block
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
    assert 'retention_features_service.get_retention_text(kind, char_id)' in SCHEDULER
    assert "scheduler.add_job(_rituals,'interval',minutes=30" in SCHEDULER
    assert '_streak_line(streak' in SCHEDULER  # V3.113.0: no «не прерывай серию» pressure


def test_premium_pitch_mentions_new_perks_and_plateau():
    pitch = MAIN[MAIN.index('def premium_pitch_text('):MAIN.index('def _limit_wall_markup(')]
    assert 'оживление фото в день' not in pitch
    assert 'photo animation a day' not in pitch
    assert 'видео-кружочки' in pitch
    assert 'безлимит сообщений' in pitch
    # V3.21.0 renamed the plateau line to the two premium levels.
    assert 'с 7-го по 10-й' in pitch  # V3.62.0: ten levels
