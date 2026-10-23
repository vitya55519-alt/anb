"""V3.71.0: video circles are paid in peaches for everyone (owner: «кошки
сделать платными» — each render costs us ~$0.2–0.3)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
WEBAPP = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_price_is_700_peaches():
    assert 'CIRCLE_PEACH_COST = _peach_env("CIRCLE_PEACH_COST", 7)' in CONFIG
    from config import CIRCLE_PEACH_COST
    assert CIRCLE_PEACH_COST == 700


def test_bot_circle_charges_and_refunds_peaches():
    gate = MAIN[MAIN.index("@dp.callback_query(F.data == 'video:circle')"):MAIN.index('async def _run_circle_background(')]
    assert 'not is_premium(' not in gate
    assert 'spend_peaches(cq.from_user.id, CIRCLE_PEACH_COST)' in gate
    assert 'peaches_keyboard(cq.from_user.id)' in gate
    job = MAIN[MAIN.index('async def _run_circle_background('):]
    job = job[:job.index('\n\n\n')]
    assert 'if charge_id == CIRCLE_PEACH_CHARGE:' in job
    assert 'add_peaches, telegram_id, CIRCLE_PEACH_COST' in job


def test_app_circle_charges_only_after_success():
    block = MAIN[MAIN.index('async def _webapp_api_chat_media('):MAIN.index('async def _webapp_media(')]
    gate = block[:block.index('gated = await asyncio.to_thread(_gate)')]
    finish = block[block.index('def _finish():'):]
    assert "'error': 'circle_limit'" not in gate
    assert "kind == 'circle' and telegram_id not in ADMIN_TELEGRAM_IDS and not spend_peaches(telegram_id, CIRCLE_PEACH_COST)" in finish


def test_shop_and_premium_copy():
    assert "('🎥', 'Кружочек' if not en else 'Video circle', CIRCLE_PEACH_COST)" in WEBAPP
    assert 'кружочки' not in WEBAPP[WEBAPP.index('def api_shop('):WEBAPP.index("'free_tier'")]
    assert "if (sp.get('open') === 'shop') { showTab('shop'); return; }" in INDEX
    assert 'только Premium' not in MAIN[MAIN.index('def premium_keyboard('):MAIN.index('def adult_keyboard(')]
