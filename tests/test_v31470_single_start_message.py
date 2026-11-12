"""V3.147.0 — owner ТЗ for the start screen, 12 Nov 2026.

1. The start is ONE message: after «Мне 18+» the bot used to fire four bubbles
   (pinned menu, the «закрепил главное меню» service line, the bonus text, the
   picker). Now bonuses, the choice and the app live in a single bubble.
2. No programmatic pinning anywhere: persistent access to the app, the peach
   balance and the partner program is the native Telegram menu button plus the
   reply keyboard that rides in behind her selfie.
3. Tapping a girl name speaks instantly: her first proactive message with the
   photo, no extra system greetings in between.
"""
import re
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
HYG = (ROOT / 'services' / 'chat_hygiene.py').read_text(encoding='utf-8')
UI = (ROOT / 'services' / 'ui_lang.py').read_text(encoding='utf-8')
PORTRAIT = ROOT / 'data' / 'media' / 'welcome_portrait.jpg'

CONSENT = MAIN[MAIN.index("async def consent_accept("):MAIN.index('# V3.98.0: the first-minute choice')]
SELFIE = MAIN[MAIN.index('async def _send_welcome_selfie('):
              MAIN.index('async def _send_welcome_selfie(') + 4000]


def _handler(source, marker):
    start = source.index(marker)
    return source[start:source.index('\n\n\n', start)]


# ── 1. one merged start message ────────────────────────────────────────────
def test_consent_accept_sends_exactly_one_message():
    handler = _handler(MAIN, 'async def consent_accept(')
    assert handler.count('cq.message.answer(') == 1
    assert 'reply_markup=_start_keyboard(flow_lang)' in handler
    assert "'start_pick'" in handler and "'start_pick_plain'" in handler
    # the banner is deleted instead of turning into a service bubble
    assert 'await cq.message.delete()' in handler
    assert 'cq.answer(' in handler
    # four bubbles used to stack here: no pinned menu, no second menu bubble
    assert '_send_pinned_menu' not in handler
    assert 'reply_markup=main_keyboard(' not in handler


def test_the_welcome_text_is_bonuses_choice_and_app_in_one_line():
    ru = re.search(r"'start_pick': '(.*?)',\n", UI).group(1)
    assert ru.startswith('🎁')
    assert '{amount}' in ru
    assert 'С кем хочешь познакомиться?' in ru
    assert 'Выбирай ту, что нравится' in ru
    assert 'в приложении' in ru
    assert ru.endswith('👇')


# ── 2. nothing is pinned, the menu is native ───────────────────────────────
def test_no_programmatic_pinning_survives():
    assert 'pin_chat_message' not in MAIN
    assert 'unpin_all_chat_messages' not in MAIN
    assert 'pin_chat_message' not in HYG
    assert 'def pin_menu(' not in HYG
    assert 'def forget_screen(' not in HYG
    # «бот закрепил(а) главное меню» was the visual garbage the owner asked to cut;
    # it may only survive in the comments that explain why it is gone.
    live = [ln for ln in MAIN.splitlines() if 'закрепил' in ln and not ln.strip().startswith('#')]
    assert live == []


def test_the_selfie_carries_the_reply_keyboard():
    # persistent access without a fourth bubble: the keyboard comes in on her photo
    assert 'reply_markup=main_keyboard(' in SELFIE
    assert SELFIE.count('bot.send_photo(') == 1


# ── 3. the picker IS the start keyboard: names, then one wide app row ──────
def test_start_keyboard_is_girls_then_one_wide_app_row():
    builder = _handler(MAIN, 'def _start_keyboard(')
    assert '_picker_rows(lang)' in builder
    assert "callback_data=f'pickgirl:{cid}'" in MAIN
    assert "web_app=types.WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp')" in builder
    assert "'📱 Открыть приложение' if lang != EN else '📱 Open the app'" in builder
    # one row, appended last, wider than any single name button
    assert builder.count('rows.append([') == 1


def test_the_standalone_picker_message_is_gone():
    assert 'async def _send_girl_picker(' not in MAIN
    assert '_send_girl_picker(' not in MAIN


# ── the defect: the animated promo showed two girls and three arms ─────────
def test_the_start_media_leads_with_one_clean_portrait():
    chooser = _handler(MAIN, 'def _welcome_banner_file(')
    assert chooser.index('WELCOME_PORTRAIT_PATH.exists()') < chooser.index('WELCOME_BANNER_GIF_PATH.exists()')
    assert "WELCOME_PORTRAIT_PATH = Path(__file__).resolve().parent / 'data' / 'media' / 'welcome_portrait.jpg'" in MAIN


def test_the_portrait_is_a_real_single_person_image():
    assert PORTRAIT.exists()
    with Image.open(PORTRAIT) as im:
        assert im.format == 'JPEG'
        assert im.width < im.height          # portrait crop, not a group banner
        assert im.width >= 480 and im.height >= 640


# ── 4. tap a name → she speaks at once ─────────────────────────────────────
def test_tapping_a_name_sends_her_hello_immediately():
    handler = _handler(MAIN, "@dp.callback_query(F.data.startswith('pickgirl:'))")
    assert 'await cq.answer()' in handler
    assert 'await cq.message.delete()' in handler
    assert 'await _deliver_first_hello(' in handler
    # instant: no timer, no menu bubble and no service line between tap and hello
    assert 'asyncio.sleep' not in handler
    assert 'pin' not in handler
    hello = _handler(MAIN, 'async def _deliver_first_hello(')
    assert 'await bot.send_message(chat_id, greeting, reply_markup=hello_kb)' in hello
    assert '_send_welcome_selfie(' in hello


def test_only_the_fallback_waits_two_minutes():
    timer = _handler(MAIN, 'async def _first_hello_fallback(')
    assert 'await asyncio.sleep(120)' in timer
    assert MAIN.count('asyncio.sleep(120)') == 1
