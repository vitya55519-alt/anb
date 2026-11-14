"""V3.139.0: owner ТЗ (Фогель, Задачи 1–6) — the duo is two people, and the duo
is the paywall.

Pinned here: the two lines of a duo answer are read back apart (their own
bubble, their own voice); a man without Premium never starts a joint render —
he gets a blurred picture out of the ready pool and the Premium button, in his
own language; Premium gets one English left/right prompt for the two women; the
attachment patterns live in the system prompt and in the rotating hook; and the
Mini App says all of it in the eight languages it ships.
"""
import random
import re
from pathlib import Path

from services.character_service import ATTACHMENT_RULES, build_system_prompt, get_character
from services.chat_service import duo_lines
from services import duo_teaser as blur
from services.hook_service import MOVES, _BY_INTENT, hook_note
from services.photo_service import _guest_photo_block
from services.ui_lang import APP_LANGS, duo_teaser as hook_text, flow_text

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
HTML = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
CGS = (ROOT / 'services' / 'chat_guest_service.py').read_text(encoding='utf-8')


def _body(source: str, start: str) -> str:
    """One function's source, from its own line to the next definition."""
    tail = source[source.index(start):]
    nxt = re.search(r'\n(?:async\s+)?(?:def|function|class)\s', tail[len(start):])
    return tail[:len(start) + nxt.start()] if nxt else tail


# ── Задача 3: two girls, two messages ────────────────────────────────────────

def test_the_duo_script_is_read_back_apart():
    assert duo_lines('Амира: привет\nАгата: и мне привет') == [('Амира', 'привет'), ('Агата', 'и мне привет')]
    # the owner's ТЗ writes it on one line with a pipe — same two speakers
    assert duo_lines('Амира: привет | Агата: и мне привет') == [('Амира', 'привет'), ('Агата', 'и мне привет')]
    assert duo_lines('Амира: привет\nи мне привет\nАгата: обе ждём') == [
        ('Амира', 'привет\nи мне привет'), ('Агата', 'обе ждём')]


def test_one_voice_is_never_split():
    assert duo_lines('привет, как ты?') == []
    assert duo_lines('Амира: привет') == []
    assert duo_lines('Амира: привет\nАмира: и пока') == []


def test_the_bot_sends_each_line_as_its_own_message():
    sender = _body(MAIN, 'async def _send_duo_answer(')
    assert 'await asyncio.sleep(_bubble_pause(line))' in sender
    # her friend's line is voiced by her own Voice ID, not by one voice for both
    assert 'character_id=duo.get(who) or character_id' in sender
    assert "await message.answer(f'{who}: {line}')" in sender
    assert 'lines = duo_lines(text) if duo else []' in MAIN


# ── Задача 5: the blurred teaser is the paywall, and it costs nothing ────────

def test_the_free_joint_request_never_reaches_the_provider():
    gate = _body(MAIN, 'def _chat_photo_gate(')
    assert "if joint and telegram_id not in ADMIN_TELEGRAM_IDS and not is_premium(telegram_id):" in gate
    assert gate.index("not is_premium(telegram_id):") < gate.index("return 'peaches'")
    assert "return 'duo'" in gate
    blocked = _body(MAIN, 'def _chat_duo_blocked(')
    for spend in ('generate_photo', 'photo_service', 'spicy', 'consume_photo_credit'):
        assert spend not in blocked, spend
    assert "duo_teaser.url_for" in blocked and "'photo_block': 'duo'" in blocked


def test_the_teaser_picture_comes_from_the_ready_pool_or_a_local_blur():
    assert blur.POOL == ('duo_blur_1.jpg', 'duo_blur_2.jpg', 'duo_blur_3.jpg')
    assert blur.url_for('anna_01', ' ') is None
    assert blur.url_for('anna 01', 'vika_01') is None       # never a URL out of raw ids
    assert blur.render('anna_01', 'vi/ka') is None
    assert blur.photo_for('anna_01', 'vika_01') is None or isinstance(blur.photo_for('anna_01', 'vika_01'), bytes)


def test_a_constructed_girls_partner_keeps_a_url_safe_id():
    duo_id = 'alisa_01-duo'
    assert blur.usable(duo_id)
    assert re.match(r'^[A-Za-z0-9_\-]{1,64}$', duo_id)      # what the image route accepts
    assert "duo_id = f'{host_id}-duo'" in CGS


