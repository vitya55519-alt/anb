"""V3.51.0: the playable-stories surface in the Mini App.
- ``GET /webapp/api/story`` and ``POST /webapp/api/story/action`` are mounted so
  the SPA runs the same resolvers the bot uses (branching / thresholds / live
  reaction are not duplicated in JS).
- The app-chat photo gap is closed: a photo request typed into the chat runs
  through ``parse_photo_request`` *before* the text model, so she sends a real
  photo instead of an empty «держи 📸».
- Premium accounts get exactly 4 daily tasks.
- The story player overlay, its chat-pill + character-card entries, the i18n
  keys and the photo render are all present in webapp/index.html.

Static pins (no imports -> runs without a DB/LLM key)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
COUPLE = (ROOT / 'services' / 'couple_service.py').read_text(encoding='utf-8')
WEBAPP = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_story_endpoints_declared_and_mounted():
    assert 'async def _webapp_api_story(' in MAIN
    assert 'async def _webapp_api_story_action(' in MAIN
    assert "app.router.add_get('/webapp/api/story', _webapp_api_story)" in MAIN
    assert "app.router.add_post('/webapp/api/story/action', _webapp_api_story_action)" in MAIN
    # the action endpoint delegates to the shared resolvers, no branch logic copy
    body = MAIN[MAIN.index('async def _webapp_api_story_action('):MAIN.index('async def _webapp_picture(')]
    assert 'await resolve_story_choice(' in body
    assert 'await resolve_story_beat(' in body


def test_chat_send_routes_photo_intent_before_the_text_model():
    # V3.57.0: the pipeline moved into the shared _webapp_chat_turn helper
    body = MAIN[MAIN.index('async def _webapp_chat_turn('):MAIN.index('async def _webapp_chat_turn') + 6000]
    assert 'parse_photo_request(' in body
    assert '_contextualize_vague_photo(' in body
    assert 'await anna_reply(' in body
    # the photo parse happens first, so a photo request never reaches the model
    assert body.index('parse_photo_request(') < body.index('await anna_reply(')
    # the delivered photo is mirrored into the shared dialog (media_kind=photo)
    assert "media_kind='photo'" in body


def test_premium_gets_four_daily_tasks():
    assert 'def daily_quests(telegram_id: int)' in COUPLE
    assert 'from services.access_service import is_premium' in COUPLE
    assert 'if is_premium(telegram_id):' in COUPLE
    assert 'count = 4' in COUPLE
    assert 'count = 3 if seed % 2 == 0 else 2' in COUPLE


def test_webapp_has_story_player_overlay_and_entries():
    assert 'id="storyview"' in WEBAPP
    assert 'async function openStory(' in WEBAPP
    assert 'function renderStoryList(' in WEBAPP
    assert 'function renderStoryResult(' in WEBAPP
    assert "'/webapp/api/story/action?init_data='" in WEBAPP
    # entry points: a chat pill and a character-card button under the path bar
    assert 'id="featStory"' in WEBAPP
    assert 'id="charStories"' in WEBAPP
    assert 'openStory(' in WEBAPP


def test_webapp_story_i18n_and_photo_render_present():
    for key in ('story_title', 'story_locked_level', 'story_locked_tasks',
                'story_canon', 'story_next' if 'story_next' in WEBAPP else 'story_play',
                'story_beat', 'story_done'):
        assert key in WEBAPP
    # a photo returned by the chat send is rendered, not dropped
    send = WEBAPP[WEBAPP.index('async function sendChat('):WEBAPP.index('requestMedia')]
    assert 'j.photo_url' in send
    assert "media_kind: 'photo'" in send
