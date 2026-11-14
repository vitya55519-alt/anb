"""V3.138.0: owner — «это не переписка в мессенджере, это театральная пьеса».
No RP format anywhere: no *stage directions*, no «Амира:» prefixes in a chat
with one girl, one voice per reply. Banned in the persona prompt, banned in
every language's directive, and cut out of the answer before it reaches him.
Same file pins the «Раздеть» price: peaches only, 250 🍑 ≈ 25 ₽, and never on
a picture of her room."""
from pathlib import Path

from services.character_service import build_system_prompt, get_character
from services.chat_service import plain_message
from services import lang_guard

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
LT = (ROOT / 'services' / 'live_talk.py').read_text(encoding='utf-8')
HTML = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
SCENES = tuple((ROOT / 'services' / p).read_text(encoding='utf-8') for p in (
    'apartment_service.py', 'dates_service.py', 'scenario_cards.py', 'storylines.py',
    'custom_character_service.py', 'chat_guest_service.py', 'lang_guard.py'))


def _prompt(cid='alisa_01'):
    return build_system_prompt(get_character(cid), 'REL', [], character_id=cid)


# ── 1. the prompt says it in stone ───────────────────────────────────────────

def test_prompt_bans_the_rp_format():
    t = _prompt()
    assert 'ФОРМАТ СООБЩЕНИЯ' in t
    assert 'Пиши только то, что живой человек набрал бы на клавиатуре смартфона' in t
    assert 'Никогда не используй звёздочки *, скобки (), ~~' in t
    assert 'для описания своих действий, мыслей, мимики или тона голоса' in t
    assert 'Никогда не ставь имя перед своей репликой' in t
    assert 'Отвечай строго от своего лица. Никогда не пиши реплики за него и за других людей' in t
    # the emotion has to come out of the text itself
    assert 'Эмоция — только самим текстом' in t


def test_no_prompt_invites_asterisk_remarks():
    for src in (MAIN, LT, CHAT) + SCENES:
        for invited in ('сначала в звёздочках', 'Первая строка в звёздочках', 'Сохрани *звёздочки*',
                        'короткие действия в *звёздочках*', 'действия в *звёздочках* тоже'):
            assert invited not in src, invited


# ── 2. and the theatre never reaches the chat anyway ─────────────────────────

def test_stage_directions_are_cut_out():
    assert plain_message('*тихо, с ленивой улыбкой в голосе* ага, и что ты теперь будешь делать?') \
        == 'ага, и что ты теперь будешь делать?'
    assert plain_message('Амира: *шёпотом, ещё тише* ну скажи уже') == 'ну скажи уже'
    assert plain_message('(улыбаюсь) ну ты даёшь') == 'ну ты даёшь'
    # a message that is nothing but a remark stays empty — _clean answers with a line
    assert plain_message('*смотрит в окно*') == ''


def test_one_word_emphasis_is_not_a_remark():
    # «я *никогда* так не делала» is a person typing, not a play script
    assert plain_message('я *никогда* так не делала') == 'я никогда так не делала'


def test_duo_keeps_the_names_and_drops_the_theatre():
    assert plain_message('Амира: привет\nАгата: *машет рукой* и мне привет', duo=True) \
        == 'Амира: привет\nАгата: и мне привет'


def test_the_cut_works_in_every_language_of_the_app():
    assert plain_message('হ্যালো, *হাসি* তুমি কোথায়?') == 'হ্যালো, হাসি তুমি কোথায়?'
    assert plain_message('নমস্কার, কেমন আছো?') == 'নমস্কার, কেমন আছো?'
    assert plain_message('你好呀～今天好累') == '你好呀～今天好累'
    assert plain_message('Амира: নমস্কার') == 'নমস্কার'


