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
    assert VERSION in ('3.43.7', '3.43.6', '3.43.5')


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
    # same rule as the bot-side toggle:spicy — enabling needs Premium
    assert 'if not current and not is_premium(telegram_id):' in handler
    assert "return web.json_response({'ok': False, 'error': 'premium_required'}, status=403)" in handler
    # the flag actually flips
    assert 'update_user_settings(telegram_id, spicy_mode=not current)' in handler
    assert "return web.json_response({'ok': True, 'spicy_mode': not current}" in handler


def test_api_me_exposes_spicy_mode():
    assert "'spicy_mode': bool(getattr(user, 'spicy_mode', False)) if user else False," in WEBAPP_SVC


def test_profile_screen_carries_the_settings_section():
    assert 'id="rowSpicy"' in INDEX
    assert 'id="spicyVal"' in INDEX
    assert "${esc(L.settings_title)}" in INDEX
    assert "${esc(L.spicy_title)}" in INDEX
    # the row posts to the new endpoint and reacts to its verdicts
    assert "fetch('/webapp/api/spicy?init_data='" in INDEX
    assert 'if (r.status === 403) { toast(L.spicy_prem); showTab(\'shop\'); return; }' in INDEX
    assert 'ME.spicy_mode = !!j.spicy_mode;' in INDEX
    assert "toast(ME.spicy_mode ? L.spicy_toast_on : L.spicy_toast_off);" in INDEX
    # the client Premium gate matches the server rule
    assert 'if (!ME.spicy_mode && !ME.premium) { toast(L.spicy_prem); showTab(\'shop\'); return; }' in INDEX


# ── 4. interface language picker: seven languages ────────────────────────────

def test_seven_interface_languages_are_wired():
    assert "const APP_LANGS = ['ru', 'en', 'es', 'it', 'fr', 'zh', 'ja'];" in INDEX
    # the Settings pick beats the Telegram account language
    assert "localStorage.getItem('app_lang')" in INDEX
    # L_RU stays the base; everyone else merges over the English dictionary
    assert 'const L_OV = {' in INDEX
    for lang in ('es', 'it', 'fr', 'zh', 'ja'):
        assert f'  {lang}: {{' in INDEX, lang
    assert 'const L = LANG === \'ru\' ? L_RU : Object.assign({}, L_EN, (L_OV[LANG] || {}));' in INDEX
    # the bottom navigation speaks every language too
    assert 'const NAV_LABELS = {' in INDEX
    assert "ru: ['Персонажи','Чаты','Картинки','Магазин','Профиль']," in INDEX
    assert "ja: ['女の子','チャット','画像','ショップ','プロフィール']," in INDEX
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
    assert 'location.reload();' in INDEX
    # every dictionary carries the Settings vocabulary
    assert "settings_title: 'Settings', spicy_title: '🌶 Spicy mode'" in INDEX
    assert "settings_title: 'Настройки', spicy_title: '🌶 Пошлый режим'" in INDEX
    assert "spicy_title: '🌶 Modo atrevido'" in INDEX
    assert "spicy_title: '🌶 Modalità audace'" in INDEX
    assert "spicy_title: '🌶 Mode coquin'" in INDEX
    assert "spicy_title: '🌶 火辣模式'" in INDEX
    assert "spicy_title: '🌶 セクシーモード'" in INDEX


# ── 5. the figure no longer drifts (Emily) ──────────────────────────────────

def test_body_identity_overrides_reference_images():
    # the declaration wins the tug-of-war with the canonical references
    assert "f'BODY IDENTITY: {name} has {body_spec}. This declared figure is a permanent body trait '" in PHOTO_SVC
    assert "'and OVERRIDES the reference images: even if a reference photo shows a smaller or flatter '" in PHOTO_SVC
    assert "'never flatten, reduce or enlarge the bust, never widen the waist or hips. '" in PHOTO_SVC
