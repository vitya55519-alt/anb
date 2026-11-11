"""Photo animations are paid: Stars in the bot and peaches in the Mini App."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_no_free_animation_allowances():
    from config import VIDEO_PREMIUM_FREE_DAILY
    from services.trial_caps import CAPS
    assert VIDEO_PREMIUM_FREE_DAILY == 0
    assert CAPS['month']['animations'] == 0
    assert CAPS['quarter']['animations'] == 0


def test_bot_gate_sells_stars_and_checks_delivery_before_payment():
    i = MAIN.index('async def _video_gate(')
    body = MAIN[i:MAIN.index('@dp.callback_query(F.data.startswith(\'video:animate:\'))', i)]
    assert 'send_stars_invoice(' in body
    assert "f'video:{delivery[\"id\"]}:{motion_preset or \"auto\"}'" in body
    assert 'VIDEO_COST_STARS' in body
    assert 'has_monthly_premium(' not in body
    assert 'consume_premium_video_free(' not in body
    assert 'ADMIN_TELEGRAM_IDS' in body
    invoice_texts = MAIN[MAIN.index('def _invoice_texts_en('):MAIN.index('async def send_stars_invoice(')]
    assert "payload.startswith('video:')" in invoice_texts
    assert "return 'Photo animation', 'A short video from this photo'" in invoice_texts

    j = MAIN.index("elif payload.startswith('video:'):")
    checkout = MAIN[j:MAIN.index("elif payload.startswith('constructor:')", j)]
    assert 'amount == VIDEO_COST_STARS' in checkout
    assert 'get_photo_delivery_for_user(query.from_user.id, delivery_id)' in checkout
    assert 'ok = False' in checkout


def test_app_paths_charge_paid_peaches_after_success():
    assert "'month_required'" not in MAIN
    assert "'video_limit'" not in MAIN
    # Two animation paths plus the already-paid Studio video path.
    assert MAIN.count('get_paid_peaches(telegram_id) < webapp_service.WEBAPP_VIDEO_COST_CREDITS') == 3
    assert MAIN.count('spend_peaches(telegram_id, webapp_service.WEBAPP_VIDEO_COST_CREDITS, paid_only=True)') == 3
    assert "quickBuy('peaches'" in SPA


def test_requested_voice_and_weekly_undress_limits_stay_unchanged():
    from services.trial_caps import CAPS
    assert CAPS['month']['voice'] == 50
    assert CAPS['week']['undress'] == 2
