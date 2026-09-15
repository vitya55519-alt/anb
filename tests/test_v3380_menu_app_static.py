"""Static regression tests for v3.38.0: the Come Closer funnel + character pack.

Owner request (benchmarking @come_closer_bot screenshots):
1. the bot's main menu funnels users into the Mini App — reply keyboard rows
   📱 Открыть приложение / 🍓 Добавить клубничек + 🖼 Создать картинку /
   💰 Партнёрка + 👥 Поддержка, with the actions living inside the Mini App;
2. five new characters incl. the requested «30+» women (мать друга и др.),
   each with a photorealistic canonical face/look reference and a cinematic
   scenario hook under the card (exactly like the screenshots);
3. the Mini App itself: 5 bottom tabs (Персонажи/Чаты/Картинки/Магазин/
   Профиль), a «Картинки» studio (prompt/style/format, 1 🍓 credit, charged
   only after a successful render) and a Чаты tab with last-message previews.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
UI_LANG = (ROOT / 'services' / 'ui_lang.py').read_text(encoding='utf-8')
CARDS = (ROOT / 'services' / 'character_card_service.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()

NEW_CHARACTERS = ('erika_01', 'sonya_01', 'vika_01', 'alisa_01', 'mila_01')


def test_version_bumped():
    assert VERSION in ('3.38.0',)


# ── 1. main menu funnel ────────────────────────────────────────────────────

def test_main_menu_rows_funnel_into_miniapp():
    # exact label pairs from the owner's screenshot
    for key, label in (
        ('app', "'app': ('📱 Открыть приложение', '📱 Open the app'),"),
        ('credits', "'credits': ('🍓 Добавить клубничек', '🍓 Add credits'),"),
        ('paint', "'paint': ('🖼 Создать картинку', '🖼 Create a picture'),"),
        ('partner', "'partner': ('💰 Партнёрка', '💰 Partner program'),"),
        ('support', "'support': ('👥 Поддержка', '👥 Support'),"),
    ):
        assert label in UI_LANG, f'missing label: {key}'
    rows = UI_LANG[UI_LANG.index('MAIN_KB_ROWS = ['):UI_LANG.index('LEVEL_NAMES_EN')]
    assert "['app']," in rows
    assert "['credits', 'paint']," in rows
    assert "['partner', 'support']," in rows


def test_menu_buttons_reply_with_webapp_entry():
    # reply keyboards cannot carry URLs — every new button answers with an
    # inline web_app button (or the PUBLIC_BASE_URL setup hint).
    assert 'def _app_entry_markup(lang' in MAIN
    assert 'async def _send_app_entry(message' in MAIN
    for handler in ('async def app_button(', 'async def credits_button(',
                    'async def paint_button('):
        assert handler in MAIN, f'missing handler: {handler}'
    block = MAIN[MAIN.index('async def app_button('):MAIN.index('async def support_button(')]
    assert '_send_app_entry(' in block
    assert "kb_pair('app')" in MAIN
    assert "kb_pair('credits')" in MAIN
    assert "kb_pair('paint')" in MAIN


def test_support_button_is_a_ticket_flow():
    # V3.38.0: «👥 Поддержка» arms a pending state; the next plain text goes
    # to the admins, not to the character.
    assert '_support_pending = dialog_store.DialogStore(' in MAIN
    assert '_support_pending[message.from_user.id] = _time.time()' in MAIN
    assert 'async def _deliver_support_message(' in MAIN
    assert 'message.from_user.id in _support_pending' in MAIN
    assert '_deliver_support_message(message, message.text' in MAIN
    assert "del _support_pending[message.from_user.id]" in MAIN


# ── 2. new character pack ──────────────────────────────────────────────────

def test_new_character_profiles_exist_and_are_adults():
    for character_id in NEW_CHARACTERS:
        path = ROOT / 'data' / 'characters' / f'{character_id}.json'
        profile = json.loads(path.read_text(encoding='utf-8'))
        assert profile['id'] == character_id
        assert profile['is_adult'] is True
        assert profile['status'] == 'active'
        boundaries = profile['boundaries']
        assert boundaries['adult_only'] is True
        assert boundaries['no_graphic_sexual_content'] is True
        assert boundaries['no_nudity_generation'] is True
        visual = profile['visual_identity']
        assert visual['status'] == 'active'
        assert len(visual['preserve_identity']) >= 5
        # the photorealistic canonical references actually exist on disk
        folder = ROOT / visual['reference_folder']
        for asset in visual['reference_assets']:
            assert (folder / asset).exists(), f'{character_id}: missing {asset}'


def test_new_characters_registered_everywhere():
    for character_id in NEW_CHARACTERS:
        assert f'"{character_id}": {{' in CARDS, f'{character_id} not in DEFAULT_CARDS'
        assert f'"{character_id}": (' in CARDS, f'{character_id} not in SCENARIO_HOOKS'
        assert f"'{character_id}': ('references'," in WEBAPP_SVC, \
            f'{character_id} not in _FACE_REFERENCES'
    # the requested archetypes: мать друга 38, начальница 35, учительница 27,
    # соседка 30, подруга детства 22
    for character_id, age in (('erika_01', 38), ('vika_01', 35),
                              ('alisa_01', 27), ('mila_01', 30), ('sonya_01', 22)):
        card = CARDS[CARDS.index(f'"{character_id}": {{'):]
        card = card[:card.index('},')]
        assert f'"age": {age}' in card


def test_storefront_cards_carry_the_hook():
    assert "'hook': get_scenario_hook(card.character_id) or ''" in WEBAPP_SVC
    assert 'const hookLine = c.hook' in INDEX
    assert 'class="hook"' in INDEX


# ── 3. Mini App: chats + picture studio ────────────────────────────────────

def test_chats_tab_backend_and_frontend():
    assert 'def api_chat_list(db_user_id' in WEBAPP_SVC
    assert 'async def _webapp_api_chats(' in MAIN
    assert "add_get('/webapp/api/chats', _webapp_api_chats)" in MAIN
    assert 'function renderChats(list)' in INDEX
    assert 'async function loadChats()' in INDEX
    assert "fetch('/webapp/api/chats?init_data='" in INDEX
    # opens the shared in-app chat view
    assert 'openChat(' in INDEX


def test_picture_studio_guards_and_charge_after_success():
    # backend guards in the service
    assert 'WEBAPP_PICTURE_COST_CREDITS = 1' in WEBAPP_SVC
    assert 'def picture_prompt_allowed(prompt' in WEBAPP_SVC
    assert 'def picture_final_prompt(' in WEBAPP_SVC
    assert 'PICTURE_PROMPT_SUFFIX' in WEBAPP_SVC
    assert 'def save_picture(' in WEBAPP_SVC
    assert 'def api_picture_list(' in WEBAPP_SVC
    assert 'def picture_file_path(' in WEBAPP_SVC
    # endpoint: auth -> prompt length -> blocked filter -> consent -> credits
    # -> generate -> save -> ONLY THEN consume the credit
    assert 'async def _webapp_api_picture_generate(' in MAIN
    assert "add_post('/webapp/api/picture', _webapp_api_picture_generate)" in MAIN
    gen = MAIN[MAIN.index('async def _webapp_api_picture_generate('):]
    gen = gen[:gen.index('async def _webapp_picture(')]
    assert "status=402" in gen and 'WEBAPP_PICTURE_COST_CREDITS' in gen
    assert "status=403" in gen and 'has_accepted(' in gen
    assert 'picture_prompt_allowed(prompt)' in gen
    assert 'picture_final_prompt(prompt, style, fmt)' in gen
    assert 'generate_custom_avatar(final_prompt, None)' in gen
    assert 'save_picture(telegram_id, filename, prompt)' in gen
    assert 'consume_photo_credit(telegram_id)' in gen
    assert gen.index('save_picture(') < gen.index('consume_photo_credit(')
    # serving is owner-scoped with an unguessable server-generated name
    assert "add_get('/webapp/picture/{filename}', _webapp_picture)" in MAIN
    assert 'picture_file_path(telegram_id' in MAIN


def test_picture_studio_frontend():
    assert 'id="tab-pictures"' in INDEX
    assert 'function renderStudio()' in INDEX
    assert 'async function generatePicture()' in INDEX
    assert 'async function loadPictures()' in INDEX
    assert "fetch('/webapp/api/picture?init_data='" in INDEX
    assert 'my_chars' in INDEX and 'create_char' in INDEX
