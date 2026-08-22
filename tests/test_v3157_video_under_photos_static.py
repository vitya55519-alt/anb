from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
PAYMENTS = (ROOT / 'services' / 'payments.py').read_text(encoding='utf-8')
USER_MODEL = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
DB = (ROOT / 'services' / 'db.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')


def test_animate_button_under_every_photo():
    assert 'def _photo_action_markup(' in PHOTO
    assert "callback_data=f'video:animate:{delivery_id}'" in PHOTO
    # Every delivery path (AI frames, library, topup, failure fallback) attaches it.
    assert PHOTO.count('_photo_action_markup(row_id') >= 4
    # Per-frame delivery rows anchor the button to a concrete photo.
    assert 'def _insert_delivery_row(' in PHOTO
    assert 'def _attach_delivery_file(' in PHOTO
    assert 'def _bump_photo_usage(' in PHOTO


def test_animate_photo_callback_guards():
    assert "F.data.startswith('video:animate:')" in MAIN
    block = MAIN[MAIN.index('async def animate_photo_cb('):]
    block = block.split('\n@dp.', 1)[0]
    assert 'has_accepted(' in block
    assert 'get_photo_delivery_for_user(' in block
    assert '_video_gate(' in block


def test_video_gate_free_premium_then_paid():
    gate = MAIN[MAIN.index('async def _video_gate('):]
    gate = gate.split('\n@dp.', 1)[0]
    # Admins animate photos for free without limits; Premium gets the daily slot.
    assert 'ADMIN_TELEGRAM_IDS' in gate
    assert 'is_premium(' in gate
    assert 'consume_premium_video_free(' in gate
    assert 'send_stars_invoice(' in gate
    assert 'VIDEO_COST_STARS' in gate
    # One unified job handles free (charge_id=None) runs with engine fallback.
    assert "_run_video_background(cq.message.chat.id, cq.from_user.id, delivery['id'], None)" in gate


def test_video_refund_only_for_paid_runs():
    sig = 'async def _run_video_background(chat_id: int, telegram_id: int, delivery_id: int, charge_id: str | None = None)'
    assert sig in MAIN
    block = MAIN[MAIN.index(sig):MAIN.index('@dp.callback_query(F.data.startswith(\'video:animate:\'))')]
    assert 'if charge_id:' in block
    # Engine fallback: Gemini/Veo first when enabled, HF spaces as backup.
    assert 'video_available()' in block
    assert 'hf_video_available()' in block
    assert 'animate_image_hf' in block


def test_premium_daily_free_limit_helpers():
    assert 'def premium_video_free_left(' in PAYMENTS
    assert 'def consume_premium_video_free(' in PAYMENTS
    assert 'VIDEO_PREMIUM_FREE_DAILY' in PAYMENTS
    # Daily counter lives on the user row and survives restarts.
    assert 'video_free_date' in USER_MODEL
    assert 'video_free_used' in USER_MODEL
    assert "'video_free_date'" in DB
    assert "'video_free_used'" in DB
    assert '"VIDEO_PREMIUM_FREE_DAILY", "1"' in CONFIG


def test_premium_pitch_mentions_daily_free_video():
    assert '1 бесплатное оживление фото каждый день' in MAIN
