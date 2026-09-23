"""Static regression tests for v3.41.0: per-character voice + a leaner onboarding
funnel + the four missing app-chat feature buttons.

Owner request (garbled voice note, decoded + confirmed over two question rounds):
1. «все как Анна» — every heroine answered in the same flirty voice. The
   per-character ``personality.communication`` profile was ignored by
   ``build_system_prompt``; now it drives the style/flirt blocks (p1).
2. On the welcome/consent screen keep 18+ / terms / privacy AND add a
   «📱 Открыть приложение» web_app button (p2).
3. After confirming 18+ drop the «Отлично, теперь выбери персонажа» message +
   inline picker (character selection lives in the Mini App now); keep the
   «💖 Поддержать проект» donation appeal (p3).
4. After picking a heroine drop the «✨ Что умеет бот» text wall (p3).
5. The main menu went «скудный» — pin the legal (Условия + Privacy) row and
   funnel into the app: app / credits / paint / partner+support / legal (p4).
6. The feature buttons фото/видео/кружок/задание дня/свидания/квартира were
   missing from the app chat — add 🎬 Видео, 🏠 Квартира, 💕 Свидание and
   🎯 Задание дня right in the in-app chat (p5).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CHAR_SVC = (ROOT / 'services' / 'character_service.py').read_text(encoding='utf-8')
UI_LANG = (ROOT / 'services' / 'ui_lang.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


def test_version_bumped():
    assert VERSION in ('3.44.4', '3.44.3', '3.43.7', '3.43.6', '3.43.5', '3.43.4', '3.43.3', '3.43.2', '3.43.1', '3.43.0', '3.42.2', '3.42.1', '3.42.0', '3.41.0', '3.40.0', '3.39.0')


# ── p1. every heroine speaks in her own voice ──────────────────────────────

def test_system_prompt_uses_the_character_communication_profile():
    # the per-character «personality.communication» block now drives the prompt
    assert 'comm = p.get("communication", {}) or {}' in CHAR_SVC
    assert 'СТИЛЬ ОБЩЕНИЯ (твой личный — держись его в каждом сообщении)' in CHAR_SVC
    # the communication fields feed the style block
    assert "comm.get('tone')" in CHAR_SVC
    assert "comm.get('initiative')" in CHAR_SVC
    # the flirt block is the character's own when present, the bold template
    # only as a fallback for profiles without a communication block
    assert "if comm.get('flirting'):" in CHAR_SVC
    assert 'ФЛИРТ И ЧУВСТВЕННОСТЬ (твой персонажный стиль)' in CHAR_SVC
    # both blocks are interpolated into the final prompt
    assert '{style_block}' in CHAR_SVC
    assert '{flirt_block}' in CHAR_SVC


# ── p2. the app is reachable from the very first screen ────────────────────

def test_consent_keyboard_offers_the_app_button():
    kb = MAIN[MAIN.index('def consent_keyboard('):MAIN.index('def legal_keyboard(')]
    assert "app_url = f'{PUBLIC_BASE_URL}/webapp' if PUBLIC_BASE_URL else None" in kb
    assert "text='📱 Открыть приложение', web_app=types.WebAppInfo(url=app_url)" in kb
    assert "text='📱 Open the app', web_app=types.WebAppInfo(url=app_url)" in kb
    # the 18+ gate + terms/privacy stay
    assert "callback_data='consent:accept'" in kb
    assert "callback_data='consent:terms'" in kb
    assert "callback_data='consent:privacy'" in kb


# ── p3. leaner onboarding after consent + after character select ───────────

def _handler(src: str, signature: str) -> str:
    """Slice one top-level handler out of ``src`` — from its ``async def`` line
    up to (not including) the next top-level ``async def``/``@dp.`` definition."""
    body = src[src.index(signature):]
    end = len(body)
    for marker in ('\nasync def ', '\n@dp.'):
        idx = body.find(marker, 1)
        if idx != -1:
            end = min(end, idx)
    return body[:end]


def test_consent_accept_shows_the_main_menu_not_a_character_picker():
    handler = _handler(MAIN, 'async def consent_accept(')
    # character selection moved into the Mini App — the persistent reply
    # keyboard replaces the old inline «теперь выбери персонажа» picker
    assert 'reply_markup=main_keyboard(cq.from_user.id in ADMIN_TELEGRAM_IDS, cq.from_user.id)' in handler
    assert 'onboarding_character_keyboard()' not in handler
    # the «💖 Поддержать проект» donation appeal is kept
    assert 'donation_service.donation_appeal(lang)' in handler
    assert 'donation_service.donation_keyboard(lang)' in handler


def test_character_select_drops_the_abilities_wall():
    # the «✨ Что умеет бот» wall is no longer auto-sent after picking a heroine
    assert 'menu_line = \'The main menu is always at the bottom 👇\' if sel_lang == EN else \'Основное меню всегда внизу 👇\'' in MAIN
    assert 'await cq.message.answer(menu_line, reply_markup=main_keyboard(' in MAIN
    # abilities_text survives only as an on-demand helper, never wired to select
    assert 'def abilities_text(lang: str = RU)' in MAIN
    select = _handler(MAIN, 'async def onboarding_character_select(')
    assert 'abilities_text(' not in select


# ── p4. the main menu keeps legal + funnels into the app ───────────────────

def test_main_keyboard_rows_pin_the_legal_row():
    rows = UI_LANG[UI_LANG.index('MAIN_KB_ROWS = ['):]
    rows = rows[:rows.index('\n]')]
    assert "['app']" in rows
    assert "['credits']" in rows
    assert "['paint']" in rows
    assert "['partner']" in rows
    assert "['support', 'legal']" in rows
    # character selection is gone from the chat funnel
    assert "['characters']" not in rows
    assert "'legal': ('📜 Документы', '📜 Documents')" in UI_LANG


# ── p5. the four missing app-chat feature buttons ──────────────────────────

def test_chat_media_endpoint_gains_the_video_kind():
    block = MAIN[MAIN.index('async def _webapp_api_chat_media('):MAIN.index('async def _webapp_media(')]
    assert "if kind not in ('photo', 'circle', 'voice', 'video') or not character_id:" in block
    # a separate Premium gate keeps the circle branch (and its test) untouched
    assert "if kind == 'video' and telegram_id not in ADMIN_TELEGRAM_IDS:" in block
    assert "kind == 'circle'" in block
    assert "elif kind == 'video':" in block
    assert "'video': '🎬 отправила видео'" in block


def test_video_and_scene_helpers_exist_and_chain_the_engines():
    assert '_WEBAPP_VIDEO_PROMPT = (' in MAIN
    assert 'async def _webapp_media_video(telegram_id: int, character_id: str):' in MAIN
    assert 'async def _webapp_media_scene(telegram_id: int, character_id: str, scene: str):' in MAIN
    video = MAIN[MAIN.index('async def _webapp_media_video('):MAIN.index('async def _webapp_media_scene(')]
    # the same engine chain the bot's «Оживить фото» uses
    assert 'engines.append(animate_image)' in video
    assert 'engines.append(animate_image_replicate)' in video
    assert 'engines.append(animate_image_fal)' in video
    assert 'engines.append(animate_image_hf)' in video
    assert "record_provider(f'video/{ename}', True)" in video
    assert "return video_bytes, 'video/mp4', 'mp4'" in video


def test_feature_endpoints_and_routes_registered():
    assert 'async def _webapp_api_feature(request: web.Request)' in MAIN
    assert 'async def _webapp_api_feature_action(request: web.Request)' in MAIN
    routes = MAIN[MAIN.index('async def _start_web_server('):MAIN.index('async def main():')]
    assert "add_get('/webapp/api/feature', _webapp_api_feature)" in routes
    assert "add_post('/webapp/api/feature/action', _webapp_api_feature_action)" in routes
    # the GET renders the menus, gated by the initData HMAC; V3.43.7 added
    # the photo scene picker as the fourth kind
    feat = MAIN[MAIN.index('async def _webapp_api_feature('):MAIN.index('async def _webapp_api_feature_action(')]
    assert 'validate_init_data' in feat
    assert "if kind not in ('apartment', 'date', 'quest', 'photo'):" in feat
    assert 'apartment_service.get_available_rooms(level)' in feat
    assert 'dates_service.get_available(level)' in feat
    assert 'couple_service.daily_quest(telegram_id)' in feat


def test_feature_action_reuses_the_existing_services():
    act = MAIN[MAIN.index('async def _webapp_api_feature_action('):MAIN.index('async def _webapp_picture(')]
    assert 'has_accepted(telegram_id)' in act
    # apartment: the room reply + relationship deltas land in the shared dialog
    assert 'apartment_service.room_action_reply(room_id, action_id)' in act
    assert 'await record_user_message(telegram_id, user_name, relationship=rel_delta, intimacy=int_delta' in act
    # quest: the character-agnostic couple_service claim (+5 attention)
    assert 'couple_service.claim_daily_quest(telegram_id)' in act
    assert "status=409" in act
    # date: free/admin delivers app-native, paid returns a Stars invoice that
    # reuses the bot's existing «date:» payment + reward path
    assert 'has_free_date(telegram_id)' in act
    assert 'await _webapp_media_scene(telegram_id, character_id, date.scene)' in act
    assert "payload=f'date:{date.id}'" in act
    assert "currency='XTR'" in act


def test_paid_date_mirrors_into_the_app_history():
    # a date paid from the Mini App must also show up in the app chat history
    assert "save_message(ensure_user(telegram_id, user_name), character_id, 'assistant', f'{date.emoji} {date.text}')" in MAIN
    assert "logger.warning('date history mirror failed user=%s date=%s', telegram_id, date.id)" in MAIN


def test_frontend_has_the_four_feature_buttons_and_sheet():
    assert 'id="mediaVideo"' in INDEX
    assert 'id="featQuest"' in INDEX
    assert 'id="featDate"' in INDEX
    assert 'id="featApt"' in INDEX
    assert 'id="featview"' in INDEX
    assert 'id="featBody"' in INDEX
    # the existing photo/circle buttons stay; the crooked voice button is gone (V3.42.2)
    assert 'id="mediaPhoto"' in INDEX
    assert 'id="mediaCircle"' in INDEX
    assert 'id="mediaVoice"' not in INDEX


def test_frontend_wires_video_and_the_feature_sheet():
    assert "document.getElementById('mediaVideo').addEventListener('click', () => requestMedia('video'))" in INDEX
    assert 'async function openFeature(kind)' in INDEX
    assert 'async function featurePost(payload)' in INDEX
    assert 'function renderFeature(j)' in INDEX
    assert 'function featItemHtml(kind, it)' in INDEX
    # the app video renders as a normal (non-round) clip
    assert 'else if (m.media_kind === \'video\') body = `<video class="m" src="${esc(src)}" controls playsinline></video>`;' in INDEX
    # the invoice path reuses tg.openInvoice; the free path appends bubbles
    assert 'tg.openInvoice(j.invoice' in INDEX
    assert "featurePost({ kind: 'quest' })" in INDEX
    assert "featurePost({ kind: 'date', id: el.dataset.id })" in INDEX
    # the wait-string for video is localized in both languages
    assert "media_wait_video: 'Rendering a video — 1–3 min…'" in INDEX
    assert "media_wait_video: 'Рисую видео — 1–3 минуты…'" in INDEX
