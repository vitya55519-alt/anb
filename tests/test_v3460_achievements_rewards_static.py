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