def test_clean_wires_the_cut_into_every_reply():
    assert 'answer = plain_message(answer, duo=duo)' in CHAT
    assert 'duo_chat = bool(guest_reminder)' in CHAT
    # V3.151.0: the novel engine splits «THOUGHT: / MESSAGE:» before cleaning,
    # so the stage-direction cut now runs inside novel_pair on the MESSAGE only.
    assert 'thought, answer = novel_pair(r.text, duo=duo_chat)' in CHAT
    assert 'def novel_pair(' in CHAT and '_clean(md, duo=duo)' in CHAT
    # the opening scene is where the format is learned — cleaned there too
    assert "scene = plain_message((r.text or '').strip()) or None" in MAIN
    assert 'text = plain_message((r.text or "").strip(), duo=True)'.replace('"', "'") in MAIN


# ── 3. every language carries the same ban ───────────────────────────────────

def test_language_directives_ban_the_rp_format():
    for lang in ('en', 'es', 'it', 'fr', 'pt', 'de', 'bn', 'hi', 'ar', 'zh', 'ja', 'ko', 'th'):
        d = lang_guard.directive(lang)
        assert 'никаких действий в *звёздочках*' in d, (lang, d)
        assert 'никакого имени перед репликой' in d, (lang, d)
        assert 'как в мессенджере' in d and 'проявляй инициативу' in d, (lang, d)


def test_name_line_bans_it_for_the_messages_she_writes_first():
    for lang in ('bn', 'zh', 'ja', 'es'):
        assert 'без действий в *звёздочках*' in lang_guard.name_line(lang), lang


# ── 4. «Раздеть»: peaches only (V3.154.0: 400 🍑; V3.165.0: owner — «одна цена
#    300 для обоих режимов», so the frame price moved down to 300 🍑 ≈ 30 ₽) ─

def test_undress_price_is_peaches_worth_30_rubles():
    from config import EXPLICIT_PHOTO_PEACH_COST, PEACH_SCALE, PEACH_PACK_10_RUB, UNDRESS_PEACH_COST
    assert UNDRESS_PEACH_COST == 300 == EXPLICIT_PHOTO_PEACH_COST
    rubles = UNDRESS_PEACH_COST / PEACH_SCALE * (PEACH_PACK_10_RUB / 10)
    assert 25 <= rubles <= 35, rubles


def test_the_app_prices_undress_in_peaches_everywhere_it_offers_it():
    assert "'undress_peaches': UNDRESS_PEACH_COST" in (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
    assert HTML.count("undress_peaches") >= 4
    assert " + ' ₽'" not in HTML.split('function openHot18')[1].split('function ')[0]
    assert "['peach_pack_30', 'peach_pack_100'].concat(trialFirst, ['premium_week'])" in HTML


def test_the_peach_route_replaces_the_money_paywall():
    body = MAIN[MAIN.index('async def _webapp_api_photo_action('):]
    gate = body[:body.index('    uid, err, pay = await')]
    assert "return uid, ('premium_required', 403), None" not in gate
    assert "return uid, ('credits', 402), None" in gate
    # non-premium is not a wall any more: what he already paid for spends first,
    # only a short peach balance sends him to the sheet
    assert gate.index('if not is_premium(telegram_id):') < gate.index('undress_credits.balance(telegram_id) > 0')
    assert gate.index('undress_credits.balance(telegram_id) > 0') < gate.index('get_paid_peaches(telegram_id) < UNDRESS_PEACH_COST')
    # and the readiness poll says ready when peaches are enough
    ready = MAIN.split('async def _webapp_api_undress_credit(', 1)[1].split('async def _webapp_api_photo_action', 1)[0]
    assert 'peaches >= UNDRESS_PEACH_COST' in ready


# ── 5. nobody to undress in a picture of the room ────────────────────────────

def test_room_picture_is_marked_and_never_offered_for_undress():
    home = MAIN[MAIN.index('async def _render_home('):MAIN.index('async def _webapp_api_home_style(')]
    assert "media_kind='room'" in home
    assert "const room = m.media_kind === 'room';" in HTML
    # V3.165.0: the old pin compared two file-wide indexes and a new '</button>')
    # elsewhere in the SPA moved it; check the feed bubble itself instead.
    feed = HTML[HTML.index("const room = m.media_kind === 'room';"):]
    assert "room ? '' : '<button class=\"pa hot\" data-pact=\"undress\"" in feed[:1500]
    assert "_her_photo(uid, ('photo', 'room') if action == 'animate' else ('photo',))" in MAIN