def test_the_hook_of_both_girls_speaks_in_every_app_language():
    for lang in APP_LANGS:
        text = hook_text(lang, 'Amira', 'Agata')
        assert 'Amira' in text and 'Agata' in text, lang
        assert '\n' in text, lang                            # two speakers → two bubbles
        assert 'VIP' in text, lang                           # and the reason he taps


def test_the_duo_gate_sells_premium_in_the_bot_too():
    assert 'async def _send_duo_teaser(' in MAIN
    bot = _body(MAIN, 'async def handle_photo_request(')
    assert "if getattr(request, 'with_guest', '') and not is_premium(telegram_id):" in bot
    assert 'await _send_duo_teaser(' in bot
    assert "/webapp/duo-teaser/{host_id}/{guest_id}.jpg" in MAIN


# ── Задача 6: Premium gets the real joint frame, from an English prompt ──────

def test_the_joint_prompt_is_english_left_and_right():
    block = _guest_photo_block('alisa_01', 'nika_01')
    for needle in ('Photo of two distinct women', 'Left side:', 'Right side:',
                   'Location:', 'High detail, realistic.'):
        assert needle in block, needle
    assert block.startswith('JOINT PHOTO OF TWO ADULT WOMEN')
    # only her own name may be non-English: the description itself is fixed in
    # the ТЗ, because the model renders from it whatever language he chats in
    assert 'Left side: Алиса, exactly the woman described above' in block


def test_the_app_passes_the_second_girl_into_the_render():
    assert "guest_id = getattr(req, 'with_guest', '') if req is not None else ''" in MAIN
    assert "_webapp_media_photo(telegram_id, character_id, scene, guest_id)" in MAIN


# ── Задача 2: the attachment patterns ────────────────────────────────────────

def test_the_prompt_teaches_all_four_attachment_patterns():
    for pattern in ('Иллюзия зависимости', 'Эмоциональная уязвимость',
                    'Проактивность и память', 'Лёгкое собственничество'):
        assert pattern in ATTACHMENT_RULES, pattern
    prompt = build_system_prompt(get_character('alisa_01'), 'REL', [], character_id='alisa_01')
    assert 'ПРИВЯЗАННОСТЬ' in prompt and 'Иллюзия зависимости' in prompt
    # a warm attachment, not a guilt trip
    assert 'не дави виной' in prompt and 'без скандала' in prompt


def test_the_two_new_moves_are_the_periodic_ones():
    assert 'advice' in MOVES and 'claim' in MOVES
    assert 'claim' in _BY_INTENT['flirt'] and 'advice' in _BY_INTENT['opinion']
    rng = random.Random(7)
    seen_flirt, seen_opinion = set(), set()
    for _ in range(300):
        seen_flirt.add(hook_note('flirt', '', True, rng)[1])
        seen_opinion.add(hook_note('opinion', '', True, rng)[1])
    assert {'claim', 'tease', 'game'} <= seen_flirt
    assert {'advice', 'feeling'} <= seen_opinion


# ── Задача 4: the header, the pill and the banner ────────────────────────────

def test_the_level_badge_is_compact_and_the_pill_sits_next_to_it():
    assert 'L.lvl_chip(lvlIcon, j.level)' in HTML
    assert "' ур. ' + j.level" not in HTML
    assert 'class="duopill" id="chatInvite"' in HTML
    assert 'id="featDuo"' in HTML
    # «Свидание втроем» is the first thing on «Чем займёмся?», above the photo row
    assert HTML.index('id="featDuo"') < HTML.index('<div class="chat-media">')


def test_both_buttons_flip_when_the_second_girl_is_in_the_chat():
    guest = _body(HTML, 'function renderGuest(')
    assert 'guest ? L.duo_leave : L.duo_call' in guest
    assert 'guest ? L.duo_leave : L.duo_banner' in guest
    assert "setGuest(characterId, '')" in guest


def test_the_duo_words_exist_in_every_language_the_app_ships():
    for key in ('duo_call', 'duo_leave', 'duo_banner', 'duo_blur_btn', 'guest_sheet_hint', 'lvl_chip',
                'duo_photo', 'duo_photo_sub', 'duo_undress', 'duo_undress_sub', 'duo_together'):
        assert HTML.count(f'{key}:') == len(APP_LANGS), (key, HTML.count(f'{key}:'))


