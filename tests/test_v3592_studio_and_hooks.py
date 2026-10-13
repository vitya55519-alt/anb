"""V3.59.2: studio uploads fit the request cap, errors name the real problem,
and three engagement hooks: welcome selfie, chat openers, evening promise."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')


def test_upload_body_cap_and_clear_errors():
    assert 'web.Application(client_max_size=12 * 1024 * 1024)' in MAIN
    assert MAIN.count("return web.json_response({'ok': False, 'error': 'bad_image'}, status=400)") == 2
    assert INDEX.count("je.error === 'blocked' ? L.pic_blocked : (je.error === 'bad_image' ? L.pic_bad_image : L.pic_bad_request)") == 2
    up = INDEX[INDEX.index('function onStudioUpload('):INDEX.index('function paintUploadPreview(')]
    assert "c.toDataURL('image/jpeg', 0.88)" in up and '1600' in up


def test_welcome_selfie_follows_the_hello():
    h = MAIN[MAIN.index('async def consent_accept('):MAIN.index('async def _send_welcome_selfie(')]
    assert '_spawn_background(_send_welcome_selfie(' in h
    fn = MAIN[MAIN.index('async def _send_welcome_selfie('):]
    fn = fn[:fn.index('\n\n\n')]
    assert "_webapp_media_photo(telegram_id, character_id, 'selfie')" in fn
    assert "media_kind='photo'" in fn


def test_chat_openers():
    assert 'if (mine < 4) renderChatHints();' in INDEX
    assert INDEX.count('chat_hints:') == 2
    send = INDEX[INDEX.index('async function sendChat('):]
    assert "const hints = document.getElementById('chatHints'); if (hints) hints.remove();" in send[:800]


def test_evening_promise_kept_in_the_morning():
    r = SCHED[SCHED.index('async def _rituals('):]
    assert "if kind=='evening' and shot:" in r
    assert "_ritual_promised.add((uid,(now+dt.timedelta(days=1)).date().isoformat()))" in r
    assert "elif kind=='morning' and shot and (uid,today_key) in _ritual_promised:" in r
