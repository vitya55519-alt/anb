"""V3.46.0 static checks: achievement rewards + the missions funnel (backend).

Owner decisions this release encodes:
- Rewards are NON-monetized perks only — a free date voucher, a permanently
  unlocked sealed private-photo category, or a cosmetic badge. Never peaches,
  never Stars (so the 20🍑 creation and the paid-photo loop stay intact).
- `unlock_achievement()` used to record a row and grant nothing. It now hands
  out the perk exactly once, on the successful insert (idempotent).
- The legacy `retention_features_service` star-reward catalog is demoted to a
  non-authoritative note; the unified board is the single source of truth.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAM = (ROOT / 'services' / 'gamification_service.py').read_text(encoding='utf-8')
PICS = (ROOT / 'services' / 'private_photo_service.py').read_text(encoding='utf-8')
RET = (ROOT / 'services' / 'retention_features_service.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def test_reward_constants_and_preview():
    assert "REWARD_VOUCHER = 'voucher'" in GAM
    assert "REWARD_SCENE = 'scene'" in GAM
    assert 'def reward_preview(reward: list | None) -> str:' in GAM


def test_achievements_are_three_tuples_with_rewards():
    # every catalog entry now carries a reward list as its 3rd element
    assert "'ten_dates': ('10 свиданий', 'Десять свиданий — настоящий роман', [('voucher', None)])," in GAM
    assert "('scene', 'ach_anniv90')" in GAM
    assert "'premium_member': ('Premium', 'Оформили подписку Premium', [])," in GAM


def test_mission_funnel_keys_present():
    for key in ('first_creation', 'community_publish', 'views_100', 'first_video', 'first_spicy_photo'):
        assert f"'{key}':" in GAM


def test_no_peach_or_star_grant_on_unlock():
    # the reward dispatch must never touch the peach/star rails
    unlock = GAM[GAM.index('def _grant_achievement_reward'):GAM.index('def list_achievements')]
    assert 'grant_photo_credits' not in unlock
    assert 'grant_stars' not in unlock
    assert 'spend_peaches' not in unlock
    # voucher + scene are the only two material kinds
    assert 'grant_free_date_voucher(telegram_id)' in unlock
    assert 'grant_achievement(telegram_id, payload)' in unlock


def test_unlock_dispatches_reward_once_on_insert():
    fn = GAM[GAM.index('def unlock_achievement'):GAM.index('def _grant_achievement_reward')]
    assert 'display_name, _desc, reward = ACHIEVEMENTS[key]' in fn
    assert 'if existing:' in fn and 'return False' in fn
    # reward is granted AFTER the successful commit, on the fresh-unlock path
    assert '_grant_achievement_reward(telegram_id, reward)' in fn
    assert fn.index('session.commit()') < fn.index('_grant_achievement_reward')


def test_unified_board_surfaces_reward_chip():
    prog = GAM[GAM.index('def get_unified_progress'):]
    assert "'reward': reward_preview(reward)" in prog
    # lifecycle unpack is now a 3-tuple
    assert 'for key, (name, desc, reward) in ACHIEVEMENTS.items():' in prog


def test_scene_unlocks_map_to_real_categories():
    assert 'ACHIEVEMENT_SCENE_UNLOCKS: Dict[str, str] = {' in PICS
    assert '"ach_anniv90": "fully_nude"' in PICS
    assert 'def unlocked_scene_categories(telegram_id: int) -> set:' in PICS
    # consume_free_private_photo honors the achievement unlock BEFORE the daily
    # limit / hot pass, and never burns the counter for it
    consume = PICS[PICS.index('def consume_free_private_photo'):PICS.index('def activate_hot_pass')]
    assert 'ACHIEVEMENT_SCENE_UNLOCKS.get(k) == category' in consume
    assert consume.index('ACHIEVEMENT_SCENE_UNLOCKS.get(k) == category') < consume.index('Hot Pass')


def test_legacy_star_catalog_demoted():
    assert 'NOT the source of truth' in RET


# ── Increment 2: missions funnel in the bot ────────────────────────────────

def test_mission_group_and_cta_maps_present():
    assert 'MISSION_GROUP: dict[str, str] = {' in GAM
    assert 'MISSION_CTA: dict[str, tuple[str, str]] = {' in GAM
    # the funnel keys are grouped and CTAs reuse live callbacks only
    assert "'first_creation': 'creator'" in GAM
    assert "'constructor:start'" in GAM
    assert "'spicy:menu'" in GAM
    assert "'video:animate_last'" in GAM


def test_try_unlock_and_get_missions_helpers():
    assert 'def achievement_unlock_text(key: str) -> str:' in GAM
    assert 'def try_unlock(telegram_id: int, key: str) -> str:' in GAM
    assert 'def get_missions(telegram_id: int) -> dict:' in GAM
    # try_unlock only pings on a genuinely NEW unlock (unlock_achievement bool)
    unlock_body = GAM[GAM.index('def try_unlock'):GAM.index('def get_missions')]
    assert 'unlock_achievement(telegram_id, key)' in unlock_body
    # get_missions returns the roadmap shape the bot + app both render
    gm_body = GAM[GAM.index('def get_missions'):GAM.index('def _today')]
    for field in ("'pct'", "'items'", "'cta_cb'", "'group'"):
        assert field in gm_body


def test_bot_missions_screen_registered():
    # command + callback route and a discoverable menu button
    assert "@dp.message(Command('missions'))" in MAIN
    assert "F.data == 'missions:view'" in MAIN
    assert "callback_data='missions:view'" in MAIN
    assert 'def _missions_screen(' in MAIN
    assert 'from services.gamification_service import get_missions' in MAIN


def test_notify_unlock_helper_and_hooks():
    # single idempotent notify helper driving every mission unlock
    helper = MAIN[MAIN.index('async def _notify_unlock'):MAIN.index("F.data == 'missions:view'")]
    assert 'from services.gamification_service import try_unlock' in helper
    assert 'await bot.send_message(chat_id, text)' in helper
    # every funnel key is unlocked at a real event site
    for key in ('first_creation', 'community_publish', 'views_100', 'first_video', 'first_spicy_photo'):
        assert f"_notify_unlock(" in MAIN and f"'{key}')" in MAIN


def test_missions_cta_targets_are_real_callbacks():
    # the CTAs the missions screen points at must exist as live handlers
    for cb in ('constructor:start', 'video:animate_last', 'spicy:menu', 'photo_menu:open'):
        assert cb in MAIN
