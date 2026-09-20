"""Static regression tests for v3.39.0: the Come Closer welcome + peach rebrand.

Owner request (screenshot of @come_closer_bot /start vs our old welcome wall):
1. /start leads with a group photo banner and a short punchy caption
   («Что умеет этот бот? … ⬇️ Поехали! ⬇️»), not a ten-line feature list;
2. the returning-user welcome is compact: photo + one line + a CTA row
   (app + partner) above a TWO-per-row character picker — the old wall of
   eight full-width «· выбрать» buttons is gone;
3. the copied «клубнички 🍓» branding is replaced with our own «персики 🍑»;
4. the new character references are the glamorous v3 shoots (files on disk).
"""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
UI_LANG = (ROOT / 'services' / 'ui_lang.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
MEMORY = (ROOT / 'services' / 'memory_service.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


def test_version_bumped():
    assert VERSION in ('3.43.7', '3.43.6', '3.43.5', '3.43.4', '3.43.3', '3.43.2', '3.43.1', '3.43.0', '3.42.2', '3.42.1', '3.42.0', '3.41.0', '3.40.0', '3.39.0',)


# ── 1. photo banner leads the welcome ──────────────────────────────────────

def test_welcome_banner_asset_exists():
    banner = ROOT / 'data' / 'media' / 'welcome_banner.png'
    assert banner.exists() and banner.stat().st_size > 100_000


def test_start_sends_the_banner_photo():
    assert 'WELCOME_BANNER_PATH' in MAIN
    assert 'def _welcome_banner_file()' in MAIN
    assert 'FSInputFile(WELCOME_BANNER_PATH)' in MAIN
    # both the new-user and the returning-user welcome go out as a photo
    assert 'await message.answer_photo(banner, caption=welcome, reply_markup=consent_keyboard(lang))' in MAIN
    assert 'await message.answer_photo(banner, caption=welcome_back, reply_markup=markup)' in MAIN
    # text fallback when the asset is missing
    assert 'await message.answer(welcome, reply_markup=consent_keyboard(lang))' in MAIN


def test_welcome_caption_is_short_and_punchy():
    # Come Closer style: what the bot does in two lines, then «Поехали!»
    assert 'Что умеет этот бот?' in MAIN
    assert 'What can this bot do?' in MAIN
    assert '⬇️ Поехали! ⬇️' in MAIN
    assert '⬇️ Let’s go! ⬇️' in MAIN
    assert 'Ролевая игра с ИИ девушками' in MAIN
    # the old ten-line feature list is gone from /start
    assert '💬 живое общение с памятью и характером' not in MAIN
    assert '💬 real conversation with memory and personality' not in MAIN


def test_welcome_back_is_compact():
    assert 'девушки, чаты, картинки и магазин — в приложении 👇' in MAIN
    assert 'the girls, chats, pictures and the shop live in the app 👇' in MAIN
    # V3.43.0: the referral dump left the welcome entirely (it lives on the
    # partner screen now) — no separate ref_hint message is sent anymore.
    assert 'await message.answer(ref_hint.strip())' not in MAIN
    assert 'welcome_back + ref_hint' not in MAIN


# ── 2. compact character picker + CTA row ──────────────────────────────────

def test_character_picker_is_two_per_row():
    assert 'def _character_pick_buttons(kind: str)' in MAIN
    assert 'def _pair_rows(buttons)' in MAIN
    assert 'buttons[i:i + 2]' in MAIN
    assert 'return InlineKeyboardMarkup(inline_keyboard=_pair_rows(_character_pick_buttons(\'onboard\')))' in MAIN
    assert "rows = _pair_rows(_character_pick_buttons('view'))" in MAIN
    # the unreadable one-per-row wall with suffixes is gone
    assert '· выбрать' not in MAIN
    assert '· доступна' not in MAIN


def test_welcome_back_rows_open_app_partner_and_legal():
    # V3.42.0: the returning-user welcome is a short button list (app / partner
    # program / terms+privacy) — the nine-button character grid is gone.
    assert 'def _welcome_back_rows(lang: str)' in MAIN
    assert "callback_data='partner:open'" in MAIN
    assert '@dp.callback_query(F.data == \'partner:open\')' in MAIN
    assert 'async def partner_open(cq: types.CallbackQuery)' in MAIN
    assert 'await referral_cmd(cq.message)' in MAIN
    assert 'markup = InlineKeyboardMarkup(inline_keyboard=_welcome_back_rows(lang))' in MAIN
    assert 'rows.extend(_pair_rows(_character_pick_buttons(\'onboard\')))' not in MAIN


# ── 3. peach rebrand ───────────────────────────────────────────────────────

def test_peaches_replaced_strawberries():
    # V3.43.5: the label lost the verb — the plain «Персики» button.
    assert "'credits': ('🍑 Персики', '🍑 Peaches')," in UI_LANG
    assert '🍑 Персики' in MAIN
    assert '🍑 peaches (photo credits) are bought in the app' in MAIN
    assert 'Создать · 1 🍑' in INDEX
    assert 'Не хватает 🍑' in INDEX
    # no strawberry branding left anywhere user-facing
    assert '🍓' not in UI_LANG
    assert '🍓' not in MAIN
    assert '🍓' not in INDEX
    assert 'клубнич' not in UI_LANG
    assert 'клубнич' not in MAIN
    assert 'клубнич' not in INDEX


# ── 4. glamorous v3 references on disk ─────────────────────────────────────

def test_new_character_references_are_the_v3_shoots():
    for name in ('erika', 'sonya', 'vika', 'alisa', 'mila'):
        face = ROOT / 'data' / 'references' / name / f'00_{name}_canonical_face.png'
        look = ROOT / 'data' / 'references' / name / f'01_{name}_canonical_look.png'
        assert face.exists() and face.stat().st_size > 100_000, f'{name} face missing'
        assert look.exists() and look.stat().st_size > 100_000, f'{name} look missing'


def test_new_characters_have_curvy_figure_anchors():
    # owner: «грудь вообще доска у всех новых» — the identity anchors now
    # carry the hourglass/full-bust line and the v4 looks match it.
    for character_id in ('erika_01', 'sonya_01', 'vika_01', 'alisa_01', 'mila_01'):
        profile = json.loads((ROOT / 'data' / 'characters' / f'{character_id}.json').read_text(encoding='utf-8'))
        anchors = ' '.join(profile['visual_identity']['preserve_identity'])
        assert 'curvy hourglass figure with a full bust' in anchors, character_id


# ── 5. Come Closer character page ──────────────────────────────────────

def test_character_page_has_strip_cta_and_plot():
    assert 'def character_gallery(character_id: str)' in WEBAPP_SVC
    assert "'gallery': [" in WEBAPP_SVC
    assert "add_get('/webapp/photo/{character_id}', _webapp_photo)" in MAIN
    assert "idx = int(request.query.get('i', '0') or 0)" in MAIN
    # frontend page: strip, «Начать чат», bio, the «КАК ВЫ ПОЗНАКОМИТЕСЬ» block
    assert 'id="charview"' in INDEX
    assert 'id="charStrip"' in INDEX
    assert 'id="charStart"' in INDEX
    assert 'id="charPlot"' in INDEX
    assert 'start_chat: \'Начать чат\'' in INDEX
    assert 'plot: \'ОНА ПИШЕТ ТЕБЕ ПЕРВОЙ\'' in INDEX
    assert 'function openCharPage(el)' in INDEX
    # a card tap opens the page, the CTA opens the dialog
    assert 'el.addEventListener(\'click\', () => openCharPage(el))' in INDEX
    assert 'openChat(CHARPAGE)' in INDEX


# ── 6. in-app chat media: photos / circles / voice ────────────────────────

def test_chat_media_endpoint_and_gates():
    assert 'async def _webapp_api_chat_media(request: web.Request)' in MAIN
    assert "add_post('/webapp/api/chat/media', _webapp_api_chat_media)" in MAIN
    assert "add_get('/webapp/media/{filename}', _webapp_media)" in MAIN
    block = MAIN[MAIN.index('async def _webapp_api_chat_media('):MAIN.index('async def _webapp_media(')]
    # photo costs 1 🍑, circles are Premium + daily free slot, consent gates all
    assert 'WEBAPP_PICTURE_COST_CREDITS' in block
    assert "kind == 'circle'" in block and 'consume_premium_video_free(telegram_id)' in block
    assert 'has_accepted(telegram_id)' in block
    # the bot's own engine chains are reused
    assert 'async def _webapp_media_circle(' in MAIN
    assert 'CIRCLE_PROMPT.format(phrase=random.choice(CIRCLE_PHRASES))' in MAIN
    assert 'async def _webapp_media_voice(' in MAIN
    assert 'synthesize_bytes(clean,' in MAIN
    assert 'async def _webapp_media_photo(' in MAIN
    # V3.43.7: the app photo runs the REAL identity-locked pipeline — the
    # generate_custom_avatar shortcut (which bypassed every lock) is gone.
    assert 'generate_photo_set(telegram_id, request, character_id=character_id, frames=1)' in MAIN


def test_chat_media_persistence_and_rendering():
    assert 'def save_chat_media(telegram_id: int, data: bytes, ext: str)' in WEBAPP_SVC
    assert 'def chat_media_file_path(telegram_id: int, filename: str)' in WEBAPP_SVC
    assert 'media_kind: Mapped[str | None]' in MODELS
    assert 'media_url: Mapped[str | None]' in MODELS
    assert 'media_kind=media_kind, media_url=media_url' in MEMORY
    assert "'media_kind': getattr(m, 'media_kind', None)" in WEBAPP_SVC
    # the frontend renders all three kinds and offers the action buttons
    assert 'function requestMedia(kind, scene)' in INDEX
    assert 'id="mediaPhoto"' in INDEX and 'id="mediaCircle"' in INDEX
    # V3.42.2: the crooked voice action button was removed from the chat strip
    assert 'id="mediaVoice"' not in INDEX
    assert 'video class="circle"' in INDEX
    assert '<audio controls src=' in INDEX
    assert 'circle_limit' in INDEX


# ── 7. Персонажи: the roster / community segment switch ────────────────────

def test_characters_tab_has_segment_switch():
    # owner: «наши персонажи в первой вкладке, созданные людьми в вкладке
    # сообщество (нашу вкладку назови оригинально)» — «🍑 Персиковый сад».
    assert 'id="charSeg"' in INDEX
    assert 'id="segOfficial"' in INDEX and 'id="segCommunity"' in INDEX
    assert "seg_official: '🍑 Персиковый сад'" in INDEX
    assert "seg_official: '🍑 Peach Garden'" in INDEX
    assert "seg_community: '👥 Сообщество'" in INDEX
    assert "seg_community: '👥 Community'" in INDEX
    # the switch filters the cached grid and moves create-card to community
    assert "let CHAR_SEG = 'official'" in INDEX
    assert 'CHAR_SEG = btn.dataset.seg' in INDEX
    assert "list.filter(c => (CHAR_SEG === 'official' ? !c.custom : !!c.custom))" in INDEX
    assert "const createCard = CHAR_SEG === 'official' ? ''" in INDEX


# ── 8. studio reliability ────────────────────────────────────────────────

def test_studio_has_two_engines_and_admin_reason():
    # a single provider outage no longer kills the «Картинки» tab
    assert 'async def _seedream_t2i(prompt: str)' in PHOTO
    assert 'studio Seedream t2i failed; falling back to Gemini' in PHOTO
    gen = MAIN[MAIN.index('async def _webapp_api_picture_generate('):MAIN.index('async def _webapp_media_photo(')]
    assert "'reason': reason" in gen
    assert 'telegram_id in ADMIN_TELEGRAM_IDS' in gen
    assert 'toast(j.reason || L.pic_gen_fail)' in INDEX
