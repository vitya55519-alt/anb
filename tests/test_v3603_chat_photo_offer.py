"""V3.60.3: no more «лови» with nothing attached — she says what blocks the photo."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_chat_photo_costs_two_peaches():
    import config
    assert config.CHAT_PHOTO_PEACH_COST == 2
    assert 'get_photo_credits(telegram_id) >= CHAT_PHOTO_PEACH_COST' in MAIN
    assert 'spend_peaches(telegram_id, CHAT_PHOTO_PEACH_COST)' in MAIN


def test_blocked_or_failed_photo_never_reaches_the_model():
    turn = MAIN[MAIN.index('async def _webapp_chat_turn('):MAIN.index('async def _webapp_api_chat_send(')]
    assert turn.index("_chat_photo_blocked, uid, character_id, photo_block, extra") < turn.index('answer = await anna_reply(')
    assert "_chat_photo_blocked, uid, character_id, 'failed', extra" in turn
    for reason in ('peaches', 'stage', 'adult', 'failed'):
        assert f"'{reason}':" in MAIN[MAIN.index('CHAT_PHOTO_BLOCK_TEXT = {'):]


def test_spa_offers_the_shop():
    assert "j.photo_block === 'peaches'" in SPA and "showTab('shop')" in SPA
