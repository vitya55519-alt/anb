"""V3.166.10 (владелец): пять правок по живому чату Mini App + новый текст в боте.

1. «вот она стоит в белье. Я нажимаю „Раздеть“, и мне это фото уже нельзя
   изменить…» — гейт действия знал только media_kind='photo', а оплаченный
   кадр «наедине…» лежит в истории как 'hot' (косплей — 'cosplay');
2. «три руки… третья рука вообще всё портит. Может, как-то в начале этих
   промптов делать» — анатомия стала первой строкой промпта «Раздеть»: хвост
   режет _fit_spicy_prompt, и модель дочитывает его последним;
3. «кнопки „Привет“, „Расскажи о себе“, „Покажи себя“ не уходят… думал, когда
   переписка уже идёт, они просто исчезают» — подсказки остаются только в том
   диалоге, где он ещё ни разу не написал;
4. «переключаясь на Камилу, фото Анны прилетает на чат Камилы» — каждый
   асинхронный конвейер помнит диалог, из которого вышел, и молча
   останавливается, если к этому времени открыт другой;
5. «какой-то пуш, который будет выходить… Анна вам сообщение. Нажимаешь и
   приходишь в тот чат» — плашка над перепиской по тому же unread, что
   рисует бейджи на вкладке «Чаты»;
6. новое приветствие в боте под его гифкой.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def _block(start: str, end: str, text: str = MAIN) -> str:
    i = text.index(start)
    return text[i:text.index(end, i)]


# ── 1. платный кадр «наедине…» тоже раздевается ───────────────────────────

def test_paid_frames_pass_the_action_gate():
    gate = _block('async def _webapp_api_photo_action(', "'credits', 402")
    assert "her_frames = ('photo', 'hot', 'cosplay')" in gate
    assert "kinds = her_frames + ('room',) if action == 'animate' else her_frames" in gate
    assert 'if not _her_photo(uid, kinds):' in gate
    # единственная виденная раньше пометка не перечисляется больше нигде в гейте
    assert "('photo',)" not in gate
    # деньги не тронуты: та же лестница цен стоит под гейтом
    assert 'webapp_service.WEBAPP_VIDEO_COST_CREDITS' in gate


def test_the_spa_already_lays_the_chips_under_a_paid_frame():
    # правка была только серверная: под любым её кадром, кроме интерьера
    # «🏠 Дом», «Раздеть» и «Оживить» рисуются и так.
    row = _block("      const room = m.media_kind === ", "else body = `<img", SPA)
    assert 'data-pact="undress"' in row
    assert 'data-pact="animate"' in row
    assert 'room ? ' in row


# ── 2. анатомия — первая строка промпта «Раздеть» ─────────────────────────

def test_the_anatomy_lock_leads_the_undress_prompt():
    lock = _block('UNDRESS_ANATOMY_LOCK = (\n', 'UNDRESS_PROMPT = (')
    assert lock.startswith("UNDRESS_ANATOMY_LOCK = (\n    'HANDS:")
    assert 'exactly two arms and two hands' in lock
    assert 'five correct fingers on each hand' in lock
    assert 'Never a third hand or arm' in lock
    # рука, уже лежащая в первом кадре, не получает права на третью
    assert 'the reveal does not get a free third one' in lock
    assembly = _block('    prompt, secret = (UNDRESS_ANATOMY_LOCK', '\n    try:')
    assert "UNDRESS_ANATOMY_LOCK + '\\n' + UNDRESS_PROMPT" in assembly
    # хвост по-прежнему идёт после всего — но анатомии в нём больше нет
    assert assembly.index('UNDRESS_ANATOMY_LOCK') < assembly.index('UNDRESS_TAIL')


def test_the_lock_is_the_last_thing_the_trimmer_touches():
    from services import private_photo_service as pps
    # tier 3 срезают последним; «HANDS:» лежит там же, где три ТЗ-замка
    assert 'HANDS:' in pps._SPICY_TIERS[2]
    assert pps._spicy_tier('HANDS: she is ONE person with exactly two arms') == 3
    assert pps._spicy_tier('Edit this exact photo. Keep the SAME adult woman') == 0
    # в хвосте осталась ровно та фраза про телефон в руке (тест V3.63.1)
    assert 'if one hand holds the phone' in MAIN


# ── 3. подсказки уходят, когда переписка пошла ────────────────────────────

def test_opener_chips_only_in_a_dialog_he_never_wrote_in():
    hist = _block('    const mine = j.history.filter', 'box.scrollTop = box.scrollHeight;', SPA)
    assert "const mine = j.history.filter(m => m.role === 'user').length;" in hist
    assert 'if (!mine) renderChatHints();' in hist
    # другой пороги подсказок в истории больше нет — только «ни разу не писал»
    assert SPA.count('renderChatHints()') == 1


# ── 4. ответ не переезжает в другой чат ───────────────────────────────────

def test_the_spa_remembers_which_dialog_a_pipeline_came_from():
    assert 'function sameChat(id) { return !id || (CHAT && CHAT.id === id); }' in SPA
    assert SPA.count('if (!sameChat(chatId)) return;') >= 6
    assert 'if (!sameChat(characterId)) return;' in SPA      # фоновый кадр V3.166.9
    # все конвейеры берут id диалога до первого await
    assert SPA.count('const chatId = CHAT.id;') >= 4
    assert 'function renderChatReply(j, chatId)' in SPA
    assert 'function insertChatReply(j, chatId)' in SPA
    assert 'function afterDraft(d, done, chatId)' in SPA
    assert 'function showRecording(done, ms, line, chatId)' in SPA


def test_the_open_chat_is_the_only_one_a_reply_can_paint():
    send = _block('async function sendChat(', 'function undressTease(', SPA)
    assert 'character_id: chatId' in send
    assert 'renderChatReply(j, chatId)' in send
    media = _block('async function requestMedia(', 'function closeFeature()', SPA)
    assert 'character_id: chatId' in media
    assert 'if (!sameChat(chatId)) return;' in media
    assert 'renderChatReply(j, chatId)' in media
    # пузырь кадра вставляется только после проверки окна
    assert media.index('if (!sameChat(chatId)) return;') < media.index('chatBubble({ role: ')
    wait = _block('function waitForChatPhoto(', 'function waitForDatePhoto(', SPA)
    assert "if (!sameChat(characterId)) return;" in wait


# ── 5. плашка «Анна написала» ─────────────────────────────────────────────

def test_the_arrived_route_reads_the_same_unread_as_the_badges():
    assert 'async def _webapp_api_chat_arrived(request: web.Request)' in MAIN
    assert "app.router.add_get('/webapp/api/chat/arrived', _webapp_api_chat_arrived)" in MAIN
    handler = _block('async def _webapp_api_chat_arrived(', 'async def _webapp_api_chat_photo(')
    assert "webapp_service.validate_init_data(request.query.get('init_data', ''))" in handler
    assert "request.query.get('except', '')" in handler
    # ни одной новой счётойки: тот же api_chat_list, что и у бейджей «Чатов»
    assert 'webapp_service.api_chat_list(uid, telegram_id)' in handler
    assert "if not row.get('unread') or row.get('last_role') != 'assistant':" in handler
    assert "if row.get('id') == except_id:" in handler
    assert 'if len(arrived) >= 3:' in handler
    assert "row.get('last_message')" in handler
    # опрос только читает — отметить прочитанным он не имеет права
    assert 'save_message' not in handler and 'mark_chat_read' not in handler


def test_the_spa_polls_other_dialogs_and_taps_through():
    assert '<div class="arrivedbar" id="arrivedBar" style="display:none"></div>' in SPA
    poll = _block('async function pollChatArrived()', 'function startArrivedPoll()', SPA)
    assert "'/webapp/api/chat/arrived?init_data='" in poll
    assert "'&except=' + encodeURIComponent(fromChat)" in poll
    # чат закрыли в обход кнопки «назад» — опрос не крутится
    assert "if (!CHAT || !document.getElementById('chatview').classList.contains('open')) return;" in poll
    # он успел сменить диалог, пока шёл запрос — не показываем
    assert 'if (!CHAT || CHAT.id !== fromChat) return;' in poll
    start = _block('function startArrivedPoll()', 'function stopArrivedPoll()', SPA)
    assert 'setInterval(pollChatArrived, 25000)' in start
    assert 'stopArrivedPoll();' in start                 # один опрос, не веер
    rows = _block('function renderArrived(list)', 'async function pollChatArrived()', SPA)
    assert 'ARRIVED_LIST.slice(0, 3)' in rows
    assert 'L.arrived_wrote' in rows
    assert 'openChat({ id: c.id, name: c.name, photo: c.photo, emoji: c.emoji, status: c.status, custom: c.custom' in rows
    assert '.arrivedbar .ab-row' in SPA
    # живёт ровно пока открыт чат
    assert 'startArrivedPoll();' in _block('function openChat(c) {', 'return history;', SPA)
    assert 'stopArrivedPoll();' in _block("document.getElementById('chatBack').addEventListener", 'loadChats();', SPA)


def test_the_push_line_is_localized_in_both_tables():
    en = _block('const L_EN = {', 'const L_RU = {', SPA)
    ru = _block('const L_RU = {', 'const L = LANG', SPA)
    assert "arrived_wrote: 'wrote you'" in en
    assert "arrived_wrote: 'написала тебе'" in ru


# ── 6. приветствие в боте ─────────────────────────────────────────────────

def test_the_new_welcome_lives_under_his_gif():
    start = _block('async def start(message: types.Message',
                   'await _send_welcome_banner(message, lang, welcome, start_keyboard(lang))')
    assert 'Идеальная девушка на вечер... или навсегда. 🔥' in start
    assert 'Что тебя ждет внутри:' in start
    assert '🌸 Два режима' in start and '📸 Живой контент' in start
    assert '🎙 Голос' in start and '📈 Развитие' in start
    assert 'The perfect girl for tonight... or forever. 🔥' in start
    assert '⬇️ Поехали! ⬇️' in start
    # гифка осталась: текст по-прежнему едет подписью к баннеру
    assert 'await _send_welcome_banner(message, lang, welcome, start_keyboard(lang))' in MAIN


def test_the_free_messages_line_repeats_the_real_cap():
    assert 'from services.daily_limit import DAILY_CAP' in MAIN
    assert "f'🎁 Дарим {DAILY_CAP} бесплатных сообщений для старта.\\n'" in MAIN
    assert "f'🎁 {DAILY_CAP} free messages to start with.\\n'" in MAIN
    # выключишь кап — витрина не соврёт
    assert "🎁 Сообщения без лимита." in MAIN
    assert '🎁 Дарим 30' not in MAIN
