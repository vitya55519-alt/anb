"""V3.66.0 static checks: clean shop cards + missions that pay peaches."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
GAM = (ROOT / 'services' / 'gamification_service.py').read_text(encoding='utf-8')
WEB = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')


def test_missions_pay_peaches_only_by_claim():
    assert 'MISSION_PEACHES: dict[str, int] = {' in GAM
    claim = GAM[GAM.index('def claim_mission'):GAM.index('def _user_message_count')]
    assert "grant_photo_credits(telegram_id, amount, reason=_mission_marker_reason(key))" in claim
    assert "return {'ok': False, 'error': 'locked'}" in claim
    # unlock itself still never touches peaches
    unlock = GAM[GAM.index('def _grant_achievement_reward'):GAM.index('def list_achievements')]
    assert 'grant_photo_credits' not in unlock


def test_get_missions_reports_peaches():
    gm = GAM[GAM.index('def get_missions'):GAM.index('def _today')]
    for field in ("'peaches'", "'claimed'", "'claimable'", "'peaches_total'", "'peaches_ready'", "'streak'"):
        assert field in gm


def test_app_chat_runs_mission_hooks():
    assert 'def note_app_chat_message(telegram_id: int, voice: bool = False) -> list[str]:' in GAM
    assert 'extra=await _app_chat_missions(telegram_id))' in MAIN
    assert "_app_chat_missions(telegram_id, voice=True)" in MAIN
    assert "app.router.add_post('/webapp/api/missions/claim', _webapp_api_missions_claim)" in MAIN


def test_spa_missions_claim_and_dot():
    assert 'async function claimMission(key, btn)' in INDEX
    assert "/webapp/api/missions/claim?init_data=" in INDEX
    assert 'function setMissionsDot(on)' in INDEX
    assert 'noteMissionsDone(j);' in INDEX
    assert 'mis_claim:' in INDEX and 'mis_done_toast:' in INDEX


def test_shop_cards_short():
    assert "'tagline':" in WEB
    assert "'photo_peaches': CHAT_PHOTO_PEACH_COST," in WEB
    assert 'class="premcard"' in INDEX
    assert 'function renderPromoBlock()' in INDEX
    assert 'id="freePeachRow"' in INDEX
    # the tile no longer prints the long description
    tiles = INDEX[INDEX.index('const packs = regularPurchases.map'):INDEX.index('const customTile')]
    assert 'x.description' not in tiles
