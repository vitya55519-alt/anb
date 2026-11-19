"""V3.166.9 (владелец): «пока генерируется фото, мне бы хотелось, чтобы она
задала какой-нибудь вопрос». Her words come first, the frame is drawn in the
background, and one short line of hers covers the wait."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def _turn():
    return MAIN[MAIN.index('async def _webapp_chat_turn('):MAIN.index('async def _webapp_api_chat_send(')]


def test_the_background_delivery_exists_and_sends_her_words_first():
    now = MAIN[MAIN.index('async def _photo_now('):MAIN.index('    try:\n        answer = await anna_reply(')]
    assert "'photo_pending': True" in now
    assert "'photo_wait': photo_wait_line(user_language)" in now
    assert '_spawn_background(_render())' in now
    # сама генерация — ровно та же функция, ничего не перенесено и не удешевлено
    assert 'got = await _photo_turn(scene, req, said=words, pay=pay)' in now
    assert "_app_ping(telegram_id, character_id, str(got.get('reply') or ''), 'photo')" in now
    # неудача тоже доходит до него словами, а не пустотой
    assert '_chat_photo_blocked, uid, character_id,' in now
    assert "'failed', None, telegram_id=telegram_id," in now


def test_photo_branches_use_it_only_when_she_has_words():
    turn = _turn()
    assert 'if said:\n            return await _photo_now(photo_scene, photo_req, said, photo_pay)' in turn
    assert 'return await _photo_now(\'selfie\', req, said, None, wait_extra)' in turn
    # без её реплики старый путь остался: один пузырь с подписью и картинкой
    assert 'payload = await _photo_turn(photo_scene, photo_req, said=said, pay=photo_pay)' in turn


def test_only_the_keys_the_spa_can_show_cross_the_receipt():
    assert "PHOTO_WAIT_KEYS = ('photo_url', 'paid_photo', 'set_completed', 'gallery'" in MAIN
    assert "'free_photos_left', 'credits_left')" in MAIN
    assert "PHOTO_WAIT_NOTE_KEYS = ('reply', 'photo_block', 'photo_price', 'locked_tease')" in MAIN
    assert 'if k in PHOTO_WAIT_KEYS and v}' in MAIN
    assert 'if k in PHOTO_WAIT_NOTE_KEYS}' in MAIN


def test_the_wait_route_is_registered():
    assert 'async def _webapp_api_chat_photo_wait(request: web.Request)' in MAIN
    assert "app.router.add_get('/webapp/api/chat/photo-wait', _webapp_api_chat_photo_wait)" in MAIN
    handler = MAIN[MAIN.index('async def _webapp_api_chat_photo_wait('):MAIN.index('async def _webapp_api_chat_photo(')]
    assert "webapp_service.validate_init_data(request.query.get('init_data', ''))" in handler
    assert 'chat_photo_wait.take, telegram_id, character_id' in handler
    assert "'more': more" in handler
    # забирается один раз — второй тап тот же кадр не покажет
    assert handler.count("chat_photo_wait.take") == 1


def test_her_wait_line_is_localized_for_every_app_language():
    from services import ui_lang
    assert 'ещё пара секунд, я делаю кадр. хочу, чтобы тебе понравилось 🙂' in ui_lang.PHOTO_WAIT_LINES['ru']
    for code in ui_lang.APP_LANGS:
        assert len(ui_lang.PHOTO_WAIT_LINES[code]) >= 2
        line = ui_lang.photo_wait_line(code)
        assert line in ui_lang.PHOTO_WAIT_LINES[code]
    # чужой код не роняет строку: она приходит из пула того языка, что выбрал app_lang
    for probe in ('de-DE', '', None):
        assert ui_lang.photo_wait_line(probe) in ui_lang.PHOTO_WAIT_LINES[ui_lang.app_lang(probe)]


def test_the_store_hands_one_frame_to_the_spa_once(monkeypatch):
    from services import chat_photo_wait as cw
    monkeypatch.setattr(cw, '_store', {})
    token = cw.begin(7, 'anna')
    assert cw.pending(7, 'anna') and cw.waiting(7, 'anna')
    assert cw.take(7, 'anna') is None            # ещё рисуется
    assert cw.deliver(7, 'anna', token, {'photo_url': '/webapp/media/x.jpg'})
    got = cw.take(7, 'anna')
    assert got == {'photo_url': '/webapp/media/x.jpg'}
    assert cw.take(7, 'anna') is None            # один раз
    assert cw.deliver(7, 'anna', 'nope', {}) is False
    # два кадра подряд: старый отдаётся первым, «ждать дальше» честно сказано
    t1, t2 = cw.begin(7, 'anna'), cw.begin(7, 'anna')
    cw.deliver(7, 'anna', t2, {'photo_url': 'second'})
    cw.deliver(7, 'anna', t1, {'photo_url': 'first'})
    assert cw.take(7, 'anna') == {'photo_url': 'first'}
    assert cw.waiting(7, 'anna') and cw.take(7, 'anna') == {'photo_url': 'second'}
    assert not cw.waiting(7, 'anna') and not cw.pending(7, 'anna')


def test_a_stale_frame_is_never_delivered_later(monkeypatch):
    import time as _clock
    from services import chat_photo_wait as cw

    class _Later:
        @staticmethod
        def time():
            return _clock.time() + cw.TTL_SECONDS + 1

    monkeypatch.setattr(cw, '_store', {})
    token = cw.begin(7, 'anna')
    monkeypatch.setattr(cw, 'time', _Later)
    assert cw.take(7, 'anna') is None
    assert not cw.pending(7, 'anna') and not cw.waiting(7, 'anna')
    assert cw.deliver(7, 'anna', token, {'photo_url': 'x'}) is False


def test_the_spa_shows_her_line_and_waits_for_the_frame():
    fn = SPA[SPA.index('function waitForChatPhoto('):SPA.index('function waitForDatePhoto(')]
    assert "/webapp/api/chat/photo-wait?init_data=" in fn
    assert "if (j.state === 'ready')" in fn
    assert "if (j.more) setTimeout(() => waitForChatPhoto(characterId), 2000)" in fn
    assert "if (j.state === 'idle') { done(); return; }" in fn
    assert 'PHOTO_WAIT_FOR === characterId' in fn       # один опрос на диалог
    # ждал-ждал и ничего: её слова всё равно лежат в истории — показать их
    assert 'loadChatHistory(characterId)' in fn
    assert SPA.count('function waitForChatPhoto(') == 1
    # второй плашки «кадр в пути» нет: её вопрос и есть знак, что картинка едет
    assert 'photoWaitTyping' not in SPA and 'photo_making' not in SPA
    start = SPA.index('function insertChatReply(')
    reply = SPA[start:SPA.index('\n}', start) + 2]
    assert "chatBubble('bot', j.photo_wait, null)" in reply
    assert "waitForChatPhoto(CHAT ? CHAT.id : '')" in reply
    # её вопрос встаёт сразу под её словами, а не после чипов этого ответа
    reply = re.sub(r'\s+', ' ', reply)
    message = ("chatBubble({ role: 'bot', content: j.reply || '', "
               "id: j.message_id, character_id: chatId, ts: null })")
    assert reply.index(message) < reply.index('if (j.photo_pending) {')
