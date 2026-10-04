"""V3.49.0: daily tasks (2-3 per day) become the cumulative currency that
unlocks story quests on the 5/10/15... ladder. Each fresh claim grants +5
attention, bumps ``quests_completed``, and rolls a <=20% spontaneous free-photo
drop (at most once per day) that reuses the owner's proactive pool and never
mints peaches/Stars (V3.46.0 rule). Static, in the style of the other V3.x pins
(the suite cannot import services without an LLM key, so no behavioral test)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
COUPLE = (ROOT / 'services' / 'couple_service.py').read_text(encoding='utf-8')
QUESTS = (ROOT / 'services' / 'quest_service.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
WEBAPP = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_user_columns_added():
    for col in ('quests_completed', 'quest_claims', 'bonus_media_date'):
        assert col in MODELS


def test_daily_quests_returns_2_to_3_with_legacy_wrapper():
    assert 'def daily_quests(telegram_id: int)' in COUPLE
    assert 'count = 3 if seed % 2 == 0 else 2' in COUPLE
    # V3.51.0: premium gets exactly 4 daily tasks (lazy is_premium import)
    assert 'from services.access_service import is_premium' in COUPLE
    assert 'if is_premium(telegram_id):' in COUPLE
    assert 'count = 4' in COUPLE
    # the single-quest entry point survives so the V3.21 pins stay green
    assert 'def daily_quest(telegram_id: int)' in COUPLE
    assert 'return daily_quests(telegram_id)[0]' in COUPLE


def test_claim_is_idempotent_per_key_and_counts_tasks():
    assert 'def claim_quest(telegram_id: int, quest_key: str)' in COUPLE
    assert "if quest_key in done:" in COUPLE
    assert "user.quests_completed = (user.quests_completed or 0) + 1" in COUPLE
    assert "user.attention_points = (user.attention_points or 0) + 5" in COUPLE


def test_bonus_media_roll_is_capped_and_once_per_day():
    assert 'if random.random() < 0.20:' in COUPLE
    assert "if (user.bonus_media_date or '') == today:" in COUPLE


def test_story_gate_requires_level_and_tasks():
    # V3.51.0: the ladder is tied to the story's own level (5 x min_level), so
    # a level-5 dilemma costs 25 tasks, not 75. All three sources agree.
    assert "need_tasks = 5 * int(q['min_level'])" in QUESTS
    assert "return 5 * int(q['min_level']) if q else 0" in QUESTS
    assert "if completed < 5 * int(quest['min_level']):" in QUESTS
    assert "'unlocked': level_ok and tasks_ok" in QUESTS
    assert "'tasks_remaining': max(0, need_tasks - completed)" in QUESTS


def test_bonus_media_never_mints_peaches():
    feat = MAIN[MAIN.index('def _deliver_bonus_media('):MAIN.index('async def _webapp_api_feature_action(')]
    # V3.51.1: the free drop now renders the actual character (was the generic
    # owner pool); it still must not touch the peach/credit balance.
    assert '_webapp_media_photo(' in feat
    assert 'save_chat_media(' in feat
    assert 'photo_credits' not in feat


def test_webapp_renders_checklist_and_progress():
    quest = WEBAPP[WEBAPP.index("if (j.kind === 'quest')"):WEBAPP.index("const items = j.items ||")]
    assert 'j.quests' in quest
    assert 'data-qkey' in quest
    assert 'next_unlock' in quest
