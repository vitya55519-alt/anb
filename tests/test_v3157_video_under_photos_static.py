import ast
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
    # V3.19.0: the preset picker runs before the video gate.
    assert '_show_video_preset_menu(' in block


def test_video_gate_paid_stars_except_admin():
    gate = MAIN[MAIN.index('async def _video_gate('):]
    gate = gate.split('\n@dp.', 1)[0]
    assert 'ADMIN_TELEGRAM_IDS' in gate
    assert 'has_monthly_premium(' not in gate
    assert 'consume_premium_video_free(' not in gate
    assert 'send_stars_invoice(' in gate
    assert 'VIDEO_COST_STARS' in gate
    # The admin job still uses the unified background renderer without a charge.
    assert "_run_video_background(cq.message.chat.id, cq.from_user.id, delivery['id'], None, motion_preset=motion_preset)" in gate


def test_video_refund_only_for_paid_runs():
    functions = {node.name: node for node in ast.parse(MAIN).body
                 if isinstance(node, ast.AsyncFunctionDef)}
    job = functions['_run_video_background']
    assert [arg.arg for arg in job.args.args] == [
        'chat_id', 'telegram_id', 'delivery_id', 'charge_id', 'motion_preset']
    assert [ast.literal_eval(value) for value in job.args.defaults] == [None, None]
    defaults = dict(zip((arg.arg for arg in job.args.kwonlyargs), job.args.kw_defaults))
    assert ast.literal_eval(defaults['app_only']) is False

    # Both the actual refund and its ledger entry must be inside the charge
    # guard, not merely somewhere in a function that mentions charge_id.
    failure = next(node for node in job.body if isinstance(node, ast.Try)).handlers[0]
    guard = next(node for node in failure.body
                 if isinstance(node, ast.If) and ast.unparse(node.test) == 'charge_id')
    for name in ('bot.refund_star_payment', 'record_refund'):
        calls = [node for node in ast.walk(job)
                 if isinstance(node, ast.Call) and ast.unparse(node.func) == name]
        assert len(calls) == 1
        assert calls[0] in list(ast.walk(guard.body[0]))
    refund = next(node for node in ast.walk(guard) if isinstance(node, ast.Call)
                  and ast.unparse(node.func) == 'bot.refund_star_payment')
    assert {kw.arg: ast.unparse(kw.value) for kw in refund.keywords} == {
        'user_id': 'telegram_id', 'telegram_payment_charge_id': 'charge_id'}

    # Stars purchases opt into app delivery; the default still supports admin jobs.
    paid_calls = [node for node in ast.walk(functions['successful_payment'])
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id == '_run_video_background']
    assert len(paid_calls) == 1
    assert ast.unparse(paid_calls[0].args[3]) == 'charge'
    assert any(kw.arg == 'app_only' and ast.literal_eval(kw.value) is True
               for kw in paid_calls[0].keywords)


def test_premium_daily_free_limit_helpers():
    assert 'def premium_video_free_left(' in PAYMENTS
    assert 'def consume_premium_video_free(' in PAYMENTS
    assert 'VIDEO_PREMIUM_FREE_DAILY' in PAYMENTS
    # Daily counter lives on the user row and survives restarts.
    assert 'video_free_date' in USER_MODEL
    assert 'video_free_used' in USER_MODEL
    assert "'video_free_date'" in DB
    assert "'video_free_used'" in DB
    # Animations are paid separately; the legacy helper is disabled by default.
    assert '"VIDEO_PREMIUM_FREE_DAILY", "0"' in CONFIG


def test_premium_pitch_does_not_promise_free_video():
    pitch = MAIN[MAIN.index('def premium_pitch_text('):MAIN.index('def _limit_wall_markup(')]
    assert 'оживление фото в день' not in pitch
    assert 'photo animation a day' not in pitch
