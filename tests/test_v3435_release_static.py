"""V3.43.5 static pins: the owner's four-screen walkthrough.

The owner reviewed the app screen by screen (5 screenshots) and filed four
items; this release answers all of them:

1. the welcome keyboard's credits button must read the plain «Персики» —
   his screenshot showed «Добавить клубничек», a stale cached build;
2. the Картинки style picker (Аниме/Реализм/Фэнтези) leaned on emoji
   (🍑/📷/🐉) that do not read as styles — it now shows a small drawn SVG
   icon per style so the choice is visible at a glance;
3. the «пошлый режим» switch was buried in the bot chat («я, как создатель
   этого, еле нашел») — the app's own profile screen now carries a Settings
   section with the spicy toggle AND the interface language picker
   (ru/en/es/it/fr/zh/ja — «нажал кнопку, и весь интерфейс на итальянский
   переключился»);
4. Emily's figure jumped between her card and generated photos (big bust
   vs small bust) — the declared BODY IDENTITY now explicitly OVERRIDES the
   reference images instead of losing the tug-of-war to them.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PHOTO_SVC = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
UI_LANG = (ROOT / 'services' / 'ui_lang.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


def test_version_bumped():
    assert VERSION in ('3.44.4', '3.44.3', '3.43.7', '3.43.6', '3.43.5')


# ── 1. the plain «Персики» label ────────────────────────────────────────────

def test_credits_button_is_plain_peaches():
    assert "'credits': ('🍑 Персики', '🍑 Peaches')," in UI_LANG
    # the press still routes through kb_pair, so both languages match
    assert "@dp.message(F.text.in_(kb_pair('credits')))" in MAIN
    # the verb label is gone everywhere
    assert 'Добавить персиков' not in UI_LANG
    assert 'Добавить персиков' not in MAIN
    assert 'Добавить персиков' not in INDEX


# ── 2. drawn style icons in the Картинки studio ─────────────────────────────

def test_style_picker_uses_drawn_icons():
    assert "let PIC_STYLE = 'anime';" in INDEX
    assert 'const STYLE_ICONS = {' in INDEX
    # one small SVG per style — visually distinct, not interchangeable emoji
    for style in ('anime', 'realistic', 'fantasy'):
        assert f"  {style}: '<svg viewBox=\"0 0 24 24\"" in INDEX, style
    # the tiles replace the old emoji <select> and highlight the choice
    assert '<div class="styleRow" id="picStyleRow">' in INDEX
    assert "document.querySelectorAll('#picStyleRow .styleTile')" in INDEX
    assert '.styleTile.on {' in INDEX
    # the selection actually reaches the generation request
    assert 'style: PIC_STYLE,' in INDEX
    # the old emoji select is gone (with its 🍑/📷/🐉 options)
    assert '<select id="picStyle">' not in INDEX
    assert "document.getElementById('picStyle').value" not in INDEX
    assert '<option value="anime">🍑' not in INDEX
    assert '<option value="realistic">📷' not in INDEX
    assert '<option value="fantasy">🐉' not in INDEX


# ── 3. Settings section: spicy switch inside the app ────────────────────────

def test_spicy_endpoint_lives_in_the_webapp_api():
    assert 'async def _webapp_api_spicy(request: web.Request) -> web.Response:' in MAIN
    assert "app.router.add_post('/webapp/api/spicy', _webapp_api_spicy)" in MAIN
    handler = MAIN[MAIN.index('async def _webapp_api_spicy'):]
    handler = handler[:handler.index('\nasync def ', 10)]
    # Telegram-authenticated only
    assert 'validate_init_data(request.query.get(\'init_data\', \'\'))' in handler
    assert "return web.json_response({'ok': False, 'error': 'auth'}, status=401)" in handler
    # V3.37.0 → V3.165.0: the endpoint used to flip the flag and demanded
    # Premium. It now takes the value the entry card was tapped with, and the
    # only gate left is the 18+ confirmation — the money moved to the frames
    # and to the daily ceiling.
    assert "explicit_mode.set_mode(telegram_id, new)" in handler
    assert "is_adult_confirmed(telegram_id)" in handler
    assert "return web.json_response({'ok': True, 'spicy_mode': bool(result)}" in handler
    assert 'is_premium(telegram_id)' not in handler
    assert 'update_user_settings(telegram_id, spicy_mode=not current)' not in handler


def test_api_me_exposes_spicy_mode():
    # V3.165.0: the flag is read through explicit_mode (the account flag the
    # entry screen writes), and the app gets the ceiling with it.
    assert "'spicy_mode': bool(mode_on)," in WEBAPP_SVC
    assert "'explicit_left': explicit_left," in WEBAPP_SVC
    assert "'explicit_cap': explicit_cap," in WEBAPP_SVC


def test_profile_screen_carries_the_settings_section():
    assert "${esc(L.settings_title)}" in INDEX
    assert '<div class="langBox">' in INDEX
    # V3.165.0 (Задача 100): the mode row left Settings — the entry screen is
    # the only place the mode is chosen, so a second switch must not come back.
    assert 'id="rowSpicy"' not in INDEX
    assert 'id="spicyVal"' not in INDEX
    assert '${esc(L.spicy_title)}' not in INDEX
    # the entry cards post the tapped value to the endpoint and honour its
    # verdicts: the 18+ answer stays separate from a network failure.
    assert "body: JSON.stringify({ spicy: !!on })," in INDEX
    assert "if (r.status === 403) adultBlocked = true;" in INDEX
    assert "toast(L.adult_confirm_needed);" in INDEX
    assert "ME.spicy_mode = j.spicy_mode;" in INDEX
    # Premium is no longer the price of the mode
    assert "if (!ME.spicy_mode && !ME.premium) { toast(L.spicy_prem); showTab('shop'); return; }" not in INDEX


# ── 4. interface language picker: seven languages ────────────────────────────

def test_seven_interface_languages_are_wired():
    assert "const APP_LANGS = ['ru', 'en', 'es', 'it', 'fr', 'zh', 'ja', 'bn'];" in INDEX
    # the Settings pick beats the Telegram account language
    assert "localStorage.getItem('app_lang')" in INDEX
    # L_RU stays the base; everyone else merges over the English dictionary
    assert 'const L_OV = {' in INDEX
    for lang in ('es', 'it', 'fr', 'zh', 'ja'):
        assert f'  {lang}: {{' in INDEX, lang
    assert 'const L = LANG === \'ru\' ? L_RU : Object.assign({}, L_EN, (L_OV[LANG] || {}));' in INDEX
    # the bottom navigation speaks every language too
    assert 'const NAV_LABELS = {' in INDEX
    # V3.46.0: a sixth «Миссии» tab joined the roadmap (index 4), so the nav
    # arrays are six slots long in every language.
    assert "ru: ['Девушки','Чаты','Картинки','Магазин','Миссии','Партнёрка','Профиль']," in INDEX
    assert "ja: ['女の子','チャット','画像','ショップ','ミッション','パートナー','プロフィール']," in INDEX
    assert '(NAV_LABELS[LANG] || NAV_LABELS.en)[i];' in INDEX


def test_language_chips_switch_the_whole_interface():
    assert 'id="langChips"' in INDEX
    # the chips are a precomputed local fragment; codes and names esc()'d
    assert 'const LANG_NAMES = { ru:' in INDEX
    for name in ("ru: 'Русский'", "en: 'English'", "es: 'Español'", "it: 'Italiano'",
                 "fr: 'Français'", "zh: '中文'", "ja: '日本語'"):
        assert name in INDEX, name
    assert 'data-lang="${esc(code)}"' in INDEX
    assert '${esc(LANG_NAMES[code])}' in INDEX
    assert '<div class="langChips" id="langChips">${langChipsHtml}</div>' in INDEX
    # picking a chip persists the choice and reboots the UI in that language
    assert "localStorage.setItem('app_lang', ch.dataset.lang);" in INDEX
    assert 'location.reload()' in INDEX
    # every dictionary carries the Settings vocabulary
    # V3.165.0: the mode captions that used to sit here moved to the entry
    # screen, which speaks every interface language too.
    for lang in ("settings_title: 'Settings'", "settings_title: 'Настройки'",
                 "settings_title: 'Ajustes'", "settings_title: 'Impostazioni'",
                 "settings_title: 'Réglages'", "settings_title: '设置'",
                 "settings_title: '設定'", "settings_title: 'সেটিংস'"):
        assert lang in INDEX, lang
    assert "spicy_title:" not in INDEX
    assert "ms_title: 'Как общаемся сегодня?'" in INDEX
    assert "ms_btn: 'Выбрать героиню'" in INDEX
    assert "ms_title: 'How are we talking today?'" in INDEX
    assert "ms_btn: 'Choose a heroine'" in INDEX


# ── 5. the figure no longer drifts (Emily) ──────────────────────────────────

def test_body_identity_overrides_reference_images():
    # the declaration wins the tug-of-war with the canonical references
    assert "f'BODY IDENTITY: {name} has {body_spec}. This declared figure is a permanent body trait '" in PHOTO_SVC
    assert "'and OVERRIDES the reference images: even if a reference photo shows a smaller or flatter '" in PHOTO_SVC
    assert "'never flatten, reduce or enlarge the bust, never widen the waist. '" in PHOTO_SVC