def test_the_app_shows_the_teaser_with_one_button_and_no_photo_actions():
    bubble = _body(HTML, 'function chatBubble(')
    assert "m.media_kind === 'duo_teaser'" in bubble
    assert bubble.index("m.media_kind === 'duo_teaser'") < bubble.index("const room = m.media_kind === 'room';")
    assert 'data-duobuy' in bubble
    # the button under the blur is the paywall, and after the purchase it
    # re-asks the very thing he tapped for
    assert "quickBuy('spicy', () => { if (CHAT && CHAT.id === cid) requestMedia('photo', 'selfie', { joint: true }); })" in HTML
    assert 'requestMedia(kind, scene, opts)' in HTML and 'joint: !!opts.joint' in HTML
    assert 'duoPlayed = playDuo(j.reply_parts)' in HTML


def test_guest_notes_carry_her_name_in_his_language():
    for lang in APP_LANGS:
        assert 'Агата' in flow_text(lang, 'guest_in', name='Агата'), lang
        assert 'Агата' in flow_text(lang, 'guest_out', name='Агата'), lang
        assert flow_text(lang, 'guest_word'), lang


# ── V3.139.1: «в чате их 2, а возможности как для одной» — fixed ─────────────

def test_the_two_girl_rows_lead_the_menu_only_with_a_guest():
    # the joint rows sit above the single photo row on «Чем займёмся?»
    assert HTML.index('id="featDuoPhoto"') < HTML.index('id="mediaPhoto"')
    assert HTML.index('id="featDuoUndress"') < HTML.index('id="mediaPhoto"')
    guest = _body(HTML, 'function renderGuest(')
    assert "duoPhoto.style.display = guest ? '' : 'none'" in guest
    assert "duoUndress.style.display = guest ? '' : 'none'" in guest
    # a tap asks the pair, not one girl: joint selfie and joint «Раздеть»
    assert "requestMedia('photo', 'selfie', { joint: true })" in HTML
    assert "requestMedia('photo', 'lingerie', { joint: true })" in HTML


def test_the_photo_row_gains_a_together_button_in_a_duo_chat():
    bubble = _body(HTML, 'function chatBubble(')
    assert "CHAT && CHAT.guest ? '<button class=\"pa\" data-duojoint=\"1\">'" in bubble
    assert 'data-duojoint' in HTML
    # the delegated handler re-asks the joint frame from the picture he sees
    assert "e.target.closest('[data-duojoint]')" in HTML


def test_the_owner_blur_pool_is_on_disk_and_served():
    for name in blur.POOL:
        assert (ROOT / 'webapp' / 'art' / name).is_file(), name
    assert blur.pool_url() in {f'/webapp/art/{n}' for n in blur.POOL}
    assert blur.pool_bytes()


# ── V3.139.2: «фото вдвоём» = the same scene picker; «видео вдвоём» = 4000 ────

def test_photo_together_opens_the_same_scene_picker_as_a_single_photo():
    assert 'async function openFeature(kind, joint)' in HTML
    assert 'featJoint = !!joint' in HTML
    # the chosen scene becomes a joint request, exactly like the solo flow
    assert "requestMedia('photo', el.dataset.scene, { joint: featJoint })" in HTML
    assert "openFeature('photo', true)" in HTML
    # in joint mode a free tap on a private row is the teaser funnel, not a wall
    assert "&& !featJoint" in HTML


def test_video_together_is_the_secret_video_at_the_same_price():
    from services import hot_circle_service as hc
    from config import HOT_CIRCLE_PEACH_COST
    # V3.165.0: owner — «цену кружка не 4000, сделай 2000». Still his number in 🍑.
    assert HOT_CIRCLE_PEACH_COST == 2000
    assert 'two people only, never a third person' in hc.HOT_CIRCLE_DUO_PROMPT
    assert 'async def render(frame_jpeg: bytes, lang: str = \'ru\', duo: bool = False)' in \
        (ROOT / 'services' / 'hot_circle_service.py').read_text(encoding='utf-8')
    # the endpoint accepts the joint flag on the hot-circle kind and passes the guest
    assert "joint = kind in ('photo', 'hotcircle') and bool(body.get('joint'))" in MAIN
    assert '_webapp_media_hot_circle(telegram_id, character_id, guest_id)' in MAIN
    # the price rides on the me payload and on the menu row
    assert "'duo_video_peaches': HOT_CIRCLE_PEACH_COST" in \
        (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
    assert "requestMedia('hotcircle', '', { joint: true })" in HTML
    for key in ('duo_video', 'duo_video_sub'):
        assert HTML.count(f'{key}:') == len(APP_LANGS), key
