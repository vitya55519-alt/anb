"""V3.58.3: a story choice answers at once (reward photo in the background)
and both stories and dates give visible feedback the moment they land."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def _fn(src, head, nxt):
    body = src[src.index(head):]
    return body[:body.index(nxt, len(head))]


def test_story_photo_no_longer_blocks_the_answer():
    fn = _fn(MAIN, 'async def _webapp_api_story_action(', '\nasync def ')
    assert 'await _webapp_media_scene(' not in fn
    assert '_spawn_background(_deliver_scene_photo(' in fn
    assert "'photo_pending': bool(stage_ok)," in fn
    deliver = _fn(MAIN, 'async def _deliver_scene_photo(', '\nasync def ')
    assert 'await _webapp_media_scene(telegram_id, character_id, scene)' in deliver
    assert "media_kind='photo'" in deliver


def test_story_result_is_visual_and_waits_for_photo():
    res = _fn(INDEX, 'function renderStoryResult(', '\nfunction ')
    assert 'class="stfx ' in res
    assert 'celebrate(' in res
    assert 'pollNewChatPhoto(' in res and 'storyPhotoWait' in res
    post = _fn(INDEX, 'async function storyPost(', '\nfunction ')
    assert 'L.story_thinking' in post
    assert INDEX.count('story_thinking:') == 2 and INDEX.count('story_photo_wait:') == 2


def test_date_answer_celebrates():
    fp = _fn(INDEX, 'async function featurePost(', '\n// ──')
    assert "if (payload.kind === 'date' && j.text) celebrate(" in fp
    assert "tg.HapticFeedback.notificationOccurred('success')" in INDEX
