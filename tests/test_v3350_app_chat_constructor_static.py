"""V3.35.0 static checks: the Mini App becomes a full product — in-app chat
(tap a card → dialog, same pipeline/gates as the bot chat), the per-user
character constructor wizard (11 steps incl. face/breast/waist/hips, payment
through the same `constructor:<id>` payload), public personas and the blue
«Открыть приложение» menu button with a Railway PUBLIC_BASE_URL fallback."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
CCS = (ROOT / 'services' / 'custom_character_service.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_version_bumped():
    assert VERSION in ('3.42.0', '3.41.0', '3.40.0', '3.35.0', '3.36.0', '3.37.0', '3.38.0', '3.39.0')


# ── constructor steps: 11 keys in wizard order ─────────────────────────────

def test_constructor_steps_extended():
    assert "CONSTRUCTOR_STEPS: list[dict] = [" in CCS
    keys = re.findall(r"'key': '(\w+)'", CCS)
    # V3.37.0: 'style' is the new first step (realistic vs anime).
    assert keys[:12] == [
        'style', 'age', 'face', 'body', 'breast', 'waist', 'hips',
        'hair', 'eyes', 'temperament', 'profession', 'role',
    ]


def test_new_figure_steps_and_options():
    # face / breast / waist / hips — the owner's requested buttons
    assert "'key': 'face', 'title': 'Какое у неё лицо?'" in CCS
    assert "'key': 'breast', 'title': 'Какая у неё грудь?'" in CCS
    assert "'key': 'waist', 'title': 'Какая у неё талия?'" in CCS
    assert "'key': 'hips', 'title': 'Какая у неё попа?'" in CCS
    for value in ('face_oval', 'face_round', 'face_sharp', 'face_soft'):
        assert f"('{value}'," in CCS
    for value in ('breast_small', 'breast_medium', 'breast_large', 'breast_xl'):
        assert f"('{value}'," in CCS
    for value in ('waist_thin', 'waist_fit', 'waist_soft'):
        assert f"('{value}'," in CCS
    for value in ('hips_small', 'hips_round', 'hips_big', 'hips_xl'):
        assert f"('{value}'," in CCS


def test_temperament_ends_of_the_dial():
    # «пошлая общается как пошлая, скромная — скромно»
    assert "('temper_shy', 'Скромная и застенчивая'" in CCS
    assert "('temper_naughty', 'Пошлая и развратная'" in CCS


def test_temperament_style_bends_chat_voice():
    assert 'TEMPERAMENT_STYLE: dict[str, str] = {' in CCS
    shy = CCS[CCS.index("'temper_shy': ("):CCS.index("'temper_naughty': (")]
    naughty = CCS[CCS.index("'temper_naughty': ("):CCS.index('}\n', CCS.index("'temper_naughty': ("))]
    assert 'скромный и застенчивый' in shy
    assert 'откровенно пошлый' in naughty
    # wired into the persona override so both bot and app chats speak that way
    persona = CCS[CCS.index('def build_persona_context('):CCS.index('# ── DB operations')]
    assert 'style = TEMPERAMENT_STYLE.get(' in persona
    assert 'lines.append(style)' in persona


def test_prompt_key_tuples_cover_new_steps():
    avatar = CCS[CCS.index('def build_avatar_prompt('):CCS.index('# V3.35.0: the owner')]
    assert "('age', 'face', 'body', 'breast', 'waist', 'hips', 'hair', 'eyes')" in avatar
    persona = CCS[CCS.index('def build_persona_context('):CCS.index('# ── DB operations')]
    assert "('style', 'age', 'face', 'body', 'breast', 'waist', 'hips', 'hair', 'eyes', 'temperament', 'profession')" in persona
    appearance = CCS[CCS.index('def custom_appearance_descriptors('):]
    assert "('style', 'age', 'face', 'body', 'breast', 'waist', 'hips', 'hair', 'eyes')" in appearance


def test_english_labels_for_app_wizard():
    assert 'OPTION_LABELS_EN: dict[str, str] = {' in CCS
    assert 'STEP_TITLES_EN: dict[str, str] = {' in CCS
    assert "'hips': 'Her butt?'" in CCS
    assert "'temper_shy': 'Shy & modest'" in CCS
    assert "'temper_naughty': 'Naughty & dirty-minded'" in CCS


# ── webapp_service payloads ────────────────────────────────────────────────

def test_api_constructor_steps_payload():
    assert 'def api_constructor_steps(' in WEBAPP_SVC
    fn = WEBAPP_SVC[WEBAPP_SVC.index('def api_constructor_steps('):WEBAPP_SVC.index('def api_chat_history(')]
    assert 'STEP_TITLES_EN.get(step[' in fn
    assert 'OPTION_LABELS_EN.get(value, label)' in fn
    assert "{'value': value, 'label':" in fn


def test_api_chat_history_payload():
    fn = WEBAPP_SVC[WEBAPP_SVC.index('def api_chat_history('):WEBAPP_SVC.index('def api_legal(')]
    assert 'limit = max(1, min(60, int(limit or 30)))' in fn
    assert 'get_recent_messages(db_user_id, character_id, limit)' in fn
    # V3.39.0: the row now also carries media_kind/media_url, so the dict opens
    # with the same role/content/ts triple and continues onto the media fields.
    assert "{'role': m.role, 'content': m.content, 'ts': ts," in fn


def test_characters_grid_marks_custom_and_mine():
    fn = WEBAPP_SVC[WEBAPP_SVC.index('def api_characters('):WEBAPP_SVC.index('def api_invoice_products(')]
    assert "'custom': custom," in fn
    assert "'mine': custom and bool(telegram_id)" in fn
    assert 'card.character_id == custom_character_id(telegram_id)' in fn


# ── chat routes + handlers ─────────────────────────────────────────────────

def test_chat_routes_registered():
    assert "app.router.add_get('/webapp/api/chat', _webapp_api_chat_history)" in MAIN
    assert "app.router.add_post('/webapp/api/chat', _webapp_api_chat_send)" in MAIN


def test_chat_history_handler():
    handler = MAIN[MAIN.index('async def _webapp_api_chat_history('):MAIN.index('async def _webapp_api_chat_send(')]
    assert 'validate_init_data' in handler
    assert "status=401" in handler
    assert "character_id = str(request.query.get('character_id', ''))" in handler
    assert 'api_chat_history(uid, character_id, limit)' in handler


def test_chat_send_handler_reuses_bot_pipeline():
    handler = MAIN[MAIN.index('async def _webapp_api_chat_send('):MAIN.index('async def _webapp_api_constructor_options(')]
    assert 'validate_init_data' in handler
    assert "status=401" in handler
    # custom personas are public — anyone can open a dialog with her
    assert 'if is_custom_character(character_id):' in handler
    assert 'get_custom_character_by_id(character_id)' in handler
    # built-ins keep the storefront gating
    assert "card.status not in ('active', 'premium')" in handler
    assert "card.status == 'premium' and not is_premium(telegram_id)" in handler
    # same gates as the bot chat: 18+ consent and the daily free limit
    assert 'has_accepted(telegram_id)' in handler
    assert "error': 'consent'" in handler
    assert 'can_send_message(telegram_id)' in handler
    assert "error': 'limit'" in handler
    assert 'status=429' in handler
    # the exact bot pipeline — memory, relationships, persona
    assert 'answer = await anna_reply(' in handler
    assert 'character_id=character_id,' in handler
    assert "{'ok': True, 'reply': answer}" in handler


# ── constructor routes + handlers ──────────────────────────────────────────

def test_constructor_routes_registered():
    assert "app.router.add_get('/webapp/api/constructor/options', _webapp_api_constructor_options)" in MAIN
    assert "app.router.add_post('/webapp/api/constructor/draft', _webapp_api_constructor_draft)" in MAIN
    assert "app.router.add_post('/webapp/api/constructor/buy', _webapp_api_constructor_buy)" in MAIN


def test_constructor_options_handler():
    handler = MAIN[MAIN.index('async def _webapp_api_constructor_options('):MAIN.index('async def _webapp_api_constructor_draft(')]
    assert 'api_constructor_steps(request.query.get(' in handler
    assert "'stars': CONSTRUCTOR_COST_STARS," in handler
    assert "telegram_id in ADMIN_TELEGRAM_IDS" in handler


def test_constructor_draft_handler():
    handler = MAIN[MAIN.index('async def _webapp_api_constructor_draft('):MAIN.index('async def _webapp_api_constructor_buy(')]
    assert 'validate_init_data' in handler
    # one persona per user
    assert 'get_custom_character(telegram_id)' in handler
    assert "error': 'exists'" in handler
    assert 'status=409' in handler
    # every step value must be a declared option
    assert 'for step in CONSTRUCTOR_STEPS:' in handler
    assert 'value not in OPTION_LABELS' in handler
    assert "params['name'] = name" in handler
    # the draft lands in the same session store the bot wizard uses
    assert "_constructor_sessions[telegram_id] = {'params': params, 'step': len(CONSTRUCTOR_STEPS)}" in handler
    assert "name = str(body.get('name') or '').strip()[:24]" in handler


def test_constructor_buy_handler_reuses_payment_pipeline():
    handler = MAIN[MAIN.index('async def _webapp_api_constructor_buy('):MAIN.index('async def _start_web_server(')]
    assert 'validate_init_data' in handler
    assert "error': 'no_draft'" in handler
    # admins and rub-credit holders finish for free
    assert 'consume_constructor_credit(telegram_id)' in handler
    assert '_finish_constructor(telegram_id, None, telegram_id)' in handler
    # everyone else pays through the same payload the bot charges
    assert 'await bot.create_invoice_link(' in handler
    assert "payload=f'constructor:{telegram_id}'" in handler
    assert "currency='XTR'" in handler
    assert 'amount=CONSTRUCTOR_COST_STARS' in handler
    assert "{'ok': True, 'link': link, 'stars': CONSTRUCTOR_COST_STARS}" in handler


def test_finish_constructor_signature():
    sig = MAIN[MAIN.index('async def _finish_constructor('):MAIN.index('\n', MAIN.index('async def _finish_constructor('))]
    assert 'chat_id: int' in sig
    assert 'charge: str | None' in sig
    assert 'telegram_id: int | None = None' in sig


def test_successful_payment_finishes_app_constructor():
    block = MAIN[MAIN.index('async def successful_payment('):MAIN.index('async def _send_voice_note(')]
    assert '_finish_constructor(message.chat.id, charge, message.from_user.id)' in block


# ── public personas + the blue button ──────────────────────────────────────

def test_blue_menu_button_text():
    assert "text='Открыть приложение'," in MAIN


def test_public_base_url_railway_fallback():
    assert '_PUBLIC_BASE_URL_RAW = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")' in CONFIG
    assert 'RAILWAY_PUBLIC_DOMAIN' in CONFIG
    assert 'PUBLIC_BASE_URL = _PUBLIC_BASE_URL_RAW' in CONFIG


# ── frontend: chat overlay + wizard ────────────────────────────────────────

def test_chat_overlay_markup():
    assert 'id="chatview"' in INDEX
    assert 'id="chatMsgs"' in INDEX
    assert 'id="chatSend"' in INDEX
    assert 'id="chatText"' in INDEX


def test_chat_frontend_flow():
    assert 'function openCharacter(el)' in INDEX
    assert 'function openChat(c)' in INDEX
    assert 'function loadChatHistory(characterId)' in INDEX
    assert 'function sendChat()' in INDEX
    assert "fetch('/webapp/api/chat?init_data=' + encodeURIComponent(tg.initData || '') + '&character_id=' + encodeURIComponent(characterId))" in INDEX
    assert "body: JSON.stringify({ character_id: CHAT.id, text: text })," in INDEX
    # consent / limit toasts instead of silent failures
    assert "j.error === 'consent'" in INDEX
    assert "j.error === 'premium_required'" in INDEX


def test_wizard_frontend_flow():
    assert 'id="wizview"' in INDEX
    assert 'function openWizard()' in INDEX
    assert 'function renderWizStep()' in INDEX
    assert 'function submitWizard()' in INDEX
    assert 'function closeWizard()' in INDEX
    assert "fetch('/webapp/api/constructor/options'" in INDEX
    assert 'function pollCharacters()' in INDEX


def test_grid_custom_badges_and_create_card():
    assert 'c.mine ? ' in INDEX
    assert 'L.mine_badge' in INDEX
    assert 'L.made_badge' in INDEX
    assert "id='createCard'" in INDEX or 'id="createCard"' in INDEX
    assert "cc.addEventListener('click', openWizard)" in INDEX
