"""V3.51.1: two post-V3.51 fixes the owner flagged from the deployed app, plus
the requested admin generation feed.

1. Story progress is now PER CHARACTER — ``UserQuestProgress`` is keyed by the
   character actually being played, not the hardcoded default — so every girl
   keeps her own canonical route and the per-character path axis can finally
   move. ``_apply_path`` also creates the relationship row when you play a story
   for a girl you never chatted with, so the «Характер связи» scale appears on
   her card instead of staying hidden.
2. The spontaneous daily-task bonus photo renders the ACTUAL character (was the
   generic owner pool -> wrong face), and a new admin-only feed in the Mini App
   lets the owner see what users generate (``UserGeneration`` audit rows +
   admin API + overlay).

Static pins (no imports -> the suite runs without a DB/LLM key)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUESTS = (ROOT / 'services' / 'quest_service.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
DB = (ROOT / 'services' / 'db.py').read_text(encoding='utf-8')
WEBAPP = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_story_progress_is_per_character():
    assert 'def progress(telegram_id: int, quest_key: str, character_id: str | None = None):' in QUESTS
    assert 'UserQuestProgress.character_id == char_id' in QUESTS
    assert 'row = UserQuestProgress(user_id=uid, character_id=char_id, quest_key=quest_key' in QUESTS
    assert 'def story_status(telegram_id: int, relationship_level: int, character_id: str | None = None) -> list[dict]:' in QUESTS
    assert 'def newly_unlocked_quests(telegram_id: int, previous_level: int, current_level: int, character_id: str | None = None) -> list[dict]:' in QUESTS
    assert 'p = progress(telegram_id, key, character_id)' in QUESTS
    # the write paths no longer key quest progress to the hardcoded default
    assert 'UserQuestProgress.user_id == uid, UserQuestProgress.character_id == CHARACTER_ID' not in QUESTS


def test_apply_path_creates_relationship_row():
    # playing a story for a girl with no relationship row must open her path
    assert 'row = UserCharacterRelationship(user_id=uid, character_id=character_id, path_axis=0.0)' in QUESTS
    seg = QUESTS[QUESTS.index('def _apply_path('):QUESTS.index('def get_quest')]
    assert 'session.add(row)' in seg and 'session.flush()' in seg


def test_callers_pass_the_character():
    assert 'story_status(telegram_id, level, character_id)' in MAIN
    assert 'story_status(telegram_id, level, cid)' in MAIN
    assert 'newly_unlocked_quests(telegram_id, before_level, after_level, get_user_character(telegram_id))' in MAIN


def test_bonus_photo_renders_the_actual_character():
    feat = MAIN[MAIN.index('async def _deliver_bonus_media('):MAIN.index('async def _webapp_api_feature_action(')]
    assert '_webapp_media_photo(telegram_id, character_id' in feat
    assert 'random_proactive_photo' not in feat
    assert '_webapp_media_photo(cq.from_user.id, character_id' in MAIN  # bot mirror


def test_usergeneration_model_and_migration():
    assert 'class UserGeneration(Base):' in MODELS
    assert '__tablename__ = "user_generations"' in MODELS
    assert 'UserGeneration' in DB  # imported so create_all sees the new table


def test_generation_recorded_at_the_user_render_points():
    assert 'def record_generation(' in WEBAPP_SVC
    assert 'def list_generations(' in WEBAPP_SVC
    assert "webapp_service.record_generation(telegram_id, 'picture', None, prompt, filename)" in MAIN
    assert "webapp_service.record_generation(telegram_id, 'photo', character_id, text, filename)" in MAIN
    assert 'webapp_service.record_generation(telegram_id, kind, character_id, scene, filename)' in MAIN


def test_admin_generation_api_and_routes():
    assert 'async def _webapp_api_admin_generations(' in MAIN
    assert 'async def _webapp_api_admin_gen_media(' in MAIN
    assert "app.router.add_get('/webapp/api/admin/generations', _webapp_api_admin_generations)" in MAIN
    assert "app.router.add_get('/webapp/api/admin/gen_media/{owner}/{filename}', _webapp_api_admin_gen_media)" in MAIN
    # both endpoints re-check admin server-side, never trusting the client
    assert MAIN.count('webapp_service._is_admin(') >= 2
    # api_me exposes the flag the app uses to reveal the entry
    assert "'admin': _is_admin(telegram_id)," in WEBAPP_SVC
    assert 'def _is_admin(' in WEBAPP_SVC


def test_webapp_admin_feed_ui():
    assert 'id="genview"' in WEBAPP
    assert 'async function openGenFeed(' in WEBAPP
    assert 'function renderGenFeed(' in WEBAPP
    assert 'id="menuGen"' in WEBAPP
    assert 'gen_title' in WEBAPP and 'gen_empty' in WEBAPP and 'gen_row' in WEBAPP
