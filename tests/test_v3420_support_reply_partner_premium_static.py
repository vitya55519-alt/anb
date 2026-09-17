"""Static regression tests for v3.42.0: support replies, a lean welcome
keyboard, the renamed partner program and the Come Closer-style tariff card.

Owner request (garbled voice note + 6 screenshots, decoded + confirmed over
one question round):
1. Photo 2 — a user wrote to support and the owner had NO way to answer
   («я не могу ему ответить»). Answering is now a reply to the ticket message
   in the owner's chat; the text is routed to that user (p1).
2. Photos 5–6 — the welcome/start screen showed a nine-button character grid.
   Drop it; keep a few buttons: open the app, the partner program, terms and
   privacy (p2).
3. Photo 4 — rename «Партнёрка» → «Партнёрская программа», make it a big
   full-width button everywhere (menu + welcome) and cut 40% → 30% (p3).
4. Photo 3 — the premium pitch must look like the benchmarked tariff card:
   a radio list with the weekly plan, the monthly plan, its per-week price
   and a savings badge (p4, confirmed: in the BOT tariff message).
5. Photo 1 — the blue «Открыть приложение» menu button must stay (p5).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CFG = (ROOT / 'config.py').read_text(encoding='utf-8')
UI_LANG = (ROOT / 'services' / 'ui_lang.py').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


def test_version_bumped():
    assert VERSION in ('3.43.1', '3.43.0', '3.42.2', '3.42.1', '3.42.0', '3.41.0', '3.40.0')


# ── p1. the owner can finally answer a support ticket ─────────────────────

def test_admin_reply_to_ticket_is_delivered_to_the_user():
    # replying to a «🛟 Support user: …» ticket in the owner's chat routes the
    # answer to that user — before v3.42.0 tickets were write-only.
    assert 'async def _deliver_admin_reply(message: types.Message, user_id: int) -> None:' in MAIN
    deliver = MAIN[MAIN.index('async def _deliver_admin_reply('):]
    deliver = deliver[:deliver.index('\nasync def ', 10)] if '\nasync def ' in deliver[10:] else deliver
    assert "prefix = '💬 support reply:\\n\\n' if lang == EN else '💬 ответ поддержки:\\n\\n'" in deliver
    assert 'await bot.send_message(user_id, prefix + text)' in deliver
    # an undeliverable answer tells the owner instead of failing silently
    assert 'не удалось доставить ответ' in deliver
    assert "f'↩️ отправлено пользователю {user_id} ✔'" in deliver


def test_text_message_intercepts_admin_ticket_replies():
    # the catch-all text handler recognizes a reply to a support/payment-support
    # ticket from an admin and extracts the user id from the ticket header.
    assert "if replied_text.startswith(('🛟 Support', '💳 Payment support')):" in MAIN
    assert "ticket = re.search(r'^user: (\\d+)', replied_text, re.M)" in MAIN
    assert 'await _deliver_admin_reply(message, int(ticket.group(1)))' in MAIN
    # only admins can trigger the routing
    branch = MAIN[MAIN.index("if replied_text.startswith(('🛟 Support'") - 300:]
    assert 'message.from_user.id in ADMIN_TELEGRAM_IDS' in branch


# ── p2. welcome-back: a short button list, not a character wall ───────────

def test_welcome_back_rows_are_app_partner_and_legal():
    assert 'def _welcome_back_rows(lang: str):' in MAIN
    rows = MAIN[MAIN.index('def _welcome_back_rows(lang: str):'):]
    rows = rows[:rows.index('\ndef ', 10)]
    # the open-app web_app tile (only when PUBLIC_BASE_URL is set)
    assert "web_app=types.WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp')" in rows
    assert "'📱 Открыть приложение' if lang == RU else '📱 Open the app'" in rows
    # the full-width partner button and the terms/privacy row
    assert "text=kb_label('partner', lang), callback_data='partner:open'" in rows
    assert "callback_data='legal:terms'" in rows
    assert "callback_data='legal:privacy'" in rows
    # no character grid in this keyboard
    assert '_character_pick_buttons' not in rows


def test_welcome_back_message_uses_the_new_rows_and_caption():
    assert 'markup = InlineKeyboardMarkup(inline_keyboard=_welcome_back_rows(lang))' in MAIN
    assert 'f\'с возвращением, {name} 🙂 девушки, чаты, картинки и магазин — в приложении 👇\'' in MAIN
    assert 'f\'welcome back, {name} 🙂 the girls, chats, pictures and the shop live in the app 👇\'' in MAIN
    # the nine-button character grid no longer feeds the welcome screen
    assert "rows.extend(_pair_rows(_character_pick_buttons('onboard')))" not in MAIN


# ── p3. «Партнёрская программа»: renamed, full-width, 30% ─────────────────

def test_partner_is_renamed_and_gets_its_own_row():
    assert "'partner': ('💰 Партнёрская программа', '💰 Partner program')," in UI_LANG
    assert "'💰 Партнёрка'" not in UI_LANG
    rows = UI_LANG[UI_LANG.index('MAIN_KB_ROWS = ['):UI_LANG.index('LEVEL_NAMES_EN')]
    assert "['partner']," in rows
    assert "['support', 'legal']," in rows
    assert "['partner', 'support']," not in rows


def test_partner_handler_keeps_the_legacy_label_and_the_command_says_30():
    # cached reply keyboards with the old «💰 Партнёрка» label still resolve
    assert "@dp.message(F.text.in_(kb_pair('partner') + ('💰 Партнёрка',)))" in MAIN
    assert "types.BotCommand(command='partner', description='💰 Партнёрская программа — 30% с покупок друзей')," in MAIN


def test_referral_commission_default_is_thirty_percent():
    assert 'REFERRAL_COMMISSION_PCT = float(os.getenv("REFERRAL_COMMISSION_PCT", "30"))' in CFG
    assert '"40"' not in CFG[CFG.index('REFERRAL_COMMISSION_PCT') - 200:CFG.index('REFERRAL_COMMISSION_PCT') + 200]


# ── p4. the premium pitch is a Come Closer-style tariff card ──────────────

def test_premium_tariff_card_layout():
    assert 'def _premium_tariff_lines(lang: str) -> list[str]:' in MAIN
    card = MAIN[MAIN.index('def _premium_tariff_lines(lang: str) -> list[str]:'):]
    card = card[:card.index('\ndef ', 10)]
    # radio list: weekly plan, then the monthly plan with a savings badge
    assert "'⭐ Тарифы:'" in card and "'⭐ Plans:'" in card
    assert "f'○  1 неделя — {PREMIUM_WEEKLY_STARS} Stars{wk_fiat}'" in card
    assert "f'●  1 месяц — {PREMIUM_MONTHLY_STARS} Stars{mo_fiat}{badge}'" in card
    # the monthly plan shows its per-week price and the struck «instead of» total
    assert "{month_pw} {unit} в неделю{strike}" in card
    assert "{month_pw} {unit} per week{strike}" in card
    assert 'save = max(0, round((1 - month_full / was) * 100))' in card
    # rub prices take over when FreeKassa is enabled — V3.43.0: the quarter
    # plan joined the trio, so all three totals come from the kassa constants
    assert "week_full, month_full, quarter_full = FREEKASSA_PREMIUM_WEEKLY_PRICE_RUB, FREEKASSA_PREMIUM_PRICE_RUB, FREEKASSA_PREMIUM_QUARTERLY_PRICE_RUB" in card


def test_premium_pitch_embeds_the_tariff_card():
    pitch = MAIN[MAIN.index('def premium_pitch_text(telegram_id: int) -> str:'):]
    pitch = pitch[:pitch.index('\ndef ', 10)]
    assert '_premium_tariff_lines(lang)' in pitch
    assert 'Разовый платёж, без автопродления.' in pitch
    assert 'One-time payment, no auto-renewal.' in pitch
    # the old one-line «тарифы: неделя — …» bullet is gone
    assert "f'• тарифы: неделя — {PREMIUM_WEEKLY_STARS} Stars" not in MAIN


# ── p5. the blue «Открыть приложение» menu button stays ───────────────────

def test_webapp_menu_button_is_still_installed_on_startup():
    assert 'await bot.set_chat_menu_button(types.MenuButtonWebApp(' in MAIN
    assert "text='Открыть приложение'," in MAIN
    assert "web_app=types.WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp')," in MAIN
    # and the v3.33.1 read-back verification is intact
    assert 'current = await bot.get_chat_menu_button()' in MAIN
